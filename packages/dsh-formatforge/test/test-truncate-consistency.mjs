// packages/dsh-formatforge/test/test-truncate-consistency.mjs
//
// v0.13.0: 跨语言一致性测试——JS smartTruncate 与 Python core/utils.py::smart_truncate
// 在同一组字符串/参数上的输出必须 byte-equal（chunk 内容 + next_offset 数值）。
//
// 防止后续任一侧改算法导致 Python ↔ Node 漂移（这正是 R3.3 抓出的链路断点模式）。
//
// 用法：node packages/dsh-formatforge/test/test-truncate-consistency.mjs

import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { spawnSync } from 'node:child_process'
import { writeFileSync, mkdtempSync, rmSync, mkdirSync } from 'node:fs'

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = join(here, '..', '..')

// 把 ESM stub 装一下（与 test-local.mjs 一致：这是测试工具，不依赖 dsh 运行时）
const stubRoot = join(here, 'node_modules', '@deepseek-ai')
for (const name of ['dsh-tools', 'dsh-skill-filesystem']) {
  const dir = join(stubRoot, name)
  mkdirSync(dir, { recursive: true })
  const body = name === 'dsh-tools'
    ? `export function defineTool(spec) { return spec }\n`
    : `export class FileSystemSkillProvider { constructor() {} }\n`
  writeFileSync(join(dir, 'index.mjs'), body)
  writeFileSync(
    join(dir, 'package.json'),
    JSON.stringify({ name: `@deepseek-ai/${name}`, version: '0.0.0', type: 'module', main: './index.mjs' }),
  )
}
process.on('exit', () => rmSync(join(here, 'node_modules'), { recursive: true, force: true }))

const { smartTruncate } = await import('../tools/_truncate.mjs')

// --- 测例矩阵（与 test_smart_truncate.py 同源） ---
const cases = [
  { name: 'short text', input: 'short', max: 100, start: 0 },
  { name: 'beyond end', input: 'abc', max: 10, start: 99 },
  { name: 'paragraph boundary', input: 'para1 line\npara1 line2\n\n## Table\n| a | b |\n| c | d |\n\ntail content', max: 40, start: 0 },
  { name: 'line boundary fallback', input: 'aaaa\nbbbb\ncccc\ndddd', max: 10, start: 0 },
  { name: 'overlong single line (hard cut)', input: 'x'.repeat(200), max: 50, start: 0 },
  { name: 'paged roundtrip last page', input: 'para1\n\npara2\n\npara3', max: 8, start: 6 },
  { name: 'empty input', input: '', max: 100, start: 0 },
  { name: 'zero max (edge)', input: 'hello world', max: 0, start: 0 },
  { name: 'exact boundary', input: 'aaa\nbbb', max: 3, start: 0 },
  // v0.14.0/B-P1-7: --- 多文件分隔符保护
  {
    name: 'multi-file separator (---) wins over paragraph',
    input: '## 文件: a.md\n\n短内容\n\n---\n\n## 文件: b.md\n\n更长的内容段落 1\n更长的内容段落 2',
    max: 50,
    start: 0,
  },
  // v0.14.0/audit: HTML 注释代替 --- 多文件分隔符
  {
    name: 'multi-file separator (<!-- ff-file-sep -->) wins',
    input: '## 文件: a.md\n\n短内容\n\n<!-- ff-file-sep -->\n\n## 文件: b.md\n\n更长的内容段落',
    max: 50,
    start: 0,
  },
  // v0.14.0/audit: markdown 水平线 --- 第 1 页 --- 不应被误识别
  {
    name: 'markdown hr (--- 第 1 页 ---) is NOT a file separator',
    input: '## 文件: a.md\n\n# 转换结果\n\n--- 第 1 页 ---\n\n文件 A 内容',
    max: 30,
    start: 0,
  },
  {
    name: 'no separator falls back to paragraph',
    input: '## 文件: a.md\n\n短内容',
    max: 30,
    start: 0,
  },
]

// --- 调 Python smart_truncate 取真值 ---
// 用 spawn 跑一次性 Python 脚本（避免在 Node 端重复实现 Python 端逻辑）
const pyScript = `
import json, sys
sys.path.insert(0, ${JSON.stringify(repoRoot)})
from core.utils import smart_truncate
cases = json.loads(sys.stdin.read())
out = []
for c in cases:
    chunk, nxt = smart_truncate(c['input'], c['max'], c.get('start', 0))
    out.append({'name': c['name'], 'chunk': chunk, 'next_offset': nxt})
print(json.dumps(out, ensure_ascii=False))
`

const python = process.env.FF_PYTHON || 'python'
const proc = spawnSync(python, ['-c', pyScript], {
  input: JSON.stringify(cases),
  encoding: 'utf-8',
  cwd: repoRoot,
  env: { ...process.env, PYTHONPATH: repoRoot, PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' },
})
if (proc.status !== 0) {
  console.error('PYTHON FAIL:', proc.stderr.slice(-500))
  process.exit(1)
}

const pyResults = JSON.parse(proc.stdout)

// --- 对比 ---
let failures = 0
console.log(`\n=== Cross-language truncate consistency (${cases.length} cases) ===\n`)
for (let i = 0; i < cases.length; i++) {
  const py = pyResults[i]
  const js = smartTruncate(cases[i].input, cases[i].max, cases[i].start || 0)
  // 序列化对齐：Python None / JS undefined 都是 "no next page"
  const jsNext = js.nextOffset === undefined ? null : js.nextOffset
  const pass = py.chunk === js.chunk && py.next_offset === jsNext
  if (!pass) {
    failures++
    console.log(`❌ [${py.name}]`)
    console.log(`   Python: ${JSON.stringify({ chunk: py.chunk, next_offset: py.next_offset })}`)
    console.log(`   JS:     ${JSON.stringify({ chunk: js.chunk, next_offset: jsNext })}`)
  } else {
    console.log(`✅ [${py.name}]  next_offset=${py.next_offset}`)
  }
}

if (failures > 0) {
  console.error(`\n❌ ${failures}/${cases.length} cases differ between JS and Python`)
  process.exit(1)
}
console.log(`\n✅ all ${cases.length} cases consistent between JS and Python`)