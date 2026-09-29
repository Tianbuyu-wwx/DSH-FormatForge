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
      const enh = result.enhanceReason ? ` enhance=${result.enhanceReason}` : ''
      const id = result.resultId ? ` id=${result.resultId}` : ''
      return `[FormatForge] ${result.file} 已锻好 (parser=${result.parser || '?'}, confidence=${result.confidence ?? '?'}${enh})${id}`
    }
    return `[FormatForge] ${result.file} 转换失败 [${result.kind}] ${result.message || ''}`
  }

  return { broadcast, buildNotice, get enabled() { return enabled } }
}
