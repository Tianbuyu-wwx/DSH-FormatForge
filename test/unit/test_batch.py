"""EVOLUTION_PLAN N3 —— batch 命令的单元测试（协议契约 + 续跑 + 汇总）。"""

import json

import pytest

from formatforge.batch import cmd_batch


@pytest.fixture()
def sample_dir(tmp_path):
    """3 个可转换文本文件 + 1 个不支持的扩展名。"""
    d = tmp_path / "docs"
    d.mkdir()
    (d / "a.txt").write_text("alpha content", encoding="utf-8")
    (d / "b.txt").write_text("beta content", encoding="utf-8")
    (d / "c.md").write_text("# gamma\n\ngamma body", encoding="utf-8")
    (d / "skipme.xyz").write_text("binary-ish", encoding="utf-8")
    return d


class _Args:
    def __init__(self, source, out, **kw):
        self.source = str(source)
        self.out = str(out)
        self.format = kw.get("format", "markdown")
        self.type = kw.get("type", "auto")
        self.workers = kw.get("workers", 2)
        self.recursive = kw.get("recursive", False)
        self.quality = kw.get("quality", False)
        self.pages = kw.get("pages", None)
        self.force = kw.get("force", False)


def _run(tmp_path, sample_dir, **kw):
    out = tmp_path / "out"
    code = cmd_batch(_Args(sample_dir, out, **kw))
    report = json.loads((out / "_batch_report.json").read_text(encoding="utf-8"))
    return code, report, out


class TestBatch:
    def test_converts_supported_files_only(self, tmp_path, sample_dir):
        code, report, out = _run(tmp_path, sample_dir)
        # .xyz 不在支持清单
        assert report["total"] == 3
        assert report["ok_count"] == 3
        assert report["failed"] == 0
        assert code == 0
        assert (out / "a.md").exists()
        assert not (out / "skipme.md").exists()

    def test_markdown_output_contains_content(self, tmp_path, sample_dir):
        _, _, out = _run(tmp_path, sample_dir)
        body = (out / "a.md").read_text(encoding="utf-8")
        assert "alpha" in body

    def test_resume_skips_existing(self, tmp_path, sample_dir):
        code1, r1, out = _run(tmp_path, sample_dir)
        assert r1["ok_count"] == 3
        # 第二轮：产物已存在 → 全部 skipped
        code2, r2, _ = _run(tmp_path, sample_dir)
        assert r2["skipped"] == 3
        assert r2["ok_count"] == 0

    def test_force_reconverts(self, tmp_path, sample_dir):
        _run(tmp_path, sample_dir)
        code, report, _ = _run(tmp_path, sample_dir, force=True)
        assert report["ok_count"] == 3
        assert report["skipped"] == 0
        assert code == 0

    def test_empty_source_reports_not_found(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        code, report, out = _run(tmp_path, empty)
        assert report["total"] == 0
        assert code != 0

    def test_glob_source(self, tmp_path, sample_dir):
        code, report, out = _run(tmp_path, sample_dir.glob("*.txt") and sample_dir / "*.txt")
        assert report["total"] == 2
        assert report["ok_count"] == 2

    def test_summary_protocol_shape(self, tmp_path, sample_dir):
        _, report, _ = _run(tmp_path, sample_dir)
        for key in ("total", "ok", "failed", "skipped", "failures", "elapsed_ms", "avg_confidence"):
            assert key in report
