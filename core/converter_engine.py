"""
数据转换引擎
核心转换逻辑，协调输入适配、AI能力发现、策略选择和格式化输出
"""
import uuid
import time
import asyncio
import threading
import logging
from typing import Dict, Any, List, Optional, Union
from datetime import datetime
from pathlib import Path

from core.models import (
    ParsedFile, FileInfo, ConversionType, OutputFormat,
    ConvertResultData, ProcessingLog, TaskStatus
)
from core.conversion_strategies import strategy_registry
from core.ai_client import create_ai_client, AIClient
from core.ai_discovery import AiDiscovery, AiCapabilities
from core.input_adapters import InputAdapterManager, InputData
from core.format_detector import FormatDetector, format_detector
from core.config import settings
from core.utils import format_output
from core.content_cache import ContentHashCache
from core.decision_engine import DecisionEngine
from core.ai_prompt_manager import AIPromptManager


logger = logging.getLogger("converter_engine")


class DataConverter:
    """
    数据转换引擎

    职责：
    1. 接收多种输入源（文件/URL/原始数据）
    2. 自动检测输入格式
    3. 发现目标AI能力
    4. 选择最佳转换策略（考虑AI能力）
    5. 执行转换
    6. 格式化输出为AI友好格式
    7. 缓存结果
    """

    def __init__(
        self,
        max_cache_size: int = 1000,
        cache_ttl: int = 3600,
        max_concurrent_ai: int = 5
    ):
        self.result_cache: Dict[str, ConvertResultData] = {}
        self._cache_timestamps: Dict[str, float] = {}
        self._cache_lock = threading.Lock()
        self._max_cache_size = max_cache_size
        self._cache_ttl = cache_ttl
        self.api_semaphore = asyncio.Semaphore(max_concurrent_ai)

        # 内容哈希缓存（内存+磁盘两级，基于内容去重）
        self._content_cache = ContentHashCache(
            max_memory_entries=max_cache_size,
            default_ttl=cache_ttl,
        )

        logger.info("初始化 DataConverter: cache_size=%d, cache_ttl=%d, max_concurrent_ai=%d",
                    max_cache_size, cache_ttl, max_concurrent_ai)

        # 初始化子系统
        self.input_manager = InputAdapterManager()
        self.format_detector = FormatDetector()
        self.ai_discovery = AiDiscovery()
        self.ai_client = self._init_ai_client()

        # 初始化子引擎
        self.decision_engine = DecisionEngine()
        self.prompt_manager = AIPromptManager(ai_client=self.ai_client)

        logger.info("DataConverter 初始化完成, AI客户端=%s", "可用" if self.ai_client else "不可用")

    def _init_ai_client(self) -> Optional[AIClient]:
        """初始化AI客户端"""
        try:
            provider = settings.AI_PROVIDER.lower()
            timeout = settings.AI_TIMEOUT
            logger.debug("尝试初始化AI客户端: provider=%s, timeout=%ds", provider, timeout)
            if provider == "minimax" and settings.MINIMAX_API_KEY:
                logger.info("使用 Minimax AI 客户端")
                return create_ai_client(
                    provider="minimax",
                    api_key=settings.MINIMAX_API_KEY,
                    base_url=settings.MINIMAX_BASE_URL,
                    timeout=timeout
                )
            elif provider == "openai" and settings.OPENAI_API_KEY:
                logger.info("使用 OpenAI 兼容客户端")
                return create_ai_client(
                    provider="openai",
                    api_key=settings.OPENAI_API_KEY,
                    base_url=settings.OPENAI_BASE_URL,
                    timeout=timeout
                )
            else:
                logger.warning("未配置有效的AI客户端 (provider=%s, key配置=%s)",
                               provider, bool(settings.MINIMAX_API_KEY or settings.OPENAI_API_KEY))
                return None
        except Exception as e:
            logger.error("AI客户端初始化失败: %s", e, exc_info=True)
            return None

    def _generate_result_id(self) -> str:
        """生成结果ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        random_suffix = uuid.uuid4().hex[:6]
        return f"cvt{timestamp}{random_suffix}"

    def _create_log(self, step: str, message: str, level: str = "info") -> ProcessingLog:
        """创建处理日志"""
        return ProcessingLog(
            timestamp=datetime.now(),
            level=level,
            message=message,
            step=step
        )

    def convert(
        self,
        parsed_file: ParsedFile,
        conversion_type: ConversionType = ConversionType.AUTO,
        output_format: OutputFormat = OutputFormat.JSON,
        custom_prompt: Optional[str] = None
    ) -> Optional[ConvertResultData]:
        """
        [兼容方法] 将解析后的文件转换为目标格式

        直接基于 ParsedFile 执行策略转换并返回结果，用于测试和旧版兼容
        """
        result_id = self._generate_result_id()
        logs: List[ProcessingLog] = []

        try:
            strategy = strategy_registry.select_best_strategy(
                parsed_file, conversion_type, None
            )
            logs.append(self._create_log("convert", f"选择策略: {strategy.strategy_name}"))

            result = strategy.convert(parsed_file, output_format, None, custom_prompt)
            logs.extend(result.get("logs", []))

            content = result.get("content", "")
            structured_data = result.get("structured_data")
            confidence = result.get("confidence", 0.0)

            result_data = ConvertResultData(
                resultId=result_id,
                parseId=parsed_file.parseId,
                fileInfo=FileInfo(
                    fileName=parsed_file.fileName,
                    fileSize=parsed_file.fileSize,
                    pageCount=parsed_file.pageCount,
                    fileType=parsed_file.fileType
                ),
                conversionType=conversion_type,
                outputFormat=output_format,
                extractedContent=parsed_file.pages[0].rawText[:500] if parsed_file.pages else "",
                convertedContent=content,
                structuredData=structured_data or {},
                confidence=confidence,
                processingLogs=logs,
                createdAt=datetime.now()
            )

            self._add_to_cache(result_id, result_data)
            return result_data
        except Exception as e:
            logger.error("转换失败: %s", e, exc_info=True)
            return None

    def discover_ai_capabilities(
        self,
        endpoint: str,
        api_key: str,
        provider: Optional[str] = None
    ) -> AiCapabilities:
        """发现目标AI的能力"""
        return self.ai_discovery.discover(endpoint, api_key, provider=provider)

    def convert_with_ai_target(
        self,
        source: Any,
        target_ai_endpoint: Optional[str] = None,
        target_ai_key: Optional[str] = None,
        target_ai_provider: Optional[str] = None,
        conversion_type: ConversionType = ConversionType.AUTO,
        output_format: OutputFormat = OutputFormat.JSON,
        custom_prompt: Optional[str] = None,
        use_ai_enhance: bool = True
    ) -> Dict[str, Any]:
        """
        执行数据转换（面向指定AI）

        Args:
            source: 输入源（文件路径/URL/字节数据）
            target_ai_endpoint: 目标AI API端点
            target_ai_key: 目标AI API密钥
            target_ai_provider: 目标AI提供商
            conversion_type: 转换类型
            output_format: 输出格式
            custom_prompt: 自定义转换指令
            use_ai_enhance: 是否使用AI增强

        Returns:
            Dict: 包含转换结果、决策记录、AI能力信息
        """
        start_time = time.time()
        result_id = self._generate_result_id()
        logs: List[ProcessingLog] = []

        logger.info("[result_id=%s] 开始转换: source_type=%s, conversion_type=%s, output_format=%s",
                    result_id, type(source).__name__, conversion_type.value, output_format.value)

        logs.append(self._create_log(
            "init",
            f"开始转换: 类型={conversion_type.value}, 输出={output_format.value}"
        ))

        # 步骤1: 读取输入
        logs.append(self._create_log("input", "读取输入源..."))
        try:
            input_data = self.input_manager.read(source)
            logger.info("[result_id=%s] 输入读取成功: source_type=%s, size=%d bytes, filename=%s",
                        result_id, input_data.source_type, input_data.size, input_data.filename)
            logs.append(self._create_log(
                "input",
                f"输入源类型: {input_data.source_type}, 大小: {input_data.size} 字节"
            ))
        except Exception as e:
            logger.error("[result_id=%s] 输入读取失败: %s", result_id, e, exc_info=True)
            logs.append(self._create_log("input", f"读取失败: {e}", "error"))
            return self._build_error_result(result_id, logs, f"输入读取失败: {e}")

        # 步骤1.5: 检查内容哈希缓存
        cached_result = self._try_get_cached(input_data, conversion_type, output_format, custom_prompt)
        if cached_result:
            logger.info("[result_id=%s] 内容缓存命中，跳过转换", result_id)
            logs.append(self._create_log("cache", "缓存命中，直接返回历史结果"))
            return cached_result

        # 步骤2: 格式检测
        logs.append(self._create_log("detect", "检测输入格式..."))
        detected = self.format_detector.detect(input_data.data, input_data.filename)
        logger.info("[result_id=%s] 格式检测完成: format=%s, mime=%s, confidence=%.2f",
                    result_id, detected.format.value, detected.mime_type, detected.confidence)
        logs.append(self._create_log(
            "detect",
            f"检测到格式: {detected.format.value}, MIME: {detected.mime_type}, 置信度: {detected.confidence:.2f}"
        ))

        # 步骤3: AI能力发现（如果提供了目标AI信息）
        ai_caps = None
        if target_ai_endpoint and target_ai_key:
            logs.append(self._create_log("ai_discover", "发现目标AI能力..."))
            logger.info("[result_id=%s] 开始发现AI能力: endpoint=%s, provider=%s",
                        result_id, target_ai_endpoint, target_ai_provider)
            try:
                ai_caps = self.discover_ai_capabilities(
                    target_ai_endpoint,
                    target_ai_key,
                    target_ai_provider
                )
                logger.info("[result_id=%s] AI能力发现成功: provider=%s, model=%s, supports=%s, max_tokens=%d",
                            result_id, ai_caps.provider, ai_caps.model,
                            [i.value for i in ai_caps.supported_inputs], ai_caps.max_tokens)
                logs.append(self._create_log(
                    "ai_discover",
                    f"AI能力: {ai_caps.provider}/{ai_caps.model}, "
                    f"支持输入: {[i.value for i in ai_caps.supported_inputs]}, "
                    f"最大token: {ai_caps.max_tokens}"
                ))
            except Exception as e:
                logger.warning("[result_id=%s] AI能力发现失败: %s", result_id, e, exc_info=True)
                logs.append(self._create_log("ai_discover", f"能力发现失败: {e}", "warning"))

        # 步骤4: 解析文件（如果是文件类型）
        parsed_file = None
        if input_data.source_type in ("file", "url", "stream"):
            logs.append(self._create_log("parse", "解析文件内容..."))
            logger.info("[result_id=%s] 开始解析文件: source_type=%s, detected_format=%s",
                        result_id, input_data.source_type, detected.format.value)
            try:
                from core.file_parser import FileParser
                from core.config import UPLOAD_DIR

                # 保存到临时文件
                temp_path = input_data.save_to_temp()
                logger.debug("[result_id=%s] 临时文件已保存: %s", result_id, temp_path)

                try:
                    # 根据检测到的格式确定文件类型
                    file_type = self._map_format_to_file_type(detected.format)
                    logger.debug("[result_id=%s] 映射文件类型: %s -> %s", result_id, detected.format.value, file_type)

                    file_parser = FileParser(UPLOAD_DIR)
                    parsed_file = file_parser.parse_file(temp_path, file_type)

                    logger.info("[result_id=%s] 文件解析完成: pages=%d, file_type=%s, parse_id=%s",
                                result_id, parsed_file.pageCount, parsed_file.fileType.value, parsed_file.parseId)
                    logs.append(self._create_log(
                        "parse",
                        f"解析完成: {parsed_file.pageCount} 页, 类型: {parsed_file.fileType.value}"
                    ))
                finally:
                    # 确保临时文件在任何情况下都被清理
                    temp_path.unlink(missing_ok=True)
                    logger.debug("[result_id=%s] 临时文件已清理", result_id)

            except Exception as e:
                logger.warning("[result_id=%s] 文件解析失败: %s", result_id, e, exc_info=True)
                logs.append(self._create_log("parse", f"解析失败: {e}", "warning"))
                # 解析失败继续，使用原始数据

        # 步骤5: 制定转换决策（委托给 DecisionEngine）
        decision = self.decision_engine.make_decision(detected, ai_caps, parsed_file)
        logger.info("[result_id=%s] 转换决策: conversion_needed=%s, target_format=%s, preserve_original=%s, strategies=%s",
                    result_id, decision.conversion_needed, decision.target_format,
                    decision.preserve_original, decision.strategies)
        logs.append(self._create_log(
            "decision",
            f"转换决策: 需要转换={decision.conversion_needed}, "
            f"目标格式={decision.target_format}, "
            f"保留原文件={decision.preserve_original}"
        ))

        # 步骤6: 执行转换
        if parsed_file and decision.conversion_needed:
            logs.append(self._create_log("convert", "执行数据转换..."))
            logger.info("[result_id=%s] 开始执行转换策略...", result_id)
            try:
                strategy = strategy_registry.select_best_strategy(
                    parsed_file, conversion_type, ai_caps
                )
                logger.info("[result_id=%s] 选择策略: strategy_id=%s, strategy_name=%s",
                            result_id, strategy.strategy_id, strategy.strategy_name)
                logs.append(self._create_log(
                    "convert",
                    f"选择策略: {strategy.strategy_name}"
                ))

                result = strategy.convert(parsed_file, output_format, ai_caps, custom_prompt)
                logs.extend(result.get("logs", []))

                content = result.get("content", "")
                structured_data = result.get("structured_data")
                confidence = result.get("confidence", 0.0)

                logger.info("[result_id=%s] 策略转换完成: content_length=%d, confidence=%.2f",
                            result_id, len(content), confidence)
                logs.append(self._create_log(
                    "convert",
                    f"转换完成，置信度: {confidence:.2f}"
                ))

            except Exception as e:
                logger.error("[result_id=%s] 转换失败: %s", result_id, e, exc_info=True)
                logs.append(self._create_log("convert", f"转换失败: {e}", "error"))
                content = f"转换失败: {e}"
                structured_data = None
                confidence = 0.0
        else:
            # 无需转换或无法解析，返回原始数据信息
            content = self._build_raw_content(input_data, detected)
            structured_data = {"raw_data": True, "size": input_data.size}
            confidence = 0.5
            logger.info("[result_id=%s] 无需转换，返回原始数据信息", result_id)
            logs.append(self._create_log("convert", "无需转换，返回原始数据信息"))

        # 步骤7: AI增强（如果启用，委托给 AIPromptManager）
        if use_ai_enhance and self.ai_client and confidence < 0.9 and parsed_file:
            logs.append(self._create_log("ai_enhance", "尝试AI增强转换..."))
            logger.info("[result_id=%s] 开始AI增强转换: current_confidence=%.2f", result_id, confidence)
            try:
                ai_result = self.prompt_manager.enhance_convert(
                    parsed_file=parsed_file,
                    base_content=content,
                    output_format=output_format,
                    custom_prompt=custom_prompt
                )
                if ai_result:
                    content = ai_result.get("content", content)
                    if ai_result.get("structured_data"):
                        structured_data = ai_result["structured_data"]
                    confidence = min(confidence + 0.1, 1.0)
                    logger.info("[result_id=%s] AI增强完成: new_confidence=%.2f, content_length=%d",
                                result_id, confidence, len(content))
                    logs.append(self._create_log("ai_enhance", "AI增强完成"))
                else:
                    logger.warning("[result_id=%s] AI增强未返回结果", result_id)
            except Exception as e:
                logger.warning("[result_id=%s] AI增强失败: %s", result_id, e, exc_info=True)
                logs.append(self._create_log("ai_enhance", f"AI增强失败: {e}", "warning"))

        # 步骤8: 格式化输出
        logs.append(self._create_log("format", f"格式化输出为 {output_format.value}..."))
        formatted_content = format_output(content, output_format, structured_data)
        logger.debug("[result_id=%s] 格式化输出完成: output_length=%d", result_id, len(formatted_content))

        # 步骤9: 构建结果
        processing_time = int(time.time() - start_time)
        logger.info("[result_id=%s] 转换完成: processing_time=%ds, final_confidence=%.2f, logs_count=%d",
                    result_id, processing_time, confidence, len(logs))
        logs.append(self._create_log("complete", f"转换完成，耗时 {processing_time} 秒"))

        recommendation = self.decision_engine.build_recommendation(decision, ai_caps)

        result_data = ConvertResultData(
            resultId=result_id,
            parseId=parsed_file.parseId if parsed_file else "",
            fileInfo=FileInfo(
                fileName=input_data.filename or "unknown",
                fileSize=input_data.size,
                pageCount=parsed_file.pageCount if parsed_file else 0,
                fileType=parsed_file.fileType if parsed_file else "unknown"
            ),
            conversionType=conversion_type,
            outputFormat=output_format,
            extractedContent=self._extract_summary(parsed_file) if parsed_file else "",
            convertedContent=formatted_content,
            structuredData={
                **(structured_data or {}),
                "conversion_decision": decision.to_dict(),
                "ai_capabilities": ai_caps.to_dict() if ai_caps else None
            },
            confidence=confidence,
            processingLogs=logs,
            createdAt=datetime.now()
        )

        # 缓存结果
        self._add_to_cache(result_id, result_data)
        self._try_store_cached(input_data, conversion_type, output_format, result_data)
        logger.debug("[result_id=%s] 结果已缓存", result_id)

        return {
            "result": result_data,
            "decision": decision.to_dict(),
            "ai_capabilities": ai_caps.to_dict() if ai_caps else None,
            "recommendation": recommendation
        }

    # ---- 向后兼容的转发方法 (委托给子引擎) ----

    def _build_ai_prompt(
        self,
        file_name: str,
        file_type: str,
        base_content: str,
        output_format: OutputFormat,
        custom_prompt: Optional[str] = None
    ) -> str:
        """[兼容] 构建AI转换提示词 - 委托给 AIPromptManager"""
        return self.prompt_manager.build_prompt(
            file_name, file_type, base_content, output_format, custom_prompt
        )

    def _parse_ai_response(self, response_text: str, output_format: OutputFormat) -> Dict[str, Any]:
        """[兼容] 解析AI响应 - 委托给 AIPromptManager"""
        return self.prompt_manager.parse_response(response_text, output_format)

    # ---- 工具方法 ----

    def _build_raw_content(self, input_data: InputData, detected: Any) -> str:
        """构建原始数据描述"""
        return f"""# 原始数据

- 文件名: {input_data.filename or 'unknown'}
- 格式: {detected.format.value}
- MIME类型: {detected.mime_type}
- 大小: {input_data.size} 字节
- 来源: {input_data.source_type}

此数据无需转换，可直接发送给支持该格式的AI。
"""

    def _map_format_to_file_type(self, fmt: Any) -> str:
        """映射检测格式到文件类型"""
        from core.format_detector import DataFormat

        mapping = {
            DataFormat.PDF: "pdf",
            DataFormat.DOCX: "doc",
            DataFormat.PPTX: "ppt",
            DataFormat.XLSX: "xls",
            DataFormat.CSV: "csv",
            DataFormat.TXT: "txt",
            DataFormat.JSON: "txt",
            DataFormat.YAML: "txt",
            DataFormat.XML: "txt",
            DataFormat.HTML: "txt",
            DataFormat.TOML: "txt",
            DataFormat.ODT: "doc",
            DataFormat.ODS: "xls",
            DataFormat.ODP: "ppt",
            DataFormat.EML: "txt",
            DataFormat.MSG: "txt",
            DataFormat.EPUB: "txt",
            DataFormat.SVG: "image",
            DataFormat.PNG: "image",
            DataFormat.JPEG: "image",
            DataFormat.GIF: "image",
            DataFormat.WEBP: "image",
            DataFormat.BMP: "image",
            DataFormat.TIFF: "image",
            DataFormat.ZIP: "unknown",
            DataFormat.SEVEN_Z: "unknown",
            DataFormat.RAR: "unknown",
        }
        return mapping.get(fmt, "unknown")

    def _extract_summary(self, parsed_file: ParsedFile) -> str:
        """提取内容摘要"""
        parts = []
        for page in parsed_file.pages[:3]:
            parts.append(page.rawText[:500])
        summary = "\n".join(parts)
        if len(summary) > 1500:
            summary = summary[:1500] + "..."
        return summary

    def _add_to_cache(self, result_id: str, result: ConvertResultData):
        """添加缓存并管理容量"""
        with self._cache_lock:
            now = time.time()
            expired = [
                k for k, v in self._cache_timestamps.items()
                if now - v > self._cache_ttl
            ]
            for k in expired:
                self.result_cache.pop(k, None)
                self._cache_timestamps.pop(k, None)

            while len(self.result_cache) >= self._max_cache_size:
                oldest = min(self._cache_timestamps, key=self._cache_timestamps.get)
                self.result_cache.pop(oldest, None)
                self._cache_timestamps.pop(oldest, None)

            self.result_cache[result_id] = result
            self._cache_timestamps[result_id] = now

    def _try_get_cached(self, input_data: InputData, conversion_type: ConversionType,
                         output_format: OutputFormat, custom_prompt: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """检查内容哈希缓存，返回完整结果或 None"""
        try:
            cached = self._content_cache.get(
                input_data.data,
                conversion_type.value,
                output_format.value,
                custom_prompt
            )
            if cached:
                logger.info("内容哈希缓存命中")
                # 包装为与 convert_with_ai_target 一致的返回格式
                return {
                    "result": cached,
                    "decision": {"from_cache": True},
                    "ai_capabilities": None,
                    "recommendation": "from cache"
                }
        except Exception as e:
            logger.debug("内容缓存读取失败（可忽略）: %s", e)
        return None

    def _try_store_cached(self, input_data: InputData, conversion_type: ConversionType,
                           output_format: OutputFormat, result_data: ConvertResultData) -> None:
        """将转换结果写入内容哈希缓存"""
        try:
            self._content_cache.set(
                input_data.data,
                conversion_type.value,
                output_format.value,
                result_data
            )
        except Exception as e:
            logger.debug("内容缓存写入失败（可忽略）: %s", e)

    def _build_error_result(self, result_id: str, logs: List[ProcessingLog], error_msg: str) -> Dict[str, Any]:
        """构建错误结果"""
        return {
            "result": ConvertResultData(
                resultId=result_id,
                parseId="",
                fileInfo=FileInfo(fileName="error", fileSize=0, pageCount=0, fileType="unknown"),
                conversionType=ConversionType.AUTO,
                outputFormat=OutputFormat.TEXT,
                extractedContent="",
                convertedContent=error_msg,
                structuredData={"error": True},
                confidence=0.0,
                processingLogs=logs,
                createdAt=datetime.now()
            ),
            "decision": None,
            "ai_capabilities": None,
            "recommendation": f"处理失败: {error_msg}"
        }

    def get_result(self, result_id: str) -> Optional[ConvertResultData]:
        """获取转换结果（带TTL检查）"""
        with self._cache_lock:
            if result_id in self._cache_timestamps:
                if time.time() - self._cache_timestamps[result_id] > self._cache_ttl:
                    self.result_cache.pop(result_id, None)
                    self._cache_timestamps.pop(result_id, None)
                    return None
            return self.result_cache.get(result_id)


class BatchConverter:
    """批量转换器"""

    def __init__(self):
        self.converter = DataConverter()

    def convert_batch(
        self,
        sources: List[Any],
        target_ai_endpoint: Optional[str] = None,
        target_ai_key: Optional[str] = None,
        conversion_type: ConversionType = ConversionType.AUTO,
        output_format: OutputFormat = OutputFormat.JSON
    ) -> List[Dict[str, Any]]:
        """批量转换多个输入"""
        results = []
        for source in sources:
            try:
                result = self.converter.convert_with_ai_target(
                    source=source,
                    target_ai_endpoint=target_ai_endpoint,
                    target_ai_key=target_ai_key,
                    conversion_type=conversion_type,
                    output_format=output_format
                )
                results.append(result)
            except Exception as e:
                logger.error("批量转换失败: %s", e)
                results.append({
                    "error": str(e),
                    "source": str(source)[:100]
                })
        return results