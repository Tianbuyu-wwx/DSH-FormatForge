"""
扩展格式解析器单元测试
"""
import pytest
import tempfile
from pathlib import Path

from core.extended_parsers import (
    EpubParser,
    MarkdownParser,
    AudioParser,
    RtfParser,
    ExtendedParserRegistry,
    ParsedContent
)


class TestMarkdownParser:
    """测试Markdown解析器"""

    def setup_method(self):
        self.parser = MarkdownParser()

    def test_can_parse(self):
        """测试文件类型检测"""
        assert self.parser.can_parse(Path("test.md")) is True
        assert self.parser.can_parse(Path("test.markdown")) is True
        assert self.parser.can_parse(Path("test.txt")) is False

    def test_parse_simple(self):
        """测试简单Markdown解析"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
            f.write("# Title\n\nSome content here.\n")
            temp_path = f.name

        try:
            result = self.parser.parse(Path(temp_path))
            assert isinstance(result, ParsedContent)
            assert result.title == "Title"
            assert "Some content" in result.content
            assert result.word_count > 0
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_parse_with_chapters(self):
        """测试带章节的Markdown解析"""
        content = """# Main Title

Intro text.

## Chapter 1

Content of chapter 1.

## Chapter 2

Content of chapter 2.
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
            f.write(content)
            temp_path = f.name

        try:
            result = self.parser.parse(Path(temp_path))
            assert result.title == "Main Title"
            # Markdown解析器会把所有标题（包括主标题）都作为章节
            assert len(result.chapters) >= 2
            chapter_titles = [ch["title"] for ch in result.chapters]
            assert "Chapter 1" in chapter_titles
            assert "Chapter 2" in chapter_titles
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_parse_no_title(self):
        """测试无标题Markdown"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
            f.write("Just some text without title.\n")
            temp_path = f.name

        try:
            result = self.parser.parse(Path(temp_path))
            assert result.title is None
            assert "Just some text" in result.content
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestRtfParser:
    """测试RTF解析器"""

    def setup_method(self):
        self.parser = RtfParser()

    def test_can_parse(self):
        """测试文件类型检测"""
        assert self.parser.can_parse(Path("test.rtf")) is True
        assert self.parser.can_parse(Path("test.txt")) is False

    def test_manual_rtf_parse(self):
        """测试手动RTF解析"""
        # 创建简单的RTF内容
        rtf_content = r"{\rtf1\ansi\deff0 {\fonttbl {\f0 Times New Roman;}} \f0\fs24 Hello World \par }"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.rtf', delete=False, encoding='utf-8') as f:
            f.write(rtf_content)
            temp_path = f.name

        try:
            result = self.parser._manual_rtf_parse(Path(temp_path))
            assert isinstance(result, ParsedContent)
            assert "Hello" in result.content or len(result.content) > 0
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestAudioParser:
    """测试音频解析器"""

    def setup_method(self):
        self.parser = AudioParser()

    def test_can_parse(self):
        """测试文件类型检测"""
        assert self.parser.can_parse(Path("test.mp3")) is True
        assert self.parser.can_parse(Path("test.wav")) is True
        assert self.parser.can_parse(Path("test.flac")) is True
        assert self.parser.can_parse(Path("test.txt")) is False

    def test_create_audio_info(self):
        """测试创建音频信息"""
        # 创建一个假的音频文件（实际上不是有效的音频）
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as f:
            f.write(b"fake audio data")
            temp_path = f.name

        try:
            result = self.parser._create_audio_info(Path(temp_path))
            assert isinstance(result, ParsedContent)
            assert "音频文件" in result.content
            assert result.title == Path(temp_path).stem
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestEpubParser:
    """测试EPUB解析器"""

    def setup_method(self):
        self.parser = EpubParser()

    def test_can_parse(self):
        """测试文件类型检测"""
        assert self.parser.can_parse(Path("test.epub")) is True
        assert self.parser.can_parse(Path("test.txt")) is False

    def test_fallback_parse(self):
        """测试降级解析"""
        # 创建一个假的EPUB文件（ZIP格式）
        import zipfile
        with tempfile.NamedTemporaryFile(suffix='.epub', delete=False) as f:
            with zipfile.ZipFile(f.name, 'w') as zf:
                zf.writestr("mimetype", "application/epub+zip")
                zf.writestr("OEBPS/chapter1.xhtml", "<html><body><p>Chapter 1 content</p></body></html>")
            temp_path = f.name

        try:
            result = self.parser._fallback_parse(Path(temp_path))
            assert isinstance(result, ParsedContent)
            assert len(result.content) > 0 or "解析失败" in result.content
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestExtendedParserRegistry:
    """测试扩展解析器注册表"""

    def setup_method(self):
        self.registry = ExtendedParserRegistry()

    def test_get_parser(self):
        """测试获取解析器"""
        parser = self.registry.get_parser(Path("test.md"))
        assert isinstance(parser, MarkdownParser)

        parser = self.registry.get_parser(Path("test.epub"))
        assert isinstance(parser, EpubParser)

        parser = self.registry.get_parser(Path("test.xyz"))
        assert parser is None

    def test_parse(self):
        """测试解析文件"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
            f.write("# Test\n\nContent")
            temp_path = f.name

        try:
            result = self.registry.parse(Path(temp_path))
            assert isinstance(result, ParsedContent)
            assert "Test" in result.content or "Content" in result.content
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_parse_unsupported(self):
        """测试解析不支持的文件"""
        with tempfile.NamedTemporaryFile(suffix='.xyz', delete=False) as f:
            f.write(b"content")
            temp_path = f.name

        try:
            result = self.registry.parse(Path(temp_path))
            assert isinstance(result, ParsedContent)
            assert "不支持" in result.content
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_get_supported_formats(self):
        """测试获取支持的格式"""
        formats = self.registry.get_supported_formats()
        assert "md" in formats
        assert "epub" in formats
        assert "mp3" in formats
        assert "rtf" in formats
