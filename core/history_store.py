"""
转换历史持久化存储
基于 SQLite 的轻量级历史记录管理
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("history_store")


class HistoryStore:
    """转换历史存储"""

    def __init__(self, db_path: str | Path = "data/history.db"):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        result_id TEXT UNIQUE NOT NULL,
                        file_name TEXT NOT NULL,
                        file_size INTEGER DEFAULT 0,
                        file_type TEXT DEFAULT '',
                        conversion_type TEXT DEFAULT 'auto',
                        output_format TEXT DEFAULT 'json',
                        confidence REAL DEFAULT 0,
                        converted_content TEXT DEFAULT '',
                        structured_data TEXT DEFAULT '{}',
                        strategy TEXT DEFAULT '',
                        from_cache INTEGER DEFAULT 0,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS history_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        history_id INTEGER NOT NULL,
                        step TEXT DEFAULT '',
                        level TEXT DEFAULT 'info',
                        message TEXT DEFAULT '',
                        FOREIGN KEY (history_id) REFERENCES history(id) ON DELETE CASCADE
                    )
                """)
                # 索引
                conn.execute("CREATE INDEX IF NOT EXISTS idx_history_created ON history(created_at DESC)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_history_filetype ON history(file_type)")
                conn.commit()
                logger.info("历史存储初始化完成: %s", self._db_path)
            finally:
                conn.close()

    def save(self, result_data: dict[str, Any]) -> int:
        """保存转换结果到历史记录"""
        with self._lock:
            conn = self._get_conn()
            try:
                now = datetime.now().isoformat()
                structured = json.dumps(result_data.get("structuredData") or {}, ensure_ascii=False)

                cursor = conn.execute(
                    """INSERT OR REPLACE INTO history
                       (result_id, file_name, file_size, file_type, conversion_type,
                        output_format, confidence, converted_content, structured_data,
                        strategy, from_cache, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        result_data.get("resultId", ""),
                        result_data.get("fileName", ""),
                        result_data.get("fileSize", 0),
                        result_data.get("fileType", ""),
                        result_data.get("conversionType", "auto"),
                        result_data.get("outputFormat", "json"),
                        result_data.get("confidence", 0),
                        result_data.get("convertedContent", ""),
                        structured,
                        result_data.get("strategy", ""),
                        1 if result_data.get("decision", {}).get("fromCache") else 0,
                        now,
                    ),
                )
                history_id = cursor.lastrowid

                # 保存日志
                logs = result_data.get("processingLogs") or []
                conn.executemany(
                    "INSERT INTO history_logs (history_id, step, level, message) VALUES (?, ?, ?, ?)",
                    [
                        (
                            history_id,
                            log.get("step", ""),
                            log.get("level", "info"),
                            log.get("message", ""),
                        )
                        for log in logs
                    ],
                )

                conn.commit()
                logger.info("历史记录已保存: result_id=%s, id=%d", result_data.get("resultId", ""), history_id)
                return history_id or 0
            finally:
                conn.close()

    def list(self, limit: int = 50, offset: int = 0, file_type: str | None = None) -> list[dict[str, Any]]:
        """获取历史记录列表"""
        conn = self._get_conn()
        try:
            query = """SELECT id, result_id, file_name, file_size, file_type,
                              conversion_type, output_format, confidence,
                              strategy, from_cache, created_at
                       FROM history"""
            params: list = []
            conditions = []

            if file_type:
                conditions.append("file_type = ?")
                params.append(file_type)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get(self, result_id: str) -> dict[str, Any] | None:
        """获取单条历史记录详情"""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT * FROM history WHERE result_id = ?", (result_id,)).fetchone()
            if not row:
                return None

            record = dict(row)
            # 获取关联日志
            log_rows = conn.execute(
                "SELECT step, level, message FROM history_logs WHERE history_id = ? ORDER BY id", (record["id"],)
            ).fetchall()
            record["processingLogs"] = [dict(lr) for lr in log_rows]

            # 解析 structured_data
            try:
                record["structuredData"] = json.loads(record.get("structured_data", "{}"))
            except (json.JSONDecodeError, TypeError):
                record["structuredData"] = {}

            return record
        finally:
            conn.close()

    def delete(self, result_id: str) -> bool:
        """删除单条历史记录"""
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute("DELETE FROM history WHERE result_id = ?", (result_id,))
                conn.commit()
                deleted = cursor.rowcount > 0
                if deleted:
                    logger.info("历史记录已删除: result_id=%s", result_id)
                return deleted
            finally:
                conn.close()

    def clear(self) -> int:
        """清空所有历史记录"""
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute("DELETE FROM history")
                conn.execute("DELETE FROM history_logs")
                conn.commit()
                count = cursor.rowcount
                logger.info("历史记录已清空: %d 条", count)
                return count
            finally:
                conn.close()

    def count(self, file_type: str | None = None) -> int:
        """获取历史记录总数"""
        conn = self._get_conn()
        try:
            if file_type:
                row = conn.execute("SELECT COUNT(*) FROM history WHERE file_type = ?", (file_type,)).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM history").fetchone()
            return row[0] if row else 0
        finally:
            conn.close()

    def stats(self) -> dict[str, Any]:
        """获取统计信息"""
        conn = self._get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
            by_type = conn.execute(
                "SELECT file_type, COUNT(*) as cnt FROM history GROUP BY file_type ORDER BY cnt DESC"
            ).fetchall()
            avg_conf = conn.execute("SELECT AVG(confidence) FROM history WHERE confidence > 0").fetchone()[0]

            return {
                "total": total,
                "byType": {r["file_type"]: r["cnt"] for r in by_type},
                "avgConfidence": round(avg_conf or 0, 3),
            }
        finally:
            conn.close()


# 全局实例
_history_instance: HistoryStore | None = None


def get_history_store() -> HistoryStore:
    global _history_instance
    if _history_instance is None:
        _history_instance = HistoryStore()
    return _history_instance
