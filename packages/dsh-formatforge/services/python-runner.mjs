// services/python-runner.mjs
//
// FormatForge Python runner.
// Resolves the interpreter, spawns `python -m formatforge <args>` (argv array,
// never a shell), enforces the timeout by killing the whole process tree, and
// parses the single-line protocol JSON from stdout:
//   { ok: true,  code, data } | { ok: false, code, error: { kind, message } }
//
// Protocol contract lives in the repo's PLUGIN_PLAN.md §4.3 — keep both in sync.

import { spawn } from 'node:child_process'
import { existsSync, statSync } from 'node:fs'
import { join, sep } from 'node:path'
import { homedir, platform } from 'node:os'

const IS_WIN = platform() === 'win32'

export const DEFAULT_TIMEOUT_MS = 120_000

/**
 * T3-5: V8 的单个字符串最大长度（64 位平台）= 2^29 - 24 = 536,870,888。
 * 超过它的字符串化会抛 RangeError: Invalid string length。
 */
export const V8_MAX_STRING_LENGTH = 536_870_888

/**
 * stdout 硬上限（审计 medium：此前无上限）；100MB 输入的正常信封远低于此值。
 *
 * T3-5: 此前是 512MB = 536,870,912 —— 比 V8 上限**大 24 字节**。旧的
 * `stdout += d` 是边收边拼字符串的，所以 ASCII 为主的输出会在上限触发**之前**
 * 于 'data' 处理器里同步抛 RangeError（emit 里的同步抛出不会路由给 'error'
 * 监听器）：守卫被它本要防住的崩溃抢了先。取 256MB，稳稳低于 V8 上限。
 */
export const DEFAULT_MAX_STDOUT_BYTES = 256 * 1024 * 1024

/**
 * T3-5: 解析生效的 stdout 上限，并夹到 V8 上限以下。
 * FF_MAX_STDOUT_BYTES 是外部旋钮，允许它超过 V8 上限就等于把这个缺陷放回来。
 */
export function resolveStdoutCap(env = process.env) {
  const configured = Number(env.FF_MAX_STDOUT_BYTES)
  const wanted = configured > 0 ? configured : DEFAULT_MAX_STDOUT_BYTES
  return Math.min(wanted, V8_MAX_STRING_LENGTH)
}
const MIN_PYTHON = [3, 10]

// ─── JS-H7: 子进程环境白名单 ───
// 此前子进程继承**整台机器**的 process.env（provider key / session token / 无关项目
// 的路径都会进 Python 子进程）。转换器真正需要的只有：解释器与 DLL 加载
// （PATH/SYSTEMROOT/WINDIR/COMSPEC/PATHEXT）、临时文件（TEMP/TMP，OCR 与 pdf 解析器
// 用 tempfile）、家目录（USERPROFILE/HOME —— output_guard 的 expanduser）、
// Tesseract 探测（LOCALAPPDATA）、locale/时区，以及 FormatForge 自己的旋钮
// （FF_*：FF_MAX_BYTES / FF_TIMEOUT_S / FF_OUTPUT_ROOT / FF_CACHE_* …）与 PYTHON* 参数。
const ENV_ALLOWLIST = new Set([
  'PATH', 'Path', 'PATHEXT', 'SYSTEMROOT', 'SystemRoot', 'WINDIR', 'COMSPEC', 'SystemDrive',
  'TEMP', 'TMP', 'LOCALAPPDATA', 'APPDATA', 'ProgramData', 'PROGRAMFILES', 'PROGRAMFILES(X86)',
  'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'HOME',
  'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ',
])

/** JS-H7: 构造子进程环境（导出以便测试环境策略本身）。 */
export function buildChildEnv(repoRoot) {
  const env = {}
  for (const [key, value] of Object.entries(process.env)) {
    if (value === undefined) continue
    if (ENV_ALLOWLIST.has(key) || key.startsWith('FF_') || key.startsWith('PYTHON')) env[key] = value
  }
  env.PYTHONPATH = repoRoot
  env.PYTHONIOENCODING = 'utf-8'
  env.PYTHONUTF8 = '1'
  return env
}

/**
 * JS-H7/M1: stderr 只在错误信封里保留「异常类 + 最后一行」——完整 traceback 会连同
 * 路径/环境细节进入模型读到的工具结果。控制字符一并剥离。
 */
export function summarizeStderr(stderr, max = 300) {
  const lines = String(stderr || '')
    .split(/\r?\n/)
    .map((l) => l.replace(/[\u0000-\u001f\u007f-\u009f]/g, ' ').trim())
    .filter(Boolean)
  if (lines.length === 0) return ''
  const exc = [...lines].reverse().find((l) => /^[A-Za-z_][\w.]*(Error|Exception|Warning|Interrupt|Exit)\b/.test(l))
  const last = lines[lines.length - 1]
  const summary = exc && exc !== last ? `${exc} | ${last}` : last
  return summary.length > max ? `${summary.slice(0, max)}…` : summary
}

/**
 * T1-1: stdout 必须按**字节**累积、结束时一次性解码。
 *
 * 旧实现是 `stdout += d`：每个 Buffer chunk 被**独立**强制转成字符串，跨 chunk
 * 边界的多字节 UTF-8 序列于是各自解成 U+FFFD。协议 JSON 仍能 parse，内容却已
 * 静默损坏——这是每一次转换（ff_translate / ff_batch / ff_diff / inbox watcher）
 * 内容必经的唯一通路，而 watcher 会把损坏文本落盘进 .ff.json/.ff.md。
 *
 * 上限仍按**字节**计（chunk.length），与 FF_MAX_BYTES 同一量纲；超限的 chunk
 * 不再入列，由调用方终止子进程。
 *
 * @param {number} capBytes 累积上限（字节）
 */
export function createStdoutCollector(capBytes) {
  /** @type {Buffer[]} */
  const parts = []
  let bytes = 0
  let overflow = false
  return {
    /** @param {Buffer|string} chunk @returns {boolean} false = 超限（chunk 被丢弃） */
    push(chunk) {
      const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), 'utf8')
      bytes += buf.length
      if (bytes > capBytes) {
        overflow = true
        return false
      }
      parts.push(buf)
      return true
    },
    get bytes() { return bytes },
    get overflow() { return overflow },
    /** 一次性解码：只有到这里字节流才成为字符串。 */
    text() { return Buffer.concat(parts).toString('utf8') },
  }
}

/**
 * T1-7: stderr 按字节累积，并只在消费时一次性 UTF-8 解码。
 *
 * 保留窗口明确以**字节**为单位：超过 64,000 字节时只保留最后 32,000
 * 字节，以继续限制错误日志的内存占用。保留点会跳过 UTF-8 continuation
 * bytes，避免截断本身在日志开头制造 U+FFFD。
 *
 * @param {number} highWaterBytes 开始收缩的字节数
 * @param {number} retainedBytes 收缩后最多保留的字节数
 */
export function createStderrCollector(highWaterBytes = 64_000, retainedBytes = 32_000) {
  /** @type {Buffer[]} */
  let parts = []
  let bytes = 0
  return {
    /** @param {Buffer|string} chunk */
    push(chunk) {
      const buf = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), 'utf8')
      parts.push(buf)
      bytes += buf.length
      if (bytes <= highWaterBytes) return

      const merged = Buffer.concat(parts, bytes)
      let start = Math.max(0, merged.length - retainedBytes)
      while (start < merged.length && (merged[start] & 0xc0) === 0x80) start++
      const tail = Buffer.from(merged.subarray(start))
      parts = [tail]
      bytes = tail.length
    },
    get bytes() { return bytes },
    /** 一次性解码：只有到这里字节流才成为字符串。 */
    text() { return Buffer.concat(parts, bytes).toString('utf8') },
  }
}

let cachedPython = null

function candidateInterpreters(repoRoot) {
  const list = []
  if (process.env.FF_PYTHON) list.push(process.env.FF_PYTHON)
  const venvDirs = [
    repoRoot ? join(repoRoot, '.venv-fg') : null,
    repoRoot ? join(repoRoot, '.venv') : null,
    join(homedir(), '.venvs', 'formatforge'),
  ].filter(Boolean)
  for (const dir of venvDirs) {
    list.push(IS_WIN ? join(dir, 'Scripts', 'python.exe') : join(dir, 'bin', 'python'))
  }
  list.push('python')
  return list.filter(Boolean)
}

function runVersion(python) {
  return new Promise((resolve) => {
    let child
    try {
      child = spawn(python, ['--version'], { windowsHide: true })
    } catch {
      resolve(null)
      return
    }
    let out = ''
    child.stdout.on('data', (d) => (out += d))
    child.stderr.on('data', (d) => (out += d))
    // JS-H2 同族：探测用的子进程 stdio 也必须有 'error' 监听（FF_PYTHON 指向坏路径时
    // 流会被销毁，裸 'error' 事件 = 进程级未捕获异常）
    child.stdin.on('error', () => {})
    child.stdout.on('error', () => {})
    child.stderr.on('error', () => {})
    child.on('error', () => resolve(null))
    child.on('close', (code) => {
      if (code !== 0) return resolve(null)
      const m = /Python\s+(\d+)\.(\d+)/.exec(out)
      if (!m) return resolve(null)
      const major = Number(m[1])
      const minor = Number(m[2])
      resolve(major > MIN_PYTHON[0] || (major === MIN_PYTHON[0] && minor >= MIN_PYTHON[1]) ? `${major}.${minor}` : null)
    })
    setTimeout(() => {
      try { child.kill() } catch { /* noop */ }
    }, 10_000).unref?.()
  })
}

/**
 * Resolve and cache a usable interpreter (>=3.10).
 * @returns {Promise<string>} python executable
 */
export async function resolvePython(repoRoot) {
  if (cachedPython) return cachedPython
  for (const cand of candidateInterpreters(repoRoot)) {
    const ver = await runVersion(cand)
    if (ver) {
      cachedPython = cand
      return cand
    }
  }
  throw new Error(
    'FormatForge: 未找到可用的 Python 解释器（需 >=3.10）。' +
    '请设置 FF_PYTHON 环境变量指向解释器，或在项目目录创建 .venv-fg 虚拟环境并安装本仓库（pip install -e .）。',
  )
}

/** Repo root that contains core/ parsers/ formatforge/ — needed for `python -m formatforge`. */
export function findRepoRoot(hintDir) {
  let dir = hintDir
  for (let i = 0; i < 6 && dir; i++) {
    if (
      existsSync(join(dir, 'formatforge')) &&
      existsSync(join(dir, 'core')) &&
      existsSync(join(dir, 'pyproject.toml'))
    ) return dir
    const parent = dir.split(sep).slice(0, -1).join(sep)
    dir = parent && parent !== dir ? parent : null
  }
  // Fallback: assume the CWD of the dsh process is the workspace containing the repo.
  return process.cwd()
}

function killTree(child) {
  if (IS_WIN) {
    try {
      const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true })
      // JS-H2 同族：spawn 出的 killer 若无 'error' 监听，taskkill 缺失时会抛未捕获异常
      killer.on('error', () => {})
    } catch { /* noop */ }
  } else {
    try { child.kill('SIGKILL') } catch { /* noop */ }
  }
}

/**
 * Run `python -m formatforge <cliArgs>` and parse the protocol JSON.
 * @param {object} opts
 * @param {string[]} opts.cliArgs        args after `-m formatforge`
 * @param {string}   opts.repoRoot       directory with formatforge/ core/ parsers/
 * @param {string}   [opts.stdinText]    text piped to stdin (--stdin-text mode)
 * @param {number}   [opts.timeoutMs]
 * @param {(line: string) => void} [opts.log] stderr logger
 * @returns {Promise<{ok:true,code:number,data:object}|{ok:false,code:number,error:{kind:string,message:string}}>}
 */
export async function runFormatForge({ cliArgs, repoRoot, stdinText, timeoutMs = DEFAULT_TIMEOUT_MS, log }) {
  const python = await resolvePython(repoRoot)
  const args = ['-m', 'formatforge', ...cliArgs]

  return await new Promise((resolve) => {
    let child
    try {
      child = spawn(python, args, {
        cwd: repoRoot,
        windowsHide: true,
        env: buildChildEnv(repoRoot),
      })
    } catch (e) {
      resolve({ ok: false, code: -1, error: { kind: 'internal', message: `spawn 失败: ${e.message}` } })
      return
    }

    let timedOut = false
    // audit medium：stdout 此前**无上限**累积（stderr 有 64KB 上限而它没有），
    // 异常输出能把活着的 harness 进程 OOM 掉。正常输入（FF_MAX_BYTES 默认 100MB）
    // 不会触及默认 256MB；可用 FF_MAX_STDOUT_BYTES 收紧（测试用），但该旋钮会被
    // 夹到 V8 单字符串上限以下（T3-5）。
    const stdoutCap = resolveStdoutCap()
    const stdoutCollector = createStdoutCollector(stdoutCap)
    const stderrCollector = createStderrCollector()
    let stdoutOverflow = false

    const timer = setTimeout(() => {
      timedOut = true
      killTree(child)
    }, timeoutMs)

    child.stdout.on('data', (d) => {
      // T1-1: 只收字节，不在这里拼字符串（见 createStdoutCollector）。
      if (stdoutCollector.push(d)) return
      if (!stdoutOverflow) {
        stdoutOverflow = true
        killTree(child)
      }
    })
    child.stderr.on('data', (d) => {
      // T1-7: 只收字节，避免每个 pipe chunk 单独解码。
      stderrCollector.push(d)
    })

    // JS-H2: 子进程可能在消费 stdin 前就退出（repoRoot 错 → ModuleNotFoundError、
    // argparse 报错、任何早退）→ stdin 流 emit 'error'(EPIPE)。这不是 promise
    // rejection，宿主也没有 uncaughtException 兜底 → 会直接打死活着的 harness 进程。
    // 所有 child stdio 流都必须有 no-throw 的 'error' 监听（写入前挂好）。
    const onStdioError = (e) => log?.(`[dsh-formatforge] child stdio ${e?.code || 'error'}: ${e?.message || e}`)
    child.stdin.on('error', onStdioError)
    child.stdout.on('error', onStdioError)
    child.stderr.on('error', onStdioError)

    const fail = (kind, message) => ({ ok: false, code: -1, error: { kind, message } })

    child.on('error', (e) => {
      clearTimeout(timer)
      resolve(fail('internal', `无法启动 Python: ${e.message}`))
    })

    child.on('close', (exitCode) => {
      clearTimeout(timer)
      if (timedOut) {
        resolve(fail('timeout', `转换超时（>${Math.round(timeoutMs / 1000)}s），已终止进程`))
        return
      }
      if (stdoutOverflow) {
        resolve(fail('output_too_large', `CLI 输出超过上限（>${stdoutCap} 字节），已终止进程；可用 FF_MAX_STDOUT_BYTES 调整`))
        return
      }
      // T1-1: 字节收齐后**一次性** UTF-8 解码，chunk 边界不再产生 U+FFFD。
      const stdout = stdoutCollector.text()
      // T1-7: 所有日志与 JS-H7 summarizeStderr 消费者都只看到解码后的字符串。
      const stderr = stderrCollector.text()
      const line = stdout.split(/\r?\n/).find((l) => l.trim().startsWith('{'))
      if (!line) {
        log?.(`[dsh-formatforge] no protocol JSON on stdout. exit=${exitCode}. stderr tail: ${stderr.slice(-300)}`)
        resolve(fail('internal', `CLI 未输出协议 JSON (exit=${exitCode})。stderr 摘要: ${summarizeStderr(stderr)}`))
        return
      }
      try {
        const payload = JSON.parse(line)
        if (payload.ok === false && Array.isArray(payload.error?.message) === false && stderr.trim()) {
          log?.(`[dsh-formatforge] stderr: ${stderr.slice(-500)}`)
        }
        resolve(payload)
      } catch (e) {
        resolve(fail('internal', `协议 JSON 解析失败: ${e.message}；原始输出: ${line.slice(0, 200)}`))
      }
    })

    if (stdinText != null) {
      try {
        child.stdin.write(stdinText)
      } catch (e) {
        log?.(`[dsh-formatforge] stdin write failed: ${e.message}`)
      }
    }
    try {
      child.stdin.end()
    } catch (e) {
      log?.(`[dsh-formatforge] stdin end failed: ${e.message}`)
    }
  })
}

/** Stat-clamp before spawn: must exist, be a file, and fit the size cap. */
export function validateLocalFile(pathStr, maxBytes) {
  let st
  try {
    st = statSync(pathStr)
  } catch {
    return { ok: false, reason: `文件不存在: ${pathStr}` }
  }
  if (!st.isFile()) return { ok: false, reason: `路径不是文件: ${pathStr}` }
  if (maxBytes && st.size > maxBytes) {
    return { ok: false, reason: `文件 ${st.size} 字节超过上限 ${maxBytes}` }
  }
  return { ok: true, size: st.size }
}
