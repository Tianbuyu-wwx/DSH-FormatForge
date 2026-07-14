"""
数据转换引擎（兼容层）

原 God Class 已拆解为 Pipeline 模式：
- core/pipeline.py      → PipelineContext + ConversionPipeline（编排器 + 缓存）
- core/pipeline_steps.py → 10 个独立的 Pipeline 步骤

本模块保留 DataConverter / BatchConverter 作为向后兼容的薄封装层，
对外 API 完全不变，内部全部委托给 ConversionPipeline。
"""

import logging
from typing import Any

from core.conversion_strategies import strategy_registry
from core.models import (
    ConversionType,
    ConvertResultData,
    OutputFormat,
    ParsedFile,
)
from core.pipeline import ConversionPipeline, PipelineContext
from core.provider_registry import AiCapabilities

logger = logging.getLogger("converter_engine")


class DataConverter:
    """
    数据转换引擎（兼容封装）

    内部委托给 ConversionPipeline，保持原有公共 API 不变。
    """

    def __init__(
        self,
        max_cache_size: int = 1000,
        cache_ttl: int = 3600,
        max_concurrent_ai: int = 5,
    ):
        self._pipeline = ConversionPipeline(
            max_cache_size=max_cache_size,
            cache_ttl=cache_ttl,
            max_concurrent_ai=max_concurrent_ai,
        )
        logger.info("DataConverter 初始化完成（Pipeline 模式）")

    # ---- 兼容属性（被 api/v1.py 直接访问） ----

    @property
    def ai_client(self):
        return self._pipeline.ai_client

    @ai_client.setter
    def ai_client(self, value):
        self._pipeline.ai_client = value

    @property
    def result_cache(self) -> dict:
        return self._pipeline.result_cache

    @property
    def ai_discovery(self):
        return self._pipeline.ai_discovery

    @property
    def prompt_manager(self):
        return self._pipeline.prompt_manager

    @property
    def decision_engine(self):
        return self._pipeline.decision_engine

    # ---- 公共 API ----

    def convert(
        self,
        parsed_file: ParsedFile,
        conversion_type: ConversionType = ConversionType.AUTO,
        output_format: OutputFormat = OutputFormat.JSON,
        custom_prompt: str | None = None,
    ) -> ConvertResultData | None:
        """
        [兼容方法] 将解析后的文件转换为目标格式

        直接基于 ParsedFile 执行策略转换并返回结果，用于测试和旧版兼容。
        """
        self._pipeline.initialize()

        from core.utils import create_processing_log, generate_result_id

        result_id = generate_result_id()
        logs = []

        try:
            strategy = strategy_registry.select_best_strategy(
                parsed_file,
                conversion_type,
                None,
            )
            logs.append(create_processing_log("convert", f"选择策略: {strategy.strategy_name}"))

            result = strategy.convert(parsed_file, output_format, None, custom_prompt)
            logs.extend(result.get("logs", []))

            content = result.get("content", "")
            structured_data = result.get("structured_data")
            confidence = result.get("confidence", 0.0)

            from datetime import datetime

            from core.models import FileInfo

            result_data = ConvertResultData(
                resultId=result_id,
                parseId=parsed_file.parseId,
                fileInfo=FileInfo(
                    fileName=parsed_file.fileName,
                    fileSize=parsed_file.fileSize,
                    pageCount=parsed_file.pageCount,
                    fileType=parsed_file.fileType,
                ),
                conversionType=conversion_type,
                outputFormat=output_format,
                extractedContent=parsed_file.pages[0].rawText[:500] if parsed_file.pages else "",
                convertedContent=content,
                structuredData=structured_data or {},
                confidence=confidence,
                processingLogs=logs,
                createdAt=datetime.now(),
            )

            self._pipeline._add_to_cache(result_id, result_data)
            return result_data
        except Exception as e:
            logger.error("转换失败: %s", e, exc_info=True)
            return None

    def discover_ai_capabilities(
        self,
        endpoint: str,
        api_key: str,
        provider: str | None = None,
    ) -> AiCapabilities:
        """发现目标AI的能力"""
        return self._pipeline.ai_discovery.discover(endpoint, api_key, provider=provider)

    def convert_with_ai_target(
        self,
        source: Any,
        target_ai_endpoint: str | None = None,
        target_ai_key: str | None = None,
        target_ai_provider: str | None = None,
        conversion_type: ConversionType = ConversionType.AUTO,
        output_format: OutputFormat = OutputFormat.JSON,
        custom_prompt: str | None = None,
        use_ai_enhance: bool = True,
    ) -> dict[str, Any]:
        """
        执行数据转换（面向指定AI）—— 委托给 ConversionPipeline.run()
        """
        ctx = PipelineContext(
            source=source,
            conversion_type=conversion_type,
            output_format=output_format,
            custom_prompt=custom_prompt,
            use_ai_enhance=use_ai_enhance,
            target_ai_endpoint=target_ai_endpoint,
            target_ai_key=target_ai_key,
            target_ai_provider=target_ai_provider,
        )
        return self._pipeline.run(ctx)

    def get_result(self, result_id: str) -> ConvertResultData | None:
        """获取转换结果（带TTL检查）"""
        return self._pipeline.get_result(result_id)


class BatchConverter:
    """批量转换器（不变）"""

    def __init__(self):
        self.converter = DataConverter()

    def convert_batch(
        self,
        sources: list[Any],
        target_ai_endpoint: str | None = None,
        target_ai_key: str | None = None,
        conversion_type: ConversionType = ConversionType.AUTO,
        output_format: OutputFormat = OutputFormat.JSON,
    ) -> list[dict[str, Any]]:
        results = []
        for source in sources:
            try:
                result = self.converter.convert_with_ai_target(
                    source=source,
                    target_ai_endpoint=target_ai_endpoint,
                    target_ai_key=target_ai_key,
                    conversion_type=conversion_type,
                    output_format=output_format,
                )
                results.append(result)
            except Exception as e:
                logger.error("批量转换失败: %s", e)
                results.append({"error": str(e), "source": str(source)[:100]})
        return results
