// build-client.mjs — regenerate lib/client.js from client.source.js.
//
// The __ModuleLoader__.load id is the **npm package name** (or that name with a
// "/client" suffix — both normalize to the same row). The host's
// @deepseek-ai/dsh-client-modules keys its graph rows by the package name
// (`table.set(packageName, { entry: graphRow(packageName, ...) })`) and its
// browser half throws
//   `bundle <url> loaded without registering "<packageName>" via __ModuleLoader__.load`
// when the bundle registers anything else. The cordis loader entry id (the
// `id:` in cordis.patch.yml) is NOT what the client bundle registers under.
// The id is read from package.json below so the two can never drift.
//
// The wrapper also gives the bundle the cordis client-plugin shape the host
// expects — `exports.{ inject, apply }` — and hands `activate()`'s disposer to
// `ctx.effect` so a client-module reload tears the listeners down instead of
// stacking a second set.
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const pkgRoot = dirname(here)
const pkg = JSON.parse(readFileSync(join(pkgRoot, 'package.json'), 'utf8'))
const src = readFileSync(join(pkgRoot, 'lib', 'client.source.js'), 'utf8')
// The source is authored for this wrapper: `activate()` is a plain function in
// the factory scope, not a module export.
if (/\bexport\s/.test(src)) {
  throw new Error('client.source.js must not contain ESM syntax; the host loads the bundle as a classic script')
}

const lines = [
  'window.__ModuleLoader__.load({',
  `\tid: ${JSON.stringify(pkg.name)},`,
  '\tfactory: (require) => {',
  '\t\tvar module = { exports: {} };',
  '\t\tvar exports = module.exports;',
  '\t\tObject.defineProperty(exports, Symbol.toStringTag, { value: "Module" });',
  src,
  '',
  '\t\t// cordis client-plugin contract: the host mounts each client module as a',
  '\t\t// plugin, so exports must carry { inject: [...], apply(ctx) }. The disposer',
  '\t\t// returned by activate() goes to ctx.effect so an HMR reload unregisters',
  '\t\t// the listeners instead of stacking a second set.',
  '\t\texports.inject = [];',
  '\t\texports.apply = function (ctx) {',
  '\t\t\tif (ctx && typeof ctx.effect === "function") ctx.effect(() => activate());',
  '\t\t\telse activate();',
  '\t\t};',
  '\t\treturn exports;',
  '\t},',
  '});',
]
const wrapped = lines.join('\n') + '\n'
writeFileSync(join(pkgRoot, 'lib', 'client.js'), wrapped)
console.log('lib/client.js rebuilt:', wrapped.length, 'chars, id =', pkg.name)
