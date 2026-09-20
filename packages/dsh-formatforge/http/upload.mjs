// http/upload.mjs
//
// POST /formatforge/upload — browser drop target for non-image files.
//
// Contract:
//   Request  : raw body = file bytes. Headers carry metadata (avoids multipart
//              parsing entirely; fetch() in the client module sends them natively):
//                x-ff-filename : UTF-8 filename (RFC 5987 style, raw utf-8 ok on loopback)
//                content-type  : browser-reported MIME (advisory only)
//   Response : { ok: true, saved: <path>, size: N }
//              { ok: false, error: '<reason>' } with 4xx
//
// Safety: loopback server already gates external access; we still enforce
//          Origin allowlist (JS-H6, DNS-rebinding) + extension whitelist +
//          size cap + filename sanitization (basename only) + atomic create.

import { join, basename, extname } from 'node:path'
import { mkdirSync, writeFileSync } from 'node:fs'
import { createInboxWatcher, inboxDir, isArtifactName } from '../services/inbox-watcher.mjs'

/** JS-H6/T2-3: 只认 **dsh web UI 自己的来源**，不是「任意环回端口」。
 *
 *  为什么不是 `^https?://(localhost|127.0.0.1|[::1])(:\d+)?$`：本机上跑着的任何网页
 *  （dev server :3000、Electron 壳、别的本地服务）都能满足它，而 OPTIONS 现在回显
 *  合法 ACAO，preflight 会通过 —— 对环回来源，这比它替换掉的规范非法值
 *  `'same-origin'`（任何浏览器都不接受 → 跨源 POST 根本发不出去）**更宽**。
 *  收紧成「GUI 的 origin（host:port 三写法 × http/https）」：DNS rebinding 仍然被挡
 *  （origin 留在攻击者域名），同源的 GUI 照常，别的本地页面进不来。
 *
 *  端口不写死：优先用 `webServer` 自己**正在监听**的端口（宿主
 *  `@deepseek-ai/dsh-host-webserver` 暴露 `get port()`，`port: 0` 时也是 OS 实际
 *  分配的那个），再退到 `FF_WEB_PORT`，最后才是默认 3080；`FF_UPLOAD_ORIGINS`
 *  （逗号分隔）整体覆盖。显式配置优先于探测到的值。
 *  缺 Origin 的请求（curl / 后端调用）仍然放行：非浏览器客户端本来就无法被网页 drive-by。 */
const DEFAULT_WEB_PORT = 3080
const LOOPBACK_HOSTS = ['127.0.0.1', 'localhost', '[::1]']

function normalizeOrigin(value) {
  return String(value ?? '').trim().toLowerCase()
}

function validPort(value) {
  const n = Number(value)
  return Number.isInteger(n) && n > 0 && n < 65536 ? n : null
}

/** 允许的 origin 集合。导出供测试与运维核对（大小写归一后的精确匹配）。
 *  @param livePort webServer 实际监听的端口（未监听时为 undefined） */
export function allowedOrigins(env = process.env, livePort = undefined) {
  const override = String(env.FF_UPLOAD_ORIGINS ?? '').trim()
  if (override) {
    return new Set(override.split(',').map(normalizeOrigin).filter(Boolean))
  }
  const port = validPort(env.FF_WEB_PORT) ?? validPort(livePort) ?? DEFAULT_WEB_PORT
  const set = new Set()
  for (const host of LOOPBACK_HOSTS) {
    // http/https 都收：GUI 若换成 TLS，origin 会变 https 而端口不变；该端口被
    // harness 自己占着，所以带上 https 不会多放进任何**别的**本地页面。
    set.add(`http://${host}:${port}`)
    set.add(`https://${host}:${port}`)
  }
  return set
}

function originAllowed(req, allowed) {
  const origin = req.headers?.origin
  if (origin === undefined || origin === '') return true
  if (typeof origin !== 'string') return false
  return allowed.has(normalizeOrigin(origin))
}

/** 日志/文件名里的控制字符（含 NUL/CR/LF）：NUL 会让 basename() 直接抛异常。
 *  T3-4/audit：U+2028/U+2029 同样要剥 —— 它们是合法的 NTFS 文件名字符，不在
 *  C0/C1 里，却在很多渲染器/分词器里当换行用；文件名会一路进收件箱、进通知文本。 */
function stripControl(s) {
  return String(s ?? '').replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/g, '_')
}

const KNOWN_EXT = new Set([
  // H18/audit: .doc/.ppt/.xlsb 移除（无解析器，收缩宣称）——未知扩展交 CLI 报 unsupported_format
  '.pdf', '.docx', '.pptx', '.xlsx', '.xlsm', '.csv', '.txt', '.md', '.markdown',
  '.rtf', '.odt', '.ods', '.odp', '.html', '.htm', '.xml', '.json', '.yaml', '.yml',
  '.toml', '.eml', '.msg', '.epub', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp',
  '.bmp', '.tiff', '.zip', '.7z', '.rar', '.srt', '.sql', '.latex', '.tex',
])

function readRawBody(req, maxBytes) {
  return new Promise((resolve, reject) => {
    const chunks = []
    let total = 0
    req.on('data', (c) => {
      total += c.length
      if (total > maxBytes) {
        reject(new Error('too_large'))
        req.destroy()
        return
      }
      chunks.push(c)
    })
    req.on('end', () => resolve(Buffer.concat(chunks)))
    req.on('error', reject)
  })
}

export function registerUploadRoute(ctx, { maxBytes, log }) {
  const webServer = ctx.get && ctx.get('webServer')
  if (!webServer || typeof webServer.register !== 'function') {
    log('[ff-upload] webServer unavailable; /formatforge/upload NOT registered')
    return false
  }
  // 白名单在**首次请求**时定一次并缓存：`webServer.port` 要等 listen 成功才有值，
  // 而 apply() 注册路由时它可能还没监听（这里读到的会是 undefined）。首个请求到达
  // 时一定已经在监听了。改端口/改白名单仍然需要重启，和其余配置一致。
  let allowed = null
  const allowedNow = () => {
    if (!allowed) {
      allowed = allowedOrigins(process.env, webServer.port)
      log(`[ff-upload] Origin allowlist: ${[...allowed].join(', ')}`)
    }
    return allowed
  }

  webServer.register({
    kind: 'exact',
    path: '/formatforge/upload',
    handler: async (req, res) => {
      // JS-H6: Origin 白名单（DNS rebinding 会把攻击者域名的请求变成「同源」POST）
      if (!originAllowed(req, allowedNow())) {
        log(`[ff-upload] rejected Origin: ${stripControl(req.headers?.origin).slice(0, 120)}`)
        res.writeHead(403, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ ok: false, error: 'forbidden_origin' }))
        return
      }
      // CORS preflight（同源部署其实用不到，防御性保留；回显校验通过的 Origin
      // ——旧值 'same-origin' 是规范非法值，任何浏览器都不会接受）
      if (req.method === 'OPTIONS') {
        res.writeHead(204, {
          'access-control-allow-origin': req.headers?.origin || 'null',
          'access-control-allow-methods': 'POST, OPTIONS',
          'access-control-allow-headers': 'content-type, x-ff-filename',
          vary: 'origin',
        })
        res.end()
        return
      }
      if (req.method !== 'POST') {
        res.writeHead(405, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ ok: false, error: 'method_not_allowed' }))
        return
      }

      let rawName
      try {
        rawName = decodeURIComponent(req.headers['x-ff-filename'] || '')
      } catch {
        rawName = req.headers['x-ff-filename'] || ''
      }
      // 控制字符（含 %00/NUL/CRLF）先替换：basename() 遇到 NUL 会抛 ERR_INVALID_ARG_VALUE，
      // 而 CR/LF 还能一路进收件箱文件名与通知文本
      const safeName = basename(stripControl(rawName).replace(/[\\/:*?"<>|]/g, '_'))
      const ext = extname(safeName).toLowerCase()

      if (!safeName || !ext || !KNOWN_EXT.has(ext)) {
        res.writeHead(415, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ ok: false, error: `unsupported_format: ${safeName || '(no name)'}` }))
        return
      }
      // JS-H6/M11: 产物形状的名字（`x.ff.json` 等）不是源文档 —— 上传口拒收，
      // 否则伪造的 `.ff.json` 会绕过转换直接躺在收件箱里被当作「转换结果」
      if (isArtifactName(safeName)) {
        res.writeHead(415, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ ok: false, error: `artifact_name_rejected: ${safeName}` }))
        return
      }

      const dir = inboxDir()
      try {
        mkdirSync(dir, { recursive: true })
      } catch { /* exists */ }

      let body
      try {
        body = await readRawBody(req, maxBytes)
      } catch (e) {
        res.writeHead(e.message === 'too_large' ? 413 : 400, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ ok: false, error: e.message }))
        return
      }
      if (body.length === 0) {
        res.writeHead(400, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ ok: false, error: 'empty_body' }))
        return
      }

      // 同名冲突 + TOCTOU：用 O_EXCL(flag:'wx') 原子创建，EEXIST 时追加序号重试
      //（旧的 existsSync→writeFileSync 之间两个并发同名上传会互相覆盖）
      const stem = safeName.slice(0, safeName.length - ext.length)
      let finalName = safeName
      let dest = ''
      for (let attempt = 0; ; attempt++) {
        dest = join(dir, finalName)
        try {
          writeFileSync(dest, body, { flag: 'wx' })
          break
        } catch (e) {
          if (e.code !== 'EEXIST' || attempt >= 100) {
            log(`[ff-upload] write failed: ${e.message}`)
            res.writeHead(500, { 'content-type': 'application/json' })
            res.end(JSON.stringify({ ok: false, error: `write_failed: ${e.message}` }))
            return
          }
          finalName = `${stem}(${attempt + 1})${ext}`
        }
      }

      log(`[ff-upload] ${finalName} (${body.length}B) -> inbox`)
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ ok: true, saved: finalName, size: body.length }))
    },
  })

  // 健康检查
  webServer.register({
    kind: 'exact',
    path: '/formatforge/health',
    handler: async (_req, res) => {
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ ok: true, plugin: 'dsh-formatforge', inbox: inboxDir() }))
    },
  })

  log('[ff-upload] routes registered: POST /formatforge/upload, GET /formatforge/health')
  return true
}
