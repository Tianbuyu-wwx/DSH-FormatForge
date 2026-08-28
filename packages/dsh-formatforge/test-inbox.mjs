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

rmSync(testHome, { recursive: true, force: true })
console.log('INBOX-E2E-DONE')
