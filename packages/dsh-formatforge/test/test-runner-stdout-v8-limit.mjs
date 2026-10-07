// packages/dsh-formatforge/test/test-runner-stdout-v8-limit.mjs
//
// T3-5 回归：stdout 上限必须低于 V8 的单字符串长度上限。
//
// 旧值 512MB = 536,870,912，比 V8 的 2^29-24 = 536,870,888 **大 24 字节**。
// 当时 stdout 是 `stdout += d` 边收边拼的，所以 ASCII 为主的输出会在上限触发
// 之前就在 'data' 处理器里同步抛 RangeError —— 而 emit 里的同步抛出不会路由到
// 'error' 监听器。守卫被它本要防住的那次崩溃抢了先。
//
// T1-1 改成 Buffer 累积之后，字符串只在末尾成形一次，所以这条上限现在是纵深
// 防御而不是承重墙 —— 除非 FF_MAX_STDOUT_BYTES 被设到 V8 上限之上，那就又成了
// 承重墙。因此夹取（clamp）也必须验。
//
// 用法：node packages/dsh-formatforge/test/test-runner-stdout-v8-limit.mjs

let failures = 0
function check(name, cond, detail = '') {
  if (cond) {
    console.log(`✅ ${name}`)
  } else {
    failures++
    console.error(`❌ ${name}  ${detail}`)
  }
}

const { DEFAULT_MAX_STDOUT_BYTES, V8_MAX_STRING_LENGTH, resolveStdoutCap } =
  await import('../services/python-runner.mjs')

console.log('\n=== stdout cap vs V8 max string length (T3-5) ===\n')

// V8 的真实上限：直接问引擎，不写死一个可能过时的常数
let measured = null
try {
  ''.padEnd(V8_MAX_STRING_LENGTH + 1)
  measured = 'no throw'
} catch (e) {
  measured = e.constructor.name
}
check('V8_MAX_STRING_LENGTH 是真实上限（+1 即 RangeError）', measured === 'RangeError', String(measured))

check(
  '默认上限低于 V8 单字符串上限',
  DEFAULT_MAX_STDOUT_BYTES < V8_MAX_STRING_LENGTH,
  `cap=${DEFAULT_MAX_STDOUT_BYTES} v8=${V8_MAX_STRING_LENGTH} 差=${V8_MAX_STRING_LENGTH - DEFAULT_MAX_STDOUT_BYTES}`,
)

check(
  '默认上限仍然宽裕（>= 128MB，不误伤正常信封）',
  DEFAULT_MAX_STDOUT_BYTES >= 128 * 1024 * 1024,
  String(DEFAULT_MAX_STDOUT_BYTES),
)

// 一个 ASCII 为主的输出跑满上限时，字符数 <= 字节数，所以字符串必然成形得了
check(
  '跑满上限的 ASCII 输出仍可字符串化',
  DEFAULT_MAX_STDOUT_BYTES <= V8_MAX_STRING_LENGTH,
  `${DEFAULT_MAX_STDOUT_BYTES} > ${V8_MAX_STRING_LENGTH}`,
)

console.log('')

// ── FF_MAX_STDOUT_BYTES 旋钮 ────────────────────────────────────────────
check('未设置 → 用默认值', resolveStdoutCap({}) === DEFAULT_MAX_STDOUT_BYTES, String(resolveStdoutCap({})))
check(
  '合理值 → 原样生效（收紧仍然可用）',
  resolveStdoutCap({ FF_MAX_STDOUT_BYTES: '1000' }) === 1000,
  String(resolveStdoutCap({ FF_MAX_STDOUT_BYTES: '1000' })),
)
check(
  '越过 V8 上限的值 → 被夹回上限以下',
  resolveStdoutCap({ FF_MAX_STDOUT_BYTES: String(1024 * 1024 * 1024) }) <= V8_MAX_STRING_LENGTH,
  String(resolveStdoutCap({ FF_MAX_STDOUT_BYTES: String(1024 * 1024 * 1024) })),
)
check(
  '旧的 512MB 取值 → 也被夹回（正是本条 finding 的那 24 字节）',
  resolveStdoutCap({ FF_MAX_STDOUT_BYTES: String(512 * 1024 * 1024) }) <= V8_MAX_STRING_LENGTH,
  String(resolveStdoutCap({ FF_MAX_STDOUT_BYTES: String(512 * 1024 * 1024) })),
)
check('非法值 → 退回默认', resolveStdoutCap({ FF_MAX_STDOUT_BYTES: 'nonsense' }) === DEFAULT_MAX_STDOUT_BYTES)
check('0 / 负数 → 退回默认', resolveStdoutCap({ FF_MAX_STDOUT_BYTES: '-1' }) === DEFAULT_MAX_STDOUT_BYTES)

if (failures > 0) {
  console.error(`\n❌ ${failures} check(s) failed`)
  process.exit(1)
}
console.log('\n✅ stdout cap stays under the V8 string ceiling')
