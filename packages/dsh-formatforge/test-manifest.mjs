// test-manifest.mjs — CI-side sanity for the dsh-formatforge bundle:
// package.json contract (dsh.client + exports["./client"]) and the generated
// client.js wrapper. No dsh runtime needed.
//
// Host contract being asserted (DSH 0.2.0-rc.2, @deepseek-ai/dsh-client-modules):
//   - lib/index.js composes graph rows keyed by the *package name*
//     (`table.set(packageName, { entry: graphRow(packageName, rev, meta) })`).
//   - lib/client.js `register({id, factory})` files the factory under
//     `stripClientSuffix(registration.id)` and `import(id)` then throws
//     `bundle <url> loaded without registering "<id>" via __ModuleLoader__.load`
//     when that id is absent.
//   So the __ModuleLoader__.load id MUST be the npm package name — NOT the
//   cordis loader entry id from cordis.patch.yml. scripts/build-client.mjs reads
//   the id from package.json so the two can never drift.
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
if (!Array.isArray(pkg.dsh.client.inject)) {
  fail('dsh.client.inject must be a string array (host: optionalStringArray)')
}

// 2) dsh.bundle.patch declared — the profile layer the host composes
if (!pkg.dsh.bundle || typeof pkg.dsh.bundle.patch !== 'string') {
  fail('package.json must declare dsh.bundle.patch (host skips packages without it)')
}

// 3) exports["./client"] present — host refuses otherwise
//    ("declares dsh.client but exports no \"./client\" bundle")
if (!pkg.exports || !pkg.exports['./client']) {
  fail('exports must contain "./client"')
}
const clientPath = join(pkgRoot, pkg.exports['./client'])
const clientSrc = readFileSync(clientPath, 'utf8')

// 4) client.js wrapped with __ModuleLoader__.load
if (!clientSrc.includes('window.__ModuleLoader__.load(')) {
  fail('lib/client.js must be wrapped in window.__ModuleLoader__.load({id, factory})')
}

// 5) load id must equal the npm package name (see header note)
if (!clientSrc.includes(`id: ${JSON.stringify(pkg.name)}`)) {
  fail(`client.js load id must be ${JSON.stringify(pkg.name)} (the host keys its graph rows by package name)`)
}
// ...and must NOT be the bare cordis entry id, which is a common regression
const patch = readFileSync(join(pkgRoot, pkg.dsh.bundle.patch), 'utf8')
const m = /- insert:\s*\n\s*-\s*id:\s*([^\s]+)\n\s*name:\s*['"]?([^\s'"]+)/.exec(patch)
if (!m) fail('cannot parse the loader entry id/name from the bundle patch')
const [, entryId, entryName] = m
if (entryName !== pkg.name) {
  fail(`bundle patch entry name must be the package name ${JSON.stringify(pkg.name)} (got ${JSON.stringify(entryName)})`)
}
if (entryId === pkg.name) {
  fail('bundle patch entry id should stay the short row id, not the package name')
}
if (clientSrc.includes(`id: "${entryId}"`)) {
  fail(`client.js registers the cordis entry id "${entryId}" — the host would fail boot with "loaded without registering"`)
}

// 6) cordis plugin shape on exports
if (!clientSrc.includes('exports.inject')) fail('client.js exports must carry inject')
if (!clientSrc.includes('exports.apply')) fail('client.js exports must carry an apply method')

// 7) compatibility gate: every @deepseek-ai/dsh* peer must accept the declared engines.dsh floor
if (pkg.peerDependencies) {
  for (const [name, range] of Object.entries(pkg.peerDependencies)) {
    if (name !== '@deepseek-ai/dsh' && !name.startsWith('@deepseek-ai/dsh-')) continue
    if (typeof range !== 'string' || range.trim() === '') fail(`peerDependencies[${name}] must be a non-empty range`)
  }
  if (typeof pkg.engines?.dsh !== 'string') {
    fail('package.json must declare engines.dsh alongside @deepseek-ai/dsh* peers (author-declared host range)')
  }
}

console.log('MANIFEST-OK:', entryId, '|', pkg.name, '|', pkg.version)
