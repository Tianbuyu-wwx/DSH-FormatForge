// packages/dsh-formatforge/test/test-runner-env-stderr.mjs
//
// v1.0.3/JS-H7 回归（审计 M1）：
//   1) 子进程环境此前是 `{...process.env}` —— 整台机器的 provider key / session token /
//      无关项目路径都进了 Python 子进程。现在只放行 OS 必需项 + `FF_*` / `PYTHON*` 旋钮。
//   2) stderr 此前把尾部 200 字符直接塞进 error.message，再被渲染进**模型读到的**
//      工具结果；现在只保留「异常类 + 最后一行」。
//
// 用法：node packages/dsh-formatforge/test/test-runner-env-stderr.mjs

let failures = 0
function check(name, cond, detail = '') {
  if (cond) {
    console.log(`✅ ${name}`)
  } else {
    failures++
    console.error(`❌ ${name}  ${detail}`)
  }
}

const { buildChildEnv, summarizeStderr } = await import('../services/python-runner.mjs')

console.log('\n=== child env policy + stderr redaction (JS-H7) ===\n')

// ---- 1) 环境白名单 ----
const SECRETS = {
  OPENAI_API_KEY: 'sk-canary-should-not-leak',
  ANTHROPIC_API_KEY: 'sk-ant-canary',
  DSH_SESSION_TOKEN: 'session-token-canary',
  GH_TOKEN: 'ghp_canary',
  AWS_SECRET_ACCESS_KEY: 'aws-canary',
  UNRELATED_PROJECT_PATH: 'D:/some/other/project',
}
const KNOBS = { FF_MAX_BYTES: '12345', FF_OUTPUT_ROOT: 'D:/sandbox-out', PYTHONHASHSEED: '0' }
Object.assign(process.env, SECRETS, KNOBS)

const env = buildChildEnv('D:/Deepseek-harness/DSH-FormatForge')

check('PATH passed through', typeof env.PATH === 'string' && env.PATH.length > 0, String(env.PATH).slice(0, 60))
if (process.platform === 'win32') {
  check('SYSTEMROOT passed through (Windows DLL loading)', !!env.SYSTEMROOT || !!env.SystemRoot, JSON.stringify({ SYSTEMROOT: env.SYSTEMROOT, SystemRoot: env.SystemRoot }))
  check('TEMP passed through (tempfile/OCR)', !!(env.TEMP || env.TMP), JSON.stringify({ TEMP: env.TEMP, TMP: env.TMP }))
  check('LOCALAPPDATA passed through (Tesseract discovery)', !!env.LOCALAPPDATA, String(env.LOCALAPPDATA))
}
check('USERPROFILE passed through (expanduser)', !!env.USERPROFILE || !!env.HOME, JSON.stringify({ USERPROFILE: env.USERPROFILE, HOME: env.HOME }))

for (const [key, value] of Object.entries(SECRETS)) {
  check(`secret NOT inherited: ${key}`, env[key] === undefined, String(env[key]))
}
check('FF_MAX_BYTES knob passed through', env.FF_MAX_BYTES === '12345', String(env.FF_MAX_BYTES))
check('FF_OUTPUT_ROOT knob passed through', env.FF_OUTPUT_ROOT === 'D:/sandbox-out', String(env.FF_OUTPUT_ROOT))
check('PYTHON* params passed through', env.PYTHONHASHSEED === '0', String(env.PYTHONHASHSEED))
check('PYTHONPATH pinned to repoRoot', env.PYTHONPATH === 'D:/Deepseek-harness/DSH-FormatForge', String(env.PYTHONPATH))
check('PYTHONIOENCODING/PYTHONUTF8 pinned', env.PYTHONIOENCODING === 'utf-8' && env.PYTHONUTF8 === '1', JSON.stringify(env))

const unexpected = Object.keys(env).filter((k) => !(k in SECRETS) && !(k in KNOBS) && !/^(FF_|PYTHON)/.test(k) && !['PATH', 'Path', 'PATHEXT', 'SYSTEMROOT', 'SystemRoot', 'WINDIR', 'COMSPEC', 'SystemDrive', 'TEMP', 'TMP', 'LOCALAPPDATA', 'APPDATA', 'ProgramData', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'USERPROFILE', 'HOMEDRIVE', 'HOMEPATH', 'HOME', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ'].includes(k))
check('no other parent env leaks in', unexpected.length === 0, JSON.stringify(unexpected))

// ---- 2) stderr 摘要 ----
const traceback = [
  'Traceback (most recent call last):',
  '  File "C:\\repo\\formatforge\\__main__.py", line 42, in main',
  '    import core.secret_module',
  '  File "C:\\repo\\core\\secret_module.py", line 7, in <module>',
  '    TOKEN = "sk-canary-in-traceback"',
  "ModuleNotFoundError: No module named 'formatforge'",
].join('\n')
const summary = summarizeStderr(traceback)
check('keeps the exception class', summary.includes('ModuleNotFoundError'), summary)
check('keeps the last line', summary.includes("No module named 'formatforge'"), summary)
check('drops intermediate traceback frames', !summary.includes('File "C:'), summary)
check('drops content that only lived in a middle frame', !summary.includes('sk-canary-in-traceback'), summary)
check('summary is length-capped', summarizeStderr('y'.repeat(5000)).length <= 320, String(summarizeStderr('y'.repeat(5000)).length))
check('control chars stripped from stderr', !/[\u0000-\u001f\u007f]/.test(summarizeStderr('a\u0007b\r\nc')), JSON.stringify(summarizeStderr('a\u0007b\r\nc')))
check('empty stderr → empty summary', summarizeStderr('') === '' && summarizeStderr('\n\n') === '', JSON.stringify([summarizeStderr(''), summarizeStderr('\n\n')]))
check('plain last line without exception class survives', summarizeStderr('warning: something\nplain failure text') === 'plain failure text', summarizeStderr('warning: something\nplain failure text'))

if (failures > 0) {
  console.error(`\n❌ ${failures} check(s) failed`)
  process.exit(1)
}
console.log('\n✅ child env policy + stderr redaction hold')