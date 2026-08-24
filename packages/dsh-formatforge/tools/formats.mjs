// tools/formats.mjs
//
// ff_formats — list formats FormatForge supports. Cheap: runs `formats` subcommand.

import { defineTool } from '@deepseek-ai/dsh-tools'
import { runFormatForge } from '../services/python-runner.mjs'

export function createFormatsTool({ repoRoot, log }) {
  return defineTool({
    name: 'ff_formats',
    description:
      'FormatForge: 列出支持转换的文件格式矩阵（输入格式、输出格式、转换策略）。' +
      '在不确定某扩展名能否转换时先调用本工具查询。',
    parameters: {},
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
        const lines = [
          `输入格式 (${d.count} 种): ${(d.formats || []).join(', ')}`,
          `输出格式: ${(d.output_formats || []).join(', ')}`,
          `转换策略: ${(d.conversion_types || []).join(', ')}`,
        ]
        return [{ type: 'text', text: lines.join('\n') }]
      },
    },
    async execute() {
      return await runFormatForge({ cliArgs: ['formats'], repoRoot, log })
    },
  })
}
