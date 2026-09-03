// packages/dsh-formatforge/tools/_truncate.mjs
//
// v0.13.0/E1: 抽出 smartTruncate + renderTruncate 共用模块，
// 与 Python 端 core/utils.py::smart_truncate 行为镜像。
//
// v0.14.0/B-P1-7: --- 多文件分隔符（translate.mjs 多文件拼接）> 段落（\n\n）> 行（\n）> 硬切
// --- 分隔符保护多文件拼接时不被切在某个文件标题中间。
//
// v0.14.0/audit: 加入 <!-- ff-file-sep --> 多文件分隔符——比 --- 更稳，
// 因为 markdown --- 水平线（含 --- 第 N 页 ---）会与多文件 --- 模式冲突。
//
// 用法：
//   import { renderTruncate, smartTruncate } from './_truncate.mjs'

/**
 * Render-time 截断（最弱保证——只按 maxChars 长度硬切）。
 * 用于 result.mjs 渲染 stage 的输出超长控制。
 *
 * @param {string} text
 * @param {number} maxChars
 * @returns {{content: string, truncated: boolean}}
 */
export function renderTruncate(text, maxChars) {
  if (!text || text.length <= maxChars) {
    return { content: text || '', truncated: false }
  }
  return { content: text.slice(0, maxChars), truncated: true }
}

// 多文件分隔符：v0.14.0/B-P1-7 加入 --- 多文件分隔符；v0.14.0/audit 加入 <!-- ff-file-sep -->
// 优先按分隔符数组找（前者优先级更高）；找到就用，不应用 cap/2 阈值
const FILE_SEPARATORS = ['<!-- ff-file-sep -->', '\n\n---\n\n']

/**
 * v0.14.0/B-P1-7 + audit: E1-mirror + 多文件分隔符保护。
 * 优先级：--- 多文件 > 段落 > 行 > 硬切。
 *
 * @param {string} text
 * @param {number} maxChars
 * @param {number} [start=0]
 * @returns {{chunk: string, nextOffset: number | undefined}}
 */
export function smartTruncate(text, maxChars, start = 0) {
  if (start >= text.length) return { chunk: '', nextOffset: undefined }
  const windowEnd = Math.min(start + maxChars, text.length)
  if (windowEnd === text.length) return { chunk: text.slice(start), nextOffset: undefined }
  const window = text.slice(start, windowEnd)
  // v0.14.0/B-P1-7 + audit: 多文件分隔符为最强边界——找到就用，不应用 cap/2 阈值
  let cut = -1
  let sepLen = 0
  for (const sep of FILE_SEPARATORS) {
    const idx = window.lastIndexOf(sep)
    if (idx >= 0 && (cut < 0 || idx > cut)) {
      cut = idx
      sepLen = sep.length
    }
  }
  if (cut < 0) {
    // 没找到多文件分隔符 → 走原有逻辑（段落 > 行 > 硬切）
    cut = window.lastIndexOf('\n\n')
    sepLen = 2 // "\n\n"
    if (cut < maxChars / 2) {
      cut = window.lastIndexOf('\n')
      sepLen = 1 // "\n"
    }
  }
  let chunk, next
  if (cut <= 0) {
    chunk = window
    next = windowEnd
  } else {
    chunk = window.slice(0, cut)
    next = start + cut + sepLen
  }
  return { chunk, nextOffset: next < text.length ? next : undefined }
}