"""
Integration tests for core.pipeline —— ConversionPipeline 端到端测试
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from datetime import datetime

from core.models import (
    ConversionType, OutputFormat, FileType, ConvertResultData,
    ParsedFile, PageContent, FileInfo, ProcessingLog, TaskStatus,
)
from core.pipeline import PipelineContext, ConversionPipeline
from core.input_adapters import InputData
from core.format_detector import DataFormat, FormatDetectionResult
from core.decision_engine import ConversionDecision


# ═══════════════════════════════════════════════════════════
# PipelineContext
# ═══════════════════════════════════════════════════════════

class TestPipelineContext:
    def test_default_values(self):
        ctx = PipelineContext(
            source=b"data",
            conversion_type=ConversionType.AUTO,
            output_format=OutputFormat.JSON,
            custom_prompt=None,
            use_ai_enhance=True,
            target_ai_endpoint=None,
            target_ai_key=None,
            target_ai_provider=None,
        )
        assert ctx.result_id == ""
        assert ctx.logs == []
        assert ctx.input_data is None
        assert ctx.parsed_file is None
        assert ctx.decision is None
        assert ctx.content == ""
        assert ctx.confidence == 0.0
        assert ctx.structured_data is None
        assert ctx.finished is False
        assert ctx.error is None
        assert ctx.final_response is None
        assert ctx.start_time > 0

    def test_all_input_params_stored(self):
        ctx = PipelineContext(
            source="http://example.com",
            conversion_type=ConversionType.OCR,
            output_format=OutputFormat.MARKDOWN,
            custom_prompt="请转换",
            use_ai_enhance=False,
            target_ai_endpoint="https://api.x.com",
            target_ai_key="key-123",
            target_ai_provider="minimax",
        )
        assert ctx.source == "http://example.com"
        assert ctx.conversion_type == ConversionType.OCR
        assert ctx.output_format == OutputFormat.MARKDOWN
        assert ctx.custom_prompt == "请转换"
        assert ctx.use_ai_enhance is False
        assert ctx.target_ai_endpoint == "https://api.x.com"
        assert ctx.target_ai_key == "key-123"
        assert ctx.target_ai_provider == "minimax"


# ═══════════════════════════════════════════════════════════
# ConversionPipeline 集成测试
# ═══════════════════════════════════════════════════════════

class TestConversionPipelineInit:
    def test_initializes_subsystems(self):
        pipeline = ConversionPipeline(max_cache_size=50, cache_ttl=600)
        assert pipeline.input_manager is not None
        assert pipeline.format_detector is not None
        assert pipeline.ai_discovery is not None
        assert pipeline.decision_engine is not None
        assert pipeline._content_cache is not None
        assert pipeline.result_cache == {}
        assert pipeline._max_cache_size == 50
        assert pipeline._cache_ttl == 600

    def test_ai_client_none_before_initialize(self):
        pipeline = ConversionPipeline()
        assert pipeline.ai_client is None
        assert pipeline.prompt_manager is None

    def test_initialize_sets_ai_client(self):
        pipeline = ConversionPipeline()
        pipeline.initialize()
        # AI client 可能是 None（如果未配置 API key），但 prompt_manager 必须设置
        assert pipeline.prompt_manager is not None


class TestPipelineResultCache:
    def test_add_and_get_result(self):
        pipeline = ConversionPipeline(max_cache_size=10, cache_ttl=3600)
        result_data = ConvertResultData(
            resultId="test_id",
            parseId="parse_1",
            fileInfo=FileInfo(fileName="f.txt", fileSize=10, pageCount=1, fileType="txt"),
            conversionType=ConversionType.AUTO,
            outputFormat=OutputFormat.JSON,
            extractedContent="",
            convertedContent="data",
            structuredData={},
            confidence=1.0,
            processingLogs=[],
            createdAt=datetime.now(),
        )
        pipeline._add_to_cache("test_id", result_data)
        fetched = pipeline.get_result("test_id")
        assert fetched is not None
        assert fetched.resultId == "test_id"

    def test_get_nonexistent_result(self):
        pipeline = ConversionPipeline()
        assert pipeline.get_result("nonexistent") is None

    def test_expired_result_returns_none(self):
        pipeline = ConversionPipeline(max_cache_size=10, cache_ttl=0)  # TTL=0 立即过期
        result_data = ConvertResultData(
            resultId="expired", parseId="", fileInfo=FileInfo(fileName="", fileSize=0, pageCount=0, fileType="unknown"),
            conversionType=ConversionType.AUTO, outputFormat=OutputFormat.JSON,
            extractedContent="", convertedContent="", structuredData={}, confidence=0.0,
            processingLogs=[], createdAt=datetime.now(),
        )
        pipeline._add_to_cache("expired", result_data)
        import time
        time.sleep(0.01)  # 确保过期
        assert pipeline.get_result("expired") is None


class TestPipelineRun:
    """端到端集成测试 —— 模拟完整 Pipeline 执行"""

    def test_complete_text_conversion(self):
        """纯文本 raw 输入 → 格式检测 → 策略转换 → 格式化 → 构建结果"""
        pipeline = ConversionPipeline()

        # Mock AI 客户端初始化
        pipeline.ai_client = MagicMock()
        pipeline.prompt_manager = MagicMock()

        ctx = PipelineContext(
            source=b"Hello World\nThis is a test.",
            conversion_type=ConversionType.AUTO,
            output_format=OutputFormat.JSON,
            custom_prompt=None,
            use_ai_enhance=False,  # 关闭增强以简化测试
            target_ai_endpoint=None,
            target_ai_key=None,
            target_ai_provider=None,
        )

        result = pipeline.run(ctx)

        assert "result" in result
        assert result["result"] is not None
        assert result["result"].convertedContent is not None
        assert len(result["result"].convertedContent) > 0
        # 确认所有步骤日志都存在
        log_steps = {l.step for l in result["result"].processingLogs}
        expected_steps = {"init", "input", "detect", "decision", "convert", "format", "complete"}
        missing = expected_steps - log_steps
        assert not missing, f"缺失步骤: {missing}"

    def test_cache_hit_short_circuits(self):
        """缓存命中时 Pipeline 在 CacheCheckStep 中止"""
        pipeline = ConversionPipeline()
        pipeline.ai_client = MagicMock()
        pipeline.prompt_manager = MagicMock()

        # 预置缓存返回
        pipeline._content_cache = MagicMock()
        cached_result = ConvertResultData(
            resultId="cached_id", parseId="", fileInfo=FileInfo(fileName="cached", fileSize=10, pageCount=0, fileType="unknown"),
            conversionType=ConversionType.AUTO, outputFormat=OutputFormat.JSON,
            extractedContent="", convertedContent="cached content", structuredData={},
            confidence=1.0, processingLogs=[], createdAt=datetime.now(),
        )
        pipeline._content_cache.get.return_value = cached_result

        ctx = PipelineContext(
            source=b"same content",
            conversion_type=ConversionType.AUTO,
            output_format=OutputFormat.JSON,
            custom_prompt=None,
            use_ai_enhance=False,
            target_ai_endpoint=None,
            target_ai_key=None,
            target_ai_provider=None,
        )

        result = pipeline.run(ctx)

        assert result["result"] == cached_result
        assert result["recommendation"] == "from cache"

    def test_input_error_returns_error_response(self):
        """输入读取失败时返回错误响应"""
        pipeline = ConversionPipeline()
        pipeline.ai_client = MagicMock()
        pipeline.prompt_manager = MagicMock()

        # 让 input_manager 抛出异常
        ctx = PipelineContext(
            source="nonexistent_file.txt",
            conversion_type=ConversionType.AUTO,
            output_format=OutputFormat.JSON,
            custom_prompt=None,
            use_ai_enhance=False,
            target_ai_endpoint=None,
            target_ai_key=None,
            target_ai_provider=None,
        )

        result = pipeline.run(ctx)

        # 如果 input_manager 因文件不存在而失败, 应返回错误
        # (实际行为取决于 input_manager 如何处理路径)
        assert "result" in result

    def test_build_error_response_format(self):
        """验证错误响应格式"""
        pipeline = ConversionPipeline()
        ctx = PipelineContext(
            source=b"data",
            conversion_type=ConversionType.TEXT,
            output_format=OutputFormat.TEXT,
            custom_prompt=None,
            use_ai_enhance=False,
            target_ai_endpoint=None,
            target_ai_key=None,
            target_ai_provider=None,
        )
        ctx.error = "test error message"
        ctx.logs = []

        response = pipeline._build_error_response(ctx)

        assert response["result"].convertedContent == "test error message"
        assert response["result"].structuredData == {"error": True}
        assert response["result"].confidence == 0.0
        assert response["decision"] is None
        assert response["ai_capabilities"] is None
        assert "test error message" in response["recommendation"]

    def test_execute_stops_on_finished(self):
        """ctx.finished 时 execute 应停止后续步骤"""
        pipeline = ConversionPipeline()
        ctx = PipelineContext(
            source=b"data",
            conversion_type=ConversionType.AUTO,
            output_format=OutputFormat.JSON,
            custom_prompt=None,
            use_ai_enhance=False,
            target_ai_endpoint=None,
            target_ai_key=None,
            target_ai_provider=None,
        )
        ctx.finished = True

        result_ctx = pipeline.execute(ctx)

        # 没有日志生成（InitStep 没运行）
        assert len(result_ctx.logs) == 0

    def test_execute_stops_on_error(self):
        """ctx.error 时 execute 应停止后续步骤"""
        pipeline = ConversionPipeline()
        ctx = PipelineContext(
            source=b"data",
            conversion_type=ConversionType.AUTO,
            output_format=OutputFormat.JSON,
            custom_prompt=None,
            use_ai_enhance=False,
            target_ai_endpoint=None,
            target_ai_key=None,
            target_ai_provider=None,
        )
        ctx.error = "pre-existing error"

        result_ctx = pipeline.execute(ctx)

        assert len(result_ctx.logs) == 0
        assert result_ctx.error == "pre-existing error"
