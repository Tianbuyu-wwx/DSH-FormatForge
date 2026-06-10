"""
单元测试 - 数据模型
测试所有 Pydantic 模型的创建、验证和序列化
"""
import pytest
from datetime import datetime
from core.models import (
    ResponseCode, TaskStatus, ConversionType, OutputFormat, FileType,
    BaseResponse, FileInfo, ExtractedElement, PageContent, ParsedFile,
    ConvertRequest, ConvertResultData, ProcessingLog,
    ConversionStrategyInfo, StrategyScore
)


class TestEnums:
    """测试枚举类型"""

    def test_response_code_values(self):
        assert ResponseCode.SUCCESS == 200
        assert ResponseCode.PARAM_ERROR == 400
        assert ResponseCode.SERVER_ERROR == 500

    def test_task_status_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"

    def test_conversion_type_values(self):
        assert ConversionType.AUTO == "auto"
        assert ConversionType.TEXT == "text"
        assert ConversionType.STRUCTURED == "structured"

    def test_output_format_values(self):
        assert OutputFormat.JSON == "json"
        assert OutputFormat.MARKDOWN == "markdown"
        assert OutputFormat.TEXT == "text"

    def test_file_type_values(self):
        assert FileType.PPT == "ppt"
        assert FileType.PDF == "pdf"
        assert FileType.IMAGE == "image"


class TestBaseResponse:
    """测试基础响应模型"""

    def test_create_success_response(self):
        response = BaseResponse(
            code=200,
            msg="操作成功",
            data={"key": "value"},
            requestId="req123"
        )
        assert response.code == 200
        assert response.msg == "操作成功"
        assert response.data == {"key": "value"}
        assert response.requestId == "req123"

    def test_default_values(self):
        response = BaseResponse(requestId="req456")
        assert response.code == 200
        assert response.msg == "操作成功"
        assert response.data is None

    def test_error_response(self):
        response = BaseResponse(
            code=500,
            msg="服务器错误",
            requestId="req789"
        )
        assert response.code == 500
        assert response.msg == "服务器错误"


class TestFileInfo:
    """测试文件信息模型"""

    def test_create_file_info(self):
        info = FileInfo(
            fileName="test.pdf",
            fileSize=1024,
            pageCount=5,
            fileType=FileType.PDF
        )
        assert info.fileName == "test.pdf"
        assert info.fileSize == 1024
        assert info.pageCount == 5
        assert info.fileType == FileType.PDF

    def test_file_info_serialization(self):
        info = FileInfo(fileName="test.txt", fileSize=100, pageCount=1, fileType=FileType.TXT)
        data = info.model_dump()
        assert data["fileName"] == "test.txt"
        assert data["fileType"] == "txt"


class TestExtractedElement:
    """测试提取元素模型"""

    def test_create_element(self):
        elem = ExtractedElement(
            elementId="elem_1_0",
            elementType="text",
            content="Hello World"
        )
        assert elem.elementId == "elem_1_0"
        assert elem.elementType == "text"
        assert elem.content == "Hello World"
        assert elem.position is None
        assert elem.metadata is None

    def test_element_with_metadata(self):
        elem = ExtractedElement(
            elementId="elem_1_1",
            elementType="image",
            content="Image description",
            metadata={"format": "PNG", "size": [100, 100]}
        )
        assert elem.metadata["format"] == "PNG"


class TestPageContent:
    """测试页面内容模型"""

    def test_create_page(self):
        page = PageContent(
            pageNumber=1,
            elements=[],
            rawText="Test content",
            hasImage=False,
            hasTable=False
        )
        assert page.pageNumber == 1
        assert page.rawText == "Test content"
        assert not page.hasImage
        assert not page.hasTable

    def test_page_with_elements(self):
        elem = ExtractedElement(elementId="e1", elementType="heading", content="Title")
        page = PageContent(
            pageNumber=1,
            elements=[elem],
            rawText="Title",
            hasImage=True,
            hasTable=True
        )
        assert len(page.elements) == 1
        assert page.hasImage
        assert page.hasTable


class TestParsedFile:
    """测试解析文件模型"""

    def test_create_parsed_file(self):
        parsed = ParsedFile(
            parseId="parse123",
            fileName="test.pdf",
            fileSize=2048,
            pageCount=3,
            fileType=FileType.PDF,
            pages=[],
            createdAt=datetime.now(),
            status=TaskStatus.COMPLETED
        )
        assert parsed.parseId == "parse123"
        assert parsed.fileType == FileType.PDF
        assert parsed.status == TaskStatus.COMPLETED

    def test_parsed_file_with_pages(self):
        page = PageContent(pageNumber=1, elements=[], rawText="Content", hasImage=False, hasTable=False)
        parsed = ParsedFile(
            parseId="parse456",
            fileName="test.pptx",
            fileSize=1024,
            pageCount=1,
            fileType=FileType.PPT,
            pages=[page],
            createdAt=datetime.now(),
            status=TaskStatus.COMPLETED
        )
        assert len(parsed.pages) == 1
        assert parsed.pageCount == 1


class TestConvertRequest:
    """测试转换请求模型"""

    def test_create_request(self):
        request = ConvertRequest(
            parseId="parse123",
            conversionType=ConversionType.AUTO,
            outputFormat=OutputFormat.JSON,
            enc="signature123"
        )
        assert request.parseId == "parse123"
        assert request.conversionType == ConversionType.AUTO
        assert request.outputFormat == OutputFormat.JSON
        assert request.customPrompt is None

    def test_request_with_custom_prompt(self):
        request = ConvertRequest(
            parseId="parse456",
            conversionType=ConversionType.TABLE,
            outputFormat=OutputFormat.MARKDOWN,
            customPrompt="Extract all tables",
            enc="signature456"
        )
        assert request.customPrompt == "Extract all tables"
        assert request.conversionType == ConversionType.TABLE


class TestProcessingLog:
    """测试处理日志模型"""

    def test_create_log(self):
        log = ProcessingLog(
            timestamp=datetime.now(),
            level="info",
            message="Test message",
            step="test_step"
        )
        assert log.level == "info"
        assert log.message == "Test message"
        assert log.step == "test_step"


class TestConvertResultData:
    """测试转换结果数据模型"""

    def test_create_result(self):
        file_info = FileInfo(fileName="test.pdf", fileSize=1024, pageCount=1, fileType=FileType.PDF)
        result = ConvertResultData(
            resultId="res123",
            parseId="parse123",
            fileInfo=file_info,
            conversionType=ConversionType.TEXT,
            outputFormat=OutputFormat.JSON,
            extractedContent="Summary",
            convertedContent='{"key": "value"}',
            confidence=0.95,
            processingLogs=[],
            createdAt=datetime.now()
        )
        assert result.resultId == "res123"
        assert result.confidence == 0.95
        assert result.structuredData is None


class TestStrategyModels:
    """测试策略相关模型"""

    def test_conversion_strategy_info(self):
        info = ConversionStrategyInfo(
            strategyId="text_extraction",
            strategyName="纯文本提取",
            description="提取纯文本",
            supportedTypes=[FileType.PDF, FileType.TXT],
            confidence=0.95
        )
        assert info.strategyId == "text_extraction"
        assert len(info.supportedTypes) == 2

    def test_strategy_score(self):
        score = StrategyScore(strategyId="text_extraction", score=0.9, reason="High text content")
        assert score.score == 0.9
        assert score.reason == "High text content"
