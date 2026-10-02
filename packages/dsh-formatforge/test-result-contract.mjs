// test-result-contract.mjs — ff_result 的字段口径契约测试（v3.0.0 / P-1.1 回归）。
//
// 背景：v2.x 里 ff_result 读的是 `data.convertedContent` / `data.resultId` / `data.fileInfo.*`，
// 而 CLI（与 watcher 落盘的 .ff.json）写的是 `data.content` / `data.meta.*`。后果是
// **取回正文恒为空、parser 恒为 `?`、confidence 恒为 null** —— 工具看起来在工作，实际拿不到东西。
// 本测试用「真实形状」的产物钉死这个口径，并覆盖 v3.0.0 新增的 search/stats/limit。
//
// 用法：node packages/dsh-formatforge/test-result-contract.mjs

import { mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { tmpdir } from 'node:os'
import { ensureHostStubs } from './test/_host-stubs.mjs'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = dirname(dirname(HERE)) // packages/dsh-formatforge → 仓库根（.venv-fg 就在这一层）

let failures = 0
const ok = (label) => console.log('  ok   ' + label)
const fail = (label, detail) => {
  failures += 1
  console.error('  FAIL ' + label + (detail === undefined ? '' : ' — ' + detail))
}
const assert = (cond, label, detail) => (cond ? ok(label) : fail(label, detail))

// —— 隔离环境：临时 FF_HOME，并把索引库关掉（本测试只验证"用文件即能取回"这条底线）
const HOME = join(tmpdir(), `ff-result-contract-${Date.now()}`)
mkdirSync(join(HOME, 'inbox'), { recursive: true })
process.env.FF_HOME = HOME
process.env.FF_DB = 'off' // 无 DB 也要能 list/search/fetch（回滚开关的语义）

const stubs = ensureHostStubs()
const SOURCE = '合同2024.txt'
// 正文刻意为"长文"，用于验证分页（>2 个分页窗口）
const CONTENT =
  '# 转换结果\n\n--- 第 1 页 ---\n\n付款条款：月结30天\n合同编号 HT-2024-001\n' +
  Array.from({ length: 12 }, (_, i) => `第 ${i + 1} 条：双方约定以人民币结算，逾期按日万分之五计息。\n`).join('')
const RESULT_ID = 'cvt20261001120000abcdef'

function writeArtifact({ legacy = false } = {}) {
  const inbox = join(HOME, 'inbox')
  writeFileSync(join(inbox, SOURCE), '付款条款：月结30天\n合同编号 HT-2024-001\n', 'utf8')
  const doc = legacy
    ? {
        // 旧形状：v0.x 产物把字段放在 data 里（convertedContent/resultId/fileInfo）
        ok: true,
        code: 200,
        data: {
          convertedContent: CONTENT,
          resultId: RESULT_ID,
          fileInfo: { fileName: SOURCE, fileType: 'pdf', pageCount: 2 },
          confidence: 0.8,
        },
      }
    : {
        ok: true,
        code: 200,
        data: {
          content: CONTENT,
          format: 'markdown',
          meta: {
            parser: 'txt',
            file_size: 60,
            result_id: RESULT_ID,
            confidence: 0.95,
            elapsed_ms: 12,
            quality_auto: false,
          },
        },
      }
  writeFileSync(join(inbox, '合同2024.ff.json'), JSON.stringify(doc, null, 2), 'utf8')
  writeFileSync(join(inbox, '合同2024.ff.md'), CONTENT, 'utf8')
  return inbox
}

try {
  const { createResultTool } = await import('./tools/result.mjs')
  const tool = createResultTool({ log: () => {}, repoRoot: REPO_ROOT })
  const inbox = writeArtifact()

  console.log('\n1. fetch 用真实契约（content + meta.*）')
  const fetched = await tool.execute({ id: RESULT_ID })
  assert(fetched.ok === true, 'fetch ok', JSON.stringify(fetched).slice(0, 160))
  const fd = fetched.data || {}
  assert(typeof fd.content === 'string' && fd.content.includes('付款条款'), 'content 非空（P-1.1 回归点）', JSON.stringify(fd.content))
  assert(fd.content === CONTENT, 'content 与产物正文完全一致')
  assert(fd.parser === 'txt', 'parser 来自 meta.parser（不再是 ?）', String(fd.parser))
  assert(fd.confidence === 0.95, 'confidence 来自 meta.confidence（不再是 null）', String(fd.confidence))
  assert(fd.source === SOURCE, 'source 来自 meta.source_name/文件名', String(fd.source))
  assert(fd.id === RESULT_ID, 'id 保留 cvt 前缀', String(fd.id))
  assert(String(fd.md_path).endsWith('合同2024.ff.md'), 'md_path 指向可读版', String(fd.md_path))

  console.log('\n2. 分页（max_chars / offset）')
  const page1 = await tool.execute({ id: RESULT_ID, max_chars: 200 })
  assert(page1.data.truncated === true, '小分页触发 truncated')
  assert(typeof page1.data.next_offset === 'number', '给出 next_offset', String(page1.data.next_offset))
  const page2 = await tool.execute({ id: RESULT_ID, max_chars: 200, offset: page1.data.next_offset })
  assert(page2.ok === true && page2.data.content.length > 0, '续读仍能取到内容')

  console.log('\n3. id 前缀匹配与错误码')
  const byPrefix = await tool.execute({ id: 'cvt2026100112' })
  assert(byPrefix.ok === true && byPrefix.data.id === RESULT_ID, '前缀匹配到同一条')
  const missing = await tool.execute({ id: 'no-such-id' })
  assert(missing.ok === false && missing.code === 4002, '找不到时返回 4002', JSON.stringify(missing).slice(0, 120))
  const traversal = await tool.execute({ id: '../../etc/passwd' })
  assert(traversal.ok === false && traversal.code === 4003, '路径穿越被拒（4003）')

  console.log('\n4. list / search / stats（无索引库时的文件兜底）')
  const listed = await tool.execute({ list: true })
  assert(listed.ok === true && listed.data.count === 1, 'list 返回 1 条', String(listed.data.count))
  assert(listed.data.items[0].parser === 'txt', 'list 行的 parser 也来自 meta（不再是 ?）')
  const searched = await tool.execute({ search: '合同' })
  assert(searched.ok === true && searched.data.count === 1, '中文短词检索命中（LIKE/文件名兜底）', JSON.stringify(searched.data).slice(0, 140))
  const stats = await tool.execute({ stats: true })
  assert(stats.ok === true && stats.data.file_count === 1, 'stats 报告磁盘产物数', JSON.stringify(stats.data).slice(0, 160))
  assert(stats.data.stats.available === false, 'FF_DB=off 时 stats 明确报告库不可用', JSON.stringify(stats.data.stats).slice(0, 120))

  console.log('\n5. 旧形状产物（convertedContent / fileInfo / resultId）仍能取回')
  writeArtifact({ legacy: true })
  const legacyDoc = await tool.execute({ id: RESULT_ID })
  assert(legacyDoc.ok === true && legacyDoc.data.content === CONTENT, '旧字段名兜底仍可读正文')
  assert(legacyDoc.data.parser === 'pdf', '旧 fileInfo.fileType 兜底为 parser', String(legacyDoc.data.parser))
  assert(legacyDoc.data.confidence === 0.8, '旧 confidence 兜底生效', String(legacyDoc.data.confidence))

  console.log('\n6. 大产物（正文 > 64K 字符 / 文件 > 2MB）：id 反查与 meta 兜底都要工作')
  {
    // 复现条件：content 在前、meta.result_id 在后 → 只扫前 64KB 就找不到 id；
    // 文件 > 2MB 时又走不了全量 JSON.parse，只能靠首尾窗口正则。
    const BIG_ID = 'cvt20261001120002bigdoc'
    const BIG_SOURCE = '大文档2024.txt'
    const BIG_CONTENT = `# 大文档\n\n${'中文正文行，用来把 result_id 挤出前 64KB 窗口。\n'.repeat(90_000)}` // ≈ 2.6MB
    const bigJson = join(inbox, '大文档2024.ff.json')
    writeFileSync(join(inbox, BIG_SOURCE), '大文档正文\n', 'utf8')
    writeFileSync(
      bigJson,
      JSON.stringify({ ok: true, code: 200, data: { content: BIG_CONTENT, format: 'markdown', meta: { parser: 'txt', file_size: BIG_CONTENT.length, result_id: BIG_ID, confidence: 0.9 } } }, null, 2),
      'utf8',
    )
    writeFileSync(join(inbox, '大文档2024.ff.md'), BIG_CONTENT, 'utf8')

    const { readFileSync, statSync } = await import('node:fs')
    const size = statSync(bigJson).size
    assert(size > 2 * 1024 * 1024, `大产物文件超过 2MB（实际 ${size} 字节，走首尾窗口兜底）`)
    assert(!readFileSync(bigJson, 'utf8').slice(0, 64 * 1024).includes(`"result_id": "${BIG_ID}"`), '复现条件成立：result_id 落在前 64KB 之外')

    const bigFetch = await tool.execute({ id: BIG_ID })
    assert(bigFetch.ok === true, '按 id 取回大产物（全文扫描兜底）', JSON.stringify(bigFetch).slice(0, 160))
    assert(bigFetch.data.id === BIG_ID && bigFetch.data.parser === 'txt', '大产物 id/parser 正确（首尾窗口抓到 meta）', JSON.stringify({ id: bigFetch.data.id, parser: bigFetch.data.parser }))
    assert(bigFetch.data.source === BIG_SOURCE, '大产物 source 是真实文件名', String(bigFetch.data.source))
    assert(typeof bigFetch.data.content === 'string' && bigFetch.data.content.length > 0, '大产物正文非空', String(bigFetch.data.content).slice(0, 40))

    const bigList = await tool.execute({ list: true })
    const bigRow = (bigList.data.items || []).find((r) => r.id === BIG_ID)
    assert(Boolean(bigRow), 'list 里能按 id 找到大产物', JSON.stringify((bigList.data.items || []).map((r) => r.id)))
    assert(bigRow && bigRow.parser === 'txt', 'list 行 parser 不再退化成 ?', String(bigRow && bigRow.parser))
  }

  console.log('\n7. 空收件箱的边界')
  rmSync(inbox, { recursive: true, force: true })
  mkdirSync(inbox, { recursive: true })
  const empty = await tool.execute({ list: true })
  assert(empty.ok === true && empty.data.count === 0, '空收件箱返回 0 条而非报错')
} finally {
  stubs.cleanup()
  try {
    rmSync(HOME, { recursive: true, force: true })
  } catch {
    /* best effort */
  }
}

if (failures > 0) {
  console.error(`\nRESULT-CONTRACT-FAIL: ${failures} assertion(s) failed`)
  process.exit(1)
}
console.log('\nRESULT-CONTRACT-OK: ff_result 字段口径 + search/stats/limit')
