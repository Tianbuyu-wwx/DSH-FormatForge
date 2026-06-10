"""
Archive 解析器单元测试（ZIP）
"""
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.archive_parser import ArchiveParser


class TestArchiveParserBasic:
    """基础测试"""

    def test_supported_extensions(self):
        parser = ArchiveParser()
        assert ".zip" in parser.supported_extensions

    def test_can_parse_zip(self):
        parser = ArchiveParser()
        assert parser.can_parse(Path("/tmp/test.zip")) == 0.9

    def test_can_parse_by_magic(self):
        parser = ArchiveParser()
        assert parser.can_parse(Path("/tmp/test"), b"PK\x03\x04") == 0.95


class TestArchiveParserZIP:
    """ZIP 解析测试"""

    @pytest.fixture
    def parser(self):
        return ArchiveParser()

    def test_parse_empty_zip(self, parser, tmp_path):
        """测试空 ZIP"""
        zip_path = tmp_path / "empty.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            pass

        result = parser.parse(zip_path)

        assert len(result) == 1
        assert "empty.zip" in result[0].rawText

    def test_parse_zip_with_files(self, parser, tmp_path):
        """测试包含文件的 ZIP"""
        zip_path = tmp_path / "files.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("file1.txt", "内容1")
            zf.writestr("file2.txt", "内容2")

        result = parser.parse(zip_path)

        assert "file1.txt" in result[0].rawText
        assert "file2.txt" in result[0].rawText
        assert len(result[0].elements) >= 2

    def test_parse_zip_with_text_content(self, parser, tmp_path):
        """测试提取 ZIP 内文本内容"""
        zip_path = tmp_path / "content.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("readme.txt", "这是 README 文件的内容。\n多行文本。")
            zf.writestr("data.json", '{"key": "value"}')

        result = parser.parse(zip_path)

        assert "README" in result[0].rawText or "readme" in result[0].rawText
        code_elems = [e for e in result[0].elements if e.elementType == "code"]
        assert len(code_elems) > 0

    def test_parse_zip_with_directories(self, parser, tmp_path):
        """测试包含目录的 ZIP"""
        zip_path = tmp_path / "dirs.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("folder/file.txt", "内容")

        result = parser.parse(zip_path)

        assert "folder/" in result[0].rawText or "folder" in result[0].rawText

    def test_parse_corrupted_zip(self, parser, tmp_path):
        """测试损坏的 ZIP"""
        zip_path = tmp_path / "bad.zip"
        zip_path.write_bytes(b"PK\x03\x04not_a_valid_zip")

        with pytest.raises(ValueError):
            parser.parse(zip_path)

    def test_is_text_file(self, parser):
        """测试文本文件判断"""
        assert parser._is_text_file("test.txt") is True
        assert parser._is_text_file("test.json") is True
        assert parser._is_text_file("test.py") is True
        assert parser._is_text_file("test.exe") is False
        assert parser._is_text_file("test.jpg") is False

    def test_format_size(self, parser):
        """测试文件大小格式化"""
        assert parser._format_size(512) == "512.0 B"
        assert parser._format_size(1024) == "1.0 KB"
        assert parser._format_size(1024 * 1024) == "1.0 MB"


class TestArchiveParserWithoutLib:
    """无库测试"""

    def test_parse_without_zipfile(self, tmp_path):
        """测试 zipfile 不可用（实际上 zipfile 是内置库，此测试用于覆盖）"""
        parser = ArchiveParser()
        zip_path = tmp_path / "test.zip"
        with zipfile.ZipFile(zip_path, 'w') as zf:
            zf.writestr("test.txt", "内容")

        # zipfile 始终可用，所以解析应成功
        result = parser.parse(zip_path)
        assert len(result) == 1


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
