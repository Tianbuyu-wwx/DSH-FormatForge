// packages/dsh-formatforge/test/test-result-key-order.mjs
//
// T3-3 回归（审计）：大产物流式扫描器的文档注释写着「停止条件不预设键序：
// `ok`/`content`/`meta` 三项齐了就停」，代码却只看 `metaSeen && contentIsString`
// —— `ok` 根本不在停止条件里，而兜底又停在 `data` 闭合。两条路径都可能在读到
// `ok` 之前收工：只要 `ok` 排在 `data` 之后，每一份 > 64KB 的产物都会被判成
// `ok:false` → list 打上 `⚠非转换产物（伪造/损坏，取回会被拒）`，正是这个扫描器
// 当初被写出来消灭的那个误报。
//
// 当前 `_emit` 按 {ok, code, data} 发，所以线上还踩不到；但这是「注释宣称了代码
// 不保证的东西」的典型，而且就发生在一段专门为了**不假设键序**而写的代码里。
// 修法是让代码兑现注释：`ok` 进停止条件，缺它就一路扫到**信封**闭合。
//
// 用法：node packages/dsh-formatforge/test/test-result-key-order.mjs

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

const home = mkdtempSync(join(tmpdir(), 'ff-keyorder-test-'))
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

const BIG_CONTENT = '# 大产物\n\n' + '正文一行，够长到把 meta 推离文件尾。\n'.repeat(3000) // > 64KB

/** 手写 JSON，键序逐字可控（JSON.stringify 按插入序，但这里要的是「非协议序」的确定性） */
function envelope(order, { ok, meta, content }) {
  const dataParts = {
    content: `"content":${JSON.stringify(content)}`,
    format: '"format":"markdown"',
    meta: `"meta":${JSON.stringify(meta)}`,
  }
  const data = `"data":{${order.data.map((k) => dataParts[k]).join(',')}}`
  const topParts = { ok: `"ok":${ok}`, code: '"code":200', data }
  return `{${order.top.map((k) => topParts[k]).join(',')}}`
}

const META = { parser: 'txt', file_size: 4242, result_id: 'cvt_keyorder01', confidence: 0.66 }

// 1) `ok` 排在 `data` 之后（协议之外的键序）
const okLast = envelope({ top: ['code', 'data', 'ok'], data: ['content', 'format', 'meta'] }, {
  ok: 'true',
  meta: META,
  content: BIG_CONTENT,
})
writeFileSync(join(inbox, 'ok-last.ff.json'), okLast)

// 2) `meta` 排在 `content` 之前**且** `ok` 在最后（两个键序假设同时被打破）
const metaFirstOkLast = envelope({ top: ['code', 'data', 'ok'], data: ['meta', 'format', 'content'] }, {
  ok: 'true',
  meta: { ...META, result_id: 'cvt_keyorder02' },
  content: BIG_CONTENT,
})
writeFileSync(join(inbox, 'meta-first.ff.json'), metaFirstOkLast)

// 3) 同样的键序，但 ok:false —— 必须仍然判非法（别把「修好」变成「一律放行」）
const okLastFalse = envelope({ top: ['code', 'data', 'ok'], data: ['content', 'format', 'meta'] }, {
  ok: 'false',
  meta: { ...META, result_id: 'cvt_keyorder03' },
  content: BIG_CONTENT,
})
writeFileSync(join(inbox, 'ok-last-false.ff.json'), okLastFalse)

// 4) 协议键序的对照组：修复不能影响正常产物
const protocolOrder = envelope({ top: ['ok', 'code', 'data'], data: ['content', 'format', 'meta'] }, {
  ok: 'true',
  meta: { ...META, result_id: 'cvt_keyorder04' },
  content: BIG_CONTENT,
})
writeFileSync(join(inbox, 'protocol.ff.json'), protocolOrder)

const { createResultTool } = await import('../tools/result.mjs')
const tool = createResultTool({ log: () => {} })

console.log('\n=== ff_result scanner stop condition vs key order (T3-3) ===\n')

for (const name of ['ok-last.ff.json', 'meta-first.ff.json', 'ok-last-false.ff.json', 'protocol.ff.json']) {
  check(`fixture ${name} is a large artifact (> 64KB)`, statSync(join(inbox, name)).size > 64 * 1024, String(statSync(join(inbox, name)).size))
}

const listed = await tool.execute({ list: true })
const row = (f) => listed.data.items.find((it) => it.file === f)

check(
  'ok after data: still reported valid (was ⚠非转换产物)',
  row('ok-last.ff.json')?.valid === true && row('ok-last.ff.json')?.id === 'cvt_keyorder01',
  JSON.stringify(row('ok-last.ff.json')),
)
check(
  'meta before content + ok last: still reported valid',
  row('meta-first.ff.json')?.valid === true && row('meta-first.ff.json')?.id === 'cvt_keyorder02',
  JSON.stringify(row('meta-first.ff.json')),
)
check(
  'ok:false after data: still reported invalid',
  row('ok-last-false.ff.json')?.valid === false,
  JSON.stringify(row('ok-last-false.ff.json')),
)
check(
  'protocol key order unaffected',
  row('protocol.ff.json')?.valid === true && row('protocol.ff.json')?.confidence === 0.66,
  JSON.stringify(row('protocol.ff.json')),
)

const rendered = tool.output.render({}, listed)
const okLastLine = rendered[0].text.split('\n').find((l) => l.includes('ok-last.ff.json') || l.includes('cvt_keyorder01'))
check('render: no spurious ⚠非转换产物 warning for the ok-last artifact', !!okLastLine && !okLastLine.includes('非转换产物'), String(okLastLine))

// 取回路径（整段 JSON.parse）与 list 的判定必须一致
const fetched = await tool.execute({ id: 'cvt_keyorder01', max_chars: 100 })
check('fetch by result_id agrees with the list verdict', fetched.ok === true && fetched.data?.id === 'cvt_keyorder01', JSON.stringify({ ok: fetched.ok, err: fetched.error }))
const fetchedFalse = await tool.execute({ id: 'ok-last-false' })
check(
  'fetching the ok:false artifact is still rejected',
  fetchedFalse.ok === false && fetchedFalse.error?.kind === 'not_a_conversion_result',
  JSON.stringify(fetchedFalse),
)

if (failures > 0) {
  console.error(`\n❌ ${failures} check(s) failed`)
  process.exit(1)
}
console.log('\n✅ scanner stop condition is key-order independent')
