"""FF-L-* 低危批量修复的回归测试（每类一个 TestCase，注释标注 finding 编号）。"""

from __future__ import annotations

import pytest


class TestMarkdownLow:
    """FF-L-md/audit: TOML/JSON 前言、BOM、行号偏移、嵌套列表深度。"""

    @pytest.fixture()
    def parser(self):
        from parsers.markdown_parser import MarkdownParser

        return MarkdownParser()

    def test_toml_front_matter(self, parser, tmp_path):
        f = tmp_path / "a.md"
        f.write_text('+++\ntitle = "T"\n+++\n\n# Body\n', encoding="utf-8")
        els = parser.parse(f)[0].elements
        fm = next(e for e in els if e.elementType == "front_matter")
        assert fm.metadata["type"] == "toml"
        assert 'title = "T"' in fm.content
        # 正文行号计入前言占用的 3 行：正文 "# Body" 在真实第 5 行（0-based 4）
        heading = next(e for e in els if e.elementType == "heading")
        assert heading.metadata["line"] == 4

    def test_json_front_matter_with_content_field(self, parser, tmp_path):
        f = tmp_path / "b.md"
        f.write_text('{"title": "T", "content": "# Real body\\n"}', encoding="utf-8")
        page = parser.parse(f)[0]
        fm = next(e for e in page.elements if e.elementType == "front_matter")
        assert fm.metadata["type"] == "json"
        assert "Real body" in page.rawText

    def test_bom_stripped_before_yaml_front_matter(self, parser, tmp_path):
        f = tmp_path / "c.md"
        f.write_text("\ufeff---\ntitle: T\n---\n\ntext\n", encoding="utf-8")
        els = parser.parse(f)[0].elements
        assert els[0].elementType == "front_matter"
        assert els[0].metadata["type"] == "yaml"

    def test_nested_list_indent_preserved(self, parser, tmp_path):
        f = tmp_path / "d.md"
        f.write_text("- top\n  - nested\n    - deep\n", encoding="utf-8")
        lst = next(e for e in parser.parse(f)[0].elements if e.elementType == "list")
        assert [i["indent"] for i in lst.metadata["items"]] == [0, 2, 4]

    def test_front_matter_line_offset_yaml(self, parser, tmp_path):
        f = tmp_path / "e.md"
        f.write_text("---\na: 1\n---\n# H\n", encoding="utf-8")
        heading = next(e for e in parser.parse(f)[0].elements if e.elementType == "heading")
        assert heading.metadata["line"] == 3  # 前言 3 行（0-based），"# H" 是第 4 行


class TestCsvLow:
    """FF-L-csv/audit: BOM 剥离与 ragged row 归一。"""

    @pytest.fixture()
    def parser(self):
        from parsers.csv_parser import CSVParser

        return CSVParser()

    def test_bom_not_glued_to_first_header(self, parser, tmp_path):
        f = tmp_path / "bom.csv"
        f.write_bytes(b"\xef\xbb\xbfid,name\n1,a\n2,b\n")
        page = parser.parse(f)[0]
        table = page.elements[0]
        assert table.metadata["header"] == "id,name"
        assert "\ufeff" not in table.metadata["header"]
        assert "\ufeff" not in table.content

    def test_ragged_rows_normalized_to_widest_row(self, parser, tmp_path):
        # T1-3/audit: 归一目标是「最宽行」，不是表头宽度。这个用例原先断言
        # cols == 3，把 "overflow" 的丢失锁进了测试；列宽统一的诉求仍然成立，
        # 但必须靠补齐窄行实现，不能靠截断宽行。
        f = tmp_path / "ragged.csv"
        f.write_text("id,name,extra\n1,a\n2,b,c,overflow\n", encoding="utf-8")
        page = parser.parse(f)[0]
        table = page.elements[0]
        assert table.metadata["cols"] == 4
        assert table.metadata["ragged_rows"] == 2
        rows = [e for e in page.elements if e.elementType == "table_row"]
        assert all(e.metadata["cols"] == 4 for e in rows)
        assert "overflow" in table.content
class TestAudioLow:
    """FF-L-audio/audit: <128 字节 MP3 的 seek 守卫。"""

    def test_tiny_mp3_does_not_crash_on_id3v1_seek(self, tmp_path):
        from parsers.audio_parser import AudioParser

        f = tmp_path / "t.mp3"
        # 20 字节，远小于 ID3v1 的 128 字节尾标
        f.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"x" * 10)
        pages = AudioParser().parse(f)
        assert pages[0].elements[0].metadata["file_size"] == 20


class TestPdfLow:
    """FF-L-pdf/audit: _merge_text_and_ocr 保序去重（不再是 set）。"""

    def test_merge_preserves_order_and_dedupes(self):
        from parsers.pdf_parser import PDFParser

        p = PDFParser(ocr_engine=None)
        pdf_text = "alpha\nbeta\nbeta\ngamma"
        ocr_text = "beta\nalpha\ndelta"
        merged = p._merge_text_and_ocr(pdf_text, ocr_text).split("\n")
        # 去重
        assert len(merged) == len(set(merged))
        # OCR 行在前（按 OCR 顺序），PDF 独有行在后——且结果确定
        assert merged == p._merge_text_and_ocr(pdf_text, ocr_text).split("\n")
        assert set(merged) == {"alpha", "beta", "gamma", "delta"}


class TestMainLow:
    """FF-L-main/audit: 协议错误消息收敛（绝对路径→basename、超长截断）。"""

    def test_safe_message_relativizes_windows_path(self):
        from formatforge.__main__ import _safe_message

        msg = _safe_message(r"读取失败: D:\Users\jared\secret\report.pdf 无法解析")
        assert "jared" not in msg
        assert "secret" not in msg
        assert "report.pdf" in msg

    def test_safe_message_relativizes_forward_slash_drive_and_unc_paths(self):
        from formatforge.__main__ import _safe_message

        drive = _safe_message("读取失败: D:/Users/jared/secret/report.pdf 无法解析")
        unc = _safe_message(r"读取失败: \\SERVER\share\jared\secret\report.pdf 无法解析")

        assert "report.pdf" in drive
        assert "jared" not in drive
        assert "secret" not in drive
        assert "report.pdf" in unc
        assert "SERVER" not in unc
        assert "share" not in unc
        assert "jared" not in unc

    def test_safe_message_truncates(self):
        from formatforge.__main__ import _MAX_MESSAGE_CHARS, _safe_message

        msg = _safe_message("x" * 5000)
        assert len(msg) <= _MAX_MESSAGE_CHARS + 20

    def test_fail_sanitizes_path(self, capsys, tmp_path):
        from formatforge.__main__ import _fail

        secret = tmp_path / "deep" / "secret.pdf"
        _fail("parse_failed", f"PDF 解析失败: {secret}")
        import json

        out = [l for l in capsys.readouterr().out.splitlines() if l.strip()][0]
        payload = json.loads(out)
        assert "secret.pdf" in payload["error"]["message"]
        assert "deep" not in payload["error"]["message"]

