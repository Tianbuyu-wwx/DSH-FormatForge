// services/ff-paths.mjs — FormatForge 的路径与环境开关（单一来源，v3.0.0）。
//
// 为什么要单独一个模块：inbox-watcher（写）与 inbox-db（读）都要用这些路径，
// 互相 import 会形成环。这里只有纯函数，谁都能安全依赖。
//
// 与 Python 侧 formatforge/inbox.py::ff_home/db_path/db_disabled 保持同一套语义：
//   FF_HOME          覆盖 <DSH_HOME>/formatforge
//   FF_DB_PATH       覆盖库文件位置（默认 <FF_HOME>/index.db）
//   FF_DB=off        整体停用索引库（回滚开关）

import { join } from 'node:path'
import { homedir } from 'node:os'
import { readdirSync } from 'node:fs'

/** <DSH_HOME>/formatforge（FF_HOME 可覆盖）。 */
export function ffHomeDir() {
  const fromEnv = process.env.DSH_HOME
  const dshHome = fromEnv !== undefined && fromEnv.trim() !== '' ? fromEnv.trim() : join(homedir(), '.dsh')
  return process.env.FF_HOME || join(dshHome, 'formatforge')
}

export function inboxDir() {
  return join(ffHomeDir(), 'inbox')
}

/** 索引库文件（与收件箱同级）。 */
export function dbPath() {
  const override = (process.env.FF_DB_PATH || '').trim()
  return override || join(ffHomeDir(), 'index.db')
}

/** FF_DB=off|0|false|no → 索引库停用。 */
export function dbDisabled() {
  const raw = (process.env.FF_DB || '').trim().toLowerCase()
  return raw === 'off' || raw === '0' || raw === 'false' || raw === 'no'
}

/**
 * 从产物名反查真实源文件名。
 *
 * 产物命名是 `<stem>.ff.json`（stem 丢掉了扩展名，如 `合同.txt` → `合同.ff.json`），
 * 所以真实源名要靠同目录下同 stem 的文件反查。与 Python 侧
 * `formatforge/inbox.py::_resolve_source` 同一策略；等 R6.1.1 的命名
 * （`<name>.<ext>.ff.json`）落地后可以直接解析、不再需要反查。
 *
 * @param {string} dir 收件箱目录
 * @param {string} stem 产物 stem
 * @param {string} [fallback] 已有名字（来自 meta.source_name）；与 stem 不同时直接采用
 */
export function resolveSourceName(dir, stem, fallback) {
  if (fallback && fallback !== stem) return fallback
  try {
    for (const cand of readdirSync(dir).sort()) {
      if (!cand.startsWith(`${stem}.`) || cand.includes('.ff.')) continue
      return cand
    }
  } catch {
    /* 目录不可读：用兜底 */
  }
  return fallback || stem
}
