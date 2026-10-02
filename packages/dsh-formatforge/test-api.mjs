// test-api.mjs — /formatforge/api/* 的路由/鉴权/读写契约（v3.0.0）。
//
// 用假 webServer + 假 req/res 直接调 handler，不需要真宿主；真机验证另见
// scripts/verify-install.py 与 UI_DB_PLAN.md §7 的实机清单。
//
// 重点覆盖**安全**：宿主鉴权围栏只保护 `/api`，我们的路由在围栏外，
// 所以必须自己挡住"非 loopback Host / 非同源 / 无 token"的请求。
//
// 用法：node packages/dsh-formatforge/test-api.mjs

import { mkdirSync, writeFileSync, readFileSync, statSync, rmSync, existsSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'
import { execFileSync } from 'node:child_process'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = dirname(dirname(HERE))
/** 解释器：FF_PYTHON 优先，其次仓库 venv，最后 PATH 上的 python（CI 用）。 */
const PY = (() => {
  const venv = process.platform === 'win32' ? join(REPO_ROOT, '.venv-fg', 'Scripts', 'python.exe') : join(REPO_ROOT, '.venv-fg', 'bin', 'python')
  if (process.env.FF_PYTHON) return process.env.FF_PYTHON
  if (existsSync(venv)) return venv
  return process.platform === 'win32' ? 'python' : 'python3'
})()

let failures = 0
const ok = (label) => console.log('  ok   ' + label)
const fail = (label, detail) => {
  failures += 1
  console.error('  FAIL ' + label + (detail === undefined ? '' : ' — ' + detail))
}
const assert = (cond, label, detail) => (cond ? ok(label) : fail(label, detail))

const HOME = join(tmpdir(), `ff-api-test-${Date.now()}`)
mkdirSync(join(HOME, 'inbox'), { recursive: true })
process.env.FF_HOME = HOME
delete process.env.FF_DB
process.env.PYTHONPATH = REPO_ROOT

const SOURCE = '合同2024.txt'
const CONTENT = '# 转换结果\n\n付款条款：月结30天\n合同编号 HT-2024-001\n'
const RESULT_ID = 'cvt20261001120000abcdef'

function cli(args) {
  const out = execFileSync(PY, ['-m', 'formatforge', ...args], {
    cwd: REPO_ROOT,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
    encoding: 'utf8',
  })
  return JSON.parse(out.trim().split('\n').find((l) => l.startsWith('{')))
}

// 造产物 + 建索引（走真实 CLI，顺便验证 Python 侧）
mkdirSync(join(HOME, 'inbox'), { recursive: true })
writeFileSync(join(HOME, 'inbox', SOURCE), '付款条款：月结30天\n', 'utf8')
const doc = {
  ok: true,
  code: 200,
  data: { content: CONTENT, format: 'markdown', meta: { parser: 'txt', file_size: 60, result_id: RESULT_ID, confidence: 0.95 } },
}
const JSON_PATH = join(HOME, 'inbox', '合同2024.ff.json')
writeFileSync(JSON_PATH, JSON.stringify(doc, null, 2), 'utf8')
writeFileSync(join(HOME, 'inbox', '合同2024.ff.md'), CONTENT, 'utf8')
assert(cli(['inbox', 'init']).ok === true, 'CLI: inbox init 成功')
assert(cli(['inbox', 'index', '--artifact', JSON_PATH]).data.indexed[0] === RESULT_ID, 'CLI: 产物已进索引')

const { registerApiRoutes, requestUrl, findArtifact, isLoopbackHostHeader } = await import('./http/api.mjs')

// ── 假 host：webServer 对重复 (kind,path) 抛错（与真宿主一致） ───────────────
const routes = []
const webServer = {
  register(route) {
    if (routes.some((r) => r.kind === route.kind && r.path === route.path)) {
      throw new Error(`duplicate route ${route.kind} ${route.path}`)
    }
    routes.push(route)
    return () => {
      const i = routes.indexOf(route)
      if (i >= 0) routes.splice(i, 1)
    }
  },
}
const ctx = { get: (name) => (name === 'webServer' ? webServer : null) }
const forgot = []
const watcher = { forget: (stem) => { forgot.push(stem); return true } }

let disposers = []
try {
  disposers = registerApiRoutes(ctx, { repoRoot: REPO_ROOT, timeoutMs: 30_000, log: () => {}, watcher })
} catch (e) {
  fail('registerApiRoutes 抛出', e.message)
}

console.log('\n1. 路由注册')
assert(routes.length === 6, `注册 6 条路由（health/stats/settings/artifacts×2/events），实际 ${routes.length}`, JSON.stringify(routes.map((r) => `${r.kind}:${r.path}`)))
assert(routes.some((r) => r.path === '/formatforge/api/artifacts' && r.kind === 'exact'), 'list 路由是 exact')
assert(routes.some((r) => r.path === '/formatforge/api/artifacts' && r.kind === 'prefix'), '单条路由是 prefix（GET/POST/DELETE 共用一个，避免重复注册）')
assert(typeof disposers.length === 'number', 'disposer 列表可回收')

const routeOf = (kind, path) => routes.find((r) => r.kind === kind && r.path === path)

console.log('\n1b. 宿主 prefix 匹配语义（前缀不能带尾斜杠）')
{
  for (const r of routes.filter((x) => x.kind === 'prefix')) {
    assert(!r.path.endsWith('/'), `prefix 路径不带尾斜杠：${r.path}`, r.path)
  }
  const hit = (p) => {
    const m = hostMatch(routes, p)
    return m ? `${m.kind}:${m.path}` : '(fallback 404)'
  }
  assert(hit('/formatforge/api/artifacts') === 'exact:/formatforge/api/artifacts', '裸列表路径命中 exact 表', hit('/formatforge/api/artifacts'))
  assert(hit('/formatforge/api/artifacts/cvt123') === 'prefix:/formatforge/api/artifacts', '单条路径命中 prefix', hit('/formatforge/api/artifacts/cvt123'))
  assert(hit('/formatforge/api/artifacts/cvt123/content') === 'prefix:/formatforge/api/artifacts', '正文子路径命中 prefix', hit('/formatforge/api/artifacts/cvt123/content'))
  assert(hit('/formatforge/api/artifacts/cvt123/retry') === 'prefix:/formatforge/api/artifacts', 'retry 子路径命中 prefix', hit('/formatforge/api/artifacts/cvt123/retry'))
  assert(hit('/formatforge/api/artifactsX') === '(fallback 404)', '同前缀但非子路径不抢（artifactsX）', hit('/formatforge/api/artifactsX'))
  assert(hit('/formatforge/api/health') === 'exact:/formatforge/api/health', 'API 健康检查命中 exact', hit('/formatforge/api/health'))
  // 本套件只注册 API 路由；上传/健康路由由 test-plugin-boot.mjs 覆盖
  assert(hit('/formatforge/health') === '(fallback 404)', '非本套件注册的路径不在此表内', hit('/formatforge/health'))
}

console.log('\n1c. 行归一化（库列名 → 面板消费的客户端形状）')
{
  const { toClientRow } = await import('./services/inbox-db.mjs')
  const raw = toClientRow({ id: 'cvt1', source_name: '合同2024.txt', source_bytes: 467, created_at: 1790907982 })
  assert(raw.source === '合同2024.txt', 'source_name → source', String(raw.source))
  assert(raw.size_bytes === 467, 'source_bytes → size_bytes', String(raw.size_bytes))
  assert(Date.parse(raw.forged_at) === 1790907982 * 1000, 'unix 秒 created_at → ISO forged_at', String(raw.forged_at))
  assert(raw.source_name === '合同2024.txt', '原始列名保留（无损）')
  const passthrough = toClientRow({ source: 'a.txt', size_bytes: 5, forged_at: '2026-10-02T00:00:00.000Z' })
  assert(passthrough.source === 'a.txt' && passthrough.forged_at === '2026-10-02T00:00:00.000Z', '已是客户端形状时原样透传')
  assert(Date.parse(toClientRow({ id: 'y', created_at: 1790907982000 }).forged_at) === 1790907982000, '毫秒时间戳也认')
  assert(toClientRow(null) === null && toClientRow(undefined) === undefined, 'null/undefined 安全')
}

function fakeReq({ method = 'GET', headers = {}, url = '/' } = {}) {
  const listeners = {}
  return {
    method,
    url,
    headers: { host: '127.0.0.1:19387', 'sec-fetch-site': 'same-origin', ...headers },
    on(event, fn) { listeners[event] = fn },
    _listeners: listeners,
  }
}
function fakeRes() {
  const state = { status: 0, headers: null, body: null, chunks: [] }
  return {
    state,
    writeHead(status, headers) { state.status = status; state.headers = headers },
    write(chunk) { state.chunks.push(String(chunk)) },
    end(body) { if (body !== undefined) state.body = String(body) },
  }
}
/**
 * 复刻宿主路由匹配：先查 exact 表，再在 prefix 表里「最长前缀胜」，
 * 命中条件是 `pathname === prefix || pathname.startsWith(prefix + '/')`
 * （`@deepseek-ai/dsh-host-webserver/lib/index.js` `match()`）。
 * 少了这层仿真，注册路径写错（例如前缀带尾斜杠）在测试里完全看不出来 —— 线上会静默落到 SPA fallback 变 404。
 */
function hostMatch(table, pathname) {
  const exact = table.find((r) => r.kind === 'exact' && r.path === pathname)
  if (exact) return exact
  let best
  for (const route of table) {
    if (route.kind !== 'prefix') continue
    if (pathname !== route.path && !pathname.startsWith(`${route.path}/`)) continue
    if (!best || route.path.length > best.path.length) best = route
  }
  return best
}

// 宿主 @deepseek-ai/dsh-host-webserver 以 `await route.handler(req, res)` 调用
// （lib/index.js），**不传第三个参数**。测试必须照做：多传 URL 会掩盖
// “handler 依赖第三参 → 线上 TypeError → 宿主 400 空 body” 这类缺陷。
// 同时断言「按 URL 匹配到的必须就是我们指定的那条路由」，把 prefix 语义也钉住。
const call = async (kind, path, req, url) => {
  const target = new URL(url, 'http://127.0.0.1:19387')
  req.url = target.pathname + target.search
  const matched = hostMatch(routes, target.pathname)
  assert(
    Boolean(matched) && matched.kind === kind && matched.path === path,
    `宿主 match(${target.pathname}) → ${kind === 'exact' ? 'exact' : 'prefix'}:${path}`,
    matched ? `实际落到 ${matched.kind}:${matched.path}` : '无匹配（会落到 SPA fallback → 404）',
  )
  if (!matched) return { status: 404, headers: null, body: '', chunks: [] }
  const res = fakeRes()
  await matched.handler(req, res)
  return res.state
}

console.log('\n2. 鉴权（我们的路由在宿主围栏之外，必须自己挡）')
{
  const url = 'http://127.0.0.1:19387/formatforge/api/stats'
  const forbidden = await call('exact', '/formatforge/api/stats', fakeReq({ headers: { host: 'evil.example.com' } }), url)
  assert(forbidden.status === 403, '非 loopback Host → 403', JSON.stringify(forbidden.body))

  const unauth = await call(
    'exact',
    '/formatforge/api/stats',
    fakeReq({ headers: { 'sec-fetch-site': 'cross-site', origin: 'https://evil.example.com' } }),
    url,
  )
  assert(unauth.status === 401, '跨源且无 token → 401', JSON.stringify(unauth.body))

  const sameOrigin = await call('exact', '/formatforge/api/stats', fakeReq({}), url)
  assert(sameOrigin.status === 200, '同源浏览器请求 → 200')

  // IPv6 loopback 字面量：`split(':')` 式解析会把 '[::1]:19387' 判成 '['，这里钉死三种写法
  for (const host of ['[::1]:19387', '[::1]', '::1']) {
    const v6 = await call('exact', '/formatforge/api/stats', fakeReq({ headers: { host } }), url)
    assert(v6.status === 200, `IPv6 loopback Host（${host}）放行`, JSON.stringify(v6.body).slice(0, 120))
  }
  const v6Evil = await call('exact', '/formatforge/api/stats', fakeReq({ headers: { host: 'localhost.evil.com:80' } }), url)
  assert(v6Evil.status === 403, '带端口的外域 Host 仍被拒（403）', String(v6Evil.status))
  assert(isLoopbackHostHeader('127.0.0.1:19387') === true && isLoopbackHostHeader('evil.example.com') === false, 'isLoopbackHostHeader 基本判定')

  const token = (await import('node:fs')).readFileSync(join(HOME, 'api-token'), 'utf8').trim()
  const withToken = await call(
    'exact',
    '/formatforge/api/stats',
    fakeReq({ headers: { 'sec-fetch-site': 'none', 'x-ff-token': token } }),
    url,
  )
  assert(withToken.status === 200, '带 token 的脚本请求 → 200')
  assert(token.length >= 32, 'token 足够长', String(token.length))

  const badToken = await call(
    'exact',
    '/formatforge/api/stats',
    fakeReq({ headers: { 'sec-fetch-site': 'none', 'x-ff-token': 'nope' } }),
    url,
  )
  assert(badToken.status === 401, '错误 token → 401')

  // 桌面端（Electron 渲染进程 / 主进程代理）的 fetch **不带** Sec-Fetch-* 与 Origin，
  // 这是线上真实翻车点：面板首屏就是被这条规则挡成 401 的。浏览器发起的跨站请求一定带这两个头，
  // 所以"两者都没有"可以判定不是网页攻击面 → 读放行。
  const appLikeRead = await call('exact', '/formatforge/api/stats', fakeReq({ headers: { 'sec-fetch-site': undefined } }), url)
  assert(appLikeRead.status === 200, '桌面端无浏览器信号（无 Sec-Fetch-*/Origin）读 → 200', JSON.stringify(appLikeRead.body).slice(0, 160))

  const opaqueRead = await call('exact', '/formatforge/api/stats', fakeReq({ headers: { 'sec-fetch-site': 'none', origin: 'null' } }), url)
  assert(opaqueRead.status === 200, 'opaque 信号（site=none / origin=null）读 → 200')

  // 写操作更严：桌面端必须带面板标记头；跨站网页即使带标记头也被拒
  const settingsUrl = 'http://127.0.0.1:19387/formatforge/api/settings'
  const appLikeWrite = await call('exact', '/formatforge/api/settings', fakeReq({ method: 'PUT', headers: { 'sec-fetch-site': undefined } }), settingsUrl)
  assert(appLikeWrite.status === 401, '桌面端无标记头的写操作 → 401', String(appLikeWrite.status))

  const appLikeWriteOk = await call(
    'exact',
    '/formatforge/api/settings',
    fakeReq({ method: 'PUT', headers: { 'sec-fetch-site': undefined, 'x-ff-client': 'panel' } }),
    settingsUrl,
  )
  assert(appLikeWriteOk.status === 200, '桌面端带 x-ff-client: panel 的写操作 → 200', `${appLikeWriteOk.status} ${String(appLikeWriteOk.body).slice(0, 120)}`)

  const crossSiteWrite = await call(
    'exact',
    '/formatforge/api/settings',
    fakeReq({ method: 'PUT', headers: { 'sec-fetch-site': 'cross-site', origin: 'https://evil.example.com', 'x-ff-client': 'panel' } }),
    settingsUrl,
  )
  assert(crossSiteWrite.status === 401, '跨站网页的写操作（带标记头也）→ 401', String(crossSiteWrite.status))

  const crossSiteRead = await call(
    'exact',
    '/formatforge/api/artifacts',
    fakeReq({ headers: { 'sec-fetch-site': 'cross-site', origin: 'https://evil.example.com' } }),
    'http://127.0.0.1:19387/formatforge/api/artifacts?limit=5',
  )
  assert(crossSiteRead.status === 401, '跨站网页的读操作 → 401（浏览器另有 CORS 兜底）', String(crossSiteRead.status))
}

console.log('\n3. 读接口（SQLite 路径）')
{
  const list = await call('exact', '/formatforge/api/artifacts', fakeReq(), 'http://127.0.0.1:19387/formatforge/api/artifacts?limit=10')
  const payload = JSON.parse(list.body)
  assert(list.status === 200 && payload.ok === true, 'list 200 + ok', String(list.status))
  assert(payload.data.rows.length === 1 && payload.data.rows[0].id === RESULT_ID, 'list 命中刚索引的产物', JSON.stringify(payload.data).slice(0, 160))
  assert(payload.data.source === 'sqlite', '走的是内置 node:sqlite 只读路径', String(payload.data.source))
  // 客户端契约：库里是 source_name/source_bytes/created_at(unix 秒)，面板读 source/size_bytes/forged_at。
  // 不归一化时列表会显示产物 id、大小与时间空白 —— 必须用真实库行验证，不能用编造的假行。
  const row0 = payload.data.rows[0]
  assert(row0.source === SOURCE, `列表行 source 是真实文件名（不是 id）：${SOURCE}`, String(row0.source))
  assert(typeof row0.size_bytes === 'number' && row0.size_bytes > 0, '列表行带 size_bytes（真实字节数）', String(row0.size_bytes))
  assert(
    typeof row0.forged_at === 'string' && !Number.isNaN(Date.parse(row0.forged_at)),
    '列表行 forged_at 是可解析的 ISO 时间',
    String(row0.forged_at),
  )

  const search = await call('exact', '/formatforge/api/artifacts', fakeReq(), 'http://127.0.0.1:19387/formatforge/api/artifacts?q=%E4%BB%98%E6%AC%BE')
  const sp = JSON.parse(search.body)
  assert(sp.data.rows.length === 1, '中文短词检索命中（LIKE 兜底）', JSON.stringify(sp.data.search_mode))

  const one = await call('prefix', '/formatforge/api/artifacts', fakeReq(), `http://127.0.0.1:19387/formatforge/api/artifacts/${RESULT_ID}`)
  const op = JSON.parse(one.body)
  assert(op.ok === true && op.data.parser === 'txt' && op.data.source === SOURCE, '单条元数据（parser/source 正确）', JSON.stringify(op.data).slice(0, 200))

  const content = await call('prefix', '/formatforge/api/artifacts', fakeReq(), `http://127.0.0.1:19387/formatforge/api/artifacts/${RESULT_ID}/content?max_chars=200`)
  const cp = JSON.parse(content.body)
  assert(cp.ok === true && cp.data.content.includes('付款条款'), '正文接口返回内容', JSON.stringify(cp.data).slice(0, 160))

  const missing = await call('prefix', '/formatforge/api/artifacts', fakeReq(), 'http://127.0.0.1:19387/formatforge/api/artifacts/no-such-id')
  assert(JSON.parse(missing.body).code === 4002 && missing.status === 404, '找不到 → 404 / 4002', String(missing.status))

  const stats = await call('exact', '/formatforge/api/stats', fakeReq(), 'http://127.0.0.1:19387/formatforge/api/stats')
  const stp = JSON.parse(stats.body)
  assert(stp.ok === true && stp.data.stats.total === 1, 'stats 报告 1 条产物', JSON.stringify(stp.data.stats).slice(0, 160))

  const health = await call('exact', '/formatforge/api/health', fakeReq(), 'http://127.0.0.1:19387/formatforge/api/health')
  const hp = JSON.parse(health.body)
  assert(hp.ok === true && hp.data.plugin === 'dsh-formatforge' && hp.data.files === 1, 'health 报告插件与文件数', JSON.stringify(hp.data).slice(0, 160))
}

console.log('\n4. 写接口')
{
  // retry：删产物文件 + 让 watcher 忘掉
  const retry = await call('prefix', '/formatforge/api/artifacts', fakeReq({ method: 'POST' }), `http://127.0.0.1:19387/formatforge/api/artifacts/cvt20261001120000abcdef/retry`)
  const rp = JSON.parse(retry.body)
  assert(retry.status === 200 && rp.data.retry === true, 'retry 返回成功', JSON.stringify(rp).slice(0, 160))
  assert(!existsSync(JSON_PATH), 'retry 删掉了旧 .ff.json（等 watcher 重转）')
  assert(forgot.includes('合同2024'), 'retry 通知 watcher 忘记该文件', JSON.stringify(forgot))

  // 复原产物以便测 delete
  writeFileSync(JSON_PATH, JSON.stringify(doc, null, 2), 'utf8')
  writeFileSync(join(HOME, 'inbox', '合同2024.ff.md'), CONTENT, 'utf8')
  cli(['inbox', 'index', '--artifact', JSON_PATH])
  const del = await call('prefix', '/formatforge/api/artifacts', fakeReq({ method: 'DELETE' }), `http://127.0.0.1:19387/formatforge/api/artifacts/${RESULT_ID}`)
  const dp = JSON.parse(del.body)
  assert(del.status === 200 && dp.data.deleted === true, 'DELETE 软删除成功', JSON.stringify(dp).slice(0, 160))
  assert(existsSync(JSON_PATH), '软删除不动磁盘文件（文件是真相源）')
  const after = await call('exact', '/formatforge/api/artifacts', fakeReq(), 'http://127.0.0.1:19387/formatforge/api/artifacts?limit=10')
  assert(JSON.parse(after.body).data.rows.length === 0, '删除后不再出现在列表里')

  const methodNotAllowed = await call('prefix', '/formatforge/api/artifacts', fakeReq({ method: 'PUT' }), `http://127.0.0.1:19387/formatforge/api/artifacts/${RESULT_ID}`)
  assert(methodNotAllowed.status === 405, 'PUT → 405', String(methodNotAllowed.status))
}

console.log('\n4b. 大产物按 id 取回（曾经只扫前 64KB → 详情/正文/重转/删除全 404）')
{
  // 复现条件：payload 里 content 在前、meta.result_id 在后，watcher 又是 pretty-print 落盘。
  // 正文超过 ~64K 字符时，id 落在"前 64KB"窗口之外 —— 面板按 r.id 请求就全部 404。
  const BIG_ID = 'cvt20261001120001bigdoc'
  const BIG_STEM = '大文档2024'
  const bigStemPath = join(HOME, 'inbox', `${BIG_STEM}.txt`)
  const bigJsonPath = join(HOME, 'inbox', `${BIG_STEM}.ff.json`)
  const bigContent = `# 大文档\n\n${'中文正文行，用来把 result_id 挤出 64KB 窗口。\n'.repeat(3000)}`
  writeFileSync(bigStemPath, '大文档正文\n', 'utf8')
  writeFileSync(
    bigJsonPath,
    JSON.stringify({ ok: true, code: 200, data: { content: bigContent, format: 'markdown', meta: { parser: 'txt', file_size: bigContent.length, result_id: BIG_ID, confidence: 0.9 } } }, null, 2),
    'utf8',
  )
  writeFileSync(join(HOME, 'inbox', `${BIG_STEM}.ff.md`), bigContent, 'utf8')

  const jsonSize = statSync(bigJsonPath).size
  assert(jsonSize > 64 * 1024, `大产物 JSON 超过 64KB（实际 ${jsonSize} 字节）`)
  assert(
    !readFileSync(bigJsonPath, 'utf8').slice(0, 64 * 1024).includes(`"result_id": "${BIG_ID}"`),
    '复现条件成立：result_id 确实落在前 64KB 之外',
  )
  const indexed = cli(['inbox', 'index', '--artifact', bigJsonPath])
  assert(indexed.data.indexed[0] === BIG_ID, 'CLI: 大产物已进索引')

  const detail = await call('prefix', '/formatforge/api/artifacts', fakeReq(), `http://127.0.0.1:19387/formatforge/api/artifacts/${BIG_ID}`)
  const dp = JSON.parse(detail.body)
  assert(detail.status === 200 && dp.ok === true, '大产物 GET /artifacts/<id> → 200', `${detail.status} ${detail.body.slice(0, 140)}`)
  assert(dp.data.source === `${BIG_STEM}.txt`, '大产物 source 是真实文件名', String(dp.data.source))
  assert(dp.data.parser === 'txt' && dp.data.chars === bigContent.length, '大产物元数据正确（parser/chars）', JSON.stringify({ p: dp.data.parser, c: dp.data.chars }))

  const content = await call('prefix', '/formatforge/api/artifacts', fakeReq(), `http://127.0.0.1:19387/formatforge/api/artifacts/${BIG_ID}/content?max_chars=500`)
  const cpp = JSON.parse(content.body)
  assert(content.status === 200 && cpp.ok === true && cpp.data.content.length === 500, '大产物正文接口 → 200（500 字窗口）', String(content.status))

  // 库被关掉（回滚开关）时，全文扫描兜底也必须能按 id 找到 —— 这正是 64KB 窗口的原始缺陷
  process.env.FF_DB = 'off'
  let viaScan = null
  try {
    viaScan = findArtifact(BIG_ID)
  } finally {
    delete process.env.FF_DB
  }
  assert(viaScan && viaScan.jsonPath === bigJsonPath, 'FF_DB=off 时全文扫描仍能反查到（不再受 64KB 限制）', JSON.stringify(viaScan))
  assert(viaScan && viaScan.via === 'scan', '走的是全文扫描兜底（via=scan）', String(viaScan && viaScan.via))

  const del = await call('prefix', '/formatforge/api/artifacts', fakeReq({ method: 'DELETE' }), `http://127.0.0.1:19387/formatforge/api/artifacts/${BIG_ID}`)
  assert(del.status === 200 && JSON.parse(del.body).data.deleted === true, '大产物 DELETE 也能按 id 命中', `${del.status} ${del.body.slice(0, 120)}`)
}

console.log('\n5. 面板偏好（GET/PUT /settings）')
{
  const before = await call('exact', '/formatforge/api/settings', fakeReq(), 'http://127.0.0.1:19387/formatforge/api/settings')
  const bp = JSON.parse(before.body)
  assert(before.status === 200 && bp.ok === true && bp.data.prefs.panelLimit === 50, '默认偏好 panelLimit=50', JSON.stringify(bp.data).slice(0, 160))

  const putReq = fakeReq({ method: 'PUT' })
  putReq[Symbol.asyncIterator] = async function* () {
    yield Buffer.from(JSON.stringify({ panelLimit: 200 }), 'utf8')
  }
  const put = await call('exact', '/formatforge/api/settings', putReq, 'http://127.0.0.1:19387/formatforge/api/settings')
  const pp = JSON.parse(put.body)
  assert(put.status === 200 && pp.ok === true && pp.data.prefs.panelLimit === 200, 'PUT 写入并回显新偏好', JSON.stringify(pp.data).slice(0, 160))

  const after = await call('exact', '/formatforge/api/settings', fakeReq(), 'http://127.0.0.1:19387/formatforge/api/settings')
  assert(JSON.parse(after.body).data.prefs.panelLimit === 200, '偏好已持久化（再读仍是 200）')
  assert(cli(['inbox', 'prefs']).data.prefs.panelLimit === 200, 'CLI 侧读到同一个值（单一存储）')

  const badJson = fakeReq({ method: 'PUT' })
  badJson[Symbol.asyncIterator] = async function* () {
    yield Buffer.from('{not json', 'utf8')
  }
  const bad = await call('exact', '/formatforge/api/settings', badJson, 'http://127.0.0.1:19387/formatforge/api/settings')
  assert(bad.status === 400, '非法 JSON → 400', String(bad.status))
}

console.log('\n6. SSE 事件流')
{
  const req = fakeReq({ url: '/formatforge/api/events' })
  const res = fakeRes()
  await routeOf('exact', '/formatforge/api/events').handler(req, res)
  assert(res.state.status === 200, 'SSE 200', String(res.state.status))
  assert(String(res.state.headers['content-type']).startsWith('text/event-stream'), 'content-type 是 text/event-stream', JSON.stringify(res.state.headers))
  const first = res.state.chunks.join('')
  assert(first.includes('event: hello') && first.includes('"count"'), '首帧推送了 hello + 当前计数', first.slice(0, 120))
  if (req._listeners.close) req._listeners.close() // 收尾：清掉轮询定时器
}

console.log('\n7. 宿主调用约定（必须能在只传两参时工作）')
{
  // 回归：线上曾因 handler 依赖第三参 url → TypeError → 宿主 writeHead(400) 空 body。
  // 这里显式用宿主的调用方式（handler(req, res)）打一遍全部路由。
  const cases = [
    ['exact', '/formatforge/api/health', '/formatforge/api/health'],
    ['exact', '/formatforge/api/stats', '/formatforge/api/stats'],
    ['exact', '/formatforge/api/settings', '/formatforge/api/settings'],
    ['exact', '/formatforge/api/artifacts', '/formatforge/api/artifacts?limit=5'],
    ['prefix', '/formatforge/api/artifacts', '/formatforge/api/artifacts/__missing__'],
  ]
  for (const [kind, path, reqUrl] of cases) {
    const state = await call(kind, path, fakeReq({ url: reqUrl }), reqUrl)
    assert(state.status > 0, `${path} 两参调用有响应（非宿主 400 空 body）`, JSON.stringify(state))
    assert(state.status !== 400 || state.body, `${path} 不返回空 body 的 400`, JSON.stringify(state))
    assert(state.body && JSON.parse(state.body).ok !== undefined, `${path} 返回结构化 JSON`, String(state.body).slice(0, 120))
  }
  // 带 query 的路由必须真的读到 query（证明 URL 是从 req.url 还原的）
  const q = await call('exact', '/formatforge/api/artifacts', fakeReq({ url: '/formatforge/api/artifacts?limit=7' }), '/formatforge/api/artifacts?limit=7')
  assert(q.status === 200, '带 query 的两参调用 → 200', String(q.status))
  const listed = JSON.parse(q.body).data
  assert(Array.isArray(listed.rows), 'artifacts 返回 rows 数组', JSON.stringify(listed).slice(0, 120))

  // 直接对 URL 还原做断言（不依赖库里有多少条数据）
  const derived = requestUrl({ url: '/formatforge/api/artifacts?limit=7&q=%E5%90%88%E5%90%8C', headers: { host: '127.0.0.1:19387' } })
  assert(derived.pathname === '/formatforge/api/artifacts', '从 req.url 还原 pathname', derived.pathname)
  assert(derived.searchParams.get('limit') === '7', 'limit 解析正确', String(derived.searchParams.get('limit')))
  assert(derived.searchParams.get('q') === '合同', '中文 query 解码正确', String(derived.searchParams.get('q')))
  assert(requestUrl({ url: '/' }).hostname === '127.0.0.1', '缺 Host 头时回退 loopback', requestUrl({ url: '/' }).hostname)
  assert(requestUrl({ url: '/a?x=1//../b' }).pathname === '/a', '异常 path 不抛错', requestUrl({ url: '/a?x=1//../b' }).pathname)
  assert(requestUrl(null).pathname === '/', 'req 为空也不抛错', requestUrl(null).pathname)
  assert(requestUrl({ url: '//evil.example.com/formatforge/api/health' }).hostname === '127.0.0.1', '协议相对 URL 不带偏 host', requestUrl({ url: '//evil.example.com/formatforge/api/health' }).hostname)
  assert(requestUrl({ url: '//evil.example.com/formatforge/api/health' }).pathname === '/evil.example.com/formatforge/api/health', '协议相对 URL 只保留 path（鉴权仍看 Host 头）', requestUrl({ url: '//evil.example.com/formatforge/api/health' }).pathname)
  assert(requestUrl({ url: 'http://h:9/x?z=2' }).pathname === '/x' && requestUrl({ url: 'http://h:9/x?z=2' }).searchParams.get('z') === '2', 'absolute-form 只取 path?search')
  assert(requestUrl({ url: 'weird' }).pathname === '/weird', '缺前导斜杠时补上')
  assert(requestUrl({ url: '/x?z=1' }, new URL('http://h/y?z=2')).searchParams.get('z') === '2', '显式传入 URL 时沿用')
  assert(requestUrl({ url: '/x' }, null).pathname === '/x', 'provided 为 null 时回退自建')
}

// ── 清理 ────────────────────────────────────────────────────────────────────
for (const dispose of disposers) {
  try {
    dispose()
  } catch {
    /* noop */
  }
}
try {
  rmSync(HOME, { recursive: true, force: true })
} catch {
  /* best effort */
}

if (failures > 0) {
  console.error(`\nAPI-FAIL: ${failures} assertion(s) failed`)
  process.exit(1)
}
console.log('\nAPI-OK: /formatforge/api/* 路由 + 鉴权 + 读写 + SSE')
