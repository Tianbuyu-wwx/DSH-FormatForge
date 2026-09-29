// test-client-bundle.mjs — execute lib/client.js the way the host does and
// assert the client-module contract of DSH 0.2.0-rc.2:
//
//   1. The bundle is a classic script that calls
//      `window.__ModuleLoader__.load({ id, factory })` exactly once.
//   2. `id` is the npm package name (@deepseek-ai/dsh-client-modules keys its
//      graph rows by package name; `stripClientSuffix` also accepts "<name>/client").
//   3. The factory returns an exports object carrying `{ inject, apply }`, with
//      `inject` a string array (cordis SERVICE names — a different namespace
//      from dsh.client.inject).
//   4. `apply(ctx)` routes the activation through `ctx.effect(...)` and that
//      effect hands back a disposer which removes every listener it added —
//      without this, a client-module reload stacks a second listener set and a
//      single drop uploads N times.
//
// No dsh runtime and no DOM: `window`/`document` are minimal fakes.
// 用法：node packages/dsh-formatforge/test-client-bundle.mjs

import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'

const here = dirname(fileURLToPath(import.meta.url))
const pkg = JSON.parse(readFileSync(join(here, 'package.json'), 'utf8'))
const source = readFileSync(join(here, 'lib', 'client.js'), 'utf8')

const fail = (msg) => {
  console.error('CLIENT-BUNDLE-FAIL:', msg)
  process.exit(1)
}

// ── fake DOM that records every listener with its capture flag ──────────────
function makeTarget(label) {
  const listeners = []
  return {
    label,
    listeners,
    addEventListener(type, fn, capture) { listeners.push({ type, fn, capture: capture === true }) },
    removeEventListener(type, fn, capture) {
      const i = listeners.findIndex((l) => l.type === type && l.fn === fn && l.capture === (capture === true))
      if (i >= 0) listeners.splice(i, 1)
    },
  }
}
const doc = Object.assign(makeTarget('document'), {
  createElement: () => ({ style: {}, appendChild() {}, remove() {}, textContent: '' }),
  getElementById: () => null,
  body: { appendChild() {} },
  querySelectorAll: () => [],
})
const win = Object.assign(makeTarget('window'), { innerWidth: 1000, innerHeight: 800 })

const registrations = []
const sandbox = {
  window: Object.assign(win, { __ModuleLoader__: { load: (r) => registrations.push(r) } }),
  document: doc,
  DataTransfer: class { constructor() { this.items = { add() {} } } },
  DragEvent: class { constructor(type, init) { this.type = type; Object.assign(this, init) } },
  fetch: async () => ({ ok: true, status: 200, json: async () => ({ ok: true, saved: 'x' }) }),
  setTimeout,
  clearTimeout,
  console,
}
sandbox.globalThis = sandbox
vm.createContext(sandbox)

try {
  vm.runInContext(source, sandbox, { filename: 'lib/client.js' })
} catch (e) {
  fail(`bundle threw while executing: ${e.message}`)
}

// ── 1/2. registration shape ─────────────────────────────────────────────────
if (registrations.length !== 1) fail(`expected exactly 1 __ModuleLoader__.load call, got ${registrations.length}`)
const reg = registrations[0]
if (reg.id !== pkg.name) fail(`load id must be the package name ${JSON.stringify(pkg.name)}, got ${JSON.stringify(reg.id)}`)
if (typeof reg.factory !== 'function') fail('registration.factory must be a function')
console.log('load() id       :', reg.id)

// ── 3. factory exports ──────────────────────────────────────────────────────
let exports
try {
  exports = reg.factory(() => { throw new Error('this bundle must not require() anything') })
} catch (e) {
  fail(`factory threw: ${e.message}`)
}
if (typeof exports !== 'object' || exports === null) fail('factory must return an exports object')
if (!Array.isArray(exports.inject)) fail('exports.inject must be a string array (cordis service names)')
for (const name of exports.inject) if (typeof name !== 'string') fail('exports.inject must contain strings')
if (typeof exports.apply !== 'function') fail('exports.apply must be a function (cordis client-plugin contract)')
console.log('exports.inject  :', JSON.stringify(exports.inject))

// ── 4. apply(ctx) → ctx.effect → disposer removes every listener ────────────
const effects = []
const ctx = { effect: (cb) => { const d = cb(); effects.push(d); return d } }
const before = doc.listeners.length + win.listeners.length
exports.apply(ctx)
const added = doc.listeners.length + win.listeners.length - before
if (effects.length !== 1) fail(`apply(ctx) must route activation through ctx.effect exactly once, got ${effects.length}`)
if (added === 0) fail('apply(ctx) registered no listeners — the divert is inert')
if (typeof effects[0] !== 'function') fail('the effect callback must return a disposer function')

effects[0]()
const after = doc.listeners.length + win.listeners.length
if (after !== before) fail(`disposer left ${after - before} listener(s) registered (HMR would stack duplicates)`)
console.log('listeners       : +%d on activate, %d left after disposer', added, after - before)

// ── idempotence: a reload replaces, never doubles ───────────────────────────
exports.apply(ctx)
const doubled = doc.listeners.length + win.listeners.length - before
if (doubled !== added) fail(`a second apply() must not change the listener count (got ${doubled}, first was ${added})`)
effects[1]()
console.log('reload cycle    : clean (%d listeners after two activate/dispose cycles)', doc.listeners.length + win.listeners.length - before)

// ── fallback path: no ctx.effect available (still must activate) ────────────
const beforeFb = doc.listeners.length + win.listeners.length
exports.apply(undefined)
if (doc.listeners.length + win.listeners.length - beforeFb !== added) fail('apply() without a ctx must still activate')
console.log('no-ctx fallback : ok (activates without a disposer, by design)')

console.log('CLIENT-BUNDLE-OK:', pkg.name, '|', pkg.version)
