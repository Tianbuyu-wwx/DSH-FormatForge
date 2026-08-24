// FormatForge drop-to-forge — dsh client module (v0.2).
//
// Behavior:
//   - Drop NON-image files anywhere → POST /formatforge/upload → lands in
//     ~/.dsh/formatforge/inbox/ → inbox watcher forges → session notice.
//   - Image files (png/jpeg/webp/gif) are IGNORED here (native attachment flow).
//
// v0.2 fix — native overlay freeze: the host's DropOverlay shows on dragenter
// and only resets inside its own drop handler. If we stopPropagation()'d the
// drop (to handle non-images ourselves), the host never reset → full-screen
// mask stuck until refresh. Fix: when a drag contains non-image files we take
// over the WHOLE drag lifecycle at capture phase (dragenter/dragover/drop),
// so the host never sees it and never shows its overlay; we render our own.
// Belt-and-braces: after handling a drop we also dispatch a synthetic empty
// drop so any host drag state still resets.

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
    if ((f.type && IMAGE_RE.test(f.type)) || IMAGE_EXT_RE.test(f.name || '')) images.push(f)
    else others.push(f)
  }
  return { images, others }
}

// ─── our own overlay (shown only when the drag contains non-image files) ───
let overlayEl = null
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
}
function hideOverlay() {
  if (overlayEl) {
    overlayEl.remove()
    overlayEl = null
  }
}

let uploading = 0

async function handleOthers(others) {
  uploading += others.length
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
    } finally {
      uploading--
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

/**
 * Dispatch a synthetic empty drop so the host's DropOverlay state machine
 * resets (its handler calls reset() then onAddImages([]) — a no-op).
 * Only needed when the host may have seen the dragenter (i.e. we did NOT
 * fully capture this drag from the start).
 */
function resetHostOverlay() {
  try {
    const dt = new DataTransfer()
    const synthetic = new DragEvent('drop', { bubbles: true, cancelable: true })
    Object.defineProperty(synthetic, 'dataTransfer', { value: dt })
    document.dispatchEvent(synthetic)
  } catch (e) {
    log('synthetic reset failed: ' + (e && e.message))
  }
}

export function activate() {
  let captured = false // true while WE own the current drag (contains others)

  const classify = (e) => {
    if (!hasFiles(e)) return null
    let files = []
    try { files = Array.from(e.dataTransfer.files || []) } catch { return null }
    if (files.length === 0) return null // undecidable yet — don't interfere
    return partition(files)
  }

  // Take over the drag as early as possible so the host overlay never appears.
  const onDragEnter = (e) => {
    const p = classify(e)
    if (!p || p.others.length === 0) return
    captured = true
    e.preventDefault()
    e.stopPropagation()
    showOverlay()
  }

  const onDragOver = (e) => {
    if (captured) {
      e.preventDefault()
      e.stopPropagation()
      e.dataTransfer.dropEffect = 'copy'
      return
    }
    const p = classify(e)
    if (!p || p.others.length === 0) return
    // Host may have already shown its overlay (files were empty on dragenter).
    captured = true
    e.preventDefault()
    e.stopPropagation()
    showOverlay()
  }

  const onDragLeave = (e) => {
    if (!captured) return
    // Left the window entirely?
    const left =
      e.clientX <= 0 || e.clientY <= 0 || e.clientX >= window.innerWidth || e.clientY >= window.innerHeight
    if (left) {
      captured = false
      hideOverlay()
    }
  }

  const onDrop = (e) => {
    const wasCaptured = captured
    captured = false
    hideOverlay()

    const p = classify(e)
    const others = p ? p.others : []
    const images = p ? p.images : []

    if (others.length === 0) {
      if (wasCaptured) {
        // We owned the drag but the user dropped only images (or nothing):
        // nothing to upload; if the host overlay is somehow showing, reset it.
        e.preventDefault()
        resetHostOverlay()
      }
      return // pure-image drop → native flow untouched
    }

    // We handle this drop; the host must not see it.
    e.preventDefault()
    e.stopPropagation()
    void handleOthers(others)

    if (images.length > 0) {
      // Mixed drag: hand images to the native attachment pipeline.
      try {
        const dt = new DataTransfer()
        for (const img of images) dt.items.add(img)
        const synthetic = new DragEvent('drop', { bubbles: true, cancelable: true })
        Object.defineProperty(synthetic, 'dataTransfer', { value: dt })
        document.dispatchEvent(synthetic)
      } catch (err) {
        log('native handoff failed: ' + (err && err.message))
        flash('图片未能交给原生附件通道，请单独拖入', 'warn')
      }
    } else if (!wasCaptured) {
      // Edge case: host saw the dragenter/over (we couldn't classify then) and
      // its overlay is up, but we just consumed the drop. Force-reset it.
      resetHostOverlay()
    }
  }

  const onDragEnd = () => {
    if (captured) {
      captured = false
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
  window.addEventListener('dragend', onDragEnd, true)
  window.addEventListener('blur', onDragEnd, true)
  document.addEventListener('paste', onPaste, true)
  log('v0.2 active — drop non-image files to forge them (overlay-safe)')
}
