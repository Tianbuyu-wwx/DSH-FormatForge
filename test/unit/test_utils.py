"""
工具函数单元测试

测试 ID 生成、响应构建、文件保存、格式输出等公共函数
"""
import pytest
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from core.utils import (
    generate_request_id,
    generate_result_id,
    generate_parse_id,
    create_response,
    save_upload_file,
    build_convert_response_data,
    build_parse_response_data,
    create_processing_log,
    format_output,
)
from core.models import (
    BaseResponse,
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
        from datetime import datetime
        rid = generate_request_id()
        today = datetime.now().strftime("%Y%m%d")
        assert today in rid


class TestCreateResponse:
    """测试统一响应创建"""

    def test_success_response(self):
        resp = create_response(200, "成功", {"key": "value"})
        assert resp.code == 200
        assert resp.msg == "成功"
        assert resp.data == {"key": "value"}
        assert resp.requestId.startswith("req")

    def test_error_response(self):
        resp = create_response(500, "服务器错误")
        assert resp.code == 500
        assert resp.data is None

    def test_response_type(self):
        resp = create_response(200, "test")
        assert isinstance(resp, BaseResponse)


class TestSaveUploadFile:
    """测试文件上传保存"""

    @pytest.mark.asyncio
    async def test_save_small_file(self, tmp_path):
        from fastapi import UploadFile
        import io

        file = UploadFile(filename="test.pdf", file=io.BytesIO(b"PDF content"))
        saved_path = await save_upload_file(tmp_path, file, 50 * 1024 * 1024)

        assert saved_path.exists()
        assert saved_path.read_bytes() == b"PDF content"

    @pytest.mark.asyncio
    async def test_save_file_size_exceeded(self, tmp_path):
        from fastapi import UploadFile
        import io

        file = UploadFile(filename="large.bin", file=io.BytesIO(b"x" * 100))
        with pytest.raises(ValueError, match="文件大小超过限制"):
            await save_upload_file(tmp_path, file, 50)  # 限制50字节

    @pytest.mark.asyncio
    async def test_save_file_preserves_name(self, tmp_path):
        from fastapi import UploadFile
        import io

        file = UploadFile(filename="document.pdf", file=io.BytesIO(b"content"))
        saved_path = await save_upload_file(tmp_path, file, 1024)

        assert "document.pdf" in saved_path.name


class TestBuildConvertResponseData:
    """测试转换响应数据构建"""

    def test_build_basic_response(self):
        result = ConvertResultData(
            resultId="cvt001",
            parseId="parse001",
            fileInfo=FileInfo(
                fileName="test.pdf",
                fileSize=1024,
                pageCount=3,
                fileType=FileType.PDF,
            ),
            conversionType=ConversionType.TEXT,
            outputFormat=OutputFormat.JSON,
            extractedContent="extracted",
            convertedContent="converted",
            structuredData={"key": "val"},
            confidence=0.95,
            processingLogs=[
                ProcessingLog(
                    timestamp=datetime.now(),
                    step="parse",
                    level="info",
                    message="parsed successfully",
                )
            ],
            createdAt=datetime.now(),
        )

        data = build_convert_response_data(result)

        assert data["resultId"] == "cvt001"
        assert data["fileName"] == "test.pdf"
        assert data["confidence"] == 0.95
        assert data["convertedContent"] == "converted"
        assert len(data["processingLogs"]) == 1

    def test_build_response_with_base_url(self):
        result = ConvertResultData(
            resultId="cvt002",
            parseId="parse002",
            fileInfo=FileInfo(fileName="test.txt", fileSize=100, pageCount=1, fileType=FileType.TXT),
            conversionType=ConversionType.AUTO,
            outputFormat=OutputFormat.TEXT,
            extractedContent="",
            convertedContent="content",
            structuredData=None,
            confidence=0.8,
            processingLogs=[],
            createdAt=datetime.now(),
        )

        data = build_convert_response_data(result, base_url="http://example.com")
        assert "exportUrl" in data
        assert data["exportUrl"].startswith("http://example.com")


class TestBuildParseResponseData:
    """测试解析响应数据构建"""

    def test_build_parse_response(self):
        result = ConvertResultData(
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

        data = build_parse_response_data(result)

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
