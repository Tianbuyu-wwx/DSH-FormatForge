// tools/diff.mjs
//
// ff_diff — 对比两份解析结果（合同/法规/脚本版本对照）。
//   包装 Python CLI `diff` 子命令（v0.12.0 新增）：
//     1. 各调用 ff_translate 把两份文件转成 markdown
//     2. 行级 LCS diff 输出 unified diff 格式
//   输出：additions / deletions / unchanged_count + 一份 unified diff 文本预览
//
// DSL contract: parameters = flat value-schema; output = { schema, render }.

import { defineTool } from '@deepseek-ai/dsh-tools'
import { runFormatForge, validateLocalFile } from '../services/python-runner.mjs'

const OUTPUT_FORMATS = ['json', 'markdown', 'html', 'text']

export function createDiffTool({ repoRoot, maxBytes, timeoutMs, log = () => {} }) {
  return defineTool({
    name: 'ff_diff',
    description:
      '对比两份文件的内容差异（合同/法规/脚本版本对照）。' +
      '返回 additions/deletions/unchanged_count + unified diff 预览。',
    parameters: {
      path_a: { type: 'string', description: '文件 A 路径（旧版本）。' },
      path_b: { type: 'string', description: '文件 B 路径（新版本）。' },
      format: { type: 'string', enum: OUTPUT_FORMATS, default: 'text', description: '中间转换格式。' },
      context_lines: { type: 'integer', default: 3, description: 'diff 上下文行数。' },
      max_chars: { type: 'integer', default: 12000, description: 'diff 文本截断上限。' },
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
          return [{ type: 'text', text: `ff_diff 失败 [${value.error.kind}]: ${value.error.message}` }]
        }
        const d = (value && value.data) || {}
        const lines = [
          `对比结果（A → B）：`,
          `  新增 ${d.additions} 行 · 删除 ${d.deletions} 行 · 未变 ${d.unchanged_count} 行`,
          `  相似度: ${d.similarity ?? '?'} · 截断: ${d.truncated ? '是' : '否'}`,
        ]
        if (d.diff_preview) {
          lines.push('', '--- diff 预览（最多 ' + (d.max_chars ?? 12000) + ' 字符）---', d.diff_preview)
        }
        return [{ type: 'text', text: lines.join('\n') }]
      },
    },
    async execute(args) {
      if (!args.path_a || !args.path_b) {
        return {
          ok: false,
          code: 4001,
          error: { kind: 'bad_request', message: 'path_a 与 path_b 必填' },
        }
      }
      // B1/v0.13.0: size clamp 复用 ff_translate 的 validateLocalFile（防 OOM 大文件）
      for (const p of [args.path_a, args.path_b]) {
        const check = validateLocalFile(p, maxBytes)
        if (!check.ok) {
          return { ok: false, code: -1, error: { kind: 'too_large', message: check.reason } }
        }
      }
      const contextLines = Math.max(0, Math.min(20, Number(args.context_lines) || 3))
      const maxChars = Math.max(500, Number(args.max_chars) || 12000)

      log(`[ff_diff] A=${args.path_a} B=${args.path_b} context=${contextLines} maxChars=${maxChars}`)
      const res = await runFormatForge({
        cliArgs: [
          'diff',
          String(args.path_a),
          String(args.path_b),
          '--format', args.format || 'text',
          '--context', String(contextLines),
          '--max-chars', String(maxChars),
        ],
        repoRoot,
        timeoutMs,
        log,
      })
      return res
    },
  })
}