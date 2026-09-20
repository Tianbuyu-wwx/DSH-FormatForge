// packages/dsh-formatforge/test/test-result-enhance-large.mjs
//
// T3-1 回归（审计）：大产物分支里 `enhance: null` 是**硬编码**的，于是
// `ff_result list` 对任何 > 64KB 的产物都不显示 `⚠enhance=…` —— 偏偏最可能需要
// 增强的就是这些大文档。渲染层把 null 读作「不需要增强」而不是「不知道」，
// 所以这个缺省会主动误导会话模型。
//
// 流式扫描器已经要走过 enhance 所在的位置（它是 data 的最后一个键），把它按
// 收 meta 的同一套机制收下来即可，内存边界不变（两者不会同时在收）。
// 收不进上限时如实报 `unknown`，而不是退回 null。
//
// 断言：
//   - 大产物的 enhance.reason 进 list 行与渲染文本；
//   - 小产物（JSON.parse 快路径）与大产物给出**同一个** reason；
//   - 没有 enhance 块的大产物仍然是 null（不能凭空造一个提示）；
//   - enhance 超过收集上限 → `unknown`，不是 null；
//   - meta/result_id/valid 不受新机制影响。
//
// 用法：node packages/dsh-formatforge/test/test-result-enhance-large.mjs

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

const home = mkdtempSync(join(tmpdir(), 'ff-enhance-test-'))
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

const BIG_CONTENT = '# 扫描件\n\n' + '这一页是图片，没有文字层。\n'.repeat(4000) // > 64KB
const SMALL_CONTENT = '# 小文件\n\n一行正文。\n'
const ENHANCE = { needed: true, reason: 'low_text_ratio', hint: '这份 PDF 基本是扫描件，请按图像描述补齐。' }

/** 协议键序逐字复刻：content → format → meta → structured_data → quality → enhance */
function protocolArtifact({ content, meta, structuredData, quality, enhance }) {
  const data = { content, format: 'markdown', meta }
  if (structuredData) data.structured_data = structuredData
  if (quality) data.quality = quality
  if (enhance) data.enhance = enhance
  return { ok: true, code: 200, data }
}

// 1) 大产物 + enhance（enhance 排在 data 的最后，正是旧实现够不着的位置）
writeFileSync(
  join(inbox, 'scan.pdf.ff.json'),
  JSON.stringify(
    protocolArtifact({
      content: BIG_CONTENT,
      meta: { parser: 'pdf', file_size: 8_000_000, result_id: 'cvt_enh0000001', confidence: 0.31 },
      structuredData: { structured: false, pages: Array.from({ length: 40 }, (_, i) => ({ page: i, chars: 0 })) },
      quality: { score: 0.3, grade: 'D', actions: Array.from({ length: 20 }, (_, i) => `建议 ${i}`) },
      enhance: ENHANCE,
    }),
    null,
    2,
  ),
)

// 2) 小产物 + 同一个 enhance：两条路径必须给出同一个 reason
writeFileSync(
  join(inbox, 'memo.pdf.ff.json'),
  JSON.stringify(
    protocolArtifact({
      content: SMALL_CONTENT,
      meta: { parser: 'pdf', file_size: 900, result_id: 'cvt_enh0000002', confidence: 0.35 },
      enhance: ENHANCE,
    }),
  ),
)

// 3) 大产物、无 enhance → 必须仍然是 null（不能凭空造提示）
writeFileSync(
  join(inbox, 'clean.docx.ff.json'),
  JSON.stringify(
    protocolArtifact({
      content: BIG_CONTENT,
      meta: { parser: 'docx', file_size: 120_000, result_id: 'cvt_enh0000003', confidence: 0.95 },
      quality: { score: 0.95, grade: 'A' },
    }),
    null,
    2,
  ),
)

// 4) enhance 超过 64KB 收集上限 → unknown（「不知道」≠「不需要」）
writeFileSync(
  join(inbox, 'huge-hint.pdf.ff.json'),
  JSON.stringify(
    protocolArtifact({
      content: BIG_CONTENT,
      meta: { parser: 'pdf', file_size: 7_000_000, result_id: 'cvt_enh0000004', confidence: 0.22 },
      enhance: { needed: true, reason: 'low_text_ratio', hint: 'h'.repeat(80 * 1024) },
    }),
    null,
    2,
  ),
)

const { createResultTool } = await import('../tools/result.mjs')
const tool = createResultTool({ log: () => {} })

console.log('\n=== ff_result enhance on large artifacts (T3-1) ===\n')

for (const name of ['scan.pdf.ff.json', 'clean.docx.ff.json', 'huge-hint.pdf.ff.json']) {
  check(`fixture ${name} is a large artifact (> 64KB)`, statSync(join(inbox, name)).size > 64 * 1024, String(statSync(join(inbox, name)).size))
}
check('fixture memo.pdf.ff.json takes the small fast path (< 64KB)', statSync(join(inbox, 'memo.pdf.ff.json')).size <= 64 * 1024)

const listed = await tool.execute({ list: true })
const row = (f) => listed.data.items.find((it) => it.file === f)

check(
  'large artifact: enhance reason is reported',
  row('scan.pdf.ff.json')?.enhance === 'low_text_ratio',
  JSON.stringify(row('scan.pdf.ff.json')),
)
check(
  'large artifact: meta still resolves (capture machinery unaffected)',
  row('scan.pdf.ff.json')?.id === 'cvt_enh0000001' && row('scan.pdf.ff.json')?.valid === true && row('scan.pdf.ff.json')?.confidence === 0.31,
  JSON.stringify(row('scan.pdf.ff.json')),
)
check(
  'small and large paths agree on the same enhance reason',
  row('memo.pdf.ff.json')?.enhance === row('scan.pdf.ff.json')?.enhance,
  JSON.stringify({ small: row('memo.pdf.ff.json')?.enhance, large: row('scan.pdf.ff.json')?.enhance }),
)
check(
  'large artifact without an enhance block stays null',
  row('clean.docx.ff.json')?.enhance === null && row('clean.docx.ff.json')?.valid === true,
  JSON.stringify(row('clean.docx.ff.json')),
)
check(
  'oversized enhance is reported as unknown, not null',
  row('huge-hint.pdf.ff.json')?.enhance === 'unknown',
  JSON.stringify(row('huge-hint.pdf.ff.json')),
)
check(
  'oversized enhance does not break meta resolution',
  row('huge-hint.pdf.ff.json')?.id === 'cvt_enh0000004' && row('huge-hint.pdf.ff.json')?.valid === true,
  JSON.stringify(row('huge-hint.pdf.ff.json')),
)

const rendered = tool.output.render({}, listed)
const lineFor = (needle) => rendered[0].text.split('\n').find((l) => l.includes(needle))
check(
  'render: large artifact carries the ⚠enhance marker',
  String(lineFor('cvt_enh0000001')).includes('⚠enhance=low_text_ratio'),
  String(lineFor('cvt_enh0000001')),
)
check(
  'render: artifact without enhance carries no marker',
  !String(lineFor('cvt_enh0000003')).includes('enhance='),
  String(lineFor('cvt_enh0000003')),
)

// 取回路径（整段 JSON.parse）本来就带 enhance —— 两者必须一致
const fetched = await tool.execute({ id: 'cvt_enh0000001', max_chars: 100 })
check(
  'fetch returns the same enhance reason as list',
  fetched.data?.enhance?.reason === 'low_text_ratio',
  JSON.stringify(fetched.data?.enhance),
)

if (failures > 0) {
  console.error(`\n❌ ${failures} check(s) failed`)
  process.exit(1)
}
console.log('\n✅ enhance is reported for large artifacts')
