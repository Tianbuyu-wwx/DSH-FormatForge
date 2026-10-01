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


		// cordis client-plugin contract: the host mounts each client module as a
		// plugin, so exports must carry { inject: [...], apply(ctx) }. The disposer
		// returned by activate() goes to ctx.effect so an HMR reload unregisters
		// the listeners instead of stacking a second set.
		exports.inject = [];
		exports.apply = function (ctx) {
			if (ctx && typeof ctx.effect === "function") ctx.effect(() => activate());
			else activate();
		};
		return exports;
	},
});
