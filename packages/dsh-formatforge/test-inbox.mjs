// packages/dsh-formatforge/test-inbox.mjs
//
// 本地开发测试 inbox watcher（不依赖 dsh 运行时）：
// 建临时 FF_HOME → 拷 fixture 进 inbox → 等 watcher 转换 → **断言**产物与 onDone 载荷。
//
// v1.0.3/JS-H8 修复：本文件此前硬编码作者的机器路径（`E:/项目/DSH-FormatForge`）、
// 从不调用 ff_result、且只 printf 不 assert —— 头条 JS-H1 的协议键漂移就是这样漏掉的。
// 现在：路径从仓库布局推导、真实调用 ff_result 取回正文、每条检查都是断言且失败非零退出。
//
// 用法：node packages/dsh-formatforge/test-inbox.mjs

import { mkdirSync, writeFileSync, copyFileSync, rmSync, existsSync, readFileSync, utimesSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { tmpdir } from 'node:os'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
// 本文件在包根（<repo>/packages/dsh-formatforge）→ 仓库根（含 formatforge/ core/ test/fixtures）在上两层
const repoRoot = join(here, '..', '..')

// ─── 断言工具 ───
let failures = 0
function check(name, cond, detail = '') {
  if (cond) {
    console.log(`✅ ${name}`)
  } else {
    failures++
    console.error(`❌ ${name}  ${detail}`)
  }
}
function section(title) {
  console.log(`\n--- ${title} ---`)
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// ─── @deepseek-ai/dsh-tools stub（只为让 tools/result.mjs 能在裸 Node 下导入；
//     M19 教训：只在包根 node_modules 不存在时建，且只清理自己建的目录） ───
const stubRoot = join(here, 'node_modules', '@deepseek-ai')
const stubOwned = !existsSync(join(here, 'node_modules'))
if (stubOwned) {
  const dir = join(stubRoot, 'dsh-tools')
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, 'index.mjs'), `export function defineTool(spec) { return spec }\n`)
  writeFileSync(
    join(dir, 'package.json'),
    JSON.stringify({ name: '@deepseek-ai/dsh-tools', version: '0.0.0', type: 'module', main: './index.mjs' }),
  )
}

// ─── 隔离环境 ───
const testHome = join(tmpdir(), `ffinbox-test-${Date.now()}`)
process.env.FF_HOME = testHome
process.env.FF_INBOX_NOTIFY = 'true'
process.env.FF_INBOX_TTL_DAYS = '999' // 关闭 TTL：fixture mtime 古老会被 retention 判过期
process.env.FF_INBOX_MAX_MB = '0'
mkdirSync(join(testHome, 'inbox'), { recursive: true })

const cleanup = () => {
  if (stubOwned) rmSync(join(here, 'node_modules'), { recursive: true, force: true })
  rmSync(testHome, { recursive: true, force: true })
}
process.on('exit', cleanup)

const { createInboxWatcher, inboxDir } = await import('./services/inbox-watcher.mjs')
const { createResultTool } = await import('./tools/result.mjs')
const resultTool = createResultTool({ log: () => {} })

console.log('\n=== inbox watcher E2E (JS-H3/H4/H8) ===')
console.log('inbox at:', inboxDir())

section('S0 FF_HOME honored')
check('FF_HOME honored', inboxDir() === join(testHome, 'inbox'), inboxDir())

// ─── 主 watcher：真实转换 ───
const events = []
const watcher = createInboxWatcher({
  repoRoot,
  maxBytes: 100 * 1024 * 1024,
  timeoutMs: 120_000,
  log: () => {},
  onDone: (r) => events.push(r),
})
watcher.start()
// 启动预检先跑一遍再投文件，避免与首轮 scanStable 抢时序
await sleep(2200)

section('S1 真实转换（txt → markdown）+ ff_result 取回')
const fixture = join(repoRoot, 'test', 'fixtures', 'gbk_chinese.txt')
check('fixture exists', existsSync(fixture), fixture)
copyFileSync(fixture, join(inboxDir(), 'sample.txt'))
await sleep(7000)

const jsonPath = join(inboxDir(), 'sample.txt.ff.json')
const mdPath = join(inboxDir(), 'sample.txt.ff.md')
check('artifact keyed by source name + ext (sample.txt.ff.json)', existsSync(jsonPath), JSON.stringify(readdirSafe()))
check('markdown artifact written', existsSync(mdPath))
check('legacy stem-only key NOT used', !existsSync(join(inboxDir(), 'sample.ff.json')))

const translated = events.find((e) => e.file === 'sample.txt' && e.ok === true)
check('onDone fired ok:true for sample.txt', !!translated, JSON.stringify(events.slice(-2)))
check('onDone.resultId present (cvt…)', typeof translated?.resultId === 'string' && translated.resultId.startsWith('cvt'), String(translated?.resultId))
check('onDone.parser reported', !!translated?.parser, String(translated?.parser))

// JS-H1 头条回归：通知里广告的 result_id 必须真的能取回正文
const fetched = await resultTool.execute({ id: translated?.resultId })
check('ff_result(resultId) → ok', fetched.ok === true, JSON.stringify(fetched).slice(0, 300))
check('ff_result returns NON-EMPTY content', typeof fetched.data?.content === 'string' && fetched.data.content.length > 0, `len=${fetched.data?.content?.length}`)
check('ff_result content matches the .ff.md artifact', readFileSync(mdPath, 'utf8').startsWith(fetched.data?.content?.slice(0, 20)), JSON.stringify(fetched.data?.content?.slice(0, 40)))
check('ff_result reports parser from meta.parser', fetched.data?.parser === translated?.parser, JSON.stringify({ tool: fetched.data?.parser, notify: translated?.parser }))
check('ff_result reports confidence from meta.confidence', fetched.data?.confidence === translated?.confidence, JSON.stringify({ tool: fetched.data?.confidence, notify: translated?.confidence }))
check('ff_result reports meta.file_size', typeof fetched.data?.file_size === 'number' && fetched.data.file_size > 0, String(fetched.data?.file_size))
const listed = await resultTool.execute({ list: true })
const row = listed.data?.items?.find((it) => it.file === 'sample.txt.ff.json')
check('ff_result list shows the artifact as valid', !!row && row.valid === true && row.parser === translated?.parser, JSON.stringify(row))

section('S2 JS-H4 同 stem 不同扩展名不互相覆盖')
writeFileSync(join(inboxDir(), 'dup.txt'), 'dup txt body\n'.repeat(5), 'utf-8')
writeFileSync(join(inboxDir(), 'dup.md'), '# dup md body\n'.repeat(5), 'utf-8')
await sleep(7000)
check('dup.txt artifact exists', existsSync(join(inboxDir(), 'dup.txt.ff.json')))
check('dup.md artifact exists', existsSync(join(inboxDir(), 'dup.md.ff.json')))
check('no shared stem-only artifact (dup.ff.json)', !existsSync(join(inboxDir(), 'dup.ff.json')))
const dupTxt = readFileSync(join(inboxDir(), 'dup.txt.ff.md'), 'utf8')
const dupMd = readFileSync(join(inboxDir(), 'dup.md.ff.md'), 'utf8')
check('both dup conversions kept their own content', dupTxt.includes('dup txt body') && dupMd.includes('dup md body'), JSON.stringify({ txt: dupTxt.slice(0, 30), md: dupMd.slice(0, 30) }))

section('S3 不支持扩展名：不转换、不写错误文件（实际契约）')
writeFileSync(join(inboxDir(), 'junk.exe'), Buffer.from([0x4d, 0x5a, 0x00]))
await sleep(4000)
check('unsupported ext: no error artifact', !existsSync(join(inboxDir(), 'junk.exe.ff.error.txt')))
check('unsupported ext: no conversion artifact', !existsSync(join(inboxDir(), 'junk.exe.ff.json')))

section('S4 重启：已有产物不重放')
watcher.stop()
const before = events.filter((e) => e.file === 'sample.txt').length
const w2 = createInboxWatcher({ repoRoot, log: () => {}, onDone: (r) => events.push(r) })
w2.start()
await sleep(4000)
w2.stop()
check('restart does not re-process sample.txt', events.filter((e) => e.file === 'sample.txt').length === before, JSON.stringify({ before, after: events.filter((e) => e.file === 'sample.txt').length }))

// ─── S5 too_large（JS-H3：终态必须记 doneAt，否则每个 tick 重通知） ───
section('S5 too_large：只通知一次（JS-H3）')
const home5 = join(tmpdir(), `ffinbox-test-tooLarge-${Date.now()}`)
mkdirSync(join(home5, 'inbox'), { recursive: true })
writeFileSync(join(home5, 'inbox', 'huge.txt'), 'x'.repeat(4000), 'utf-8')
process.env.FF_HOME = home5
const tooLargeEvents = []
const w5 = createInboxWatcher({ repoRoot, maxBytes: 1000, timeoutMs: 60_000, log: () => {}, onDone: (r) => tooLargeEvents.push(r) })
w5.start()
await sleep(11_000) // setInterval 首触发在 2s；11s 覆盖 5 个 tick
w5.stop()
const tooLarge = tooLargeEvents.filter((e) => e.kind === 'too_large')
check('too_large notified exactly once across 5 ticks', tooLarge.length === 1, `count=${tooLarge.length}`)
check('too_large error artifact written', existsSync(join(home5, 'inbox', 'huge.txt.ff.error.txt')))
check('too_large error artifact is source-keyed', !existsSync(join(home5, 'inbox', 'huge.ff.error.txt')))
process.env.FF_HOME = testHome
rmSync(home5, { recursive: true, force: true })

// ─── S6 CLI 失败 → .ff.error.txt（此前零覆盖的分支） ───
section('S6 转换失败 → .ff.error.txt（timeoutMs=50 强制超时）')
const home6 = join(tmpdir(), `ffinbox-test-fail-${Date.now()}`)
mkdirSync(join(home6, 'inbox'), { recursive: true })
writeFileSync(join(home6, 'inbox', 'slow.txt'), 'y'.repeat(200), 'utf-8')
process.env.FF_HOME = home6
const failEvents = []
const w6 = createInboxWatcher({ repoRoot, maxBytes: 100 * 1024 * 1024, timeoutMs: 50, log: () => {}, onDone: (r) => failEvents.push(r) })
w6.start()
await sleep(7000)
w6.stop()
const failure = failEvents.find((e) => e.file === 'slow.txt' && e.ok === false)
check('CLI failure reported as ok:false', !!failure, JSON.stringify(failEvents))
check('failure kind is timeout', failure?.kind === 'timeout', String(failure?.kind))
check('failure wrote .ff.error.txt', existsSync(join(home6, 'inbox', 'slow.txt.ff.error.txt')))
check('failure did not write a result artifact', !existsSync(join(home6, 'inbox', 'slow.txt.ff.json')))
process.env.FF_HOME = testHome
rmSync(home6, { recursive: true, force: true })

// ─── S7 通知器：retention 降噪 + 正常转换广播 ───
section('S7 通知器降噪')
const { makeNotifier } = await import('./services/notify.mjs')
const capturedTexts = []
const fakeCtx = {
  sessions: { get: () => ({ append: (_type, msg) => { if (msg?.content?.[0]?.text) capturedTexts.push(msg.content[0].text) } }) },
  agents: { list: () => [{ id: 'session-A' }] },
}
const notifier = makeNotifier({ log: () => {} })
notifier.broadcast(fakeCtx, notifier.buildNotice({ retention: true, count: 5 }))
notifier.broadcast(fakeCtx, notifier.buildNotice({ ok: true, file: 'r.txt', parser: 'txt', confidence: 0.9 }))
check('retention broadcast suppressed', capturedTexts.filter((t) => t.includes('清理')).length === 0, JSON.stringify(capturedTexts))
check('normal conversion broadcast once', capturedTexts.filter((t) => t.includes('已锻好')).length === 1, JSON.stringify(capturedTexts))

// ─── S8 retention → .ff.retired.log ───
section('S8 retention 清理写 .ff.retired.log')
const home8 = join(tmpdir(), `ffinbox-test-r8-${Date.now()}`)
const inbox8 = join(home8, 'inbox')
mkdirSync(inbox8, { recursive: true })
process.env.FF_HOME = home8
process.env.FF_INBOX_TTL_DAYS = '0'
process.env.FF_INBOX_MAX_MB = '0.001'
const oldFile = join(inbox8, 'old-report.txt')
writeFileSync(oldFile, '这是将被清理的旧文件\n'.repeat(50), 'utf-8') // ~1KB > 0.001MB cap
utimesSync(oldFile, 946684800, 946684800) // 2000-01-01
const w8 = createInboxWatcher({ repoRoot, maxBytes: 100 * 1024 * 1024, timeoutMs: 30_000, log: () => {}, onDone: () => {} })
w8.start()
await sleep(5000)
w8.stop()
process.env.FF_HOME = testHome
process.env.FF_INBOX_TTL_DAYS = '999'
process.env.FF_INBOX_MAX_MB = '0'
const retiredLog = join(inbox8, '.ff.retired.log')
check('.ff.retired.log created', existsSync(retiredLog))
if (existsSync(retiredLog)) {
  const lines = readFileSync(retiredLog, 'utf-8').trim().split('\n')
  check('.ff.retired.log has one entry', lines.length === 1, `lines=${lines.length}`)
  const entry = JSON.parse(lines[0])
  check('retired entry has sha256', typeof entry.sha256 === 'string' && entry.sha256.length === 64)
  check('retired entry path matches', entry.path === oldFile, String(entry.path))
  check('retired entry has ts', typeof entry.ts === 'string')
}
check('expired file deleted', !existsSync(oldFile))
rmSync(home8, { recursive: true, force: true })

function readdirSafe() {
  try {
    const { readdirSync } = process.getBuiltinModule('node:fs')
    return readdirSync(inboxDir())
  } catch {
    return []
  }
}

console.log('')
if (failures > 0) {
  console.error(`❌ ${failures} assertion(s) failed`)
  process.exit(1)
}
console.log('✅ INBOX-E2E-DONE — all assertions passed')