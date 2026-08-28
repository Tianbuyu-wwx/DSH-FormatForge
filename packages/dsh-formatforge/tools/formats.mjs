// tools/formats.mjs
//
// ff_formats — list formats FormatForge supports, optionally filtered by category.
//   Cheap: runs `formats` subcommand; supports `--category document|data|email|image|archive|audio`.
//   v0.10.0/A10: category 过滤让会话模型一次只列相关格式。

import { defineTool } from '@deepseek-ai/dsh-tools'
import { runFormatForge } from '../services/python-runner.mjs'

const CATEGORIES = ['document', 'data', 'email', 'image', 'archive', 'audio']

export function createFormatsTool({ repoRoot, log }) {
  return defineTool({
    name: 'ff_formats',
    description:
      'FormatForge: 列出支持转换的文件格式（输入/输出/策略）。' +
      '默认列全部；可用 category 过滤单类（document/data/email/image/archive/audio）。',
    parameters: {
      category: { type: 'string', enum: CATEGORIES, description: '按分类过滤（默认全部）。' },
    },
    output: {
      schema: {
        type: 'object',
        additionalProperties: false,
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
        const d = (value && value.data) || {}
        const cat = d.category && d.category !== 'all' ? `[${d.category}] ` : ''
        const lines = [
          `输入格式 ${cat}(${d.count} 种): ${(d.formats || []).join(', ')}`,
          `输出格式: ${(d.output_formats || []).join(', ')}`,
          `转换策略: ${(d.conversion_types || []).join(', ')}`,
        ]
        if (d.categories && d.categories.length) {
          lines.push(`可用分类: ${d.categories.join(', ')}`)
        }
        return [{ type: 'text', text: lines.join('\n') }]
      },
    },
    async execute(args) {
      const cliArgs = ['formats']
      if (args.category) cliArgs.push('--category', String(args.category))
      return await runFormatForge({ cliArgs, repoRoot, log })
    },
  })
}