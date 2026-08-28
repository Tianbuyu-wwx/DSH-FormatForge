// tools/batch.mjs
//
// ff_batch — bulk-forge a directory (or glob) into one or many output files.
//   Wraps the Python CLI `batch` subcommand. Each file is parsed concurrently
//   (ThreadPoolExecutor on the Python side); failures don't abort the run.
//   Output: <out>/<stem>.<format> per file + <out>/_batch_report.json summary.
//
// DSL contract (dsh-tools): parameters = flat value-schema; output = { schema, render }.

import { defineTool } from '@deepseek-ai/dsh-tools'
import { runFormatForge } from '../services/python-runner.mjs'

const OUTPUT_FORMATS = ['json', 'markdown', 'html', 'text']
const CONVERSION_TYPES = ['auto', 'text', 'structured', 'table', 'image_desc', 'ocr']

export function createBatchTool({ repoRoot, maxBytes, timeoutMs, log = () => {} }) {
  return defineTool({
    name: 'ff_batch',
    description:
      '批量锻造：目录或 glob 一次转多个文件（共享 Python 进程、并发解析、失败不中断）。' +
      '返回汇总报告 + 每文件结果（路径、parser、confidence、chars、耗时）。',
    parameters: {
      source: { type: 'string', description: '目录路径（如 E:/docs）或 glob 模式（如 E:/docs/*.pdf）。' },
      out: { type: 'string', description: '产物输出目录（不存在则创建）。' },
      format: { type: 'string', enum: OUTPUT_FORMATS, default: 'markdown', description: '输出格式。' },
      type: { type: 'string', enum: CONVERSION_TYPES, default: 'auto' },
      workers: { type: 'integer', default: 4, description: '并发线程数（1-8）。' },
      recursive: { type: 'boolean', default: false, description: '递归子目录。' },
      force: { type: 'boolean', default: false, description: '强制重转（忽略产物是否比源新）。' },
      pages: { type: 'string', description: 'PDF 页选择如 1-3,7（仅 PDF 生效）。' },
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
          return [{ type: 'text', text: `ff_batch 失败 [${value.error.kind}]: ${value.error.message}` }]
        }
        const d = (value && value.data) || {}
        if (d.total === 0) {
          return [{ type: 'text', text: `ff_batch：未发现可转换文件。源="${d.source ?? '?'}"。` }]
        }
        const lines = (d.results || []).slice(0, 50).map((r) => {
          if (!r.ok) return `- ❌ ${r.file}: ${r.kind} ${r.message}`
          const outRel = r.out ? r.out.replace(/^.*[\\/]/, '') : '?'
          return `- ✅ ${r.file.replace(/^.*[\\/]/, '')} → ${outRel} (parser=${r.parser}, confidence=${r.confidence}, ${r.chars} chars, ${r.elapsed_ms}ms)`
        })
        const truncNote = d.results && d.results.length > 50 ? `\n...（还有 ${d.results.length - 50} 个未显示）` : ''
        const failSection = d.failures && d.failures.length
          ? `\n\n[失败 ${d.failed} 个]\n` + d.failures.map((f) => `- ${f.file}: ${f.kind} ${f.message}`).join('\n')
          : ''
        return [
          {
            type: 'text',
            text:
              `ff_batch 完成 ${d.ok_count}/${d.total}（跳过 ${d.skipped}，失败 ${d.failed}，平均置信度 ${d.avg_confidence}，${d.elapsed_ms}ms）\n` +
              `产物目录：${d.out_dir}\n` +
              `详细报告：${d.out_dir}/_batch_report.json\n\n` +
              lines.join('\n') + truncNote + failSection,
          },
        ]
      },
    },
    async execute(args) {
      if (!args.source || !args.out) {
        return { ok: false, code: 4001, error: { kind: 'bad_request', message: 'source 与 out 必填' } }
      }
      const workers = Math.max(1, Math.min(8, Number(args.workers) || 4))
      const cliArgs = [
        'batch',
        String(args.source),
        '--out', String(args.out),
        '--to', args.format || 'markdown',
        '--type', args.type || 'auto',
        '--workers', String(workers),
      ]
      if (args.recursive) cliArgs.push('--recursive')
      if (args.force) cliArgs.push('--force')
      if (args.pages) cliArgs.push('--pages', String(args.pages))

      log(`[ff_batch] ${cliArgs.join(' ')} (timeoutMs=${timeoutMs})`)
      const res = await runFormatForge({
        cliArgs,
        repoRoot,
        timeoutMs,
        log,
      })
      // CLI batch 输出形如 {ok, code, total, ok_count, ..., results}（顶层 ok/code），
      // 也要把它包成 {ok, code, data:{...}} 契约
      if (res && typeof res === 'object' && 'total' in res) {
        return {
          ok: res.ok !== false,
          code: res.code ?? 200,
          data: {
            source: String(args.source),
            total: res.total,
            ok_count: res.ok_count,
            failed: res.failed ?? 0,
            skipped: res.skipped ?? 0,
            avg_confidence: res.avg_confidence ?? 0,
            elapsed_ms: res.elapsed_ms ?? 0,
            out_dir: res.out_dir ?? String(args.out),
            results: res.results ?? [],
            failures: res.failures ?? [],
          },
        }
      }
      // 错误形态（CLI 直接 emit {ok:false, error:{kind, message}}）
      return res
    },
  })
}