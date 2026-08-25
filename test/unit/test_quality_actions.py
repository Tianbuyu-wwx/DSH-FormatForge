"""EVOLUTION_PLAN E4 —— 质量报告可操作化 actions 的单元测试。"""

from core.quality_report import QualityReport


class FakePage:
    def __init__(self, raw_text="x", has_table=False):
        self.rawText = raw_text
        self.hasTable = has_table


class FakeParsed:
    def __init__(self, pages):
        self.pages = pages


def _report(content, parsed=None, file_type="pdf", file_size=1000):
    q = QualityReport()
    q.analyze(content=content, file_size=file_size, file_type=file_type, parsed_file=parsed)
    return q


class TestActions:
    def test_no_actions_on_healthy_content(self):
        content = "# 标题\n\n这是一段足够长的正常中文内容。" * 20
        q = _report(content)
        assert q.actions == []

    def test_replacement_chars_suggest_gbk_retry(self):
        content = "正常文字\ufffd\ufffd\ufffd" + "填充" * 50
        q = _report(content)
        enc = [a for a in q.actions if a["code"] == "encoding"]
        assert len(enc) >= 1
        assert enc[0]["retry_with"] == {"encoding": "gbk"}
        assert "U+FFFD" in enc[0]["message"]

    def test_mojibake_suggests_latin1(self):
        content = "Ã©Ã¨Ãª" + "正常" * 60
        q = _report(content)
        enc = [a for a in q.actions if a["code"] == "encoding"]
        assert len(enc) >= 1
        assert enc[0]["retry_with"] == {"encoding": "latin-1"}

    def test_low_coverage_suggests_ocr(self):
        # 二进制式内容 → 覆盖率极低
        content = "ab"
        q = _report(content, file_type="pdf", file_size=50000)
        cov = [a for a in q.actions if a["code"] == "coverage"]
        assert len(cov) >= 1
        assert cov[0]["retry_with"] == {"conversion_type": "ocr"}

    def test_table_sparse_suggests_table_strategy(self):
        pages = [FakePage(has_table=True)]
        parsed = FakeParsed(pages)
        content = "| 表头 |\n|---|\n| 值 |"
        q = QualityReport()
        q.analyze(content=content, file_size=200, file_type="docx", parsed_file=parsed)
        tab = [a for a in q.actions if a["code"] == "table"]
        assert len(tab) >= 1
        assert tab[0]["retry_with"] == {"conversion_type": "table"}

    def test_to_dict_contains_actions(self):
        content = "\ufffd" + "x" * 100
        q = _report(content)
        d = q.to_dict()
        assert "actions" in d
        assert isinstance(d["actions"], list)
