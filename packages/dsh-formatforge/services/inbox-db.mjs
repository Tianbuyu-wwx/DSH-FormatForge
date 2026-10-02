// services/inbox-db.mjs — 收件箱索引库的**只读**访问层（v3.0.0）。
//
// 分层（见 UI_DB_PLAN.md §3.2）：
//   - 写：只有 Python 侧（`python -m formatforge inbox …`）写库，Node 永不写。
//   - 读：首选 Node 内置 `node:sqlite`（Node ≥ 22.5 免 flag；宿主实测 Node 24.18.1）。
//     拿不到内置模块或库文件不存在时，退回 spawn `python -m formatforge inbox query`，
//     两条路径返回同一形状，调用方无感（ROADMAP R6.2 的保守路径）。
//
// 查询语义与 formatforge/inbox.py::query 对齐：
//   - 检索词 ≥ 3 字 → FTS5 trigram；< 3 字或 FTS 无命中 → LIKE 兜底（中文短词必需）。
//   - 过滤：format / parser / status / since / cursor（created_at 倒序游标分页）。
//
// 安全：只读打开（`readOnly: true`），并对 SQL 参数做白名单化，避免把用户输入拼进 SQL。

import { existsSync } from 'node:fs'
import { dbDisabled, dbPath, inboxDir } from './ff-paths.mjs'
import { runFormatForge } from './python-runner.mjs'

export { dbDisabled, dbPath }

export const FTS_MIN_CHARS = 3
export const DEFAULT_LIMIT = 50
export const MAX_LIMIT = 500

let cachedModule
/** 探测内置 node:sqlite；返回 null 表示不可用（不抛错）。 */
function sqliteModule() {
  if (cachedModule !== undefined) return cachedModule
  cachedModule = null
  try {
    const mod = typeof process.getBuiltinModule === 'function' ? process.getBuiltinModule('node:sqlite') : null
    if (mod && typeof mod.DatabaseSync === 'function') cachedModule = mod
  } catch {
    cachedModule = null
  }
  return cachedModule
}

export function sqliteSupport() {
  const mod = sqliteModule()
  if (!mod) return { available: false, reason: 'node:sqlite unavailable', db_path: dbPath() }
  if (!existsSync(dbPath())) return { available: false, reason: 'index.db not found', db_path: dbPath() }
  return { available: true, reason: 'ok', db_path: dbPath() }
}

function clampLimit(value) {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return DEFAULT_LIMIT
  return Math.max(1, Math.min(MAX_LIMIT, Math.trunc(n)))
}

/** 把外部输入收敛成允许的过滤值（防 SQL 注入 + 防脏查询）。 */
function sanitizeFilters(options = {}) {
  const str = (v, max = 120) => {
    if (v === undefined || v === null) return null
    const s = String(v).trim()
    return s ? s.slice(0, max) : null
  }
  return {
    q: str(options.q, 200),
    fmt: str(options.format ?? options.fmt, 40),
    parser: str(options.parser, 80),
    status: str(options.status, 20),
    since: Number.isFinite(Number(options.since)) && Number(options.since) > 0 ? Math.trunc(Number(options.since)) : null,
    cursor: Number.isFinite(Number(options.cursor)) && Number(options.cursor) > 0 ? Math.trunc(Number(options.cursor)) : null,
    limit: clampLimit(options.limit),
  }
}

function ftsPhrase(raw) {
  return `"${String(raw).replace(/"/g, ' ').trim()}"`
}

/** 只读句柄（内部）；调用方用 queryArtifacts/stats，不要直接持有。 */
function openReader() {
  const mod = sqliteModule()
  if (!mod || !existsSync(dbPath())) return null
  try {
    return new mod.DatabaseSync(dbPath(), { readOnly: true })
  } catch {
    return null
  }
}

function rowsToObjects(rows) {
  return rows.map((r) => ({ ...r }))
}

/**
 * 按 result_id 取一行（只读）。
 *
 * 这是「id → 产物文件」的**首选**路径：库里有 `json_path`，与产物正文多大无关。
 * 曾经的实现是扫产物文件前 64KB 找 `"result_id": "…"`，而 payload 里 `content` 在前、
 * `meta.result_id` 在后 —— 正文超过 ~64K 字符的产物就反查不到，面板点它一律 404。
 *
 * @param {string} id  result_id（或它的前缀，与 ff_result 的前缀语义一致）
 * @param {object} [opts] { prefix = true } 精确未命中时是否允许前缀匹配
 * @returns {object|null} 命中行（含 json_path/source_name），未命中或库不可用时 null
 */
export function findArtifactById(id, { prefix = true } = {}) {
  const raw = String(id || '').trim()
  if (!raw || raw.length > 200) return null
  if (dbDisabled()) return null
  const db = openReader()
  if (!db) return null
  try {
    const exact = db.prepare('SELECT * FROM artifacts WHERE id = ? LIMIT 1').get(raw)
    if (exact) return toClientRow(rowsToObjects([exact])[0])
    if (!prefix) return null
    const like = db.prepare('SELECT * FROM artifacts WHERE id LIKE ? ORDER BY id LIMIT 1').get(`${raw.replace(/[%_\\]/g, '')}%`)
    return like ? toClientRow(rowsToObjects([like])[0]) : null
  } catch {
    return null
  } finally {
    try {
      db.close()
    } catch {
      /* noop */
    }
  }
}

function runQuery(db, filters, mode) {
  const where = []
  const params = []
  if (filters.fmt) {
    where.push('a.format = ?')
    params.push(filters.fmt)
  }
  if (filters.parser) {
    where.push('a.parser = ?')
    params.push(filters.parser)
  }
  if (filters.status) {
    where.push('a.status = ?')
    params.push(filters.status)
  }
  if (filters.since) {
    where.push('a.created_at >= ?')
    params.push(filters.since)
  }
  where.push('a.deleted_at IS NULL')
  if (filters.cursor) {
    where.push('a.created_at < ?')
    params.push(filters.cursor)
  }
  let join = ''
  if (mode === 'fts') {
    join = 'JOIN artifacts_fts f ON f.id = a.id'
    where.push('artifacts_fts MATCH ?')
    params.push(ftsPhrase(filters.q))
  } else if (mode === 'like') {
    join = 'JOIN artifacts_fts f ON f.id = a.id'
    where.push('(f.source_name LIKE ? OR f.content LIKE ? OR a.id LIKE ?)')
    const like = `%${filters.q}%`
    params.push(like, like, like)
  }
  const sql =
    `SELECT a.* FROM artifacts a ${join}` +
    (where.length ? ` WHERE ${where.join(' AND ')}` : '') +
    ' ORDER BY a.created_at DESC LIMIT ?'
  return rowsToObjects(db.prepare(sql).all(...params, filters.limit + 1))
}

/**
 * 把库里的原始行（DB 列名 + unix 秒）归一成面板消费的客户端形状。
 *
 * 不做这一步，面板读 `source/size_bytes/forged_at` 会全部落空 —— 列表显示产物 id 而不是文件名、
 * 大小与时间为空。旧形状（`source`/`size_bytes`/`forged_at` 已是 ISO）原样透传，两种来源都能用。
 */
export function toClientRow(row) {
  if (!row || typeof row !== 'object') return row
  const created = row.created_at ?? row.forged_at ?? null
  let forgedAt = row.forged_at ?? null
  if (forgedAt === null || forgedAt === undefined) {
    // 库里的 created_at 是 unix 秒；毫秒数（>= 1e12）与 ISO 字符串都兼容
    if (typeof created === 'number' && Number.isFinite(created)) forgedAt = new Date(created < 1e12 ? created * 1000 : created).toISOString()
    else if (typeof created === 'string' && created.trim() !== '') forgedAt = created
  }
  return {
    ...row,
    source: row.source_name || row.source || null,
    size_bytes: row.source_bytes ?? row.size_bytes ?? null,
    forged_at: forgedAt,
  }
}

/**
 * 查询产物。
 * @returns {Promise<{rows:object[], next_cursor:number|null, total_returned:number, search_mode:string, source:string}>}
 */
export async function queryArtifacts(options = {}, { repoRoot, timeoutMs, log } = {}) {
  const filters = sanitizeFilters(options)
  const db = dbDisabled() ? null : openReader()
  if (db) {
    try {
      const modes = []
      if (filters.q) modes.push(filters.q.length >= FTS_MIN_CHARS ? 'fts' : 'like')
      if (filters.q && filters.q.length >= FTS_MIN_CHARS) modes.push('like') // FTS 空命中时补漏
      else if (!filters.q) modes.push('list')
      let rows = []
      let used = modes[0] || 'list'
      for (const mode of modes.length ? modes : ['list']) {
        rows = runQuery(db, filters, mode)
        used = mode
        if (rows.length > 0 || mode === 'list') break
      }
      return {
        rows: rows.slice(0, filters.limit).map(toClientRow),
        next_cursor: rows.length > filters.limit ? rows[filters.limit].created_at : null,
        total_returned: Math.min(rows.length, filters.limit),
        search_mode: used,
        source: 'sqlite',
      }
    } catch (e) {
      log?.(`[ff-db] sqlite query failed, falling back to CLI: ${e.message}`)
    } finally {
      try {
        db.close()
      } catch {
        /* noop */
      }
    }
  }
  return cliQuery(filters, { repoRoot, timeoutMs, log })
}

async function cliQuery(filters, { repoRoot, timeoutMs, log } = {}) {
  const args = ['inbox', 'query', '--limit', String(filters.limit)]
  if (filters.q) args.push('--q', filters.q)
  if (filters.fmt) args.push('--format', filters.fmt)
  if (filters.parser) args.push('--parser', filters.parser)
  if (filters.status) args.push('--status', filters.status)
  if (filters.since) args.push('--since', String(filters.since))
  if (filters.cursor) args.push('--cursor', String(filters.cursor))
  const res = await runFormatForge({ cliArgs: args, repoRoot, stdinText: null, timeoutMs, log })
  if (!res.ok) {
    return { rows: [], next_cursor: null, total_returned: 0, search_mode: 'unavailable', source: 'cli', error: res.error }
  }
  const data = res.data || {}
  return {
    rows: Array.isArray(data.rows) ? data.rows.map(toClientRow) : [],
    next_cursor: data.next_cursor ?? null,
    total_returned: data.total_returned ?? 0,
    search_mode: data.search_mode || 'list',
    source: 'cli',
    db_path: data.db_path,
  }
}

/** 库状态统计；sqlite 不可用或库不存在时返回 {available:false}。 */
export async function dbStats({ repoRoot, timeoutMs, log } = {}) {
  const db = dbDisabled() ? null : openReader()
  if (db) {
    try {
      const one = (sql, ...p) => {
        const row = db.prepare(sql).get(...p)
        return row ? Object.values(row)[0] : null
      }
      const grouped = (sql) => Object.fromEntries(db.prepare(sql).all().map((r) => [Object.values(r)[0] ?? '?', Object.values(r)[1]]))
      return {
        available: true,
        source: 'sqlite',
        db_path: dbPath(),
        schema_version: one('SELECT COALESCE(MAX(version),0) FROM schema_migrations'),
        fts_tokenizer: (() => {
          const row = db.prepare("SELECT value_json FROM settings WHERE key='fts_tokenizer'").get()
          return row ? JSON.parse(row.value_json) : null
        })(),
        total: one('SELECT COUNT(*) FROM artifacts WHERE deleted_at IS NULL') ?? 0,
        deleted: one('SELECT COUNT(*) FROM artifacts WHERE deleted_at IS NOT NULL') ?? 0,
        retired: one('SELECT COUNT(*) FROM artifacts WHERE retired_at IS NOT NULL AND deleted_at IS NULL') ?? 0,
        chars: one('SELECT COALESCE(SUM(chars),0) FROM artifacts WHERE deleted_at IS NULL') ?? 0,
        source_bytes: one('SELECT COALESCE(SUM(source_bytes),0) FROM artifacts WHERE deleted_at IS NULL') ?? 0,
        newest_at: one('SELECT MAX(created_at) FROM artifacts WHERE deleted_at IS NULL'),
        oldest_at: one('SELECT MIN(created_at) FROM artifacts WHERE deleted_at IS NULL'),
        by_status: grouped('SELECT status, COUNT(*) FROM artifacts WHERE deleted_at IS NULL GROUP BY status'),
        by_format: grouped('SELECT COALESCE(format, \'?\'), COUNT(*) FROM artifacts WHERE deleted_at IS NULL GROUP BY format'),
        by_parser: grouped('SELECT COALESCE(parser, \'?\'), COUNT(*) FROM artifacts WHERE deleted_at IS NULL GROUP BY parser ORDER BY 2 DESC LIMIT 20'),
        inbox: inboxDir(),
      }
    } catch (e) {
      log?.(`[ff-db] sqlite stats failed: ${e.message}`)
    } finally {
      try {
        db.close()
      } catch {
        /* noop */
      }
    }
  }
  const res = await runFormatForge({ cliArgs: ['inbox', 'stats'], repoRoot, stdinText: null, timeoutMs, log }).catch(
    (e) => ({ ok: false, error: { kind: 'internal', message: (e && e.message) || 'runner failed' } }),
  )
  if (!res.ok) return { available: false, source: 'none', reason: res.error?.message || 'unavailable', db_path: dbPath() }
  return { available: true, source: 'cli', inbox: inboxDir(), ...(res.data || {}) }
}

/**
 * 读取面板偏好（settings 表）。与索引同库：单一可写存储 + 单一迁移故事。
 * @returns {Promise<{panelLimit:number, lang:string, contentIndex:boolean, source:string}>}
 */
export const DEFAULT_PREFS = { panelLimit: DEFAULT_LIMIT, lang: 'zh', contentIndex: true }

export async function dbPrefs({ repoRoot, timeoutMs, log } = {}) {
  const db = dbDisabled() ? null : openReader()
  if (db) {
    try {
      const row = db.prepare("SELECT value_json FROM settings WHERE key='prefs'").get()
      const stored = row ? JSON.parse(row.value_json) : {}
      return { ...DEFAULT_PREFS, ...(stored && typeof stored === 'object' ? stored : {}), source: 'sqlite' }
    } catch (e) {
      log?.(`[ff-db] sqlite prefs failed: ${e.message}`)
    } finally {
      try {
        db.close()
      } catch {
        /* noop */
      }
    }
  }
  const res = await runFormatForge({ cliArgs: ['inbox', 'prefs'], repoRoot, stdinText: null, timeoutMs, log }).catch(
    () => ({ ok: false }),
  )
  if (res.ok && res.data && res.data.prefs) return { ...DEFAULT_PREFS, ...res.data.prefs, source: 'cli' }
  return { ...DEFAULT_PREFS, source: 'default' }
}

/** 写入偏好（必须走 CLI：单写者约定）。 */
export async function savePrefs(patch, { repoRoot, timeoutMs, log } = {}) {
  const res = await runFormatForge({
    cliArgs: ['inbox', 'prefs', '--set', JSON.stringify(patch || {})],
    repoRoot,
    stdinText: null,
    timeoutMs,
    log,
  }).catch(() => ({ ok: false, error: { message: 'runner failed' } }))
  if (!res.ok) return { ok: false, error: res.error || { message: 'save failed' } }
  return { ok: true, prefs: { ...DEFAULT_PREFS, ...(res.data?.prefs || {}) } }
}

/**
 * 内容去重：按 sha256 找已有产物（拖入秒回）。
 * 优先 sqlite，其次 CLI；都不可用时返回 null（调用方继续正常锻造）。
 */
export async function findByDigest(digest, { repoRoot, timeoutMs, log } = {}) {
  if (!digest) return null
  const db = dbDisabled() ? null : openReader()
  if (db) {
    try {
      const row = db
        .prepare('SELECT * FROM artifacts WHERE source_sha256 = ? AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1')
        .get(String(digest))
      return row ? { ...row } : null
    } catch (e) {
      log?.(`[ff-db] sqlite digest lookup failed: ${e.message}`)
    } finally {
      try {
        db.close()
      } catch {
        /* noop */
      }
    }
  }
  const res = await runFormatForge({
    cliArgs: ['inbox', 'find', '--sha256', String(digest)],
    repoRoot,
    stdinText: null,
    timeoutMs,
    log,
  })
  if (!res.ok) return null
  return res.data?.artifact || null
}
