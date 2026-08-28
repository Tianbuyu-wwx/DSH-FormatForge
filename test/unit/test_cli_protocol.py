"""
CLI 协议契约测试（test_cli_protocol.py）

验证 `python -m formatforge` 的 stdout 协议 JSON 形状与退出码。
JS 侧 python-runner 依赖这些契约，改动须同步 PLUGIN_PLAN.md §4.3。
"""

import json
import os
import shutil
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
        assert err["kind"] == "file_not_found"
        assert err["message"]
        assert code == 2

    def test_directory_rejected(self):
        payload, code = run_cli("translate", str(REPO_ROOT / "test"))
        assert payload["ok"] is False
        assert payload["error"]["kind"] == "file_not_found"
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


class TestR3SmartDefault:
    """R3.1: auto 模式下自动附带 quality（无需显式 --quality）。"""

    def test_auto_mode_implicit_quality(self):
        target = FIXTURES / "gbk_chinese.txt"
        if not target.exists():
            pytest.skip("fixture 缺失")
        # 不带 --quality；auto 模式应该自动附 quality
        payload, code = run_cli("translate", str(target), "--type", "auto", "--format", "text")
        assert payload["ok"] is True
        data = payload["data"]
        assert data.get("meta", {}).get("quality_auto") is True, "auto 模式应自动开启 quality"
        assert "quality" in data, "应附 quality 报告"
        assert "overall_score" in data["quality"]
        assert code == 0


class TestR3EncodingRetry:
    """R3.3: --encoding 透传让 quality.actions.retry_with.encoding 真可重调。"""

    def test_encoding_override_redecodes_gbk(self):
        """CLI --encoding gbk 应该用 GBK 重新解码（绕过 chardet 误判）。"""
        target = FIXTURES / "gbk_chinese.txt"
        if not target.exists():
            pytest.skip("fixture 缺失")
        # 强制 gbk 解码（fixture 本身就是 GBK）→ 中文应可读
        payload, code = run_cli(
            "translate", str(target), "--encoding", "gbk", "--format", "text",
        )
        assert payload["ok"] is True
        content = payload["data"]["content"]
        assert "GBK 编码测试文件" in content, f"GBK 重解码失败：{content[:60]!r}"
        assert code == 0

    def test_encoding_action_retry_round_trip(self):
        """模拟 actions.retry_with.encoding 闭环：first pass 不带 encoding → quality.actions;
        second pass 带 encoding → 中文可读。"""
        target = FIXTURES / "gbk_chinese.txt"
        if not target.exists():
            pytest.skip("fixture 缺失")
        # 第一轮：auto，让 chardet 自由判断
        p1, _ = run_cli("translate", str(target), "--type", "auto", "--format", "text")
        q1 = p1["data"].get("quality") or {}
        actions = q1.get("actions") or []
        encoding_actions = [a for a in actions if a.get("code") == "encoding" and a.get("retry_with")]
        # 第二轮：依 retry_with.encoding 重调
        if encoding_actions:
            enc = encoding_actions[0]["retry_with"].get("encoding")
            assert enc in ("gbk", "gb2312", "gb18030")
            p2, _ = run_cli("translate", str(target), "--encoding", enc, "--format", "text")
            assert "GBK 编码测试文件" in p2["data"]["content"]
        else:
            # chardet 在本机已经猜对了 GBK → 不出 encoding action 也属正常
            assert "GBK 编码测试文件" in p1["data"]["content"]


class TestR3MarkdownStructureField:
    """R2.3/R3.x 配套：md 格式输出应有 meta.structured 字段供会话模型识别。"""

    def test_markdown_structured_flag(self):
        target = FIXTURES / "complex_test.pdf"
        if not target.exists():
            pytest.skip("fixture 缺失")
        payload, code = run_cli("translate", str(target), "--format", "markdown")
        assert payload["ok"] is True
        meta = payload["data"]["meta"]
        # meta.structured 是 R2 引入的契约字段；测试必须守住
        assert "structured" in meta
        assert isinstance(meta["structured"], bool)
        assert code == 0


class TestR10LanguageFlag:
    """v0.10.0/B9: --language 写入 meta.target_language + enhance.hint。"""

    def test_language_sets_metadata(self):
        target = FIXTURES / "gbk_chinese.txt"
        if not target.exists():
            pytest.skip("fixture 缺失")
        payload, code = run_cli("translate", str(target), "--language", "en", "--format", "text")
        assert payload["ok"] is True
        meta = payload["data"]["meta"]
        assert meta.get("target_language") == "en"
        # enhance.hint 应提示目标语言
        enhance = payload["data"].get("enhance")
        assert enhance is not None
        assert "en" in enhance.get("hint", "")
        assert code == 0

    def test_language_case_normalized(self):
        target = FIXTURES / "gbk_chinese.txt"
        if not target.exists():
            pytest.skip("fixture 缺失")
        payload, code = run_cli("translate", str(target), "--language", "ZH-CN", "--format", "text")
        assert payload["ok"] is True
        assert payload["data"]["meta"].get("target_language") == "zh-cn"
        assert code == 0


class TestR10OutputFile:
    """v0.10.0/A9: --output-file 把 content 落盘，stdout 协议不变。"""

    def test_output_file_writes_content(self, tmp_path):
        target = FIXTURES / "gbk_chinese.txt"
        if not target.exists():
            pytest.skip("fixture 缺失")
        out_file = tmp_path / "out.txt"
        payload, code = run_cli("translate", str(target), "--format", "text", "--output-file", str(out_file))
        assert payload["ok"] is True
        # stdout 协议不变：content 仍包含转换结果
        assert "GBK 编码测试文件" in payload["data"]["content"]
        # 落盘文件存在且内容等于 content
        assert out_file.exists()
        assert out_file.read_text(encoding="utf-8") == payload["data"]["content"]
        # meta.output_file 字段标记
        assert payload["data"]["meta"].get("output_file") == str(out_file)
        assert code == 0


class TestR10FormatsCategory:
    """v0.10.0/A10: formats --category 按分类过滤。"""

    def test_category_document(self):
        payload, code = run_cli("formats", "--category", "document")
        assert payload["ok"] is True
        d = payload["data"]
        assert d["category"] == "document"
        assert d["count"] >= 5
        # 必须含主文档格式
        assert "pdf" in d["formats"]
        assert "docx" in d["formats"]
        assert "txt" in d["formats"]
        assert code == 0

    def test_category_data(self):
        payload, code = run_cli("formats", "--category", "data")
        assert payload["ok"] is True
        d = payload["data"]
        assert d["category"] == "data"
        assert "csv" in d["formats"]
        assert "xlsx" in d["formats"]
        assert code == 0

    def test_category_invalid(self):
        """argparse choices 校验在 CLI 层拒绝；非 0 退出码 + stderr 信息。"""
        proc = subprocess.run(
            [PY, "-m", "formatforge", "formats", "--category", "no_such_thing"],
            capture_output=True, text=True, cwd=REPO_ROOT, timeout=30,
            env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        )
        assert proc.returncode != 0
        assert "invalid choice" in proc.stderr or "no_such_thing" in proc.stderr

    def test_categories_listed(self):
        payload, _ = run_cli("formats")
        cats = payload["data"].get("categories", [])
        # 必须含这 6 类
        assert {"document", "data", "email", "image", "archive", "audio"} <= set(cats)


class TestR10Batch:
    """v0.10.0/B3: batch 子命令 + --force 重转 + 报告落盘。"""

    def test_batch_basic_run(self, tmp_path):
        in_dir = tmp_path / "in"
        out_dir = tmp_path / "out"
        in_dir.mkdir()
        # 拷两个 fixture（GBK 中文 + 一个 txt）
        shutil.copy(FIXTURES / "gbk_chinese.txt", in_dir / "a.txt")
        shutil.copy(FIXTURES / "gbk_chinese.txt", in_dir / "b.txt")
        payload, code = run_cli(
            "batch", str(in_dir),
            "--out", str(out_dir),
            "--to", "markdown",
            "--workers", "2",
            "--type", "auto",
            "--force",
        )
        assert payload["ok"] is True
        assert payload["total"] == 2
        assert payload["ok_count"] == 2
        assert payload["failed"] == 0
        # 产物存在
        assert (out_dir / "a.md").exists()
        assert (out_dir / "b.md").exists()
        # 报告落盘
        report = out_dir / "_batch_report.json"
        assert report.exists()
        assert code == 0

    def test_batch_skip_existing(self, tmp_path):
        """产物比源新 → 跳过（无需 --force）。"""
        in_dir = tmp_path / "in"
        out_dir = tmp_path / "out"
        in_dir.mkdir()
        shutil.copy(FIXTURES / "gbk_chinese.txt", in_dir / "a.txt")
        # 先跑一次产产物
        run_cli("batch", str(in_dir), "--out", str(out_dir), "--to", "markdown")
        # 第二跑应全跳过
        payload, code = run_cli("batch", str(in_dir), "--out", str(out_dir), "--to", "markdown")
        assert payload["ok"] is True
        assert payload["ok_count"] == 0
        assert payload["skipped"] >= 1
        assert code == 0

    def test_batch_empty_source(self, tmp_path):
        """空目录 → 空报告（v0.10.0/B3: 但 exit != 0，与原契约一致）。"""
        empty = tmp_path / "empty"
        empty.mkdir()
        payload, code = run_cli(
            "batch", str(empty),
            "--out", str(tmp_path / "out"),
            "--to", "markdown",
            "--force",
        )
        assert payload["ok"] is True
        assert payload["total"] == 0
        assert payload["ok_count"] == 0
        # 报告必须落盘（契约）
        assert (tmp_path / "out" / "_batch_report.json").exists()
        assert code != 0  # 空源也算异常（用户期望处理但没匹配）
