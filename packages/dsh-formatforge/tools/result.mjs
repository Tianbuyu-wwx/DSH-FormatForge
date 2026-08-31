// tools/result.mjs
//
// ff_result — consume inbox artifacts without knowing file paths.
//   list mode : scan ~/.dsh/formatforge/inbox for .ff.json, return metadata rows.
//   fetch mode: given `id` (result_id prefix or file stem), return forged content
//               with smart pagination (E1 semantics).
// Security: reads confined to inbox; path traversal in `id` rejected.
//
// DSL contract (dsh-tools): parameters = flat value-schema; output = { schema, render }.

import { defineTool } from '@deepseek-ai/dsh-tools'
import { join, basename } from 'node:path'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { inboxDir } from '../services/inbox-watcher.mjs'
import { smartTruncate } from './_truncate.mjs'

const DEFAULT_MAX_CHARS = 12_000

/** v0.13.0: 截断逻辑已抽到 _truncate.mjs 共用；smartTruncate 由该模块导入（与 core/utils.py::smart_truncate 镜像） */

function listArtifacts() {
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
    const full = join(dir, name)
    try {
      const st = statSync(full)
      const head = readFileSync(full, { encoding: 'utf8' }).slice(0, 2048)
      let meta = {}
      try {
        const j = JSON.parse(head.endsWith('}') ? head : head.slice(0, head.lastIndexOf('}') + 1))
        meta = j.data || j
      } catch { /* truncated head — leave empty */ }
      const fileInfo = meta.fileInfo || {}
      rows.push({
        id: meta.resultId || name.replace(/\.ff\.json$/, ''),
        file: name,
        source: fileInfo.fileName || name.replace(/\.ff\.json$/, ''),
        parser: fileInfo.fileType || '?',
        pages: fileInfo.pageCount ?? 0,
        confidence: typeof meta.confidence === 'number' ? meta.confidence : null,
        enhance: meta.enhance?.reason || null,
        forged_at: st.mtime.toISOString(),
        size_bytes: st.size,
        path: full,
      })
    } catch { /* concurrent delete etc. */ }
  }
  return rows.sort((a, b) => b.forged_at.localeCompare(a.forged_at))
}

export function createResultTool({ log = () => {} }) {
  return defineTool({
    name: 'ff_result',
    description: '查 FormatForge 收件箱产物。list=true 列出；id/ids 取回内容（可分页）。',
    parameters: {
      list: { type: 'boolean', default: false, description: '列出全部产物。' },
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
        if (d.count !== undefined) {
          if (d.count === 0) return [{ type: 'text', text: 'FormatForge 收件箱当前为空。把文件拖进网页即可自动锻造。' }]
          const lines = d.items.map(
            (it) =>
              `- [${it.id}] ${it.source} (parser=${it.parser}, confidence=${it.confidence ?? '?'}` +
              `${it.enhance ? `, ⚠enhance=${it.enhance}` : ''}, ${Math.round(it.size_bytes / 1024)}KB, ${it.forged_at})`,
          )
          return [{ type: 'text', text: `FormatForge 收件箱共 ${d.count} 个产物：\n${lines.join('\n')}\n\n用 ff_result(id=...) 取回内容。` }]
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
      const wantList = args.list || (!args.id && !args.ids)
      if (wantList) {
        const items = listArtifacts()
        log(`[ff_result] listed ${items.length} artifact(s)`)
        return { ok: true, code: 200, data: { count: items.length, items } }
      }

      // R3.2: 批量模式 —— ids 逗号分隔，逐份复用单取回逻辑
      if (args.ids && String(args.ids).trim()) {
        const ids = String(args.ids)
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
          .slice(0, 20)
        if (ids.length === 0) {
          return { ok: false, code: 4003, error: { kind: 'bad_request', message: 'ids 为空' } }
        }
        const results = []
        for (const oneId of ids) {
          results.push(await fetchOne(oneId, args, log))
        }
        const okCount = results.filter((r) => r.ok).length
        log(`[ff_result] batch fetched ${okCount}/${ids.length}`)
        return { ok: true, code: 200, data: { batch: true, count: ids.length, ok_count: okCount, results } }
      }

      return await fetchOne(String(args.id), args, log)
    },
  })
}

/** 单份取回（id 解析 + 路径安全 + 分页），单/批量共用。 */
async function fetchOne(rawId, args, log) {
  // 路径安全：id 不允许分隔符与 ..
  if (/[/\\]|\.\./.test(rawId)) {
    return { ok: false, code: 4003, error: { kind: 'bad_request', message: '非法 id：不允许路径分隔符或 ..' } }
  }
  const dir = inboxDir()
  let target = null
  try {
    const names = readdirSync(dir).filter((n) => n.endsWith('.ff.json'))
    // v0.13.0/C6: 删 includes() 兜底（id="abc" 会命中 xxxabcxxx.ff.json 是误匹配）
    // 三段递进：精确 file stem → 前缀（如 resultId 前 8 位）→ JSON 头里的 resultId
    target =
      names.find((n) => n === `${rawId}.ff.json`) ||
      names.find((n) => n.startsWith(`${rawId}.ff.`)) ||
      null
    if (!target && names.length > 0) {
      for (const n of names) {
        try {
          const head = readFileSync(join(dir, n), { encoding: 'utf8' }).slice(0, 512)
          // 精确匹配 resultId（JSON 头里 "resultId": "cvt..." 字段）
          if (head.includes(`"resultId": "${rawId}"`)) {
            target = n
            break
          }
        } catch { /* skip */ }
      }
    }
  } catch {
    target = null
  }
  if (!target) {
    return {
      ok: false,
      code: 4002,
      error: { kind: 'file_not_found', message: `收件箱中找不到匹配 "${rawId}" 的产物（可先 list=true 查看）。` },
    }
  }

  const full = join(dir, target)
  let doc
  try {
    doc = JSON.parse(readFileSync(full, { encoding: 'utf8' }))
  } catch (e) {
    return { ok: false, code: 4004, error: { kind: 'parse_failed', message: `产物损坏无法解析: ${e.message}` } }
  }
  const data = doc.data || {}
  const content = typeof data.convertedContent === 'string' ? data.convertedContent : ''
  const maxChars = Math.max(200, Number(args.max_chars) || DEFAULT_MAX_CHARS)
  const start = Math.max(0, Number(args.offset) || 0)
  const { chunk, nextOffset } = smartTruncate(content, maxChars, start)

  log(`[ff_result] fetched ${target} (${chunk.length} chars @${start})`)
  return {
    ok: true,
    code: 200,
    data: {
      id: data.resultId || target.replace(/\.ff\.json$/, ''),
      file: basename(target),
      source: data.fileInfo?.fileName || '',
      parser: data.fileInfo?.fileType || '?',
      confidence: data.confidence ?? null,
      enhance: data.enhance || null,
      md_path: full.replace(/\.ff\.json$/, '.ff.md'),
      content: chunk,
      truncated: nextOffset !== undefined,
      next_offset: nextOffset,
    },
  }
}
