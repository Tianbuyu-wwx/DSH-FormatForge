// tools/translate.mjs
//
// ff_translate — forge a local file or raw text into AI-readable structured data.
// DSL notes (see dsh-tools assertAuthorKeys):
//   - parameters are a flat value-schema: only type/enum/default/description; no minimum/maximum.
//   - nested objects in output.schema MUST declare additionalProperties explicitly.

import { defineTool } from '@deepseek-ai/dsh-tools'
import { runFormatForge, validateLocalFile, DEFAULT_TIMEOUT_MS } from '../services/python-runner.mjs'

const OUTPUT_FORMATS = ['json', 'markdown', 'html', 'text']
const CONVERSION_TYPES = ['auto', 'text', 'structured', 'table', 'image_desc', 'ocr']

export function createTranslateTool({ repoRoot, maxBytes, timeoutMs, log }) {
  return defineTool({
    name: 'ff_translate',
    description:
      'FormatForge: 把本地文件或原始文本锻造成 AI 可读的结构化数据。' +
      '支持 pdf/docx/xlsx/pptx/eml/msg/epub/toml/yaml/json/csv/md/html/svg/图片/压缩包等 30+ 格式。' +
      '只接受已存在的本地文件路径（远程内容请先用 pwsh 下载）。' +
      '当返回 data.enhance.needed=true 时，请按 enhance.hint 用你自己的能力基于 content 完成增强，不要再次调用外部 API。',
    parameters: {
      path: { type: 'string', description: '本地文件的绝对路径。与 text 二选一，都提供时优先 path。' },
      text: { type: 'string', description: '原始文本内容（stdin 模式）。与 path 二选一。' },
      format: { type: 'string', enum: OUTPUT_FORMATS, default: 'json', description: '输出格式，默认 json。' },
      type: {
        type: 'string',
        enum: CONVERSION_TYPES,
        default: 'auto',
        description: '转换策略：auto 自动选择；text 纯文本提取；structured 结构化抽取；table 表格抽取；image_desc 图片描述；ocr OCR 识别。',
      },
      prompt: { type: 'string', description: '可选：自定义转换指令（透传给策略层）。' },
      quality: { type: 'boolean', default: false, description: '附带质量报告（评分/警告/建议）。' },
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
        if (body.length > 20_000) body = body.slice(0, 20_000) + `\n…[截断，共 ${body.length} 字符]`
        const enhance = data.enhance && data.enhance.needed
          ? `\n\n[enhance:${data.enhance.reason}] ${data.enhance.hint}`
          : ''
        return [{ type: 'text', text: `${head}\n\n${body}${enhance}` }]
      },
    },
    async execute(args) {
      const hasPath = typeof args.path === 'string' && args.path.trim().length > 0
      const hasText = typeof args.text === 'string' && args.text.length > 0

      if (!hasPath && !hasText) {
        return { ok: false, code: -1, error: { kind: 'bad_request', message: '必须提供 path 或 text 之一' } }
      }

      const cliArgs = ['translate', '--format', args.format || 'json']
      cliArgs.push('--type', args.type || 'auto')
      if (args.quality) cliArgs.push('--quality')
      if (args.prompt) cliArgs.push('--prompt', String(args.prompt))

      if (hasPath) {
        // 安全 clamp：存在 / 是文件 / 大小上限（与 CLI 内检查双保险）
        const check = validateLocalFile(args.path.trim(), maxBytes)
        if (!check.ok) {
          return { ok: false, code: -1, error: { kind: 'not_found', message: check.reason } }
        }
        cliArgs.push(args.path.trim())
      } else {
        cliArgs.push('--stdin-text')
      }

      return await runFormatForge({
        cliArgs,
        repoRoot,
        stdinText: hasPath ? null : args.text,
        timeoutMs: timeoutMs || DEFAULT_TIMEOUT_MS,
        log,
      })
    },
  })
}
