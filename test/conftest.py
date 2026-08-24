"""
共享测试 fixtures

为 Pipeline 各 Step 的单元测试提供统一的 mock 对象工厂。
"""
import os

import pytest

# 必须在首次导入 core.*（config 在导入期读环境变量）之前设置：
# RateLimitMiddleware 按 client_ip 进程内全局计数（默认 60 次/分钟），全量跑测试时
# 所有集成测试共享同一 TestClient 来源，累计超限误触发 429，造成跨文件污染。
# 用 setdefault：外部显式设置的 RATE_LIMIT_ENABLED 仍然优先生效。
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
from datetime import datetime
from unittest.mock import MagicMock, PropertyMock

from core.models import (
    ConversionType, OutputFormat, FileType, ConvertResultData,
    ParsedFile, PageContent, FileInfo, ProcessingLog, TaskStatus,
)
from core.pipeline import PipelineContext
from core.input_adapters import InputData
from core.format_detector import DataFormat, FormatDetectionResult
from core.decision_engine import ConversionDecision


# ════════════════════ PipelineContext ════════════════════

@pytest.fixture
def basic_ctx():
    """最小的有效 PipelineContext"""
    return PipelineContext(
        source=b"test data",
        conversion_type=ConversionType.AUTO,
        output_format=OutputFormat.JSON,
        custom_prompt=None,
        use_ai_enhance=True,
        target_ai_endpoint=None,
        target_ai_key=None,
        target_ai_provider=None,
    )


@pytest.fixture
def ctx_with_ai():
    """带有目标 AI 信息的 PipelineContext"""
    return PipelineContext(
        source=b"test data",
        conversion_type=ConversionType.AUTO,
        output_format=OutputFormat.MARKDOWN,
        custom_prompt="请转换为中文",
        use_ai_enhance=True,
        target_ai_endpoint="https://api.example.com/v1",
        target_ai_key="sk-test-key",
        target_ai_provider="openai",
    )


@pytest.fixture
def ctx_no_enhance():
    """AI 增强关闭的 PipelineContext"""
    return PipelineContext(
        source=b"raw data",
        conversion_type=ConversionType.TEXT,
        output_format=OutputFormat.TEXT,
        custom_prompt=None,
        use_ai_enhance=False,
        target_ai_endpoint=None,
        target_ai_key=None,
        target_ai_provider=None,
    )


# ════════════════════ InputData ════════════════════

@pytest.fixture
def input_data():
    """标准 InputData fixture"""
    return InputData(
        source_type="raw",
        data=b"Hello World",
        filename="test.txt",
        mime_type="text/plain",
    )


@pytest.fixture
def file_input_data():
    """文件类型 InputData"""
    return InputData(
        source_type="file",
        data=b"%PDF-1.4 mock pdf content",
        filename="document.pdf",
        mime_type="application/pdf",
    )


@pytest.fixture
def url_input_data():
    """URL 类型 InputData"""
    return InputData(
        source_type="url",
        data=b"<html><body>web content</body></html>",
        filename="page.html",
        mime_type="text/html",
    )


# ════════════════════ FormatDetectionResult ════════════════════

@pytest.fixture
def detected_result():
    """检测为 TXT 格式的结果"""
    return FormatDetectionResult(
        format=DataFormat.TXT,
        mime_type="text/plain",
        confidence=0.5,
        extension=".txt",
    )


@pytest.fixture
def detected_pdf():
    """检测为 PDF 格式的结果"""
    return FormatDetectionResult(
        format=DataFormat.PDF,
        mime_type="application/pdf",
        confidence=0.95,
        extension=".pdf",
    )


# ════════════════════ ParsedFile ════════════════════

@pytest.fixture
def parsed_file():
    """标准 ParsedFile fixture"""
    return ParsedFile(
        parseId="parse_001",
        fileName="test.txt",
        fileSize=100,
        pageCount=1,
        fileType=FileType.TXT,
        pages=[
            PageContent(
                pageNumber=1,
                elements=[],
                rawText="Hello World content",
                hasImage=False,
                hasTable=False,
            )
        ],
        createdAt=datetime.now(),
        status=TaskStatus.COMPLETED,
    )


@pytest.fixture
def parsed_pdf():
    """PDF ParsedFile fixture"""
    return ParsedFile(
        parseId="parse_pdf_001",
        fileName="document.pdf",
        fileSize=1024,
        pageCount=3,
        fileType=FileType.PDF,
        pages=[
            PageContent(pageNumber=1, elements=[], rawText="Page 1 content.", hasImage=False, hasTable=False),
            PageContent(pageNumber=2, elements=[], rawText="Page 2 with table.", hasImage=False, hasTable=True),
            PageContent(pageNumber=3, elements=[], rawText="Page 3 content.", hasImage=True, hasTable=False),
        ],
        createdAt=datetime.now(),
        status=TaskStatus.COMPLETED,
    )


# ════════════════════ ConversionDecision ════════════════════

@pytest.fixture
def decision_convert():
    """需要转换的决策"""
    return ConversionDecision(
        input_format="txt",
        conversion_needed=True,
        target_format="text",
        strategies=["text_extraction"],
        preserve_original=False,
    )


@pytest.fixture
def decision_noop():
    """无需转换的决策"""
    return ConversionDecision(
        input_format="txt",
        conversion_needed=False,
        target_format="text",
        strategies=[],
        preserve_original=True,
    )


# ════════════════════ Mock Pipeline ════════════════════

@pytest.fixture
def mock_pipeline():
    """模拟 ConversionPipeline，提供 Step 所需的接口"""
    pipeline = MagicMock()
    pipeline.result_cache = {}
    pipeline._cache_timestamps = {}
    pipeline._cache_lock = MagicMock()
    pipeline._max_cache_size = 100
    pipeline._cache_ttl = 3600
    pipeline._content_cache = MagicMock()
    pipeline._content_cache.get.return_value = None
    pipeline._content_cache.set.return_value = None

    # decision_engine
    pipeline.decision_engine = MagicMock()
    pipeline.decision_engine.build_recommendation.return_value = "请将转换后的文本发送给目标AI。"

    # prompt_manager (用于 EnhanceStep)
    pipeline.prompt_manager = MagicMock()
    pipeline.ai_client = MagicMock()

    # 缓存方法
    pipeline._add_to_cache = MagicMock()
    pipeline._try_get_cached = MagicMock(return_value=None)
    pipeline._try_store_cached = MagicMock()

    return pipeline


# ════════════════════ Sub-system Mocks ════════════════════

@pytest.fixture
def mock_input_manager():
    """模拟 InputAdapterManager"""
    mgr = MagicMock()
    mgr.read.return_value = InputData(
        source_type="raw", data=b"test data", filename="test.txt",
    )
    return mgr


@pytest.fixture
def mock_detector():
    """模拟 FormatDetector"""
    detector = MagicMock()
    detector.detect.return_value = FormatDetectionResult(
        format=DataFormat.TXT, mime_type="text/plain", confidence=0.5,
    )
    return detector


@pytest.fixture
def mock_ai_discovery():
    """模拟 AiDiscovery"""
    from core.ai_discovery import AiCapabilities
    discovery = MagicMock()
    discovery.discover.return_value = AiCapabilities(
        provider="openai",
        model="gpt-4",
        supported_inputs=[],
        max_tokens=8192,
        supports_function_calling=True,
    )
    return discovery


@pytest.fixture
def mock_decision_engine():
    """模拟 DecisionEngine"""
    engine = MagicMock()
    engine.make_decision.return_value = ConversionDecision(
        input_format="txt",
        conversion_needed=True,
        target_format="text",
        strategies=["text_extraction"],
    )
    engine.build_recommendation.return_value = "recommendation text"
    return engine


@pytest.fixture
def mock_strategy_registry(monkeypatch):
    """模拟 strategy_registry 全局单例"""
    from unittest.mock import MagicMock

    strategy = MagicMock()
    strategy.strategy_id = "text_extraction"
    strategy.strategy_name = "文本提取"
    strategy.convert.return_value = {
        "content": "converted text",
        "structured_data": {"key": "value"},
        "confidence": 0.85,
        "logs": [],
    }

    reg = MagicMock()
    reg.select_best_strategy.return_value = strategy

    import core.pipeline_steps
    monkeypatch.setattr(core.pipeline_steps, "strategy_registry", reg)
    return reg
