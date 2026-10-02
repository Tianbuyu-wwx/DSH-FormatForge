// test-client-panel.mjs — 右侧栏面板（v3.0.0）的注册契约、渲染冒烟与降级路径。
//
// 面板跑在宿主的 Module Loader lane 里，拿 `require('react')` 与 `ctx.slots` /
// `ctx.sidebarRightTabs` / `ctx.sidebarRight`。本测试用**假 React + 假宿主服务 + 假 fetch**
// 把这条链路整段跑一遍：注册参数、渲染内容、以及"宿主契约变了也不能拖垮拖拽模块"。
//
// 用法：node packages/dsh-formatforge/test-client-panel.mjs

import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'

const HERE = dirname(fileURLToPath(import.meta.url))
const pkg = JSON.parse(readFileSync(join(HERE, 'package.json'), 'utf8'))
const source = readFileSync(join(HERE, 'lib', 'client.js'), 'utf8')

let failures = 0
const ok = (label) => console.log('  ok   ' + label)
const fail = (label, detail) => {
  failures += 1
  console.error('  FAIL ' + label + (detail === undefined ? '' : ' — ' + detail))
}
const assert = (cond, label, detail) => (cond ? ok(label) : fail(label, detail))

// ─────────────────────────── 假 DOM / 假 React ──────────────────────────────
const makeTarget = () => ({
  listeners: [],
  addEventListener(type, fn) { this.listeners.push({ type, fn }) },
  removeEventListener(type, fn) {
    const i = this.listeners.findIndex((l) => l.type === type && l.fn === fn)
    if (i >= 0) this.listeners.splice(i, 1)
  },
})

const fakeReact = {
  createElement(type, props, ...children) {
    return {
      type,
      props: props || {},
      children: children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false),
    }
  },
  useState(initial) {
    return [typeof initial === 'function' ? initial() : initial, () => {}]
  },
  useReducer(_reducer, init) {
    return [init, () => {}]
  },
  useEffect(fn) {
    const cleanup = fn()
    if (typeof cleanup === 'function') cleanup()
  },
}

/** 把 React 元素树拍平成字符串，便于断言"屏幕上出现了什么"（含 placeholder/title 这类可见属性）。 */
const flat = (node) => {
  if (node === null || node === undefined || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(flat).join(' ')
  const props = node.props || {}
  const extra = [props.placeholder, props.title].filter(Boolean).join(' ')
  return [String(node.type), extra, flat(node.children)].filter(Boolean).join(' ')
}

/** 递归找第一个满足条件的元素（用于模拟点击）。 */
const findElement = (node, pred) => {
  if (!node || typeof node !== 'object') return null
  if (Array.isArray(node)) {
    for (const child of node) {
      const hit = findElement(child, pred)
      if (hit) return hit
    }
    return null
  }
  if (pred(node)) return node
  return findElement(node.children, pred)
}

const tick = () => new Promise((r) => setImmediate(r))

function loadBundle({ requireImpl, fetchImpl }) {
  const registrations = []
  const doc = Object.assign(makeTarget(), {
    createElement: () => ({ style: {}, appendChild() {}, remove() {}, textContent: '' }),
    getElementById: () => null,
    body: { appendChild() {} },
    documentElement: { appendChild() {} },
  })
  const win = Object.assign(makeTarget(), { innerWidth: 1200, innerHeight: 800 })
  const sandbox = {
    window: Object.assign(win, { __ModuleLoader__: { load: (r) => registrations.push(r) } }),
    document: doc,
    console: { log: () => {}, error: () => {}, warn: () => {} },
    setTimeout,
    clearTimeout,
    requestAnimationFrame: (fn) => fn(),
    fetch: fetchImpl,
    DataTransfer: class { constructor() { this.items = { add() {} } } },
    DragEvent: class { constructor(type, init) { this.type = type; Object.assign(this, init) } },
    Event: class { constructor(type, init) { this.type = type; Object.assign(this, init) } },
    navigator: { clipboard: { writeText: async () => {} } },
  }
  sandbox.globalThis = sandbox
  vm.createContext(sandbox)
  vm.runInContext(source, sandbox, { filename: 'lib/client.js' })
  if (registrations.length !== 1) throw new Error(`expected 1 load() call, got ${registrations.length}`)
  return { exports: registrations[0].factory(requireImpl), doc, win }
}

/** 假宿主：slots / sidebarRightTabs / sidebarRight / locale 全部可观测。 */
function makeHost({ withTabs = true, withSidebar = true, withLocale = true, throwOnRegister = false } = {}) {
  const seen = { effects: [], injects: [], registers: [], tabTypes: [], footerComponents: [], localeRegs: [], openedTabs: [] }
  const slots = {
    inject(name, cb) {
      seen.injects.push(name)
      // 模拟"插槽已被声明"：立刻回放注册
      if (
        name === 'sidebar.right.pane.tab' ||
        name === 'sidebar.right.pane.tab.title' ||
        name === 'sidebar.footer.action' ||
        name === 'sidebar.panellist' ||
        name === 'main'
      ) {
        cb()
      }
      return () => {}
    },
    register(spec, component) {
      if (throwOnRegister) throw new Error('slot undeclared (host contract changed)')
      seen.registers.push({ spec, component })
      if (spec.name === 'sidebar.footer.action') seen.footerComponents.push(component)
      return () => {}
    },
  }
  const services = {
    slots,
    ...(withTabs
      ? {
          sidebarRightTabs: {
            register(definition) {
              seen.tabTypes.push(definition)
              return () => {}
            },
          },
        }
      : {}),
    ...(withSidebar ? { sidebarRight: { openTab: (kind) => seen.openedTabs.push(kind) } } : {}),
    ...(withLocale
      ? {
          locale: {
            register: (ns, dict) => {
              seen.localeRegs.push({ ns, dict })
              return () => {}
            },
            bind: () => (key) => key,
          },
        }
      : {}),
  }
  const ctx = {
    effect(cb) {
      const dispose = cb()
      seen.effects.push(dispose)
      return dispose
    },
    inject(deps, cb) {
      if (!deps.includes('slots')) throw new Error('slots missing')
      cb({ get: (name) => services[name] })
    },
    get: (name) => services[name],
  }
  return { ctx, seen, services }
}

const stubFetch = (payloads) => {
  const calls = []
  const impl = async (url, init) => {
    calls.push({ url: String(url), method: (init && init.method) || 'GET', headers: (init && init.headers) || {} })
    for (const [match, payload] of payloads) {
      if (String(url).includes(match)) return { ok: true, status: 200, json: async () => ({ ok: true, data: payload }) }
    }
    return { ok: true, status: 200, json: async () => ({ ok: true, data: {} }) }
  }
  return { impl, calls }
}

// ─────────────────────────── 1. 注册契约 ────────────────────────────────────
console.log('\n1. 侧栏导航条目 + 右侧栏页签 + guide（v3.0.0 注册契约）')
{
  const { impl } = stubFetch([])
  const { exports: exportsObj } = loadBundle({ requireImpl: (n) => (n === 'react' ? fakeReact : (() => { throw new Error('unexpected require ' + n) })()), fetchImpl: impl })
  const { ctx, seen } = makeHost()
  exportsObj.apply(ctx)

  assert(seen.tabTypes.length === 1, '注册了 1 个页签类型', String(seen.tabTypes.length))
  const type = seen.tabTypes[0] || {}
  assert(type.kind === 'formatforge-inbox', 'kind = formatforge-inbox', String(type.kind))
  assert(type.id === pkg.name, 'id 用包名（宿主全局唯一）', String(type.id))
  assert(type.priority === 'extension', 'priority = extension（第三方插件最高 band）')
  assert(Array.isArray(type.guide) && type.guide[0] && type.guide[0].kind === 'formatforge-inbox', 'guide 入口指向自己的 kind')
  assert(typeof type.title === 'function', 'title 是函数（打开页签时取文案）')

  assert(seen.injects.includes('sidebar.right.pane.tab'), 'inject 了页签主体插槽')
  assert(seen.injects.includes('sidebar.right.pane.tab.title'), 'inject 了页签标题插槽')
  const body = seen.registers.find((r) => r.spec.name === 'sidebar.right.pane.tab')
  const title = seen.registers.find((r) => r.spec.name === 'sidebar.right.pane.tab.title')
  assert(Boolean(body) && body.spec.key === pkg.name, '主体用 key=包名（keyed 插槽）', JSON.stringify(body && body.spec))
  assert(Boolean(title) && title.spec.key === pkg.name, '标题用同一个 key')
  assert(typeof body.component === 'function', '主体是 React 组件函数')
  const dict = (seen.localeRegs[0] || {}).dict || {}
  assert(seen.localeRegs.length === 1 && dict.zh && dict.en, '注册了 zh/en 两套文案')
  assert(seen.footerComponents.length === 1, '侧栏底部入口按钮也注册了', String(seen.footerComponents.length))
  assert(seen.effects.length >= 4, '所有注册都挂在 ctx.effect 上（可随插件卸载回收）', String(seen.effects.length))

  // 用户要求：入口排在「自动化任务」下面 → sidebar.panellist（图标 + label，order 大于 10）
  const nav = seen.registers.find((r) => r.spec.name === 'sidebar.panellist')
  assert(Boolean(nav), '注册了侧栏导航条目（sidebar.panellist）')
  assert(nav && nav.spec.id === pkg.name, '导航条目 id = 包名（宿主用它做 selectPanel 的 key）', JSON.stringify(nav && nav.spec))
  assert(nav && nav.spec.order === 20 && nav.spec.order > 10, 'order=20 → 排在自动化任务（order 10）下面', String(nav && nav.spec.order))
  assert(nav && typeof nav.spec.label === 'function' && String(nav.spec.label()).length > 0, 'label 是函数且非空')
  const iconTree = nav && nav.component ? nav.component({ size: 18, active: true }) : null
  assert(Boolean(iconTree) && iconTree.type === 'svg' && String(iconTree.props.width) === '18', '条目组件渲染出图标（宿主传 {size, active}）', JSON.stringify(iconTree && iconTree.type))
  assert(iconTree && iconTree.props['aria-hidden'] === 'true', '图标对读屏隐藏（宿主自己带 aria-label）')

  const mainPage = seen.registers.find((r) => r.spec.name === 'main')
  assert(Boolean(mainPage) && mainPage.spec.key === pkg.name, '注册了 main 主区页面（keyed，与导航条目同 key）', JSON.stringify(mainPage && mainPage.spec))
  assert(Boolean(mainPage) && typeof mainPage.spec.inject === 'function' && mainPage.spec.inject().variant === 'page', 'main 页面以 variant=page 注入（宽松布局）')
}

// ─────────────────────────── 2. 渲染与交互 ──────────────────────────────────
console.log('\n2. 组件渲染 + 取数 + 点击详情（假 React / 假 fetch）')
{
  const { impl, calls } = stubFetch([
    ['/settings', { prefs: { panelLimit: 100, lang: 'zh' } }],
    ['/artifacts?', { rows: [{ id: 'cvt1', source: '合同2024.txt', parser: 'txt', size_bytes: 2048, forged_at: '2026-10-02T00:00:00.000Z' }], source: 'sqlite', search_mode: 'list' }],
    ['/stats', { stats: { available: true, total: 7, source: 'sqlite' } }],
    ['/content', { content: '付款条款：月结30天', total_chars: 8, offset: 0, truncated: false }],
    ['/artifacts/cvt1', { id: 'cvt1', source: '合同2024.txt', parser: 'txt', md_path: 'E:/x/合同2024.ff.md', size_bytes: 2048, confidence: 0.95 }],
  ])
  const { exports: exportsObj } = loadBundle({ requireImpl: (n) => (n === 'react' ? fakeReact : (() => { throw new Error('no') })()), fetchImpl: impl })
  const { ctx, seen } = makeHost()
  exportsObj.apply(ctx)
  const body = seen.registers.find((r) => r.spec.name === 'sidebar.right.pane.tab').component

  const first = flat(body({}))
  assert(first.includes('搜索产物'), '渲染出搜索框', first.slice(0, 100))
  await tick()
  await tick()
  const second = flat(body({}))
  assert(second.includes('合同2024.txt'), '列表里出现产物（fetch /artifacts 生效）', second.slice(0, 200))
  assert(second.includes('txt'), '行里显示 parser')
  assert(calls.some((c) => c.url.includes('/formatforge/api/artifacts?')), '走的是 /formatforge/api 前缀', JSON.stringify(calls.map((c) => c.url)))

  // 点击第一行 → 拉详情 → 再渲染
  const clicked = findElement(body({}), (el) => el.type === 'button' && flat(el).includes('合同2024.txt'))
  assert(Boolean(clicked), '找到产物行按钮')
  if (clicked && clicked.props.onClick) clicked.props.onClick()
  await tick()
  await tick()
  const third = flat(body({}))
  assert(third.includes('付款条款：月结30天'), '详情里出现正文预览', third.slice(-200))
  assert(third.includes('@tianbuyu-wwx/dsh-formatforge') || third.includes('cvt1'), '详情里显示产物 id')

  // 偏好：面板读 /settings 并用 panelLimit 取列表
  assert(calls.some((c) => c.url.includes('/settings')), '挂载时读了 /settings（面板偏好）')
  assert(calls.some((c) => c.url.includes('limit=100')), '列表用偏好里的 panelLimit=100', JSON.stringify(calls.map((c) => c.url).slice(0, 4)))
  const select = findElement(body({}), (el) => el.type === 'select')
  assert(Boolean(select) && String(select.props.value) === '100', '页长下拉框反映偏好值')
  if (select && select.props.onChange) select.props.onChange({ target: { value: '200' } })
  await tick()
  await tick()
  assert(calls.some((c) => c.method === 'PUT' && c.url.includes('/settings')), '改页长会 PUT /settings 持久化')
  // 写操作的门票：桌面端面板不带 Sec-Fetch-*/Origin，服务端靠这个标记头放行写操作；
  // 跨站网页带自定义头会触发 CORS 预检（我们从不回 Access-Control-Allow-*）→ 发不出去。
  assert(
    calls.every((c) => c.headers['x-ff-client'] === 'panel'),
    '每个请求都带 x-ff-client: panel（写操作的门票）',
    JSON.stringify(calls.map((c) => [c.method, c.headers['x-ff-client']])),
  )

  // main 主区页面复用同一个组件（variant=page）
  const mainPageComponent = seen.registers.find((r) => r.spec.name === 'main').component
  const pageHtml = flat(mainPageComponent({ variant: 'page' }))
  assert(pageHtml.includes('搜索产物'), 'main 主区页面同样渲染出面板（variant=page）', pageHtml.slice(0, 100))
}

// ─────────────────────── 2b. 宿主 400 空 body（线上事故复现） ────────────────
console.log('\n2b. 宿主 400 空 body → 面板必须给出可诊断提示')
{
  // 复现线上事故：宿主 webserver 在处理器抛错时回 400 + 空 body（无法 JSON.parse）。
  const impl400 = async () => ({
    ok: false,
    status: 400,
    json: async () => {
      throw new Error('empty body')
    },
  })
  const { exports: e400 } = loadBundle({ requireImpl: (n) => (n === 'react' ? fakeReact : (() => { throw new Error('no') })()), fetchImpl: impl400 })
  const host400 = makeHost()
  e400.apply(host400.ctx)
  const body400 = host400.seen.registers.find((r) => r.spec.name === 'sidebar.right.pane.tab').component
  flat(body400({}))
  await tick()
  await tick()
  await tick()
  const html400 = flat(body400({}))
  assert(html400.includes('400'), '提示里带 HTTP 400', html400.slice(0, 300))
  assert(html400.includes('完全退出 DSH'), '引导完全退出 DSH（含托盘）重开', html400.slice(0, 300))
  assert(!html400.includes('undefined'), '不出现 undefined 文案', html400.slice(0, 300))

  // 后端有 JSON 错误体时：优先显示后端文案，并附上接口路径便于定位
  const impl500 = async () => ({ ok: false, status: 500, json: async () => ({ ok: false, error: { kind: 'boom', message: '索引库打不开' } }) })
  const { exports: e500 } = loadBundle({ requireImpl: (n) => (n === 'react' ? fakeReact : (() => { throw new Error('no') })()), fetchImpl: impl500 })
  const host500 = makeHost()
  e500.apply(host500.ctx)
  const body500 = host500.seen.registers.find((r) => r.spec.name === 'sidebar.right.pane.tab').component
  flat(body500({}))
  await tick()
  await tick()
  await tick()
  const html500 = flat(body500({}))
  assert(html500.includes('索引库打不开'), '显示后端错误文案', html500.slice(0, 300))
  assert(html500.includes('/formatforge/api'), '附上接口路径便于定位', html500.slice(0, 300))
}

// ─────────────────── 2c. 库列名行（未归一化）也必须渲染正确 ──────────────────
console.log('\n2c. 行字段兜底：库列名（source_name/source_bytes/created_at）也要显示成文件名')
{
  const { impl } = stubFetch([
    ['/settings', { prefs: { panelLimit: 50, lang: 'zh' } }],
    // 故意用库里的原始列名 + unix 秒，模拟「接口没归一化」的退化情况
    ['/artifacts?', { rows: [{ id: 'cvt999', source_name: '库列名合同.txt', source_bytes: 4096, parser: 'txt', created_at: 1790907982 }], source: 'sqlite', search_mode: 'list' }],
    ['/stats', { stats: {} }],
  ])
  const { exports: exportsObj } = loadBundle({ requireImpl: (n) => (n === 'react' ? fakeReact : (() => { throw new Error('no') })()), fetchImpl: impl })
  const { ctx, seen } = makeHost()
  exportsObj.apply(ctx)
  const body = seen.registers.find((r) => r.spec.name === 'sidebar.right.pane.tab').component
  flat(body({}))
  await tick()
  await tick()
  const html = flat(body({}))
  assert(html.includes('库列名合同.txt'), '库列名 source_name 也能显示文件名（不是 id）', html.slice(0, 240))
  assert(html.includes('4KB'), 'size_bytes 从 source_bytes 兜底（4096 → 4KB）', html.slice(0, 240))
  assert(html.includes('txt'), 'parser 正常显示', html.slice(0, 240))
}

// ─────────────────────────── 3. 降级路径 ────────────────────────────────────
console.log('\n3. 降级：宿主契约变化不能拖垮拖拽模块')
{
  // 3a. 拿不到 react
  const { impl } = stubFetch([])
  const { exports: noReact, doc: d1, win: w1 } = loadBundle({ requireImpl: () => { throw new Error('react unavailable') }, fetchImpl: impl })
  const host1 = makeHost()
  let threw = null
  try {
    noReact.apply(host1.ctx)
  } catch (e) {
    threw = e
  }
  assert(threw === null, 'react 缺失时不抛异常', threw && threw.message)
  assert(host1.seen.registers.length === 0, 'react 缺失时不注册任何插槽')
  assert(d1.listeners.length > 0 && w1.listeners.length > 0, '拖拽模块照样挂上监听器')

  // 3b. 没有 sidebarRightTabs（只有 slots）
  const host2 = makeHost({ withTabs: false })
  const { exports: noTabs } = loadBundle({ requireImpl: (n) => (n === 'react' ? fakeReact : (() => { throw new Error('no') })()), fetchImpl: impl })
  noTabs.apply(host2.ctx)
  assert(host2.seen.tabTypes.length === 0, '没有 sidebarRightTabs 时不注册页签类型')
  assert(host2.seen.registers.some((r) => r.spec.name === 'sidebar.right.pane.tab'), '但主体插槽仍注册（等宿主自己开）')

  // 3c. 插槽未声明 → register 抛错
  const host3 = makeHost({ throwOnRegister: true })
  const { exports: hostile, doc: d3, win: w3 } = loadBundle({ requireImpl: (n) => (n === 'react' ? fakeReact : (() => { throw new Error('no') })()), fetchImpl: impl })
  let threw3 = null
  try {
    hostile.apply(host3.ctx)
  } catch (e) {
    threw3 = e
  }
  assert(threw3 === null, '插槽未声明（register 抛错）时 apply 不抛', threw3 && threw3.message)
  assert(host3.seen.tabTypes.length === 1, '页签类型仍注册（能被 guide 打开）')
  assert(d3.listeners.length > 0 && w3.listeners.length > 0, '拖拽模块不受影响')

  // 3d. 完全没有 slots 服务（inject 拿不到）
  const bare = {
    effect: (cb) => { const d = cb(); return d },
    inject: () => { throw new Error('slots missing') },
  }
  let threw4 = null
  try {
    const { exports: bareExports } = loadBundle({ requireImpl: (n) => (n === 'react' ? fakeReact : (() => { throw new Error('no') })()), fetchImpl: impl })
    bareExports.apply(bare)
  } catch (e) {
    threw4 = e
  }
  assert(threw4 === null, 'slots 注入失败也不抛异常', threw4 && threw4.message)
}

if (failures > 0) {
  console.error(`\nCLIENT-PANEL-FAIL: ${failures} assertion(s) failed`)
  process.exit(1)
}
console.log('\nCLIENT-PANEL-OK:', pkg.name, '| 右侧栏面板注册 + 渲染 + 降级')
