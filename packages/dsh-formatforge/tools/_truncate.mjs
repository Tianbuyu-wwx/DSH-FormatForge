// tools/_truncate.mjs
//
// v0.13.0/C1: render 层兜底截断（与 Python core/utils.py::smart_truncate 镜像）。
// 抽出共用模块避免 translate.mjs / result.mjs / 未来工具重复实现。
//
// v0.14.0/B-P1-7: 优先级
//   --- 多文件分隔符（translate.mjs 多文件拼接模式）> 段落（\n\n）> 行（\n）> 硬切
// --- 分隔符保护多文件拼接时不被切在某个文件标题中间。
//
// 当最弱边界 < cap/2 时回退下一级（避免截得太短）。

/**
 * @param {string} text  输入文本
 * @param {number} cap   最大字符数（截断上限）
 * @returns {string}     截断后的字符串（长度 ≤ cap，按 ---/段落/行边界截断）
 */
export function renderTruncate(text, cap) {
  if (text.length <= cap) return text
  // v0.14.0/B-P1-7: --- 多文件分隔符为最强边界（不应用 cap/2 阈值）
  let cut = text.lastIndexOf('\n\n---\n\n', cap)
  if (cut < 0) cut = text.lastIndexOf('\n\n', cap)
  if (cut < cap / 2) cut = text.lastIndexOf('\n', cap)
  if (cut <= 0) cut = cap
  return text.slice(0, cut)
}

/**
 * v0.14.0/B-P1-7: E1-mirror + 多文件分隔符保护。
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
  // v0.14.0/B-P1-7: --- 多文件分隔符为最强边界——找到就用，不应用 cap/2 阈值
  let cut = window.lastIndexOf('\n\n---\n\n')
  if (cut < 0) {
    // 没找到 --- → 走原有逻辑
    cut = window.lastIndexOf('\n\n')
    if (cut < maxChars / 2) cut = window.lastIndexOf('\n')
  }
  let chunk, next
  if (cut <= 0) {
    chunk = window
    next = windowEnd
  } else {
    chunk = window.slice(0, cut)
    next = start + cut + 1
    // --- 分隔符含 7 个换行（\n\n---\n\n）→ 跳过整个分隔符
    if (text.startsWith('\n\n---\n\n', start + cut)) {
      next = start + cut + 7
    } else if (next < text.length && text[next] === '\n') {
      next += 1
    }
  }
  return { chunk, nextOffset: next < text.length ? next : undefined }
}
