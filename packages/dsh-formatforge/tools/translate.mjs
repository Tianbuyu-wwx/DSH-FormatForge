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
import { renderTruncate, smartTruncate } from './_truncate.mjs'

const OUTPUT_FORMATS = ['json', 'markdown', 'html', 'text']
const CONVERSION_TYPES = ['auto', 'text', 'structured', 'table', 'image_desc', 'ocr']
const HARD_CONTENT_CAP = 60_000

export function createTranslateTool({ repoRoot, maxBytes, timeoutMs, log }) {
  return defineTool({
    name: 'ff_translate',
    description: '把本地文件/文本转成 AI 可读数据（30+ 格式）。返回 enhance.needed=true 时按 hint 自行增强，勿调外部 API。',
    parameters: {
      path: { type: 'string', description: '本地路径。与 paths/text 三选一。' },
      paths: { type: 'string', description: '多路径逗号分隔，可含 */** 通配。' },
      text: { type: 'string', description: '原始文本（stdin）。' },
      format: { type: 'string', enum: OUTPUT_FORMATS, default: 'json' },
      type: { type: 'string', enum: CONVERSION_TYPES, default: 'auto' },
      quality: { type: 'boolean', default: false, description: '附质量报告（低置信自动附带）。' },
      max_chars: { type: 'integer', description: '分页大小。' },
      offset: { type: 'integer', default: 0 },
      language: { type: 'string', description: '目标语言代码（ISO 639-1，如 zh/en/ja）。' },
      output_file: { type: 'string', description: '把 content 另存到此路径。' },
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
          return [{ type: 'text', text: `FormatForge 失败 [${value.error.kind}]: ${value.error.message}` }]
        }
        const data = value && value.data ? value.data : {}
        const meta = data.meta || {}
        const head = `FormatForge 完成 (parser=${meta.parser || '?'}, ${meta.file_size ?? '?'}B, confidence=${meta.confidence ?? '?'})`
        let body = typeof data.content === 'string' ? data.content : JSON.stringify(data.content)
        // R3.1: 长 markdown/json 内容带 200 字头部预览，模型可先判断质量/相关性再决定翻页
        let preview = ''
        if (body.length > 2_000 && (data.format === 'markdown' || data.format === 'json')) {
          preview = `\n\n[头部预览]\n${renderTruncate(body, 200)}…`
        }
        // C1/v0.13.0: 兜底截断走 renderTruncate（段落/行边界优先，避免切碎代码块/表格）
        if (body.length > 20_000) {
          const orig = body.length
          body = renderTruncate(body, 20_000) + `\n…[render 截断，共 ${orig} 字符]`
        }
        const enhance = data.enhance && data.enhance.needed
          ? `\n\n[enhance:${data.enhance.reason}] ${data.enhance.hint}`
          : ''
        // A1/v0.13.0: 分页提示统一读 paging.next_offset（与单文件路径一致；多文件路径已迁）
        const nextOffset = data.paging?.next_offset ?? meta.next_offset
        const pageNote = data.truncated && nextOffset !== undefined
          ? `\n\n[已按 max_chars 分页：本页到 offset=${nextOffset}；继续读取请带 offset=${nextOffset}]`
          : ''
        return [{ type: 'text', text: `${head}\n\n${body}${preview}${enhance}${pageNote}` }]
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
      if (args.prompt) cliArgs.push('--prompt', String(args.prompt))
      // B9/v0.10.0: 目标语言透传
      if (args.language) cliArgs.push('--language', String(args.language).toLowerCase())
      // A9/v0.10.0: output_file 透传
      if (args.output_file) cliArgs.push('--output-file', String(args.output_file))
      // R3.1 智能默认：quality 由模型显式传入，或 auto 模式下自动附带
      // （低置信/劣化场景在结果里自动出现 quality.actions，供自愈闭环消费）
      const wantQuality = args.quality === true || (args.quality === undefined && (args.type || 'auto') === 'auto')
      if (wantQuality) cliArgs.push('--quality')

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
          // v0.14.0/B-P1-7 多文件拼接用 HTML 注释代替 --- ——markdown --- 水平线
          // （--- 第 1 页 ---）会被 smartTruncate 的 --- 边界检测误判为分隔符。
          // HTML 注释不影响渲染，对会话模型可见（可读性好），与 --- 不冲突。
          let joined = parts.join('\n\n<!-- ff-file-sep -->\n\n')
          const fullLen = joined.length
          let truncated = false
          if (fullLen > startOff + cap) {
            // v0.14.0/B-P1-7: 用 _truncate.mjs::smartTruncate 替代旧的 inline 逻辑，
            // 保证多文件分隔符 \n\n---\n\n 在多文件分页时不被切断
            const { chunk, nextOffset } = smartTruncate(joined, cap, startOff)
            joined = chunk
            truncated = true
            // smartTruncate 的 nextOffset 是相对全文本的偏移，与原设计一致
            // 保留作为 paging.next_offset 输出
            var nextOffsetVal = nextOffset
          } else if (startOff > 0) {
            joined = joined.slice(startOff)
            // startOff > 0 但不需要再切（cap 已够），nextOffset 仍 undefined
          }
          // A1/v0.13.0: 分页字段统一到顶层 paging（与单文件 applyPaging 输出一致）；
          // v0.14.0/B-P1-7: smartTruncate 直接给出 nextOffset 数值（如果 truncated）
          const nextOffset = truncated ? nextOffsetVal : undefined
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
                elapsed_ms: 0,
              },
              truncated,
              ...(truncated ? { paging: { next_offset: nextOffset, total: fullLen } } : {}),
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
