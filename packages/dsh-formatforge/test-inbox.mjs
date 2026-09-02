// 本地开发测试 inbox watcher（不依赖 dsh 运行时）：
// 建临时 FF_HOME → 拷 fixture 进 inbox → 等 watcher 转换 → 校验产物与通知回调。
// 用法：node packages/dsh-formatforge/test-inbox.mjs

import { mkdirSync, writeFileSync, copyFileSync, rmSync, existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = 'E:/项目/DSH-FormatForge'

// stub @deepseek-ai/*（watcher 本身不需要，但 import 链上的 index 不在此测试中）
const testHome = join(tmpdir(), `ffinbox-test-${Date.now()}`)
process.env.FF_HOME = testHome
process.env.FF_INBOX_NOTIFY = 'true'
process.env.FF_INBOX_TTL_DAYS = '999'  // 关闭 TTL：fixture mtime 古老会被 retention 判过期

mkdirSync(join(testHome, 'inbox'), { recursive: true })

const { createInboxWatcher, inboxDir } = await import('./services/inbox-watcher.mjs')
console.log('inbox at:', inboxDir())
if (inboxDir() !== join(testHome, 'inbox')) {
  console.error('FAIL: FF_HOME not honored')
  process.exit(1)
}

const events = []
const watcher = createInboxWatcher({
  repoRoot,
  maxBytes: 100 * 1024 * 1024,
  timeoutMs: 120_000,
  log: (l) => console.log('  ', l),
  onDone: (r) => {
    console.log('onDone:', JSON.stringify(r))
    events.push(r)
  },
})
watcher.start()

// 场景1：拖入一个 txt
copyFileSync(join(repoRoot, 'test', 'fixtures', 'gbk_chinese.txt'), join(inboxDir(), 'sample.txt'))
await new Promise((r) => setTimeout(r, 6000))

const jsonPath = join(inboxDir(), 'sample.ff.json')
const mdPath = join(inboxDir(), 'sample.ff.md')
console.log('json exists:', existsSync(jsonPath), '| md exists:', existsSync(mdPath))
if (existsSync(mdPath)) {
  const md = readFileSync(mdPath, 'utf8')
  console.log('md head:', md.slice(0, 60).replace(/\n/g, '\\n'))
}
console.log('events so far:', events.length)
console.log('last event:', JSON.stringify(events[events.length - 1]))

// R3.2: onDone payload 必须含 resultId（会话模型据此 ff_result 取回）
const translated = events.find((e) => e.file === 'sample.txt' && e.ok === true)
const hasResultId = translated && typeof translated.resultId === 'string' && translated.resultId.startsWith('cvt')
console.log('R3.2 onDone.resultId present:', hasResultId, '(id=', translated?.resultId, ')')

// 场景2：重复拷贝同内容不同名 → 应各自转换（名字不同）；同名覆盖 mtime 变 → 也重转
// 场景3：不支持的扩展名 → error 文件
writeFileSync(join(inboxDir(), 'junk.exe'), Buffer.from([0x4d, 0x5a, 0x00]))
await new Promise((r) => setTimeout(r, 5000))
const errPath = join(inboxDir(), 'junk.ff.error.txt')
console.log('unsupported ext produces no output (exe not in whitelist):', !existsSync(errPath))

// 场景4：重启 watcher —— 已有产物的文件不再重放
watcher.stop()
const w2 = createInboxWatcher({ repoRoot, log: () => {}, onDone: (r) => events.push(r) })
w2.start()
await new Promise((r) => setTimeout(r, 4000))
w2.stop()
console.log('after restart, no re-processing:', events.filter((e) => e.file === 'sample.txt').length === 1)

// 场景5（v0.14.0/B-P1-3）：retention 清理通知降噪
// 预期：retention=true 的事件 → broadcast 收到空文本（notify.broadcast 跳过），
// 而 onDone 回调仍然被 inbox-watcher 触发（行为不丢，仅日志层面降噪）。
const { makeNotifier } = await import('./services/notify.mjs')
const capturedTexts = []
const fakeCtx = {
  sessions: {
    get: (id) => ({
      append: (type, msg, opts) => {
        if (type === 'user/message' && msg?.content?.[0]?.text) {
          capturedTexts.push(msg.content[0].text)
        }
      },
    }),
  },
  agents: { list: () => [{ id: 'session-A' }] },
}
const notifier = makeNotifier({ log: () => {} })
notifier.broadcast(fakeCtx, notifier.buildNotice({ retention: true, count: 5 }))
notifier.broadcast(fakeCtx, notifier.buildNotice({ ok: true, file: 'r.txt', parser: 'txt', confidence: 0.9 }))
console.log('retention broadcast captured:', capturedTexts.filter((t) => t.includes('收件箱清理')).length, '(expect 0)')
console.log('normal conversion broadcast captured:', capturedTexts.filter((t) => t.includes('已锻好')).length, '(expect 1)')

// 场景6（v0.14.0/B-P1-4）：retention 清理后 .ff.retired.log 应有 entry
// 测：在新 FF_HOME 里造一个旧文件 + 触发 retention → 验证 .ff.retired.log 存在
import { readFileSync as _rfs, writeFileSync as _wfs, utimesSync } from 'node:fs'
const home6 = join(tmpdir(), `ffinbox-test-r6-${Date.now()}`)
const inbox6 = join(home6, 'inbox')
process.env.FF_HOME = home6
mkdirSync(inbox6, { recursive: true })
// v0.14.0 enforceRetention: MAX_BYTES=0 短路 return；用 0.001 MB (~1024 bytes) cap
// 让任何非空文件都超 cap → 全部标 doomed 走清理。
process.env.FF_INBOX_TTL_DAYS = '0'
process.env.FF_INBOX_MAX_MB = '0.001'

const oldFile = join(inbox6, 'old-report.txt')
_wfs(oldFile, '这是将被清理的旧文件\n'.repeat(50), 'utf-8')  // ~1KB
utimesSync(oldFile, 946684800, 946684800)  // 2000-01-01

const { createInboxWatcher: createW6 } = await import('./services/inbox-watcher.mjs')
const retiredOnDoneEvents = []
const w6 = createW6({
  repoRoot,
  maxBytes: 100 * 1024 * 1024,
  timeoutMs: 30_000,
  log: () => {},
  onDone: (r) => { retiredOnDoneEvents.push(r) },
})
w6.start()
// 等待 retention tick（默认 SCAN_INTERVAL_MS=2000ms 后 enforceRetention 跑）
await new Promise((r) => setTimeout(r, 5000))
w6.stop()

const retiredLog = join(inbox6, '.ff.retired.log')
const logExists = existsSync(retiredLog)
console.log('.ff.retired.log created:', logExists, '(expect true)')
if (logExists) {
  const content = _rfs(retiredLog, 'utf-8').trim()
  const lines = content.split('\n').length
  console.log('.ff.retired.log lines:', lines, '(expect 1)')
  // 验证 entry 含必要字段
  const entry = JSON.parse(content.split('\n')[0])
  console.log('retired entry has sha256:', typeof entry.sha256 === 'string' && entry.sha256.length === 64)
  console.log('retired entry has path:', entry.path === oldFile)
  console.log('retired entry has ts:', typeof entry.ts === 'string')
  console.log('file deleted:', !existsSync(oldFile))
}
rmSync(home6, { recursive: true, force: true })

rmSync(testHome, { recursive: true, force: true })
console.log('INBOX-E2E-DONE')
