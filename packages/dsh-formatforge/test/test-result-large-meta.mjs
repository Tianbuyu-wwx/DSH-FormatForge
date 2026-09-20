// packages/dsh-formatforge/test/test-result-large-meta.mjs
//
// 独立评审 #1 回归：大产物（> 64KB）的 meta 定位不能靠「尾部 4KB」猜。
// 协议的键序是 content → format → meta → structured_data → quality → enhance
// （`formatforge/__main__.py:186-220`），meta **排在第三**：
//   - content 可以任意大 → meta 离文件尾很远；
//   - structured_data / quality（inbox watcher 恒传 --quality）单项就能超过 4KB。
// 于是尾窗里根本没有 "result_id"：
//   - list 把**真产物**标成 `⚠非转换产物（伪造/损坏，取回会被拒）`（result.mjs:159）；
//   - notify 播出去的 result_id 在 fetch 的兜底扫描里被 `rid == null` 跳过 → 4002。
// 本测试合成一份键序与协议一致的产物，断言 list 报出**真实 result_id** + valid=true，
// 且按该 result_id 取回成功；同时守住「真损坏仍然 valid=false」与小产物快路径。
//
// 用法：node packages/dsh-formatforge/test/test-result-large-meta.mjs

import { fileURLToPath, pathToFileURL } from 'node:url'
import { dirname, join } from 'node:path'
import { writeFileSync, mkdtempSync, rmSync, mkdirSync, existsSync, statSync, openSync, writeSync, closeSync } from 'node:fs'
import { spawnSync } from 'node:child_process'
import { tmpdir } from 'node:os'

const here = dirname(fileURLToPath(import.meta.url))

// ESM stub（同 test-result-protocol.mjs：只在包根 node_modules 不存在时才建，且只删自己建的）
const pkgRoot = join(here, '..')
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

const home = mkdtempSync(join(tmpdir(), 'ff-largemeta-test-'))
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

/** 造一份 post-meta 载荷 > 4KB 的 structured_data（真实 xlsx 的 schema/preview 就是这形状） */
function bigStructuredData(rows) {
  return {
    structured: true,
    conversion_decision: 'markdown_table',
    schema: Array.from({ length: 24 }, (_, i) => ({ name: `column_${i}`, type: 'string', nullable: true })),
    preview_rows: Array.from({ length: rows }, (_, i) => ({
      row: i,
      cells: [`单元格内容 ${i}`, 'x'.repeat(64), `备注-${i}`],
    })),
  }
}

/** 协议键序逐字复刻：content → format → meta → structured_data → quality → enhance */
function protocolArtifact({ content, meta, structuredData, quality, enhance }) {
  const data = { content, format: 'markdown', meta }
  if (structuredData) data.structured_data = structuredData
  if (quality) data.quality = quality
  if (enhance) data.enhance = enhance
  return { ok: true, code: 200, data }
}

const BIG_CONTENT = '# 大表格\n\n' + '| 甲 | 乙 |\n| --- | --- |\n'.repeat(4000) // > 64KB
const BIG_META = { parser: 'xlsx', file_size: 987654, result_id: 'cvt_big1234567', confidence: 0.83 }
const bigArtifact = protocolArtifact({
  content: BIG_CONTENT,
  meta: BIG_META,
  structuredData: bigStructuredData(80),
  quality: {
    score: 0.91,
    grade: 'A',
    evidence: Array.from({ length: 60 }, (_, i) => `证据行 ${i}: ${'y'.repeat(60)}`),
    actions: Array.from({ length: 20 }, (_, i) => `建议 ${i}`),
  },
})
const bigPath = join(inbox, 'sheet.xlsx.ff.json')
writeFileSync(bigPath, JSON.stringify(bigArtifact, null, 2))
writeFileSync(join(inbox, 'sheet.xlsx.ff.md'), BIG_CONTENT)

// 小产物（< 64KB）快路径必须不受影响
const SMALL_CONTENT = '# 小产物\n\n正文。\n'
writeFileSync(
  join(inbox, 'memo.txt.ff.json'),
  JSON.stringify(
    protocolArtifact({
      content: SMALL_CONTENT,
      meta: { parser: 'txt', file_size: 42, result_id: 'cvt_small00001', confidence: 0.99 },
    }),
    null,
    2,
  ),
)

// 真·损坏的大产物：ok:true 但整份信封里没有 meta.result_id → 必须仍然 valid=false
writeFileSync(
  join(inbox, 'forged-big.ff.json'),
  JSON.stringify({ ok: true, code: 200, data: { content: BIG_CONTENT, format: 'markdown', meta: { parser: 'pdf' } } }, null, 2),
)
// ok:false 的大信封同样不是合法产物
writeFileSync(
  join(inbox, 'failed-big.ff.json'),
  JSON.stringify(
    { ok: false, code: 4004, error: { kind: 'parse_failed', message: 'x' }, data: { content: BIG_CONTENT, meta: { result_id: 'cvt_notok00001' } } },
    null,
    2,
  ),
)

const { createResultTool } = await import('../tools/result.mjs')
const tool = createResultTool({ log: () => {} })

console.log('\n=== ff_result large-artifact meta resolution (review #1) ===\n')

const sizeKB = Math.round(statSync(bigPath).size / 1024)
check('fixture really is a large artifact (> 64KB)', statSync(bigPath).size > 64 * 1024, `${sizeKB}KB`)
// meta 与文件尾之间的字节数必须 > 4096，否则复现不到旧尾窗 bug
const raw = JSON.stringify(bigArtifact, null, 2)
const bytesAfterMeta = Buffer.byteLength(raw.slice(raw.indexOf('"result_id"')), 'utf8')
check('fixture puts meta more than 4KB from EOF (the bug window)', bytesAfterMeta > 4096, `${bytesAfterMeta}B after result_id`)

const listed = await tool.execute({ list: true })
const bigRow = listed.data.items.find((it) => it.file === 'sheet.xlsx.ff.json')
check('large artifact: id ← real meta.result_id (not the stem)', bigRow?.id === 'cvt_big1234567', JSON.stringify(bigRow))
check('large artifact: not flagged as forged/corrupt', bigRow?.valid === true, JSON.stringify(bigRow))
check('large artifact: parser ← meta.parser', bigRow?.parser === 'xlsx', String(bigRow?.parser))
check('large artifact: confidence ← meta.confidence', bigRow?.confidence === 0.83, String(bigRow?.confidence))
check('large artifact: file_size ← meta.file_size', bigRow?.file_size === 987654, String(bigRow?.file_size))

// 按 notify 播出去的 result_id 取回：旧代码在兜底扫描里因 rid=null 而 4002
const fetched = await tool.execute({ id: 'cvt_big1234567', max_chars: 200 })
check(
  'fetch by advertised result_id succeeds (was 4002 file_not_found)',
  fetched.ok === true && fetched.data?.id === 'cvt_big1234567',
  JSON.stringify({ ok: fetched.ok, code: fetched.code, err: fetched.error }),
)
check('fetched content is the real body', typeof fetched.data?.content === 'string' && fetched.data.content.startsWith('# 大表格'), String(fetched.data?.content).slice(0, 40))

// 小产物快路径不回归
const smallRow = listed.data.items.find((it) => it.file === 'memo.txt.ff.json')
check('small artifact still resolves normally', smallRow?.id === 'cvt_small00001' && smallRow?.valid === true, JSON.stringify(smallRow))

// 校验没有被 fix 蒙蔽：真损坏仍然 valid=false
const forgedRow = listed.data.items.find((it) => it.file === 'forged-big.ff.json')
check('large artifact without meta.result_id still valid=false', forgedRow?.valid === false, JSON.stringify(forgedRow))
const notOkRow = listed.data.items.find((it) => it.file === 'failed-big.ff.json')
check('large envelope with ok:false still valid=false', notOkRow?.valid === false, JSON.stringify(notOkRow))
const forgedFetch = await tool.execute({ id: 'forged-big' })
check(
  'forged large artifact fetch still rejected',
  forgedFetch.ok === false && forgedFetch.error?.kind === 'not_a_conversion_result',
  JSON.stringify(forgedFetch),
)

// list 渲染：真产物不得带警告文案
const rendered = tool.output.render({}, listed)
const bigLine = rendered[0].text.split('\n').find((l) => l.includes('sheet.xlsx'))
check('render: genuine large artifact carries no ⚠ warning', !!bigLine && !bigLine.includes('非转换产物'), String(bigLine))

// ---- T2-5 回归：顶层 `"ok"` 字面量必须有上限 ----
//
// 扫描器自述「内存边界与产物大小无关」，但 `okLiteral += String.fromCharCode(c)`
// 是**唯一**没有上限的缓冲区（KEY_TOKEN_BYTES / META_CAPTURE_BYTES 管住了其余）：
// 一份 `{"ok":` + 一大片没有 `,`/`}`/`]` 终止的字面量，会被逐字节累积进活着的
// harness 进程。真产物只会写 `true`/`false`，所以这是损坏/构造专属路径 —— 但
// M11 信任边界下同机进程能往收件箱放文件，因此可达。
//
// 实测放大倍率约 32×（8MB 字面量 → 256MB 堆），所以在**受限堆的子进程**里跑：
// 修复前是确定性的 OOM（exit 134），修复后毫秒级返回且堆增长 ~0。
const bombHome = mkdtempSync(join(tmpdir(), 'ff-okbomb-test-'))
const bombInbox = join(bombHome, 'inbox')
mkdirSync(bombInbox, { recursive: true })
process.on('exit', () => rmSync(bombHome, { recursive: true, force: true }))

const BOMB_MB = 8
{
  const fd = openSync(join(bombInbox, 'bomb.ff.json'), 'w')
  writeSync(fd, Buffer.from('{"ok":', 'utf8'))
  // 'A' —— 非空白（c > 0x20）、非结构字符：旧代码对每个字节都做一次 okLiteral += …
  const filler = Buffer.alloc(1024 * 1024, 0x41)
  for (let i = 0; i < BOMB_MB; i++) writeSync(fd, filler)
  closeSync(fd)
}
const childPath = join(bombHome, 'scan-child.mjs')
const resultUrl = pathToFileURL(join(here, '..', 'tools', 'result.mjs')).href
writeFileSync(
  childPath,
  [
    `const { createResultTool } = await import(${JSON.stringify(resultUrl)})`,
    'const before = process.memoryUsage().heapUsed',
    'const listed = await createResultTool({ log: () => {} }).execute({ list: true })',
    'const grewMB = Math.round((process.memoryUsage().heapUsed - before) / 1048576)',
    'const rows = listed.data.items.map((r) => ({ file: r.file, valid: r.valid }))',
    'console.log(JSON.stringify({ rows, grewMB }))',
    '',
  ].join('\n'),
)
const bombRun = spawnSync(process.execPath, ['--max-old-space-size=96', childPath], {
  encoding: 'utf8',
  env: { ...process.env, FF_HOME: bombHome },
})
check(
  `pathological "ok" literal (${BOMB_MB}MB) survives a 96MB heap cap`,
  bombRun.status === 0,
  `status=${bombRun.status} signal=${bombRun.signal} stderr=${String(bombRun.stderr).split('\n').slice(0, 4).join(' | ')}`,
)
let bombOut = null
try {
  bombOut = JSON.parse(String(bombRun.stdout).trim().split('\n').pop())
} catch { /* 子进程没活到打印 */ }
check('pathological "ok" literal: heap growth stays bounded', !!bombOut && bombOut.grewMB <= 16, JSON.stringify(bombOut))
check(
  'pathological "ok" literal: never reported as a valid artifact',
  !!bombOut && !bombOut.rows.some((r) => r.file === 'bomb.ff.json' && r.valid === true),
  JSON.stringify(bombOut),
)

// 大小两条路径的判定要一致：同样形状的小产物走 JSON.parse 快路径，读不动 → 不进 list
writeFileSync(join(inbox, 'small-bomb.ff.json'), `{"ok":${'A'.repeat(1024)}`)
const listedAfterBomb = await tool.execute({ list: true })
check(
  'malformed small artifact is dropped from the listing (fast path)',
  !listedAfterBomb.data.items.some((it) => it.file === 'small-bomb.ff.json'),
  JSON.stringify(listedAfterBomb.data.items.map((i) => i.file)),
)
check(
  'the genuine large artifact is still listed alongside it',
  listedAfterBomb.data.items.some((it) => it.file === 'sheet.xlsx.ff.json' && it.valid === true),
  JSON.stringify(listedAfterBomb.data.items.map((i) => i.file)),
)

if (failures > 0) {
  console.error(`\n❌ ${failures} check(s) failed`)
  process.exit(1)
}
console.log('\n✅ all large-artifact meta checks passed')
