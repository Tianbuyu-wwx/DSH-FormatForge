"""
数据转换引擎
核心转换逻辑，协调输入适配、AI能力发现、策略选择和格式化输出
"""
import uuid
import json
import time
import asyncio
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


logger = logging.getLogger("converter_engine")


class ConversionDecision:
    """转换决策记录"""

    def __init__(
        self,
        input_format: str,
        target_ai_capabilities: Optional[AiCapabilities] = None,
        conversion_needed: bool = True,
        target_format: str = "text",
        strategies: List[str] = None,
        preserve_original: bool = False
    ):
        self.input_format = input_format
        self.target_ai_capabilities = target_ai_capabilities
        self.conversion_needed = conversion_needed
        self.target_format = target_format
        self.strategies = strategies or []
        self.preserve_original = preserve_original

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_format": self.input_format,
            "target_ai": self.target_ai_capabilities.to_dict() if self.target_ai_capabilities else None,
            "conversion_needed": self.conversion_needed,
            "target_format": self.target_format,
            "strategies": self.strategies,
            "preserve_original": self.preserve_original
        }


class DataConverter:
    """
    数据转换引擎

    新职责：
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
        self._max_cache_size = max_cache_size
        self._cache_ttl = cache_ttl
        self.api_semaphore = asyncio.Semaphore(max_concurrent_ai)

        logger.info("初始化 DataConverter: cache_size=%d, cache_ttl=%d, max_concurrent_ai=%d",
                    max_cache_size, cache_ttl, max_concurrent_ai)

        # 初始化子系统
        self.input_manager = InputAdapterManager()
        self.format_detector = FormatDetector()
        self.ai_discovery = AiDiscovery()
        self.ai_client = self._init_ai_client()
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
        from core.conversion_strategies import strategy_registry

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

                # 清理临时文件
                temp_path.unlink(missing_ok=True)
                logger.debug("[result_id=%s] 临时文件已清理", result_id)

            except Exception as e:
                logger.warning("[result_id=%s] 文件解析失败: %s", result_id, e, exc_info=True)
                logs.append(self._create_log("parse", f"解析失败: {e}", "warning"))
                # 解析失败继续，使用原始数据

        # 步骤5: 制定转换决策
        decision = self._make_decision(detected, ai_caps, parsed_file)
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

        # 步骤7: AI增强（如果启用）
        if use_ai_enhance and self.ai_client and confidence < 0.9 and parsed_file:
            logs.append(self._create_log("ai_enhance", "尝试AI增强转换..."))
            logger.info("[result_id=%s] 开始AI增强转换: current_confidence=%.2f", result_id, confidence)
            try:
                ai_result = self._ai_enhance_convert(
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
        formatted_content = self._format_output(content, output_format, structured_data)
        logger.debug("[result_id=%s] 格式化输出完成: output_length=%d", result_id, len(formatted_content))

        # 步骤9: 构建结果
        processing_time = int(time.time() - start_time)
        logger.info("[result_id=%s] 转换完成: processing_time=%ds, final_confidence=%.2f, logs_count=%d",
                    result_id, processing_time, confidence, len(logs))
        logs.append(self._create_log("complete", f"转换完成，耗时 {processing_time} 秒"))

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
        logger.debug("[result_id=%s] 结果已缓存", result_id)

        return {
            "result": result_data,
            "decision": decision.to_dict(),
            "ai_capabilities": ai_caps.to_dict() if ai_caps else None,
            "recommendation": self._build_recommendation(decision, ai_caps)
        }

    def _make_decision(
        self,
        detected: Any,
        ai_caps: Optional[AiCapabilities],
        parsed_file: Optional[ParsedFile]
    ) -> ConversionDecision:
        """制定转换决策"""
        decision = ConversionDecision(
            input_format=detected.format.value
        )
        logger.debug("制定转换决策: input_format=%s, has_ai_caps=%s, has_parsed_file=%s",
                     detected.format.value, bool(ai_caps), bool(parsed_file))

        if not ai_caps:
            # 无AI能力信息，默认需要转换
            decision.conversion_needed = True
            decision.target_format = "text"
            logger.debug("无AI能力信息，默认需要转换为文本")
            return decision

        # 根据AI能力决定是否需要转换
        if detected.format.value in ["png", "jpeg", "gif", "webp", "bmp", "tiff"]:
            # 图片输入
            if ai_caps.supports_input("image"):
                # AI支持图片输入，可以保留原图
                decision.conversion_needed = False
                decision.preserve_original = True
                decision.target_format = "image"
                logger.debug("AI支持图片输入，建议保留原图")
            else:
                # AI不支持图片，需要OCR/描述转换
                decision.conversion_needed = True
                decision.target_format = "text"
                decision.strategies = ["ocr", "image_description"]
                logger.debug("AI不支持图片输入，需要OCR/描述转换")

        elif detected.format.value in ["pdf", "pptx"]:
            # 文档输入
            has_image = parsed_file and any(page.hasImage for page in parsed_file.pages)
            logger.debug("文档输入: has_image=%s, ai_multimodal=%s",
                         has_image, ai_caps.supports_multimodal)
            if has_image:
                if ai_caps.supports_multimodal:
                    # 多模态AI，可以保留原文件
                    decision.conversion_needed = False
                    decision.preserve_original = True
                    decision.target_format = "document"
                    logger.debug("多模态AI支持，建议保留原文件")
                else:
                    decision.conversion_needed = True
                    decision.target_format = "text"
                    decision.strategies = ["text_extraction", "ocr"]
                    logger.debug("非多模态AI，需要文本提取+OCR")
            else:
                decision.conversion_needed = True
                decision.target_format = ai_caps.preferred_format.value
                decision.strategies = ["text_extraction"]
                logger.debug("纯文本文档，使用文本提取策略")

        else:
            # 其他格式，默认转换
            decision.conversion_needed = True
            decision.target_format = ai_caps.preferred_format.value
            decision.strategies = ["auto_detect"]
            logger.debug("其他格式，使用自动检测策略")

        return decision

    def _build_recommendation(
        self,
        decision: ConversionDecision,
        ai_caps: Optional[AiCapabilities]
    ) -> str:
        """构建使用建议"""
        if not decision.conversion_needed:
            return f"目标AI ({ai_caps.provider if ai_caps else 'unknown'}) 支持直接处理此格式，建议保留原始文件直接发送。"

        if decision.preserve_original:
            return "转换完成。建议同时发送原始文件和转换后的文本，以获得最佳效果。"

        return "转换完成。请将转换后的文本发送给目标AI。"

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

    def _ai_enhance_convert(
        self,
        parsed_file: ParsedFile,
        base_content: str,
        output_format: OutputFormat,
        custom_prompt: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """使用AI增强转换"""
        if not self.ai_client:
            logger.debug("AI客户端不可用，跳过增强转换")
            return None

        prompt = self._build_ai_prompt(
            file_name=parsed_file.fileName,
            file_type=parsed_file.fileType.value,
            base_content=base_content,
            output_format=output_format,
            custom_prompt=custom_prompt
        )

        logger.info("调用AI增强转换: file=%s, prompt_length=%d", parsed_file.fileName, len(prompt))
        response_text = self.ai_client.generate_text(prompt)
        logger.info("AI响应长度: %d 字符", len(response_text))

        return self._parse_ai_response(response_text, output_format)

    def _build_ai_prompt(
        self,
        file_name: str,
        file_type: str,
        base_content: str,
        output_format: OutputFormat,
        custom_prompt: Optional[str] = None
    ) -> str:
        """构建AI转换提示词"""
        format_instruction = {
            OutputFormat.JSON: "输出有效的JSON格式",
            OutputFormat.MARKDOWN: "输出Markdown格式",
            OutputFormat.TEXT: "输出纯文本格式",
            OutputFormat.HTML: "输出HTML格式"
        }.get(output_format, "输出结构化文本")

        prompt = f"""你是一个数据转换专家。请将以下从 {file_type} 文件中提取的内容转换为AI可理解和处理的标准格式。

## 文件信息
- 文件名: {file_name}
- 文件类型: {file_type}

## 提取的原始内容

```
{base_content[:4000]}
```

{"(内容已截断，仅显示前4000字符)" if len(base_content) > 4000 else ""}

## 转换要求

1. {format_instruction}
2. 保留所有关键信息和数据
3. 对不完整或模糊的内容进行合理推断
4. 识别并标注内容类型（标题、段落、表格、列表等）
5. 保持内容的层级结构

## 输出格式

{"请输出JSON格式，包含 'content' 和 'structured_data' 字段" if output_format == OutputFormat.JSON else "请直接输出转换后的内容"}

{custom_prompt if custom_prompt else ""}

请直接输出转换结果，不要添加额外说明。"""

        return prompt

    def _parse_ai_response(self, response_text: str, output_format: OutputFormat) -> Dict[str, Any]:
        """解析AI响应"""
        result = {"content": response_text, "structured_data": None}

        if output_format == OutputFormat.JSON:
            try:
                import re
                json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    json_str = response_text.strip()

                parsed = json.loads(json_str)
                result["structured_data"] = parsed
            except Exception as e:
                logger.warning("JSON解析失败: %s", e)

        return result

    def _format_output(self, content: str, output_format: OutputFormat, structured_data: Optional[Dict] = None) -> str:
        """根据输出格式格式化内容"""
        if output_format == OutputFormat.JSON:
            if structured_data:
                return json.dumps(structured_data, ensure_ascii=False, indent=2)
            try:
                return json.dumps({"content": content}, ensure_ascii=False, indent=2)
            except:
                return content
        elif output_format == OutputFormat.MARKDOWN:
            if not content.startswith("#"):
                return f"# 转换结果\n\n{content}"
            return content
        elif output_format == OutputFormat.HTML:
            html = content.replace("\n\n", "</p><p>").replace("\n", "<br>")
            return f"<div class='converted-content'><p>{html}</p></div>"
        else:
            return content

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
        import time

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
        import time

        if result_id in self._cache_timestamps:
            if time.time() - self._cache_timestamps[result_id] > self._cache_ttl:
                self.result_cache.pop(result_id, None)
                self._cache_timestamps.pop(result_id, None)
                return None
        return self.result_cache.get(result_id)

    def export_result(self, result: ConvertResultData, format_type: str = "txt") -> str:
        """导出转换结果"""
        if format_type == "json":
            return json.dumps({
                "resultId": result.resultId,
                "fileName": result.fileInfo.fileName,
                "conversionType": result.conversionType.value,
                "outputFormat": result.outputFormat.value,
                "confidence": result.confidence,
                "content": result.convertedContent,
                "structuredData": result.structuredData,
                "processingLogs": [
                    {"time": log.timestamp.isoformat(), "level": log.level, "message": log.message, "step": log.step}
                    for log in result.processingLogs
                ]
            }, ensure_ascii=False, indent=2)

        elif format_type == "md":
            lines = [
                f"# {result.fileInfo.fileName} - 转换结果",
                "",
                f"- 转换类型: {result.conversionType.value}",
                f"- 输出格式: {result.outputFormat.value}",
                f"- 置信度: {result.confidence:.2f}",
                f"- 生成时间: {result.createdAt.strftime('%Y-%m-%d %H:%M:%S')}",
                "",
                "## 转换内容",
                "",
                result.convertedContent,
                "",
                "## 处理日志",
                ""
            ]
            for log in result.processingLogs:
                lines.append(f"- [{log.level.upper()}] {log.step}: {log.message}")
            return "\n".join(lines)

        else:
            lines = [
                f"转换结果: {result.fileInfo.fileName}",
                f"类型: {result.conversionType.value} | 格式: {result.outputFormat.value} | 置信度: {result.confidence:.2f}",
                "=" * 50,
                "",
                result.convertedContent,
                "",
                "=" * 50,
                "处理日志:",
            ]
            for log in result.processingLogs:
                lines.append(f"  [{log.level}] {log.step}: {log.message}")
            return "\n".join(lines)


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
