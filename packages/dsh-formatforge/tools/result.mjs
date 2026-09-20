// tools/result.mjs
//
// ff_result — consume inbox artifacts without knowing file paths.
//   list mode : scan ~/.dsh/formatforge/inbox for .ff.json, return metadata rows.
//   fetch mode: given `id` (result_id prefix or file stem), return forged content
//               with smart pagination (E1 semantics).
// Security: reads confined to inbox; path traversal in `id` rejected.
//
// DSL contract (dsh-tools): parameters = flat value-schema; output = { schema, render }.

import { defineTool } from '@deepseek-ai/dsh-tools'
import { join, basename } from 'node:path'
import { readdirSync, readFileSync, statSync, openSync, readSync, closeSync } from 'node:fs'
import { inboxDir } from '../services/inbox-watcher.mjs'
import { smartTruncate } from './_truncate.mjs'

const DEFAULT_MAX_CHARS = 12_000
/** 小产物整段解析的上限；更大的产物改用流式扫描（不把正文读进内存） */
const SMALL_ARTIFACT_BYTES = 64 * 1024
/** 大产物流式扫描的块大小（同一块 Buffer 复用，内存占用与产物大小无关） */
const SCAN_CHUNK_BYTES = 64 * 1024
/** meta 对象的收集上限——超过就当它不是协议 meta，绝不无界缓冲 */
const META_CAPTURE_BYTES = 64 * 1024
/** 键 token 的收集上限（协议键都是短名；超长字符串一律不当键看） */
const KEY_TOKEN_BYTES = 64
/** T2-5/audit：顶层 `"ok"` 字面量的收集上限。协议里它只可能是 `true`/`false`，
 *  8 字节绰绰有余；这是扫描器里最后一个没有上限的缓冲区，不设限就等于
 *  「内存边界与产物大小无关」这条自述的反例（`{"ok":` + 100MB 无终止字面量
 *  能在活着的 harness 进程里缓冲 100MB，实测 8MB 字面量 → 256MB 堆）。 */
const OK_LITERAL_BYTES = 8

/** v0.13.0: 截断逻辑已抽到 _truncate.mjs 共用；smartTruncate 由该模块导入（与 core/utils.py::smart_truncate 镜像） */

/**
 * 读产物的协议元数据（JS-H1b：顺带给出「是不是合法转换结果」的判定）。
 * 返回 {valid, meta, enhance}；不可读/不可解析返回 null。
 */
function readArtifactMeta(full, size) {
  if (size <= SMALL_ARTIFACT_BYTES) {
    let doc
    try {
      doc = JSON.parse(readFileSync(full, { encoding: 'utf8' }))
    } catch {
      return null
    }
    const data = doc?.data || {}
    const meta = data.meta || {}
    return { valid: doc?.ok === true && typeof data.content === 'string' && !!meta.result_id, meta, enhance: data.enhance || null }
  }
  // 大产物：流式扫描，只把 meta / enhance 这两个小对象本身读进内存。
  // （旧实现读尾部 4KB 猜 meta —— 协议键序是 content → format → meta →
  //   structured_data → quality → enhance，meta 排第三：正文一大、meta 就离尾部很远，
  //   structured_data/quality 一超过 4KB 尾窗里就没有 result_id，真产物会被判成伪造。）
  // T3-1：enhance 此前在这里被硬编码成 null —— 于是 `ff_result list` 对**任何**
  // > 64KB 的产物都不显示 `⚠enhance=…`，偏偏最需要增强的就是这些大文档。
  // null 在渲染层读作「不需要增强」，而不是「不知道」，所以这是会误导模型的缺省。
  const scanned = scanEnvelopeHead(full)
  if (!scanned) return null
  const meta = scanned.meta || {}
  return {
    valid: scanned.ok === true && scanned.contentIsString === true && !!meta.result_id,
    meta,
    enhance: scanned.enhance || null,
  }
}

/**
 * 顺序扫描产物，返回 {ok, contentIsString, meta, enhance}；读不动返回 null。
 *
 * 为什么不是「找 "meta" 子串」：正文里可以出现任何字节，只有带引号/转义状态的
 * 结构化扫描才能区分「键」和「正文里的同名文本」。为什么不是整段 JSON.parse：
 * 产物可以到上百 MB，list 会对收件箱里每一份都做这件事。
 *
 * 内存边界：一块复用的 64KB 读缓冲 + ≤64B 的键 token + ≤8B 的 ok 字面量 +
 * ≤64KB 的对象收集区（meta / enhance 复用同一块，两者不会同时在收）。
 * 与产物大小无关；代价是顺序 I/O（meta 之前的正文必须读过去，但不驻留）。
 * 停止条件不预设键序：`ok`/`content`/`meta` 三项齐了就停；不齐就一路扫到信封闭合
 * （T3-3：旧代码只看 `meta`+`content`，`ok` 不在停止条件里，而兜底又停在 `data` 闭合
 *  —— 一旦 `ok` 排在 `data` 之后，每一份大产物都会被判成 `ok:false`，正是这个扫描器
 *  当初要消灭的「假设键序」。注释宣称的保证必须由代码兑现，不是反过来）。
 */
function scanEnvelopeHead(full) {
  let fd
  try {
    fd = openSync(full, 'r')
  } catch {
    return null
  }
  const buf = Buffer.alloc(SCAN_CHUNK_BYTES)
  let filePos = 0
  let depth = 0
  let inString = false
  let trailingBackslashes = 0 // 跨块的连续反斜杠数（判断块首引号是否被转义）
  const tokenBuf = Buffer.alloc(KEY_TOKEN_BYTES)
  let tokenLen = 0
  let tokenOverflow = false
  let lastToken = null // 最近一个完整的（短）字符串 token
  const keyAt = [] // keyAt[d] = 第 d 层当前正在赋值的键
  let okLiteral = null // 读到 `"ok":` 之后收集字面量
  let ok = false
  let okSeen = false // 顶层 `ok` 的值是否真的读到过（T3-3：停止条件要求它）
  let contentIsString = false
  let capturing = false
  let captureTarget = null // 'meta' | 'enhance'：当前正在收集的是哪个对象
  let captureOverflow = false
  let captureBaseDepth = 0
  let captureStart = -1
  let captureParts = []
  let captureLen = 0
  let meta = null
  let metaSeen = false
  let enhance = null // T3-1：与 meta 同一套机制收集（两者不会同时在收）
  let enhanceSeen = false
  let done = false
  /** T2-5：`ok` 字面量越界 —— 信封不是协议产物（或已损坏），整份判为读不动 */
  let malformed = false

  const flushCapture = (endExclusive) => {
    if (!capturing || captureStart < 0) return
    if (captureOverflow) {
      captureStart = -1
      return
    }
    const part = Buffer.from(buf.subarray(captureStart, endExclusive))
    captureStart = -1
    captureLen += part.length
    if (captureLen > META_CAPTURE_BYTES) {
      // 协议的 meta/enhance 不可能这么大 → 停止收集（内存边界优先），但**继续跟到
      // 闭合**：这样 enhance 才能如实报成 unknown，而不是退回 null（= 不需要增强）。
      captureOverflow = true
      captureParts = []
      captureLen = 0
      return
    }
    captureParts.push(part)
  }

  try {
    while (!done) {
      const read = readSync(fd, buf, 0, SCAN_CHUNK_BYTES, filePos)
      if (read <= 0) break
      filePos += read
      if (capturing) captureStart = 0
      // T3-2/audit：只在**本次真正读进来**的 [0, read) 里找引号。`buf` 是复用的
      // 64KB 块且不清零：短读（截断产物，或 watcher 非原子写到一半的产物）之后，
      // [read, 64KB) 还留着上一块的字节。在那里匹配到一个陈旧引号，会让扫描器
      // 认为字符串已闭合并从一个并不存在的偏移继续 —— 截断产物的正确结论是
      // 「按读到的字节判」，而不是「按上一块的残留判」。
      const nextQuote = (from) => {
        const at = buf.indexOf(0x22, from)
        return at === -1 || at >= read ? -1 : at
      }
      let i = 0
      while (i < read) {
        if (inString) {
          // 跳到下一个未转义的引号；正文字符串在这里被整段跳过（不驻留）
          let q = nextQuote(i)
          while (q !== -1) {
            let bs = 0
            let k = q - 1
            while (k >= 0 && buf[k] === 0x5c) {
              bs++
              k--
            }
            if (k < 0) bs += trailingBackslashes
            if (bs % 2 === 0) break
            q = nextQuote(q + 1)
          }
          const end = q === -1 ? read : q
          if (!tokenOverflow) {
            const room = KEY_TOKEN_BYTES - tokenLen
            const take = Math.min(room, end - i)
            buf.copy(tokenBuf, tokenLen, i, i + take)
            tokenLen += take
            if (end - i > take) tokenOverflow = true
          }
          if (q === -1) {
            i = read
            break
          }
          lastToken = tokenOverflow ? null : tokenBuf.subarray(0, tokenLen).toString('utf8')
          inString = false
          i = q + 1
          continue
        }
        const c = buf[i]
        if (c === 0x22) {
          // 字符串开始；`data.content` 必须是字符串（与 fetchOne 的校验对齐）
          if (depth === 2 && keyAt[1] === 'data' && keyAt[2] === 'content') contentIsString = true
          inString = true
          tokenLen = 0
          tokenOverflow = false
          i++
          continue
        }
        if (c === 0x7b || c === 0x5b) {
          if (!capturing && c === 0x7b && depth === 2 && keyAt[1] === 'data') {
            if (keyAt[2] === 'meta' && !metaSeen) captureTarget = 'meta'
            else if (keyAt[2] === 'enhance' && !enhanceSeen) captureTarget = 'enhance'
            if (captureTarget) {
              capturing = true
              captureOverflow = false
              captureBaseDepth = depth
              captureStart = i
              captureParts = []
              captureLen = 0
            }
          }
          depth++
          keyAt[depth] = null
          i++
          continue
        }
        if (c === 0x7d || c === 0x5d) {
          if (okLiteral !== null) {
            ok = okLiteral === 'true'
            okLiteral = null
            okSeen = true
          }
          depth--
          if (capturing && depth === captureBaseDepth) {
            flushCapture(i + 1)
            let parsed = null
            if (!captureOverflow) {
              try {
                const value = JSON.parse(Buffer.concat(captureParts).toString('utf8'))
                if (value && typeof value === 'object') parsed = value
              } catch { /* 不可解析 → 当没读到 */ }
            }
            if (captureTarget === 'meta') {
              metaSeen = true
              meta = parsed
            } else {
              enhanceSeen = true
              // T3-1：读到了 enhance 却收不进内存边界 → 如实报 unknown。
              // 退回 null 会被渲染成「没有增强提示」，那是把「不知道」说成「不需要」。
              enhance = parsed || (captureOverflow ? { reason: 'unknown' } : null)
            }
            capturing = false
            captureTarget = null
            captureOverflow = false
            captureParts = []
            captureLen = 0
          }
          i++
          // 协议键序（ok → code → data{content → format → meta}）下三项在 meta 闭合时
          // 就都齐了 → 正常产物照旧扫到 meta 即止。
          // T3-3：`ok` 必须在停止条件里。旧代码只要 `meta`+`content` 就停，兜底又停在
          // `data` 闭合 —— 两条路径都可能在读到 `ok` 之前收工，只要 `ok` 排在 `data`
          // 之后，每份大产物都会被判成 `ok:false`（正是这段代码当初要消灭的
          // 「⚠非转换产物」误报）。缺 `ok` 就一路扫到**信封**闭合，代价只是多读一段
          // 顺序 I/O，内存不变。
          if (okSeen && metaSeen && contentIsString && enhanceSeen) {
            done = true
            break
          }
          if (depth <= 0) {
            done = true
            break
          }
          // `data` 闭合 → enhance 不可能再出现（它是 data 的成员），此时 null
          // 就是「这份产物没有 enhance 块」的准确答案。
          if (depth === 1 && keyAt[1] === 'data' && okSeen) {
            done = true
            break
          }
          continue
        }
        if (c === 0x3a) {
          keyAt[depth] = lastToken
          if (depth === 1 && lastToken === 'ok') okLiteral = ''
          lastToken = null
          i++
          continue
        }
        if (c === 0x2c) {
          if (okLiteral !== null) {
            ok = okLiteral === 'true'
            okLiteral = null
            okSeen = true
          }
          keyAt[depth] = null
          lastToken = null
          i++
          continue
        }
        if (okLiteral !== null && c > 0x20) {
          // T2-5：越界就地判非法，绝不继续累积。注意不能「只是停止累积」——
          // 那样 okLiteral 会停在一个被截断的值上，扫描器等于**猜**出了一个
          // ok（几乎必然是 false），与真·`ok:false` 信封无法区分。
          if (okLiteral.length >= OK_LITERAL_BYTES) {
            malformed = true
            done = true
            break
          }
          okLiteral += String.fromCharCode(c)
        }
        i++
      }
      if (!done) {
        flushCapture(read)
        // 块尾的连续反斜杠要带到下一块，否则块首引号的转义状态会判错
        let bs = 0
        while (bs < read && buf[read - 1 - bs] === 0x5c) bs++
        trailingBackslashes = bs === read ? trailingBackslashes + bs : bs
      }
    }
  } catch {
    return null
  } finally {
    try {
      closeSync(fd)
    } catch { /* ignore */ }
  }
  // T2-5：与小产物快路径一致 —— `JSON.parse` 失败同样返回 null（读不动 ≠ ok:false）
  if (malformed) return null
  return { ok, contentIsString, meta, enhance }
}

function listArtifacts() {
  const dir = inboxDir()
  let names
  try {
    names = readdirSync(dir)
  } catch {
    return []
  }
  const rows = []
  for (const name of names) {
    if (!name.endsWith('.ff.json')) continue
    const full = join(dir, name)
    try {
      const st = statSync(full)
      // round-1 H1 协议：成功信封 {ok, code, data:{content, format, meta:{parser, file_size, result_id, confidence}}}
      // 源文件名不入协议——由产物文件名承载（`foo.pdf.ff.json` → 源 `foo.pdf`）
      const info = readArtifactMeta(full, st.size)
      if (!info) continue
      const meta = info.meta || {}
      const stem = name.replace(/\.ff\.json$/, '')
      rows.push({
        id: meta.result_id || stem,
        file: name,
        source: stem,
        parser: meta.parser || '?',
        confidence: typeof meta.confidence === 'number' ? meta.confidence : null,
        file_size: typeof meta.file_size === 'number' ? meta.file_size : null,
        enhance: info.enhance?.reason || null,
        valid: info.valid === true,
        forged_at: st.mtime.toISOString(),
        size_bytes: st.size,
        path: full,
      })
    } catch { /* concurrent delete etc. */ }
  }
  return rows.sort((a, b) => b.forged_at.localeCompare(a.forged_at))
}

export function createResultTool({ log = () => {} }) {
  return defineTool({
    name: 'ff_result',
    description: '查 FormatForge 收件箱产物。list=true 列出；id/ids 取回内容（可分页）。',
    parameters: {
      list: { type: 'boolean', default: false, description: '列出全部产物。' },
      id: { type: 'string', description: '单取回：result_id/文件名前缀。' },
      ids: { type: 'string', description: '批量：id 逗号分隔（≤20）。' },
      max_chars: { type: 'integer', default: DEFAULT_MAX_CHARS, description: '分页大小。' },
      offset: { type: 'integer', default: 0 },
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
          return [{ type: 'text', text: `ff_result 失败 [${value.error.kind}]: ${value.error.message}` }]
        }
        const d = (value && value.data) || {}
        // R3.2: 批量结果渲染
        if (d.batch) {
          const parts = d.results.map((r) => {
            if (!r.ok) return `- ❌ ${r.error?.message || '失败'}`
            const rd = r.data
            const enh = rd.enhance?.needed ? ` ⚠enhance=${rd.enhance.reason}` : ''
            const trunc = rd.truncated ? `（已截断，续读 offset=${rd.next_offset}）` : ''
            return `- [${rd.id}] ${rd.source} (parser=${rd.parser}, confidence=${rd.confidence ?? '?'}${enh})${trunc}\n${rd.content}`
          })
          return [
            {
              type: 'text',
              text: `FormatForge 批量取回 ${d.ok_count}/${d.count} 份：\n\n${parts.join('\n\n---\n\n')}`,
            },
          ]
        }
        if (d.count !== undefined) {
          if (d.count === 0) return [{ type: 'text', text: 'FormatForge 收件箱当前为空。把文件拖进网页即可自动锻造。' }]
          const lines = d.items.map(
            (it) =>
              `- [${it.id}] ${it.source} (parser=${it.parser}, confidence=${it.confidence ?? '?'}` +
              `${it.enhance ? `, ⚠enhance=${it.enhance}` : ''}, ${Math.round(it.size_bytes / 1024)}KB, ${it.forged_at})` +
              `${it.valid === false ? ' ⚠非转换产物（伪造/损坏，取回会被拒）' : ''}`,
          )
          return [{ type: 'text', text: `FormatForge 收件箱共 ${d.count} 个产物：\n${lines.join('\n')}\n\n用 ff_result(id=...) 取回内容。` }]
        }
        const enh = d.enhance?.needed ? `\n[enhance:${d.enhance.reason}] ${d.enhance.hint}` : ''
        const pageNote = d.truncated ? `\n\n[已截断；继续读取请带 offset=${d.next_offset}]` : ''
        return [
          {
            type: 'text',
            text:
              `FormatForge 产物 ${d.id} (${d.source}, parser=${d.parser}, confidence=${d.confidence ?? '?'})\n` +
              `可读版：${d.md_path}\n\n${d.content}${enh}${pageNote}`,
          },
        ]
      },
    },
    async execute(args) {
      const wantList = args.list || (!args.id && !args.ids)
      if (wantList) {
        const items = listArtifacts()
        log(`[ff_result] listed ${items.length} artifact(s)`)
        return { ok: true, code: 200, data: { count: items.length, items } }
      }

      // R3.2: 批量模式 —— ids 逗号分隔，逐份复用单取回逻辑
      if (args.ids && String(args.ids).trim()) {
        const ids = String(args.ids)
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
          .slice(0, 20)
        if (ids.length === 0) {
          return { ok: false, code: 4003, error: { kind: 'bad_request', message: 'ids 为空' } }
        }
        const results = []
        for (const oneId of ids) {
          results.push(await fetchOne(oneId, args, log))
        }
        const okCount = results.filter((r) => r.ok).length
        log(`[ff_result] batch fetched ${okCount}/${ids.length}`)
        return { ok: true, code: 200, data: { batch: true, count: ids.length, ok_count: okCount, results } }
      }

      return await fetchOne(String(args.id), args, log)
    },
  })
}

/** 单份取回（id 解析 + 路径安全 + 分页），单/批量共用。 */
async function fetchOne(rawId, args, log) {
  // 路径安全：id 不允许分隔符与 ..
  if (/[/\\]|\.\./.test(rawId)) {
    return { ok: false, code: 4003, error: { kind: 'bad_request', message: '非法 id：不允许路径分隔符或 ..' } }
  }
  const dir = inboxDir()
  let target = null
  try {
    const names = readdirSync(dir).filter((n) => n.endsWith('.ff.json'))
    // v0.13.0/C6: 删 includes() 兜底（id="abc" 会命中 xxxabcxxx.ff.json 是误匹配）
    // 四段递进：旧式精确 stem（foo.ff.json）→ 新式精确 stem（foo.pdf.ff.json，含源扩展名）
    //          → 源 stem 前缀（foo → foo.pdf）→ JSON 头里的 result_id（精确，再 8 位以上前缀）
    const stemOf = (n) => n.replace(/\.ff\.json$/, '')
    target =
      names.find((n) => n === `${rawId}.ff.json`) ||
      names.find((n) => stemOf(n) === rawId) ||
      names.find((n) => stemOf(n).startsWith(`${rawId}.`)) ||
      null
    if (!target && names.length > 0) {
      let idPrefixHit = null
      for (const n of names) {
        try {
          const np = join(dir, n)
          const info = readArtifactMeta(np, statSync(np).size)
          const rid = info?.meta?.result_id
          if (!rid) continue
          // 精确匹配协议里的 result_id（唯一写入方 inbox-watcher 存的是 CLI 信封逐字拷贝）
          if (rid === rawId) {
            target = n
            break
          }
          if (!idPrefixHit && rawId.length >= 8 && rid.startsWith(rawId)) idPrefixHit = n
        } catch { /* skip */ }
      }
      if (!target && idPrefixHit) target = idPrefixHit
    }
  } catch {
    target = null
  }
  if (!target) {
    return {
      ok: false,
      code: 4002,
      error: { kind: 'file_not_found', message: `收件箱中找不到匹配 "${rawId}" 的产物（可先 list=true 查看）。` },
    }
  }

  const full = join(dir, target)
  let doc
  try {
    doc = JSON.parse(readFileSync(full, { encoding: 'utf8' }))
  } catch (e) {
    return { ok: false, code: 4004, error: { kind: 'parse_failed', message: `产物损坏无法解析: ${e.message}` } }
  }
  const data = doc.data || {}
  const meta = data.meta || {}
  // JS-H1b 信任边界：`.json` 是上传白名单扩展名 → 任何人（或页面）都能伪造
  // `anything.ff.json` 丢进收件箱。只认 round-1 成功信封（ok:true + string content
  // + meta.result_id）；其余一律拒绝，绝不把原始文件字节当「转换结果」端给模型。
  if (doc.ok !== true || typeof data.content !== 'string' || !meta.result_id) {
    return {
      ok: false,
      code: 4005,
      error: {
        kind: 'not_a_conversion_result',
        message: `产物 ${basename(target)} 不是合法的转换结果（需 ok:true + content + meta.result_id）——已拒绝返回。`,
      },
    }
  }
  const content = data.content
  // 参数归一：0/负数/非数回落到默认（`max_chars: 0` 在调用方=未指定），非整数向下取整
  const rawMax = Number(args.max_chars)
  const maxChars = Number.isFinite(rawMax) && rawMax > 0 ? Math.floor(rawMax) : DEFAULT_MAX_CHARS
  const start = Math.max(0, Math.floor(Number(args.offset) || 0))
  const { chunk, nextOffset } = smartTruncate(content, maxChars, start)

  log(`[ff_result] fetched ${target} (${chunk.length} chars @${start})`)
  return {
    ok: true,
    code: 200,
    data: {
      id: meta.result_id || target.replace(/\.ff\.json$/, ''),
      file: basename(target),
      source: target.replace(/\.ff\.json$/, ''),
      parser: meta.parser || '?',
      confidence: typeof meta.confidence === 'number' ? meta.confidence : null,
      file_size: meta.file_size ?? null,
      enhance: data.enhance || null,
      md_path: full.replace(/\.ff\.json$/, '.ff.md'),
      content: chunk,
      truncated: nextOffset !== undefined,
      next_offset: nextOffset,
    },
  }
}
