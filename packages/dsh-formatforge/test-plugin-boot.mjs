// test-plugin-boot.mjs — 宿主半（index.mjs）的无宿主启动冒烟（v3.0.0）。
//
// 为什么需要：client bundle 会热重载（面板图标立刻可见），但 **Node 半只在宿主启动时加载**。
// 如果 index.mjs 里有导入/注册错误，插件会静默半死：拖拽看起来正常、API 却一直 404。
// 本测试用假 cordis ctx 把 apply() 完整跑一遍，断言：不抛错、5 个工具注册、8 条路由注册、
// watcher 起得来；这样"重启宿主"之前就能确认新代码是好的。
//
// 用法：node packages/dsh-formatforge/test-plugin-boot.mjs

import { mkdirSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'
import { ensureHostStubs } from './test/_host-stubs.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = dirname(dirname(HERE))

let failures = 0
const ok = (label) => console.log('  ok   ' + label)
const fail = (label, detail) => {
  failures += 1
  console.error('  FAIL ' + label + (detail === undefined ? '' : ' — ' + detail))
}
const assert = (cond, label, detail) => (cond ? ok(label) : fail(label, detail))

const HOME = join(tmpdir(), `ff-boot-${Date.now()}`)
mkdirSync(join(HOME, 'inbox'), { recursive: true })
process.env.FF_HOME = HOME
process.env.FF_DB_PATH = join(HOME, 'index.db')
delete process.env.FF_DB

const stubs = ensureHostStubs()
const logs = []
try {
  const mod = await import('./index.mjs')

  const tools = []
  const routes = []
  const webServer = {
    register(route) {
      if (routes.some((r) => r.kind === route.kind && r.path === route.path)) {
        throw new Error(`duplicate route ${route.kind} ${route.path}`)
      }
      routes.push(route)
      return () => {}
    },
  }
  const effects = []
  const ctx = {
    skills: { registerProvider: () => {} },
    tools: { register: (tool) => tools.push(tool) },
    sessions: { list: () => [] },
    agents: { list: () => [] },
    effects: [],
    effect(cb) {
      const dispose = cb()
      effects.push(dispose)
      return dispose
    },
    get: (name) => (name === 'webServer' ? webServer : undefined),
    on: () => {},
  }

  console.log('\n1. apply() 整体启动')
  let threw = null
  try {
    mod.apply(ctx)
  } catch (e) {
    threw = e
  }
  assert(threw === null, 'apply() 不抛异常（导入/注册链路完好）', threw && threw.stack?.split('\n')[0])

  console.log('\n2. 工具注册')
  const names = tools.map((t) => t && t.name).filter(Boolean)
  assert(names.length === 5, `注册 5 个工具（实际 ${names.length}）`, names.join(','))
  for (const want of ['ff_translate', 'ff_formats', 'ff_result', 'ff_batch', 'ff_diff']) {
    assert(names.includes(want), `含 ${want}`)
  }

  console.log('\n3. 路由注册（上传/健康 + v3.0.0 API）')
  const paths = routes.map((r) => `${r.kind}:${r.path}`)
  assert(paths.includes('exact:/formatforge/upload'), 'POST /formatforge/upload')
  assert(paths.includes('exact:/formatforge/health'), 'GET /formatforge/health（旧健康检查）')
  const apiPaths = paths.filter((p) => p.includes('/formatforge/api/'))
  assert(apiPaths.length === 6, `注册 6 条 API 路由（实际 ${apiPaths.length}）`, apiPaths.join(' '))
  assert(paths.includes('exact:/formatforge/api/health'), 'API 健康检查存在（重启后应返回 200）')
  assert(paths.includes('prefix:/formatforge/api/artifacts'), 'API 单条 prefix 路由（GET/POST/DELETE 共用）')
  // 宿主 prefix 命中条件是 `pathname === prefix || pathname.startsWith(prefix + '/')`，
  // 带尾斜杠的前缀只有 `/artifacts//<id>` 能命中 → 真实请求会落到 SPA fallback 变 404。
  for (const r of routes.filter((x) => x.kind === 'prefix')) {
    assert(!r.path.endsWith('/'), `prefix 路径不带尾斜杠：${r.path}`, r.path)
  }
  const hostMatch = (pathname) => {
    const exact = routes.find((r) => r.kind === 'exact' && r.path === pathname)
    if (exact) return exact
    let best
    for (const route of routes) {
      if (route.kind !== 'prefix') continue
      if (pathname !== route.path && !pathname.startsWith(`${route.path}/`)) continue
      if (!best || route.path.length > best.path.length) best = route
    }
    return best
  }
  assert(Boolean(hostMatch('/formatforge/api/artifacts/cvt1')), '模拟宿主匹配：/artifacts/<id> 能命中 prefix 路由')

  console.log('\n4. 宿主调用约定：handler(req, res) 两参调用（不抛错 = 线上不会变 400 空 body）')
  {
    // @deepseek-ai/dsh-host-webserver 以 `await route.handler(req, res)` 调用，
    // 处理器若依赖第三参（如 url）会抛 TypeError，被宿主转成 400 空 body。
    const makeReq = (method, url) => {
      const listeners = {}
      return {
        method,
        url,
        headers: { host: '127.0.0.1:19387', 'sec-fetch-site': 'same-origin' },
        on(event, fn) {
          listeners[event] = fn
        },
        _listeners: listeners,
      }
    }
    const makeRes = () => {
      const state = { status: 0, headers: null, body: '', ended: false, headersSent: false, writableEnded: false }
      const res = {
        state,
        writeHead(status, headers) {
          state.status = status
          state.headers = headers || null
          state.headersSent = true
        },
        write(chunk) {
          state.body += String(chunk)
        },
        end(body) {
          if (body !== undefined) state.body += String(body)
          state.ended = true
          state.writableEnded = true
          if (typeof res._onEnd === 'function') res._onEnd()
        },
        destroy() {},
        on(event, fn) {
          if (event === 'close') res._onEnd = fn
        },
      }
      return res
    }

    for (const route of routes) {
      const method = route.path === '/formatforge/upload' ? 'POST' : 'GET'
      const req = makeReq(method, route.path === '/formatforge/api/artifacts/' ? `${route.path}__missing__` : route.path)
      const res = makeRes()
      let failure = null
      try {
        await route.handler(req, res)
        if (typeof req._listeners.end === 'function') req._listeners.end()
      } catch (e) {
        failure = e
      }
      if (typeof req._listeners.close === 'function') req._listeners.close() // 清掉 SSE 轮询
      assert(failure === null, `${method} ${route.path} 两参调用不抛错`, failure && failure.message)
      assert(res.state.status > 0, `${method} ${route.path} 写回了状态码`, `status=${res.state.status}`)
      assert(!(res.state.status === 400 && res.state.body === ''), `${method} ${route.path} 不是空 body 的 400`, JSON.stringify(res.state.body).slice(0, 80))
    }
  }

  console.log('\n5. 副作用与收尾')
  const disposeFns = effects.filter((d) => typeof d === 'function')
  assert(disposeFns.length >= 1, 'API disposer 交给了 ctx.effect（可回收）', String(disposeFns.length))
  assert(Boolean(mod.name === 'dsh-formatforge' && Array.isArray(mod.inject)), '导出契约 name/inject 正常')
  assert(mod.inject.includes('webServer'), 'inject 里声明了 webServer', JSON.stringify(mod.inject))
} finally {
  stubs.cleanup()
  try {
    rmSync(HOME, { recursive: true, force: true })
  } catch {
    /* best effort */
  }
}

if (failures > 0) {
  console.error(`\nPLUGIN-BOOT-FAIL: ${failures} assertion(s) failed`)
  process.exit(1)
}
console.log('\nPLUGIN-BOOT-OK: index.mjs 挂载 5 工具 + 8 路由（含 /formatforge/api/*）')
