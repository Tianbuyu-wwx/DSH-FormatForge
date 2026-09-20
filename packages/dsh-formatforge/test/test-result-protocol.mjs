// packages/dsh-formatforge/test/test-result-protocol.mjs
//
// v1.0.3/JS-H1 回归：产物文件是 Python round-1 协议信封的**逐字拷贝**
//   {"ok": true, "code": 200, "data": {"content", "format",
//     "meta": {"parser", "file_size", "result_id", "confidence"}, "enhance"?}}
// ff_result 必须按这套真实键取回：非空 content + 正确 parser/confidence。
// （历史 bug：读 `data.convertedContent` → 永远返回空正文，且 `meta.fileId` 之类的键根本不存在。）
//
// 用法：node packages/dsh-formatforge/test/test-result-protocol.mjs

import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { writeFileSync, mkdtempSync, rmSync, mkdirSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'

const here = dirname(fileURLToPath(import.meta.url))

// 把 ESM stub 装一下（测试工具不依赖 dsh 运行时）。
// M19 教训：只在包根 node_modules 不存在时才建 stub，且只清理自己建的目录，
// 绝不覆盖/删除真实的 @deepseek-ai/dsh-tools 安装。
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

// 隔离收件箱：FF_HOME 指向临时目录（inboxDir() 每次调用读 env）
const home = mkdtempSync(join(tmpdir(), 'ff-result-test-'))
const inbox = join(home, 'inbox')
mkdirSync(inbox, { recursive: true })
process.env.FF_HOME = home
process.on('exit', () => {
  if (stubOwned) rmSync(join(pkgRoot, 'node_modules'), { recursive: true, force: true })
  rmSync(home, { recursive: true, force: true })
})

// --- 合成产物：真实协议形状（Python 成功信封逐字写入，见 __main__.py:156-191） ---
const CONTENT = '# 转换结果\n\n这是一段正文内容，用来验证 ff_result 真的取回了 content。\n'
const artifact = {
  ok: true,
  code: 200,
  data: {
    content: CONTENT,
    format: 'markdown',
    meta: { parser: 'pdf', file_size: 1234, result_id: 'cvt_abc12345', confidence: 0.97 },
    enhance: { needed: false },
  },
}
// JS-H4 新命名：产物名带源扩展名
writeFileSync(join(inbox, 'report.pdf.ff.json'), JSON.stringify(artifact, null, 2))
writeFileSync(join(inbox, 'report.pdf.ff.md'), CONTENT)
// 旧式 stem 命名仍须可读（向后兼容）
writeFileSync(join(inbox, 'legacy.ff.json'), JSON.stringify({ ...artifact, data: { ...artifact.data, meta: { ...artifact.data.meta, result_id: 'cvt_legacy01' } } }, null, 2))

const { createResultTool } = await import('../tools/result.mjs')
const tool = createResultTool({ log: () => {} })

let failures = 0
function check(name, cond, detail = '') {
  if (cond) {
    console.log(`✅ ${name}`)
  } else {
    failures++
    console.error(`❌ ${name}  ${detail}`)
  }
}

console.log('\n=== ff_result protocol-key regression (JS-H1) ===\n')

// 1) 按 result_id 精确取回
const byId = await tool.execute({ id: 'cvt_abc12345' })
check('fetch by result_id → ok', byId.ok === true, JSON.stringify(byId))
check('content non-empty (data.content)', typeof byId.data?.content === 'string' && byId.data.content.includes('正文内容'), JSON.stringify(byId.data?.content))
check('parser ← meta.parser', byId.data?.parser === 'pdf', String(byId.data?.parser))
check('confidence ← meta.confidence', byId.data?.confidence === 0.97, String(byId.data?.confidence))
check('file_size ← meta.file_size', byId.data?.file_size === 1234, String(byId.data?.file_size))
check('id ← meta.result_id', byId.data?.id === 'cvt_abc12345', String(byId.data?.id))
check('source ← 产物文件名 stem', byId.data?.source === 'report.pdf', String(byId.data?.source))
check('md_path 指向同名 .ff.md', String(byId.data?.md_path).endsWith('report.pdf.ff.md'), String(byId.data?.md_path))

// 2) result_id 前 8 位前缀
const byPrefix = await tool.execute({ id: 'cvt_abc1' })
check('fetch by result_id prefix (≥8)', byPrefix.ok === true && byPrefix.data?.id === 'cvt_abc12345', JSON.stringify(byPrefix))

// 3) 源 stem（新命名下不带扩展名）与精确文件名 stem
const byStem = await tool.execute({ id: 'report' })
check('fetch by source stem (report → report.pdf.ff.json)', byStem.ok === true && byStem.data?.content?.includes('正文内容'), JSON.stringify(byStem))
const byFullStem = await tool.execute({ id: 'report.pdf' })
check('fetch by full artifact stem', byFullStem.ok === true && byFullStem.data?.id === 'cvt_abc12345', JSON.stringify(byFullStem))

// 4) 旧式 stem 命名仍可读
const legacy = await tool.execute({ id: 'legacy' })
check('legacy stem-named artifact still readable', legacy.ok === true && legacy.data?.content?.includes('正文内容'), JSON.stringify(legacy))

// 5) list 模式：行字段来自真实键
const listed = await tool.execute({ list: true })
const row = listed.data?.items?.find((it) => it.file === 'report.pdf.ff.json')
check('list finds both artifacts', listed.data?.count === 2, JSON.stringify(listed.data?.count))
check('list row parser ← meta.parser', row?.parser === 'pdf', String(row?.parser))
check('list row confidence ← meta.confidence', row?.confidence === 0.97, String(row?.confidence))
check('list row id ← meta.result_id', row?.id === 'cvt_abc12345', String(row?.id))

// 6) render 必须内嵌正文（模型看到的就是这个）
const rendered = tool.output.render({}, byId)
check('render embeds content', rendered[0].text.includes('正文内容'), rendered[0].text.slice(0, 120))

// 7) 分页参数：< 200 的 max_chars 不得被静默抬到 200；非整数向下取整
const paged = await tool.execute({ id: 'report.pdf', max_chars: 5 })
check('max_chars=5 honored (not floored to 200)', paged.data?.content?.length === 5, JSON.stringify({ len: paged.data?.content?.length, next: paged.data?.next_offset }))
check('max_chars=5 paginates', paged.data?.truncated === true && paged.data?.next_offset === 5, JSON.stringify(paged.data))
const paged2 = await tool.execute({ id: 'report.pdf', max_chars: 12.7, offset: 0.9 })
const paged2Zero = await tool.execute({ id: 'report.pdf', max_chars: 12.7 })
check(
  'non-integer max_chars floored (≤12, not 200)',
  paged2.data?.content?.length <= 12 && paged2.data?.truncated === true,
  JSON.stringify(paged2.data),
)
check(
  'non-integer offset floored to 0',
  paged2.data?.next_offset === paged2Zero.data?.next_offset && paged2.data?.content === paged2Zero.data?.content,
  JSON.stringify({ a: paged2.data?.next_offset, b: paged2Zero.data?.next_offset }),
)

// 8) 未知 id → file_not_found（不误匹配）
const missing = await tool.execute({ id: 'nope' })
check('unknown id → file_not_found', missing.ok === false && missing.error?.kind === 'file_not_found', JSON.stringify(missing))

// 9) 路径穿越仍被拒
const traversal = await tool.execute({ id: '../secret' })
check('path traversal rejected', traversal.ok === false && traversal.error?.kind === 'bad_request', JSON.stringify(traversal))

// 10) JS-H1b 信任边界：伪造/残缺的 .ff.json 绝不能被当作转换结果端出去
writeFileSync(join(inbox, 'forged.ff.json'), JSON.stringify({ hello: 'world', content: 'attacker payload' }))
const forged = await tool.execute({ id: 'forged' })
check('fabricated artifact → not_a_conversion_result', forged.ok === false && forged.error?.kind === 'not_a_conversion_result', JSON.stringify(forged))
writeFileSync(
  join(inbox, 'noid.ff.json'),
  JSON.stringify({ ok: true, code: 200, data: { content: 'x', format: 'markdown', meta: { parser: 'pdf' } } }),
)
const noId = await tool.execute({ id: 'noid' })
check('envelope without meta.result_id → rejected', noId.ok === false && noId.error?.kind === 'not_a_conversion_result', JSON.stringify(noId))
const listedFlagged = await tool.execute({ list: true })
check(
  'list flags non-conversion artifacts (valid:false)',
  listedFlagged.data.items.filter((it) => it.valid === false).length === 2,
  JSON.stringify(listedFlagged.data.items.map((it) => [it.file, it.valid])),
)
const flaggedRender = tool.output.render({}, listedFlagged)
check('list render warns on invalid rows', flaggedRender[0].text.includes('非转换产物'), flaggedRender[0].text.slice(0, 200))

// 11) 大产物（> 64KB）：list 不得整段读正文，但仍要从尾部 meta 取到 parser/confidence
const bigContent = 'x'.repeat(80 * 1024)
writeFileSync(
  join(inbox, 'big.docx.ff.json'),
  JSON.stringify(
    { ok: true, code: 200, data: { content: bigContent, format: 'markdown', meta: { parser: 'docx', file_size: 99999, result_id: 'cvt_big00001', confidence: 0.88 } } },
    null,
    2,
  ),
)
const bigRow = (await tool.execute({ list: true })).data.items.find((it) => it.file === 'big.docx.ff.json')
check(
  'large artifact: list meta read from tail',
  bigRow?.parser === 'docx' && bigRow?.confidence === 0.88 && bigRow?.id === 'cvt_big00001' && bigRow?.valid === true,
  JSON.stringify(bigRow),
)
const bigFetch = await tool.execute({ id: 'cvt_big00001', max_chars: 200_000 })
check('large artifact fetch returns full content', bigFetch.ok === true && bigFetch.data?.content?.length === bigContent.length, JSON.stringify({ ok: bigFetch.ok, len: bigFetch.data?.content?.length }))
const bigPaged = await tool.execute({ id: 'cvt_big00001' })
check('large artifact default paging (12k page)', bigPaged.data?.content?.length === 12_000 && bigPaged.data?.next_offset === 12_000, JSON.stringify({ len: bigPaged.data?.content?.length, next: bigPaged.data?.next_offset }))

if (failures > 0) {
  console.error(`\n❌ ${failures} check(s) failed`)
  process.exit(1)
}
console.log('\n✅ all ff_result protocol checks passed')