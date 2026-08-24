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
const MIN_PYTHON = [3, 10]

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
      spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true })
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
        env: {
          ...process.env,
          PYTHONPATH: repoRoot,
          PYTHONIOENCODING: 'utf-8',
          PYTHONUTF8: '1',
        },
      })
    } catch (e) {
      resolve({ ok: false, code: -1, error: { kind: 'internal', message: `spawn 失败: ${e.message}` } })
      return
    }

    let stdout = ''
    let stderr = ''
    let timedOut = false

    const timer = setTimeout(() => {
      timedOut = true
      killTree(child)
    }, timeoutMs)

    child.stdout.on('data', (d) => (stdout += d))
    child.stderr.on('data', (d) => {
      stderr += d
      if (stderr.length > 64_000) stderr = stderr.slice(-32_000)
    })

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
      const line = stdout.split(/\r?\n/).find((l) => l.trim().startsWith('{'))
      if (!line) {
        log?.(`[dsh-formatforge] no protocol JSON on stdout. exit=${exitCode}. stderr tail: ${stderr.slice(-300)}`)
        resolve(fail('internal', `CLI 未输出协议 JSON (exit=${exitCode})。stderr 尾部: ${stderr.slice(-200)}`))
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
      child.stdin.write(stdinText)
    }
    child.stdin.end()
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
