"""
数据转换 Pipeline 框架

将原先 God Class DataConverter 拆解为独立的 Pipeline 步骤。
PipelineContext 携带所有状态在步骤间流转，每个步骤职责单一、可独立测试。
"""

import logging
import threading
import time
from datetime import datetime
from typing import Any

from core.content_cache import ContentHashCache
from core.decision_engine import ConversionDecision, DecisionEngine
from core.format_detector import FormatDetector
from core.input_adapters import InputAdapterManager, InputData
from core.models import ConversionType, ConvertResultData, FileInfo, FileType, OutputFormat, ParsedFile, ProcessingLog

logger = logging.getLogger(__name__)


class PipelineContext:
    """Pipeline 上下文 —— 携带所有步骤间共享的状态"""

    def __init__(
        self,
        source: Any,
        conversion_type: ConversionType,
        output_format: OutputFormat,
        custom_prompt: str | None = None,
        pages: str | None = None,
    ):
        # 输入参数
        self.source = source
        self.conversion_type = conversion_type
        self.output_format = output_format
        self.custom_prompt = custom_prompt
        # E2: PDF 页选择表达式（"1-3,7"）；非 PDF 输入忽略
        self.pages = pages

        # 步骤产出
        self.result_id: str = ""
        self.logs: list[ProcessingLog] = []
        self.input_data: InputData | None = None
        self.detected: Any | None = None
        self.parsed_file: ParsedFile | None = None
        self.decision: ConversionDecision | None = None
        self.content: str = ""
        self.structured_data: dict[str, Any] | None = None
        self.confidence: float = 0.0

        # 结果
        self.result_data: ConvertResultData | None = None
        self.recommendation: str = ""
        self.final_response: dict[str, Any] | None = None

        # 控制标志
        self.finished: bool = False  # True 时跳过后续步骤（缓存命中）
        self.error: str | None = None  # 非 None 时中止并返回错误

        # 性能计时
        self.start_time: float = time.time()


class ConversionPipeline:
    """
    数据转换 Pipeline 编排器

    职责：
    1. 管理 PipelineContext 在步骤间的流转
    2. 管理两级缓存（内存 result_cache + 内容哈希 cache）
    3. 编排步骤执行顺序

    注：插件形态下无内置 AI 客户端；需要模型增强时由调用方（dsh 会话模型）按
    enhance 提示完成，见 PLUGIN_PLAN.md §6。
    """

    def __init__(
        self,
        max_cache_size: int = 1000,
        cache_ttl: int = 3600,
        enable_content_cache: bool = True,
    ):
        # 内存缓存（result_id → ConvertResultData）
        self.result_cache: dict[str, ConvertResultData] = {}
        self._cache_timestamps: dict[str, float] = {}
        self._cache_lock = threading.Lock()
        self._max_cache_size = max_cache_size
        self._cache_ttl = cache_ttl

        # 内容哈希缓存（内存 + 磁盘两级）；CLI 一次性进程默认关闭
        self._content_cache = (
            ContentHashCache(
                max_memory_entries=max_cache_size,
                default_ttl=cache_ttl,
            )
            if enable_content_cache
            else None
        )

        # 子系统（供步骤使用）
        self.input_manager = InputAdapterManager()
        self.format_detector = FormatDetector()
        self.decision_engine = DecisionEngine()

        logger.info(
            "ConversionPipeline 初始化: cache_size=%d, cache_ttl=%d",
            max_cache_size,
            cache_ttl,
        )

    def initialize(self):
        """保留钩子：CLI 模式下无需初始化外部资源"""

    # ---- 缓存管理 ----

    def _add_to_cache(self, result_id: str, result: ConvertResultData):
        with self._cache_lock:
            now = time.time()
            expired = [k for k, v in self._cache_timestamps.items() if now - v > self._cache_ttl]
            for k in expired:
                self.result_cache.pop(k, None)
                self._cache_timestamps.pop(k, None)
            while len(self.result_cache) >= self._max_cache_size:
                oldest = min(self._cache_timestamps, key=lambda k: self._cache_timestamps[k])
                self.result_cache.pop(oldest, None)
                self._cache_timestamps.pop(oldest, None)
            self.result_cache[result_id] = result
            self._cache_timestamps[result_id] = now

    def _try_get_cached(
        self,
        input_data: InputData,
        conversion_type: ConversionType,
        output_format: OutputFormat,
        custom_prompt: str | None = None,
    ) -> dict[str, Any] | None:
        if self._content_cache is None:
            return None
        try:
            cached = self._content_cache.get(
                input_data.data,
                conversion_type.value,
                output_format.value,
                custom_prompt,
            )
            if cached:
                logger.info("内容哈希缓存命中")
                # v2.1.0: JSON 缓存命中时 result 是 dict，需重建为 ConvertResultData
                if isinstance(cached, dict):
                    cached = ConvertResultData(**cached)
                return {
                    "result": cached,
                    "decision": {"from_cache": True},
                    "recommendation": "from cache",
                }
        except Exception as e:
            logger.debug("内容缓存读取失败（可忽略）: %s", e)
        return None

    def _try_store_cached(
        self,
        input_data: InputData,
        conversion_type: ConversionType,
        output_format: OutputFormat,
        result_data: ConvertResultData,
    ):
        if self._content_cache is None:
            return
        try:
            self._content_cache.set(
                input_data.data,
                conversion_type.value,
                output_format.value,
                result_data,
            )
        except Exception as e:
            logger.debug("内容缓存写入失败（可忽略）: %s", e)

    def get_result(self, result_id: str) -> ConvertResultData | None:
        with self._cache_lock:
            if (
                result_id in self._cache_timestamps
                and time.time() - self._cache_timestamps[result_id] > self._cache_ttl
            ):
                self.result_cache.pop(result_id, None)
                self._cache_timestamps.pop(result_id, None)
                return None
            return self.result_cache.get(result_id)

    # ---- 主执行入口 ----

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        """按顺序执行各步骤，步骤可通过 ctx.finished/ctx.error 控制流程"""
        from core.pipeline_steps import (
            BuildResultStep,
            CacheCheckStep,
            ConvertStep,
            DecisionStep,
            DetectStep,
            FormatStep,
            InitStep,
            InputStep,
            OcrStep,
            ParseStep,
        )

        steps = [
            InitStep(),
            InputStep(self.input_manager),
            CacheCheckStep(self),
            DetectStep(self.format_detector),
            ParseStep(self),
            OcrStep(),
            DecisionStep(self.decision_engine),
            ConvertStep(),
            FormatStep(),
            BuildResultStep(self),
        ]
        # 各 Step 类分散定义于 pipeline_steps，运行时都有 process()；统一按协议基类标注。
        steps_typed: list[Any] = steps
        for step in steps_typed:
            if ctx.finished or ctx.error:
                break
            try:
                step.process(ctx)
            except Exception as e:
                logger.error("[result_id=%s] 步骤 %s 失败: %s", ctx.result_id, type(step).__name__, e, exc_info=True)
                ctx.error = str(e)
                break

        return ctx

    def run(self, ctx: PipelineContext) -> dict[str, Any]:
        """运行 Pipeline 并返回最终响应"""
        self.initialize()
        self.execute(ctx)

        if ctx.final_response:
            return ctx.final_response
        if ctx.error:
            return self._build_error_response(ctx)
        # 正常情况下 final_response 应该在 BuildResultStep 中设置
        return ctx.final_response or self._build_error_response(ctx)

    def _build_error_response(self, ctx: PipelineContext) -> dict[str, Any]:
        from core.utils import create_processing_log

        error_msg = ctx.error or "未知错误"
        if ctx.logs:
            ctx.logs.append(create_processing_log("error", error_msg, "error"))
        return {
            "result": ConvertResultData(
                resultId=ctx.result_id,
                parseId="",
                fileInfo=FileInfo(fileName="error", fileSize=0, pageCount=0, fileType=FileType.UNKNOWN),
                conversionType=ctx.conversion_type,
                outputFormat=OutputFormat.TEXT,
                extractedContent="",
                convertedContent=error_msg,
                structuredData={"error": True},
                confidence=0.0,
                processingLogs=ctx.logs,
                # start_time 为 time.time() 时间戳，响应模型字段需要 datetime。
                createdAt=datetime.fromtimestamp(ctx.start_time),
            ),
            "decision": None,
            "recommendation": f"处理失败: {error_msg}",
        }
