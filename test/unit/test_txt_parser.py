"""
TXT 解析器单元测试
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.txt_parser import TXTParser


class TestTXTParserBasic:
    """基础测试"""

    def test_supported_extensions(self):
        parser = TXTParser()
        assert ".txt" in parser.supported_extensions
        assert ".md" in parser.supported_extensions
        assert ".log" in parser.supported_extensions

    def test_supported_magic_empty(self):
        parser = TXTParser()
        assert parser.supported_magic == []

    def test_can_parse_txt(self):
        parser = TXTParser()
        assert parser.can_parse(Path("/tmp/test.txt")) == 0.9

    def test_can_parse_non_txt(self):
        parser = TXTParser()
        assert parser.can_parse(Path("/tmp/test.pdf")) == 0.0


class TestTXTParserRealFile:
    """真实文件测试"""

    @pytest.fixture
    def parser(self):
        return TXTParser()

    def test_parse_utf8_txt(self, parser, tmp_path):
        """测试 UTF-8 编码文件"""
        txt_path = tmp_path / "test.txt"
        txt_path.write_text("第一行文本\n\n第二行文本\n\n标题：\n\n列表项1\n列表项2", encoding='utf-8')

        result = parser.parse(txt_path)

        assert len(result) == 1
        assert result[0].pageNumber == 1
        assert "第一行文本" in result[0].rawText
        assert len(result[0].elements) > 0

    def test_parse_gbk_txt(self, parser, tmp_path):
        """测试 GBK 编码文件"""
        txt_path = tmp_path / "test_gbk.txt"
        txt_path.write_text("中文内容\n\n另一段文字", encoding='gbk')

        result = parser.parse(txt_path)

        assert len(result) == 1
        assert "中文内容" in result[0].rawText

    def test_parse_empty_txt(self, parser, tmp_path):
        """测试空文件"""
        txt_path = tmp_path / "empty.txt"
        txt_path.write_text("", encoding='utf-8')

        result = parser.parse(txt_path)

        assert len(result) == 1
        assert result[0].rawText == ""
        assert len(result[0].elements) == 0

    def test_parse_large_txt(self, parser, tmp_path):
        """测试大文件流式解析"""
        txt_path = tmp_path / "large.txt"
        content = "\n\n".join([f"段落 {i}" for i in range(100)])
        txt_path.write_text(content, encoding='utf-8')

        result = parser.parse(txt_path)

        assert len(result) == 1
        assert len(result[0].elements) == 100

    def test_element_types(self, parser, tmp_path):
        """测试元素类型检测"""
        txt_path = tmp_path / "types.txt"
        txt_path.write_text("# Markdown 标题\n\n普通文本段落\n\n1. 列表项\n\n代码块内容", encoding='utf-8')

        result = parser.parse(txt_path)

        types = [e.elementType for e in result[0].elements]
        assert "heading" in types or "text" in types

    def test_detect_encoding_utf8(self, parser, tmp_path):
        """测试 UTF-8 编码检测"""
        txt_path = tmp_path / "utf8.txt"
        txt_path.write_text("UTF-8 内容", encoding='utf-8')

        encoding = parser._detect_encoding(txt_path)
        assert encoding in ('utf-8', 'utf-8-sig')

    def test_detect_encoding_gbk(self, parser, tmp_path):
        """测试 GBK 编码检测"""
        txt_path = tmp_path / "gbk.txt"
        txt_path.write_bytes("\xd6\xd0\xce\xc4".encode('latin-1'))  # GBK 编码的中文字节

        # 直接写入 GBK 编码内容
        txt_path.write_text("中文GBK", encoding='gbk')

        encoding = parser._detect_encoding(txt_path)
        assert encoding == 'gbk'


class TestTXTParserStream:
    """流式解析测试"""

    def test_stream_parse(self, tmp_path):
        parser = TXTParser()
        txt_path = tmp_path / "stream.txt"
        txt_path.write_text("段落1\n\n段落2\n\n段落3", encoding='utf-8')

        results = list(parser.parse_stream(txt_path))

        assert len(results) == 1
        assert len(results[0].elements) == 3


class TestTXTParserEdgeCases:
    """边界情况测试"""

    def test_parse_nonexistent_file(self):
        parser = TXTParser()
        with pytest.raises((ValueError, FileNotFoundError)):
            parser.parse(Path("/tmp/nonexistent.txt"))

    def test_detect_element_type_heading(self):
        parser = TXTParser()
        assert parser._detect_element_type("标题：") == "heading"

    def test_detect_element_type_list(self):
        parser = TXTParser()
        assert parser._detect_element_type("1. 列表项") == "list"

    def test_detect_element_type_code(self):
        parser = TXTParser()
        assert parser._detect_element_type("```python\ncode\n```") == "code"

    def test_detect_element_type_text(self):
        parser = TXTParser()
        assert parser._detect_element_type("普通文本") == "text"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
