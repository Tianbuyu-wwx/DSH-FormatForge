// packages/dsh-formatforge/test/test-python-runner-stdin.mjs
//
// v1.0.3/JS-H2 回归：子进程在消费 stdin 之前就退出时，stdin 流会 emit 'error'(EPIPE)。
// 这不是 promise rejection（宿主的 unhandledRejection 兜底不管用），若没有 'error'
// 监听就是**进程级未捕获异常** → 打死活着的 harness。本测试：
//   1) 正常路径（真跑一次 `python -m formatforge version`）必须成功——证明加了监听
//      没破坏正常 stdin.end()；
//   2) 坏 repoRoot（`python -m formatforge` → ModuleNotFoundError 立即退出）+ 4MB
//      stdinText 必须**被 EPIPE 打中**，且 runFormatForge 仍然 resolve 出
//      ok:false（而不是让进程崩掉）。
//
// 用法：node packages/dsh-formatforge/test/test-python-runner-stdin.mjs

import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const here = dirname(fileURLToPath(import.meta.url))
// 本 JS 包位于 <repo>/packages/dsh-formatforge → 仓库根（含 formatforge/ core/ pyproject.toml）在上三层
const repoRoot = join(here, '..', '..', '..')

let failures = 0
function check(name, cond, detail = '') {
  if (cond) {
    console.log(`✅ ${name}`)
  } else {
    failures++
    console.error(`❌ ${name}  ${detail}`)
  }
}

// 未捕获异常/未处理 rejection = 本测试要防的失败模式：记下来并让进程以非零退出
const escapes = []
process.on('uncaughtException', (e) => {
  escapes.push(`uncaughtException: ${e?.code || ''} ${e?.message || e}`)
})
process.on('unhandledRejection', (e) => {
  escapes.push(`unhandledRejection: ${e?.message || e}`)
})

const { runFormatForge } = await import('../services/python-runner.mjs')

console.log('\n=== python-runner stdin EPIPE guard (JS-H2) ===\n')

// 1) 正常路径
const okRun = await runFormatForge({ cliArgs: ['version'], repoRoot, timeoutMs: 120_000, log: () => {} })
check('normal run still works (version)', okRun.ok === true && !!okRun.data?.version, JSON.stringify(okRun).slice(0, 300))

// 2) 子进程在消费 stdin 前就退出 + 大 stdinText → 必然 EPIPE
//    用 argparse 立即报错的参数组合：parse_args 在任何 stdin 读取之前就 exit(2)，
//    所以 4MB stdin 一定写进一个已经死掉的管道（与「repoRoot 错 → ModuleNotFoundError」
//    是同一个早退路径）。
const logs = []
const t0 = Date.now()
const epipeRun = await runFormatForge({
  cliArgs: ['translate', '--stdin-text', '--definitely-not-a-flag'],
  repoRoot,
  stdinText: 'x'.repeat(4 * 1024 * 1024),
  timeoutMs: 60_000,
  log: (l) => logs.push(l),
})
const elapsed = Date.now() - t0

check('child exiting before stdin → still resolves (no hang)', epipeRun && epipeRun.ok === false, JSON.stringify(epipeRun).slice(0, 300))
check('early child exit → error envelope (not a crash)', epipeRun?.ok === false && typeof epipeRun?.error?.kind === 'string', JSON.stringify(epipeRun?.error))
check('resolved well before the timeout', elapsed < 60_000, `elapsed=${elapsed}ms`)
const stdioLog = logs.find((l) => /child stdio|stdin (write|end) failed/.test(l))
check('EPIPE path was actually exercised (logged, not swallowed silently)', !!stdioLog, JSON.stringify(logs.slice(-3)))
if (stdioLog) console.log(`   ↳ ${stdioLog}`)
check('no uncaughtException / unhandledRejection escaped', escapes.length === 0, JSON.stringify(escapes))

if (failures > 0) {
  console.error(`\n❌ ${failures} check(s) failed`)
  process.exit(1)
}
console.log('\n✅ stdin EPIPE guard holds (process survived the child crash)')