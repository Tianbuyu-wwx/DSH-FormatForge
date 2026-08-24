"""
工具函数单元测试

测试 ID 生成、文件保存、处理日志、格式输出等公共函数
（HTTP 响应构建相关用例已随 API 层移除）
"""
import pytest
from datetime import datetime
from pathlib import Path

from core.utils import (
    generate_request_id,
    generate_result_id,
    generate_parse_id,
    save_bytes_to_dir,
    build_parse_response_data,
    create_processing_log,
    format_output,
)
from core.models import (
    FileInfo,
    FileType,
    ConvertResultData,
    ConversionType,
    OutputFormat,
    ProcessingLog,
    TaskStatus,
)


class TestIdGeneration:
    """测试 ID 生成函数"""

    def test_generate_request_id_format(self):
        rid = generate_request_id()
        assert rid.startswith("req")
        # 格式: reqYYYYMMDDxxxxxxxx (8位hex)
        assert len(rid) > 10

    def test_generate_result_id_format(self):
        rid = generate_result_id()
        assert rid.startswith("cvt")
        assert len(rid) > 10

    def test_generate_parse_id_format(self):
        pid = generate_parse_id()
        assert pid.startswith("parse")
        assert len(pid) > 10

    def test_ids_are_unique(self):
        ids = set()
        for _ in range(100):
            ids.add(generate_request_id())
            ids.add(generate_result_id())
            ids.add(generate_parse_id())
        # 应该没有碰撞
        assert len(ids) == 300

    def test_request_id_contains_date(self):
        rid = generate_request_id()
        today = datetime.now().strftime("%Y%m%d")
        assert today in rid


class TestSaveBytesToDir:
    """测试字节内容保存（原 save_upload_file 的本地化版本）"""

    def test_save_small_content(self, tmp_path):
        saved_path = save_bytes_to_dir(tmp_path, "test.pdf", b"PDF content", 50 * 1024 * 1024)

        assert saved_path.exists()
        assert saved_path.read_bytes() == b"PDF content"

    def test_save_size_exceeded(self, tmp_path):
        with pytest.raises(ValueError, match="文件大小超过限制"):
            save_bytes_to_dir(tmp_path, "large.bin", b"x" * 100, 50)  # 限制50字节

    def test_save_preserves_name(self, tmp_path):
        saved_path = save_bytes_to_dir(tmp_path, "document.pdf", b"content", 1024)

        assert "document.pdf" in saved_path.name

    def test_save_strips_path_traversal(self, tmp_path):
        saved_path = save_bytes_to_dir(tmp_path, "../../etc/passwd", b"data", 1024)

        # 文件名应只保留 basename，不允许目录穿越
        assert ".." not in saved_path.name
        assert saved_path.parent == tmp_path

    def test_save_none_filename_uses_default(self, tmp_path):
        saved_path = save_bytes_to_dir(tmp_path, None, b"data", 1024)

        assert saved_path.exists()


class TestBuildParseResponseData:
    """测试解析响应数据构建"""

    def _make_result(self) -> ConvertResultData:
        return ConvertResultData(
            resultId="parse001",
            parseId="parse001",
            fileInfo=FileInfo(
                fileName="doc.docx",
                fileSize=2048,
                pageCount=5,
                fileType=FileType.DOC,
            ),
            conversionType=ConversionType.AUTO,
            outputFormat=OutputFormat.JSON,
            extractedContent="",
            convertedContent="",
            structuredData=None,
            confidence=1.0,
            processingLogs=[],
            createdAt=datetime.now(),
        )

    def test_build_parse_response(self):
        data = build_parse_response_data(self._make_result())

        assert data["parseId"] == "parse001"
        assert data["fileInfo"]["fileName"] == "doc.docx"
        assert data["fileInfo"]["fileSize"] == 2048
        assert data["taskStatus"] == TaskStatus.COMPLETED.value


class TestCreateProcessingLog:
    """测试处理日志创建"""

    def test_create_log_default_level(self):
        log = create_processing_log("test_step", "test message")
        assert log.step == "test_step"
        assert log.message == "test message"
        assert log.level == "info"

    def test_create_log_error_level(self):
        log = create_processing_log("error_step", "error occurred", "error")
        assert log.level == "error"
        assert log.step == "error_step"

    def test_create_log_warning_level(self):
        log = create_processing_log("warn_step", "warning message", "warning")
        assert log.level == "warning"

    def test_create_log_type(self):
        log = create_processing_log("step", "msg")
        assert isinstance(log, ProcessingLog)


class TestFormatOutput:
    """测试输出格式化"""

    def test_format_json(self):
        result = format_output("hello world", OutputFormat.JSON, None)
        assert "content" in result
        assert "hello world" in result

    def test_format_json_with_structured_data(self):
        data = {"name": "test", "value": 42}
        result = format_output("", OutputFormat.JSON, data)
        assert '"name"' in result
        assert '"test"' in result

    def test_format_markdown(self):
        result = format_output("plain text", OutputFormat.MARKDOWN)
        assert result.startswith("# 转换结果")

    def test_format_markdown_already_has_header(self):
        result = format_output("# My Title\n\ncontent", OutputFormat.MARKDOWN)
        assert result == "# My Title\n\ncontent"

    def test_format_html(self):
        result = format_output("line1\nline2", OutputFormat.HTML)
        assert "<div class='converted-content'>" in result
        assert "<p>" in result

    def test_format_text(self):
        result = format_output("raw text", OutputFormat.TEXT)
        assert result == "raw text"

    def test_format_output_preserves_content(self):
        """确保格式化不丢失内容"""
        content = "This is a long content with multiple paragraphs.\n\nSecond paragraph."
        for fmt in [OutputFormat.JSON, OutputFormat.MARKDOWN, OutputFormat.HTML, OutputFormat.TEXT]:
            result = format_output(content, fmt)
            assert len(result) > 0
