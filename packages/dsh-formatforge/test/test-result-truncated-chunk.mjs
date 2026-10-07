// packages/dsh-formatforge/test/test-result-truncated-chunk.mjs
//
// T3-2 回归（审计）：流式扫描器在跳字符串时用 `buf.indexOf(0x22, i)` 搜**整块**
// 64KB 复用缓冲，而不是本次真正读到的 `[0, read)`。短读（截断产物，或 watcher
// 非原子写到一半的产物）之后，`[read, 64KB)` 还留着上一块的字节 —— 在那里匹配到
// 一个陈旧引号，扫描器就会认为字符串已闭合，并从一个并不存在的偏移继续。
//
// 说明（诚实起见）：在「短读即 EOF」这一种情形下，陈旧匹配之后 `i = q + 1 > read`
// 会立刻退出内层循环，随后的 readSync 返回 0，`{ok, contentIsString, meta}` 与修复后
// **逐字段相同** —— 本文件的断言因此在修复前后都通过，它钉住的是「截断产物必须按
// 读到的字节判成非法」这条契约。真正的行为差异出现在「短读不是最后一次读」时
// （watcher 非原子写 .ff.json，list 正好扫到写了一半的文件），那时残留字节会带着
// 错误的 inString 状态进入下一块。最后一节用同样被污染的缓冲直接验证两种搜索的
// 分歧（机制层，与 T3-4 的报告者做法一致）。
//
// 用法：node packages/dsh-formatforge/test/test-result-truncated-chunk.mjs

import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { writeFileSync, mkdtempSync, rmSync, mkdirSync, existsSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'

const here = dirname(fileURLToPath(import.meta.url))
const pkgRoot = join(here, '..')

// ESM stub（同 test-result-large-meta.mjs：只在包根 node_modules 不存在时才建，且只删自己建的）
const stubRoot = join(pkgRoot, 'node_modules', '@deepseek-ai')
const stubOwned = !existsSync(join(pkgRoot, 'node_modules'))
if (stubOwned) {
  const dir = join(stubRoot, 'dsh-tools')
  mkdirSync(dir, { recursive: true })
  writeFileSync(join(dir, 'index.mjs'), `export function defineTool(spec) { return spec }\n`)
  writeFileSync(
    join(dir, 'package.json'),
    JSON.stringify({ name: '@deepseek-ai/dsh-tools', version: '0.0.0', type: 'module', main: './index.mjs' }),
  )
}

const home = mkdtempSync(join(tmpdir(), 'ff-trunc-test-'))
const inbox = join(home, 'inbox')
mkdirSync(inbox, { recursive: true })
process.env.FF_HOME = home
process.on('exit', () => {
  if (stubOwned) rmSync(join(pkgRoot, 'node_modules'), { recursive: true, force: true })
  rmSync(home, { recursive: true, force: true })
})

let failures = 0
function check(name, cond, detail = '') {
  if (cond) {
    console.log(`✅ ${name}`)
  } else {
    failures++
    console.error(`❌ ${name}  ${detail}`)
  }
}

const CHUNK = 64 * 1024 // result.mjs::SCAN_CHUNK_BYTES

// 截断产物：总长 64KB + 200 → 最后一块 read=200（与缓冲大小不同），
// 且这 200 字节落在一个**没有闭合**的字符串里；复用缓冲的 [200, 64KB) 残留着
// 上一块的真引号（content 的闭合引号、format/structured_data 的键引号……）。
const head = '{"ok":true,"code":200,"data":{"content":"'
const CONTENT_END = 64_000
const mid = '","format":"markdown","structured_data":{"note":"'
const total = CHUNK + 200
const truncated =
  head + 'x'.repeat(CONTENT_END - head.length) + mid + 'y'.repeat(total - CONTENT_END - mid.length)
writeFileSync(join(inbox, 'truncated.ff.json'), truncated, 'utf8')
check('fixture: final chunk length differs from the scan buffer', statSync(join(inbox, 'truncated.ff.json')).size % CHUNK === 200, String(statSync(join(inbox, 'truncated.ff.json')).size))
check(
  'fixture: the stale tail really does hold unescaped quotes',
  truncated.slice(200, CHUNK).includes('"'),
  'no quote in [200, 64KB)',
)

// 同一尺寸级别的**完整**产物：证明「非法」来自截断，不是来自大小
const okDoc = {
  ok: true,
  code: 200,
  data: {
    content: 'z'.repeat(CONTENT_END),
    format: 'markdown',
    meta: { parser: 'txt', file_size: 123, result_id: 'cvt_trunc00001', confidence: 0.77 },
  },
}
writeFileSync(join(inbox, 'intact.ff.json'), JSON.stringify(okDoc))

const { createResultTool } = await import('../tools/result.mjs')
const tool = createResultTool({ log: () => {} })

console.log('\n=== ff_result truncated final chunk (T3-2) ===\n')

const t0 = Date.now()
const listed = await tool.execute({ list: true })
const elapsed = Date.now() - t0
const truncRow = listed.data.items.find((it) => it.file === 'truncated.ff.json')
const intactRow = listed.data.items.find((it) => it.file === 'intact.ff.json')

check('truncated artifact is reported invalid', truncRow?.valid === false, JSON.stringify(truncRow))
check('truncated artifact exposes no meta from stale bytes', !truncRow?.confidence && truncRow?.parser === '?', JSON.stringify(truncRow))
check('intact artifact of the same size class is still valid', intactRow?.valid === true && intactRow?.id === 'cvt_trunc00001', JSON.stringify(intactRow))
check('scan of a truncated artifact terminates promptly', elapsed < 5_000, `${elapsed}ms`)

const fetched = await tool.execute({ id: 'truncated' })
check(
  'fetching the truncated artifact is rejected',
  fetched.ok === false && (fetched.error?.kind === 'parse_failed' || fetched.error?.kind === 'not_a_conversion_result'),
  JSON.stringify(fetched),
)

// ---- 机制层：同一块被污染的缓冲，两种搜索的分歧 ----
// 这段不经过 result.mjs，它记录的是修复到底改了什么：短读之后，无界搜索会命中
// 上一块残留的引号，而按 [0, read) 限定的搜索不会。
const buf = Buffer.alloc(CHUNK)
buf.fill(0x51) // 上一块：'Q'
buf[CHUNK - 1000] = 0x22 // 上一块尾部的一个真引号
const read = 200
buf.fill(0x79, 0, read) // 本次短读：200 个 'y'，没有引号
const unbounded = buf.indexOf(0x22, 0)
const bounded = (() => {
  const at = buf.indexOf(0x22, 0)
  return at === -1 || at >= read ? -1 : at
})()
check('mechanism: unbounded search matches a stale quote past `read`', unbounded === CHUNK - 1000, String(unbounded))
check('mechanism: bounded search reports no quote in the filled slice', bounded === -1, String(bounded))

if (failures > 0) {
  console.error(`\n❌ ${failures} check(s) failed`)
  process.exit(1)
}
console.log('\n✅ truncated-chunk scanning holds')
