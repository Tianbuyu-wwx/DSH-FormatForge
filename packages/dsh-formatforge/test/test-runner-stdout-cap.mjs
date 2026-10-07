// packages/dsh-formatforge/test/test-runner-stdout-cap.mjs
//
// v1.0.3 审计 medium 回归：`python-runner.mjs` 的 stdout 此前**无上限**累积
// （stderr 有 64KB 上限，它没有）——异常输出会把活着的 harness 进程 OOM 掉。
// 上限通过 `FF_MAX_STDOUT_BYTES` 可收紧，因此这里用一个极小上限真实触发一次。
//
// 用法：node packages/dsh-formatforge/test/test-runner-stdout-cap.mjs

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

const { runFormatForge, DEFAULT_MAX_STDOUT_BYTES, V8_MAX_STRING_LENGTH } = await import('../services/python-runner.mjs')
const repoRoot = join(import.meta.dirname, '..', '..', '..')

const dir = mkdtempSync(join(tmpdir(), 'ff-stdout-cap-'))
const src = join(dir, 'cap.txt')
writeFileSync(src, '正文内容 '.repeat(200), 'utf-8') // 信封 > 1000 字节
process.on('exit', () => rmSync(dir, { recursive: true, force: true }))

const run = (extraEnv) => {
  for (const [k, v] of Object.entries(extraEnv)) process.env[k] = v
  return runFormatForge({ cliArgs: ['translate', src, '--format', 'markdown'], repoRoot, timeoutMs: 120_000, log: () => {} })
}

console.log('\n=== stdout cap (audit medium) ===\n')
// T3-5: 此前这里写死 512MB —— 恰好比 V8 单字符串上限大 24 字节。断言改为
// 「宽裕但低于 V8 上限」，不再把那个具体的坏值锁进测试。
check('default cap is a bounded, generous size', DEFAULT_MAX_STDOUT_BYTES >= 128 * 1024 * 1024, String(DEFAULT_MAX_STDOUT_BYTES))
check('default cap stays under the V8 string ceiling', DEFAULT_MAX_STDOUT_BYTES < V8_MAX_STRING_LENGTH, `${DEFAULT_MAX_STDOUT_BYTES} vs ${V8_MAX_STRING_LENGTH}`)

// 1) 极小上限 → 触发上限并终止子进程，拿到明确错误（而不是 OOM 或挂着不返回）
process.env.FF_MAX_STDOUT_BYTES = '1000'
const capped = await run({})
check('tiny cap → ok:false', capped.ok === false, JSON.stringify(capped).slice(0, 200))
check('tiny cap → kind output_too_large', capped.error?.kind === 'output_too_large', String(capped.error?.kind))
check('tiny cap → message names the knob', /FF_MAX_STDOUT_BYTES/.test(capped.error?.message || ''), String(capped.error?.message))
check('tiny cap → resolved (killed child did not hang the call)', !!capped, '')

// 2) 恢复正常上限 → 同一转换成功（上限没有误伤正常路径）
delete process.env.FF_MAX_STDOUT_BYTES
const normal = await run({})
check('normal cap → conversion still succeeds', normal.ok === true, JSON.stringify(normal).slice(0, 200))
check('normal cap → content present and non-truncated', typeof normal.data?.content === 'string' && normal.data.content.includes('正文内容'), `len=${normal.data?.content?.length}`)

if (failures > 0) {
  console.error(`\n❌ ${failures} check(s) failed`)
  process.exit(1)
}
console.log('\n✅ stdout cap holds')