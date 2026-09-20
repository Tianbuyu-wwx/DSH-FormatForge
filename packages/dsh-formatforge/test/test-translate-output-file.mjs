// packages/dsh-formatforge/test/test-translate-output-file.mjs
//
// T2-2 回归（审计）：`ff_translate` 的多文件分支把**同一个** `--output-file`
// 原样 spread 进每一次 spawn（`cliArgs` 在 :89 一次建好，:135 每个目标复用）。
// 于是每份转换都覆盖上一份，磁盘上只剩最后一个文档，而返回给模型的 content 里
// 却是全部文档拼接 ——「另存 content」的承诺与落盘结果互相矛盾，中间产物无声丢失。
//
// 修法是**明确拒绝**（而不是自动派生多个输出路径）：多文件落盘归 `ff_batch(out=…)`，
// 它走 output guard 并复用 `batch.py::_plan_out_paths` 的消歧规则。
//
// 本测试真跑 Python CLI（与 test-python-runner-stdin.mjs 同约定），断言：
//   - 多目标 + output_file → bad_request，且**一个字节都没落盘**（拒绝发生在 spawn 之前）；
//   - 单目标 + output_file 照常工作，且磁盘内容 == 返回的 content（没修过头）；
//   - 多目标 + 不带 output_file 仍然正常拼接两份文档。
//
// 用法：node packages/dsh-formatforge/test/test-translate-output-file.mjs

import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync, existsSync } from 'node:fs'
import { tmpdir } from 'node:os'

const here = dirname(fileURLToPath(import.meta.url))
const pkgRoot = join(here, '..')
// 本 JS 包位于 <repo>/packages/dsh-formatforge → 仓库根（含 formatforge/ core/）在上三层
const repoRoot = join(here, '..', '..', '..')

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

const work = mkdtempSync(join(tmpdir(), 'ff-outputfile-test-'))
const srcDir = join(work, 'src')
const outDir = join(work, 'out')
mkdirSync(srcDir, { recursive: true })
mkdirSync(outDir, { recursive: true })
process.on('exit', () => {
  if (stubOwned) rmSync(join(pkgRoot, 'node_modules'), { recursive: true, force: true })
  rmSync(work, { recursive: true, force: true })
})

// T1-4 之后 --output-file 对 FF_OUTPUT_ROOT 是 fail-closed 的：显式声明测试输出根
process.env.FF_OUTPUT_ROOT = outDir

let failures = 0
function check(name, cond, detail = '') {
  if (cond) {
    console.log(`✅ ${name}`)
  } else {
    failures++
    console.error(`❌ ${name}  ${detail}`)
  }
}

const A_TEXT = '文档 A 的正文：第一份。'
const B_TEXT = '文档 B 的正文：第二份。'
const aPath = join(srcDir, 'doc-a.txt')
const bPath = join(srcDir, 'doc-b.txt')
writeFileSync(aPath, A_TEXT, 'utf8')
writeFileSync(bPath, B_TEXT, 'utf8')

const { createTranslateTool } = await import('../tools/translate.mjs')
const tool = createTranslateTool({
  repoRoot,
  maxBytes: 100 * 1024 * 1024,
  timeoutMs: 180_000,
  log: () => {},
})

console.log('\n=== ff_translate output_file × multi-target (T2-2) ===\n')

// 1) 多目标 + output_file —— 必须在任何 spawn 之前被拒
const combined = join(outDir, 'combined.md')
const multi = await tool.execute({
  paths: `${aPath},${bPath}`,
  format: 'markdown',
  output_file: combined,
})
const onDisk = existsSync(combined) ? readFileSync(combined, 'utf8') : null
check(
  'multi-target + output_file rejected as bad_request',
  multi.ok === false && multi.error?.kind === 'bad_request',
  JSON.stringify({ ok: multi.ok, error: multi.error, content: String(multi.data?.content ?? '').slice(0, 200) }),
)
check(
  'rejection names the supported multi-file route (ff_batch)',
  typeof multi.error?.message === 'string' && multi.error.message.includes('ff_batch'),
  String(multi.error?.message),
)
check(
  'nothing was written to the output root (no spawn happened)',
  onDisk === null && readdirSync(outDir).length === 0,
  JSON.stringify({ dir: readdirSync(outDir), onDisk: onDisk === null ? null : onDisk.slice(0, 200) }),
)
// 旧行为的证据：content 里两份都在、磁盘上只剩最后一份 → 两者不一致
if (multi.ok === true) {
  const content = String(multi.data?.content ?? '')
  check(
    'returned content and the file on disk agree',
    onDisk !== null && content.includes(A_TEXT) && onDisk.includes(A_TEXT),
    JSON.stringify({
      contentHasA: content.includes(A_TEXT),
      contentHasB: content.includes(B_TEXT),
      diskHasA: onDisk !== null && onDisk.includes(A_TEXT),
      diskHasB: onDisk !== null && onDisk.includes(B_TEXT),
    }),
  )
}

// 2) 单目标 + output_file 仍然工作，磁盘内容 == 返回的 content（防止修过头）
const single = join(outDir, 'single.md')
const one = await tool.execute({ path: aPath, format: 'markdown', output_file: single })
check('single target + output_file still succeeds', one.ok === true, JSON.stringify(one).slice(0, 300))
// Python 的 write_text 在 Windows 上会把 LF 翻成 CRLF（平台换行），比对前归一
const lf = (v) => String(v).replace(/\r\n/g, '\n')
const singleDisk = existsSync(single) ? readFileSync(single, 'utf8') : null
check(
  'single target: disk content == returned content',
  singleDisk !== null && typeof one.data?.content === 'string' && lf(singleDisk) === lf(one.data.content),
  JSON.stringify({ disk: String(singleDisk).slice(0, 120), returned: String(one.data?.content).slice(0, 120) }),
)
check('single target: source text survived the round trip', String(singleDisk).includes(A_TEXT), String(singleDisk).slice(0, 200))

// 3) 多目标（不带 output_file）不受影响
const multiPlain = await tool.execute({ paths: `${aPath},${bPath}`, format: 'markdown' })
const plainContent = String(multiPlain.data?.content ?? '')
check('multi-target without output_file still succeeds', multiPlain.ok === true, JSON.stringify(multiPlain).slice(0, 300))
check(
  'multi-target without output_file keeps BOTH documents',
  plainContent.includes(A_TEXT) && plainContent.includes(B_TEXT),
  plainContent.slice(0, 300),
)

if (failures > 0) {
  console.error(`\n❌ ${failures} check(s) failed`)
  process.exit(1)
}
console.log('\n✅ ff_translate output_file / multi-target contract holds')
