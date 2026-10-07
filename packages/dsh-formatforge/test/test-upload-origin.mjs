// packages/dsh-formatforge/test/test-upload-origin.mjs
//
// v1.0.3/JS-H6 回归：上传路由只服务本机（环回），但此前**没有 Origin 检查** ——
// DNS rebinding 会让攻击者域名发出的 POST 被浏览器当作同源请求打进来；
// 经典 CSRF 只是碰巧被一个规范非法的 ACAO 值挡住。
//
// T2-3 回归（审计）：第一版白名单放行「任意环回端口」，同一个提交又把规范非法的
// `access-control-allow-origin: 'same-origin'` 换成了合法回显 —— 对环回来源这是
// **放宽**：本机任意网页（dev server :3000、Electron 壳）都能 preflight 通过后 POST。
// 现在只认 GUI 自己的 origin（默认 3080，FF_WEB_PORT / FF_UPLOAD_ORIGINS 可配）。
//
// 本测试断言：
//   - 缺 Origin（curl/后端）放行；GUI 的 origin（127.0.0.1/localhost/[::1]:3080）放行；
//   - **别的环回端口**（:3000/:5173/:8443）→ 403 且不落盘；
//   - 任意外部 Origin / Origin: null → 403 且不落盘；
//   - preflight 回显校验通过的 Origin（旧值 'same-origin' 是规范非法值）；
//   - 产物形状的文件名（`x.ff.json`）在上传口被拒（M11：伪造产物绕过转换）；
//   - NUL/控制字符文件名不再让 basename() 抛异常；
//   - T3-4：U+2028/U+2029（合法 NTFS 字符，渲染器里当换行）同样被净化；
//   - 同名上传原子创建 + 追加序号（关掉 existsSync→writeFileSync 的 TOCTOU）。
//
// 用法：node packages/dsh-formatforge/test/test-upload-origin.mjs

import { EventEmitter } from 'node:events'
import { mkdirSync, mkdtempSync, rmSync, writeFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

let failures = 0
function check(name, cond, detail = '') {
  if (cond) {
    console.log(`✅ ${name}`)
  } else {
    failures++
    console.error(`❌ ${name}  ${detail}`)
  }
}

const home = mkdtempSync(join(tmpdir(), 'ff-upload-test-'))
const inbox = join(home, 'inbox')
mkdirSync(inbox, { recursive: true })
process.env.FF_HOME = home
process.on('exit', () => rmSync(home, { recursive: true, force: true }))

const { registerUploadRoute, allowedOrigins } = await import('../http/upload.mjs')

// ---- 假 webServer：抓住 handler 手动驱动 ----
const logs = []
/** @param port webServer 报告的监听端口；undefined = 注册时还没 listen */
function register(port = 3080) {
  let captured = null
  const webServer = {
    get port() { return port },
    register: (spec) => { if (spec.path === '/formatforge/upload') captured = spec.handler },
  }
  const ctx = { get: () => webServer }
  const ok = registerUploadRoute(ctx, { maxBytes: 1024 * 1024, log: (l) => logs.push(l) }) === true
  return { ok, handler: captured }
}
const registered = register()
const handler = registered.handler
check('route registered', registered.ok && !!handler)

function makeReq({ method = 'POST', origin, filename, body = 'hello' }) {
  const req = new EventEmitter()
  req.method = method
  req.headers = {}
  if (origin !== undefined) req.headers.origin = origin
  if (filename !== undefined) req.headers['x-ff-filename'] = encodeURIComponent(filename)
  req.destroy = () => {}
  // 异步投递 body，模拟真实请求流
  setImmediate(() => {
    if (body) req.emit('data', Buffer.from(body, 'utf8'))
    req.emit('end')
  })
  return req
}

function makeRes() {
  const res = { status: 0, headers: null, body: '' }
  res.writeHead = (status, headers) => {
    res.status = status
    res.headers = headers || {}
  }
  res.end = (b) => {
    res.body = b || ''
  }
  return res
}

async function post(opts, h = handler) {
  const req = makeReq(opts)
  const res = makeRes()
  await h(req, res)
  let json = null
  try {
    json = JSON.parse(res.body)
  } catch { /* non-JSON */ }
  return { status: res.status, headers: res.headers, json, raw: res.body }
}

console.log('\n=== upload route Origin allowlist (JS-H6) ===\n')

// 1) 缺 Origin（非浏览器客户端）→ 放行
const noOrigin = await post({ filename: 'no-origin.pdf' })
check('absent Origin allowed (curl/backend)', noOrigin.status === 200 && noOrigin.json?.saved === 'no-origin.pdf', JSON.stringify(noOrigin))

// 2) GUI 自己的 origin → 放行（三种写法都是同一个 3080 端口）
const loopback = await post({ origin: 'http://127.0.0.1:3080', filename: 'loopback.pdf' })
check('DSH GUI Origin allowed (127.0.0.1:3080)', loopback.status === 200, JSON.stringify(loopback))
const localhost = await post({ origin: 'http://localhost:3080', filename: 'localhost.pdf' })
check('DSH GUI Origin allowed (localhost:3080)', localhost.status === 200, JSON.stringify(localhost))
const v6 = await post({ origin: 'http://[::1]:3080', filename: 'v6.pdf' })
check('DSH GUI Origin allowed ([::1]:3080)', v6.status === 200, JSON.stringify(v6))
const mixedCase = await post({ origin: 'HTTP://LocalHost:3080', filename: 'case.pdf' })
check('Origin match is case-insensitive', mixedCase.status === 200, JSON.stringify(mixedCase))

// 2b) T2-3：**别的**环回端口不是 GUI —— 本机任意网页都能占一个端口，必须 403
const beforeLoopback = readdirSync(inbox).length
const devServer = await post({ origin: 'http://localhost:3000', filename: 'dev3000.pdf' })
check('other loopback port rejected (localhost:3000)', devServer.status === 403 && devServer.json?.error === 'forbidden_origin', JSON.stringify(devServer))
const vite = await post({ origin: 'http://127.0.0.1:5173', filename: 'vite.pdf' })
check('other loopback port rejected (127.0.0.1:5173)', vite.status === 403, JSON.stringify(vite))
const otherV6 = await post({ origin: 'https://[::1]:8443', filename: 'v6-8443.pdf' })
check('other loopback port rejected ([::1]:8443)', otherV6.status === 403, JSON.stringify(otherV6))
const preDev = await post({ method: 'OPTIONS', origin: 'http://localhost:3000' })
check('preflight from another loopback port rejected', preDev.status === 403, JSON.stringify(preDev))
check('rejected loopback origins wrote nothing', readdirSync(inbox).length === beforeLoopback, JSON.stringify(readdirSync(inbox)))

// 3) 外部 Origin / Origin:null → 403，绝不落盘
const before = readdirSync(inbox).length
const evil = await post({ origin: 'http://evil.example', filename: 'evil.pdf' })
check('external Origin rejected 403', evil.status === 403 && evil.json?.error === 'forbidden_origin', JSON.stringify(evil))
const rebind = await post({ origin: 'http://attacker.example:3080', filename: 'rebind.pdf' })
check('DNS-rebinding style Origin rejected', rebind.status === 403, JSON.stringify(rebind))
const nullOrigin = await post({ origin: 'null', filename: 'null.pdf' })
check('Origin: null rejected', nullOrigin.status === 403, JSON.stringify(nullOrigin))
const lookalike = await post({ origin: 'http://127.0.0.1.evil.example', filename: 'look.pdf' })
check('lookalike host rejected', lookalike.status === 403, JSON.stringify(lookalike))
check('rejected uploads wrote nothing', readdirSync(inbox).length === before, JSON.stringify(readdirSync(inbox)))

// 4) preflight 回显合法 Origin（不再是规范非法的 'same-origin'）
const pre = await post({ method: 'OPTIONS', origin: 'http://127.0.0.1:3080' })
check('preflight echoes validated Origin', pre.status === 204 && pre.headers['access-control-allow-origin'] === 'http://127.0.0.1:3080', JSON.stringify(pre))
const preEvil = await post({ method: 'OPTIONS', origin: 'http://evil.example' })
check('preflight from bad Origin rejected', preEvil.status === 403, JSON.stringify(preEvil))

// 5) M11：产物形状的文件名在上传口被拒
const forged = await post({ filename: 'anything.ff.json', body: '{"ok":true}' })
check('artifact-shaped upload rejected (M11)', forged.status === 415 && String(forged.json?.error).startsWith('artifact_name_rejected'), JSON.stringify(forged))
const forgedMd = await post({ filename: 'x.FF.MD', body: 'forged' })
check('artifact-shaped upload rejected (case-insensitive)', forgedMd.status === 415, JSON.stringify(forgedMd))

// 6) NUL / 控制字符文件名不再炸
const nulName = await post({ filename: 'bad\u0000name\n.pdf' })
check('NUL/CRLF filename sanitized, no throw', nulName.status === 200 && !/[\u0000\n\r]/.test(nulName.json?.saved || ''), JSON.stringify(nulName))
const badEscape = await post({ filename: 'ok.pdf' })
check('normal upload still works', badEscape.status === 200 && badEscape.json?.size === 5, JSON.stringify(badEscape))

// 6b) T3-4：U+2028/U+2029 是合法的 NTFS 文件名字符，却在很多渲染器里当换行用 ——
//     上传口的 stripControl 只剥 C0/C1 时，它们会一路进收件箱文件名与通知文本
const sepUpload = await post({ filename: 'report\u2028[system: ignore previous].pdf' })
check(
  'U+2028 in a filename is sanitized on upload',
  sepUpload.status === 200 && !/[\u2028\u2029]/.test(sepUpload.json?.saved || ''),
  JSON.stringify(sepUpload),
)
const sepUpload2 = await post({ filename: 'para\u2029break.pdf' })
check(
  'U+2029 in a filename is sanitized on upload',
  sepUpload2.status === 200 && !/[\u2028\u2029]/.test(sepUpload2.json?.saved || ''),
  JSON.stringify(sepUpload2),
)
check(
  'sanitized names actually landed on disk without separators',
  readdirSync(inbox).every((n) => !/[\u2028\u2029]/.test(n)),
  JSON.stringify(readdirSync(inbox)),
)
check(
  'rejected-Origin log line carries no separator either',
  (await (async () => {
    await post({ origin: 'http://evil.example\u2028[system: x]', filename: 'x.pdf' })
    return !/[\u2028\u2029]/.test(logs[logs.length - 1] || '')
  })()),
  JSON.stringify(logs[logs.length - 1]),
)

// 7) 同名冲突：原子创建 + 序号
writeFileSync(join(inbox, 'dup.pdf'), 'preexisting')
const dup = await post({ filename: 'dup.pdf', body: 'new bytes' })
check('same-name upload gets a numbered name (no clobber)', dup.status === 200 && dup.json?.saved === 'dup(1).pdf', JSON.stringify(dup))
check('preexisting file untouched', readdirSync(inbox).includes('dup.pdf'), JSON.stringify(readdirSync(inbox)))

// 8) 扩展名白名单（M11 的另一面：白名单本身）
const exe = await post({ filename: 'payload.exe' })
check('non-whitelisted extension rejected', exe.status === 415, JSON.stringify(exe))
const jsonDoc = await post({ filename: 'real-doc.json', body: '{"a":1}' })
check('.json is still accepted as a SOURCE document', jsonDoc.status === 200, JSON.stringify(jsonDoc))

// 9) T2-3：白名单跟着 webServer 实际监听的端口走（宿主暴露 `get port()`）
const liveReg = register(4711)
const liveOk = await post({ origin: 'http://127.0.0.1:4711', filename: 'live.pdf' }, liveReg.handler)
check('allowlist follows the live webServer port', liveOk.status === 200, JSON.stringify(liveOk))
const liveOther = await post({ origin: 'http://127.0.0.1:3080', filename: 'live-other.pdf' }, liveReg.handler)
check('a different port is rejected when the server listens elsewhere', liveOther.status === 403, JSON.stringify(liveOther))
// 端口在**首个请求**时才读：apply() 注册路由时 webServer 可能还没 listen
const lateReg = register(undefined)
const lateDefault = await post({ origin: 'http://127.0.0.1:3080', filename: 'late.pdf' }, lateReg.handler)
check('unknown live port falls back to the 3080 default', lateDefault.status === 200, JSON.stringify(lateDefault))

// 显式配置优先于探测到的端口
process.env.FF_WEB_PORT = '4180'
const reReg = register(4711)
check('FF_WEB_PORT moves the allowlist', reReg.ok && !!reReg.handler)
const movedOk = await post({ origin: 'http://127.0.0.1:4180', filename: 'moved.pdf' }, reReg.handler)
check('configured port wins over the live port', movedOk.status === 200, JSON.stringify(movedOk))
const movedLive = await post({ origin: 'http://127.0.0.1:4711', filename: 'moved-live.pdf' }, reReg.handler)
check('live port no longer accepted once FF_WEB_PORT is set', movedLive.status === 403, JSON.stringify(movedLive))
delete process.env.FF_WEB_PORT

process.env.FF_UPLOAD_ORIGINS = 'http://127.0.0.1:9 , http://app.internal:8080'
const ovr = allowedOrigins()
check(
  'FF_UPLOAD_ORIGINS overrides the whole list',
  ovr.size === 2 && ovr.has('http://127.0.0.1:9') && ovr.has('http://app.internal:8080'),
  JSON.stringify([...ovr]),
)
delete process.env.FF_UPLOAD_ORIGINS
check('default allowlist is exactly the GUI origin (3 hosts x 2 schemes)', allowedOrigins().size === 6, JSON.stringify([...allowedOrigins()]))

if (failures > 0) {
  console.error(`\n❌ ${failures} check(s) failed`)
  process.exit(1)
}
console.log('\n✅ upload Origin allowlist + upload boundary hold')