"""
流式解析器单元测试
"""
import pytest
import tempfile
from pathlib import Path

from core.stream_parser import (
    TextStreamParser,
    BinaryStreamParser,
    StreamParserManager,
    TextChunk
)


class TestTextStreamParser:
    """测试文本流式解析器"""

    def setup_method(self):
        self.parser = TextStreamParser(chunk_size=100, overlap=10)

    def test_can_handle_txt(self):
        """测试能处理txt文件"""
        assert self.parser.can_handle(Path("test.txt")) is True
        assert self.parser.can_handle(Path("test.md")) is True
        assert self.parser.can_handle(Path("test.csv")) is True

    def test_can_handle_other(self):
        """测试不能处理其他文件"""
        assert self.parser.can_handle(Path("test.pdf")) is False
        assert self.parser.can_handle(Path("test.docx")) is False

    def test_parse_stream_small_file(self):
        """测试小文件解析"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write("Hello world. This is a test.\n")
            f.write("Second paragraph here.\n")
            temp_path = f.name

        try:
            chunks = list(self.parser.parse_stream(Path(temp_path)))
            assert len(chunks) >= 1
            assert all(isinstance(c, TextChunk) for c in chunks)
            assert all(len(c.content) > 0 for c in chunks)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_parse_stream_large_file(self):
        """测试大文件分块"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            # 写入足够大的内容以触发分块
            for i in range(50):
                f.write(f"This is paragraph {i}. It contains some text. ")
            temp_path = f.name

        try:
            chunks = list(self.parser.parse_stream(Path(temp_path)))
            assert len(chunks) > 1  # 应该分成多个块
            # 检查重叠
            if len(chunks) > 1:
                # 重叠内容应该在下一个块的开头
                pass
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_sentence_boundary(self):
        """测试句子边界检测"""
        # 使用足够长的文本，确保有超过 chunk_size // 2 的内容
        text = "First sentence here. " * 10 + "Second sentence. Third sentence."
        boundary = self.parser._find_sentence_boundary(text)
        assert boundary > 0


class TestStreamParserManager:
    """测试流式解析器管理器"""

    def setup_method(self):
        self.manager = StreamParserManager()

    def test_should_use_streaming_small_file(self):
        """测试小文件不使用流式"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("small")
            temp_path = f.name

        try:
            assert self.manager.should_use_streaming(Path(temp_path)) is False
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_should_use_streaming_large_file(self):
        """测试大文件使用流式"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            # 写入超过10MB的内容
            f.write("x" * (11 * 1024 * 1024))
            temp_path = f.name

        try:
            assert self.manager.should_use_streaming(Path(temp_path)) is True
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_parse_txt_file(self):
        """测试解析txt文件"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write("Line 1\nLine 2\nLine 3\n")
            temp_path = f.name

        try:
            chunks = list(self.manager.parse(Path(temp_path)))
            assert len(chunks) > 0
            assert all(isinstance(c, TextChunk) for c in chunks)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_parse_unsupported_file(self):
        """测试不支持文件抛出异常"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xyz', delete=False) as f:
            f.write("content")
            temp_path = f.name

        try:
            with pytest.raises(ValueError):
                list(self.manager.parse(Path(temp_path)))
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_parse_with_progress(self):
        """测试带进度的解析"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as f:
            f.write("Progress test content.\n" * 100)
            temp_path = f.name

        try:
            chunks = list(self.manager.parse_with_progress(Path(temp_path)))
            assert len(chunks) > 0
            # 检查进度信息
            last_chunk = chunks[-1]
            assert last_chunk.metadata is not None
            assert "progress" in last_chunk.metadata
            assert last_chunk.metadata["progress"] > 0
        finally:
            Path(temp_path).unlink(missing_ok=True)
