"""
Webhook 回调管理器

功能：
1. 注册 webhook URL（关联到转换任务）
2. 异步投递转换结果到回调 URL
3. 失败重试（最多 3 次，指数退避）
4. HMAC-SHA256 签名验证
5. SQLite 持久化状态
"""
import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("webhook")


class WebhookStatus:
    PENDING = "pending"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WebhookManager:
    """Webhook 管理器"""

    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 2  # 秒
    TIMEOUT = 30  # 秒

    def __init__(self, db_path: str | Path = "data/webhooks.db"):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._secret = secrets.token_hex(32)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS webhooks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT UNIQUE NOT NULL,
                        callback_url TEXT NOT NULL,
                        secret TEXT DEFAULT '',
                        status TEXT DEFAULT 'pending',
                        retry_count INTEGER DEFAULT 0,
                        last_error TEXT DEFAULT '',
                        result_snapshot TEXT DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        delivered_at TEXT DEFAULT ''
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_webhooks_status ON webhooks(status)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_webhooks_task ON webhooks(task_id)")
                conn.commit()
                logger.info("Webhook 存储初始化完成: %s", self._db_path)
            finally:
                conn.close()

    # ==================== 注册 ====================

    def register(self, task_id: str, callback_url: str, secret: str = "") -> dict[str, Any]:
        """注册 webhook"""
        # 验证 URL
        parsed = urlparse(callback_url)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"不支持的 URL 协议: {parsed.scheme}")
        if not parsed.netloc:
            raise ValueError("无效的 URL: 缺少主机名")

        now = datetime.now().isoformat()
        webhook_secret = secret or secrets.token_hex(16)

        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO webhooks
                       (task_id, callback_url, secret, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (task_id, callback_url, webhook_secret, WebhookStatus.PENDING, now, now)
                )
                conn.commit()
                logger.info("Webhook 已注册: task_id=%s, url=%s", task_id, callback_url)
            finally:
                conn.close()

        return {
            "task_id": task_id,
            "callback_url": callback_url,
            "status": WebhookStatus.PENDING,
            "secret": webhook_secret,
        }

    # ==================== 投递 ====================

    def _sign_payload(self, payload: bytes, secret: str) -> str:
        """HMAC-SHA256 签名"""
        return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    async def deliver(self, task_id: str, result: dict[str, Any]) -> dict[str, Any]:
        """异步投递转换结果到回调 URL"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM webhooks WHERE task_id = ?", (task_id,)
            ).fetchone()

            if not row:
                logger.warning("Webhook 未找到: task_id=%s", task_id)
                return {"status": "not_found", "task_id": task_id}

            if row["status"] == WebhookStatus.CANCELLED:
                return {"status": "cancelled", "task_id": task_id}

            # 标记为投递中
            conn.execute(
                "UPDATE webhooks SET status = ?, updated_at = ? WHERE task_id = ?",
                (WebhookStatus.DELIVERING, datetime.now().isoformat(), task_id)
            )
            conn.commit()

            callback_url = row["callback_url"]
            secret = row["secret"]

            # 准备 payload
            payload = {
                "task_id": task_id,
                "status": "completed",
                "timestamp": datetime.now().isoformat(),
                "data": result,
            }
            payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            signature = self._sign_payload(payload_bytes, secret)

            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "X-Webhook-Signature": f"sha256={signature}",
                "X-Webhook-Task-Id": task_id,
                "User-Agent": "DataFormatTranslator/1.4",
            }

            # 指数退避重试
            last_error = ""
            for attempt in range(1, self.MAX_RETRIES + 1):
                try:
                    async with httpx.AsyncClient(timeout=self.TIMEOUT) as client:
                        response = await client.post(callback_url, content=payload_bytes, headers=headers)

                    if 200 <= response.status_code < 300:
                        # 成功
                        delivered_at = datetime.now().isoformat()
                        conn.execute(
                            """UPDATE webhooks
                               SET status = ?, retry_count = ?, delivered_at = ?, updated_at = ?
                               WHERE task_id = ?""",
                            (WebhookStatus.DELIVERED, attempt, delivered_at, delivered_at, task_id)
                        )
                        conn.commit()
                        logger.info(
                            "Webhook 投递成功: task_id=%s, attempt=%d, status=%d",
                            task_id, attempt, response.status_code
                        )
                        return {
                            "status": "delivered",
                            "task_id": task_id,
                            "attempt": attempt,
                            "http_status": response.status_code,
                        }

                    # 非 2xx 响应
                    last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                    logger.warning(
                        "Webhook 投递失败: task_id=%s, attempt=%d, status=%d",
                        task_id, attempt, response.status_code
                    )

                except httpx.TimeoutException:
                    last_error = f"超时 ({self.TIMEOUT}s)"
                    logger.warning("Webhook 投递超时: task_id=%s, attempt=%d", task_id, attempt)
                except Exception as e:
                    last_error = str(e)[:500]
                    logger.warning("Webhook 投递异常: task_id=%s, attempt=%d, error=%s", task_id, attempt, e)

                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_BASE_DELAY * (2 ** (attempt - 1))
                    logger.info("Webhook 重试等待: task_id=%s, delay=%ds", task_id, delay)
                    await asyncio.sleep(delay)

            # 全部重试失败
            conn.execute(
                """UPDATE webhooks
                   SET status = ?, retry_count = ?, last_error = ?, updated_at = ?
                   WHERE task_id = ?""",
                (WebhookStatus.FAILED, self.MAX_RETRIES, last_error, datetime.now().isoformat(), task_id)
            )
            conn.commit()
            logger.error("Webhook 投递最终失败: task_id=%s, error=%s", task_id, last_error)

            return {
                "status": "failed",
                "task_id": task_id,
                "attempt": self.MAX_RETRIES,
                "error": last_error,
            }

        finally:
            conn.close()

    # ==================== 查询 ====================

    def get_status(self, task_id: str) -> dict[str, Any] | None:
        """获取 webhook 状态"""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM webhooks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if not row:
                return None
            return dict(row)
        finally:
            conn.close()

    def list_pending(self) -> list[dict[str, Any]]:
        """列出所有待投递的 webhook"""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM webhooks WHERE status IN (?, ?) ORDER BY created_at",
                (WebhookStatus.PENDING, WebhookStatus.DELIVERING)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    # ==================== 取消 ====================

    def cancel(self, task_id: str) -> bool:
        """取消 webhook"""
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "UPDATE webhooks SET status = ?, updated_at = ? WHERE task_id = ? AND status = ?",
                    (WebhookStatus.CANCELLED, datetime.now().isoformat(), task_id, WebhookStatus.PENDING)
                )
                conn.commit()
                cancelled = cursor.rowcount > 0
                if cancelled:
                    logger.info("Webhook 已取消: task_id=%s", task_id)
                return cancelled
            finally:
                conn.close()

    # ==================== 统计 ====================

    def stats(self) -> dict[str, Any]:
        """获取统计信息"""
        conn = self._get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM webhooks").fetchone()[0]
            by_status = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM webhooks GROUP BY status"
            ).fetchall()
            return {
                "total": total,
                "by_status": {r["status"]: r["cnt"] for r in by_status},
            }
        finally:
            conn.close()


# 全局实例
_webhook_instance: WebhookManager | None = None


def get_webhook_manager() -> WebhookManager:
    global _webhook_instance
    if _webhook_instance is None:
        _webhook_instance = WebhookManager()
    return _webhook_instance