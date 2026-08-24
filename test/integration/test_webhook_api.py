"""
P2-16 集成测试：Webhook 回调功能
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastapi.testclient import TestClient

from core.webhook_manager import WebhookManager
from main import app

client = TestClient(app)


def test_register_webhook(monkeypatch):
    """测试 webhook 注册"""
    monkeypatch.setattr("core.webhook_manager.validate_url_domain", lambda _url: True)
    resp = client.post("/api/v2/webhook/register", json={
        "task_id": "test-task-001",
        "callback_url": "https://example.com/webhook",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 200
    assert data["data"]["task_id"] == "test-task-001"
    assert data["data"]["status"] == "pending"
    assert "secret" in data["data"]
    print(f"[注册] task_id=test-task-001, secret={data['data']['secret'][:8]}...")


def test_get_webhook_status():
    """测试 webhook 状态查询"""
    resp = client.get("/api/v2/webhook/status/test-task-001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"]["status"] == "pending"
    assert data["data"]["callback_url"] == "https://example.com/webhook"
    print(f"[状态] status={data['data']['status']}")


def test_cancel_webhook():
    """测试 webhook 取消"""
    resp = client.delete("/api/v2/webhook/test-task-001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 200

    # 验证已取消
    resp2 = client.get("/api/v2/webhook/status/test-task-001")
    assert resp2.json()["data"]["status"] == "cancelled"
    print("[取消] 已取消")


def test_webhook_stats():
    """测试 webhook 统计"""
    resp = client.get("/api/v2/webhook/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data["data"]
    assert "by_status" in data["data"]
    print(f"[统计] total={data['data']['total']}, by_status={data['data']['by_status']}")


def test_register_invalid_url():
    """测试无效 URL 拒绝"""
    resp = client.post("/api/v2/webhook/register", json={
        "task_id": "test-002",
        "callback_url": "ftp://invalid.com/webhook",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 400
    print(f"[无效URL] msg={data['msg']}")


@pytest.mark.parametrize(
    "callback_url",
    [
        "http://localhost:8000/internal",
        "http://127.0.0.1/admin",
        "http://10.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
    ],
)
def test_register_blocks_ssrf_targets(callback_url):
    """注册阶段拒绝本机、内网和云元数据地址。"""
    resp = client.post(
        "/api/v2/webhook/register",
        json={"task_id": f"blocked-{callback_url}", "callback_url": callback_url},
    )

    assert resp.status_code == 200
    assert resp.json()["code"] == 400


@pytest.mark.asyncio
async def test_delivery_revalidates_url_before_retry(tmp_path, monkeypatch):
    """DNS/安全判断变化后，后续重试不得再次发出 HTTP 请求。"""
    validation_results = iter([True, True, False])
    monkeypatch.setattr(
        "core.webhook_manager.validate_url_domain",
        lambda _url: next(validation_results),
    )

    post_calls = []

    class FailedResponse:
        status_code = 500
        text = "temporary failure"

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **_kwargs):
            post_calls.append(url)
            return FailedResponse()

    monkeypatch.setattr("core.webhook_manager.httpx.AsyncClient", FakeAsyncClient)

    manager = WebhookManager(tmp_path / "webhooks.db")
    manager.RETRY_BASE_DELAY = 0
    manager.register("retry-task", "https://example.com/webhook")

    result = await manager.deliver("retry-task", {"converted": True})

    assert result["status"] == "failed"
    assert result["attempt"] == 2
    assert "安全校验" in result["error"]
    assert post_calls == ["https://example.com/webhook"]
    assert manager.get_status("retry-task")["status"] == "failed"


def test_not_found():
    """测试不存在的 webhook"""
    resp = client.get("/api/v2/webhook/status/non-existent")
    assert resp.status_code == 200
    assert resp.json()["code"] == 404
    print("[未找到] 404 正确返回")


def test_cancel_not_found():
    """测试取消不存在的 webhook"""
    resp = client.delete("/api/v2/webhook/non-existent-2")
    assert resp.status_code == 200
    assert resp.json()["code"] == 404
    print("[取消失败] 404 正确返回")


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v", "-s", "--tb=short"])
