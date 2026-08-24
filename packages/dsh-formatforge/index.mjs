// dsh-formatforge — DSH plugin entry (v0.2).
//
// What this plugin wires:
//   1. Skill provider so `skills/dsh-formatforge/SKILL.md` is discoverable
//      (user can @skill dsh-formatforge to read what it does).
//   2. Python runner bootstrap: resolve interpreter (FF_PYTHON → .venv-fg → PATH)
//      and repo root (walk up from this file; contains formatforge/ + core/).
//   3. Cordis tools: ff_translate, ff_formats.
//   4. Inbox watcher (v0.2): drop files into ~/.dsh/formatforge/inbox/ → auto
//      forge → lightweight notice appended to every live session
//      (FF_INBOX_NOTIFY=false to disable). No full-content injection.

import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { FileSystemSkillProvider } from '@deepseek-ai/dsh-skill-filesystem'
import { createTranslateTool } from './tools/translate.mjs'
import { createFormatsTool } from './tools/formats.mjs'
import { findRepoRoot, resolvePython, DEFAULT_TIMEOUT_MS } from './services/python-runner.mjs'
import { createInboxWatcher, inboxDir } from './services/inbox-watcher.mjs'
import { registerUploadRoute } from './http/upload.mjs'
import { makeNotifier } from './services/notify.mjs'

const VERSION = '0.3.2'

const here = dirname(fileURLToPath(import.meta.url))
const pluginDir = join(here)
const skillDir = join(pluginDir, 'skills')
// packages/dsh-formatforge → 仓库根在两级之上（发布形态下可能不在，则退化为 CWD 探测）
const defaultRepoRoot = findRepoRoot(join(pluginDir, '..', '..'))

export const name = 'dsh-formatforge'
export const inject = ['skills', 'tools', 'sessions', 'agents', 'webServer']

function timeoutFromEnv() {
  const raw = Number(process.env.FF_TIMEOUT_S)
  return Number.isFinite(raw) && raw > 0 ? raw * 1000 : DEFAULT_TIMEOUT_MS
}

function maxBytesFromEnv() {
  const raw = Number(process.env.FF_MAX_BYTES)
  return Number.isFinite(raw) && raw > 0 ? raw : 100 * 1024 * 1024
}

export function apply(ctx) {
  console.log(`[dsh-formatforge v${VERSION}] applying`)

  // 1. skill provider — makes `@skill dsh-formatforge` work
  try {
    ctx.skills.registerProvider(
      (control) => new FileSystemSkillProvider(ctx, control, {
        providerName: 'dsh-formatforge',
        customSkillDirs: [skillDir],
      }),
    )
  } catch (e) {
    console.error(`[dsh-formatforge v${VERSION}] skill provider registration failed:`, (e && e.message) || e)
  }

  // 2. runner bootstrap — resolve python eagerly so first translate call is fast,
  //    but never crash the boot when python is missing (tool surfaces the error).
  const log = (line) => console.log(line)
  let repoRoot = process.env.FF_REPO_ROOT || defaultRepoRoot
  const bootstrap = resolvePython(repoRoot)
  bootstrap.then(
    (py) => console.log(`[dsh-formatforge v${VERSION}] python=${py}, repo_root=${repoRoot}`),
    (e) => console.warn(`[dsh-formatforge v${VERSION}] ${e.message}`),
  )

  // 3. Cordis tools
  try {
    if (ctx.tools && ctx.tools.register) {
      ctx.tools.register(createTranslateTool({ repoRoot, maxBytes: maxBytesFromEnv(), timeoutMs: timeoutFromEnv(), log }))
      ctx.tools.register(createFormatsTool({ repoRoot, log }))
      console.log(`[dsh-formatforge v${VERSION}] tools registered: ff_translate, ff_formats`)
    } else {
      console.warn(`[dsh-formatforge v${VERSION}] ctx.tools not available; tools not registered`)
    }
  } catch (e) {
    console.error(`[dsh-formatforge v${VERSION}] tool registration failed:`, (e && e.message) || e)
  }

  // 4. HTTP routes — browser drop uploads land straight in the inbox.
  try {
    registerUploadRoute(ctx, { maxBytes: maxBytesFromEnv(), log })
  } catch (e) {
    console.error(`[dsh-formatforge v${VERSION}] upload route failed:`, (e && e.message) || e)
  }

  // 5. Inbox watcher — drop files into ~/.dsh/formatforge/inbox/ → auto forge.
  //    Never crashes boot; sessions injection is best-effort.
  try {
    const notifier = makeNotifier({ log })
    const watcher = createInboxWatcher({
      repoRoot,
      maxBytes: maxBytesFromEnv(),
      timeoutMs: timeoutFromEnv(),
      log,
      onDone: (result) => {
        try {
          notifier.broadcast(ctx, notifier.buildNotice(result))
        } catch (e) {
          log(`[dsh-formatforge] notify failed: ${(e && e.message) || e}`)
        }
      },
    })
    watcher.start()
    console.log(`[dsh-formatforge v${VERSION}] inbox watching: ${inboxDir()} (notify=${notifier.enabled})`)
  } catch (e) {
    console.error(`[dsh-formatforge v${VERSION}] inbox watcher init failed:`, (e && e.message) || e)
  }
}
