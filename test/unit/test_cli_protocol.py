"""
CLI 协议契约测试（test_cli_protocol.py）

验证 `python -m formatforge` 的 stdout 协议 JSON 形状与退出码。
JS 侧 python-runner 依赖这些契约，改动须同步 PLUGIN_PLAN.md §4.3。
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PY = sys.executable
FIXTURES = REPO_ROOT / "test" / "fixtures"


def run_cli(*args: str, stdin: str | None = None) -> tuple[dict, int]:
    env_pythonpath = str(REPO_ROOT)
    proc = subprocess.run(
        [PY, "-m", "formatforge", *args],
        capture_output=True,
        text=True,
        input=stdin,
        cwd=REPO_ROOT,
        timeout=180,
        # 未 pip install 时也能找到 formatforge 包（与 pythonpath=["."] 一致）
        env={**os.environ, "PYTHONPATH": env_pythonpath},
    )
    # stdout 首行必须是合法协议 JSON
    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    assert lines, f"stdout 为空。stderr={proc.stderr[-500:]}"
    payload = json.loads(lines[0])
    assert isinstance(payload, dict)
    assert "ok" in payload and "code" in payload
    return payload, proc.returncode


class TestVersion:
    def test_version_ok(self):
        payload, code = run_cli("version")
        assert payload["ok"] is True
        assert payload["code"] == 200
        assert payload["data"]["name"] == "dsh-formatforge"
        assert code == 0


class TestFormats:
    def test_formats_lists_supported(self):
        payload, code = run_cli("formats")
        assert payload["ok"] is True
        data = payload["data"]
        assert data["count"] > 20
        for fmt in ("pdf", "docx", "xlsx", "pptx", "eml", "toml", "csv"):
            assert fmt in data["formats"]
        assert "json" in data["output_formats"]
        assert code == 0


class TestTranslateText:
    def test_stdin_text_ok(self):
        payload, code = run_cli(
            "translate", "--stdin-text", "--format", "text",
            stdin="Hello FormatForge\n第二行",
        )
        assert payload["ok"] is True
        data = payload["data"]
        assert isinstance(data["content"], str) and len(data["content"]) > 0
        assert data["format"] == "text"
        meta = data["meta"]
        assert {"parser", "file_size", "elapsed_ms"} <= set(meta)
        assert code == 0

    def test_txt_file_conversion(self):
        target = FIXTURES / "gbk_chinese.txt"
        if not target.exists():
            pytest.skip("fixture 缺失")
        payload, code = run_cli("translate", str(target), "--format", "text")
        assert payload["ok"] is True
        assert "GBK 编码测试文件" in payload["data"]["content"]
        assert code == 0


class TestTranslateErrors:
    def test_missing_file(self):
        payload, code = run_cli("translate", "/no/such/file.docx")
        assert payload["ok"] is False
        err = payload["error"]
        assert err["kind"] == "not_found"
        assert err["message"]
        assert code == 2

    def test_directory_rejected(self):
        payload, code = run_cli("translate", str(REPO_ROOT / "test"))
        assert payload["ok"] is False
        assert payload["error"]["kind"] == "not_found"
        assert code == 2


@pytest.mark.slow
class TestTranslatePdf:
    def test_pdf_with_enhance_hint(self):
        """扫描件应触发 image_only 增强提示（PLUGIN_PLAN §6）"""
        target = FIXTURES / "image_only_test.pdf"
        if not target.exists():
            pytest.skip("fixture 缺失")
        payload, code = run_cli("translate", str(target), "--format", "markdown")
        assert payload["ok"] is True
        enhance = payload["data"].get("enhance")
        assert enhance is not None
        assert enhance["needed"] is True
        assert enhance["reason"] == "image_only"
        assert "扫描件" in enhance["hint"] or "文字层" in enhance["hint"]
        assert code == 0
