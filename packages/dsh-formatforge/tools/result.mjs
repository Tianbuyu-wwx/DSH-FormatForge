// tools/result.mjs
//
// ff_result — consume inbox artifacts without knowing file paths.
//   list mode : scan ~/.dsh/formatforge/inbox for .ff.json, return metadata rows
//               (id/file/parser/confidence/forged_at/size) — never full content.
//   fetch mode: given `id` (result_id prefix or file stem), return the forged
//               content with smart pagination (E1 semantics).
//
// Security: reads are confined to the inbox directory; path traversal in `id`
// is rejected (no separators, no '..').

import { defineTool } from '@deepseek-ai/dsh-tools'
import { join, basename } from 'node:path'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { inboxDir } from '../services/inbox-watcher.mjs'

const DEFAULT_MAX_CHARS = 12_000

/** E1-mirror: paragraph boundary > line boundary > hard cut. */
function smartTruncate(text, maxChars, start = 0) {
  if (start >= text.length) return { chunk: '', nextOffset: undefined }
  const windowEnd = Math.min(start + maxChars, text.length)
  if (windowEnd === text.length) return { chunk: text.slice(start), nextOffset: undefined }
  const window = text.slice(start, windowEnd)
  let cut = window.lastIndexOf('\n\n')
  if (cut < maxChars / 2) cut = window.lastIndexOf('\n')
  let chunk, next
  if (cut <= 0) {
    chunk = window
    next = windowEnd
  } else {
    chunk = window.slice(0, cut)
    next = start + cut + 1
    if (next < text.length && text[next] === '\n') next += 1
  }
  return { chunk, nextOffset: next < text.length ? next : undefined }
}

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
      // 只读头部 2KB 解析元数据，避免大文件整载
      const head = readFileSync(full, { encoding: 'utf8', flag: 'r' }).slice(0, 2048)
      let meta = {}
      try {
        const j = JSON.parse(head.endsWith('}') ? head : head.slice(0, head.lastIndexOf('}') + 1))
        meta = j.data || j
      } catch { /* 截断的 JSON 头解析失败则留空 */ }
      const fileInfo = meta.fileInfo || {}
      rows.push({
        id: meta.resultId || name.replace(/\.ff\.json$/, ''),
        file: name,
        source: (fileInfo.fileName || '') || name.replace(/\.ff\.json$/, ''),
        parser: fileInfo.fileType || '?',
        pages: fileInfo.pageCount ?? 0,
        confidence: typeof meta.confidence === 'number' ? meta.confidence : null,
        enhance: meta.enhance?.reason || null,
        forged_at: st.mtime.toISOString(),
        size_bytes: st.size,
        path: full,
      })
    } catch { /* 竞态删除等场景跳过 */ }
  }
  return rows.sort((a, b) => b.forged_at.localeCompare(a.forged_at))
}

export function createResultTool({ log = () => {} }) {
  return defineTool({
    name: 'ff_result',
    title: 'FormatForge 收件箱结果查询',
    description:
      '查询 FormatForge 收件箱（拖拽自动转换）的锻造结果。list=true 列出全部产物元数据；' +
      '传 id（result_id 或文件名前缀）取回对应内容（支持 max_chars/offset 分页）。' +
      '收件箱目录仅限白名单读取。',
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        list: { type: 'boolean', default: false, description: '列出收件箱全部产物元数据。' },
        id: { type: 'string', description: '要取回的结果：result_id 或 .ff 文件名前缀。与 list 二选一。' },
        max_chars: { type: 'integer', default: DEFAULT_MAX_CHARS, description: '内容分页大小。' },
        offset: { type: 'integer', default: 0, description: '内容起始偏移。' },
      },
    },
    outputSchema: {
      type: 'object',
      additionalProperties: true,
      properties: {
        ok: { type: 'boolean', required: true },
      },
    },
    async execute(args) {
      const wantList = args.list || !args.id
      if (wantList) {
        const items = listArtifacts()
        log(`[ff_result] listed ${items.length} artifact(s)`)
        return {
          ok: true,
          code: 200,
          data: { count: items.length, items },
        }
      }

      // fetch 模式 —— 路径安全：id 不允许分隔符与 ..
      const rawId = String(args.id)
      if (/[/\\]|\.\./.test(rawId)) {
        return {
          ok: false,
          code: 4003,
          error: { kind: 'bad_request', message: '非法 id：不允许路径分隔符或 ..' },
        }
      }
      const dir = inboxDir()
      let target = null
      try {
        const names = readdirSync(dir).filter((n) => n.endsWith('.ff.json'))
        // 精确 stem 匹配 → result_id 前缀匹配 → 唯一包含匹配
        target =
          names.find((n) => n === `${rawId}.ff.json`) ||
          names.find((n) => n.startsWith(`${rawId}.ff.`)) ||
          names.find((n) => n.includes(rawId))
        if (!target && names.length > 0) {
          // 尝试按 result_id 前缀在 JSON 内容里找（读头部）
          for (const n of names) {
            try {
              const head = readFileSync(join(dir, n), { encoding: 'utf8' }).slice(0, 512)
              if (head.includes(`"resultId": "${rawId}`)) {
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
        return {
          ok: false,
          code: 4004,
          error: { kind: 'parse_failed', message: `产物损坏无法解析: ${e.message}` },
        }
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
    },
    render(_args, value) {
      if (value && value.ok === false && value.error) {
        return [{ type: 'text', text: `ff_result 失败 [${value.error.kind}]: ${value.error.message}` }]
      }
      const d = value.data || {}
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
  })
}
