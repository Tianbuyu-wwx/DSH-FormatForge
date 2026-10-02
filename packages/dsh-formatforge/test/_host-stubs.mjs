// test/_host-stubs.mjs — 为不依赖 dsh 运行时的 Node 测试准备 peer 桩。
//
// 安全约束（沿用 test-local.mjs 的教训）：桩绝不能留在包里。宿主按 peer 名把
// @deepseek-ai/* 路由到运行时那一份，但路由命中前会先看本目录；一个残留的桩会让
// 插件拿到 `defineTool = spec => spec`（未编译的裸 spec），工具静默失效。
//
// 用法：
//   const stubs = ensureHostStubs()        // 必须在 import 插件模块之前
//   try { const mod = await import('./tools/result.mjs') ... } finally { stubs.cleanup() }

import { mkdirSync, writeFileSync, rmSync, existsSync, readFileSync, readdirSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = dirname(fileURLToPath(import.meta.url)) // packages/dsh-formatforge/test
const PKG_ROOT = dirname(HERE)
const STUB_MARKER = '0.0.0-local-stub'
const STUB_NAMES = ['dsh-tools', 'dsh-skill-filesystem']

function isOurStub(dir) {
  try {
    return JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8')).version === STUB_MARKER
  } catch {
    return false
  }
}

export function ensureHostStubs({ log = () => {} } = {}) {
  const stubRoot = join(PKG_ROOT, 'node_modules', '@deepseek-ai')
  const created = []
  for (const name of STUB_NAMES) {
    const dir = join(stubRoot, name)
    const manifestPath = join(dir, 'package.json')
    if (existsSync(manifestPath) && !isOurStub(dir)) {
      log(`[stub] real dependency present, left untouched: ${name}`)
      continue
    }
    if (existsSync(dir)) rmSync(dir, { recursive: true, force: true })
    mkdirSync(dir, { recursive: true })
    const body =
      name === 'dsh-tools'
        ? 'export function defineTool(spec) { return spec }\n'
        : 'export class FileSystemSkillProvider { constructor() {} }\n'
    writeFileSync(join(dir, 'index.mjs'), body)
    writeFileSync(
      manifestPath,
      JSON.stringify({ name: `@deepseek-ai/${name}`, version: STUB_MARKER, type: 'module', main: './index.mjs' }),
    )
    created.push(dir)
  }
  return {
    created,
    cleanup() {
      for (const dir of created) {
        try {
          rmSync(dir, { recursive: true, force: true })
        } catch {
          /* best effort */
        }
      }
      // 只在没有别的内容时收掉外层目录，绝不 rmSync 整个 node_modules。
      for (const outer of [stubRoot, join(PKG_ROOT, 'node_modules')]) {
        try {
          if (existsSync(outer) && readdirSync(outer).length === 0) rmSync(outer, { recursive: true, force: true })
        } catch {
          /* best effort */
        }
      }
    },
  }
}
