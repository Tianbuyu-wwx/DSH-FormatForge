// tools/_truncate.mjs
//
// v0.13.0/C1: render 层兜底截断（与 Python core/utils.py::smart_truncate 镜像）。
// 抽出共用模块避免 translate.mjs / result.mjs / 未来工具重复实现。
//
// 优先级：段落边界（\n\n）> 行边界（\n）> 硬切。
// 当段落/行边界位置 < cap/2 时回退硬切（避免截得太短）。

/**
 * @param {string} text  输入文本
 * @param {number} cap   最大字符数（截断上限）
 * @returns {string}     截断后的字符串（长度 ≤ cap，按段落/行边界截断）
 */
export function renderTruncate(text, cap) {
  if (text.length <= cap) return text
  let cut = text.lastIndexOf('\n\n', cap)
  if (cut < cap / 2) cut = text.lastIndexOf('\n', cap)
  if (cut <= 0) cut = cap
  return text.slice(0, cut)
}

/**
 * E1-mirror: 段落 > 行 > 硬切；返回 (chunk, nextOffset)。
 * 用于分页场景（与 Python core/utils.py::smart_truncate 行为一致）。
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
  let cut = window.lastIndexOf('\n\n')
  if (cut < maxChars / 2) cut = window.lastIndexOf('\n')
  let chunk, next
  if (cut <= 0) {
    chunk = window
    next = windowEnd
  } else {
    chunk = window.slice(0, cut)
    next = start + cut + 1
    if (next < text.length && text[next] === '\n') next += 1
  }
  return { chunk, nextOffset: next < text.length ? next : undefined }
}
