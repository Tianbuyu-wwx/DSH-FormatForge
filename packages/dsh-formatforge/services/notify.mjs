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
            content: [{ type: 'text', text }],
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
      const enh = result.enhanceReason ? `；⚠ enhance=${result.enhanceReason}` : ''
      const idLine = result.resultId ? `\n- 结果 id：${result.resultId}（用 ff_result {id:"${result.resultId}"} 直接取回）` : ''
      return (
        `[FormatForge] 收件箱文件已锻好：${result.file} ` +
        `(parser=${result.parser || '?'}, confidence=${result.confidence ?? '?'}${enh})。\n` +
        `结果文件：\n- 完整协议 JSON：${result.jsonPath}\n- 可读内容：${result.mdPath}${idLine}\n` +
        `用户接下来很可能基于该文件提问——如需原文请用 ff_translate（路径见上）或直接读取 .ff.md。`
      )
    }
    return (
      `[FormatForge] 收件箱文件转换失败：${result.file}\n` +
      `原因 [${result.kind}]: ${result.message || ''}\n` +
      `详情见同目录 .ff.error.txt；修正后重新拖入即可重试。`
    )
  }

  return { broadcast, buildNotice, get enabled() { return enabled } }
}
