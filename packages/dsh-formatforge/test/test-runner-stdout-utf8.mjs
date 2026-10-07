// packages/dsh-formatforge/test/test-runner-stdout-utf8.mjs
//
// T1-1 回归：`python-runner.mjs` 的 stdout 此前用 `stdout += d` 累积——每个原始
// Buffer chunk 被**独立**强制转成字符串，跨 chunk 边界的多字节 UTF-8 序列于是
// 各自解成 U+FFFD。协议 JSON 仍然能 parse，内容却已静默损坏；这是每一次转换
// 内容必经的唯一通路，inbox watcher 还会把损坏文本落盘。
//
// 两层验证：
//   1) 单元层：直接驱动 createStdoutCollector，手工切在多字节序列中间（确定性）。
//   2) 端到端：真实跑一次 1MB 纯 CJK 转换，断言返回内容里没有 U+FFFD。
//
// 用法：node packages/dsh-formatforge/test/test-runner-stdout-utf8.mjs

import { mkdtempSync, writeFileSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

let failures = 0
function check(name, cond, detail = '') {
  if (cond) {
    console.log(`✅ ${name}`)
  } else {
    failures++
    console.error(`❌ ${name}  ${detail}`)
  }
}

const { runFormatForge, createStdoutCollector } = await import('../services/python-runner.mjs')
const repoRoot = join(import.meta.dirname, '..', '..', '..')

console.log('\n=== stdout UTF-8 integrity (T1-1) ===\n')

check('python-runner exports a byte-level stdout collector', typeof createStdoutCollector === 'function', String(typeof createStdoutCollector))

// 单元层检查需要这个导出；端到端检查不需要，未修复时也必须跑到（它验证的是行为）。
const hasCollector = typeof createStdoutCollector === 'function'
if (!hasCollector) console.error('   ↳ createStdoutCollector 缺失，跳过单元层检查，仅跑端到端')

// ── 1) 单元层：7 字节切片，保证切在 3 字节序列中间 ──────────────────────
if (hasCollector) {
  const payload = '中文测试'.repeat(3) // 12 字符 / 36 字节
  const bytes = Buffer.from(payload, 'utf8')
  const collector = createStdoutCollector(1 << 20)
  for (let i = 0; i < bytes.length; i += 7) collector.push(bytes.subarray(i, i + 7))
  const decoded = collector.text()
  check('7 字节切片：解码结果与原文逐字符相同', decoded === payload, `got=${JSON.stringify(decoded)}`)
  check('7 字节切片：没有 U+FFFD', !decoded.includes('\uFFFD'), `count=${(decoded.match(/\uFFFD/g) || []).length}`)
  check('7 字节切片：字节数按字节计', collector.bytes === 36, String(collector.bytes))
}

// ── 1b) 4 字节序列（星形平面 emoji）被切开 ──────────────────────────────
if (hasCollector) {
  const payload = '语料😀结束'
  const bytes = Buffer.from(payload, 'utf8')
  const collector = createStdoutCollector(1 << 20)
  // 切点落在 emoji 的 4 字节序列内部
  const cut = 6 + 2
  collector.push(bytes.subarray(0, cut))
  collector.push(bytes.subarray(cut))
  check('切开 4 字节 emoji：解码仍精确', collector.text() === payload, JSON.stringify(collector.text()))
}

// ── 1c) 逐字节投喂（最坏情况） ─────────────────────────────────────────
if (hasCollector) {
  const payload = '每一个字节都单独到达：中文测试内容'
  const bytes = Buffer.from(payload, 'utf8')
  const collector = createStdoutCollector(1 << 20)
  for (const b of bytes) collector.push(Buffer.from([b]))
  check('逐字节投喂：解码仍精确', collector.text() === payload, JSON.stringify(collector.text()))
}

// ── 1d) 上限仍按字节生效，且超限 chunk 不入列 ───────────────────────────
if (hasCollector) {
  const collector = createStdoutCollector(10)
  check('cap: 前 8 字节被接受', collector.push(Buffer.alloc(8)) === true)
  check('cap: 越界的 chunk 被拒绝', collector.push(Buffer.alloc(8)) === false)
  check('cap: overflow 被记录', collector.overflow === true)
  check('cap: 被拒绝的 chunk 没有进入缓冲', collector.text().length === 8, String(collector.text().length))
}

// ── 2) 端到端：真实转换，1MB 纯 CJK（远超单个 64KB 管道 chunk） ──────────
{
  const dir = mkdtempSync(join(tmpdir(), 'ff-stdout-utf8-'))
  process.on('exit', () => rmSync(dir, { recursive: true, force: true }))
  const unit = '中文测试内容一二三四五六七八九十'
  const body = unit.repeat(Math.ceil((1024 * 1024) / Buffer.byteLength(unit)))
  const src = join(dir, 'cjk-1mb.txt')
  writeFileSync(src, body, 'utf-8')

  const res = await runFormatForge({
    cliArgs: ['translate', src, '--format', 'text'],
    repoRoot,
    timeoutMs: 120_000,
    log: () => {},
  })
  const content = typeof res?.data?.content === 'string' ? res.data.content : ''
  const mojibake = (content.match(/\uFFFD/g) || []).length

  check('e2e: 转换成功', res.ok === true, JSON.stringify(res).slice(0, 200))
  check('e2e: 返回了内容', content.length > 0, `len=${content.length}`)
  check('e2e: 1MB CJK 通过管道后没有 U+FFFD', mojibake === 0, `U+FFFD × ${mojibake}`)
  check('e2e: 内容仍是原始 CJK 语料', content.includes(unit), content.slice(0, 80))
}

if (failures > 0) {
  console.error(`\n❌ ${failures} check(s) failed`)
  process.exit(1)
}
console.log('\n✅ stdout decodes as one UTF-8 stream')
