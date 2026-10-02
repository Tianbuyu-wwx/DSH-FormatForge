// test-host-http.mjs — 用**真实 node:http 服务器**复刻宿主路由语义，端到端跑 /formatforge/api/*（v3.0.0）。
//
// 为什么不能只有 test-api.mjs：那里直接调 handler，绕过了宿主（@deepseek-ai/dsh-host-webserver）
// 的两条真实契约 —— 两条都真实炸过线上：
//   1. `lib/index.js`: `await route.handler(req, res)` —— **没有第三个 url 参数**。
//      曾经 handler 写成 `(req, res, url)` 并在 try 外读 `url.searchParams` → TypeError →
//      宿主 catch → `res.writeHead(400); res.end()` → 所有 API 变成 400 空 body。
//   2. `match()`（lib/index.js:323-332）：先查 exact 表，未命中再在 prefix 表里「最长前缀胜」，
//      命中条件是 `pathname === prefix || pathname.startsWith(prefix + '/')`。
//      prefix 带尾斜杠时只有 `/artifacts//<id>` 能命中，真实的 `/artifacts/<id>` 会落到
//      SPA fallback → 404 空 body。
// 本套件把这两条都钉在真实 socket 上：mini 宿主按源码逐条复刻 register/match/fallback/错误兜底，
// 断言只看响应的状态码、响应头与 body —— 处理器多要一个参数、注册路径写错，都会在这里变红。
//
// 用法：node packages/dsh-formatforge/test-host-http.mjs

import { mkdirSync, mkdtempSync, writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs'
import { createServer, request as httpRequest } from 'node:http'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'
import { execFileSync } from 'node:child_process'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = dirname(dirname(HERE))
/** 解释器：FF_PYTHON 优先，其次仓库 venv，最后 PATH 上的 python（与 test-api.mjs 同一套）。 */
const PY = (() => {
  const venv = process.platform === 'win32' ? join(REPO_ROOT, '.venv-fg', 'Scripts', 'python.exe') : join(REPO_ROOT, '.venv-fg', 'bin', 'python')
  if (process.env.FF_PYTHON) return process.env.FF_PYTHON
  if (existsSync(venv)) return venv
  return process.platform === 'win32' ? 'python' : 'python3'
})()

let passed = 0
let failures = 0
const ok = (label) => {
  passed += 1
  console.log('  ok   ' + label)
}
const fail = (label, detail) => {
  failures += 1
  console.error('  FAIL ' + label + (detail === undefined ? '' : ' — ' + detail))
}
const assert = (cond, label, detail) => (cond ? ok(label) : fail(label, detail))
/**
 * 断言详情的安全截断。失败路径下被打印的值很可能是 undefined
 * （`JSON.stringify(undefined)` 返回 undefined，再 `.slice` 就会把整个套件带走），
 * 所以这里统一兜底：任何断言失败都只报告，不中断后续断言。
 */
function brief(value, max = 200) {
  let text
  try {
    text = typeof value === 'string' ? value : JSON.stringify(value) ?? String(value)
  } catch {
    text = String(value)
  }
  return text.length > max ? text.slice(0, max) : text
}

// ── 环境隔离：临时 FF_HOME，绝不碰真实收件箱/索引库 ─────────────────────────
const HOME = mkdtempSync(join(tmpdir(), 'ff-host-http-'))
mkdirSync(join(HOME, 'inbox'), { recursive: true })
process.env.FF_HOME = HOME
delete process.env.FF_DB
delete process.env.FF_DB_PATH // 防外部环境把库指到别处（否则 stats/列表计数不可控）
process.env.PYTHONPATH = REPO_ROOT
const TOKEN_FILE = join(HOME, 'api-token')
// 兜底：断言失败或未捕获异常会跳过收尾段，这里的 'exit' 钩子保证临时目录不留在系统里
// （正常路径下收尾段已经删过，这里是幂等的空操作）。
process.on('exit', () => {
  try {
    rmSync(HOME, { recursive: true, force: true })
  } catch {
    /* best effort */
  }
})

// ── 造产物：与 test-api.mjs 相同的 JSON 形状（data.content + data.meta.*） ───
const SOURCE = '合同2024.txt'
const CONTENT = '# 转换结果\n\n付款条款：月结30天\n合同编号 HT-2024-001\n'
const RESULT_ID = 'cvt20261001120000abcdef'
const STEM = '合同2024'
const JSON_PATH = join(HOME, 'inbox', `${STEM}.ff.json`)
const MD_PATH = join(HOME, 'inbox', `${STEM}.ff.md`)
const DOC = {
  ok: true,
  code: 200,
  data: { content: CONTENT, format: 'markdown', meta: { parser: 'txt', file_size: 60, result_id: RESULT_ID, confidence: 0.95 } },
}

function cli(args) {
  const out = execFileSync(PY, ['-m', 'formatforge', ...args], {
    cwd: REPO_ROOT,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
    encoding: 'utf8',
    timeout: 60_000,
  })
  return JSON.parse(out.trim().split('\n').find((l) => l.startsWith('{')))
}

function writeArtifact() {
  writeFileSync(join(HOME, 'inbox', SOURCE), '付款条款：月结30天\n', 'utf8')
  writeFileSync(JSON_PATH, JSON.stringify(DOC, null, 2), 'utf8')
  writeFileSync(MD_PATH, CONTENT, 'utf8')
}

// ── mini 宿主：按 @deepseek-ai/dsh-host-webserver/lib/index.js 逐条复刻 ─────
function createMiniHost() {
  const exact = new Map()
  const prefixes = new Map()
  const sockets = new Set()
  const stats = { handled: 0, fallback: 0, hostCatch400: 0, arity: null }

  // 宿主调用约定：`await route.handler(req, res)` —— 恰好两参，绝不补传 url。
  // 用 arguments.length 记录实参个数，便于断言"复刻得对"（产品 handler 若真依赖第三参，
  // 拿到的是 undefined，线上就会走宿主 catch → 400 空 body）。
  function invoke(route, req, res) {
    stats.handled += 1
    stats.arity = arguments.length - 1
    return route.handler(req, res)
  }

  // SPA 已占位 fallback：未命中任何命名路由时交给它。真实 SPA 对未知路径回 404 空 body，
  // 与宿主无 fallback 时的 `res.writeHead(404); res.end()` 同形 —— 这正是我们"自己的 404"
  // （JSON code 4002）要区分开的对象。
  function fallback(_req, res) {
    stats.fallback += 1
    res.writeHead(404)
    res.end()
  }

  async function dispatch(req, res) {
    const rawPath = new URL(req.url ?? '/', 'http://x').pathname
    const route = host.match(rawPath)
    if (route !== undefined) {
      await invoke(route, req, res)
      return
    }
    await fallback(req, res)
  }

  const server = createServer((req, res) => {
    dispatch(req, res).catch(() => {
      // 宿主 lib/index.js 的兜底：handler 抛错且未发头 → writeHead(400) + end()。
      // 线上那次「所有 API 返回 400 空 body」就是踩进这个分支。
      stats.hostCatch400 += 1
      if (res.headersSent) {
        res.destroy()
        return
      }
      res.writeHead(400)
      res.end()
    })
  })
  server.on('connection', (socket) => {
    sockets.add(socket)
    socket.on('close', () => sockets.delete(socket))
  })

  const host = {
    /** register：重复 (kind,path) 抛错；返回 disposer（与宿主 register 一致）。 */
    register(route) {
      const table = route.kind === 'exact' ? exact : prefixes
      if (table.has(route.path)) throw new Error(`webserver: duplicate ${route.kind} route "${route.path}"`)
      table.set(route.path, route)
      return () => {
        table.delete(route.path)
      }
    },
    /** match：先 exact 表，再 prefix 表「最长前缀胜」（与宿主 match 一致）。 */
    match(pathname) {
      const hit = exact.get(pathname)
      if (hit !== undefined) return hit
      let best
      for (const [prefix, route] of prefixes) {
        if (pathname !== prefix && !pathname.startsWith(`${prefix}/`)) continue
        if (best === undefined || prefix.length > best.path.length) best = route
      }
      return best
    },
    routes() {
      return [...exact.values(), ...prefixes.values()]
    },
    stats() {
      return { ...stats }
    },
    socketCount() {
      return sockets.size
    },
    listening() {
      return server.listening
    },
    async listen() {
      await new Promise((resolve, reject) => {
        server.once('error', reject)
        server.listen(0, '127.0.0.1', () => {
          server.off('error', reject)
          resolve()
        })
      })
      return server.address().port
    },
    async close() {
      server.closeAllConnections() // 宿主收尾也用 closeAllConnections（含 SSE 长连接）
      await new Promise((resolve) => server.close(() => resolve()))
    },
  }
  return host
}

console.log('\n0. 准备：临时 FF_HOME + CLI 造产物建索引')
writeArtifact()
assert(cli(['inbox', 'init']).ok === true, 'CLI: inbox init 成功')
assert(cli(['inbox', 'index', '--artifact', JSON_PATH]).data.indexed[0] === RESULT_ID, 'CLI: 产物已进索引')

// 环境就绪后再 import 产品模块（ff-paths 在调用时读 env，顺序仍是好习惯）
const { registerApiRoutes } = await import('./http/api.mjs')

const host = createMiniHost()
const webServer = { register: (route) => host.register(route) }
const ctx = { get: (name) => (name === 'webServer' ? webServer : null) }
const forgot = []
const watcher = {
  forget: (stem) => {
    forgot.push(stem)
    return true
  },
}
const logs = []
const disposers = registerApiRoutes(ctx, { repoRoot: REPO_ROOT, timeoutMs: 30_000, log: (m) => logs.push(m), watcher })
const PORT = await host.listen()
const BASE = `http://127.0.0.1:${PORT}`

// ── 请求工具：全部走真实 socket ─────────────────────────────────────────────
// 默认带 `sec-fetch-site: same-origin`（浏览器同源请求），否则会被 authorize 判成跨源。
const BROWSER = { 'sec-fetch-site': 'same-origin' }

function parseJson(text) {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

/** 全局 fetch（Host 头由 URL 决定，无法伪造）。 */
async function call(path, init = {}) {
  const res = await fetch(BASE + path, { ...init, headers: { ...BROWSER, ...(init.headers || {}) } })
  const text = await res.text()
  return { status: res.status, type: res.headers.get('content-type') || '', text, json: parseJson(text) }
}

/** 裸 node:http：fetch 不允许覆写 Host，伪造 Host 的场景（鉴权）走这里。 */
function rawCall(path, { method = 'GET', headers = {}, body = null } = {}) {
  return new Promise((resolve, reject) => {
    const req = httpRequest(
      { host: '127.0.0.1', port: PORT, path, method, headers: { connection: 'close', ...headers } },
      (res) => {
        let text = ''
        res.setEncoding('utf8')
        res.on('data', (d) => (text += d))
        res.on('end', () => resolve({ status: res.statusCode, type: res.headers['content-type'] || '', text, json: parseJson(text) }))
      },
    )
    req.on('error', reject)
    req.end(body === null ? undefined : body)
  })
}

/** SSE：读到首个完整帧就中止（AbortController + reader.cancel），别让进程挂住。 */
async function readFirstFrame(path, headers = {}) {
  const ac = new AbortController()
  const res = await fetch(BASE + path, { headers: { ...BROWSER, ...headers }, signal: ac.signal })
  const out = { status: res.status, type: res.headers.get('content-type') || '', text: '' }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  const deadline = Date.now() + 5_000
  try {
    while (!out.text.includes('\n\n') && Date.now() < deadline) {
      const { value, done } = await reader.read()
      if (done) break
      out.text += decoder.decode(value, { stream: true })
    }
  } catch (e) {
    out.error = e.message
  } finally {
    try {
      await reader.cancel()
    } catch {
      /* 已关闭 */
    }
    ac.abort()
  }
  return out
}

console.log('\n1. 路由注册与宿主匹配语义')
{
  assert(logs.some((l) => String(l).includes('routes registered')), '注册成功并留下日志（没走 webServer unavailable 分支）', brief(logs, 160))
  const table = host.routes()
  assert(table.length === 6, `注册 6 条 API 路由（实际 ${table.length}）`, table.map((r) => `${r.kind}:${r.path}`).join(' '))
  assert(table.filter((r) => r.kind === 'exact').length === 5, 'exact 路由 5 条（health/stats/settings/artifacts/events）')
  assert(table.some((r) => r.kind === 'prefix' && r.path === '/formatforge/api/artifacts'), 'prefix 路由 1 条：/formatforge/api/artifacts（GET/POST/DELETE 共用）')
  for (const r of table.filter((x) => x.kind === 'prefix')) {
    assert(!r.path.endsWith('/'), `prefix 路径不带尾斜杠：${r.path}`, r.path)
  }
  assert(host.match('/formatforge/api/health')?.kind === 'exact', '宿主 match：/health 命中 exact 表')
  assert(host.match('/formatforge/api/artifacts')?.kind === 'exact', '宿主 match：裸 /artifacts 命中 exact 表')
  assert(host.match(`/formatforge/api/artifacts/${RESULT_ID}`)?.kind === 'prefix', '宿主 match：/artifacts/<id> 命中 prefix 表（不是 fallback）')
  assert(host.match(`/formatforge/api/artifacts/${RESULT_ID}/content`)?.kind === 'prefix', '宿主 match：/artifacts/<id>/content 命中 prefix 表')
  assert(host.match('/formatforge/api/artifactsX') === undefined, '宿主 match：/artifactsX 不抢（无匹配 → fallback）')

  // 复刻保真度自检：宿主 register 的重复检测与 disposer 语义
  let dup = null
  try {
    host.register({ kind: 'exact', path: '/formatforge/api/health', handler: () => {} })
  } catch (e) {
    dup = e
  }
  assert(dup !== null, '复刻宿主 register：重复 (kind,path) 抛错（所以多种动作只能共用一个 prefix 路由）', dup ? dup.message : '没有抛错')
  const tmpDispose = host.register({ kind: 'prefix', path: '/formatforge/api/tmp', handler: () => {} })
  assert(typeof tmpDispose === 'function' && host.routes().length === 7, '复刻宿主 register：返回 disposer', String(host.routes().length))
  tmpDispose()
  assert(host.routes().length === 6, 'disposer 调用后路由表复原', String(host.routes().length))
}

console.log('\n2. 读接口（真实 HTTP）')
{
  const health = await call('/formatforge/api/health')
  assert(health.status === 200, 'GET /health → 200', `status=${health.status} body=${health.text.slice(0, 120)}`)
  assert(health.type.startsWith('application/json'), 'health 的 content-type 是 application/json', health.type)
  assert(health.json?.ok === true && health.json.data.plugin === 'dsh-formatforge', 'health 返回结构化 JSON（ok:true + plugin）', health.text.slice(0, 160))
  assert(health.json?.data?.files === 1, 'health 报告收件箱 1 个产物文件', brief(health.json?.data, 160))
  assert(host.stats().arity === 2, '宿主分发器只传 (req, res) 两参（复刻 lib/index.js 调用约定）', String(host.stats().arity))

  const statsRes = await call('/formatforge/api/stats')
  assert(statsRes.status === 200 && statsRes.json?.ok === true, 'GET /stats → 200 + ok:true', `status=${statsRes.status} body=${statsRes.text.slice(0, 120)}`)
  assert(statsRes.json?.data?.stats?.total === 1, 'stats 报告 1 条产物（索引库可读）', brief(statsRes.json?.data?.stats))

  const settingsRes = await call('/formatforge/api/settings')
  assert(settingsRes.status === 200 && settingsRes.json?.ok === true, 'GET /settings → 200 + ok:true', `status=${settingsRes.status}`)
  assert(settingsRes.json?.data?.prefs?.panelLimit === 50, 'GET /settings 默认 panelLimit=50', brief(settingsRes.json?.data, 160))

  const listRes = await call('/formatforge/api/artifacts?limit=5')
  assert(listRes.status === 200 && listRes.json?.ok === true, 'GET /artifacts?limit=5 → 200 + ok:true', `status=${listRes.status} body=${listRes.text.slice(0, 120)}`)
  assert(
    Array.isArray(listRes.json?.data?.rows) && listRes.json.data.rows.length === 1 && listRes.json.data.rows[0].id === RESULT_ID,
    '列表命中刚索引的产物（query 经真实 HTTP 传参）',
    brief(listRes.json?.data),
  )

  const searchRes = await call(`/formatforge/api/artifacts?q=${encodeURIComponent('付款')}&limit=5`)
  assert(searchRes.status === 200 && searchRes.json?.data?.rows?.length === 1, '中文检索词命中 1 条', brief(searchRes.json?.data, 160))
  const emptyRes = await call(`/formatforge/api/artifacts?q=${encodeURIComponent('查无此词')}&limit=5`)
  assert(emptyRes.status === 200 && emptyRes.json?.data?.rows?.length === 0, '无命中检索返回 0 行（不是 404/500）', `status=${emptyRes.status}`)
}

console.log('\n3. 单条产物（本次事故的核心回归点：prefix 不能带尾斜杠）')
{
  const one = await call(`/formatforge/api/artifacts/${RESULT_ID}`)
  assert(one.status === 200, 'GET /artifacts/<真实id> → 200（没落到 SPA fallback 的 404）', `status=${one.status} body=${one.text.slice(0, 120)}`)
  assert(one.json !== null && one.json.ok === true, '单条响应是结构化 JSON（非空 body）', one.text.slice(0, 120))
  assert(
    one.json?.data?.id === RESULT_ID && one.json.data.parser === 'txt' && one.json.data.source === SOURCE,
    '元数据 id/parser/source 正确',
    brief(one.json?.data),
  )
  assert(one.json?.data?.chars === CONTENT.length, `chars 等于正文长度（${CONTENT.length}）`, String(one.json?.data?.chars))

  const stemRes = await call(`/formatforge/api/artifacts/${encodeURIComponent(STEM)}`)
  assert(stemRes.status === 200 && stemRes.json?.data?.id === RESULT_ID, '按 stem 查（非 ASCII 路径 percent-encoded）→ 200', `status=${stemRes.status}`)

  const contentRes = await call(`/formatforge/api/artifacts/${RESULT_ID}/content?max_chars=200`)
  assert(contentRes.status === 200 && contentRes.json?.ok === true, 'GET /artifacts/<id>/content → 200', `status=${contentRes.status}`)
  assert(String(contentRes.json?.data?.content || '').includes('付款条款'), '正文非空且内容正确', brief(contentRes.json?.data, 160))
  assert(
    contentRes.json?.data?.total_chars === CONTENT.length && contentRes.json?.data?.md_path === MD_PATH,
    'content 带上 total_chars 与 md_path',
    brief(contentRes.json?.data, 220),
  )

  const missing = await call('/formatforge/api/artifacts/no-such-id')
  assert(missing.status === 404, 'GET /artifacts/no-such-id → 404', `status=${missing.status}`)
  assert(missing.json?.code === 4002, '404 body 是 JSON code 4002（我们的 404）', missing.text.slice(0, 160))
  assert(missing.text.length > 0, '我们的 404 不是空 body —— 可与宿主 fallback 的 404 区分', JSON.stringify(missing.text).slice(0, 80))

  const methodNotAllowed = await call(`/formatforge/api/artifacts/${RESULT_ID}`, { method: 'PUT' })
  assert(methodNotAllowed.status === 405 && methodNotAllowed.json?.ok === false, 'PUT /artifacts/<id> → 405 + JSON', `status=${methodNotAllowed.status}`)
}

console.log('\n4. 写接口（retry / delete / settings PUT）')
{
  const retry = await call(`/formatforge/api/artifacts/${RESULT_ID}/retry`, { method: 'POST' })
  assert(retry.status === 200 && retry.json?.data?.retry === true, 'POST /artifacts/<id>/retry → 200 + retry:true', `status=${retry.status} body=${retry.text.slice(0, 120)}`)
  assert(!existsSync(JSON_PATH), 'retry 删掉了旧 .ff.json（等 watcher 重转）')
  assert(forgot.includes(STEM), 'retry 通知 watcher 忘记该文件', JSON.stringify(forgot))

  writeArtifact()
  assert(cli(['inbox', 'index', '--artifact', JSON_PATH]).ok === true, 'CLI: 复原产物并重新入索引')

  const del = await call(`/formatforge/api/artifacts/${RESULT_ID}`, { method: 'DELETE' })
  assert(del.status === 200 && del.json?.data?.deleted === true, 'DELETE /artifacts/<id> → 200 + deleted:true', `status=${del.status} body=${del.text.slice(0, 120)}`)
  assert(existsSync(JSON_PATH), '软删除不动磁盘文件（文件才是真相源）')
  const afterDel = await call('/formatforge/api/artifacts?limit=5')
  assert(afterDel.json?.data?.rows?.length === 0, '删除后不再出现在列表里', brief(afterDel.json?.data, 160))

  const put = await call('/formatforge/api/settings', {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ panelLimit: 200 }),
  })
  assert(put.status === 200 && put.json?.data?.prefs?.panelLimit === 200, 'PUT /settings（真实 JSON body）→ 200 + 回显新值', `status=${put.status} body=${put.text.slice(0, 160)}`)
  const reread = await call('/formatforge/api/settings')
  assert(reread.json?.data?.prefs?.panelLimit === 200, '再 GET /settings 读到新值（已持久化）', brief(reread.json?.data, 160))
  assert(cli(['inbox', 'prefs']).data.prefs.panelLimit === 200, 'CLI 侧读到同一个值（单一存储）')

  const badJson = await call('/formatforge/api/settings', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: '{not json' })
  assert(badJson.status === 400 && badJson.json?.ok === false, '非法 JSON 的 PUT → 400 + JSON 错误体', `status=${badJson.status} body=${badJson.text.slice(0, 160)}`)
  const arrayJson = await call('/formatforge/api/settings', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: '[1,2,3]' })
  assert(arrayJson.status === 400, 'JSON 数组（非对象）→ 400', `status=${arrayJson.status}`)
}

console.log('\n4b. 大产物按 id 取回（正文 > 64K 字符时 id 落在"前 64KB"窗口之外）')
{
  // 复现条件：payload 里 content 在前、meta.result_id 在后，watcher 又 pretty-print 落盘。
  // 修复前：findArtifact 只扫前 64KB → 详情/正文/重转/删除全部 404（接口本身是好的）。
  const BIG_ID = 'cvt20261001120001bigdoc'
  const BIG_STEM = '大文档2024'
  const BIG_CONTENT = `# 大文档\n\n${'中文正文行，用来把 result_id 挤出 64KB 窗口。\n'.repeat(3000)}`
  const bigJson = join(HOME, 'inbox', `${BIG_STEM}.ff.json`)
  writeFileSync(join(HOME, 'inbox', `${BIG_STEM}.txt`), '大文档正文\n', 'utf8')
  writeFileSync(
    bigJson,
    JSON.stringify({ ok: true, code: 200, data: { content: BIG_CONTENT, format: 'markdown', meta: { parser: 'txt', file_size: BIG_CONTENT.length, result_id: BIG_ID, confidence: 0.9 } } }, null, 2),
    'utf8',
  )
  writeFileSync(join(HOME, 'inbox', `${BIG_STEM}.ff.md`), BIG_CONTENT, 'utf8')
  const bigText = readFileSync(bigJson, 'utf8')
  assert(bigText.length > 64 * 1024, `大产物 JSON 超过 64KB（实际 ${bigText.length} 字符）`)
  assert(!bigText.slice(0, 64 * 1024).includes(`"result_id": "${BIG_ID}"`), '复现条件成立：result_id 落在前 64KB 之外')
  assert(cli(['inbox', 'index', '--artifact', bigJson]).ok === true, 'CLI: 大产物已进索引')

  const bigOne = await call(`/formatforge/api/artifacts/${BIG_ID}`)
  assert(bigOne.status === 200 && bigOne.json?.ok === true, '大产物 GET /artifacts/<id> → 200（先查库，与正文大小无关）', `status=${bigOne.status} body=${bigOne.text.slice(0, 140)}`)
  assert(bigOne.json?.data?.chars === BIG_CONTENT.length, `大产物 chars 正确（${BIG_CONTENT.length}）`, String(bigOne.json?.data?.chars))

  const bigContent = await call(`/formatforge/api/artifacts/${BIG_ID}/content?max_chars=300`)
  assert(bigContent.status === 200 && bigContent.json?.data?.content?.length === 300, '大产物 /content → 200（300 字窗口）', `status=${bigContent.status}`)

  const bigDel = await call(`/formatforge/api/artifacts/${BIG_ID}`, { method: 'DELETE' })
  assert(bigDel.status === 200 && bigDel.json?.data?.deleted === true, '大产物 DELETE → 200（按 id 命中）', `status=${bigDel.status} body=${bigDel.text.slice(0, 140)}`)
}

console.log('\n5. 鉴权（我们的路由在宿主围栏之外，必须自己挡）')
{
  const badHost = await rawCall('/formatforge/api/stats', { headers: { host: 'evil.example.com', ...BROWSER } })
  assert(badHost.status === 403, '非 loopback Host 头 → 403', `status=${badHost.status}`)
  assert(badHost.json?.error?.kind === 'forbidden_host', '403 body 是结构化 JSON（forbidden_host）', badHost.text.slice(0, 160))

  const rebind = await rawCall('/formatforge/api/artifacts?limit=5', { headers: { host: 'localhost.evil.com', ...BROWSER } })
  assert(rebind.status === 403, 'DNS rebinding 类主机名（localhost.evil.com）→ 403', `status=${rebind.status}`)

  const v6Host = await rawCall('/formatforge/api/health', { headers: { host: `[::1]:${PORT}`, ...BROWSER } })
  assert(
    (v6Host.status === 403 && v6Host.json?.error?.kind === 'forbidden_host') || (v6Host.status === 200 && v6Host.json?.ok === true),
    'Host 为 [::1]:<port> 时要么按 loopback 放行、要么明确 forbidden_host（不能是兜底空 body）',
    `status=${v6Host.status} body=${v6Host.text.slice(0, 100)}`,
  )

  const crossSite = await call('/formatforge/api/stats', { headers: { 'sec-fetch-site': 'cross-site', origin: 'https://evil.example.com' } })
  assert(crossSite.status === 401, '跨源且无 token → 401', `status=${crossSite.status}`)
  assert(crossSite.json?.error?.kind === 'unauthorized', '401 body 是结构化 JSON（unauthorized）', crossSite.text.slice(0, 160))

  const crossSiteDelete = await call(`/formatforge/api/artifacts/${RESULT_ID}`, {
    method: 'DELETE',
    headers: { 'sec-fetch-site': 'cross-site', origin: 'https://evil.example.com' },
  })
  assert(crossSiteDelete.status === 401, '跨源的 DELETE → 401（鉴权先于写操作）', `status=${crossSiteDelete.status}`)
  assert(existsSync(JSON_PATH), '被挡下的 DELETE 没碰磁盘', String(existsSync(JSON_PATH)))

  assert(existsSync(TOKEN_FILE), 'token 文件已生成：<FF_HOME>/api-token')
  // 失败路径下 token 文件可能还不存在：读不到就给空串，让后面的断言照常报告而不是抛异常
  const token = existsSync(TOKEN_FILE) ? readFileSync(TOKEN_FILE, 'utf8').trim() : ''
  assert(token.length >= 32, 'token 足够长', String(token.length))

  const byHeader = await call('/formatforge/api/stats', { headers: { 'sec-fetch-site': 'none', 'x-ff-token': token } })
  assert(byHeader.status === 200 && byHeader.json?.ok === true, '带 x-ff-token 的脚本请求 → 200', `status=${byHeader.status}`)
  const byQuery = await call(`/formatforge/api/health?token=${token}`, { headers: { 'sec-fetch-site': 'none' } })
  assert(byQuery.status === 200, 'token 走 query（?token=）→ 200', `status=${byQuery.status}`)
  const wrongToken = await call('/formatforge/api/stats', { headers: { 'sec-fetch-site': 'none', 'x-ff-token': 'nope' } })
  assert(wrongToken.status === 401, '错误 token → 401', `status=${wrongToken.status}`)

  // 桌面端（Electron 渲染进程 / 主进程代理）**不带** Sec-Fetch-* 与 Origin —— 线上真实翻车点：
  // 面板首屏就是这样被 401 挡下的。浏览器发起的跨站请求一定带这两个头，所以"两者都没有"判非网页攻击面。
  const appLikeRead = await rawCall('/formatforge/api/stats', { headers: {} })
  assert(appLikeRead.status === 200, '无浏览器信号（桌面端）读 → 200', `status=${appLikeRead.status} body=${appLikeRead.text.slice(0, 120)}`)

  const appLikeNoMarker = await rawCall('/formatforge/api/settings', {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ panelLimit: 150 }),
  })
  assert(appLikeNoMarker.status === 401, '桌面端写操作缺 x-ff-client → 401', `status=${appLikeNoMarker.status}`)
  const unchanged = await call('/formatforge/api/settings')
  assert(unchanged.json?.data?.prefs?.panelLimit !== 150, '被挡下的写没有落库', brief(unchanged.json?.data?.prefs))

  const appLikeWrite = await rawCall('/formatforge/api/settings', {
    method: 'PUT',
    headers: { 'content-type': 'application/json', 'x-ff-client': 'panel' },
    body: JSON.stringify({ panelLimit: 150 }),
  })
  assert(appLikeWrite.status === 200, '桌面端写操作带 x-ff-client: panel → 200', `status=${appLikeWrite.status} body=${appLikeWrite.text.slice(0, 120)}`)
  const persisted = await call('/formatforge/api/settings')
  assert(persisted.json?.data?.prefs?.panelLimit === 150, '带标记头的写真的落库了（单一存储）', brief(persisted.json?.data?.prefs))
  await call('/formatforge/api/settings', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ panelLimit: 200 }) })
}

console.log('\n6. SSE 事件流（真实 socket，拿到首帧后中止）')
{
  const sse = await readFirstFrame('/formatforge/api/events')
  assert(sse.status === 200, 'GET /events → 200', `status=${sse.status}${sse.error ? ' error=' + sse.error : ''}`)
  assert(sse.type.startsWith('text/event-stream'), 'content-type 以 text/event-stream 开头', sse.type)
  assert(sse.text.includes('event: hello'), '首帧是 event: hello', JSON.stringify(sse.text.slice(0, 120)))
  const dataLine = sse.text.split('\n').find((l) => l.startsWith('data: '))
  const hello = parseJson(String(dataLine).slice(6))
  assert(hello !== null && typeof hello.count === 'number', 'hello 帧带 JSON 快照（count）', String(dataLine).slice(0, 120))
  assert(hello !== null && typeof hello.newest === 'number', 'hello 快照含 newest mtime', String(dataLine).slice(0, 120))

  const afterSse = await call('/formatforge/api/health')
  assert(afterSse.status === 200, '中止 SSE 后服务器仍正常服务', `status=${afterSse.status}`)
}

console.log('\n7. 结构不变量与 fallback 对照')
{
  const before = host.stats().fallback
  const artifactsX = await call('/formatforge/api/artifactsX')
  assert(artifactsX.status === 404, 'GET /artifactsX → 404（同前缀但不是子路径，prefix 不抢）', `status=${artifactsX.status}`)
  assert(artifactsX.text === '', 'fallback 的 404 是空 body（正是我们的 4002 404 要区分的对象）', JSON.stringify(artifactsX.text).slice(0, 80))
  assert(host.stats().fallback === before + 1, '/artifactsX 确实交给了 SPA fallback（计数 +1）', `fallback=${host.stats().fallback}`)
  assert(host.stats().hostCatch400 === 0, '没有任何 handler 抛错（宿主 catch → 400 空 body 分支 0 次）', String(host.stats().hostCatch400))
}

console.log('\n8. 复刻保真度自检：把线上那两种写法注进对照宿主，确认套件看得见')
{
  // 这一节不碰产品代码：只在**对照宿主**（同款 mini host）上注册两个"错误写法"，
  // 断言它们产生与线上完全一致的失败信号。没有这一节，上面的全绿无法证明套件有感知力。
  const probe = createMiniHost()
  const probePort = await probe.listen()
  const probeBase = `http://127.0.0.1:${probePort}`

  // 注入 A：handler 形参带 url、且真的去读它（线上写法）→ 宿主只传两参 → TypeError → 400 空 body
  probe.register({
    kind: 'exact',
    path: '/probe/third-arg',
    handler: async (_req, res, url) => {
      const limit = url.searchParams.get('limit') // 线上写法：进 handler 先读第三参
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ limit }))
    },
  })
  const buggy = await fetch(`${probeBase}/probe/third-arg?limit=5`)
  const buggyText = await buggy.text()
  assert(buggy.status === 400 && buggyText === '', '注入 A（handler 依赖第三参 url）→ 复刻出线上的 400 空 body', `status=${buggy.status} body=${JSON.stringify(buggyText).slice(0, 80)}`)
  assert(probe.stats().hostCatch400 === 1, '注入 A 走的是宿主 catch 分支（线上那次事故的分支）', String(probe.stats().hostCatch400))

  // 注入 B：prefix 带尾斜杠 → 真实 /artifacts/<id> 匹配不到 → 落到 fallback 的 404 空 body
  probe.register({
    kind: 'prefix',
    path: '/formatforge/api/artifacts/',
    handler: (_req, res) => {
      res.writeHead(200)
      res.end('hit')
    },
  })
  const slashMiss = await fetch(`${probeBase}/formatforge/api/artifacts/${RESULT_ID}`)
  const slashMissText = await slashMiss.text()
  assert(probe.match(`/formatforge/api/artifacts/${RESULT_ID}`) === undefined, '注入 B：带尾斜杠的 prefix 匹配不到 /artifacts/<id>')
  assert(probe.match(`/formatforge/api/artifacts//${RESULT_ID}`)?.path === '/formatforge/api/artifacts/', '注入 B：只有 /artifacts//<id> 才命中（线上 404 的成因）')
  assert(slashMiss.status === 404 && slashMissText === '', '注入 B → 真实请求变成 fallback 的 404 空 body（不是我们 JSON 4002 的 404）', `status=${slashMiss.status} body=${JSON.stringify(slashMissText).slice(0, 80)}`)

  await probe.close()
  await new Promise((resolve) => setTimeout(resolve, 50))
  assert(probe.socketCount() === 0, '对照宿主收尾：连接已销毁', String(probe.socketCount()))
}

console.log('\n9. 收尾（disposer / socket / 定时器）')
{
  for (const dispose of disposers) {
    try {
      dispose()
    } catch {
      /* noop */
    }
  }
  assert(host.routes().length === 0, 'disposer 回收后路由表清空（宿主 disposer 语义）', String(host.routes().length))

  await host.close()
  assert(host.listening() === false, 'server.close() 后不再监听')
  await new Promise((resolve) => setTimeout(resolve, 50))
  assert(host.socketCount() === 0, '所有连接已销毁（SSE 已 abort、keep-alive 已断开）', String(host.socketCount()))

  let removed = true
  try {
    rmSync(HOME, { recursive: true, force: true })
  } catch {
    removed = false
  }
  assert(removed && !existsSync(HOME), '临时 FF_HOME 已删除')
}

// 事件循环自检：socket 与定时器都清掉后，进程应当自行退出。看门狗刻意 unref ——
// 正常清理时它既不阻止退出也不会触发；只有遗留 handle（例如 SSE 轮询没清）才会让它响。
const exitGuard = setTimeout(() => {
  console.error('  FAIL 清理后进程未能自行退出 —— 仍有未关闭的 socket / 定时器')
  console.error(`\nHOST-HTTP-FAIL: ${failures + 1} assertion(s) failed`)
  process.exit(1)
}, 10_000)
exitGuard.unref?.()

if (failures > 0) {
  console.error(`\nHOST-HTTP-FAIL: ${failures} assertion(s) failed`)
  process.exit(1)
}
console.log(`\nHOST-HTTP-OK: ${passed} 条断言全绿（真实 node:http × 宿主语义复刻；进程可自行退出）`)
