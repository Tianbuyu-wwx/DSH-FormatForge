// services/notify.mjs
//
// FormatForge inbox notifications — inject a LIGHTWEIGHT notice into every live
// dsh session when an inbox file has been forged.
//
// Design guardrails (learned from hermes-link v0.2.1 rollback):
//   - metadata + result path only, NEVER full content (cross-project context pollution)
//   - user/message shape per dsh-session assertMessageEventShape:
//       { id, role:'user', content:[{type:'text',text}], source:{kind:'user'} }
//   - surfaceOp is the STRING 'append'
//   - FF_INBOX_NOTIFY=false disables everything
//   - JS-H5: 注入文本里的**不可信字段**（文件名、错误文本、路径）先净化——
//     CR/LF/控制字符能把一行元数据变成一段伪造的多行 user 消息（提示注入载体）

import { homedir } from 'node:os'

const HOME_PREFIX = homedir()
const MAX_NOTICE_CHARS = 1000

/**
 * JS-H5: 不可信字段净化——剥离 C0/C1 控制字符（含 CR/LF）、折叠空白、限长。
 * 通知是以 role:'user' 注入**活的会话**的，任何能写收件箱的进程都能影响文件名。
 *
 * T3-4/audit：U+2028 LINE SEPARATOR / U+2029 PARAGRAPH SEPARATOR 也必须算进来。
 * 它们是**合法的 NTFS 文件名字符**，既不在 C0 也不在 C1，却在大量渲染器和
 * 分词器里就是换行 —— 一个带 U+2028 的文件名能原样穿过这里，把 JS-H5 要堵的
 * 「多行伪造 user 消息」载体重新带进注入文本。Zl/Zp 两个分类只有这两个码位，
 * NEL(U+0085)/VT/FF 已经落在 C0/C1 区间里。
 */
function sanitizeText(value, max = 200) {
  return String(value ?? '')
    .replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]+/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim()
    .slice(0, max)
}

/** 审计 M（notify）：绝对路径的家目录前缀（含用户名）不进会话记录 → `~`。 */
function redactPath(value) {
  const s = sanitizeText(value, 400)
  if (!s) return ''
  const esc = HOME_PREFIX.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  return s.replace(new RegExp(`^${esc}`, 'i'), '~')
}

/** 注入点兜底：只放行通知自身使用的 `\n`，其余控制字符（含 T3-4 的 U+2028/9）
 *  一律剥掉，并限长。 */
function hardenForSession(text) {
  return String(text ?? '')
    .replace(/\r/g, '')
    .replace(/[\u0000-\u0009\u000b-\u001f\u007f-\u009f\u2028\u2029]/g, ' ')
    .slice(0, MAX_NOTICE_CHARS + 200)
}

/** 整条通知硬上限（元数据 + 路径本来很短，这是兜底）。 */
function capNotice(text) {
  return text.length <= MAX_NOTICE_CHARS ? text : `${text.slice(0, MAX_NOTICE_CHARS)}…（通知已截断）`
}

export function makeNotifier({ log = () => {} } = {}) {
  const enabled = process.env.FF_INBOX_NOTIFY !== 'false'

  /**
   * Broadcast a one-line notice to all live sessions.
   * @param {object} ctx cordis ctx (needs ctx.sessions & ctx.agents)
   * @param {string} text
   */
  function broadcast(ctx, text) {
    if (!enabled) {
      log('[ff-notify] disabled (FF_INBOX_NOTIFY=false), skip')
      return
    }
    if (!ctx || !ctx.sessions || !ctx.agents) {
      log('[ff-notify] ctx.sessions/agents unavailable, skip')
      return
    }
    let sent = 0
    let agents = []
    try {
      // ctx.agents may be a Map-like or have list()/values()
      if (typeof ctx.agents.list === 'function') agents = ctx.agents.list()
      else if (typeof ctx.agents.values === 'function') [...ctx.agents.values()].forEach((a) => agents.push(a))
      else if (typeof ctx.agents.forEach === 'function') ctx.agents.forEach((a) => agents.push(a))
      else if (typeof ctx.agents.get === 'function') agents = []
    } catch (e) {
      log(`[ff-notify] enumerate agents failed: ${e.message}`)
      return
    }

    const ts = Date.now()
    for (const agent of agents) {
      const id = typeof agent === 'string' ? agent : agent?.id
      if (!id) continue
      try {
        const session = ctx.sessions.get(id)
        if (!session || typeof session.append !== 'function') continue
        session.append(
          'user/message',
          {
            id: `ff-inbox-${ts}-${Math.random().toString(36).slice(2, 8)}`,
            role: 'user',
            content: [{ type: 'text', text: hardenForSession(text) }],
            source: { kind: 'user' },
          },
          { surfaceOp: 'append' },
        )
        sent++
      } catch (e) {
        log(`[ff-notify] append to ${id} failed: ${e.message}`)
      }
    }
    if (sent > 0) log(`[ff-notify] notice delivered to ${sent} session(s)`)
    else log('[ff-notify] no live session to notify')
  }

  /** Build the standard one-liner for a finished conversion. */
  function buildNotice(result) {
    // v0.14.0/B-P1-3: retention 清理通知降噪——只 log 不广播
    // 原因：retention 每 7 天 / 容量阈值触发一次清理（FF_INBOX_TTL_DAYS / FF_INBOX_MAX_MB），
    // 广播会惊扰所有 live session；保留 log 让运维可见，避免用户被打扰。
    if (result.retention) {
      log(`[ff-notify] retention cleanup: ${result.count} file(s) removed (silent)`)
      return ''
    }
    if (result.ok) {
      const file = sanitizeText(result.file, 120)
      const parser = sanitizeText(result.parser, 40) || '?'
      const confidence = typeof result.confidence === 'number' ? result.confidence : '?'
      const enh = result.enhanceReason ? `；⚠ enhance=${sanitizeText(result.enhanceReason, 120)}` : ''
      const rid = sanitizeText(result.resultId, 80)
      const idLine = rid ? `\n- 结果 id：${rid}（用 ff_result {id:"${rid}"} 直接取回）` : ''
      return capNotice(
        `[FormatForge] 收件箱文件已锻好：${file} ` +
        `(parser=${parser}, confidence=${confidence}${enh})。\n` +
        `结果文件：\n- 完整协议 JSON：${redactPath(result.jsonPath)}\n- 可读内容：${redactPath(result.mdPath)}${idLine}\n` +
        `用户接下来很可能基于该文件提问——如需原文请用 ff_translate（路径见上）或直接读取 .ff.md。`,
      )
    }
    return capNotice(
      `[FormatForge] 收件箱文件转换失败：${sanitizeText(result.file, 120)}\n` +
      `原因 [${sanitizeText(result.kind, 40)}]: ${sanitizeText(result.message, 300)}\n` +
      `详情见同目录 .ff.error.txt；修正后重新拖入即可重试。`,
    )
  }

  return { broadcast, buildNotice, get enabled() { return enabled } }
}
