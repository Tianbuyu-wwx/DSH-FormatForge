window.__ModuleLoader__.load({
	id: "dsh-formatforge",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
// FormatForge drop-to-forge — dsh client module (v0.3).
//
// Behavior:
//   - Drop NON-image files anywhere → POST /formatforge/upload → lands in
//     ~/.dsh/formatforge/inbox/ → inbox watcher forges → session notice.
//   - Image files (png/jpeg/webp/gif) are IGNORED here (native attachment flow).
//
// v0.3 fix — pure-image drag froze the page:
//   The host DropOverlay shows when its dragDepth>0 and resets only in ITS OWN
//   drop/dragleave handlers. Our old state machine could flip mid-drag: at
//   dragenter dataTransfer.files is often EMPTY in Chrome → we didn't capture;
//   a moment later files became readable, we captured and stopPropagation()'d
//   every subsequent event — the host never received leave/drop, its dragDepth
//   stayed >0, and the full-screen mask stuck until refresh.
//
//   New rule: DECIDE ONCE per drag, at first classification, then stay
//   consistent for the whole drag. If undecided at dragenter, do NOT capture —
//   let the host own the drag; we only act on the final `drop` (which needs no
//   early capture: preventDefault on drop is enough to divert it). A watchdog
//   timer also force-hides our overlay if no drop/leave arrives within 10s.

const FF_UPLOAD = '/formatforge/upload'
const IMAGE_RE = /^image\/(png|jpeg|webp|gif)$/i
const IMAGE_EXT_RE = /\.(png|jpe?g|webp|gif)$/i

function log(msg) {
  try { console.log('[ff-drop] ' + msg) } catch { /* noop */ }
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
      document.body.appendChild(el)
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

function partition(files) {
  const images = []
  const others = []
  for (const f of files) {
    // 图片判定放宽：任何 image/* MIME 或常见图片扩展名都算图片（交给原生管线，
    // 即使原生不认 heic/avif 也由它自己弹"不支持"——绝不能由我们误接管导致卡死）。
    if ((f.type && /^image\//i.test(f.type)) || IMAGE_EXT_RE.test(f.name || '')) images.push(f)
    else others.push(f)
  }
  return { images, others }
}

// ─── our own overlay (shown only while WE own an active drag) ───
let overlayEl = null
let overlayWatchdog = null
function showOverlay() {
  if (overlayEl) return
  overlayEl = document.createElement('div')
  overlayEl.id = 'ff-drop-overlay'
  overlayEl.style.cssText =
    'position:fixed;inset:0;z-index:2147482900;pointer-events:none;display:flex;align-items:center;justify-content:center;' +
    'background:rgba(0,0,0,.45);backdrop-filter:blur(2px)'
  const card = document.createElement('div')
  card.style.cssText =
    'background:var(--dsw-alias-bg-primary, #fff);color:var(--dsw-alias-text-primary, #111);' +
    'padding:22px 34px;border-radius:14px;font-size:15px;font-weight:600;text-align:center;' +
    'box-shadow:0 8px 30px rgba(0,0,0,.35)'
  card.textContent = 'FormatForge：松手即锻造成 AI 可读数据'
  overlayEl.appendChild(card)
  document.body.appendChild(overlayEl)
  // Watchdog: any overlay older than 10s is a bug — remove it ourselves.
  overlayWatchdog = setTimeout(hideOverlay, 10_000)
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

async function handleOthers(others) {
  flash(`FormatForge：正在锻造 ${others.length} 个文件…`, 'info')
  const results = []
  for (const f of others) {
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
  //   'ours'        = contains non-image files → we own everything
  //   'theirs'      = pure images / no files → host owns everything
  let decision = null

  const classifyFiles = (files) => {
    if (!files || files.length === 0) return null
    const p = partition(files)
    return p.others.length > 0 ? 'ours' : 'theirs'
  }

  const onDragEnter = (e) => {
    if (decision !== null || !hasFiles(e)) return
    let files = []
    try { files = Array.from(e.dataTransfer.files || []) } catch { return }
    const c = classifyFiles(files)
    if (c === 'ours') {
      decision = 'ours' // decided ONCE — stays for this whole drag
      e.preventDefault()
      e.stopPropagation()
      showOverlay()
    }
    // 'theirs'/undecided: hands off completely. The host owns the visuals and
    // will get the natural leave/drop sequence — counters stay balanced.
  }

  const onDragOver = (e) => {
    if (decision !== 'ours') return
    e.preventDefault()
    e.stopPropagation()
    e.dataTransfer.dropEffect = 'copy'
  }

  const onDragLeave = (e) => {
    if (decision !== 'ours') return
    const left =
      e.clientX <= 0 || e.clientY <= 0 || e.clientX >= window.innerWidth || e.clientY >= window.innerHeight
    if (left) {
      decision = null
      hideOverlay()
    }
  }

  const onDrop = (e) => {
    // Final say happens here regardless of earlier indecision.
    let p = null
    if (hasFiles(e)) {
      try { p = partition(Array.from(e.dataTransfer.files || [])) } catch { p = null }
    }
    const ours = p ? p.others.length > 0 : false
    const wasOurs = decision === 'ours'
    decision = null
    hideOverlay()

    if (!ours) {
      if (wasOurs) e.preventDefault() // we showed UI for this drag; swallow it
      return // pure-image / empty drop → native flow untouched
    }

    // Ours: divert before the host's bubble-phase handler runs.
    e.preventDefault()
    e.stopPropagation()
    void handleOthers(p.others)

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

  const endDrag = () => {
    if (decision === 'ours') {
      decision = null
      hideOverlay()
    }
  }

  const onPaste = (e) => {
    if (!e.clipboardData) return
    let files = []
    try { files = Array.from(e.clipboardData.files || []) } catch { return }
    const { others } = partition(files)
    if (others.length === 0) return
    e.preventDefault()
    e.stopPropagation()
    void handleOthers(others)
  }

  document.addEventListener('dragenter', onDragEnter, true)
  document.addEventListener('dragover', onDragOver, true)
  document.addEventListener('dragleave', onDragLeave, true)
  document.addEventListener('drop', onDrop, true)
  window.addEventListener('dragend', endDrag, true)
  window.addEventListener('blur', endDrag, true)
  document.addEventListener('paste', onPaste, true)

  log('v0.3 active — decide-once drag state machine (no mid-drag capture flips)')
}


		// cordis plugin contract: host treats each client module as a plugin —
		// exports must carry { inject: [...], apply(ctx) }.
		exports.inject = [];
		exports.apply = function () { activate(); };
		return exports;
	},
});
