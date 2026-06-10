"""
Pytest 全局配置和共享 fixtures
"""
import pytest
import os
from datetime import datetime
from unittest.mock import MagicMock, patch

from core.models import (
    ParsedFile, PageContent, ExtractedElement,
    FileType, TaskStatus, ConversionType, OutputFormat,
    FileInfo
)


@pytest.fixture
def mock_ai_client():
    """提供模拟的 AI 客户端"""
    client = MagicMock()
    client.generate_text.return_value = '{"content": "AI enhanced content", "structured_data": {"key": "value"}}'
    return client


@pytest.fixture
def sample_parsed_file():
    """提供示例解析文件"""
    return ParsedFile(
        parseId="test_parse_123",
        fileName="test.pdf",
        fileSize=1024,
        pageCount=1,
        fileType=FileType.PDF,
        pages=[PageContent(
            pageNumber=1,
            elements=[ExtractedElement(elementId="e1", elementType="text", content="Test content")],
            rawText="Test content",
            hasImage=False,
            hasTable=False
        )],
        createdAt=datetime.now(),
        status=TaskStatus.COMPLETED,
        filePath="/tmp/test.pdf"
    )


@pytest.fixture
def sample_text_parsed_file():
    """提供示例文本解析文件"""
    return ParsedFile(
        parseId="test_parse_txt",
        fileName="test.txt",
        fileSize=256,
        pageCount=1,
        fileType=FileType.TXT,
        pages=[PageContent(
            pageNumber=1,
            elements=[ExtractedElement(elementId="e1", elementType="text", content="Hello World")],
            rawText="Hello World",
            hasImage=False,
            hasTable=False
        )],
        createdAt=datetime.now(),
        status=TaskStatus.COMPLETED,
        filePath="/tmp/test.txt"
    )


@pytest.fixture
def sample_table_parsed_file():
    """提供示例表格解析文件"""
    return ParsedFile(
        parseId="test_parse_table",
        fileName="test.csv",
        fileSize=512,
        pageCount=1,
        fileType=FileType.CSV,
        pages=[PageContent(
            pageNumber=1,
            elements=[
                ExtractedElement(elementId="e1", elementType="table", content="Name, Age"),
                ExtractedElement(elementId="e2", elementType="table", content="Alice, 30")
            ],
            rawText="Name, Age\nAlice, 30",
            hasImage=False,
            hasTable=True
        )],
        createdAt=datetime.now(),
        status=TaskStatus.COMPLETED,
        filePath="/tmp/test.csv"
    )


@pytest.fixture
def sample_image_parsed_file():
    """提供示例图片解析文件"""
    return ParsedFile(
        parseId="test_parse_img",
        fileName="test.png",
        fileSize=2048,
        pageCount=1,
        fileType=FileType.IMAGE,
        pages=[PageContent(
            pageNumber=1,
            elements=[ExtractedElement(elementId="e1", elementType="image", content="image.png")],
            rawText="[image]",
            hasImage=True,
            hasTable=False
        )],
        createdAt=datetime.now(),
        status=TaskStatus.COMPLETED,
        filePath="/tmp/test.png"
    )


@pytest.fixture
def sample_file_info():
    """提供示例文件信息"""
    return FileInfo(
        fileName="test.pdf",
        fileSize=1024,
        pageCount=1,
        fileType=FileType.PDF
    )


@pytest.fixture(autouse=True)
def clean_caches():
    """每次测试前清理缓存"""
    # 清理 file_parser 缓存
    from file_parser import FileParser
    from converter_engine import DataConverter

    # 在测试前执行
    yield

    # 测试后清理
    # 注意：这里不能直接从 main 导入，因为可能导致循环导入
    # 实际清理在集成测试中通过 TestFixtures 处理


@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """测试会话开始时设置环境变量"""
    os.environ.setdefault("MINIMAX_API_KEY", "test-key")
    os.environ.setdefault("MINIMAX_BASE_URL", "https://test.api.minimax.chat")
    os.environ.setdefault("AI_PROVIDER", "minimax")
    yield
