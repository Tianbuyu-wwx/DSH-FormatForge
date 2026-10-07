// packages/dsh-formatforge/test/test-runner-stderr-utf8.mjs
//
// T1-7 regression: stderr used to be decoded once per raw pipe chunk via
// `stderr += d`. A multi-byte UTF-8 sequence split across chunks therefore
// became U+FFFD before logging or summarizeStderr could read it.
//
// Usage: node packages/dsh-formatforge/test/test-runner-stderr-utf8.mjs

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
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

const runner = await import('../services/python-runner.mjs')
const { createStderrCollector, runFormatForge, summarizeStderr } = runner

console.log('\n=== stderr UTF-8 integrity (T1-7) ===\n')

check(
  'python-runner exports a byte-level stderr collector',
  typeof createStderrCollector === 'function',
  String(typeof createStderrCollector),
)

// Unit layer: seven-byte chunks deterministically split three- and four-byte
// UTF-8 sequences. The decoded string must reconstruct the original bytes.
if (typeof createStderrCollector === 'function') {
  const payload = 'UnicodeError: 中文测试😀结束'
  const expected = Buffer.from(payload, 'utf8')
  const collector = createStderrCollector()
  for (let i = 0; i < expected.length; i += 7) {
    collector.push(expected.subarray(i, i + 7))
  }
  const decoded = collector.text()
  check('split sequences decode byte-identically', Buffer.from(decoded, 'utf8').equals(expected), JSON.stringify(decoded))
  check('split sequences contain no U+FFFD', !decoded.includes('\uFFFD'), JSON.stringify(decoded))
  check('summarizeStderr receives a decoded string', typeof decoded === 'string' && summarizeStderr(decoded) === payload, JSON.stringify(summarizeStderr(decoded)))

  const bounded = createStderrCollector(20, 5)
  bounded.push(Buffer.from(`${'a'.repeat(20)}😀xy`, 'utf8'))
  const retained = bounded.text()
  check('retention window is byte-bounded', bounded.bytes <= 5, String(bounded.bytes))
  check('retention starts on a UTF-8 boundary', retained === 'xy' && !retained.includes('\uFFFD'), JSON.stringify(retained))
}

// End-to-end layer: a tiny stand-in module emits stderr one byte at a time,
// with a pause so each byte reaches Node as a separate pipe chunk. No protocol
// JSON is emitted, making the decoded stderr summary observable in the result.
{
  const realRepoRoot = join(import.meta.dirname, '..', '..', '..')
  process.env.FF_PYTHON = process.platform === 'win32'
    ? join(realRepoRoot, '.venv-fg', 'Scripts', 'python.exe')
    : join(realRepoRoot, '.venv-fg', 'bin', 'python')

  const fakeRepoRoot = mkdtempSync(join(tmpdir(), 'ff-stderr-utf8-'))
  process.on('exit', () => rmSync(fakeRepoRoot, { recursive: true, force: true }))
  const packageDir = join(fakeRepoRoot, 'formatforge')
  mkdirSync(packageDir)

  const payload = 'UnicodeError: stderr 完整😀终点'
  writeFileSync(join(packageDir, '__main__.py'), [
    'import sys',
    'import time',
    `payload = ${JSON.stringify(payload)}.encode("utf-8")`,
    'for byte in payload:',
    '    sys.stderr.buffer.write(bytes([byte]))',
    '    sys.stderr.buffer.flush()',
    '    time.sleep(0.005)',
  ].join('\n'), 'utf8')

  const res = await runFormatForge({
    cliArgs: [],
    repoRoot: fakeRepoRoot,
    timeoutMs: 30_000,
    log: () => {},
  })
  const marker = 'stderr 摘要: '
  const message = String(res?.error?.message || '')
  const decoded = message.includes(marker) ? message.slice(message.indexOf(marker) + marker.length) : ''
  const expected = Buffer.from(payload, 'utf8')

  check('e2e: missing protocol returns an internal error', res?.ok === false && res?.error?.kind === 'internal', JSON.stringify(res))
  check('e2e: stderr remains byte-identical', Buffer.from(decoded, 'utf8').equals(expected), JSON.stringify(decoded))
  check('e2e: stderr contains no U+FFFD', !decoded.includes('\uFFFD'), JSON.stringify(decoded))
}

if (failures > 0) {
  console.error(`\n❌ ${failures} check(s) failed`)
  process.exit(1)
}
console.log('\n✅ stderr decodes as one UTF-8 stream')
