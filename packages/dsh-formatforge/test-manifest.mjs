// test-manifest.mjs — CI-side sanity for the dsh-formatforge bundle:
// package.json contract (dsh.client + exports["./client"]) and generated
// client.js wrapper id consistency. No dsh runtime needed.
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const pkgRoot = dirname(fileURLToPath(import.meta.url))
const fail = (msg) => {
  console.error('MANIFEST-FAIL:', msg)
  process.exit(1)
}

const pkg = JSON.parse(readFileSync(join(pkgRoot, 'package.json'), 'utf8'))

// 1) dsh.client declared
if (!pkg.dsh || !pkg.dsh.client || pkg.dsh.client.platform !== 'web') {
  fail('package.json must declare dsh.client = { inject: [], platform: "web" }')
}

// 2) exports["./client"] present — host refuses otherwise
if (!pkg.exports || !pkg.exports['./client']) {
  fail('exports must contain "./client" (host: declares dsh.client but exports no "./client" bundle)')
}
const clientPath = join(pkgRoot, pkg.exports['./client'])
const clientSrc = readFileSync(clientPath, 'utf8')

// 3) client.js wrapped with __ModuleLoader__.load
if (!clientSrc.includes('window.__ModuleLoader__.load(')) {
  fail('lib/client.js must be wrapped in window.__ModuleLoader__.load({id, factory})')
}

// 4) load id must equal the cordis loader entry id (bare name from cordis.patch.yml)
const patch = readFileSync(join(pkgRoot, 'cordis.patch.yml'), 'utf8')
const m = /id:\s*([^\s]+)\n/.exec(patch.split('- insert:')[1] || '')
const entryId = m ? m[1].trim().replace(/^['"]|['"]$/g, '') : null
if (!entryId) fail('cannot parse loader entry id from cordis.patch.yml')
if (!clientSrc.includes(`id: "${entryId}"`)) {
  fail(`client.js load id must be "${entryId}" (got a different id; mismatch => "loaded without registering")`)
}

// 5) cordis plugin shape on exports
if (!clientSrc.includes('.apply =')) fail('client.js exports must carry an apply method')
if (!clientSrc.includes('.inject')) fail('client.js exports must carry inject')

console.log('MANIFEST-OK:', entryId, '|', pkg.version)
