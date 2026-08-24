// build-client.mjs — regenerate lib/client.js from client.source.js.
// The __ModuleLoader__.load id MUST equal the cordis loader entry id (bare
// "dsh-formatforge"), not the npm package name — mismatch fails boot with
// "loaded without registering <id> via __ModuleLoader__.load".
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const pkgRoot = dirname(here)
const src = readFileSync(join(pkgRoot, 'lib', 'client.source.js'), 'utf8')
const body = src.replace('export function activate()', 'function activate()')

const lines = [
  'window.__ModuleLoader__.load({',
  '\tid: "dsh-formatforge",',
  '\tfactory: (require) => {',
  '\t\tvar module = { exports: {} };',
  '\t\tvar exports = module.exports;',
  '\t\tObject.defineProperty(exports, Symbol.toStringTag, { value: "Module" });',
  body,
  '',
  '\t\t// cordis plugin contract: host treats each client module as a plugin —',
  '\t\t// exports must carry { inject: [...], apply(ctx) }.',
  '\t\texports.inject = [];',
  '\t\texports.apply = function () { activate(); };',
  '\t\treturn exports;',
  '\t},',
  '});',
]
const wrapped = lines.join('\n') + '\n'
writeFileSync(join(pkgRoot, 'lib', 'client.js'), wrapped)
console.log('lib/client.js rebuilt:', wrapped.length, 'chars')
