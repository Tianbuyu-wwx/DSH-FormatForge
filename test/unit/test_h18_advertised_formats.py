"""
H18/audit 回归测试： advertised-but-broken 格式收缩（Option C）。
.doc/.ppt/.xlsb 无可用解析器——宣称必须收缩，且错误必须是友好的
unsupported_format，而不是误导性的 OLE2 误路由。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent.parent))

import pytest

from parsers import ParserRegistry
from parsers.docx_parser import DOCXParser
from parsers.pptx_parser import PPTXParser
from parsers.xlsx_parser import XLSXParser

OLE2 = b"\xd0\xcf\x11\xe0" + b"\x00" * 8


class TestH18AdvertisedFormatsShrunk:
    """收缩后：解析器不再宣称 .doc/.ppt/.xlsb，OLE2 魔数不再误路由到 DOCX/PPTX。"""

    def test_docx_no_longer_claims_doc(self):
        parser = DOCXParser()
        assert ".doc" not in parser.supported_extensions
        assert OLE2 not in parser.supported_magic

    def test_xlsx_no_longer_claims_xlsb(self):
        parser = XLSXParser()
        assert ".xlsb" not in parser.supported_extensions
        assert ".xls" in parser.supported_extensions  # 有 xlrd 代码路径，保留

    def test_find_best_parser_returns_none_for_shrunk_formats(self, tmp_path):
        """收缩的扩展名必须找不到解析器 → 走 unsupported_format 友好错误。"""
        from parsers import ParserRegistry

        registry = ParserRegistry()
        for name, data in (
            ("legacy.doc", b"\xd0\xcf\x11\xe0" + b"\x00" * 64),
            ("legacy.ppt", b"\xd0\xcf\x11\xe0" + b"\x00" * 64),
            ("book.xlsb", b"\x00" * 64),
        ):
            path = tmp_path / name
            path.write_bytes(data)
            assert registry.find_best_parser(path, data) is None, f"不应有解析器认领 {name}"

    def test_extensionless_ole2_no_longer_routed_to_docx(self, tmp_path):
        """extensionless OLE2 不应再被误路由到 DOCXParser（audit H18 误路由问题）。"""
        from parsers import ParserRegistry

        registry = ParserRegistry()
        ole2 = OLE2 + b"\x00" * 64
        path = tmp_path / "noext"
        path.write_bytes(ole2)
        parser = registry.find_best_parser(path, ole2)
        assert parser is None or type(parser).__name__ != "DOCXParser"


class TestH18UnsupportedKind:
    """收缩后的格式必须走 unsupported_format（exit 3），而不是 parse_failed。"""

    def test_doc_file_reports_unsupported_format(self, tmp_path):
        from formatforge.__main__ import translate_file_data

        path = tmp_path / "legacy.doc"
        path.write_bytes(OLE2 + b"\x00" * 64)
        data, exit_code = translate_file_data(path)
        assert exit_code != 0
        assert data.get("kind") == "unsupported_format"
