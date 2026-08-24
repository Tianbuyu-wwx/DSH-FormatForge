window.__ModuleLoader__.load({
	id: "dsh-formatforge",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;
		Object.defineProperty(exports, Symbol.toStringTag, { value: "Module" });
// FormatForge drop-to-forge — dsh client module (v0.1).
//
// Behavior:
//   - User drops NON-image files anywhere on the page → upload to
//     POST /formatforge/upload → lands in ~/.dsh/formatforge/inbox/ → the
//     existing inbox watcher forges it → session notice follows.
//   - Image files are IGNORED here (pass through to native attachment flow).
//   - Paste of file objects is handled too (screenshot paste stays native).
//
// Mount contract (verified against dsh web 0.1.1-rc.x):
//   The host serves <pkg>/lib/client.js at /plugins/<pkg>/client.js and
//   registers it in the boot manifest when package.json declares:
//     "dsh": { "client": { "inject": [], "platform": "web" } }
//   The file body is wrapped by the host build as:
//     window.__ModuleLoader__.load({ id, factory: (require) => { ... } })
//   so we must ship the SAME wrapper shape from our own lib/client.js.

const FF_UPLOAD = '/formatforge/upload'
const IMAGE_RE = /^image\/(png|jpeg|webp|gif)$/i

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

/** Toast-like transient banner (no dependency on host toast internals). */
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
      'max-width:380px;box-shadow:0 4px 14px rgba(0,0,0,.35);opacity:0;transition:opacity .25s'
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
    // 无扩展名/空 type 的按扩展名兜底判断（Windows 拖出的某些文件 type 为空）
    if ((f.type && IMAGE_RE.test(f.type)) || /\.(png|jpe?g|webp|gif)$/i.test(f.name || '')) images.push(f)
    else others.push(f)
  }
  return { images, others }
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
      results.push(`✗ ${f.name}: ${e.message}`)
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

function activate() {
  // 捕获阶段拦在官方 DropOverlay 之前；图片一律不碰。
  const onDrop = (e) => {
    if (!hasFiles(e)) return
    const files = Array.from(e.dataTransfer.files || [])
    const { images, others } = partition(files)
    if (others.length === 0) return // 纯图片 → 原生管线
    e.preventDefault()
    e.stopPropagation()
    void handleOthers(others)
    if (images.length > 0) {
      // 混合拖拽：图片部分手动交给原生流（构造新的 DataTransfer）
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
    }
  }

  const onDragOver = (e) => {
    if (!hasFiles(e)) return
    const files = Array.from(e.dataTransfer.files || [])
    const { others } = partition(files)
    if (others.length === 0) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'copy'
  }

  const onPaste = (e) => {
    if (!e.clipboardData) return
    const files = Array.from(e.clipboardData.files || [])
    const { others } = partition(files)
    if (others.length === 0) return
    e.preventDefault()
    e.stopPropagation()
    void handleOthers(others)
  }

  document.addEventListener('drop', onDrop, true)
  document.addEventListener('dragover', onDragOver, true)
  document.addEventListener('paste', onPaste, true)
  log('active — drop any non-image file to forge it')

  return () => {
    document.removeEventListener('drop', onDrop, true)
    document.removeEventListener('dragover', onDragOver, true)
    document.removeEventListener('paste', onPaste, true)
  }
}


		// cordis plugin contract: host treats each client module as a plugin —
		// exports must carry { inject: [...], apply(ctx) }.
		exports.inject = [];
		exports.apply = function () { activate(); };
		return exports;
	},
});
