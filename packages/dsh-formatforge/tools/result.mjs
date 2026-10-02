// tools/result.mjs
//
// ff_result — consume inbox artifacts without knowing file paths.
//   list mode  : newest N artifacts (index DB when available, filesystem scan otherwise)
//   search mode: FTS5 full-text over title/excerpt (v3.0.0, Chinese-friendly)
//   stats mode : index/database summary (v3.0.0)
//   fetch mode : given `id` (result_id prefix or file stem), return forged content
//                with smart pagination (E1 semantics).
// Security: reads confined to inbox; path traversal in `id` rejected.
//
// DSL contract (dsh-tools): parameters = flat value-schema; output = { schema, render }.
//
// v3.0.0 字段口径修正（P-1.1）：CLI 实际写出的是 `data.content` + `data.meta.*`
// （parser/result_id/confidence/file_size），而本文件此前读的是 `data.convertedContent`
// / `data.resultId` / `data.fileInfo.*` —— 结果是**取回正文恒为空、parser 恒为 `?`**。
// 现在以实际契约为准，旧字段名仅作兜底（兼容历史产物）。

import { defineTool } from '@deepseek-ai/dsh-tools'
import { join, basename } from 'node:path'
import { existsSync, openSync, readSync, closeSync, fstatSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { inboxDir } from '../services/inbox-watcher.mjs'
import { resolveSourceName as ffResolveSourceName } from '../services/ff-paths.mjs'
import { dbStats, findArtifactById, queryArtifacts, sqliteSupport } from '../services/inbox-db.mjs'
import { smartTruncate } from './_truncate.mjs'

const DEFAULT_MAX_CHARS = 12_000
const DEFAULT_LIMIT = 50
const MAX_LIMIT = 200
// 元数据读取策略：小文件整体解析（准确）；大文件只扫前缀 + 正则兜底（省内存/CPU）。
const FULL_PARSE_LIMIT = 2 * 1024 * 1024
const META_SCAN_BYTES = 64 * 1024
// 大产物元数据兜底：首尾各读一段（meta 排在 content 之后 → 尾部窗口才是关键）
const TAIL_SCAN_BYTES = 1024 * 1024
// id 反查的单个产物体积上限（超过就不再全文扫描）
const ARTIFACT_SCAN_MAX_BYTES = 64 * 1024 * 1024
const escapeRe = (s) => String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** 大文件兜底：从前缀里正则抓关键字段（正文很长的产物，meta 会排在 content 之后）。 */
function metaFromScan(head) {
  const grab = (key) => {
    const m = new RegExp(`"${key}"\\s*:\\s*"([^"]*)"`).exec(head)
    return m ? m[1] : null
  }
  const num = (key) => {
    const m = new RegExp(`"${key}"\\s*:\\s*([0-9.]+)`).exec(head)
    return m ? Number(m[1]) : null
  }
  return {
    result_id: grab('result_id') || grab('resultId'),
    parser: grab('parser') || grab('fileType'),
    confidence: num('confidence'),
    source_name: grab('source_name') || grab('fileName'),
  }
}

/** v0.13.0: 截断逻辑已抽到 _truncate.mjs 共用；smartTruncate 由该模块导入（与 core/utils.py::smart_truncate 镜像） */

/** 产物 JSON → 扁平元数据。字段以 CLI 实际契约（content + meta.*）为准，旧名兜底。 */
function artifactMeta(doc, fileName) {
  const data = (doc && doc.data) || {}
  const meta = (data && data.meta) || {}
  const fileInfo = (data && data.fileInfo) || {}
  const stem = String(fileName || '').replace(/\.ff\.json$/, '')
  const rawContent = typeof data.content === 'string' ? data.content : typeof data.convertedContent === 'string' ? data.convertedContent : ''
  const confidence = typeof meta.confidence === 'number' ? meta.confidence : typeof data.confidence === 'number' ? data.confidence : null
  return {
    id: meta.result_id || data.resultId || stem,
    source: meta.source_name || fileInfo.fileName || stem,
    parser: meta.parser || fileInfo.fileType || '?',
    fileType: meta.file_type || fileInfo.fileType || null,
    pages: meta.page_count ?? fileInfo.pageCount ?? 0,
    confidence,
    enhance: (data && data.enhance) || null,
    format: data.format || null,
    chars: rawContent.length,
    content: rawContent,
  }
}

/** 产物名丢了源文件扩展名（`合同.txt` → `合同.ff.json`），用同目录同 stem 反查真实源名。
 *  实现在 services/ff-paths.mjs（与 http/api.mjs 共用一份）。 */
const resolveSourceName = ffResolveSourceName

/**
 * 大产物的元数据兜底：只读**首尾窗口**而不是整文件。
 *
 * payload 里 `content` 在前、`meta` 紧随其后（后面才是 structured_data/quality），
 * 所以正文一长，`meta` 就落在尾部窗口里 —— 只看头部会得到 `parser='?'`。
 * 用 fd 分段读，避免把上百 MB 的产物整个读进内存（旧实现 `readFileSync().slice()` 正是如此）。
 */
function readEdgeWindows(full) {
  const fd = openSync(full, 'r')
  try {
    const size = fstatSync(fd).size
    const headLen = Math.min(size, META_SCAN_BYTES)
    const head = Buffer.alloc(headLen)
    readSync(fd, head, 0, headLen, 0)
    let tail = Buffer.alloc(0)
    if (size > headLen + 1024) {
      const tailLen = Math.min(size - headLen, TAIL_SCAN_BYTES)
      const buf = Buffer.alloc(tailLen)
      readSync(fd, buf, 0, tailLen, size - tailLen)
      tail = buf
    }
    return `${head.toString('utf8')}\n${tail.toString('utf8')}`
  } finally {
    closeSync(fd)
  }
}

function rowFromFile(name, full) {
  const st = statSync(full)
  let doc = {}
  let scanned = null
  try {
    if (st.size <= FULL_PARSE_LIMIT) {
      doc = JSON.parse(readFileSync(full, { encoding: 'utf8' }))
    } else {
      scanned = metaFromScan(readEdgeWindows(full))
    }
  } catch {
    /* 大文件/损坏：落回正则兜底 */
    try {
      scanned = metaFromScan(readEdgeWindows(full))
    } catch {
      scanned = null
    }
  }
  const m = artifactMeta(doc, name)
  if (scanned) {
    m.id = m.id === String(name).replace(/\.ff\.json$/, '') && scanned.result_id ? scanned.result_id : m.id
    m.parser = m.parser === '?' && scanned.parser ? scanned.parser : m.parser
    m.confidence = m.confidence === null ? scanned.confidence : m.confidence
    m.source = scanned.source_name || m.source
  }
  const stem = String(name).replace(/\.ff\.json$/, '')
  return {
    id: m.id,
    file: name,
    source: resolveSourceName(inboxDir(), stem, m.source),
    parser: m.parser,
    pages: m.pages,
    confidence: m.confidence,
    enhance: m.enhance?.reason || null,
    forged_at: st.mtime.toISOString(),
    size_bytes: st.size,
    path: full,
  }
}

/** 文件系统兜底（无索引库时仍然可用；也让 list 永远反映"真相源"文件）。 */
function listFromFiles(limit) {
  const dir = inboxDir()
  let names
  try {
    names = readdirSync(dir)
  } catch {
    return []
  }
  const rows = []
  for (const name of names) {
    if (!name.endsWith('.ff.json')) continue
    try {
      rows.push(rowFromFile(name, join(dir, name)))
    } catch {
      /* concurrent delete etc. */
    }
  }
  rows.sort((a, b) => b.forged_at.localeCompare(a.forged_at))
  return Number.isFinite(limit) && limit > 0 ? rows.slice(0, limit) : rows
}

function rowFromDb(record) {
  return {
    id: record.id,
    file: basename(String(record.json_path || `${record.id}.ff.json`)),
    source: record.source_name || record.id,
    parser: record.parser || '?',
    pages: record.pages ?? 0,
    confidence: typeof record.confidence === 'number' ? record.confidence : null,
    enhance: record.enhance_reason || null,
    forged_at: new Date((record.created_at || 0) * 1000).toISOString(),
    size_bytes: record.source_bytes || 0,
    path: record.json_path || join(inboxDir(), `${record.id}.ff.json`),
    status: record.status || 'ok',
    session_id: record.session_id || null,
    chars: record.chars ?? null,
  }
}

function clampLimit(value) {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return DEFAULT_LIMIT
  return Math.max(1, Math.min(MAX_LIMIT, Math.trunc(n)))
}

export function createResultTool({ log = () => {}, repoRoot = null } = {}) {
  const dbCtx = { repoRoot, log }

  async function listOrSearch({ q = null, limit = DEFAULT_LIMIT } = {}) {
    const support = sqliteSupport()
    if (support.available) {
      const res = await queryArtifacts({ q, limit }, dbCtx)
      if (res && res.search_mode !== 'unavailable') {
        return { items: res.rows.map(rowFromDb), source: 'index', search_mode: res.search_mode, next_cursor: res.next_cursor }
      }
    }
    const items = listFromFiles(limit)
    if (!q) return { items, source: 'files', search_mode: 'scan', next_cursor: null }
    const needle = q.toLowerCase()
    return {
      items: items.filter((r) => String(r.source).toLowerCase().includes(needle) || String(r.id).toLowerCase().includes(needle)),
      source: 'files',
      search_mode: 'name-match',
      next_cursor: null,
    }
  }

  return defineTool({
    name: 'ff_result',
    description:
      '查 FormatForge 收件箱产物。list=true 列出（可 limit）；search=词 全文检索；stats=true 看库状态；id/ids 取回内容（可分页）。',
    parameters: {
      list: { type: 'boolean', default: false, description: '列出产物（默认取最新 limit 条）。' },
      search: { type: 'string', description: '全文检索：标题+正文摘要（中文子串可用）。' },
      stats: { type: 'boolean', default: false, description: '返回索引库与收件箱统计。' },
      limit: { type: 'integer', default: DEFAULT_LIMIT, description: `list/search 返回条数上限（≤${MAX_LIMIT}）。` },
      id: { type: 'string', description: '单取回：result_id/文件名前缀。' },
      ids: { type: 'string', description: '批量：id 逗号分隔（≤20）。' },
      max_chars: { type: 'integer', default: DEFAULT_MAX_CHARS, description: '分页大小。' },
      offset: { type: 'integer', default: 0 },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: true,
        properties: {
          ok: { type: 'boolean', required: true },
          code: { type: 'integer' },
          data: { type: 'object', additionalProperties: true },
          error: { type: 'object', additionalProperties: true },
        },
      },
      render(_args, value) {
        if (value && value.ok === false && value.error) {
          return [{ type: 'text', text: `ff_result 失败 [${value.error.kind}]: ${value.error.message}` }]
        }
        const d = (value && value.data) || {}
        // R3.2: 批量结果渲染
        if (d.batch) {
          const parts = d.results.map((r) => {
            if (!r.ok) return `- ❌ ${r.error?.message || '失败'}`
            const rd = r.data
            const enh = rd.enhance?.needed ? ` ⚠enhance=${rd.enhance.reason}` : ''
            const trunc = rd.truncated ? `（已截断，续读 offset=${rd.next_offset}）` : ''
            return `- [${rd.id}] ${rd.source} (parser=${rd.parser}, confidence=${rd.confidence ?? '?'}${enh})${trunc}\n${rd.content}`
          })
          return [
            {
              type: 'text',
              text: `FormatForge 批量取回 ${d.ok_count}/${d.count} 份：\n\n${parts.join('\n\n---\n\n')}`,
            },
          ]
        }
        // v3.0.0: stats 模式
        if (d.stats) {
          const s = d.stats
          const lines = [
            `FormatForge 索引库：${s.available ? '可用' : '不可用'}（来源 ${s.source || '?'}）`,
            `库文件：${s.db_path || '?'}`,
            s.available
              ? `产物 ${s.total} 条（失败 ${s.by_status?.failed ?? 0} / 已删 ${s.deleted ?? 0}）/ 正文 ${s.chars ?? 0} 字 / 源文件 ${s.source_bytes ?? 0} 字节`
              : `原因：${s.reason || '未知'}`,
            s.available && s.by_format ? `格式分布：${Object.entries(s.by_format).map(([k, v]) => `${k}=${v}`).join(', ')}` : '',
            `收件箱：${d.inbox || inboxDir()}（列目录 ${d.file_count ?? '?'} 个产物文件）`,
          ].filter(Boolean)
          return [{ type: 'text', text: lines.join('\n') }]
        }
        if (d.count !== undefined) {
          const head = d.query
            ? `FormatForge 检索「${d.query}」命中 ${d.count} 条（${d.search_mode}，来源 ${d.source}）`
            : `FormatForge 收件箱共 ${d.count} 个产物（来源 ${d.source}）`
          if (d.count === 0) {
            return [
              {
                type: 'text',
                text: `${head}。\n把文件拖进网页即可自动锻造${d.next_cursor ? `；更多请用 cursor=${d.next_cursor}` : ''}。`,
              },
            ]
          }
          const lines = d.items.map(
            (it) =>
              `- [${it.id}] ${it.source} (parser=${it.parser}, confidence=${it.confidence ?? '?'}` +
              `${it.enhance ? `, ⚠enhance=${it.enhance}` : ''}, ${Math.round(it.size_bytes / 1024)}KB, ${it.forged_at})`,
          )
          const more = d.next_cursor ? `\n\n[还有更多：cursor=${d.next_cursor}]` : ''
          return [{ type: 'text', text: `${head}：\n${lines.join('\n')}${more}\n\n用 ff_result(id=...) 取回内容。` }]
        }
        const enh = d.enhance?.needed ? `\n[enhance:${d.enhance.reason}] ${d.enhance.hint}` : ''
        const pageNote = d.truncated ? `\n\n[已截断；继续读取请带 offset=${d.next_offset}]` : ''
        return [
          {
            type: 'text',
            text:
              `FormatForge 产物 ${d.id} (${d.source}, parser=${d.parser}, confidence=${d.confidence ?? '?'})\n` +
              `可读版：${d.md_path}\n\n${d.content}${enh}${pageNote}`,
          },
        ]
      },
    },
    async execute(args) {
      // v3.0.0: 统计
      if (args.stats) {
        const stats = await dbStats(dbCtx)
        let fileCount = 0
        try {
          fileCount = readdirSync(inboxDir()).filter((n) => n.endsWith('.ff.json')).length
        } catch {
          fileCount = 0
        }
        log(`[ff_result] stats: ${stats.source}${stats.available ? ` total=${stats.total}` : ` (${stats.reason})`}`)
        return { ok: true, code: 200, data: { stats, inbox: inboxDir(), file_count: fileCount } }
      }

      const limit = clampLimit(args.limit)
      const searchTerm = args.search ? String(args.search).trim() : ''

      // v3.0.0: 检索模式
      if (searchTerm) {
        const { items, source, search_mode, next_cursor } = await listOrSearch({ q: searchTerm, limit })
        log(`[ff_result] search "${searchTerm}" → ${items.length} hit(s) via ${search_mode}`)
        return {
          ok: true,
          code: 200,
          data: { count: items.length, query: searchTerm, items, source, search_mode, next_cursor },
        }
      }

      const wantList = args.list || (!args.id && !args.ids)
      if (wantList) {
        const { items, source, next_cursor } = await listOrSearch({ limit })
        log(`[ff_result] listed ${items.length} artifact(s) via ${source}`)
        return { ok: true, code: 200, data: { count: items.length, items, source, next_cursor } }
      }

      // R3.2: 批量模式 —— ids 逗号分隔，逐份复用单取回逻辑
      if (args.ids && String(args.ids).trim()) {
        const ids = String(args.ids)
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
          .slice(0, 20)
        if (ids.length === 0) {
          return { ok: false, code: 4001, error: { kind: 'bad_request', message: 'ids 为空。' } }
        }
        const results = []
        for (const one of ids) {
          results.push(await fetchOne(one, args, log))
        }
        const okCount = results.filter((r) => r.ok).length
        return { ok: true, code: 200, data: { batch: true, count: results.length, ok_count: okCount, results } }
      }

      return fetchOne(args.id, args, log)
    },
  })
}

async function fetchOne(rawId, args, log) {
  const raw = String(rawId || '').trim()
  if (!raw || /[/\\]|\.\./.test(raw)) {
    return { ok: false, code: 4003, error: { kind: 'bad_request', message: `非法 id：${rawId}` } }
  }
  const dir = inboxDir()
  let target = null
  try {
    // 0) 首选：索引库里按 id 精确查（json_path 与正文大小无关）
    const row = findArtifactById(raw)
    if (row && row.json_path && existsSync(row.json_path)) target = basename(row.json_path)
  } catch {
    target = null
  }
  try {
    const names = readdirSync(dir)
    // 三阶段匹配：精确 → 前缀 → 全文里的 resultId（兼容 cvt 前缀）
    const exact = `${raw}.ff.json`
    if (!target && names.includes(exact)) target = exact
    if (!target) {
      const prefixed = names.filter((n) => n.endsWith('.ff.json') && n.startsWith(raw))
      if (prefixed.length > 0) target = prefixed.sort()[0]
    }
    if (!target) {
      // 产物文件名是「源文件 stem.ff.json」，不含 result_id，所以只能扫正文。
      // **必须扫全文**：payload 里 content 在前、meta.result_id 在后，正文一长 id 就落在头部窗口之外
      // （曾经的 64KB 前缀窗口让大产物按 id 取回一律 4002）。前缀语义与 id 前缀匹配保持一致。
      const re = new RegExp(`"(?:result_id|resultId)"\\s*:\\s*"${escapeRe(raw)}`)
      for (const name of names) {
        if (!name.endsWith('.ff.json')) continue
        try {
          const full = join(dir, name)
          if (statSync(full).size > ARTIFACT_SCAN_MAX_BYTES) continue
          if (re.test(readFileSync(full, { encoding: 'utf8' }))) {
            target = name
            break
          }
        } catch {
          /* skip */
        }
      }
    }
  } catch {
    target = null
  }
  if (!target) {
    return {
      ok: false,
      code: 4002,
      error: { kind: 'file_not_found', message: `收件箱中找不到匹配 "${raw}" 的产物（可先 list=true 查看）。` },
    }
  }

  const full = join(dir, target)
  let doc
  try {
    doc = JSON.parse(readFileSync(full, { encoding: 'utf8' }))
  } catch (e) {
    return { ok: false, code: 4004, error: { kind: 'parse_failed', message: `产物损坏无法解析: ${e.message}` } }
  }
  const m = artifactMeta(doc, target)
  const stemOfTarget = basename(target).replace(/\.ff\.json$/, '')
  m.source = resolveSourceName(dir, stemOfTarget, m.source)
  const maxChars = Math.max(200, Number(args.max_chars) || DEFAULT_MAX_CHARS)
  const start = Math.max(0, Number(args.offset) || 0)
  const { chunk, nextOffset } = smartTruncate(m.content, maxChars, start)

  log(`[ff_result] fetched ${target} (${chunk.length} chars @${start}, parser=${m.parser})`)
  return {
    ok: true,
    code: 200,
    data: {
      id: m.id,
      file: basename(target),
      source: m.source,
      parser: m.parser,
      file_type: m.fileType,
      pages: m.pages,
      confidence: m.confidence,
      enhance: m.enhance,
      format: m.format,
      chars: m.chars,
      md_path: full.replace(/\.ff\.json$/, '.ff.md'),
      content: chunk,
      truncated: nextOffset !== undefined,
      next_offset: nextOffset,
    },
  }
}
