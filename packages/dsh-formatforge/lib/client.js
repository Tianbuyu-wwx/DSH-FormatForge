window.__ModuleLoader__.load({
	id: "@tianbuyu-wwx/dsh-formatforge",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
// FormatForge drop-to-forge — dsh client module (v0.3.1 · plugin 2.0.2).
//
// Behavior:
//   - Drop NON-image FILES anywhere → POST /formatforge/upload → lands in
//     ~/.dsh/formatforge/inbox/ → inbox watcher forges → session notice.
//   - Image files (png/jpeg/webp/gif) are IGNORED here (native attachment flow).
//   - DIRECTORIES are RELEASED to the host (放行文件夹): the host turns a dropped
//     folder into an @-path reference; this module must not touch that drag.
//
// v0.3.1 fix — dragging a FOLDER froze the page:
//   1) 放行文件夹. Chrome hands a directory to the page as a File that is
//      indistinguishable from an empty file (no MIME, no extension, 0 bytes),
//      so v0.3 classified it as an ordinary file: it preventDefault()'d the
//      whole drag, showed our mask, and then POSTed a 0-byte phantom. A drag
//      that contains ANY directory is now classified 'theirs' at the first
//      classification — no capture, no mask, no upload — so the host's own
//      folder intake (drop-events.js `droppedDirectories`) runs untouched.
//   2) × escape hatch. The host DropOverlay (dsh-client-ui-attachment) is shown
//      from its own `dragDepth` counter and only resets inside ITS OWN
//      drop/dragleave handlers. Once we swallow a terminal event that counter
//      can stay > 0 and the full-screen mask sticks until a page refresh.
//      Our mask now carries a × (plus Esc), and a small × chip rides EVERY file
//      drag — including the ones we released — so a wedged mask can always be
//      dismissed without refreshing.
//   3) 宿主计数器复位. Every terminal transition we swallow (our own drop, ×,
//      Esc, watchdog, teardown) also replays the host's own reset path — a
//      synthetic window `dragend` plus a viewport-edge `dragleave` aimed at
//      <body> — instead of leaving the host's counter wedged.
//
// (v0.3 kept: DECIDE ONCE per drag, at first classification — never flip mid-
//  drag — plus a 10s watchdog that force-hides whatever we show.)

const FF_UPLOAD = '/formatforge/upload'
const IMAGE_MIME_RE = /^image\//i
const IMAGE_EXT_RE = /\.(png|jpe?g|webp|gif)$/i
const OVERLAY_WATCHDOG_MS = 10_000
const ESCAPE_LINGER_MS = 8_000
const ESCAPE_LATCH_MS = 1_500

function log(msg) {
  try { console.log('[ff-drop] ' + msg) } catch { /* noop */ }
}

/** Append to <body> (the bundle may run before body exists). */
function mount(el) {
  try {
    const host = document.body || document.documentElement
    if (host && typeof host.appendChild === 'function') {
      host.appendChild(el)
      return true
    }
  } catch { /* noop */ }
  return false
}

async function uploadFile(file) {
  const buf = await file.arrayBuffer()
  const res = await fetch(FF_UPLOAD, {
    method: 'POST',
    headers: {
      'content-type': file.type || 'application/octet-stream',
      'x-ff-filename': encodeURIComponent(file.name || 'upload.bin'),
    },
    body: new Uint8Array(buf),
  })
  let payload = null
  try { payload = await res.json() } catch { /* noop */ }
  if (!res.ok || !payload || payload.ok !== true) {
    throw new Error((payload && payload.error) || `HTTP ${res.status}`)
  }
  return payload
}

/** Transient toast stack (bottom-right, pointer-events: none). */
function flash(text, kind) {
  try {
    const id = 'ff-drop-toast'
    let el = document.getElementById(id)
    if (!el) {
      el = document.createElement('div')
      el.id = id
      el.style.cssText =
        'position:fixed;right:18px;bottom:18px;z-index:2147483000;display:flex;flex-direction:column;gap:8px;pointer-events:none;font-family:inherit'
      mount(el)
    }
    const t = document.createElement('div')
    const bg = kind === 'error' ? '#b3261e' : kind === 'warn' ? '#8a6d00' : '#2e5d34'
    t.style.cssText =
      `background:${bg};color:#fff;padding:10px 14px;border-radius:8px;font-size:13px;line-height:1.45;` +
      'max-width:380px;box-shadow:0 4px 14px rgba(0,0,0,.35);opacity:0;transition:opacity .25s;white-space:pre-line'
    t.textContent = text
    el.appendChild(t)
    requestAnimationFrame(() => { t.style.opacity = '1' })
    setTimeout(() => {
      t.style.opacity = '0'
      setTimeout(() => t.remove(), 400)
    }, kind === 'error' ? 6000 : 3500)
  } catch { /* noop */ }
}

function hasFiles(e) {
  const dt = e && (e.dataTransfer || e.clipboardData)
  return !!(dt && dt.types && Array.prototype.includes.call(dt.types, 'Files'))
}

/** Files carried by a drag, from `files` and (when Chrome leaves it empty) `items`. */
function droppedFiles(dt) {
  const out = []
  try {
    for (const f of Array.from((dt && dt.files) || [])) out.push(f)
  } catch { /* noop */ }
  if (out.length > 0) return out
  // Chrome can expose an empty `files` on the first dragenter while `items`
  // already carries the entries — reading only `files` used to leave the drag
  // undecided, which is how the host ended up owning a drag we later captured.
  try {
    for (const item of Array.from((dt && dt.items) || [])) {
      if (!item || item.kind !== 'file') continue
      let f = null
      try { f = item.getAsFile() } catch { f = null }
      if (f) out.push(f)
    }
  } catch { /* noop */ }
  return out
}

/**
 * The shape Chrome gives a directory: NO MIME and 0 (or one block) bytes.
 * A fallback only — the entry API is the authoritative source — but it must
 * cover directories whose NAME carries an extension (`报告.pdf`), because the
 * entry API can be missing or can go silent mid-drag. An empty typeless real
 * file lands here too; releasing it to the host is the harmless side of the
 * trade (nothing is uploaded, the host simply attaches it).
 */
function looksLikeDirectory(f) {
  if (!f || f.type) return false
  const size = Number(f.size)
  return size === 0 || size === 4096
}

/**
 * Members of the drag that are DIRECTORIES. A dropped directory is a File
 * indistinguishable from an empty file, so the entry API is the only reliable
 * source — the same technique the host uses in drop-events.js. Each item is
 * decided on its own: one item whose entry cannot be read must not disable the
 * shape fallback for the others.
 */
function directoryFiles(dt, files) {
  const dirs = new Set()
  const answered = new Set()
  try {
    let i = 0
    for (const item of Array.from((dt && dt.items) || [])) {
      if (!item || item.kind !== 'file') continue
      const file = files[i++]
      if (!file) continue
      let entry = null
      if (typeof item.webkitGetAsEntry === 'function') {
        try { entry = item.webkitGetAsEntry() } catch { entry = null }
      }
      if (!entry) continue // no answer for THIS item → shape fallback below
      answered.add(file)
      if (entry.isDirectory === true) dirs.add(file)
    }
  } catch { /* noop */ }
  for (const f of files) {
    if (answered.has(f) || dirs.has(f)) continue
    if (looksLikeDirectory(f)) dirs.add(f)
  }
  return dirs
}

function partition(files, dt) {
  const list = Array.from(files || [])
  const dirs = directoryFiles(dt, list)
  const images = []
  const others = []
  for (const f of list) {
    if (dirs.has(f)) continue
    // 图片判定放宽：任何 image/* MIME 或常见图片扩展名都算图片（交给原生管线，
    // 即使原生不认 heic/avif 也由它自己弹"不支持"——绝不能由我们误接管导致卡死）。
    if ((f.type && IMAGE_MIME_RE.test(f.type)) || IMAGE_EXT_RE.test(f.name || '')) images.push(f)
    else others.push(f)
  }
  return { images, others, dirs }
}

/**
 * Decide ONCE per drag which side owns it.
 *   'ours'   — non-image files, no directory → we divert and forge.
 *   'theirs' — images and/or directories → host owns everything, we stay off.
 *   null     — undecided (nothing readable yet) → host visual, we watch drop.
 */
function classify(files, dt) {
  const part = partition(files, dt)
  if (part.dirs.size > 0) return { verdict: 'theirs', part }
  if (part.others.length > 0) return { verdict: 'ours', part }
  if (part.images.length > 0) return { verdict: 'theirs', part }
  return { verdict: null, part }
}

// ─── our own overlay + the × escape chip ────────────────────────────────────
let overlayEl = null
let overlayWatchdog = null
let escapeEl = null
let escapeLinger = null
let escapeAction = null

function showOverlay() {
  if (overlayEl) return
  const mask = document.createElement('div')
  mask.id = 'ff-drop-overlay'
  mask.style.cssText =
    'position:fixed;inset:0;z-index:2147482900;pointer-events:none;display:flex;align-items:center;justify-content:center;' +
    'background:rgba(0,0,0,.45);backdrop-filter:blur(2px)'
  const card = document.createElement('div')
  card.style.cssText =
    'position:relative;background:var(--dsw-alias-bg-base, #fff);color:var(--dsw-alias-label-primary, #111);' +
    'padding:22px 40px;border-radius:14px;font-size:15px;font-weight:600;text-align:center;' +
    'box-shadow:0 8px 30px rgba(0,0,0,.35)'
  const title = document.createElement('div')
  title.textContent = 'FormatForge：松手即锻造成 AI 可读数据'
  const hint = document.createElement('div')
  hint.textContent = '文件夹与图片会交回原生流程 · 点 × 或按 Esc 退出'
  hint.style.cssText = 'margin-top:8px;font-size:12px;font-weight:500;opacity:.72'
  // The escape button is the ONLY pointer-interactive part: the mask itself
  // stays pointer-inert so a stuck drag never blocks the app underneath.
  const close = document.createElement('button')
  close.id = 'ff-drop-close'
  close.type = 'button'
  close.textContent = '×'
  close.title = '退出拖拽遮罩（Esc）'
  close.setAttribute('aria-label', '退出拖拽遮罩')
  close.style.cssText =
    'position:absolute;top:6px;right:6px;width:28px;height:28px;padding:0;border:none;border-radius:50%;' +
    'pointer-events:auto;cursor:pointer;font-family:inherit;font-size:15px;line-height:1;color:inherit;' +
    'background:rgba(127,127,127,.18)'
  close.addEventListener('click', onEscapeClick)
  card.appendChild(title)
  card.appendChild(hint)
  card.appendChild(close)
  mask.appendChild(card)
  if (!mount(mask)) return
  overlayEl = mask
  // Watchdog: any overlay older than 10s is a bug — hand the drag back.
  overlayWatchdog = setTimeout(() => { if (escapeAction) escapeAction('watchdog') }, OVERLAY_WATCHDOG_MS)
}

function hideOverlay() {
  if (overlayWatchdog) {
    clearTimeout(overlayWatchdog)
    overlayWatchdog = null
  }
  if (overlayEl) {
    overlayEl.remove()
    overlayEl = null
  }
}

/**
 * The × chip: visible for every file drag (ours or released) and for a few
 * seconds after it ends, so a mask wedged by a dead drag session can still be
 * dismissed. It never preventDefault()s anything — UI only.
 */
function showEscape() {
  if (escapeLinger) {
    clearTimeout(escapeLinger)
    escapeLinger = null
  }
  if (escapeEl) return
  const btn = document.createElement('button')
  btn.id = 'ff-drop-escape'
  btn.type = 'button'
  btn.textContent = '× 退出拖拽'
  btn.title = '退出拖拽 / 关掉卡住的拖拽遮罩（Esc）'
  btn.setAttribute('aria-label', '退出拖拽遮罩')
  btn.style.cssText =
    'position:fixed;top:14px;right:14px;z-index:2147483001;pointer-events:auto;cursor:pointer;' +
    'padding:6px 12px;border:none;border-radius:999px;font-family:inherit;font-size:12px;line-height:1.2;' +
    'color:#fff;background:rgba(0,0,0,.62);box-shadow:0 2px 10px rgba(0,0,0,.35)'
  btn.addEventListener('click', onEscapeClick)
  if (!mount(btn)) return
  escapeEl = btn
}

function hideEscape() {
  if (escapeLinger) {
    clearTimeout(escapeLinger)
    escapeLinger = null
  }
  if (escapeEl) {
    escapeEl.remove()
    escapeEl = null
  }
}

function lingerEscape() {
  if (!escapeEl) return
  if (escapeLinger) clearTimeout(escapeLinger)
  escapeLinger = setTimeout(retireEscape, ESCAPE_LINGER_MS)
}

/**
 * The linger expired without any further drag activity for 8s: the drag session
 * is over by definition, so if the host is still showing its own mask it is
 * stale — replay its reset once more before losing the only visible escape.
 */
function retireEscape() {
  hideEscape()
  releaseHostDrag()
}

function onEscapeClick(ev) {
  if (ev && typeof ev.preventDefault === 'function') ev.preventDefault()
  if (ev && typeof ev.stopPropagation === 'function') ev.stopPropagation()
  if (escapeAction) escapeAction('escape-button')
}

/**
 * Replay the host's OWN reset path (dsh-client-ui-attachment
 * installDocumentDropEvents) so its dragDepth counter cannot stay > 0 and
 * leave the full-screen DropOverlay up until a refresh.
 */
let releasingHost = false
function releaseHostDrag() {
  if (releasingHost) return
  releasingHost = true
  try {
    // 1) window `dragend` is the host's unconditional reset (dragDepth = 0).
    try { window.dispatchEvent(new Event('dragend', { bubbles: true })) } catch { /* noop */ }
    // 2) A dragleave at the viewport edge targeting <body> trips the host's
    //    "left the viewport" reset branch as well.
    const target = document.body || document.documentElement
    if (target && typeof target.dispatchEvent === 'function') {
      const dt = new DataTransfer()
      if (dt && dt.items && typeof File === 'function') {
        dt.items.add(new File([new Uint8Array(0)], 'ff-drag-release'))
      }
      const ev = new DragEvent('dragleave', { bubbles: true, cancelable: true, clientX: -1, clientY: -1 })
      Object.defineProperty(ev, 'dataTransfer', { value: dt })
      target.dispatchEvent(ev)
    }
  } catch (e) {
    log('host drag reset failed: ' + (e && e.message))
  } finally {
    releasingHost = false
  }
}

async function handleOthers(others) {
  // Everything reaching here already passed partition(): directories are out.
  // Do NOT re-filter by shape — a legitimate empty typeless file must still be
  // forged, and a drop we already swallowed must never be dropped on the floor.
  const targets = (others || []).filter(Boolean)
  if (targets.length === 0) return
  flash(`FormatForge：正在锻造 ${targets.length} 个文件…`, 'info')
  const results = []
  for (const f of targets) {
    try {
      const r = await uploadFile(f)
      results.push(`✓ ${r.saved}`)
      log('uploaded ' + r.saved)
    } catch (e) {
      results.push(`✗ ${f.name || '未命名'}: ${e.message}`)
      log('upload failed ' + f.name + ': ' + e.message)
    }
  }
  const okN = results.filter((r) => r.startsWith('✓')).length
  const failN = results.length - okN
  const head =
    failN === 0
      ? `FormatForge：${okN} 个文件已投递到收件箱，转换完成后将自动通知`
      : `FormatForge：${okN} 成功 / ${failN} 失败`
  flash(`${head}\n${results.join('\n')}`, failN === 0 ? 'info' : 'error')
}

function activate() {
  // Per-drag decision, fixed at FIRST classification:
  //   null          = undecided (host owns the visuals; we still watch drop)
  //   'ours'        = non-image files → we own everything
  //   'theirs'      = folder or pure images → host owns everything
  let decision = null
  // We swallowed an event the host may have counted → its dragDepth needs the
  // reset nudge before this drag is forgotten.
  let hostSuspect = false
  // Set by the × / Esc escape: hands the rest of THIS drag to the host so a
  // dead drag session cannot immediately re-arm our mask. Cleared by a real
  // terminal event, or when a drag event arrives after a quiet gap (see below).
  let escaped = false
  // Timestamp of the last drag event; a fresh `dragenter` more than
  // ESCAPE_LATCH_MS after it is a NEW drag session. Chrome fires `dragover`
  // continuously (~350ms) while a drag is alive, so an ongoing drag keeps this
  // fresh and a live escape is never undone mid-drag.
  let lastDragEventAt = 0

  const touchDrag = () => {
    const now = Date.now()
    if (escaped && now - lastDragEventAt > ESCAPE_LATCH_MS) escaped = false
    lastDragEventAt = now
  }

  /** End of a drag for us: hide ours, keep the × reachable, un-wedge the host. */
  const finish = () => {
    // Ignore the events releaseHostDrag() synthesizes: they are our own nudge
    // for the host, not evidence that the user's drag session ended.
    if (releasingHost) return
    const mayHoldHost = hostSuspect
    hostSuspect = false
    decision = null
    escaped = false
    hideOverlay()
    lingerEscape()
    if (mayHoldHost) releaseHostDrag()
  }

  const escapeDrag = (why) => {
    log('escape (' + why + ') — drag handed back to the host')
    // Only an escape DURING a live drag (we own it) needs a latch: the common
    // case is clicking the × chip after the drag already died, and latching
    // there would poison the user's NEXT drag (its dragenter would be ignored
    // while its drop was still swallowed). See onDrop's wasEscaped branch.
    escaped = decision === 'ours' || overlayEl !== null
    hostSuspect = false
    decision = null
    hideOverlay()
    hideEscape()
    releaseHostDrag()
  }

  const onDragEnter = (e) => {
    if (!hasFiles(e)) return
    touchDrag()
    // After a × / Esc the user asked us out of THIS drag: no chip, no capture,
    // no visuals — just stay out of the way until the drag session ends.
    if (escaped) return
    showEscape() // UI only: rides every file drag, folder drags included
    if (decision !== null) return
    let files = []
    try { files = droppedFiles(e.dataTransfer) } catch { return }
    const { verdict } = classify(files, e.dataTransfer)
    if (verdict === 'ours') {
      decision = 'ours' // decided ONCE — stays for this whole drag
      hostSuspect = true
      e.preventDefault()
      e.stopPropagation()
      showOverlay()
      return
    }
    if (verdict === 'theirs') {
      // Folders/images: hands off completely, host owns it. Deliberately NOT
      // latched: only 'ours' must stay fixed for the whole drag. A latched
      // 'theirs' would outlive a drag that ends without a drop/leave and
      // silently disable the user's NEXT drag.
      return
    }
    // undecided: hands off. The host owns the visuals and will get the natural
    // leave/drop sequence — counters stay balanced.
  }

  const onDragOver = (e) => {
    if (escaped) {
      touchDrag() // keep the current drag session identifiable; stay hands-off
      return
    }
    if (decision !== 'ours') return
    e.preventDefault()
    e.stopPropagation()
    e.dataTransfer.dropEffect = 'copy'
  }

  const onDragLeave = (e) => {
    const left =
      e.clientX <= 0 || e.clientY <= 0 || e.clientX >= window.innerWidth || e.clientY >= window.innerHeight
    if (!left) return
    if (decision === 'ours') {
      // No stopPropagation on this path: the host must still see the leave and
      // balance its own counter. We only drop our visuals.
      finish()
      return
    }
    // Released (folder/image) and undecided drags belong to the host, but our
    // × chip must not outlive the drag: retire it on the same signal.
    lingerEscape()
  }

  const onDrop = (e) => {
    // Final say happens here regardless of earlier indecision.
    const wasEscaped = escaped
    let p = null
    if (hasFiles(e)) {
      try { p = partition(droppedFiles(e.dataTransfer), e.dataTransfer) } catch { p = null }
    }
    const wasOurs = decision === 'ours'
    const mayHoldHost = hostSuspect
    decision = null
    escaped = false
    hostSuspect = false
    hideOverlay()
    lingerEscape()

    // The user pressed × / Esc during this drag: it is the host's drop now —
    // hand it back untouched instead of diverting it silently ("退出" must mean
    // exit, and the host's own drop is what resets its counter).
    if (wasEscaped) {
      if (mayHoldHost) releaseHostDrag()
      return
    }

    const dirs = p ? p.dirs.size : 0
    const others = p ? p.others : []

    // 放行文件夹: a drag carrying a directory stays with the host end to end —
    // no preventDefault, no upload, no state of ours left behind. The counter
    // nudge only matters if an earlier dragenter of ours was captured.
    if (dirs > 0) {
      log(`released: drag contains ${dirs} directory entr${dirs === 1 ? 'y' : 'ies'}`)
      if (mayHoldHost) releaseHostDrag()
      return
    }

    if (others.length === 0) {
      if (wasOurs) e.preventDefault() // we showed UI for this drag; swallow it
      if (mayHoldHost) releaseHostDrag()
      return // pure-image / empty drop → native flow untouched
    }

    // Ours: divert before the host's bubble-phase handler runs. Its own drop
    // reset can never run past a stopPropagation, so replay it ALWAYS — also
    // for a drag we only classified here, because an unreadable first
    // dragenter let the host count it. A conditional nudge leaves a wedged
    // full-screen mask behind in exactly that case.
    e.preventDefault()
    e.stopPropagation()
    releaseHostDrag()
    void handleOthers(others)

    if (p.images.length > 0) {
      // Mixed drag: hand images back through a fresh synthetic drop.
      try {
        const dt = new DataTransfer()
        for (const img of p.images) dt.items.add(img)
        const synthetic = new DragEvent('drop', { bubbles: true, cancelable: true })
        Object.defineProperty(synthetic, 'dataTransfer', { value: dt })
        document.dispatchEvent(synthetic)
      } catch (err) {
        log('native handoff failed: ' + (err && err.message))
        flash('图片未能交给原生附件通道，请单独拖入', 'warn')
      }
    }
  }

  const onKeyDown = (e) => {
    if (e.key !== 'Escape') return
    if (!overlayEl && !escapeEl && decision !== 'ours') return
    escapeDrag('escape-key')
  }

  const onPaste = (e) => {
    if (!e.clipboardData) return
    let files = []
    try { files = Array.from(e.clipboardData.files || []) } catch { return }
    const { others, dirs } = partition(files, e.clipboardData)
    if (dirs.size > 0 || others.length === 0) return
    e.preventDefault()
    e.stopPropagation()
    void handleOthers(others)
  }

  document.addEventListener('dragenter', onDragEnter, true)
  document.addEventListener('dragover', onDragOver, true)
  document.addEventListener('dragleave', onDragLeave, true)
  document.addEventListener('drop', onDrop, true)
  document.addEventListener('keydown', onKeyDown, true)
  window.addEventListener('dragend', finish, true)
  window.addEventListener('blur', finish, true)
  document.addEventListener('paste', onPaste, true)

  escapeAction = escapeDrag
  log('v0.3.1 active — folders released, × / Esc escape hatch, host counter reset')

  // Teardown: the host's client module system can reload this bundle (client-hmr
  // → tearDownEntryFiber → the fiber's effect cleanups). Without a disposer every
  // reload would stack another listener set and one drop would upload N times,
  // because stopPropagation does not stop sibling listeners on the same node.
  return function deactivate() {
    document.removeEventListener('dragenter', onDragEnter, true)
    document.removeEventListener('dragover', onDragOver, true)
    document.removeEventListener('dragleave', onDragLeave, true)
    document.removeEventListener('drop', onDrop, true)
    document.removeEventListener('keydown', onKeyDown, true)
    window.removeEventListener('dragend', finish, true)
    window.removeEventListener('blur', finish, true)
    document.removeEventListener('paste', onPaste, true)
    const mayHoldHost = hostSuspect
    decision = null
    escaped = false
    hostSuspect = false
    // Only retract the handler if it is still ours: on a client-module reload
    // the host may mount the new fiber before running this disposer.
    if (escapeAction === escapeDrag) escapeAction = null
    hideOverlay()
    hideEscape()
    // A reload during a captured drag must not leave the host's counter behind.
    if (mayHoldHost) releaseHostDrag()
  }
}

// lib/panel.source.js — FormatForge 面板（v3.0.0，从零手写：零构建、零 npm 依赖）。
//
// 落点（用户拍板"只做面板"）：宿主右侧栏的**页签**——
//   1) 类型：ctx.sidebarRightTabs.register({ id, kind, priority:'extension', title, guide })
//   2) 主体：ctx.slots.register({ name:'sidebar.right.pane.tab', key: id }, Body)
//   3) 标题：ctx.slots.register({ name:'sidebar.right.pane.tab.title', key: id }, Title)
//   4) 入口：guide 条目（宿主内置 guide 页面里出现一张卡片）+ 侧栏底部动作按钮
//
// 依赖：宿主 Module Loader 提供的 `react`（本 bundle 的 factory 参数 require）。
// 降级（详见 UI_DB_PLAN.md §8-R1）：拿不到 react / 没有 sidebarRightTabs / 插槽未声明
//   → 只写日志，**绝不影响拖拽模块与工具**。
//
// 数据来源：`/formatforge/api/*`（同源请求，宿主鉴权围栏管不到我们的路由，
//   所以 API 侧做了同源判定 + 一次性 token，见 http/api.mjs）。

const FF_PANEL_KIND = 'formatforge-inbox'
const FF_PANEL_ID = '@tianbuyu-wwx/dsh-formatforge'
const FF_PANEL_NS = 'formatforge'
// 侧栏导航条目顺序：宿主的「插件」多为 0、「自动化任务」是 10 → 我们排 20，落在自动化任务下面
const FF_PANEL_ORDER = 20
const FF_API = '/formatforge/api'
const FF_PANEL_LIMIT = 50
const FF_PREVIEW_CHARS = 4000

const FF_DICT = {
  zh: {
    'panel.title': 'FormatForge',
    'panel.guide': 'FormatForge 收件箱',
    'panel.guideDesc': '搜索、预览、重新锻造已转换的产物',
    'panel.search': '搜索产物（支持中文子串）',
    'panel.refresh': '刷新',
    'panel.limit': '每页条数',
    'panel.loading': '加载中…',
    'panel.empty': '还没有产物：把文件拖进窗口即可自动锻造。',
    'panel.emptyQuery': '没有匹配的产物。',
    'panel.error': '读取失败',
    'panel.apiStale': '接口未就绪（HTTP 404）：插件已更新，但宿主还跑着旧的 Node 半 —— 请完全退出 DSH（含托盘）后重开一次。',
    'panel.apiRejected': '宿主拒绝了请求（HTTP 400，空响应）：插件 Node 半未随本次启动加载 —— 请完全退出 DSH（含托盘）后重开一次。',
    'panel.copyPath': '复制路径',
    'panel.retry': '重新锻造',
    'panel.delete': '从列表移除',
    'panel.copied': '已复制',
    'panel.retryQueued': '已排队重转（下一个扫描周期执行）',
    'panel.deleted': '已从列表移除（磁盘文件保留）',
    'panel.preview': '正文预览',
    'panel.more': '还有更多，用 ff_result 取全文',
    'panel.stats': '共 {total} 条 · 来源 {source}',
    'panel.close': '收起',
  },
  en: {
    'panel.title': 'FormatForge',
    'panel.guide': 'FormatForge inbox',
    'panel.guideDesc': 'Search, preview and re-forge converted artifacts',
    'panel.search': 'Search artifacts (substring, CJK friendly)',
    'panel.refresh': 'Refresh',
    'panel.limit': 'Page size',
    'panel.loading': 'Loading…',
    'panel.empty': 'No artifacts yet — drop a file onto the window.',
    'panel.emptyQuery': 'No artifact matches that query.',
    'panel.error': 'Request failed',
    'panel.apiStale': 'API not ready (HTTP 404): the plugin updated but the host still runs the old Node half — fully quit DSH (including the tray) and reopen.',
    'panel.apiRejected': 'Host rejected the request (HTTP 400, empty body): the plugin Node half did not load on this boot — fully quit DSH (including the tray) and reopen.',
    'panel.copyPath': 'Copy path',
    'panel.retry': 'Re-forge',
    'panel.delete': 'Hide',
    'panel.copied': 'Copied',
    'panel.retryQueued': 'Queued for re-forge (next scan tick)',
    'panel.deleted': 'Hidden (files kept on disk)',
    'panel.preview': 'Content preview',
    'panel.more': 'Truncated — use ff_result for the full text',
    'panel.stats': '{total} artifacts · source {source}',
    'panel.close': 'Collapse',
  },
}

function panelLog(msg) {
  try {
    console.log('[ff-panel] ' + msg)
  } catch {
    /* noop */
  }
}

function pickText(lang, key, vars) {
  const dict = FF_DICT[lang] || FF_DICT.zh
  let text = dict[key] || FF_DICT.zh[key] || key
  if (vars) {
    for (const k of Object.keys(vars)) text = text.replace('{' + k + '}', String(vars[k]))
  }
  return text
}

/** 面板内部的小状态机：一次取一页，选中项再取正文。 */
function makeStore() {
  let state = {
    rows: [],
    total: 0,
    source: '-',
    searchMode: '-',
    loading: false,
    error: null,
    query: '',
    notice: '',
    prefs: { panelLimit: FF_PANEL_LIMIT, lang: 'zh' },
  }
  const listeners = new Set()
  const emit = () => {
    for (const fn of [...listeners]) {
      try {
        fn()
      } catch (e) {
        panelLog('listener failed: ' + e.message)
      }
    }
  }
  const set = (patch) => {
    state = { ...state, ...patch }
    emit()
  }
  const api = async (path, options) => {
    // x-ff-client 是写操作的门票：跨站网页带自定义头会触发 CORS 预检，而我们从不回
    // Access-Control-Allow-*，恶意页面因此发不出写请求；面板（同源页面或桌面端）可以随便带。
    const res = await fetch(FF_API + path, {
      ...options,
      credentials: 'same-origin',
      headers: { 'x-ff-client': 'panel', ...((options && options.headers) || {}) },
    })
    let payload = null
    try {
      payload = await res.json()
    } catch {
      payload = null
    }
    if (!res.ok || !payload || payload.ok !== true) {
      const lang = state.prefs && state.prefs.lang
      if (res.status === 404) throw new Error(pickText(lang, 'panel.apiStale'))
      // 宿主 webserver 在处理器抛错时回 400 空 body —— 说明 Node 半没跟着本次启动加载。
      if (res.status === 400 && !payload) throw new Error(pickText(lang, 'panel.apiRejected'))
      const detail = (payload && payload.error && payload.error.message) || `HTTP ${res.status}`
      throw new Error(`${detail}（${FF_API}${path}）`)
    }
    return payload.data || {}
  }
  return {
    getState: () => state,
    subscribe(fn) {
      listeners.add(fn)
      return () => listeners.delete(fn)
    },
    async load(query) {
      set({ loading: true, error: null, notice: '', query: query === undefined ? state.query : query })
      try {
        const q = state.query ? `&q=${encodeURIComponent(state.query)}` : ''
        const limit = Number(state.prefs.panelLimit) || FF_PANEL_LIMIT
        const data = await api(`/artifacts?limit=${limit}${q}`)
        set({ rows: data.rows || [], total: (data.rows || []).length, source: data.source || '?', searchMode: data.search_mode || '?', loading: false })
      } catch (e) {
        set({ loading: false, error: e.message, rows: [] })
      }
    },
    async loadPrefs() {
      try {
        const data = await api('/settings')
        if (data && data.prefs) set({ prefs: { ...state.prefs, ...data.prefs } })
      } catch {
        /* 偏好读不到就用默认值 */
      }
    },
    async setLimit(limit) {
      const next = { ...state.prefs, panelLimit: Number(limit) || FF_PANEL_LIMIT }
      set({ prefs: next, error: null })
      try {
        const data = await api('/settings', {
          method: 'PUT',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ panelLimit: next.panelLimit }),
        })
        if (data && data.prefs) set({ prefs: { ...next, ...data.prefs } })
      } catch (e) {
        set({ error: e.message })
      }
      try {
        const q = state.query ? `&q=${encodeURIComponent(state.query)}` : ''
        const data = await api(`/artifacts?limit=${next.panelLimit}${q}`)
        set({ rows: data.rows || [], total: (data.rows || []).length, source: data.source || '?', searchMode: data.search_mode || '?' })
      } catch (e) {
        set({ error: e.message })
      }
    },
    async refreshStats() {
      try {
        const data = await api('/stats')
        const s = (data && data.stats) || {}
        set({ total: s.total ?? state.total, source: s.available ? s.source || 'sqlite' : 'files' })
      } catch {
        /* stats 失败不影响列表 */
      }
    },
    async detail(id) {
      set({ loading: true, error: null })
      try {
        const meta = await api(`/artifacts/${encodeURIComponent(id)}`)
        let content = ''
        try {
          const body = await api(`/artifacts/${encodeURIComponent(id)}/content?max_chars=${FF_PREVIEW_CHARS}`)
          content = body.content || ''
        } catch (e) {
          content = `（正文读取失败：${e.message}）`
        }
        set({ loading: false, selected: { ...meta, content } })
      } catch (e) {
        set({ loading: false, error: e.message })
      }
    },
    async retry(id, t) {
      try {
        await api(`/artifacts/${encodeURIComponent(id)}/retry`, { method: 'POST' })
        set({ notice: t('panel.retryQueued'), selected: null })
      } catch (e) {
        set({ error: e.message })
      }
    },
    async remove(id, t) {
      try {
        await api(`/artifacts/${encodeURIComponent(id)}`, { method: 'DELETE' })
        set({ notice: t('panel.deleted'), selected: null })
        await api.load(state.query)
      } catch (e) {
        set({ error: e.message })
      }
    },
    clearSelection() {
      set({ selected: null })
    },
  }
}

const FF_STYLE = {
  root: { display: 'flex', flexDirection: 'column', gap: '8px', padding: '10px 12px', fontSize: '12px', color: 'var(--dsw-alias-label-primary, #111)', height: '100%', boxSizing: 'border-box', overflow: 'auto' },
  rootPage: { maxWidth: '960px', width: '100%', margin: '0 auto', padding: '18px 22px', gap: '12px', fontSize: '13px' },
  row: { display: 'flex', gap: '6px', alignItems: 'center' },
  input: { flex: '1 1 auto', minWidth: '0', padding: '5px 8px', fontSize: '12px', borderRadius: '6px', border: '1px solid var(--dsw-alias-border-l2, #d0d0d0)', background: 'var(--dsw-alias-bg-base, #fff)', color: 'inherit' },
  button: { padding: '5px 9px', fontSize: '12px', borderRadius: '6px', border: '1px solid var(--dsw-alias-border-l2, #d0d0d0)', background: 'var(--dsw-alias-interactive-bg-hover, rgba(127,127,127,.12))', color: 'inherit', cursor: 'pointer', whiteSpace: 'nowrap' },
  list: { display: 'flex', flexDirection: 'column', gap: '4px' },
  item: { textAlign: 'left', display: 'flex', flexDirection: 'column', gap: '2px', padding: '6px 8px', borderRadius: '6px', border: '1px solid transparent', background: 'var(--dsw-alias-interactive-bg-hover, rgba(127,127,127,.08))', color: 'inherit', cursor: 'pointer' },
  itemTitle: { fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  meta: { opacity: 0.65, fontSize: '11px' },
  detail: { border: '1px solid var(--dsw-alias-border-l2, #d0d0d0)', borderRadius: '8px', padding: '8px', display: 'flex', flexDirection: 'column', gap: '6px' },
  pre: { margin: 0, padding: '8px', maxHeight: '240px', overflow: 'auto', fontSize: '11px', lineHeight: 1.45, whiteSpace: 'pre-wrap', wordBreak: 'break-word', background: 'var(--dsw-alias-bg-base, #fff)', borderRadius: '6px' },
  badge: { fontSize: '10px', padding: '1px 5px', borderRadius: '999px', background: 'var(--dsw-alias-interactive-bg-hover, rgba(127,127,127,.18))' },
  notice: { color: 'var(--dsw-alias-label-secondary, #666)', fontSize: '11px' },
  error: { color: '#b3261e', fontSize: '11px' },
}

function bytesLabel(n) {
  if (n === null || n === undefined || n === '') return ''
  const v = Number(n) || 0
  if (v < 1024) return `${v}B`
  if (v < 1024 * 1024) return `${Math.round(v / 1024)}KB`
  return `${(v / 1024 / 1024).toFixed(1)}MB`
}

// 兼容 ISO 字符串、unix 秒与毫秒时间戳（库里存的是秒，接口归一后是 ISO，两种都不能崩）
function timeLabel(value) {
  try {
    if (value === null || value === undefined || value === '') return ''
    if (typeof value === 'number' && Number.isFinite(value)) {
      const d = new Date(value < 1e12 ? value * 1000 : value)
      return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString()
    }
    const d = new Date(value)
    if (Number.isNaN(d.getTime())) return String(value)
    return d.toLocaleString()
  } catch {
    return String(value)
  }
}

// 兜底归一：接口正常时已经是客户端形状，但库列名（source_name/source_bytes/created_at）
// 若因任何原因透出来，列表也不能显示成 id 或空白。
function rowOf(r) {
  if (!r || typeof r !== 'object') return {}
  const created = r.forged_at ?? r.created_at
  return {
    ...r,
    source: r.source || r.source_name || null,
    size_bytes: r.size_bytes ?? r.source_bytes ?? null,
    forged_at: created === undefined ? null : created,
  }
}

/** 组装面板组件；返回 React 组件函数。 */
function makePanel(React, store, t) {
  const h = React.createElement
  const useSync = (selector) => {
    const [, force] = React.useReducer((x) => x + 1, 0)
    React.useEffect(() => store.subscribe(force), [])
    return selector(store.getState())
  }

  return function FormatForgePanel(props) {
    const state = useSync((s) => s)
    const [draft, setDraft] = React.useState('')
    const isPage = Boolean(props && props.variant === 'page')
    const rootStyle = isPage ? { ...FF_STYLE.root, ...FF_STYLE.rootPage } : FF_STYLE.root

    React.useEffect(() => {
      void store.loadPrefs().then(() => store.load(''))
      void store.refreshStats()
    }, [])

    const submit = () => {
      void store.load(draft)
    }

    const rows = state.rows || []
    const head = h(
      'div',
      { style: FF_STYLE.row },
      h('input', {
        style: FF_STYLE.input,
        placeholder: t('panel.search'),
        value: draft,
        onChange: (e) => setDraft(e.target.value),
        onKeyDown: (e) => {
          if (e.key === 'Enter') submit()
        },
        'aria-label': t('panel.search'),
      }),
      h('button', { style: FF_STYLE.button, onClick: submit, type: 'button' }, t('panel.refresh')),
      h(
        'select',
        {
          style: FF_STYLE.button,
          value: String((state.prefs && state.prefs.panelLimit) || FF_PANEL_LIMIT),
          title: t('panel.limit'),
          'aria-label': t('panel.limit'),
          onChange: (e) => void store.setLimit(e.target.value),
        },
        [20, 50, 100, 200].map((n) => h('option', { key: n, value: String(n) }, String(n))),
      ),
    )

    const status = state.error
      ? h('div', { style: FF_STYLE.error }, `${t('panel.error')}: ${state.error}`)
      : state.notice
        ? h('div', { style: FF_STYLE.notice }, state.notice)
        : h('div', { style: FF_STYLE.notice }, t('panel.stats', { total: state.total, source: state.source }))

    const list = state.loading && rows.length === 0
      ? h('div', { style: FF_STYLE.notice }, t('panel.loading'))
      : rows.length === 0
        ? h('div', { style: FF_STYLE.notice }, state.query ? t('panel.emptyQuery') : t('panel.empty'))
        : h(
            'div',
            { style: FF_STYLE.list, role: 'list' },
            rows.map((rawRow) => {
              const r = rowOf(rawRow)
              return h(
                'button',
                {
                  key: r.id,
                  type: 'button',
                  role: 'listitem',
                  style: FF_STYLE.item,
                  onClick: () => void store.detail(r.id),
                },
                h('span', { style: FF_STYLE.itemTitle }, r.source || r.id),
                h(
                  'span',
                  { style: FF_STYLE.meta },
                  `${r.parser || '?'} · ${bytesLabel(r.size_bytes)} · ${timeLabel(r.forged_at)}` +
                    (r.status === 'failed' ? ' · ⚠failed' : '') +
                    (r.session_id ? ` · ${String(r.session_id).slice(0, 8)}` : ''),
                ),
              )
            }),
          )

    const sel = state.selected ? rowOf(state.selected) : null
    const detail = sel
      ? h(
          'div',
          { style: FF_STYLE.detail },
          h('div', { style: FF_STYLE.row }, h('strong', null, sel.source || sel.id), h('span', { style: FF_STYLE.badge }, sel.parser || '?')),
          h(
            'div',
            { style: FF_STYLE.meta },
            `${sel.id} · ${bytesLabel(sel.size_bytes)}` +
              (sel.confidence !== null && sel.confidence !== undefined ? ` · conf=${sel.confidence}` : ''),
          ),
          h('div', { style: FF_STYLE.row },
            h('button', {
              type: 'button',
              style: FF_STYLE.button,
              onClick: () => {
                const p = sel.md_path || sel.json_path || ''
                try {
                  void navigator.clipboard.writeText(p)
                } catch {
                  /* clipboard 不可用时忽略 */
                }
              },
            }, t('panel.copyPath')),
            h('button', { type: 'button', style: FF_STYLE.button, onClick: () => void store.retry(sel.id, t) }, t('panel.retry')),
            h('button', { type: 'button', style: FF_STYLE.button, onClick: () => void store.remove(sel.id, t) }, t('panel.delete')),
            h('button', { type: 'button', style: FF_STYLE.button, onClick: () => store.clearSelection() }, t('panel.close')),
          ),
          h('div', { style: FF_STYLE.meta }, t('panel.preview')),
          h('pre', { style: FF_STYLE.pre }, sel.content || ''),
        )
      : null

    return h('div', { style: rootStyle }, head, status, list, detail)
  }
}

/** 侧栏导航条目要的是**图标**（宿主 PanelRow 传 { size, active }）。内联 SVG，零依赖、跟随主题。 */
function makePanelIcon(React) {
  return function FormatForgeIcon(props) {
    const size = (props && props.size) || 18
    return React.createElement(
      'svg',
      {
        width: size,
        height: size,
        viewBox: '0 0 24 24',
        fill: 'none',
        stroke: 'currentColor',
        strokeWidth: 1.7,
        strokeLinecap: 'round',
        strokeLinejoin: 'round',
        'aria-hidden': 'true',
        focusable: 'false',
      },
      // 一个"收件箱 + 锻造火花"的极简字形：箱子 + 上方三点
      React.createElement('path', { d: 'M3 12.5 5 6h14l2 6.5V18a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 3 18z' }),
      React.createElement('path', { d: 'M3 12.5h5l1.2 2.2h5.6L16 12.5h5' }),
      React.createElement('path', { d: 'M12 3.2v2.4M8.6 4.4v1.2M15.4 4.4v1.2' }),
    )
  }
}

/**
 * 把面板挂到宿主右侧栏。由 client bundle 的 apply() 调用。
 * @param {object} ctx cordis 客户端根 ctx
 */
function activatePanel(ctx) {
  if (!ctx || typeof ctx.inject !== 'function') {
    panelLog('ctx.inject unavailable; panel disabled')
    return
  }
  ctx.inject(['slots'], (scope) => {
    let React = null
    try {
      React = require('react')
    } catch (e) {
      panelLog('react unavailable, panel stays off: ' + (e && e.message))
      return
    }
    if (!React || typeof React.createElement !== 'function') {
      panelLog('react shape unexpected; panel stays off')
      return
    }
    const get = (name) => {
      try {
        return scope && typeof scope.get === 'function' ? scope.get(name) : scope && scope[name]
      } catch {
        return null
      }
    }
    const slots = get('slots') || (scope && scope.slots)
    if (!slots || typeof slots.register !== 'function') {
      panelLog('slots service unavailable; panel stays off')
      return
    }
    const locale = get('locale')
    const tabs = get('sidebarRightTabs')
    const sidebar = get('sidebarRight')

    let lang = 'zh'
    try {
      if (locale && typeof locale.register === 'function') {
        ctx.effect(() => locale.register(FF_PANEL_NS, FF_DICT), 'ff-panel: dictionaries')
      }
      if (locale && typeof locale.get === 'function' && typeof locale.get() === 'string') lang = locale.get()
    } catch {
      /* locale 不可用就用默认 zh */
    }
    const t = (key, vars) => pickText(lang, key, vars)

    const store = makeStore()
    const Panel = makePanel(React, store, t)
    const PanelIcon = makePanelIcon(React)

    const Title = function FormatForgeTitle() {
      return React.createElement('span', { title: t('panel.title'), style: { fontWeight: 600 } }, t('panel.title'))
    }

    // 1) 侧栏导航条目（用户要的位置：`sidebar.panellist`，排在「自动化任务」下面）
    //    宿主 PanelRow 会把条目渲染成「图标 + 标题」，点击时调 selectPanel(id) 切到 main 插槽同 key 的页面。
    const iconSpec = { name: 'sidebar.panellist', id: FF_PANEL_ID, order: FF_PANEL_ORDER, label: () => t('panel.title') }
    const mainSpec = { name: 'main', key: FF_PANEL_ID }
    if (locale) {
      iconSpec.locale = FF_PANEL_NS
      mainSpec.locale = FF_PANEL_NS
    }
    try {
      ctx.effect(
        () =>
          slots.inject('sidebar.panellist', () =>
            slots.register(iconSpec, function FormatForgeNavIcon(props) {
              return PanelIcon(props)
            }),
          ),
        'ff-panel: sidebar entry',
      )
      ctx.effect(
        () => slots.inject('main', () => slots.register({ ...mainSpec, inject: () => ({ variant: 'page' }) }, Panel)),
        'ff-panel: main page',
      )
      panelLog(`registered sidebar.panellist entry (order=${FF_PANEL_ORDER}) + main page`)
    } catch (e) {
      panelLog('sidebar entry / main page registration failed: ' + (e && e.message))
    }

    // 2) 页签类型 + guide 入口（没有 sidebarRightTabs 时跳过：body 仍注册，等宿主自己开）
    if (tabs && typeof tabs.register === 'function') {
      try {
        ctx.effect(
          () =>
            tabs.register({
              id: FF_PANEL_ID,
              kind: FF_PANEL_KIND,
              priority: 'extension',
              title: () => t('panel.title'),
              guide: [{ id: 'inbox', kind: FF_PANEL_KIND, title: t('panel.guide'), description: t('panel.guideDesc') }],
            }),
          'ff-panel: tab type',
        )
      } catch (e) {
        panelLog('tab type registration failed: ' + (e && e.message))
      }
    } else {
      panelLog('sidebarRightTabs unavailable — guide entry skipped')
    }

    // 3) 右侧栏页签主体 + 标题（keyed 插槽：key 必须等于类型注册的 id）
    const bodySpec = { name: 'sidebar.right.pane.tab', key: FF_PANEL_ID }
    const titleSpec = { name: 'sidebar.right.pane.tab.title', key: FF_PANEL_ID }
    if (locale) {
      bodySpec.locale = FF_PANEL_NS
      titleSpec.locale = FF_PANEL_NS
    }
    try {
      ctx.effect(
        () => slots.inject('sidebar.right.pane.tab', () => slots.register({ ...bodySpec, inject: () => ({ variant: 'pane' }) }, Panel)),
        'ff-panel: body',
      )
      ctx.effect(
        () => slots.inject('sidebar.right.pane.tab.title', () => slots.register(titleSpec, Title)),
        'ff-panel: title',
      )
      panelLog('registered into sidebar.right.pane.tab (kind=' + FF_PANEL_KIND + ')')
    } catch (e) {
      // 插槽未声明/结构变化：静默降级，绝不影响拖拽模块
      panelLog('slot registration failed (host contract changed?): ' + (e && e.message))
    }

    // 4) 侧栏底部保留一个入口：右侧栏页签不是每个人都会展开
    if (sidebar && typeof sidebar.openTab === 'function') {
      try {
        ctx.effect(
          () =>
            slots.inject('sidebar.footer.action', () =>
              slots.register({ name: 'sidebar.footer.action', id: 'ff-panel-open' }, function FormatForgeOpen() {
                return React.createElement(
                  'button',
                  {
                    type: 'button',
                    title: t('panel.guideDesc'),
                    style: { ...FF_STYLE.button, width: '100%' },
                    onClick: () => sidebar.openTab(FF_PANEL_KIND),
                  },
                  t('panel.guide'),
                )
              }),
            ),
          'ff-panel: footer action',
        )
      } catch (e) {
        panelLog('footer action skipped: ' + (e && e.message))
      }
    }
  })
}


		// cordis client-plugin contract: the host mounts each client module as a
		// plugin, so exports must carry { inject: [...], apply(ctx) }. The disposer
		// returned by activate() goes to ctx.effect so an HMR reload unregisters
		// the listeners instead of stacking a second set.
		exports.inject = [];
		exports.apply = function (ctx) {
			var run = function (label, fn) {
				try {
					if (ctx && typeof ctx.effect === "function") ctx.effect(function () { return fn(); });
					else fn();
				} catch (e) {
					// 拖拽与面板互不拖累：一个失败不能挡住另一个（面板还会自己降级）
					try { console.error("[ff-drop] " + label + " activation failed: " + (e && e.message)); } catch (_) {}
				}
			};
			run("drag", activate);
			run("panel", function () { return activatePanel(ctx); });
		};
		return exports;
	},
});
