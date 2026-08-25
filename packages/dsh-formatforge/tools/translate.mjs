// tools/translate.mjs
//
// ff_translate — forge local file(s) or raw text into AI-readable structured data.
// DSL notes (see dsh-tools assertAuthorKeys):
//   - parameters are a flat value-schema: only type/enum/default/description; no minimum/maximum.
//   - nested objects in output.schema MUST declare additionalProperties explicitly.
//
// Phase 5 层1: paths 数组（多文件/glob）+ max_chars 分页；单 path 仍兼容。

import { defineTool } from '@deepseek-ai/dsh-tools'
import { runFormatForge, validateLocalFile, DEFAULT_TIMEOUT_MS } from '../services/python-runner.mjs'

const OUTPUT_FORMATS = ['json', 'markdown', 'html', 'text']
const CONVERSION_TYPES = ['auto', 'text', 'structured', 'table', 'image_desc', 'ocr']
const HARD_CONTENT_CAP = 60_000

export function createTranslateTool({ repoRoot, maxBytes, timeoutMs, log }) {
  return defineTool({
    name: 'ff_translate',
    description:
      'FormatForge: 把本地文件或原始文本锻造成 AI 可读的结构化数据。' +
      '支持 pdf/docx/xlsx/pptx/eml/msg/epub/toml/yaml/json/csv/md/html/svg/图片/压缩包等 30+ 格式。' +
      '只接受已存在的本地文件路径（远程内容请先用 pwsh 下载）。' +
      '支持多文件（paths 数组，可含 * 通配）与 max_chars 分页。' +
      '当返回 data.enhance.needed=true 时，请按 enhance.hint 用你自己的能力基于 content 完成增强，不要再次调用外部 API。',
    parameters: {
      path: { type: 'string', description: '本地文件路径（单个）。与 paths/text 三选一。' },
      paths: {
        type: 'string',
        description:
          '多个本地路径，逗号分隔；每段可含 * 或 ** 通配（如 D:/docs/*.pdf、D:/docs/**/*.docx）。与 path/text 三选一。',
      },
      text: { type: 'string', description: '原始文本内容（stdin 模式）。' },
      format: { type: 'string', enum: OUTPUT_FORMATS, default: 'json', description: '输出格式，默认 json。' },
      type: {
        type: 'string',
        enum: CONVERSION_TYPES,
        default: 'auto',
        description: '转换策略：auto 自动选择；text 纯文本提取；structured 结构化抽取；table 表格抽取；image_desc 图片描述；ocr OCR 识别。',
      },
      prompt: { type: 'string', description: '可选：自定义转换指令（透传给策略层）。' },
      quality: { type: 'boolean', default: false, description: '附带质量报告（评分/警告/建议）。' },
      max_chars: {
        type: 'integer',
        description: '返回内容的最大字符数（分页用）。超长时结果带 truncated=true 与 next_offset。',
      },
      offset: { type: 'integer', default: 0, description: '内容起始偏移（配合 max_chars 翻页）。' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
        properties: {
          ok: { type: 'boolean', required: true },
          code: { type: 'integer' },
          data: {
            type: 'object',
            additionalProperties: true,
            properties: {
              content: { type: 'string' },
              format: { type: 'string' },
              meta: { type: 'object', additionalProperties: true },
              quality: { type: 'object', additionalProperties: true },
              enhance: { type: 'object', additionalProperties: true },
              truncated: { type: 'boolean' },
              next_offset: { type: 'integer' },
            },
          },
          error: {
            type: 'object',
            additionalProperties: true,
            properties: {
              kind: { type: 'string' },
              message: { type: 'string' },
            },
          },
        },
      },
      render(_args, value) {
        if (value && value.ok === false && value.error) {
          return [{ type: 'text', text: `FormatForge 失败 [${value.error.kind}]: ${value.error.message}` }]
        }
        const data = value && value.data ? value.data : {}
        const meta = data.meta || {}
        const head = `FormatForge 完成 (parser=${meta.parser || '?'}, ${meta.file_size ?? '?'}B, confidence=${meta.confidence ?? '?'})`
        let body = typeof data.content === 'string' ? data.content : JSON.stringify(data.content)
        if (body.length > 20_000) body = body.slice(0, 20_000) + `\n…[render 截断，共 ${body.length} 字符]`
        const enhance = data.enhance && data.enhance.needed
          ? `\n\n[enhance:${data.enhance.reason}] ${data.enhance.hint}`
          : ''
        const pageNote = data.truncated
          ? `\n\n[已按 max_chars 分页：本页到 offset=${(meta.next_offset ?? 0)}；继续读取请带 offset=${meta.next_offset}]`
          : ''
        return [{ type: 'text', text: `${head}\n\n${body}${enhance}${pageNote}` }]
      },
    },
    async execute(args) {
      const hasPath = typeof args.path === 'string' && args.path.trim().length > 0
      const hasPaths = typeof args.paths === 'string' && args.paths.trim().length > 0
      const hasText = typeof args.text === 'string' && args.text.length > 0

      if (!hasPath && !hasPaths && !hasText) {
        return { ok: false, code: -1, error: { kind: 'bad_request', message: '必须提供 path/paths/text 之一' } }
      }

      const cliArgs = ['translate', '--format', args.format || 'json']
      cliArgs.push('--type', args.type || 'auto')
      if (args.quality) cliArgs.push('--quality')
      if (args.prompt) cliArgs.push('--prompt', String(args.prompt))

      // 解析目标文件列表（path 单个 / paths 多个+glob）
      let targets = []
      const rawList = hasPath
        ? [args.path.trim()]
        : hasPaths
          ? args.paths.split(',').map((s) => s.trim()).filter(Boolean)
          : []
      if (rawList.length > 0) {
        const errors = []
        for (const item of rawList) {
          if (/[*?]/.test(item)) {
            const expanded = expandGlobLocal(item)
            if (expanded.length === 0) errors.push(`glob 无匹配: ${item}`)
            else targets.push(...expanded)
          } else {
            targets.push(item)
          }
        }
        targets = [...new Set(targets)]
        if (targets.length === 0) {
          return { ok: false, code: -1, error: { kind: 'file_not_found', message: `没有可用文件。${errors.join('; ')}` } }
        }
        for (const t of targets.slice(0, 20)) {
          const check = validateLocalFile(t, maxBytes)
          if (!check.ok) {
            return { ok: false, code: -1, error: { kind: 'file_not_found', message: check.reason } }
          }
        }
        if (targets.length > 20) {
          log?.(`[ff_translate] paths 超过 20 个，截断至前 20`)
          targets = targets.slice(0, 20)
        }
        // 多文件逐个转换后拼接；单文件保持原样（走 CLI 直传）
        if (targets.length > 1) {
          const parts = []
          let totalLen = 0
          const cap = Number(args.max_chars) > 0 ? Number(args.max_chars) : HARD_CONTENT_CAP
          const startOff = Math.max(0, Number(args.offset) || 0)
          for (const t of targets) {
            const one = await runFormatForge({
              cliArgs: [...cliArgs, t],
              repoRoot,
              stdinText: null,
              timeoutMs: timeoutMs || DEFAULT_TIMEOUT_MS,
              log,
            })
            const name = t.split(/[\\/]/).pop()
            if (one.ok) {
              parts.push(`## 文件: ${name}\n\n${one.data.content}`)
            } else {
              parts.push(`## 文件: ${name}\n\n[失败 ${one.error.kind}] ${one.error.message}`)
            }
          }
          let joined = parts.join('\n\n---\n\n')
          const fullLen = joined.length
          let truncated = false
          if (fullLen > startOff + cap) {
            // E1: 结构化截断——优先段落边界 > 行边界 > 硬切（与 core/utils.py smart_truncate 镜像）
            const windowEnd = startOff + cap
            let cut = joined.lastIndexOf('\n\n', windowEnd)
            if (cut < startOff + cap / 2) cut = joined.lastIndexOf('\n', windowEnd)
            if (cut <= startOff) {
              joined = joined.slice(startOff, windowEnd)
            } else {
              joined = joined.slice(startOff, cut)
            }
            truncated = true
          } else if (startOff > 0) {
            joined = joined.slice(startOff)
          }
          const nextOffset = truncated ? Math.max(startOff + 1, joined.length + startOff + 1) : undefined
          return {
            ok: true,
            code: 200,
            data: {
              content: joined,
              format: args.format || 'json',
              meta: {
                parser: 'multi',
                file_count: targets.length,
                total_chars: fullLen,
                next_offset: truncated ? nextOffset : undefined,
                elapsed_ms: 0,
              },
              truncated,
            },
          }
        }
        cliArgs.push(targets[0])
        const single = await runFormatForge({
          cliArgs,
          repoRoot,
          stdinText: null,
          timeoutMs: timeoutMs || DEFAULT_TIMEOUT_MS,
          log,
        })
        return applyPaging(single, args)
      }

      // stdin-text 模式（无分页需求，原样透传）
      cliArgs.push('--stdin-text')
      return await runFormatForge({
        cliArgs,
        repoRoot,
        stdinText: args.text,
        timeoutMs: timeoutMs || DEFAULT_TIMEOUT_MS,
        log,
      })
    },
  })
}

function expandGlobLocal(pattern) {
  const fs = statSyncFs()
  const path = pathMod()
  const normalized = pattern.replace(/\//g, '\\')
  const hasMagic = /[*?]/.test(normalized)
  if (!hasMagic) return [pattern]
  const recursive = normalized.includes('**')
  const dir = path.dirname(recursive ? normalized.split('**')[0] : normalized)
  const tail = recursive ? normalized.split('**').pop() : path.basename(normalized)
  const rx = new RegExp('^' + tail.replace(/[.\\]/g, (c) => '\\' + c).replace(/\*/g, '[^\\\\]*').replace(/\?/g, '.') + '$', 'i')
  const out = []
  const walk = (d, depth) => {
    let entries
    try {
      entries = fs.readdirSync(d, { withFileTypes: true })
    } catch {
      return
    }
    for (const e of entries) {
      const full = path.join(d, e.name)
      if (e.isDirectory()) {
        if (recursive && depth < 6) walk(full, depth + 1)
      } else if (rx.test(e.name)) out.push(full)
    }
  }
  walk(dir, 0)
  return out.sort()
}

function statSyncFs() {
  // eslint-disable-next-line no-undef
  return process.getBuiltinModule('node:fs')
}
function pathMod() {
  // eslint-disable-next-line no-undef
  return process.getBuiltinModule('node:path')
}

/** 单文件结果的 max_chars/offset 分页处理 */
function applyPaging(payload, args) {
  if (!payload.ok) return payload
  const cap = Number(args.max_chars) > 0 ? Number(args.max_chars) : 0
  if (!cap) return payload
  const startOff = Math.max(0, Number(args.offset) || 0)
  const content = String(payload.data.content || '')
  const fullLen = content.length
  let sliced = content
  let truncated = false
  if (startOff + cap < fullLen) {
    sliced = content.slice(startOff, startOff + cap)
    truncated = true
  } else if (startOff > 0) {
    sliced = content.slice(startOff)
  }
  return {
    ...payload,
    data: {
      ...payload.data,
      content: sliced,
      truncated,
      ...(truncated ? {} : {}),
    },
    // next_offset 放 meta 旁顶层便于 render 提示
    ...(truncated ? { paging: { next_offset: startOff + cap, total: fullLen } } : {}),
  }
}
