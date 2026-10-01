// test-client-drag.mjs — execute lib/client.js against a miniature DOM and
// drive the REAL drag sequences, because the v0.3.1 bugs ("拖拽文件夹会卡死") are
// *sequence* bugs: they only appear when the host's dragDepth counter, our
// capture decision, the escape latch and a terminal event interact. A static
// contract check (test-client-bundle.mjs) cannot see them.
//
// The harness re-implements the host half that matters:
//   @deepseek-ai/dsh-client-ui-attachment / drop-events.js
//     installDocumentDropEvents(canAcceptDrop, onAddFiles, dragDepth, setDragActive)
// — bubble-phase document listeners with a retained dragDepth counter that only
// resets inside the host's OWN drop/dragleave/dragend handlers — plus its
// droppedDirectories() entry-API check and its dragover preventDefault.
//
// Two browser dialects are exercised, because the entry API is not equally
// available in all phases (MDN: readable only in dragstart/drop; Chrome answers
// earlier too):
//   entryPhase = 'spec'   → webkitGetAsEntry() returns null outside the drop phase
//   entryPhase = 'chrome' → entries answer in every phase
//
// Assertions (each one maps to a way the page used to wedge or to lose a file):
//   1. folder drag (both dialects) → released: host gets enter/over/drop, no
//      mask, no upload, host counter back to 0, host's own dir intake sees it
//   2. folder with a DOTTED name (报告.pdf / archive.zip) → released too
//   3. folder drag with no entry API at all (shape fallback) → released
//   4. folder drag whose FIRST dragenter carries no files (the freeze path)
//   5. real file drag → mask + × , forges once, replays the host reset
//   6. undecided first dragenter → drop classified only at drop time → still
//      forges once AND leaves the host counter at 0 (no wedged mask)
//   7. × on the mask (live escape) → mask/chip gone, host reset, nothing
//      uploaded, and the rest of THAT drag including its drop goes to the host
//   8. Esc → same escape path
//   9. escape latch survives a live drag (dragover keeps the session fresh)
//  10. watchdog → mask clears itself, and the drop of that drag is handed back
//  11. × chip on a released drag → clears a wedged host mask; the chip may come
//      back for the same live drag (it never poisons the NEXT drag)
//  12. empty / typeless files are never silently dropped: README(0B),
//      data(100B, no type) and LICENSE(0B, no type) all reach the uploader
//  13. mixed folder + file with a partially readable entry API → whole drag
//      released, nothing uploaded
//  14. drag leaving the viewport → mask + chip retired, host balances itself
//  15. real window dragend → mask gone, chip lingers then retires
//  16. disposer → listeners and escape elements removed (HMR safety)
//
// 用法：node packages/dsh-formatforge/test-client-drag.mjs

import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import vm from 'node:vm'

const here = dirname(fileURLToPath(import.meta.url))
const pkg = JSON.parse(readFileSync(join(here, 'package.json'), 'utf8'))
const source = readFileSync(join(here, 'lib', 'client.js'), 'utf8')

let failures = 0
let checks = 0
const ok = (label) => { checks += 1; console.log('  ok   ' + label) }
const fail = (label, detail) => {
  failures += 1
  checks += 1
  console.error('  FAIL ' + label + (detail === undefined ? '' : ' — ' + detail))
}
function assert(cond, label, detail) {
  if (cond) ok(label)
  else fail(label, detail)
}

// ───────────────────────────── miniature DOM ────────────────────────────────
class FakeEvent {
  constructor(type, init = {}) {
    this.type = type
    this.bubbles = init.bubbles !== false
    this.cancelable = init.cancelable === true
    this.defaultPrevented = false
    this.cancelBubble = false
    this.clientX = init.clientX === undefined ? 10 : init.clientX
    this.clientY = init.clientY === undefined ? 10 : init.clientY
    this.key = init.key
    this.target = null
    this.currentTarget = null
  }
  preventDefault() { if (this.cancelable) this.defaultPrevented = true }
  stopPropagation() { this.cancelBubble = true }
}

class FakeNode {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase()
    this.id = ''
    this.type = ''
    this.title = ''
    this.children = []
    this.parent = null
    this.listeners = []
    this.attrs = {}
    this.style = { cssText: '' }
    this._text = ''
  }
  get textContent() { return this._text }
  set textContent(v) { this._text = String(v) }
  appendChild(child) { child.parent = this; this.children.push(child); return child }
  remove() {
    if (!this.parent) return
    const i = this.parent.children.indexOf(this)
    if (i >= 0) this.parent.children.splice(i, 1)
    this.parent = null
  }
  setAttribute(k, v) { this.attrs[k] = String(v) }
  getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null }
  addEventListener(type, fn, capture) { this.listeners.push({ type, fn, capture: capture === true }) }
  removeEventListener(type, fn, capture) {
    const i = this.listeners.findIndex((l) => l.type === type && l.fn === fn && l.capture === (capture === true))
    if (i >= 0) this.listeners.splice(i, 1)
  }
  find(id) {
    if (this.id === id) return this
    for (const c of this.children) {
      const hit = c.find(id)
      if (hit) return hit
    }
    return null
  }
  countListeners() { return this.listeners.length + this.children.reduce((n, c) => n + c.countListeners(), 0) }
}

function invoke(node, event, capture) {
  for (const l of node.listeners.slice()) {
    if (l.capture !== capture || l.type !== event.type) continue
    event.currentTarget = node
    l.fn(event)
  }
}

/** Capture from the root down, then bubble from the target up (stopPropagation aware). */
function dispatch(target, event) {
  const path = []
  for (let n = target; n; n = n.parent) path.unshift(n)
  event.target = target
  for (const node of path) {
    if (event.cancelBubble) return event
    invoke(node, event, true)
  }
  for (let i = path.length - 1; i >= 0; i -= 1) {
    if (event.cancelBubble) return event
    invoke(path[i], event, false)
  }
  return event
}

const win = new FakeNode('#window')
const doc = new FakeNode('#document')
const html = new FakeNode('html')
const body = new FakeNode('body')
win.appendChild(doc)
doc.appendChild(html)
html.appendChild(body)
doc.body = body
doc.documentElement = html
doc.createElement = (tag) => new FakeNode(tag)
doc.getElementById = (id) => doc.find(id)
doc.dispatchEvent = (ev) => dispatch(doc, ev)
win.dispatchEvent = (ev) => dispatch(win, ev)
win.innerWidth = 1200
win.innerHeight = 800

// ───────────────────────────── fake drag payloads ───────────────────────────
// MDN: "During a drag operation, this method can only read data in the handlers
// for dragstart and drop ... Calling it from any other drag event returns null."
// Chrome is more permissive; the suite covers both dialects.
let dragPhase = 'drag'
let entryPhase = 'spec' // 'spec' | 'chrome'

class FakeFile {
  constructor(parts = [], name = 'file', options = {}) {
    this.name = name
    this.type = options.type || ''
    this.size = parts.reduce((n, p) => n + (p && p.byteLength ? p.byteLength : 0), 0)
  }
  async arrayBuffer() { return new ArrayBuffer(this.size) }
}
function file(name, type, size = 0) {
  const f = new FakeFile([], name, { type })
  f.size = size
  return f
}
const folder = (name = '待转换的资料') => file(name, '', 0)

class FakeItemList {
  constructor(owner) { this._items = []; this.owner = owner }
  add(f) {
    this._items.push(f)
    if (this.owner && !this.owner.files.includes(f)) this.owner.files.push(f) // items.add() also lands in files
  }
  get length() { return this._items.length }
  [Symbol.iterator]() { return this._items[Symbol.iterator]() }
}

class FakeItem {
  constructor(f, { entry = null, entryApi = true } = {}) {
    this.kind = 'file'
    this.type = f ? f.type : ''
    this._file = f
    this._entry = entry
    if (entryApi) {
      this.webkitGetAsEntry = () => (entryPhase === 'spec' && dragPhase !== 'drop' ? null : this._entry)
    }
  }
  getAsFile() { return this._file }
}

class FakeDataTransfer {
  constructor(files = [], { entries = null, types = null, entryApi = true } = {}) {
    this.files = []
    this.items = new FakeItemList(this)
    // NB: build the item list directly — items.add() takes a File in the real
    // API, so it must not be used to wrap the constructor's Files. A Files-only
    // payload still answers the entry API: per item a NON-directory entry, which
    // is what a browser reports for a real file.
    files.forEach((f, i) => {
      const entry = entries === null || entries === undefined ? { isDirectory: false } : entries[i]
      this.items._items.push(new FakeItem(f, { entry, entryApi }))
      this.files.push(f)
    })
    this._types = types
    this.dropEffect = 'none'
  }
  /** Real DataTransfer gains "Files" as soon as an item is added. */
  get types() { return this._types || (this.items.length > 0 ? ['Files'] : []) }
}
const dragEvent = (type, dt, extra = {}) => {
  const ev = new FakeEvent(type, { bubbles: true, cancelable: true, ...extra })
  Object.defineProperty(ev, 'dataTransfer', { value: dt })
  return ev
}

// ─────────────────────────── controllable timers ────────────────────────────
let now = 0
let timerSeq = 0
const timers = new Map()
// The bundle's escape latch compares Date.now() between drag events, so the
// harness owns the clock: real scenarios are seconds apart, test runs are
// microseconds apart.
const clock = { t: Date.parse('2026-10-02T00:00:00.000Z') }
class FakeDate extends Date {
  static now() { return clock.t }
}
const fakeSetTimeout = (fn, ms) => {
  const id = ++timerSeq
  timers.set(id, { at: now + (Number(ms) || 0), fn })
  return id
}
const fakeClearTimeout = (id) => { timers.delete(id) }
function advance(ms) {
  const target = now + ms
  for (;;) {
    let dueId = null
    let dueAt = Infinity
    for (const [id, t] of timers) {
      if (t.at <= target && t.at < dueAt) { dueAt = t.at; dueId = id }
    }
    if (dueId === null) break
    const t = timers.get(dueId)
    timers.delete(dueId)
    now = t.at
    t.fn()
  }
  now = target
}

// ───────────────────────────── sandbox + host ───────────────────────────────
const registrations = []
const fetches = []
const consoleLogs = []
const sandbox = {
  window: Object.assign(win, { __ModuleLoader__: { load: (r) => registrations.push(r) } }),
  document: doc,
  console: {
    log: (line) => consoleLogs.push(String(line)),
    error: (line) => consoleLogs.push(String(line)),
    warn: (line) => consoleLogs.push(String(line)),
  },
  File: FakeFile,
  DataTransfer: FakeDataTransfer,
  DragEvent: FakeEvent,
  Event: FakeEvent,
  setTimeout: fakeSetTimeout,
  clearTimeout: fakeClearTimeout,
  requestAnimationFrame: (fn) => { fn(); return 1 },
  fetch: async (url, init) => {
    fetches.push({ url, init })
    return { ok: true, status: 200, json: async () => ({ ok: true, saved: decodeURIComponent(init.headers['x-ff-filename']) }) }
  },
  Date: FakeDate,
}
sandbox.globalThis = sandbox
vm.createContext(sandbox)
vm.runInContext(source, sandbox, { filename: 'lib/client.js' })

// host simulation — mirrors installDocumentDropEvents() in drop-events.js
const host = { dragDepth: 0, active: false, dragoverAllowed: 0, addFilesCalls: 0, addedFiles: [], addedDirs: [], resets: 0 }
const hasFileTypes = (e) => {
  const dt = e.dataTransfer
  return Boolean(dt && dt.types && dt.types.includes('Files'))
}
/** Mirrors the host's own droppedDirectories(). */
function droppedDirectories(dataTransfer, files) {
  const dirs = []
  let i = 0
  for (const item of dataTransfer.items) {
    if (item.kind !== 'file') continue
    const f = files[i++]
    if (typeof item.webkitGetAsEntry !== 'function') continue
    const entry = item.webkitGetAsEntry()
    if (!entry || entry.isDirectory !== true) continue
    if (f) dirs.push(f)
  }
  return dirs
}
doc.addEventListener('dragenter', (e) => {
  if (!hasFileTypes(e)) return
  e.preventDefault()
  host.dragDepth += 1
  host.active = true
})
doc.addEventListener('dragover', (e) => {
  if (!hasFileTypes(e)) return
  e.preventDefault()
  e.dataTransfer.dropEffect = 'copy'
  host.dragoverAllowed += 1
})
doc.addEventListener('dragleave', (e) => {
  if (!hasFileTypes(e)) return
  host.dragDepth = Math.max(0, host.dragDepth - 1)
  if (host.dragDepth === 0) host.active = false
  const leftViewport = e.clientX <= 0 || e.clientY <= 0 || e.clientX >= win.innerWidth || e.clientY >= win.innerHeight
  if ((e.target === html || e.target === body) && leftViewport) {
    host.dragDepth = 0
    host.active = false
    host.resets += 1
  }
})
doc.addEventListener('drop', (e) => {
  if (!hasFileTypes(e)) return
  e.preventDefault()
  host.dragDepth = 0
  host.active = false
  host.resets += 1
  host.addFilesCalls += 1
  host.addedFiles = [...e.dataTransfer.files]
  host.addedDirs = droppedDirectories(e.dataTransfer, host.addedFiles)
})
win.addEventListener('dragend', () => {
  host.dragDepth = 0
  host.active = false
  host.resets += 1
})

const overlay = () => doc.getElementById('ff-drop-overlay')
const chip = () => doc.getElementById('ff-drop-escape')
const closeBtn = () => doc.getElementById('ff-drop-close')
const click = (el) => dispatch(el, new FakeEvent('click', { bubbles: true, cancelable: true }))
const enter = (dt) => { dragPhase = 'drag'; return dispatch(body, dragEvent('dragenter', dt)) }
const over = (dt) => { dragPhase = 'drag'; return dispatch(body, dragEvent('dragover', dt)) }
const drop = (dt) => { dragPhase = 'drop'; return dispatch(body, dragEvent('drop', dt)) }
const leaveAtEdge = (dt) => { dragPhase = 'drag'; return dispatch(body, dragEvent('dragleave', dt, { clientX: -1, clientY: -1 })) }
const pressEscape = () => dispatch(body, new FakeEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
const realDragEnd = () => dispatch(win, new FakeEvent('dragend', { bubbles: true }))
const tick = () => new Promise((r) => setImmediate(r))
const uploadedNames = () => fetches.map((f) => decodeURIComponent(f.init.headers['x-ff-filename']))

function hostClean(label) {
  assert(
    host.dragDepth === 0 && host.active === false,
    label + ' — host counter clean',
    `dragDepth=${host.dragDepth} active=${host.active}`,
  )
}
function resetHost() {
  advance(60_000) // run out any timer left over by the previous scenario
  host.dragDepth = 0
  host.active = false
  host.dragoverAllowed = 0
  host.addFilesCalls = 0
  host.addedFiles = []
  host.addedDirs = []
  host.resets = 0
  clock.t += 3_000 // a fresh scenario is a fresh drag, seconds after the last one
}

// ─────────────────────────────── bootstrap ──────────────────────────────────
if (registrations.length !== 1) {
  console.error('CLIENT-DRAG-FAIL: expected exactly 1 __ModuleLoader__.load call, got ' + registrations.length)
  process.exit(1)
}
const disposers = []
const ctx = { effect: (cb) => { const d = cb(); disposers.push(d); return d } }
const listenersBefore = doc.countListeners() + win.countListeners()
registrations[0].factory(() => { throw new Error('bundle must not require() anything') }).apply(ctx)
console.log('activate       : +%d listeners', doc.countListeners() + win.countListeners() - listenersBefore)

// ───────── 1-3. folder drags are released in both entry dialects ─────────────
for (const dialect of ['spec', 'chrome']) {
  console.log(`\n1/${dialect}. folder drag → released to the host`)
  resetHost()
  fetches.length = 0
  entryPhase = dialect
  const dir = folder()
  const dt = new FakeDataTransfer([dir], { entries: [{ isDirectory: true }] })
  enter(dt)
  assert(host.dragDepth === 1, 'host received the folder dragenter', `dragDepth=${host.dragDepth}`)
  assert(overlay() === null, 'no FormatForge mask for a folder drag')
  assert(chip() !== null, '× chip rides the folder drag')
  over(dt)
  assert(host.dragoverAllowed === 1, 'host dragover still reaches it')
  drop(dt)
  await tick()
  assert(host.addFilesCalls === 1 && host.addedFiles[0] === dir, 'host received the folder drop untouched')
  assert(host.addedDirs.length === 1, 'host dir intake saw the directory')
  assert(fetches.length === 0, 'folder never uploaded', `fetches=${fetches.length}`)
  assert(overlay() === null, 'still no mask after the drop')
  hostClean('folder drop')
}

console.log('\n2. folder with a DOTTED name → released (fail open on ambiguity)')
for (const dialect of ['spec', 'chrome']) {
  resetHost()
  fetches.length = 0
  entryPhase = dialect
  const dir = folder('报告.pdf')
  const dt = new FakeDataTransfer([dir], { entries: [{ isDirectory: true }] })
  enter(dt)
  assert(overlay() === null, `${dialect}: no mask for the dotted folder`)
  drop(dt)
  await tick()
  assert(fetches.length === 0, `${dialect}: dotted folder never uploaded`)
  assert(host.addFilesCalls === 1, `${dialect}: host received the drop`)
  hostClean(`${dialect}: dotted folder drop`)
}

console.log('\n3. folder drag with NO entry API (shape fallback) → released')
{
  resetHost()
  fetches.length = 0
  entryPhase = 'spec'
  const dir = folder('archive.zip')
  const dt = new FakeDataTransfer([dir], { entryApi: false })
  enter(dt)
  assert(host.dragDepth === 1, 'host received the folder dragenter')
  assert(overlay() === null, 'no FormatForge mask')
  drop(dt)
  await tick()
  assert(host.addFilesCalls === 1, 'host received the drop')
  assert(fetches.length === 0, 'nothing uploaded')
  hostClean('folder drop (no entry API)')
}

// ──────── 4. the reported freeze: empty first dragenter, folder second ──────
console.log('\n4. folder drag whose first dragenter carries no files (the freeze path)')
{
  resetHost()
  fetches.length = 0
  entryPhase = 'spec'
  enter(new FakeDataTransfer([], { types: ['Files'] })) // Chrome: types=Files, files=[]
  assert(host.dragDepth === 1 && host.active === true, 'host counted the first (undecided) dragenter')
  const dt = new FakeDataTransfer([folder()], { entries: [{ isDirectory: true }] })
  enter(dt)
  assert(overlay() === null && chip() !== null, 'still hands-off on the folder enter (chip only)')
  over(dt)
  drop(dt)
  await tick()
  assert(overlay() === null, 'our mask never appeared')
  assert(fetches.length === 0, 'nothing uploaded')
  hostClean('folder drag after an undecided first enter')
}

// ─────────────────── 5. real file drag: forge + host reset ──────────────────
console.log('\n5. real file drag → mask + × , one upload, host counter replayed')
{
  resetHost()
  fetches.length = 0
  entryPhase = 'spec'
  enter(new FakeDataTransfer([], { types: ['Files'] }))
  assert(host.dragDepth === 1, 'host counted the drag before we captured')
  const doc0 = file('合同.pdf', 'application/pdf', 1234)
  const dt = new FakeDataTransfer([doc0])
  enter(dt)
  assert(overlay() !== null, 'mask shown for a non-image file')
  assert(closeBtn() !== null, '× lives on the mask')
  assert(host.dragDepth === 1, 'our capture kept the host from double-counting')
  over(dt)
  drop(dt)
  assert(overlay() === null, 'mask hidden on drop')
  assert(host.addFilesCalls === 0, 'host drop handler was suppressed')
  hostClean('after our captured drop')
  await tick()
  assert(fetches.length === 1 && fetches[0].url === '/formatforge/upload', 'uploaded exactly once', `fetches=${fetches.length}`)
  assert(
    fetches[0].init.headers['x-ff-filename'] === encodeURIComponent('合同.pdf'),
    'filename header preserved (uri-encoded)',
    fetches[0].init.headers['x-ff-filename'],
  )
  // NB: the bundle builds this Uint8Array inside the VM realm, so `instanceof`
  // against the host realm's constructor is always false — check the tag.
  const body0 = fetches[0].init.body
  assert(
    body0 && body0.length === 1234 && Object.prototype.toString.call(body0) === '[object Uint8Array]',
    'file bytes sent',
    Object.prototype.toString.call(body0),
  )
  assert(chip() !== null, '× chip lingers after the drop (stuck-mask escape)')
  advance(8_000)
  assert(chip() === null, '× chip auto-hides after the linger window')
  hostClean('after the linger retired the chip')
}

// ── 6. undecided first enter, classified only at drop (wedge regression) ────
console.log('\n6. undecided first dragenter → drop classified only at drop time')
{
  resetHost()
  fetches.length = 0
  entryPhase = 'spec'
  enter(new FakeDataTransfer([], { types: ['Files'] })) // unreadable → host counts it, we stay undecided
  assert(host.dragDepth === 1, 'host counted the unreadable dragenter')
  const dt = new FakeDataTransfer([file('资料.pdf', 'application/pdf', 10)])
  drop(dt) // NO second dragenter: the final say happens here
  assert(host.addFilesCalls === 0, 'host drop suppressed by our divert')
  hostClean('captured-at-drop case left no wedged counter')
  await tick()
  assert(fetches.length === 1 && uploadedNames()[0] === '资料.pdf', 'still forged exactly once', `fetches=${fetches.length}`)
}

// ───────────── 7-8. live escape (× on the mask / Esc) ───────────────────────
for (const how of ['×', 'Esc']) {
  console.log(`\n7. live escape via ${how} → mask gone, drag handed back, host reset`)
  resetHost()
  fetches.length = 0
  entryPhase = 'spec'
  const dt = new FakeDataTransfer([file('合同.pdf', 'application/pdf', 1234)])
  enter(dt)
  assert(overlay() !== null, 'mask shown')
  const before = host.resets
  if (how === '×') click(closeBtn())
  else pressEscape()
  assert(overlay() === null, `mask removed by ${how}`)
  assert(chip() === null, 'escape chip removed too')
  assert(host.resets > before, 'host reset replayed')
  hostClean(`after ${how}`)

  // The escape must CANCELL what is left of this drag: its drop is the host's.
  enter(dt)
  assert(overlay() === null && chip() === null, 'escaped drag stays hands-off')
  assert(host.dragDepth === 1, 'host owns the escaped drag')
  drop(dt)
  assert(host.addFilesCalls === 1, 'escaped drop handed back to the host')
  hostClean('after the escaped drop')
  await tick()
  assert(fetches.length === 0, 'nothing was diverted or uploaded after the escape')

  // …and a genuinely NEW drag is captured again.
  clock.t += 3_000
  const fresh = new FakeDataTransfer([file('新合同.pdf', 'application/pdf', 99)])
  enter(fresh)
  assert(overlay() !== null, 'a fresh drag is captured again')
  drop(fresh)
  await tick()
  assert(uploadedNames().includes('新合同.pdf'), 'the fresh drag uploaded')
  hostClean('after the fresh drag')
}

// ── 9. the latch survives a live drag (dragover keeps the session fresh) ────
console.log('\n9. escape latch is drag-scoped: dragover keeps it alive, silence ends it')
{
  resetHost()
  fetches.length = 0
  entryPhase = 'spec'
  const dt = new FakeDataTransfer([file('合同.pdf', 'application/pdf', 10)])
  enter(dt)
  click(closeBtn()) // live escape → latched
  clock.t += 1_000
  over(dt) // the browser keeps firing dragover while the drag is alive
  clock.t += 1_000 // 2s total, but the session never went quiet
  enter(dt)
  assert(overlay() === null && chip() === null, 'latch survived the live drag (dragover kept it fresh)')
  drop(dt)
  assert(host.addFilesCalls === 1, 'its drop still goes to the host')
  hostClean('after the latched live drag')
}

// ─────────────────────────── 10. watchdog ───────────────────────────────────
console.log('\n10. watchdog → a mask whose drag never ends clears itself, drop handed back')
{
  resetHost()
  fetches.length = 0
  entryPhase = 'spec'
  const dt = new FakeDataTransfer([file('合同.pdf', 'application/pdf', 10)])
  enter(dt)
  assert(overlay() !== null, 'mask shown')
  advance(10_000)
  assert(overlay() === null, 'mask gone after the 10s watchdog')
  assert(chip() === null, 'escape chip gone with it')
  hostClean('after watchdog')
  enter(dt)
  assert(overlay() === null, 'the watchdog-escaped drag stays hands-off')
  drop(dt)
  assert(host.addFilesCalls === 1, 'its drop goes to the host')
  assert(fetches.length === 0, 'nothing uploaded')
  hostClean('after the watchdog-escaped drop')
}

// ───── 11. × chip on a released drag → clears a wedged host mask ────────────
console.log('\n11. × chip on a released folder drag → clears a wedged host mask')
{
  resetHost()
  entryPhase = 'spec'
  const dt = new FakeDataTransfer([folder()], { entries: [{ isDirectory: true }] })
  enter(dt)
  host.dragDepth = 3 // simulate a mask the host already wedged (dead drag session)
  host.active = true
  assert(overlay() === null && chip() !== null, 'chip present, no FormatForge mask')
  click(chip())
  assert(chip() === null, 'chip removed on click')
  hostClean('after × on the chip')

  // Clicking the chip must NOT poison the user's drags: the same (still live)
  // released drag may re-show the chip, but never a mask, and the host keeps it.
  enter(dt)
  assert(overlay() === null, 'no mask on the continuation')
  assert(chip() !== null, 'chip may return for the same live drag')
  assert(host.dragDepth === 1, 'host owns the continuation drag')
  drop(dt)
  hostClean('after the continuation drop')
}

// ───────── 12. empty / typeless files are never silently dropped ────────────
console.log('\n12. empty / typeless FILES are never silently dropped')
{
  resetHost()
  fetches.length = 0
  entryPhase = 'spec'
  for (const f of [file('README', 'text/plain', 0), file('data', '', 100), file('LICENSE', '', 0)]) {
    clock.t += 3_000 // three separate drags
    const dt = new FakeDataTransfer([f])
    enter(dt)
    drop(dt)
  }
  await tick()
  const names = uploadedNames()
  assert(names.includes('README'), 'empty file with a MIME type uploaded', names.join(','))
  assert(names.includes('data'), 'typeless file with content uploaded', names.join(','))
  assert(names.includes('LICENSE'), 'typeless empty file reaches a handler too (no silent loss)', names.join(','))
}

// ── 13. mixed drag where only one item answers the entry API ────────────────
console.log('\n13. mixed folder + file with a partially readable entry API → released')
{
  resetHost()
  fetches.length = 0
  entryPhase = 'spec'
  const pdfFile = file('合同.pdf', 'application/pdf', 1234)
  const dir = folder('资料')
  const dt = new FakeDataTransfer([pdfFile, dir], { entries: [{ isDirectory: false }, null] })
  enter(dt)
  assert(overlay() === null, 'no mask: the unreadable directory-shaped item forces a release')
  drop(dt)
  await tick()
  assert(host.addFilesCalls === 1 && host.addedFiles.length === 2, 'host received the whole drag')
  assert(fetches.length === 0, 'nothing was uploaded out of a rejected drag')
  hostClean('mixed drag with a silent entry')
}

// ─────────────── 14. drag leaving the viewport (dead session) ───────────────
console.log('\n14. drag leaving the viewport → mask/chip retired, host balances itself')
{
  resetHost()
  entryPhase = 'spec'
  const dt = new FakeDataTransfer([file('合同.pdf', 'application/pdf', 10)])
  enter(dt)
  over(dt)
  leaveAtEdge(dt)
  assert(overlay() === null, 'mask hidden when the drag leaves the viewport')
  hostClean('after leave-at-edge')

  clock.t += 3_000
  const folderDt = new FakeDataTransfer([folder()], { entries: [{ isDirectory: true }] })
  enter(folderDt)
  assert(chip() !== null, '× chip present on the released drag')
  leaveAtEdge(folderDt)
  advance(8_000)
  assert(chip() === null, '× chip retired after the released drag left the viewport')
  hostClean('after the released drag left the viewport')
}

// ─────────────── 15. real window dragend (in-page drag source) ──────────────
console.log('\n15. real dragend → mask gone, chip lingers then retires')
{
  resetHost()
  entryPhase = 'spec'
  const dt = new FakeDataTransfer([file('合同.pdf', 'application/pdf', 10)])
  enter(dt)
  assert(overlay() !== null, 'mask shown')
  realDragEnd()
  assert(overlay() === null, 'mask cleared by the real dragend')
  assert(chip() !== null, 'chip lingers so a wedged mask stays dismissible')
  advance(8_000)
  assert(chip() === null, 'chip retired after the linger')
  hostClean('after the real dragend')
}

// ────────────────────── 16. disposer / HMR cleanliness ──────────────────────
console.log('\n16. disposer → listeners and escape elements removed')
{
  resetHost()
  entryPhase = 'spec'
  const dt = new FakeDataTransfer([file('合同.pdf', 'application/pdf', 10)])
  enter(dt)
  assert(overlay() !== null && chip() !== null, 'mask + chip present before teardown')
  disposers[0]()
  assert(overlay() === null && chip() === null, 'teardown removed both')
  assert(
    doc.countListeners() + win.countListeners() === listenersBefore,
    'every listener removed',
    `${doc.countListeners() + win.countListeners()} vs ${listenersBefore}`,
  )
}

const errors = consoleLogs.filter((l) => /error|failed/i.test(l))
if (errors.length > 0) console.log('\nlog notes    :', errors.join(' | '))

if (failures > 0) {
  console.error(`\nCLIENT-DRAG-FAIL: ${failures}/${checks} assertion(s) failed`)
  process.exit(1)
}
console.log(`\nassertions   : ${checks} passed`)
console.log('CLIENT-DRAG-OK:', pkg.name, '|', pkg.version, '| 拖拽文件夹放行 + × 逃生 + 宿主计数复位')
