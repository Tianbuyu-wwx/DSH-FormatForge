"""收件箱索引库（SQLite）—— v3.0.0 新增。

设计约束（详见 UI_DB_PLAN.md §3.2 / §4）：

1. **文件为真相源**：`.ff.md` / `.ff.json` 永远留在磁盘上，库只存元数据 + 检索索引，
   可随时删库重建（``inbox reindex``）。
2. **单写者**：只有本模块写库（经 ``python -m formatforge inbox …``）；Node 侧一律只读。
3. **迁移**：``schema_migrations`` 单调版本 + 幂等；每个版本一个函数。
4. **中文检索**：FTS5 必须用 ``trigram``（``unicode61`` 对中文短语命中为 0，实测）。
5. **不引入依赖**：只用标准库 ``sqlite3``。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
DEFAULT_LIMIT = 50
MAX_LIMIT = 500
DEFAULT_EXCERPT_CHARS = 4096
FULL_HASH_LIMIT = 8 * 1024 * 1024  # ≤8MB 全文哈希，超过则首 1MB + 尺寸标记
FTS_MIN_CHARS = 3  # trigram 索引的是 3 字序列：短于此的查询必须走 LIKE

_RESULT_ID_RE = re.compile(r"^cvt(\d{14})")


# ─────────────────────────────── 路径 ───────────────────────────────


def ff_home() -> Path:
    """与 Node 侧 services/inbox-watcher.mjs::ffHome() 保持一致。"""
    ff = os.environ.get("FF_HOME")
    if ff and ff.strip():
        return Path(ff.strip())
    dsh = os.environ.get("DSH_HOME")
    base = Path(dsh.strip()) if dsh and dsh.strip() else Path.home() / ".dsh"
    return base / "formatforge"


def inbox_dir() -> Path:
    return ff_home() / "inbox"


def db_path() -> Path:
    """``FF_DB_PATH`` 可覆盖；默认与收件箱同级（ROADMAP R6.2 的落点）。"""
    override = os.environ.get("FF_DB_PATH")
    if override and override.strip():
        return Path(override.strip())
    return ff_home() / "index.db"


def db_disabled() -> bool:
    """``FF_DB=off`` → 完全回到纯文件路径（回滚开关）。"""
    return (os.environ.get("FF_DB") or "").strip().lower() in {"off", "0", "false", "no"}


# ─────────────────────────────── 连接 ───────────────────────────────


def connect(path: Path | None = None, *, readonly: bool = False) -> sqlite3.Connection:
    target = Path(path) if path is not None else db_path()
    if readonly:
        uri = f"file:{target.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target), timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        if not readonly:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
    except sqlite3.Error:
        pass
    return conn


# ─────────────────────────────── schema ───────────────────────────────


def _migration_1(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS artifacts (
          id             TEXT PRIMARY KEY,
          source_name    TEXT NOT NULL,
          source_ext     TEXT,
          source_path    TEXT,
          source_sha256  TEXT,
          source_bytes   INTEGER,
          source_mtime   INTEGER,
          format         TEXT,
          parser         TEXT,
          file_type      TEXT,
          confidence     REAL,
          enhance_reason TEXT,
          quality_json   TEXT,
          chars          INTEGER,
          elapsed_ms     INTEGER,
          md_path        TEXT,
          json_path      TEXT,
          session_id     TEXT,
          status         TEXT NOT NULL DEFAULT 'ok',
          error_kind     TEXT,
          error_message  TEXT,
          starred        INTEGER NOT NULL DEFAULT 0,
          created_at     INTEGER NOT NULL,
          updated_at     INTEGER NOT NULL,
          retired_at     INTEGER,
          deleted_at     INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_artifacts_created ON artifacts(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_artifacts_sha     ON artifacts(source_sha256);
        CREATE INDEX IF NOT EXISTS idx_artifacts_status  ON artifacts(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_artifacts_parser  ON artifacts(parser);

        CREATE TABLE IF NOT EXISTS tags (
          id    INTEGER PRIMARY KEY AUTOINCREMENT,
          name  TEXT UNIQUE NOT NULL,
          color TEXT
        );
        CREATE TABLE IF NOT EXISTS artifact_tags (
          artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
          tag_id      INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
          PRIMARY KEY (artifact_id, tag_id)
        );

        CREATE TABLE IF NOT EXISTS events (
          id          INTEGER PRIMARY KEY AUTOINCREMENT,
          ts          INTEGER NOT NULL,
          kind        TEXT NOT NULL,
          artifact_id TEXT,
          payload_json TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);

        CREATE TABLE IF NOT EXISTS settings (
          key        TEXT PRIMARY KEY,
          value_json TEXT,
          updated_at INTEGER
        );
        """
    )
    _ensure_fts(conn)


def _ensure_fts(conn: sqlite3.Connection) -> None:
    """建 FTS5 索引表；trigram 不可用时退回 unicode61（中文检索会弱，但功能不塌）。"""
    exists = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='artifacts_fts'").fetchone()
    if exists:
        return
    for tokenizer in ("trigram", "unicode61"):
        try:
            conn.execute(
                f"CREATE VIRTUAL TABLE artifacts_fts USING fts5("
                f"id UNINDEXED, source_name, content, tokenize='{tokenizer}')"
            )
            conn.execute(
                "INSERT INTO settings(key, value_json, updated_at) VALUES(?,?,?)",
                (
                    "fts_tokenizer",
                    json.dumps(tokenizer),
                    int(time.time()),
                ),
            )
            return
        except sqlite3.Error:
            continue


MIGRATIONS = {1: _migration_1}


def migrate(conn: sqlite3.Connection) -> int:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, applied_at INTEGER NOT NULL, checksum TEXT NOT NULL)"
    )
    raw_current = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations").fetchone()["v"]
    current = int(raw_current or 0)
    for version in sorted(MIGRATIONS):
        if version <= current:
            continue
        MIGRATIONS[version](conn)
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at, checksum) VALUES(?,?,?)",
            (version, int(time.time()), f"v{version}"),
        )
        conn.commit()
    return max(current, max(MIGRATIONS))


def fts_tokenizer(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT value_json FROM settings WHERE key='fts_tokenizer'").fetchone()
    try:
        return json.loads(row["value_json"]) if row else "none"
    except (TypeError, ValueError):
        return "none"


# ─────────────────────────────── 哈希 / 解析 ───────────────────────────────


def file_digest(path: Path) -> str | None:
    """内容去重键：≤8MB 全文；更大取首 1MB 并标注尺寸与总量。"""
    try:
        size = path.stat().st_size
        h = hashlib.sha256()
        with path.open("rb") as fh:
            if size <= FULL_HASH_LIMIT:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
                return h.hexdigest()
            h.update(fh.read(1 << 20))
            return f"{h.hexdigest()}:head1mb:{size}"
    except OSError:
        return None


def _created_at_from_id(result_id: str | None, fallback: int) -> int:
    """``cvt+YYYYMMDDHHMMSS+6hex`` → 本地时间戳；解析不了就用文件 mtime。"""
    if result_id:
        m = _RESULT_ID_RE.match(result_id)
        if m:
            try:
                import datetime as _dt

                parsed = _dt.datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
                return int(parsed.timestamp())
            except ValueError:
                pass
    return fallback


def _resolve_source(json_path: Path, stem: str) -> Path | None:
    """产物名丢了源文件扩展名（`合同.txt` → `合同.ff.json`），所以用同目录同 stem 反查。

    v3.0.0 沿用 R6.1.1 之前的命名；等命名方案切到 `<name>.<ext>.ff.json` 后这里可直接解析。
    """
    sibling = json_path.with_name(stem)
    if sibling.is_file():
        return sibling
    try:
        for cand in sorted(json_path.parent.glob(f"{stem}.*")):
            name = cand.name
            if not cand.is_file():
                continue
            if ".ff." in name or name.endswith(".ff"):
                continue
            return cand
    except OSError:
        return None
    return None


def read_artifact(json_path: Path, *, source_path: Path | None = None) -> dict[str, Any] | None:
    """读一份 ``.ff.json``（CLI 协议原文），返回扁平化的索引字段。"""
    try:
        doc = json.loads(Path(json_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    data = doc.get("data") if isinstance(doc, dict) else None
    if not isinstance(data, dict):
        return None
    raw_meta = data.get("meta")
    meta: dict[str, Any] = raw_meta if isinstance(raw_meta, dict) else {}
    stat = None
    with contextlib.suppress(OSError):
        stat = Path(json_path).stat()
    stem = (
        Path(json_path).name[: -len(".ff.json")] if Path(json_path).name.endswith(".ff.json") else Path(json_path).stem
    )
    md_path = Path(json_path).with_name(f"{stem}.ff.md")
    resolved = Path(source_path) if source_path else _resolve_source(Path(json_path), stem)
    source = resolved if resolved and resolved.is_file() else None
    raw_content = data.get("content")
    content: str = raw_content if isinstance(raw_content, str) else ""
    raw_enhance = data.get("enhance")
    enhance: dict[str, Any] = raw_enhance if isinstance(raw_enhance, dict) else {}
    quality = data.get("quality")
    raw_error = doc.get("error") if isinstance(doc, dict) else None
    error: dict[str, Any] = raw_error if isinstance(raw_error, dict) else {}
    result_id = meta.get("result_id") or (doc.get("result_id") if isinstance(doc, dict) else None) or stem
    return {
        "id": str(result_id),
        "source_name": meta.get("source_name") or (source.name if source else stem),
        "source_ext": source.suffix.lower() if source else None,
        "source_path": str(source) if source else None,
        "source_bytes": int(meta.get("file_size") or (source.stat().st_size if source else 0) or 0),
        "source_mtime": int(source.stat().st_mtime) if source else None,
        "format": data.get("format"),
        "parser": meta.get("parser"),
        "file_type": meta.get("file_type") or meta.get("parser"),
        "confidence": meta.get("confidence"),
        "enhance_reason": enhance.get("reason"),
        "quality_json": json.dumps(quality, ensure_ascii=False) if quality else None,
        "chars": len(content),
        "elapsed_ms": meta.get("elapsed_ms"),
        "md_path": str(md_path) if md_path.exists() else None,
        "json_path": str(json_path),
        "session_id": meta.get("session_id"),
        "status": "ok" if doc.get("ok") else "failed",
        "error_kind": error.get("kind"),
        "error_message": error.get("message"),
        "created_at": _created_at_from_id(str(result_id), int(stat.st_mtime) if stat else int(time.time())),
        "updated_at": int(stat.st_mtime) if stat else int(time.time()),
        "excerpt": content[:DEFAULT_EXCERPT_CHARS],
    }


# ─────────────────────────────── 写入 ───────────────────────────────


_UPSERT = """
INSERT INTO artifacts (
  id, source_name, source_ext, source_path, source_sha256, source_bytes, source_mtime,
  format, parser, file_type, confidence, enhance_reason, quality_json, chars, elapsed_ms,
  md_path, json_path, session_id, status, error_kind, error_message,
  starred, created_at, updated_at, retired_at, deleted_at
) VALUES (
  :id, :source_name, :source_ext, :source_path, :source_sha256, :source_bytes, :source_mtime,
  :format, :parser, :file_type, :confidence, :enhance_reason, :quality_json, :chars, :elapsed_ms,
  :md_path, :json_path, :session_id, :status, :error_kind, :error_message,
  0, :created_at, :updated_at, NULL, NULL
)
ON CONFLICT(id) DO UPDATE SET
  source_name=excluded.source_name, source_ext=excluded.source_ext, source_path=excluded.source_path,
  source_sha256=COALESCE(excluded.source_sha256, artifacts.source_sha256),
  source_bytes=excluded.source_bytes, source_mtime=excluded.source_mtime,
  format=excluded.format, parser=excluded.parser, file_type=excluded.file_type,
  confidence=excluded.confidence, enhance_reason=excluded.enhance_reason,
  quality_json=excluded.quality_json, chars=excluded.chars, elapsed_ms=excluded.elapsed_ms,
  md_path=excluded.md_path, json_path=excluded.json_path, session_id=excluded.session_id,
  status=excluded.status, error_kind=excluded.error_kind, error_message=excluded.error_message,
  updated_at=excluded.updated_at, retired_at=NULL, deleted_at=NULL
"""


def upsert_artifact(
    conn: sqlite3.Connection,
    record: dict[str, Any],
    *,
    excerpt: str | None = None,
    content_index: bool = True,
) -> str:
    """写入/更新一条产物索引（幂等）。返回 id。"""
    row = {
        "source_name": "",
        "source_ext": None,
        "source_path": None,
        "source_sha256": None,
        "source_bytes": 0,
        "source_mtime": None,
        "format": None,
        "parser": None,
        "file_type": None,
        "confidence": None,
        "enhance_reason": None,
        "quality_json": None,
        "chars": 0,
        "elapsed_ms": None,
        "md_path": None,
        "json_path": None,
        "session_id": None,
        "status": "ok",
        "error_kind": None,
        "error_message": None,
        "created_at": int(time.time()),
        "updated_at": int(time.time()),
    }
    row.update({k: v for k, v in record.items() if k in row and v is not None})
    row["id"] = record["id"]
    row["source_name"] = record.get("source_name") or record["id"]
    conn.execute(_UPSERT, row)

    try:
        conn.execute("DELETE FROM artifacts_fts WHERE id = ?", (row["id"],))
        if content_index:
            conn.execute(
                "INSERT INTO artifacts_fts(id, source_name, content) VALUES(?,?,?)",
                (row["id"], row["source_name"], (excerpt or "")[:DEFAULT_EXCERPT_CHARS]),
            )
        conn.execute(
            "INSERT INTO events(ts, kind, artifact_id, payload_json) VALUES(?,?,?,?)",
            (int(time.time()), "indexed", row["id"], json.dumps({"status": row["status"]}, ensure_ascii=False)),
        )
    except sqlite3.Error:
        pass
    conn.commit()
    return str(row["id"])


def index_json_file(
    conn: sqlite3.Connection,
    json_path: Path,
    *,
    session_id: str | None = None,
    source_path: Path | None = None,
    content_index: bool = True,
) -> str | None:
    record = read_artifact(Path(json_path), source_path=source_path)
    if record is None:
        return None
    source = record.get("source_path")
    if source:
        record["source_sha256"] = file_digest(Path(source))
    if session_id:
        record["session_id"] = session_id
    return upsert_artifact(conn, record, excerpt=record.get("excerpt"), content_index=content_index)


def reindex(conn: sqlite3.Connection, directory: Path | None = None, *, content_index: bool = True) -> dict[str, Any]:
    """扫描收件箱的 ``*.ff.json`` 回填索引；幂等、非破坏。"""
    target = Path(directory) if directory else inbox_dir()
    scanned = indexed = skipped = 0
    for path in sorted(target.glob("*.ff.json")) if target.exists() else []:
        scanned += 1
        try:
            if index_json_file(conn, path, content_index=content_index):
                indexed += 1
            else:
                skipped += 1
        except sqlite3.Error:
            skipped += 1
    return {"dir": str(target), "scanned": scanned, "indexed": indexed, "skipped": skipped}


# ─────────────────────────────── 查询 ───────────────────────────────


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    # NB: sqlite3.Row 是序列协议（迭代产出"值"），必须用 .keys()，不能用 `for k in row`
    return {k: row[k] for k in row.keys()}  # noqa: SIM118


def query(
    conn: sqlite3.Connection,
    *,
    q: str | None = None,
    fmt: str | None = None,
    parser: str | None = None,
    status: str | None = None,
    since: int | None = None,
    cursor: int | None = None,
    limit: int = DEFAULT_LIMIT,
    include_deleted: bool = False,
) -> dict[str, Any]:
    """结构化筛选 + 全文检索。

    检索策略（v3.0.0）：
    - ``len(q) >= FTS_MIN_CHARS(3)`` → FTS5 trigram（子串匹配，中文可用）；
    - 更短的词（中文里极常见，如「合同」「发票」）trigram 建不出索引 → 退回 ``LIKE``；
    - FTS 命中为 0 时也补一次 LIKE，避免分词边界漏检。
    返回值里的 ``search_mode`` 会说明本次走了哪条路径，便于 UI/排障。
    """
    limit = max(1, min(MAX_LIMIT, int(limit or DEFAULT_LIMIT)))
    term = (q or "").strip()
    select = "SELECT a.* FROM artifacts a "
    where: list[str] = []
    params: list[Any] = []
    if fmt:
        where.append("a.format = ?")
        params.append(fmt)
    if parser:
        where.append("a.parser = ?")
        params.append(parser)
    if status:
        where.append("a.status = ?")
        params.append(status)
    if since:
        where.append("a.created_at >= ?")
        params.append(int(since))
    if not include_deleted:
        where.append("a.deleted_at IS NULL")
    if cursor:
        where.append("a.created_at < ?")
        params.append(int(cursor))

    def run(extra_join: str, extra_where: list[str], extra_params: list[Any]) -> list[dict[str, Any]]:
        clauses = where + extra_where
        sql = select + extra_join + (" WHERE " + " AND ".join(clauses) if clauses else "")
        sql += " ORDER BY a.created_at DESC LIMIT ?"
        return [_row_to_dict(r) for r in conn.execute(sql, [*params, *extra_params, limit + 1]).fetchall()]

    def run_like() -> list[dict[str, Any]]:
        like = f"%{term}%"
        return run(
            "JOIN artifacts_fts f ON f.id = a.id",
            ["(f.source_name LIKE ? OR f.content LIKE ? OR a.id LIKE ?)"],
            [like, like, like],
        )

    mode = "list"
    rows: list[dict[str, Any]] = []
    note: str | None = None
    if term:
        if len(term) >= FTS_MIN_CHARS:
            try:
                rows = run("JOIN artifacts_fts f ON f.id = a.id", ["artifacts_fts MATCH ?"], [_fts_query(term)])
                mode = "fts"
            except sqlite3.Error as exc:
                rows = []
                note = f"fts_error: {exc}"
        if not rows:
            try:
                like_rows = run_like()
            except sqlite3.Error:
                like_rows = []
            if like_rows or mode != "fts":
                rows = like_rows
                mode = "like" if mode != "fts" else "fts+like"
    else:
        rows = run("", [], [])

    out: dict[str, Any] = {
        "rows": rows[:limit],
        "next_cursor": rows[limit]["created_at"] if len(rows) > limit else None,
        "total_returned": min(len(rows), limit),
        "search_mode": mode,
        "fts_min_chars": FTS_MIN_CHARS,
    }
    if note:
        out["note"] = note
    return out


def _fts_query(raw: str) -> str:
    """把用户输入变成安全的 FTS5 短语查询（trigram 下等价于子串匹配）。"""
    safe = raw.replace('"', " ").strip()
    if not safe:
        return '""'
    return '"' + safe + '"'


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    def scalar(sql: str, params: tuple[Any, ...] = ()) -> Any:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None

    by_status = {
        r["status"]: r["n"]
        for r in conn.execute("SELECT status, COUNT(*) AS n FROM artifacts WHERE deleted_at IS NULL GROUP BY status")
    }
    by_format = {
        r["format"] or "?": r["n"]
        for r in conn.execute("SELECT format, COUNT(*) AS n FROM artifacts WHERE deleted_at IS NULL GROUP BY format")
    }
    by_parser = {
        r["parser"] or "?": r["n"]
        for r in conn.execute(
            "SELECT parser, COUNT(*) AS n FROM artifacts WHERE deleted_at IS NULL "
            "GROUP BY parser ORDER BY n DESC LIMIT 20"
        )
    }
    return {
        "db_path": str(db_path()),
        "schema_version": scalar("SELECT COALESCE(MAX(version),0) FROM schema_migrations"),
        "fts_tokenizer": fts_tokenizer(conn),
        "total": scalar("SELECT COUNT(*) FROM artifacts WHERE deleted_at IS NULL") or 0,
        "retired": scalar("SELECT COUNT(*) FROM artifacts WHERE retired_at IS NOT NULL AND deleted_at IS NULL") or 0,
        "deleted": scalar("SELECT COUNT(*) FROM artifacts WHERE deleted_at IS NOT NULL") or 0,
        "chars": scalar("SELECT COALESCE(SUM(chars),0) FROM artifacts WHERE deleted_at IS NULL") or 0,
        "source_bytes": scalar("SELECT COALESCE(SUM(source_bytes),0) FROM artifacts WHERE deleted_at IS NULL") or 0,
        "newest_at": scalar("SELECT MAX(created_at) FROM artifacts WHERE deleted_at IS NULL"),
        "oldest_at": scalar("SELECT MIN(created_at) FROM artifacts WHERE deleted_at IS NULL"),
        "by_status": by_status,
        "by_format": by_format,
        "by_parser": by_parser,
    }


def find_by_digest(conn: sqlite3.Connection, digest: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM artifacts WHERE source_sha256 = ? AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 1",
        (digest,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def set_deleted(conn: sqlite3.Connection, artifact_id: str, deleted: bool = True) -> bool:
    cur = conn.execute(
        "UPDATE artifacts SET deleted_at = ?, updated_at = ? WHERE id = ?",
        (int(time.time()) if deleted else None, int(time.time()), artifact_id),
    )
    conn.commit()
    return cur.rowcount > 0


def mark_retired(conn: sqlite3.Connection, ids: list[str]) -> int:
    now = int(time.time())
    cur = conn.executemany(
        "UPDATE artifacts SET retired_at = ?, updated_at = ? WHERE id = ? AND retired_at IS NULL",
        [(now, now, i) for i in ids],
    )
    conn.commit()
    return cur.rowcount if cur.rowcount is not None and cur.rowcount >= 0 else 0


def prune(conn: sqlite3.Connection) -> dict[str, Any]:
    """把磁盘上已经不存在（retention / 手工删除）的产物标为 retired。

    retention 由 Node 侧 watcher 执行，Python 侧不感知；所以用"文件还在不在"来对齐库。
    """
    rows = conn.execute(
        "SELECT id, json_path FROM artifacts WHERE deleted_at IS NULL AND retired_at IS NULL"
    ).fetchall()
    gone: list[str] = []
    for row in rows:
        path = row["json_path"]
        if not path or not Path(path).exists():
            gone.append(row["id"])
    if gone:
        mark_retired(conn, gone)
    return {"checked": len(rows), "retired": len(gone), "ids": gone[:50]}


def vacuum(conn: sqlite3.Connection) -> dict[str, Any]:
    before = db_path().stat().st_size if db_path().exists() else 0
    conn.execute("VACUUM")
    after = db_path().stat().st_size if db_path().exists() else 0
    return {"before_bytes": before, "after_bytes": after}


def backup(conn: sqlite3.Connection, out: Path) -> dict[str, Any]:
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    conn.execute("VACUUM INTO ?", (str(target),))
    return {"out": str(target), "bytes": target.stat().st_size if target.exists() else 0}


# ─────────────────────────── 面板偏好（settings 表）───────────────────────────
#
# 设计取舍（UI_DB_PLAN.md §3.2 的 A/B 分层）：偏好本来可以走平台的
# `ctx.storageDomain`，但那个域"整域驻内存 + 没有迁移机制"，而我们这里已经有
# 一套带迁移的 SQLite。于是**偏好与索引同库**（settings 表），保持单一可写存储、
# 单一迁移故事；等偏好长成需要与宿主设置界面联动的规模，再按计划迁到 A 层。

DEFAULT_PREFS: dict[str, Any] = {
    "panelLimit": DEFAULT_LIMIT,
    "lang": "zh",
    "contentIndex": True,
}


def get_prefs(conn: sqlite3.Connection) -> dict[str, Any]:
    prefs = dict(DEFAULT_PREFS)
    row = conn.execute("SELECT value_json FROM settings WHERE key='prefs'").fetchone()
    if row and row["value_json"]:
        try:
            stored = json.loads(row["value_json"])
            if isinstance(stored, dict):
                prefs.update({k: v for k, v in stored.items() if k in DEFAULT_PREFS})
        except ValueError:
            pass
    return prefs


def set_prefs(conn: sqlite3.Connection, patch: dict[str, Any]) -> dict[str, Any]:
    clean = {k: v for k, v in (patch or {}).items() if k in DEFAULT_PREFS}
    prefs = get_prefs(conn)
    prefs.update(clean)
    if isinstance(prefs.get("panelLimit"), int):
        prefs["panelLimit"] = max(10, min(MAX_LIMIT, int(prefs["panelLimit"])))
    conn.execute(
        "INSERT INTO settings(key, value_json, updated_at) VALUES('prefs', ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
        (json.dumps(prefs, ensure_ascii=False), int(time.time())),
    )
    conn.commit()
    return prefs


# ─────────────────────────────── CLI ───────────────────────────────


def _emit(payload: dict[str, Any]) -> None:
    """stdout 唯一出口（与 formatforge.__main__ 同约定：单行协议 JSON）。"""
    import sys

    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _ok(data: dict[str, Any]) -> int:
    _emit({"ok": True, "code": 200, "data": data})
    return 0


def _fail(kind: str, message: str, code: int = 4) -> int:
    _emit({"ok": False, "code": 4000 + code, "error": {"kind": kind, "message": message}})
    return code


def register(sub: Any) -> None:
    """挂到 `python -m formatforge inbox …`（v3.0.0 新增子命令）。"""
    p = sub.add_parser("inbox", help="收件箱索引库：状态/检索/回填/备份（SQLite，v3.0.0）")
    sib = p.add_subparsers(dest="inbox_command", required=True)

    p_init = sib.add_parser("init", help="建库并执行迁移")
    p_init.add_argument("--db", default=None, help="覆盖库路径（默认 <FF_HOME>/index.db）")

    p_idx = sib.add_parser("index", help="把已产出的 .ff.json 写入索引（幂等）")
    p_idx.add_argument("--artifact", action="append", default=[], help="产物 .ff.json 路径（可重复）")
    p_idx.add_argument("--source", default=None, help="这一批产物的源文件路径（watcher 直投时给，用于去重键）")
    p_idx.add_argument("--session-id", default=None, help="溯源：触发本次锻造的会话 id")
    p_idx.add_argument("--no-content", action="store_true", help="不建内容索引（只索引元数据）")
    p_idx.add_argument("--db", default=None)

    p_q = sib.add_parser("query", help="结构化筛选 + 全文检索（FTS5 trigram，中文子串可用）")
    p_q.add_argument("--q", default=None, help="全文检索词（子串匹配）")
    p_q.add_argument("--format", dest="fmt", default=None)
    p_q.add_argument("--parser", default=None)
    p_q.add_argument("--status", default=None, choices=["ok", "failed"])
    p_q.add_argument("--since", type=int, default=None, help="created_at 下界（Unix 秒）")
    p_q.add_argument("--cursor", type=int, default=None, help="上一页返回的 next_cursor")
    p_q.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p_q.add_argument("--db", default=None)

    p_st = sib.add_parser("stats", help="库状态统计")
    p_st.add_argument("--db", default=None)

    p_re = sib.add_parser("reindex", help="扫描收件箱回填索引（幂等、非破坏、可删库重建）")
    p_re.add_argument("--dir", default=None, help="收件箱目录（默认 <FF_HOME>/inbox）")
    p_re.add_argument("--no-content", action="store_true")
    p_re.add_argument("--db", default=None)

    p_del = sib.add_parser("delete", help="软删除一条产物索引（不动磁盘文件）")
    p_del.add_argument("--id", required=True)
    p_del.add_argument("--db", default=None)

    p_pr = sib.add_parser("prune", help="把磁盘上已消失的产物标为 retired（与 retention 对齐）")
    p_pr.add_argument("--db", default=None)

    p_dg = sib.add_parser("digest", help="算内容去重键（sha256，≤8MB 全文 / 更大取首 1MB）")
    p_dg.add_argument("--path", required=True)

    p_fd = sib.add_parser("find", help="按去重键查已有产物（拖入秒回用）")
    p_fd.add_argument("--sha256", required=True)
    p_fd.add_argument("--db", default=None)

    p_vc = sib.add_parser("vacuum", help="整理库文件")
    p_vc.add_argument("--db", default=None)

    p_bk = sib.add_parser("backup", help="导出库快照（VACUUM INTO）")
    p_bk.add_argument("--out", required=True)
    p_bk.add_argument("--db", default=None)

    p_pf = sib.add_parser("prefs", help="读取/写入面板偏好（settings 表）")
    p_pf.add_argument("--set", default=None, help="要合并的 JSON，如 '{\"panelLimit\":100}'")
    p_pf.add_argument("--db", default=None)

    p.set_defaults(func=cmd_inbox)


def cmd_inbox(args: Any) -> int:
    if db_disabled() and getattr(args, "inbox_command", None) not in {"digest"}:
        return _fail("db_disabled", "FF_DB=off：索引库已停用（删掉该环境变量即可启用）", 3)

    override = getattr(args, "db", None)
    path = Path(override) if override else db_path()
    cmd = args.inbox_command

    if cmd == "digest":
        target = Path(args.path)
        if not target.exists():
            return _fail("file_not_found", f"文件不存在：{target}", 3)
        return _ok({"path": str(target), "sha256": file_digest(target)})

    try:
        if cmd == "init":
            conn = connect(path)
            version = migrate(conn)
            conn.close()
            return _ok({"db_path": str(path), "schema_version": version})

        conn = connect(path)
        try:
            migrate(conn)
            if cmd == "index":
                paths = [Path(p) for p in args.artifact]
                if not paths:
                    return _fail("bad_request", "至少给一个 --artifact <path.ff.json>", 2)
                ids: list[str] = []
                missed: list[str] = []
                for item in paths:
                    try:
                        got = index_json_file(
                            conn,
                            item,
                            session_id=args.session_id,
                            source_path=Path(args.source) if args.source else None,
                            content_index=not args.no_content,
                        )
                    except sqlite3.Error as exc:
                        return _fail("db_error", f"索引失败：{exc}", 4)
                    (ids if got else missed).append(got or str(item))
                return _ok({"indexed": ids, "skipped": missed, "db_path": str(path)})

            if cmd == "query":
                result = query(
                    conn,
                    q=args.q,
                    fmt=args.fmt,
                    parser=args.parser,
                    status=args.status,
                    since=args.since,
                    cursor=args.cursor,
                    limit=args.limit,
                )
                result["db_path"] = str(path)
                return _ok(result)

            if cmd == "stats":
                return _ok(stats(conn))

            if cmd == "reindex":
                target = Path(args.dir) if args.dir else inbox_dir()
                result = reindex(conn, target, content_index=not args.no_content)
                result["db_path"] = str(path)
                return _ok(result)

            if cmd == "delete":
                gone = set_deleted(conn, args.id, True)
                if not gone:
                    return _fail("not_found", f"索引里没有 {args.id}", 3)
                return _ok({"id": args.id, "deleted": True})

            if cmd == "find":
                row = find_by_digest(conn, args.sha256)
                return _ok({"found": row is not None, "artifact": row})

            if cmd == "prune":
                return _ok(prune(conn))

            if cmd == "vacuum":
                return _ok(vacuum(conn))

            if cmd == "prefs":
                if args.set:
                    try:
                        parsed = json.loads(args.set)
                    except ValueError as exc:
                        return _fail("bad_request", f"--set 不是合法 JSON：{exc}", 2)
                    if not isinstance(parsed, dict):
                        return _fail("bad_request", "--set 需要一个 JSON 对象", 2)
                    return _ok({"prefs": set_prefs(conn, parsed)})
                return _ok({"prefs": get_prefs(conn)})

            if cmd == "backup":
                return _ok(backup(conn, Path(args.out)))
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return _fail("db_error", f"SQLite 错误：{exc}", 4)

    return _fail("bad_request", f"未知的 inbox 子命令：{cmd}", 2)
