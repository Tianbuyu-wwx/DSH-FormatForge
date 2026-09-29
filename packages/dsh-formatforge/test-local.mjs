// 本地开发测试：stub @deepseek-ai/dsh-tools 与 dsh-skill-filesystem
// （ESM loader 不吃 Module._resolveFilename，直接在包旁生成 node_modules stub 目录），
// 验证 index.mjs 能注册工具、schema 契约合规、且 execute() 真实跑通 Python CLI。
//
// 真实环境由宿主提供这两个 peer（DSH ≥0.2.0 的 launcher 为 linked profile 包做
// peer-aware 解析），所以本脚本只在缺依赖时补 stub，退出时只删自己建的 stub。
//
// 用法：node packages/dsh-formatforge/test-local.mjs

import { mkdirSync, writeFileSync, rmSync, statSync, readFileSync, existsSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url)) // packages/dsh-formatforge
const repoRoot = dirname(here) // 仓库根

// ---- stub @deepseek-ai/*（仅在缺失时创建；退出时只清理 stub 目录）----
//
// 安全约束：stub 绝不能留在包里。宿主按 peer 名把 @deepseek-ai/* 路由到运行时
// 那一份，但那份路由在 peer 位置命中前会先看本目录；一个残留的 stub 会让插件
// 拿到 `defineTool = spec => spec`（未编译的裸 spec），工具静默失效。
const STUB_MARKER = '0.0.0-local-stub'
const STUB_NAMES = ['dsh-tools', 'dsh-skill-filesystem']
const stubRoot = join(here, 'node_modules', '@deepseek-ai')
const created = []

function isOurStub(dir) {
  try {
    return JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8')).version === STUB_MARKER
  } catch {
    return false
  }
}

for (const name of STUB_NAMES) {
  const dir = join(stubRoot, name)
  const manifestPath = join(dir, 'package.json')
  if (existsSync(manifestPath) && !isOurStub(dir)) {
    // 真实依赖（宿主 peer 副本）——不动它，也不删它。
    console.log(`[stub] real dependency present, left untouched: ${name}`)
    continue
  }
  // 上次崩溃可能留下自己的 stub：重建并登记，保证退出时一定清干净。
  if (existsSync(dir)) rmSync(dir, { recursive: true, force: true })
  mkdirSync(dir, { recursive: true })
  const body =
    name === 'dsh-tools'
      ? `export function defineTool(spec) { return spec }\n`
      : `export class FileSystemSkillProvider { constructor() {} }\n`
  writeFileSync(join(dir, 'index.mjs'), body)
  writeFileSync(
    manifestPath,
    JSON.stringify({
      name: `@deepseek-ai/${name}`,
      version: STUB_MARKER,
      type: 'module',
      main: './index.mjs',
    }),
  )
  created.push(dir)
}
function cleanupStubs() {
  for (const dir of created) {
    try {
      rmSync(dir, { recursive: true, force: true })
    } catch { /* best effort */ }
  }
  // 只在没有别的内容时收掉外层目录，绝不 rmSync 整个 node_modules。
  for (const outer of [stubRoot, join(here, 'node_modules')]) {
    try {
      if (existsSync(outer) && readdirSync(outer).length === 0) rmSync(outer, { recursive: true, force: true })
    } catch { /* best effort */ }
  }
}
process.on('exit', cleanupStubs)
process.on('SIGINT', () => {
  cleanupStubs()
  process.exit(130)
})

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
// 显式退出：index.mjs 的 inbox watcher 是 unref'd 的，但 python 探测/子进程
// 仍可能留下句柄；测试脚本不该依赖事件循环自然排空。
process.exit(0)
