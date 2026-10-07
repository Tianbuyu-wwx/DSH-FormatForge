"""
FF-M-pages/audit 回归测试：pdf_options 只转发给真正接受的解析器。

背景：``pages``/``encoding`` 这类跨解析器选项被 ParseStep 放进 ``pdf_options``，
再由 FileParser 盲传 ``**pdf_options``；22 个解析器里只有 PDF/TXT 声明了对应
形参，其余 18 个会 ``TypeError``，随后被 ParseStep 吞掉并退化为 raw 透传垃圾。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


from core.file_parser import FileParser, _accepted_parse_kwargs
from parsers.docx_parser import DOCXParser
from parsers.pdf_parser import PDFParser
from parsers.txt_parser import TXTParser


class TestAcceptedParseKwargs:
    """签名过滤辅助函数本身。"""

    def test_txt_keeps_encoding_drops_pages(self):
        accepted = _accepted_parse_kwargs(TXTParser(), {"pages": "1-3", "encoding": "utf-8"})
        assert accepted == {"encoding": "utf-8"}

    def test_pdf_keeps_pages_drops_encoding(self):
        accepted = _accepted_parse_kwargs(PDFParser(), {"pages": "1-3", "encoding": "utf-8"})
        assert accepted == {"pages": "1-3"}

    def test_parser_without_options_drops_all(self):
        assert _accepted_parse_kwargs(DOCXParser(), {"pages": "1-3", "encoding": "utf-8"}) == {}


class TestNonPdfParserDoesNotTypeError:
    """非 PDF 解析器收到跨解析器选项时不得 TypeError / 退化解析。"""

    def test_txt_with_pages_and_encoding(self, tmp_path):
        path = tmp_path / "note.txt"
        path.write_text("你好，世界\nsecond line\n", encoding="utf-8")

        parsed = FileParser(tmp_path).parse_file(path, "text", {"pages": "1-3", "encoding": "utf-8"})
        assert parsed.pageCount >= 1
        joined = "\n".join(el.content for page in parsed.pages for el in page.elements)
        assert "你好，世界" in joined

    def test_unknown_options_do_not_break_parse(self, tmp_path):
        path = tmp_path / "note.txt"
        path.write_text("plain body\n", encoding="utf-8")

        parsed = FileParser(tmp_path).parse_file(path, "text", {"pages": "1-3", "bogus": 1})
        assert parsed.pageCount >= 1

    def test_dropped_options_are_logged(self, tmp_path, caplog):
        path = tmp_path / "note.txt"
        path.write_text("plain body\n", encoding="utf-8")

        with caplog.at_level("INFO", logger="file_parser"):
            FileParser(tmp_path).parse_file(path, "text", {"pages": "1-3"})
        assert any("不接受选项" in rec.message for rec in caplog.records)
