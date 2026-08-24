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
// extension whitelist + size cap + filename sanitization (basename only).

import { join, basename, extname } from 'node:path'
import { statSync, existsSync, mkdirSync } from 'node:fs'
import { createInboxWatcher, inboxDir } from '../services/inbox-watcher.mjs'

const KNOWN_EXT = new Set([
  '.pdf', '.docx', '.doc', '.pptx', '.xlsx', '.xlsm', '.csv', '.txt', '.md', '.markdown',
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

  webServer.register({
    kind: 'exact',
    path: '/formatforge/upload',
    handler: async (req, res) => {
      // CORS preflight（同源部署其实用不到，防御性保留）
      if (req.method === 'OPTIONS') {
        res.writeHead(204, {
          'access-control-allow-origin': 'same-origin',
          'access-control-allow-methods': 'POST, OPTIONS',
          'access-control-allow-headers': 'content-type, x-ff-filename',
        })
        res.end()
        return
      }
      if (req.method !== 'POST') {
        res.writeHead(405, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ ok: false, error: 'method_not_allowed' }))
        return
      }

      const rawName = decodeURIComponent(req.headers['x-ff-filename'] || '').replace(/[\\/:*?"<>|]/g, '_')
      const safeName = basename(rawName || '')
      const ext = extname(safeName).toLowerCase()

      if (!safeName || !ext || !KNOWN_EXT.has(ext)) {
        res.writeHead(415, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ ok: false, error: `unsupported_format: ${safeName || '(no name)'}` }))
        return
      }

      const dir = inboxDir()
      try {
        mkdirSync(dir, { recursive: true })
      } catch { /* exists */ }

      // 同名冲突：追加序号（inbox watcher 以文件名为去重键，不覆盖已有产物）
      let finalName = safeName
      let stem = safeName.slice(0, safeName.length - ext.length)
      let n = 1
      while (existsSync(join(dir, finalName))) {
        finalName = `${stem}(${n++})${ext}`
      }

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

      const dest = join(dir, finalName)
      try {
        const fs = process.getBuiltinModule('node:fs')
        fs.writeFileSync(dest, body)
      } catch (e) {
        log(`[ff-upload] write failed: ${e.message}`)
        res.writeHead(500, { 'content-type': 'application/json' })
        res.end(JSON.stringify({ ok: false, error: `write_failed: ${e.message}` }))
        return
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
