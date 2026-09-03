// services/inbox-watcher.mjs
//
// FormatForge Inbox — 用户把文件拖进 ~/.dsh/formatforge/inbox/ 即自动转换。
//
// 行为：
//   1. 轮询扫描 inbox（2s 间隔，简单可靠，不依赖 chokidar）。
//   2. 文件稳定检测：连续两次采样 size/mtime 不变才转换（防拖拽半程）。
//   3. 去重：产物 <stem>.ff.json 已存在且比源文件新 → 跳过（重复拖入不发通知）。
//   4. 转换：复用 runFormatForge（translate --format markdown --quality）。
//   5. 产物：<stem>.ff.json（协议 JSON 全文）+ <stem>.ff.md（纯内容）；
//      失败写 <stem>.ff.error.txt。源文件保留不删。
//   6. 每次处理结束回调 onDone(result)，由 index.mjs 决定是否注入会话通知。

import { join, basename, extname } from 'node:path'
import { homedir } from 'node:os'
import { readdirSync, statSync, existsSync, writeFileSync, unlinkSync, readFileSync, appendFileSync, openSync, readSync, closeSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { runFormatForge } from './python-runner.mjs'

const SCAN_INTERVAL_MS = 2_000
const STABLE_CHECK_MS = 700

function ffHome() {
  return process.env.FF_HOME || join(homedir(), '.dsh', 'formatforge')
}

export function inboxDir() {
  return join(ffHome(), 'inbox')
}

/** 支持的扩展名白名单（与 parsers 能力对齐的保守清单；未知扩展交给 CLI 报 unsupported_format）。
 *  v0.13.0/B2: 移除 .doc（无 Python doc 解析器，写 .ff.error.txt 是假阳性）
 */
const KNOWN_EXT = new Set([
  '.pdf', '.docx', '.pptx', '.xlsx', '.xlsm', '.csv', '.txt', '.md', '.markdown',
  '.rtf', '.odt', '.ods', '.odp', '.html', '.htm', '.xml', '.json', '.yaml', '.yml',
  '.toml', '.eml', '.msg', '.epub', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.webp',
  '.bmp', '.tiff', '.zip', '.7z', '.rar', '.srt', '.sql', '.latex', '.tex',
])

function isSupported(name) {
  const ext = extname(name).toLowerCase()
  return KNOWN_EXT.has(ext)
}

/**
 * @param {object} opts
 * @param {string}   opts.repoRoot     FormatForge 仓库根
 * @param {number}   [opts.maxBytes]
 * @param {number}   [opts.timeoutMs]
 * @param {boolean}  [opts.notify]     是否产出通知（index 层决定注入会话）
 * @param {(line:string)=>void} opts.log
 * @param {(result:{file:string, ok:boolean, kind?:string, message?:string,
 *                  parser?:string, confidence?:number, pages?:number,
 *                  jsonPath?:string, mdPath?:string})=>void} opts.onDone
 */
export function createInboxWatcher({ repoRoot, maxBytes = 100 * 1024 * 1024, timeoutMs, log = () => {}, onDone }) {
  const inbox = inboxDir()
  let timer = null
  let busy = false
  // 稳定检测状态表：path -> {size, mtime}
  const pending = new Map()
  // 去重记忆：path -> 处理完成的 mtimeMs（防 watcher 重扫重复触发）
  const doneAt = new Map()

  function ensureDir() {
    for (const d of [ffHome(), inbox]) {
      if (!existsSync(d)) {
        try {
          mkdirp(d)
          log(`[ff-inbox] created ${d}`)
        } catch (e) {
          log(`[ff-inbox] cannot create ${d}: ${e.message}`)
        }
      }
    }
  }

  function mkdirp(d) {
    const fs = process.getBuiltinModule('node:fs')
    fs.mkdirSync(d, { recursive: true })
  }

  function listFiles() {
    try {
      return readdirSync(inbox, { withFileTypes: true })
        .filter((e) => e.isFile())
        .map((e) => e.name)
    } catch {
      return []
    }
  }

  /** 返回需要处理的稳定新文件列表 */
  function scanStable() {
    const stable = []
    const seen = new Set()
    for (const name of listFiles()) {
      seen.add(name)
      if (name.endsWith('.ff.json') || name.endsWith('.ff.md') || name.endsWith('.ff.error.txt')) continue
      if (!isSupported(name)) continue
      const full = join(inbox, name)
      let st
      try {
        st = statSync(full)
      } catch {
        pending.delete(name)
        continue
      }

      // 完成过的文件 mtime 未变 → 跳过
      if (doneAt.get(name) === st.mtimeMs) continue

      // 产物已存在且比源新 → 记 done，跳过（重启后不重做）
      const stem = name.slice(0, -extname(name).length)
      const jsonPath = join(inbox, `${stem}.ff.json`)
      try {
        if (existsSync(jsonPath) && statSync(jsonPath).mtimeMs >= st.mtimeMs) {
          doneAt.set(name, st.mtimeMs)
          continue
        }
      } catch { /* fallthrough */ }

      // 稳定检测：与上次采样比对
      const prev = pending.get(name)
      const sig = `${st.size}:${st.mtimeMs}`
      if (prev === sig) {
        pending.delete(name)
        stable.push({ full, name, size: st.size })
      } else {
        pending.set(name, sig)
      }
    }
    // 清理已消失文件的跟踪状态
    for (const k of [...pending.keys()]) if (!seen.has(k)) pending.delete(k)
    return stable
  }

  async function processOne({ full, name, size }) {
    log(`[ff-inbox] converting ${name} (${size}B)`)
    const stem = name.slice(0, -extname(name).length)
    const jsonPath = join(inbox, `${stem}.ff.json`)
    const mdPath = join(inbox, `${stem}.ff.md`)
    const errPath = join(inbox, `${stem}.ff.error.txt`)

    // 尺寸 clamp
    if (size > maxBytes) {
      const msg = `文件 ${size} 字节超过上限 ${maxBytes}`
      writeFileSync(errPath, `[too_large] ${msg}`)
      onDone?.({ file: name, ok: false, kind: 'too_large', message: msg })
      return
    }

    try { unlinkSync(errPath) } catch { /* none */ }

    const res = await runFormatForge({
      cliArgs: ['translate', full, '--format', 'markdown', '--quality'],
      repoRoot,
      stdinText: null,
      timeoutMs,
      log,
    })

    if (res.ok) {
      writeFileSync(jsonPath, JSON.stringify(res, null, 2))
      const content = String(res.data?.content ?? '')
      writeFileSync(mdPath, content)
      const meta = res.data?.meta || {}
      const enhance = res.data?.enhance && res.data.enhance.needed ? `；enhance=${res.data.enhance.reason}` : ''
      log(`[ff-inbox] done ${name}: parser=${meta.parser}, confidence=${meta.confidence}${enhance}`)
      doneAt.set(name, statSync(full).mtimeMs)
      onDone?.({
        file: name,
        ok: true,
        resultId: meta.result_id || null,
        parser: meta.parser,
        confidence: meta.confidence,
        pages: undefined,
        enhanceReason: res.data?.enhance && res.data.enhance.needed ? res.data.enhance.reason : null,
        jsonPath,
        mdPath,
      })
    } else {
      const kind = res.error?.kind || 'internal'
      const message = res.error?.message || 'unknown error'
      writeFileSync(errPath, `[${kind}] ${message}`)
      log(`[ff-inbox] failed ${name}: ${kind}`)
      doneAt.set(name, statSync(full).mtimeMs)
      onDone?.({ file: name, ok: false, kind, message })
    }
  }

  async function tick() {
    if (busy) return
    busy = true
    try {
      ensureDir()
      enforceRetention()
      const stable = scanStable()
      for (const item of stable) {
        await processOne(item)
      }
    } catch (e) {
      log(`[ff-inbox] tick error: ${e.message}`)
    } finally {
      busy = false
    }
  }

  // ─── E5: TTL 与容量管理（LRU 按 mtime；删除动作合并为一条通知） ───
  const TTL_MS = Number(process.env.FF_INBOX_TTL_DAYS ?? 7) * 86_400_000
  const MAX_BYTES = Number(process.env.FF_INBOX_MAX_MB ?? 500) * 1024 * 1024

  function enforceRetention() {
    if (TTL_MS <= 0 && MAX_BYTES <= 0) return
    let entries = []
    try {
      entries = listFiles().map((name) => {
        const full = join(inbox, name)
        const st = statSync(full)
        return { name, full, mtime: st.mtimeMs, size: st.size }
      })
    } catch { return }

    const doomed = new Set()
    const now = Date.now()
    if (TTL_MS > 0) {
      for (const e of entries) if (now - e.mtime > TTL_MS) doomed.add(e.name)
    }
    // 容量：按 mtime 从旧到新删，直到总量 ≤ MAX_BYTES（排除已判 TTL 过期的）
    if (MAX_BYTES > 0) {
      let total = entries.reduce((s, e) => s + (doomed.has(e.name) ? 0 : e.size), 0)
      for (const e of [...entries].sort((a, b) => a.mtime - b.mtime)) {
        if (total <= MAX_BYTES) break
        if (doomed.has(e.name)) continue
        doomed.add(e.name)
        total -= e.size
      }
    }
    if (doomed.size === 0) return

    // v0.14.0/B-P1-4: TTL 删除前发预览——记录到 .ff.retired.log（含 sha256/path/size/mtime）
    // 目的：用户清理后能找回历史产物 hash；运维也能审计清理动作。
    const retiredLogPath = join(inbox, '.ff.retired.log')
    const retiredEntries = []
    const removed = []
    for (const name of doomed) {
      try {
        const full = join(inbox, name)
        const stat = statSync(full)
        // v0.14.0/audit: 用 openSync + readSync 限前 64KB，避免大文件全量加载到内存
        const fd = openSync(full, 'r')
        let sample
        try {
          const buf = Buffer.alloc(65536)
          const bytesRead = readSync(fd, buf, 0, 65536, 0)
          sample = buf.subarray(0, bytesRead)
        } finally {
          closeSync(fd)
        }
        const hash = createHash('sha256').update(sample).digest('hex')
        const entry = {
          ts: new Date().toISOString(),
          name,
          path: full,
          size: stat.size,
          mtime_iso: new Date(stat.mtimeMs).toISOString(),
          sha256: hash,
          hash_note: sample.length < stat.size ? 'first 64KB only' : 'full content',
        }
        retiredEntries.push(entry)
        unlinkSync(full)
        removed.push(name)
        doneAt.delete(name)
      } catch { /* 已被并发删除等场景 */ }
    }

    // 写 .ff.retired.log（append，避免覆盖历史清理记录）
    if (retiredEntries.length > 0) {
      try {
        const lines = retiredEntries.map((e) => JSON.stringify(e)).join('\n') + '\n'
        appendFileSync(retiredLogPath, lines, 'utf-8')
        log(`[ff-inbox] retention: wrote ${retiredEntries.length} entry(s) to .ff.retired.log`)
      } catch (e) {
        log(`[ff-inbox] retention: failed to write .ff.retired.log: ${e.message}`)
      }
    }
    if (removed.length > 0) {
      log(`[ff-inbox] retention: removed ${removed.length} file(s)`)
      onDone?.({ file: removed.join(', '), ok: true, retention: true, count: removed.length })
    }
  }

  return {
    start() {
      ensureDir()
      // 首轮立即把「已有产物」的文件记为 done（重启不重放历史）
      try {
        for (const name of listFiles()) {
          if (isSupported(name)) {
            const st = statSync(join(inbox, name))
            const stem = name.slice(0, -extname(name).length)
            const jp = join(inbox, `${stem}.ff.json`)
            if (existsSync(jp) && statSync(jp).mtimeMs >= st.mtimeMs) doneAt.set(name, st.mtimeMs)
          }
        }
      } catch { /* noop */ }
      timer = setInterval(tick, SCAN_INTERVAL_MS)
      log(`[ff-inbox] watching ${inbox}`)
    },
    stop() {
      if (timer) clearInterval(timer)
      timer = null
    },
    get dir() {
      return inbox
    },
  }
}
