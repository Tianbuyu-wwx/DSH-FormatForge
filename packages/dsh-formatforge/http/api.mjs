// http/api.mjs — FormatForge 只读 API（v3.0.0）。
//
// ⚠️ 安全前提（UI_DB_PLAN.md §3.3 / §8-R10）：宿主的鉴权围栏只保护 `GET /` 与 `/api`，
//    `ctx.webServer` 自己"无 TLS、无鉴权、无 origin 策略"。因此本文件**自建**两道门：
//      1. 同源判定：浏览器同源请求（`Sec-Fetch-Site: same-origin`，或 Origin 为 loopback）放行；
//      2. 一次性 token：`<FF_HOME>/api-token`（首次生成），供脚本/非浏览器访问；
//         写操作（retry/delete）必须带 token 或来自同源页面。
//    另外校验 Host 头属于 loopback，挡住 DNS rebinding 类场景。
//
// 读写分工：本模块只**读**库（node:sqlite / CLI 兜底）；写操作一律 spawn `formatforge inbox …`。

import { existsSync, mkdirSync, readFileSync, statSync, unlinkSync, writeFileSync, readdirSync } from 'node:fs'
import { randomBytes } from 'node:crypto'
import { join, basename } from 'node:path'
import { dbPrefs, dbStats, findArtifactById, queryArtifacts, savePrefs } from '../services/inbox-db.mjs'
import { ffHomeDir, inboxDir, resolveSourceName } from '../services/ff-paths.mjs'
import { runFormatForge } from '../services/python-runner.mjs'

const API_PREFIX = '/formatforge/api'
const DEFAULT_PREVIEW_CHARS = 12_000
const MAX_PREVIEW_CHARS = 200_000

/** 一次性 API token：首次调用时生成并落盘（0600）。 */
export function apiToken() {
  const file = join(ffHomeDir(), 'api-token')
  try {
    const existing = readFileSync(file, 'utf8').trim()
    if (existing) return existing
  } catch {
    /* 首次 */
  }
  const token = randomBytes(24).toString('hex')
  try {
    mkdirSync(ffHomeDir(), { recursive: true })
    writeFileSync(file, token + '\n', { encoding: 'utf8', mode: 0o600 })
  } catch {
    /* 只读环境：仍返回内存 token */
  }
  return token
}

/**
 * Host 头是否是 loopback。
 *
 * 覆盖：`127.0.0.1:19387` / `localhost` / `[::1]:19387` / `[::1]` / `::1`。
 * 注意不能"先 split(':') 再去方括号"：`'[::1]:19387'.split(':')[0]` 是 `'['`，会把 IPv6 字面量全判成非 loopback。
 */
function isLoopbackHostHeader(host) {
  if (!host) return false
  let name = String(host).trim().toLowerCase()
  if (name.startsWith('[')) {
    const end = name.indexOf(']')
    name = end === -1 ? name.slice(1) : name.slice(1, end)
  } else {
    const first = name.indexOf(':')
    if (first !== -1 && first === name.lastIndexOf(':')) name = name.slice(0, first) // host:port（单个冒号才是端口）
  }
  return name === '127.0.0.1' || name === 'localhost' || name === '::1'
}

function isLoopbackOrigin(origin) {
  try {
    const u = new URL(String(origin))
    return ['127.0.0.1', 'localhost', '::1', '[::1]'].includes(u.hostname)
  } catch {
    return false
  }
}

/** 允许执行写操作（retry / delete / PUT settings）的授权途径。 */
const WRITE_VIAS = new Set(['token', 'same-origin', 'app-panel'])

/**
 * 授权判定。
 *
 * 威胁模型（UI_DB_PLAN.md §8-R10）：我们的路由在宿主鉴权围栏之外，所以要自己挡
 * ① 局域网/远程访问 ② 恶意网页的跨站读取与 CSRF。
 *
 * 规则：
 *  - Host 必须是 loopback（挡 DNS rebinding 与外部直连）。
 *  - 带 token（或 token 错）→ 立刻有结论，不降级。
 *  - 同源页面（`Sec-Fetch-Site: same-origin` 或 loopback Origin）→ 放行。
 *  - **桌面应用 / Electron 主进程代理 / 非浏览器客户端**：浏览器发起的跨站请求一定同时带
 *    `Sec-Fetch-Site`（cross-site/same-site）与 `Origin`，所以"两者都没有"或为 opaque（`none`/`null`）
 *    可以判定不是网页攻击面 → 读放行；写要求 `x-ff-client: panel`（跨站带自定义头会触发 CORS 预检，
 *    而我们从不回 `Access-Control-Allow-*`，浏览器根本发不出去）。
 *  - 其余（带跨站信号的网页请求）→ 401。
 *
 * @returns {{ok:true, via:string}|{ok:false, reason:string, status:number, seen?:string}}
 */
export function authorize(req, url, { requireToken = false } = {}) {
  const headers = req.headers || {}
  const seen = `site=${headers['sec-fetch-site'] ?? '-'} origin=${headers.origin ?? '-'} client=${headers['x-ff-client'] ?? '-'}`
  const denyHost = { ok: false, reason: 'forbidden_host', status: 403 }
  if (!isLoopbackHostHeader(headers.host)) return denyHost

  const supplied = url.searchParams.get('token') || headers['x-ff-token']
  if (supplied) {
    if (String(supplied) === apiToken()) return { ok: true, via: 'token' }
    return { ok: false, reason: 'bad_token', status: 401, seen } // 明确给了错凭证：直接拒，不降级
  }

  const site = headers['sec-fetch-site']
  const origin = headers.origin
  const panel = headers['x-ff-client'] === 'panel'

  // ① 同源页面（浏览器正常打开 http://127.0.0.1:19387 时）
  if (site === 'same-origin' || (Boolean(origin) && isLoopbackOrigin(origin))) return { ok: true, via: 'same-origin' }

  // ② 桌面应用 / 主进程代理 / 脚本：没有浏览器信号
  const noBrowserSignals = site === undefined && origin === undefined
  const opaqueSignals = site === 'none' || origin === 'null'
  if (noBrowserSignals || opaqueSignals) {
    // 面板标记头优先：读也走 'app-panel'，写才有门票（见 WRITE_VIAS）
    if (panel) return { ok: true, via: 'app-panel' }
    if (!requireToken) return { ok: true, via: 'app' }
  }

  return { ok: false, reason: 'unauthorized', status: 401, seen }
}

function sendJson(res, status, payload) {
  // 宿主在 handler 抛错后也会 writeHead；已发出头部时再写会二次抛错，这里直接放弃。
  if (res.headersSent || res.writableEnded) {
    try {
      res.destroy?.()
    } catch {
      /* 忽略 */
    }
    return
  }
  const body = JSON.stringify(payload)
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' })
  res.end(body)
}

/**
 * 还原请求 URL。
 *
 * 宿主 `@deepseek-ai/dsh-host-webserver` 以 `route.handler(req, res)` 调用处理器
 * （`lib/index.js`：`await route.handler(req, res)`），**不传第三个参数**；
 * 因此不能依赖形参，必须从 `req.url` 自建。传入合法 URL 时（测试/内部复用）直接采用。
 *
 * base 固定为 loopback：解析只取 path/search，主机合法性由 Host 头判定（`authorize`），
 * 以免 `//evil.example` / absolute-form 之类写法把 `url.host` 带偏。
 */
export function requestUrl(req, provided) {
  if (provided && typeof provided.searchParams?.get === 'function') return provided
  let path = String(req?.url || '/')
  const absolute = /^[a-z][a-z0-9+.-]*:\/\/[^/]*/i.exec(path)
  if (absolute) path = path.slice(absolute[0].length)
  path = path.replace(/^\/+/, '/')
  if (!path.startsWith('/')) path = `/${path}`
  try {
    return new URL(path, 'http://127.0.0.1')
  } catch {
    return new URL('/', 'http://127.0.0.1')
  }
}

const okPayload = (data) => ({ ok: true, code: 200, data })
const errPayload = (kind, message, code = 4001) => ({ ok: false, code, error: { kind, message } })

function readQuery(url) {
  const q = url.searchParams
  return {
    q: q.get('q') || undefined,
    limit: q.get('limit') || undefined,
    cursor: q.get('cursor') || undefined,
    format: q.get('format') || undefined,
    parser: q.get('parser') || undefined,
    status: q.get('status') || undefined,
    since: q.get('since') || undefined,
  }
}

/** 从产物 JSON 里取正文（读 `.ff.md`，缺失则退回 `.ff.json` 的 data.content）。 */
function readContent(jsonPath, offset, maxChars) {
  const mdPath = jsonPath.replace(/\.ff\.json$/, '.ff.md')
  let text = ''
  try {
    if (existsSync(mdPath)) text = readFileSync(mdPath, 'utf8')
    else {
      const doc = JSON.parse(readFileSync(jsonPath, 'utf8'))
      text = String(doc?.data?.content ?? doc?.data?.convertedContent ?? '')
    }
  } catch (e) {
    return { ok: false, message: e.message }
  }
  const total = text.length
  const start = Math.max(0, Number(offset) || 0)
  const size = Math.max(200, Math.min(MAX_PREVIEW_CHARS, Number(maxChars) || DEFAULT_PREVIEW_CHARS))
  const chunk = text.slice(start, start + size)
  const next = start + size < total ? start + size : null
  return { ok: true, content: chunk, total_chars: total, offset: start, next_offset: next, truncated: next !== null }
}

const escapeRe = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/**
 * 在产物 JSON 里找 result_id，**支持前缀**（`ff_result` 的既有语义）。
 * 容忍 `"key": "v"` / `"key":"v"` 两种序列化，且**必须扫全文**：
 * payload 里 `content` 在前、`meta.result_id` 在后，正文一长 id 就落在头部窗口之外。
 */
function fileHasResultId(text, id) {
  return new RegExp(`"(?:result_id|resultId)"\\s*:\\s*"${escapeRe(id)}`).test(text)
}

/** 单个产物文件的体积上限（超过就不再全文扫描，避免病态内存/CPU）。 */
const ARTIFACT_SCAN_MAX_BYTES = 64 * 1024 * 1024

/**
 * id → 产物文件。顺序：查库（O(1)，与正文大小无关）→ 文件名精确/前缀 → 全文扫描兜底。
 *
 * 历史坑：只扫前 64KB 找 result_id，导致**大产物**（正文 > ~64K 字符）详情/正文/重转/删除全 404。
 */
function findArtifact(id) {
  const dir = inboxDir()
  const raw = String(id || '').trim()
  if (!raw || /[/\\]|\.\./.test(raw)) return { error: 'bad_id' }

  // 1) 首选：索引库里有 json_path，与产物多大无关
  const row = findArtifactById(raw)
  if (row && row.json_path && existsSync(row.json_path)) {
    return { jsonPath: row.json_path, dir, sourceName: row.source_name || null, via: 'db' }
  }

  let names = []
  try {
    names = readdirSync(dir)
  } catch {
    if (row && row.json_path) return { jsonPath: row.json_path, dir, sourceName: row.source_name || null, via: 'db-missing-file' }
    return { error: 'no_inbox' }
  }

  // 2) 文件名就是 id（部分历史产物）
  if (names.includes(`${raw}.ff.json`)) return { jsonPath: join(dir, `${raw}.ff.json`), dir, via: 'filename' }
  const prefixed = names.filter((n) => n.endsWith('.ff.json') && n.startsWith(raw)).sort()
  if (prefixed.length) return { jsonPath: join(dir, prefixed[0]), dir, via: 'filename-prefix' }

  // 3) 兜底：全文扫描（库里没有或库被关掉时，仍要能按 id 取回）
  for (const name of names) {
    if (!name.endsWith('.ff.json')) continue
    const full = join(dir, name)
    try {
      if (statSync(full).size > ARTIFACT_SCAN_MAX_BYTES) continue
      if (fileHasResultId(readFileSync(full, 'utf8'), raw)) return { jsonPath: full, dir, via: 'scan' }
    } catch {
      /* skip */
    }
  }
  return { error: 'not_found' }
}

/**
 * 注册 API 路由。返回 disposer 列表（交给 ctx.effect）。
 * @param {object} ctx   cordis 根 ctx（需 webServer）
 * @param {object} opts  { repoRoot, timeoutMs, log, watcher }
 */
export function registerApiRoutes(ctx, { repoRoot, timeoutMs, log = () => {}, watcher = null } = {}) {
  const webServer = (ctx.get && ctx.get('webServer')) || null
  if (!webServer || typeof webServer.register !== 'function') {
    log('[ff-api] webServer unavailable; API routes NOT registered')
    return []
  }
  const disposers = []
  const route = (kind, path, handler) => {
    try {
      const dispose = webServer.register({ kind, path, handler })
      if (typeof dispose === 'function') disposers.push(dispose)
    } catch (e) {
      log(`[ff-api] register ${path} failed: ${e.message}`)
    }
  }

  // 启动即生成 token 文件（<FF_HOME>/api-token，0600）：脚本/非浏览器客户端要靠它访问，
  // 若等到"有人带 token 来校验"时才生成，就永远没有人能拿到凭证。
  try {
    apiToken()
  } catch (e) {
    log(`[ff-api] token 生成失败（非浏览器访问将不可用）：${e.message}`)
  }

  // 注意：宿主只传 (req, res)，URL 由 requestUrl 自建（见该函数注释）。
  const guarded = (handler, { requireToken = false } = {}) => async (req, res, provided) => {
    const url = requestUrl(req, provided)
    try {
      const auth = authorize(req, url, { requireToken })
      if (!auth.ok) {
        // 401 里带上观察到的信号（site/origin/client），下次线上失败一眼能定位
        const detail =
          auth.reason === 'unauthorized' ? `需要 token 或同源访问（${auth.seen || ''}）` : auth.reason === 'bad_token' ? `token 不正确（${auth.seen || ''}）` : '仅允许本机访问'
        sendJson(res, auth.status, errPayload(auth.reason, detail))
        return
      }
      await handler(req, res, url, auth)
    } catch (e) {
      log(`[ff-api] handler error on ${url.pathname}: ${e.message}`)
      sendJson(res, 500, errPayload('internal', e.message))
    }
  }

  /** 写操作（retry/delete/PUT settings）的统一守卫。 */
  const writeDenied = (res, auth, what) => {
    if (WRITE_VIAS.has(auth.via)) return false
    sendJson(res, 401, errPayload('unauthorized', `${what} 需要 token 或同源页面（via=${auth.via}）`))
    return true
  }

  // ── 健康/统计 ────────────────────────────────────────────────────────────
  route('exact', `${API_PREFIX}/health`, guarded(async (_req, res) => {
    const stats = await dbStats({ repoRoot, timeoutMs, log })
    let fileCount = 0
    try {
      fileCount = readdirSync(inboxDir()).filter((n) => n.endsWith('.ff.json')).length
    } catch {
      fileCount = 0
    }
    sendJson(res, 200, okPayload({ plugin: 'dsh-formatforge', inbox: inboxDir(), files: fileCount, db: stats }))
  }))

  route('exact', `${API_PREFIX}/stats`, guarded(async (_req, res) => {
    const stats = await dbStats({ repoRoot, timeoutMs, log })
    sendJson(res, 200, okPayload({ stats, inbox: inboxDir() }))
  }))

  // ── 面板偏好（读 SQLite / 写走 CLI，保持单写者） ─────────────────────────
  route('exact', `${API_PREFIX}/settings`, guarded(async (req, res, _url, auth) => {
    if (req.method === 'GET') {
      const prefs = await dbPrefs({ repoRoot, timeoutMs, log })
      sendJson(res, 200, okPayload({ prefs }))
      return
    }
    if (req.method === 'PUT' || req.method === 'POST') {
      if (writeDenied(res, auth, '保存偏好')) return
      let raw = ''
      try {
        for await (const chunk of req) raw += chunk
      } catch {
        raw = ''
      }
      let patch = {}
      try {
        patch = raw ? JSON.parse(raw) : {}
      } catch {
        sendJson(res, 400, errPayload('bad_request', '请求体不是合法 JSON'))
        return
      }
      if (!patch || typeof patch !== 'object' || Array.isArray(patch)) {
        sendJson(res, 400, errPayload('bad_request', '请求体需要一个 JSON 对象'))
        return
      }
      const saved = await savePrefs(patch, { repoRoot, timeoutMs, log })
      if (!saved.ok) {
        sendJson(res, 400, errPayload('write_failed', saved.error?.message || '保存失败'))
        return
      }
      log(`[ff-api] prefs updated: ${JSON.stringify(patch)}`)
      sendJson(res, 200, okPayload({ prefs: saved.prefs }))
      return
    }
    sendJson(res, 405, errPayload('method_not_allowed', `不支持 ${req.method}`))
  }))

  // ── 列表 / 检索 ──────────────────────────────────────────────────────────
  const listArtifacts = async (res, url) => {
    const result = await queryArtifacts(readQuery(url), { repoRoot, timeoutMs, log })
    sendJson(res, 200, okPayload(result))
  }
  route('exact', `${API_PREFIX}/artifacts`, guarded(async (_req, res, url) => listArtifacts(res, url)))

  // ── 单条：GET 元数据/正文；POST retry；DELETE 软删除 ─────────────────────
  // 两个宿主约束：
  //   1. 重复 (kind, path) 会抛错，所以这几种动作必须共用一个 prefix 路由；
  //   2. prefix 匹配规则是 `pathname === prefix || pathname.startsWith(prefix + '/')`
  //      （dsh-host-webserver/lib/index.js `match()`），所以前缀**不能带尾斜杠** ——
  //      注册成 `/artifacts/` 时只有 `/artifacts//<id>` 能命中，真实请求会落到
  //      SPA fallback 变成 404（非 JSON）。
  const ARTIFACT_BASE = `${API_PREFIX}/artifacts`
  route('prefix', ARTIFACT_BASE, guarded(async (req, res, url, auth) => {
    if (url.pathname === ARTIFACT_BASE) {
      // prefix 表里的基路径（exact 表未命中时才会走到这里）→ 与 GET /artifacts 同义
      await listArtifacts(res, url)
      return
    }
    const parts = url.pathname.slice(`${ARTIFACT_BASE}/`.length).split('/').filter(Boolean)
    const id = decodeURIComponent(parts[0] || '')
    const sub = parts[1] || ''
    if (!id) {
      sendJson(res, 400, errPayload('bad_request', '缺少 id'))
      return
    }
    const found = findArtifact(id)
    if (found.error === 'bad_id') {
      sendJson(res, 400, errPayload('bad_request', '非法 id'))
      return
    }
    if (found.error) {
      sendJson(res, 404, errPayload('file_not_found', `找不到 ${id}`, 4002))
      return
    }

    // GET /artifacts/:id/content?offset=&max_chars=
    if (req.method === 'GET' && sub === 'content') {
      const preview = readContent(found.jsonPath, url.searchParams.get('offset'), url.searchParams.get('max_chars'))
      if (!preview.ok) {
        sendJson(res, 500, errPayload('parse_failed', preview.message))
        return
      }
      sendJson(res, 200, okPayload({
        id,
        file: basename(found.jsonPath),
        md_path: found.jsonPath.replace(/\.ff\.json$/, '.ff.md'),
        ...preview,
      }))
      return
    }

    // GET /artifacts/:id → 元数据
    if (req.method === 'GET') {
      try {
        const doc = JSON.parse(readFileSync(found.jsonPath, 'utf8'))
        const data = doc?.data || {}
        const meta = data.meta || {}
        const fileInfo = data.fileInfo || {}
        let sizeBytes = null
        try {
          sizeBytes = statSync(found.jsonPath).size
        } catch {
          sizeBytes = null
        }
        const stemOfArtifact = basename(found.jsonPath).replace(/\.ff\.json$/, '')
        sendJson(res, 200, okPayload({
          id: meta.result_id || data.resultId || id,
          file: basename(found.jsonPath),
          source: resolveSourceName(found.dir, stemOfArtifact, meta.source_name || found.sourceName || fileInfo.fileName),
          parser: meta.parser || fileInfo.fileType || '?',
          confidence: typeof meta.confidence === 'number' ? meta.confidence : typeof data.confidence === 'number' ? data.confidence : null,
          format: data.format || null,
          chars: typeof data.content === 'string' ? data.content.length : null,
          enhance: data.enhance || null,
          quality: data.quality || null,
          md_path: found.jsonPath.replace(/\.ff\.json$/, '.ff.md'),
          json_path: found.jsonPath,
          size_bytes: sizeBytes,
        }))
      } catch (e) {
        sendJson(res, 500, errPayload('parse_failed', e.message))
      }
      return
    }

    // POST /artifacts/:id/retry → 删产物 + 让 watcher 重新锻造（源文件仍在）
    if (req.method === 'POST' && sub === 'retry') {
      if (writeDenied(res, auth, '重新锻造')) return
      const jsonPath = found.jsonPath
      const mdPath = jsonPath.replace(/\.ff\.json$/, '.ff.md')
      for (const p of [jsonPath, mdPath]) {
        try {
          if (existsSync(p)) unlinkSync(p)
        } catch (e) {
          log(`[ff-api] retry unlink failed ${p}: ${e.message}`)
        }
      }
      const stem = basename(jsonPath).replace(/\.ff\.json$/, '')
      const forgotten = watcher?.forget ? watcher.forget(stem) : false
      log(`[ff-api] retry queued for ${id} (watcher forget=${forgotten})`)
      sendJson(res, 200, okPayload({ id, retry: true, forgotten }))
      return
    }

    // DELETE /artifacts/:id → 软删除（只动索引，不动磁盘文件）
    if (req.method === 'DELETE') {
      if (writeDenied(res, auth, '从列表移除')) return
      const del = await runFormatForge({ cliArgs: ['inbox', 'delete', '--id', id], repoRoot, stdinText: null, timeoutMs, log })
      if (!del.ok) {
        sendJson(res, 400, errPayload(del.error?.kind || 'internal', del.error?.message || 'delete failed'))
        return
      }
      log(`[ff-api] soft-deleted ${id} (files kept)`)
      sendJson(res, 200, okPayload({ id, deleted: true, files_kept: true }))
      return
    }

    sendJson(res, 405, errPayload('method_not_allowed', `不支持 ${req.method} ${url.pathname}`))
  }))

  // ── SSE：产物变化推送（轮询目录，2s） ────────────────────────────────────
  route('exact', `${API_PREFIX}/events`, guarded(async (req, res) => {
    res.writeHead(200, {
      'content-type': 'text/event-stream; charset=utf-8',
      'cache-control': 'no-store',
      connection: 'keep-alive',
      'x-accel-buffering': 'no',
    })
    const send = (event, data) => {
      try {
        res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)
      } catch {
        /* client gone */
      }
    }
    const snapshot = () => {
      try {
        const names = readdirSync(inboxDir()).filter((n) => n.endsWith('.ff.json'))
        let newest = 0
        for (const n of names) {
          try {
            newest = Math.max(newest, statSync(join(inboxDir(), n)).mtimeMs)
          } catch {
            /* skip */
          }
        }
        return { count: names.length, newest }
      } catch {
        return { count: 0, newest: 0 }
      }
    }
    let last = { count: -1, newest: 0 }
    send('hello', snapshot())
    const timer = setInterval(() => {
      const now = snapshot()
      if (now.count !== last.count || now.newest !== last.newest) {
        last = now
        send('artifacts', now)
      }
    }, 2_000)
    timer.unref?.()
    const close = () => clearInterval(timer)
    req.on('close', close)
    req.on('error', close)
  }))

  log(`[ff-api] routes registered under ${API_PREFIX} (health/stats/artifacts/…/+SSE)`)
  return disposers
}

export { API_PREFIX, isLoopbackHostHeader, isLoopbackOrigin, readContent, findArtifact }
