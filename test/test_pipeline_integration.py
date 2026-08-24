"""
Integration tests for core.pipeline —— ConversionPipeline 端到端测试
（插件形态：无内置 AI 客户端，增强由调用方模型完成）
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
            source=b"raw-bytes",
            conversion_type=ConversionType.OCR,
            output_format=OutputFormat.MARKDOWN,
            custom_prompt="请转换",
        )
        assert ctx.source == b"raw-bytes"
        assert ctx.conversion_type == ConversionType.OCR
        assert ctx.output_format == OutputFormat.MARKDOWN
        assert ctx.custom_prompt == "请转换"


# ═══════════════════════════════════════════════════════════
# ConversionPipeline 集成测试
# ═══════════════════════════════════════════════════════════

class TestConversionPipelineInit:
    def test_initializes_subsystems(self):
        pipeline = ConversionPipeline(max_cache_size=50, cache_ttl=600)
        assert pipeline.input_manager is not None
        assert pipeline.format_detector is not None
        assert pipeline.decision_engine is not None
        assert pipeline._content_cache is not None
        assert pipeline.result_cache == {}
        assert pipeline._max_cache_size == 50
        assert pipeline._cache_ttl == 600

    def test_initialize_is_safe_noop(self):
        """插件形态：initialize 为安全空钩子"""
        pipeline = ConversionPipeline()
        pipeline.initialize()  # 不应抛异常



class TestPipelineResultCache:
    def _make_result(self, rid: str) -> ConvertResultData:
        return ConvertResultData(
            resultId=rid, parseId="parse_1",
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

    def test_add_and_get_result(self):
        pipeline = ConversionPipeline(max_cache_size=10, cache_ttl=3600)
        pipeline._add_to_cache("test_id", self._make_result("test_id"))
        fetched = pipeline.get_result("test_id")
        assert fetched is not None
        assert fetched.resultId == "test_id"

    def test_get_nonexistent_result(self):
        pipeline = ConversionPipeline()
        assert pipeline.get_result("nonexistent") is None

    def test_expired_result_returns_none(self):
        pipeline = ConversionPipeline(max_cache_size=10, cache_ttl=0)  # TTL=0 立即过期
        pipeline._add_to_cache("expired", self._make_result("expired"))
        import time
        time.sleep(0.01)  # 确保过期
        assert pipeline.get_result("expired") is None


class TestPipelineRun:
    """端到端集成测试 —— 完整 Pipeline 执行"""

    def test_complete_text_conversion(self):
        """纯文本 raw 输入 → 格式检测 → 策略转换 → 格式化 → 构建结果"""
        pipeline = ConversionPipeline()
        ctx = PipelineContext(
            source=b"Hello World\nThis is a test.",
            conversion_type=ConversionType.AUTO,
            output_format=OutputFormat.JSON,
        )

        result = pipeline.run(ctx)

        assert "result" in result
        assert result["result"] is not None
        assert result["result"].convertedContent is not None
        assert len(result["result"].convertedContent) > 0
        # 确认所有步骤日志都存在（Discover/Enhance 已随去 AI 化移除）
        log_steps = {l.step for l in result["result"].processingLogs}
        expected_steps = {"init", "input", "detect", "decision", "convert", "format", "complete"}
        missing = expected_steps - log_steps
        assert not missing, f"缺失步骤: {missing}"
        assert "ai_discover" not in log_steps
        assert "ai_enhance" not in log_steps

    def test_cache_hit_short_circuits(self):
        """缓存命中时 Pipeline 在 CacheCheckStep 中止"""
        pipeline = ConversionPipeline()

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
        )

        result = pipeline.run(ctx)

        assert result["result"] == cached_result
        assert result["recommendation"] == "from cache"

    def test_input_error_returns_error_response(self):
        """输入读取失败时返回错误响应"""
        pipeline = ConversionPipeline()

        ctx = PipelineContext(
            source="nonexistent_file.txt",
            conversion_type=ConversionType.AUTO,
            output_format=OutputFormat.JSON,
        )

        result = pipeline.run(ctx)

        assert "result" in result

    def test_build_error_response_format(self):
        """验证错误响应格式"""
        pipeline = ConversionPipeline()
        ctx = PipelineContext(
            source=b"data",
            conversion_type=ConversionType.TEXT,
            output_format=OutputFormat.TEXT,
        )
        ctx.error = "test error message"
        ctx.logs = []

        response = pipeline._build_error_response(ctx)

        assert response["result"].convertedContent == "test error message"
        assert response["result"].structuredData == {"error": True}
        assert response["result"].confidence == 0.0
        assert response["decision"] is None
        assert "test error message" in response["recommendation"]

    def test_execute_stops_on_finished(self):
        """ctx.finished 时 execute 应停止后续步骤"""
        pipeline = ConversionPipeline()
        ctx = PipelineContext(
            source=b"data",
            conversion_type=ConversionType.AUTO,
            output_format=OutputFormat.JSON,
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
        )
        ctx.error = "pre-existing error"

        result_ctx = pipeline.execute(ctx)

        assert len(result_ctx.logs) == 0
        assert result_ctx.error == "pre-existing error"
