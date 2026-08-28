// 测量三工具的 schema 体积（description + parameters + output.schema 的 JSON 字符数）
// 用法：node scripts/measure_schema.mjs   （在 packages/dsh-formatforge 下运行）
import { createTranslateTool } from '../tools/translate.mjs'
import { createResultTool } from '../tools/result.mjs'
import { createFormatsTool } from '../tools/formats.mjs'

const noop = () => {}
const tools = {
  ff_translate: createTranslateTool({ repoRoot: '.', maxBytes: 1e8, timeoutMs: 120000, log: noop }),
  ff_result: createResultTool({ log: noop }),
  ff_formats: createFormatsTool({ log: noop }),
}

let total = 0
for (const [name, t] of Object.entries(tools)) {
  const payload = { description: t.description, parameters: t.parameters, output_schema: t.output?.schema }
  const size = JSON.stringify(payload).length
  total += size
  console.log(`${name.padEnd(14)} ${size} chars`)
}
console.log('TOTAL'.padEnd(14), total, 'chars')
