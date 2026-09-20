// K-1: the JSON artifact is the inbox completion marker. Publish it only after
// both temporary files are complete and the Markdown artifact is in place.

import { sourceMtimeOr, writeArtifactPairAtomic } from '../services/inbox-watcher.mjs'

let failures = 0
function check(name, cond, detail = '') {
  if (cond) console.log(`✅ ${name}`)
  else {
    failures++
    console.error(`❌ ${name}  ${detail}`)
  }
}

function fakeFs({ failJsonRename = false } = {}) {
  const files = new Set()
  const calls = []
  return {
    files,
    calls,
    ops: {
      writeFileSync(path) {
        calls.push(['write', path])
        files.add(path)
      },
      renameSync(from, to) {
        calls.push(['rename', from, to])
        if (failJsonRename && to.endsWith('.ff.json')) throw new Error('simulated crash before completion marker')
        if (!files.delete(from)) throw new Error(`missing temp: ${from}`)
        files.add(to)
      },
      unlinkSync(path) {
        calls.push(['unlink', path])
        files.delete(path)
      },
    },
  }
}

const jsonPath = 'sample.txt.ff.json'
const mdPath = 'sample.txt.ff.md'

const good = fakeFs()
writeArtifactPairAtomic(jsonPath, '{"ok":true}', mdPath, 'body', good.ops)
const renames = good.calls.filter(([kind]) => kind === 'rename').map(([, , to]) => to)
check('Markdown is published before the JSON completion marker', renames.join(',') === `${mdPath},${jsonPath}`, renames.join(','))
check('successful publish leaves both final artifacts', good.files.has(jsonPath) && good.files.has(mdPath), [...good.files].join(','))
check('successful publish leaves no temp files', ![...good.files].some((p) => p.includes('.tmp-')), [...good.files].join(','))

const interrupted = fakeFs({ failJsonRename: true })
let threw = false
try {
  writeArtifactPairAtomic(jsonPath, '{"ok":true}', mdPath, 'body', interrupted.ops)
} catch {
  threw = true
}
check('publish surfaces a completion-marker failure', threw)
check('partial publish never exposes JSON as complete', !interrupted.files.has(jsonPath), [...interrupted.files].join(','))
check('failure cleanup removes both temp files', ![...interrupted.files].some((p) => p.includes('.tmp-')), [...interrupted.files].join(','))

const fallbackMtime = 123456789
check(
  'missing sources use the scanned mtime instead of throwing during terminal bookkeeping',
  sourceMtimeOr('definitely-missing-source.txt', fallbackMtime) === fallbackMtime,
)

if (failures) {
  console.error(`\n${failures} inbox atomic-write check(s) failed`)
  process.exit(1)
}
console.log('\nAll inbox atomic-write checks passed')
