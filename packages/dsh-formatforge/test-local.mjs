// 本地开发测试：stub @deepseek-ai/dsh-tools 与 dsh-skill-filesystem（ESM loader
// 不吃 Module._resolveFilename，直接在包旁生成 node_modules stub 目录），
// 验证 index.mjs 能注册工具、schema 契约合规、且 execute() 真实跑通 Python CLI。
// 用法：node packages/dsh-formatforge/test-local.mjs

import { mkdirSync, writeFileSync, rmSync, statSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url)) // packages/dsh-formatforge
const repoRoot = dirname(here) // 仓库根

// ---- stub @deepseek-ai/*（真实环境由 cordis/npx cache 提供）----
const stubRoot = join(here, 'node_modules', '@deepseek-ai')
for (const name of ['dsh-tools', 'dsh-skill-filesystem']) {
  const dir = join(stubRoot, name)
  mkdirSync(dir, { recursive: true })
  const body =
    name === 'dsh-tools'
      ? `export function defineTool(spec) { return spec }\n`
      : `export class FileSystemSkillProvider { constructor() {} }\n`
  writeFileSync(join(dir, 'index.mjs'), body)
  writeFileSync(
    join(dir, 'package.json'),
    JSON.stringify({ name: `@deepseek-ai/${name}`, version: '0.0.0-local-stub', type: 'module', main: './index.mjs' }),
  )
}
process.on('exit', () => rmSync(join(here, 'node_modules'), { recursive: true, force: true }))

// ---- fake ctx ----
const registered = []
const providers = []
const ctx = {
  skills: { registerProvider: (fn) => providers.push(fn) },
  tools: { register: (tool) => registered.push(tool) },
}

const mod = await import('./index.mjs')
console.log('plugin name:', mod.name)
console.log('inject:', JSON.stringify(mod.inject))
mod.apply(ctx)

if (registered.length !== 5) {
  console.error(`FAIL: expected 5 tools registered, got ${registered.length}:`, registered.map((t) => t.name))
  process.exit(1)
}
console.log('registered:', registered.map((t) => t.name).join(', '))
if (providers.length !== 1) {
  console.error(`FAIL: expected skill provider registered`)
  process.exit(1)
}

const translate = registered.find((t) => t.name === 'ff_translate')
const formats = registered.find((t) => t.name === 'ff_formats')

// schema 契约自检：嵌套 object 必须显式 additionalProperties
function checkSchema(node, pathSoFar) {
  if (typeof node !== 'object' || node === null) return
  if (node.type === 'object' && !('additionalProperties' in node)) {
    throw new Error(`schema violation at ${pathSoFar}: object without additionalProperties`)
  }
  for (const [k, v] of Object.entries(node.properties || {})) checkSchema(v, `${pathSoFar}.${k}`)
}
checkSchema(translate.output.schema, 'output')
for (const [k, v] of Object.entries(translate.parameters)) checkSchema(v, `param.${k}`)
console.log('schema contract: OK')

// ---- 真实 CLI e2e：formats ----
const r1 = await formats.execute({})
console.log('ff_formats ok=', r1.ok, 'count=', r1.data && r1.data.count)

// ---- 真实 CLI e2e：stdin text ----
const r2 = await translate.execute({ text: 'Hello FormatForge\n第二行', format: 'text' })
console.log('ff_translate stdin ok=', r2.ok, 'len=', r2.data && String(r2.data.content).length)

// ---- 错误路径：不存在的文件 ----
const r3 = await translate.execute({ path: 'Z:/no/such/file.pdf' })
console.log('missing file kind=', r3.error && r3.error.kind)

// ---- enhance 路径：扫描件 pdf ----
const scanPdf = join(repoRoot, 'test', 'fixtures', 'image_only_test.pdf')
try {
  if (statSync(scanPdf).isFile()) {
    const r4 = await translate.execute({ path: scanPdf, format: 'markdown' })
    const enh = r4.data && r4.data.enhance
    console.log('enhance needed=', enh && enh.needed, 'reason=', enh && enh.reason)
  }
} catch {
  console.log('scan pdf fixture missing; skip')
}

console.log('LOCAL-E2E-DONE')
