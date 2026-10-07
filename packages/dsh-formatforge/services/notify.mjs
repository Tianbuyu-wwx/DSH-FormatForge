// services/notify.mjs
//
// FormatForge inbox notifications — OPT-IN, OFF BY DEFAULT.
//
// Why off by default (v2.0.1)
// --------------------------
// The host has no ephemeral model-visible channel: every surface-eligible
// event is persisted in the session log. A notification therefore has to be
// appended as a `user/message`, which means it
//   1. becomes a PERMANENT transcript entry — re-sent to the model on every
//      later turn and re-rendered in the UI (the "it shows up again" noise),
//   2. is attributed to the USER (role/source = user), so the transcript
//      claims the person said something they never typed,
//   3. reaches only sessions that happen to hold a LIVE agent at that instant
//      (`ctx.agents.list()`), so a file dropped while the user is working in
//      another conversation — or while that conversation is idle — is never
//      announced anywhere.
//
// The inbox is a shared directory, so the fix is to make discovery
// conversation-independent and pull-based: `ff_result {list:true}` works from
// ANY conversation at ANY time (see SKILL.md). Set `FF_INBOX_NOTIFY=true` to
// opt back into the push notice.
//
// When enabled, the notice is a single line and is de-duplicated per result id,
// so one file can never be announced twice to the same session.
//
// Design guardrails (learned from hermes-link v0.2.1 rollback):
//   - metadata + result path only, NEVER full content (cross-project context pollution)
//   - user/message shape per dsh-session assertMessageEventShape:
//       { id, role:'user', content:[{type:'text',text}], source:{kind:'user'} }
//   - surfaceOp is the STRING 'append'
//   - FF_INBOX_NOTIFY=false disables everything
//   - JS-H5 / T3-4: 注入文本里的**不可信字段**（文件名、错误文本）先净化——
//     CR/LF/控制字符（含 U+2028/U+2029）能把一行元数据变成一段伪造的多行
//     user 消息（提示注入载体）

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

/** 整条通知硬上限（元数据本来很短，这是兜底）。 */
function capNotice(text) {
  return text.length <= MAX_NOTICE_CHARS ? text : `${text.slice(0, MAX_NOTICE_CHARS)}…（通知已截断）`
}

export function makeNotifier({ log = () => {} } = {}) {
  const enabled = process.env.FF_INBOX_NOTIFY === 'true'
  /** result ids already announced — one file is never announced twice. */
  const announced = new Set()

  /**
   * Broadcast a one-line notice to all live sessions.
   * @param {object} ctx cordis ctx (needs ctx.sessions & ctx.agents)
   * @param {string} text
   * @param {string} [resultId] de-duplication key — the same file is announced at most once
   */
  function broadcast(ctx, text, resultId) {
    if (!enabled) {
      // Default path: nothing is pushed into any transcript. The file is
      // discoverable from every conversation via `ff_result {list:true}`.
      log('[ff-notify] push disabled (set FF_INBOX_NOTIFY=true to opt in), skip')
      return
    }
    if (!text) return
    if (resultId) {
      if (announced.has(resultId)) {
        log(`[ff-notify] already announced ${resultId}, skip`)
        return
      }
      announced.add(resultId)
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
            content: [{ type: 'text', text: capNotice(sanitizeText(text, MAX_NOTICE_CHARS)) }],
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

  /**
   * Build the ONE-LINE notice for a finished conversion.
   *
   * Deliberately short: this text lands in the session transcript permanently,
   * so every extra line is re-sent to the model on every later turn. Paths and
   * the "what to do next" advice live in SKILL.md, not here.
   */
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
      const enh = result.enhanceReason ? ` enhance=${sanitizeText(result.enhanceReason, 120)}` : ''
      const id = result.resultId ? ` id=${sanitizeText(result.resultId, 80)}` : ''
      return capNotice(`[FormatForge] ${file} 已锻好 (parser=${parser}, confidence=${confidence}${enh})${id}`)
    }
    return capNotice(`[FormatForge] ${sanitizeText(result.file, 120)} 转换失败 [${sanitizeText(result.kind, 40)}] ${sanitizeText(result.message, 300) || ''}`)
  }

  return { broadcast, buildNotice, get enabled() { return enabled } }
}
