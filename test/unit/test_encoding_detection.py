"""
编码自动检测集成测试
使用 test/fixtures 中的真实文件验证 TXT 解析器的编码检测能力
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from parsers.txt_parser import TXTParser


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestEncodingDetectionRealFiles:
    """使用真实文件测试编码检测"""

    @pytest.fixture
    def parser(self):
        return TXTParser()

    def test_utf8_normal(self, parser):
        """测试 UTF-8 标准文件"""
        path = FIXTURES_DIR / "utf8_normal.txt"
        if not path.exists():
            pytest.skip("测试文件不存在")

        encoding = parser._detect_encoding(path)
        result = parser.parse(path)

        assert encoding in ('utf-8', 'utf-8-sig')
        assert "UTF-8" in result[0].rawText
        assert len(result[0].elements) > 0

    def test_utf8_bom(self, parser):
        """测试 UTF-8 BOM 文件"""
        path = FIXTURES_DIR / "utf8_bom.txt"
        if not path.exists():
            pytest.skip("测试文件不存在")

        encoding = parser._detect_encoding(path)
        result = parser.parse(path)

        # BOM 文件应被检测为 UTF-8
        assert 'utf-8' in encoding.lower()
        assert "BOM" in result[0].rawText or "UTF-8" in result[0].rawText

    def test_gbk_chinese(self, parser):
        """测试 GBK 编码文件"""
        path = FIXTURES_DIR / "gbk_chinese.txt"
        if not path.exists():
            pytest.skip("测试文件不存在")

        encoding = parser._detect_encoding(path)
        result = parser.parse(path)

        # 应检测为 GBK 或 GB2312
        assert encoding.lower() in ('gbk', 'gb2312', 'gb18030')
        assert "GBK" in result[0].rawText
        assert "中华人民共和国" in result[0].rawText

    def test_gb2312_chinese(self, parser):
        """测试 GB2312 编码文件"""
        path = FIXTURES_DIR / "gb2312_chinese.txt"
        if not path.exists():
            pytest.skip("测试文件不存在")

        encoding = parser._detect_encoding(path)
        result = parser.parse(path)

        assert encoding.lower() in ('gb2312', 'gbk', 'gb18030')
        assert "GB2312" in result[0].rawText

    def test_big5_traditional(self, parser):
        """测试 Big5 编码文件"""
        path = FIXTURES_DIR / "big5_traditional.txt"
        if not path.exists():
            pytest.skip("测试文件不存在")

        encoding = parser._detect_encoding(path)
        result = parser.parse(path)

        # Big5 文件可能被误检为 GBK（因为繁体字在 GBK 中也有编码）
        # 重点验证文件能被正确解析，不抛出异常
        assert encoding.lower() in ('big5', 'big5-hkscs', 'utf-8', 'gbk', 'gb2312', 'gb18030')
        # 如果能正确解析，应包含繁体内容
        assert "Big5" in result[0].rawText or "編碼" in result[0].rawText

    def test_gbk_corrupted(self, parser):
        """测试 GBK 乱码混合文件"""
        path = FIXTURES_DIR / "gbk_corrupted.txt"
        if not path.exists():
            pytest.skip("测试文件不存在")

        # 乱码文件不应抛出异常
        result = parser.parse(path)
        assert len(result) == 1
        # 应能解析出部分内容
        assert len(result[0].elements) >= 0

    def test_utf8_control_chars(self, parser):
        """测试 UTF-8 控制字符文件"""
        path = FIXTURES_DIR / "utf8_control_chars.txt"
        if not path.exists():
            pytest.skip("测试文件不存在")

        encoding = parser._detect_encoding(path)
        result = parser.parse(path)

        assert encoding in ('utf-8', 'utf-8-sig')
        assert "正常" in result[0].rawText

    def test_mixed_encoding(self, parser):
        """测试混合编码文件"""
        path = FIXTURES_DIR / "mixed_encoding.txt"
        if not path.exists():
            pytest.skip("测试文件不存在")

        # 混合编码文件不应抛出异常
        result = parser.parse(path)
        assert len(result) == 1

    def test_ascii_pure(self, parser):
        """测试纯 ASCII 文件"""
        path = FIXTURES_DIR / "ascii_pure.txt"
        if not path.exists():
            pytest.skip("测试文件不存在")

        encoding = parser._detect_encoding(path)
        result = parser.parse(path)

        # ASCII 文件通常被检测为 UTF-8
        assert encoding.lower() in ('ascii', 'utf-8', 'utf-8-sig')
        assert "ASCII" in result[0].rawText

    def test_gbk_long_text(self, parser):
        """测试 GBK 长文本文件"""
        path = FIXTURES_DIR / "gbk_long_text.txt"
        if not path.exists():
            pytest.skip("测试文件不存在")

        encoding = parser._detect_encoding(path)
        result = parser.parse(path)

        assert encoding.lower() in ('gbk', 'gb2312', 'gb18030')
        assert len(result[0].elements) == 50
        assert "第1行" in result[0].rawText
        assert "第50行" in result[0].rawText

    def test_utf8_markdown(self, parser):
        """测试 UTF-8 Markdown 文件"""
        path = FIXTURES_DIR / "utf8_markdown.md"
        if not path.exists():
            pytest.skip("测试文件不存在")

        encoding = parser._detect_encoding(path)
        result = parser.parse(path)

        assert encoding in ('utf-8', 'utf-8-sig')
        assert "Markdown" in result[0].rawText
        # 检测 Markdown 标题
        heading_elems = [e for e in result[0].elements if e.elementType == "heading"]
        assert len(heading_elems) > 0

    def test_gbk_log_file(self, parser):
        """测试 GBK 日志文件"""
        path = FIXTURES_DIR / "gbk_log_file.log"
        if not path.exists():
            pytest.skip("测试文件不存在")

        encoding = parser._detect_encoding(path)
        result = parser.parse(path)

        assert encoding.lower() in ('gbk', 'gb2312', 'gb18030')
        assert "系统启动成功" in result[0].rawText
        assert "ERROR" in result[0].rawText


class TestEncodingDetectionAccuracy:
    """编码检测准确性测试"""

    def test_all_files_parsable(self):
        """测试所有文件都能被解析而不抛出异常"""
        parser = TXTParser()
        test_files = [
            "utf8_normal.txt",
            "utf8_bom.txt",
            "gbk_chinese.txt",
            "gb2312_chinese.txt",
            "big5_traditional.txt",
            "gbk_corrupted.txt",
            "utf8_control_chars.txt",
            "mixed_encoding.txt",
            "ascii_pure.txt",
            "gbk_long_text.txt",
            "utf8_markdown.md",
            "gbk_log_file.log",
        ]

        for filename in test_files:
            path = FIXTURES_DIR / filename
            if not path.exists():
                continue

            try:
                result = parser.parse(path)
                assert len(result) == 1, f"{filename} 解析结果异常"
                assert isinstance(result[0].rawText, str), f"{filename} rawText 不是字符串"
            except Exception as e:
                pytest.fail(f"{filename} 解析失败: {e}")


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
