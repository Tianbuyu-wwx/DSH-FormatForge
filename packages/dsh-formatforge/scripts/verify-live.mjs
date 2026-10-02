// verify-live.mjs — 对**运行中的** DSH 宿主做端到端校验：把面板会打的每一条 URL 都验一遍。
//
// 插件是本地 link 安装时，Node 半只在宿主启动时加载 —— 改完 Node 侧代码必须完全退出 DSH（含托盘）再开，
// 然后跑这个脚本确认接口真的活了（历史事故：400 空 body / 单条 404 / 大产物 404 都是这里一眼看出来的）。
//
// 用法：node packages/dsh-formatforge/scripts/verify-live.mjs      （可用 FF_BASE 覆盖默认 http://127.0.0.1:19387）
const BASE = process.env.FF_BASE || 'http://127.0.0.1:19387'
const H = { 'sec-fetch-site': 'same-origin' }
let pass = 0
let fail = 0
const check = (label, cond, detail) => {
  if (cond) {
    pass += 1
    console.log('  ok   ' + label)
  } else {
    fail += 1
    console.error('  FAIL ' + label + (detail === undefined ? '' : ' — ' + detail))
  }
}

const req = async (path, init) => {
  const res = await fetch(BASE + path, { headers: H, ...init })
  const text = await res.text()
  let json = null
  try {
    json = JSON.parse(text)
  } catch {
    json = null
  }
  return { status: res.status, text, json }
}

console.log('\nA. 路由契约（prefix 必须覆盖子路径，404 必须是我们的 JSON）')
const health = await req('/formatforge/api/health')
check('GET /formatforge/api/health → 200', health.status === 200, `${health.status}`)
check('health 是结构化 JSON', Boolean(health.json && health.json.ok === true), health.text.slice(0, 120))
check('health 报出 plugin 与 db', Boolean(health.json && health.json.data && health.json.data.db), JSON.stringify(health.json).slice(0, 160))

const legacy = await req('/formatforge/health')
check('GET /formatforge/health（旧路由）→ 200', legacy.status === 200, `${legacy.status}`)

console.log('\nB. 列表 / 检索 / 统计 / 偏好（面板首屏）')
const list = await req('/formatforge/api/artifacts?limit=50')
check('GET /artifacts?limit=50 → 200', list.status === 200, `${list.status}`)
check('列表是结构化 JSON（prefix 表没抢走 exact）', Boolean(list.json && list.json.ok === true), list.text.slice(0, 120))
const rows = (list.json && list.json.data && list.json.data.rows) || []
check('列表返回 rows 数组', Array.isArray(rows), JSON.stringify(list.json).slice(0, 160))
check('库里至少有 1 条探针产物（可点进去）', rows.length >= 1, `rows=${rows.length}`)

const stats = await req('/formatforge/api/stats')
check('GET /stats → 200', stats.status === 200, `${stats.status}`)
check(
  'stats.total 与列表一致',
  Boolean(stats.json && stats.json.data && stats.json.data.stats && stats.json.data.stats.total >= rows.length),
  JSON.stringify(stats.json).slice(0, 200),
)

const settings = await req('/formatforge/api/settings')
check('GET /settings → 200', settings.status === 200, `${settings.status}`)

console.log('\nC. 单条：元数据 / 正文（曾经 100% 404 的那条路）')
const id = rows[0] && rows[0].id
if (!id) {
  console.log('  skip 没有产物可测单条接口')
} else {
  const one = await req(`/formatforge/api/artifacts/${encodeURIComponent(id)}`)
  check('GET /artifacts/<id> → 200', one.status === 200, `${one.status} ${one.text.slice(0, 120)}`)
  check('单条是结构化 JSON（不是宿主 fallback 的空 body 404）', Boolean(one.json && one.json.ok === true), one.text.slice(0, 160))
  check('单条回带 parser/source', Boolean(one.json && one.json.data && one.json.data.parser), JSON.stringify(one.json).slice(0, 200))

  const content = await req(`/formatforge/api/artifacts/${encodeURIComponent(id)}/content?max_chars=200`)
  check('GET /artifacts/<id>/content → 200', content.status === 200, `${content.status}`)
  check(
    '正文非空',
    Boolean(content.json && content.json.data && String(content.json.data.content).length > 0),
    content.text.slice(0, 160),
  )

  const missing = await req('/formatforge/api/artifacts/no-such-id-xyz')
  check('未知 id → 404 且是 JSON 错误体', missing.status === 404 && Boolean(missing.json && missing.json.code === 4002), `${missing.status} ${missing.text.slice(0, 120)}`)

  const badId = await req('/formatforge/api/artifacts/..%2F..%2Fetc')
  check('非法 id → 400/404 且是 JSON', Boolean(badId.json), `${badId.status} ${badId.text.slice(0, 120)}`)

  console.log('\nD. 写操作（放最后，会改状态）')
  const put = await req('/formatforge/api/settings', {
    method: 'PUT',
    headers: { ...H, 'content-type': 'application/json' },
    body: JSON.stringify({ panelLimit: 100 }),
  })
  check('PUT /settings → 200', put.status === 200, `${put.status} ${put.text.slice(0, 120)}`)
  const back = await req('/formatforge/api/settings')
  check(
    '偏好已持久化 panelLimit=100',
    Boolean(back.json && back.json.data && back.json.data.prefs && back.json.data.prefs.panelLimit === 100),
    JSON.stringify(back.json).slice(0, 200),
  )
  await req('/formatforge/api/settings', {
    method: 'PUT',
    headers: { ...H, 'content-type': 'application/json' },
    body: JSON.stringify({ panelLimit: 50 }),
  })
}

console.log('\nD2. 鉴权策略（面板跑在桌面端：不带 Sec-Fetch-*/Origin）')
{
  const bare = async (path, init) => {
    const res = await fetch(BASE + path, init)
    const text = await res.text()
    let json = null
    try {
      json = JSON.parse(text)
    } catch {
      json = null
    }
    return { status: res.status, text, json }
  }
  const desktopRead = await bare('/formatforge/api/artifacts?limit=1')
  check('桌面端（无浏览器信号）读 → 200', desktopRead.status === 200, `${desktopRead.status} ${desktopRead.text.slice(0, 140)}`)

  const desktopWrite = await bare('/formatforge/api/settings', {
    method: 'PUT',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ panelLimit: 777 }),
  })
  check('桌面端写操作缺 x-ff-client → 401', desktopWrite.status === 401, `${desktopWrite.status} ${desktopWrite.text.slice(0, 140)}`)

  const desktopWriteOk = await bare('/formatforge/api/settings', {
    method: 'PUT',
    headers: { 'content-type': 'application/json', 'x-ff-client': 'panel' },
    body: JSON.stringify({ panelLimit: 50 }),
  })
  check('桌面端写操作带 x-ff-client: panel → 200', desktopWriteOk.status === 200, `${desktopWriteOk.status} ${desktopWriteOk.text.slice(0, 140)}`)

  const crossSite = await bare('/formatforge/api/artifacts?limit=1', { headers: { 'sec-fetch-site': 'cross-site', origin: 'https://evil.example.com' } })
  check('跨站网页读 → 401', crossSite.status === 401, `${crossSite.status} ${crossSite.text.slice(0, 140)}`)

  const badToken = await bare('/formatforge/api/stats', { headers: { 'x-ff-token': 'definitely-wrong' } })
  check('错误 token → 401', badToken.status === 401, `${badToken.status} ${badToken.text.slice(0, 140)}`)
}

console.log('\nE. SSE')
try {
  const ctl = new AbortController()
  const res = await fetch(`${BASE}/formatforge/api/events`, { headers: H, signal: ctl.signal })
  const ct = res.headers.get('content-type') || ''
  check('GET /events → 200 + text/event-stream', res.status === 200 && ct.startsWith('text/event-stream'), `${res.status} ${ct}`)
  const reader = res.body.getReader()
  const first = await Promise.race([reader.read(), new Promise((r) => setTimeout(() => r({ value: null }), 4000))])
  const chunk = first && first.value ? new TextDecoder().decode(first.value) : ''
  check('SSE 首帧含 hello', chunk.includes('event: hello'), JSON.stringify(chunk.slice(0, 80)))
  ctl.abort()
} catch (e) {
  check('GET /events 可建立', false, e.message)
}

console.log(`\nLIVE-VERIFY: ${pass} passed, ${fail} failed`)
if (fail > 0) process.exit(1)
