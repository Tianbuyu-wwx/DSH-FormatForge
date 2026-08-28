"""
Pipeline 步骤实现

将原 DataConverter.convert_with_ai_target() 中的 9 个步骤拆分为独立的 Step 类。
每个 Step 职责单一、可独立测试。
"""

import logging
import time
from datetime import datetime
from typing import Any

from core.conversion_strategies import strategy_registry
from core.format_detector import DataFormat
from core.input_adapters import InputAdapterManager, InputData
from core.models import (
    ConvertResultData,
    ExtractedElement,
    FileInfo,
    FileType,
    ParsedFile,
)
from core.utils import create_processing_log, format_output, generate_result_id

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 工具函数（模块级私有）
# ═══════════════════════════════════════════════════════════


def _map_format_to_file_type(fmt: Any) -> str:
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


def _extract_summary(parsed_file: ParsedFile) -> str:
    parts = [page.rawText[:500] for page in parsed_file.pages[:3]]
    summary = "\n".join(parts)
    return summary[:1500] + "..." if len(summary) > 1500 else summary


def _build_raw_content(input_data: InputData, detected: Any) -> str:
    return f"""# 原始数据

- 文件名: {input_data.filename or "unknown"}
- 格式: {detected.format.value}
- MIME类型: {detected.mime_type}
- 大小: {input_data.size} 字节
- 来源: {input_data.source_type}

此数据无需转换，可直接发送给支持该格式的AI。
"""


# ═══════════════════════════════════════════════════════════
# Pipeline 步骤
# ═══════════════════════════════════════════════════════════


class InitStep:
    """步骤 0: 初始化 —— 生成 result_id 和起始日志"""

    def process(self, ctx):
        ctx.result_id = generate_result_id()
        ctx.logs.append(
            create_processing_log("init", f"开始转换: 类型={ctx.conversion_type.value}, 输出={ctx.output_format.value}")
        )
        logger.info(
            "[result_id=%s] 开始转换: source_type=%s, conversion_type=%s, output_format=%s",
            ctx.result_id,
            type(ctx.source).__name__,
            ctx.conversion_type.value,
            ctx.output_format.value,
        )


class InputStep:
    """步骤 1: 输入适配 —— 读取输入源为统一的 InputData"""

    def __init__(self, input_manager: InputAdapterManager):
        self._manager = input_manager

    def process(self, ctx):
        ctx.logs.append(create_processing_log("input", "读取输入源..."))
        try:
            ctx.input_data = self._manager.read(ctx.source)
            logger.info(
                "[result_id=%s] 输入读取成功: source_type=%s, size=%d bytes, filename=%s",
                ctx.result_id,
                ctx.input_data.source_type,
                ctx.input_data.size,
                ctx.input_data.filename,
            )
            ctx.logs.append(
                create_processing_log(
                    "input", f"输入源类型: {ctx.input_data.source_type}, 大小: {ctx.input_data.size} 字节"
                )
            )
        except Exception as e:
            logger.error("[result_id=%s] 输入读取失败: %s", ctx.result_id, e, exc_info=True)
            ctx.logs.append(create_processing_log("input", f"读取失败: {e}", "error"))
            ctx.error = f"输入读取失败: {e}"


class CacheCheckStep:
    """步骤 2: 缓存检查 —— 检查内容哈希缓存，命中则提前返回"""

    def __init__(self, pipeline: Any) -> None:  # pipeline 实为 ConversionPipeline，避免循环引用
        self._pipeline = pipeline

    def process(self, ctx):
        cached = self._pipeline._try_get_cached(
            ctx.input_data,
            ctx.conversion_type,
            ctx.output_format,
            ctx.custom_prompt,
        )
        if cached:
            logger.info("[result_id=%s] 内容缓存命中，跳过转换", ctx.result_id)
            ctx.logs.append(create_processing_log("cache", "缓存命中，直接返回历史结果"))
            ctx.final_response = cached
            ctx.finished = True


class DetectStep:
    """步骤 3: 格式检测 —— 通过魔数/扩展名/内容检测数据格式"""

    def __init__(self, detector):
        self._detector = detector

    def process(self, ctx):
        ctx.logs.append(create_processing_log("detect", "检测输入格式..."))
        ctx.detected = self._detector.detect(ctx.input_data.data, ctx.input_data.filename)
        logger.info(
            "[result_id=%s] 格式检测完成: format=%s, mime=%s, confidence=%.2f",
            ctx.result_id,
            ctx.detected.format.value,
            ctx.detected.mime_type,
            ctx.detected.confidence,
        )
        ctx.logs.append(
            create_processing_log(
                "detect",
                f"检测到格式: {ctx.detected.format.value}, MIME: {ctx.detected.mime_type}, "
                f"置信度: {ctx.detected.confidence:.2f}",
            )
        )


class ParseStep:
    """步骤 4: 文件解析 —— 使用插件化解析器解析文件内容"""

    def __init__(self, pipeline: Any) -> None:  # pipeline 实为 ConversionPipeline，避免循环引用
        self._pipeline = pipeline

    def process(self, ctx):
        if ctx.input_data.source_type not in ("file", "url", "stream"):
            return
        ctx.logs.append(create_processing_log("parse", "解析文件内容..."))
        logger.info(
            "[result_id=%s] 开始解析文件: source_type=%s, detected_format=%s",
            ctx.result_id,
            ctx.input_data.source_type,
            ctx.detected.format.value,
        )
        try:
            from core.config import UPLOAD_DIR
            from core.file_parser import FileParser

            temp_path = ctx.input_data.save_to_temp()
            logger.debug("[result_id=%s] 临时文件已保存: %s", ctx.result_id, temp_path)
            try:
                file_type = _map_format_to_file_type(ctx.detected.format)
                logger.debug(
                    "[result_id=%s] 映射文件类型: %s -> %s", ctx.result_id, ctx.detected.format.value, file_type
                )
                file_parser = FileParser(UPLOAD_DIR)
                # E2: PDF 页选择/家具剔除/双栏选项随 ctx 传入解析器；
                # pages 表达式非法属用户输入错误，先本地校验以便精确报错
                pdf_options = None
                if getattr(ctx, "pages", None):
                    from core.pdf_enhance import parse_pages_spec

                    selected_pages = parse_pages_spec(ctx.pages)  # 非法时抛 ValueError
                    if selected_pages:
                        pdf_options = {"pages": ctx.pages}
                # R3.3: 自愈重试的编码覆写（TXT 解析器消费；其他解析器忽略）
                enc = getattr(ctx, "encoding", None)
                if enc:
                    pdf_options = {**(pdf_options or {}), "encoding": enc}
                ctx.parsed_file = file_parser.parse_file(temp_path, file_type, pdf_options)
                logger.info(
                    "[result_id=%s] 文件解析完成: pages=%d, file_type=%s, parse_id=%s",
                    ctx.result_id,
                    ctx.parsed_file.pageCount,
                    ctx.parsed_file.fileType.value,
                    ctx.parsed_file.parseId,
                )
                ctx.logs.append(
                    create_processing_log(
                        "parse", f"解析完成: {ctx.parsed_file.pageCount} 页, 类型: {ctx.parsed_file.fileType.value}"
                    )
                )
            finally:
                temp_path.unlink(missing_ok=True)
                logger.debug("[result_id=%s] 临时文件已清理", ctx.result_id)
        except ValueError as e:
            # E2: pages 表达式非法等用户输入错误 —— 以协议错误上抛（bad_request）
            logger.warning("[result_id=%s] 解析参数错误: %s", ctx.result_id, e)
            if "pages 参数格式错误" in str(e):
                raise
            ctx.logs.append(create_processing_log("parse", f"解析失败: {e}", "warning"))
        except Exception as e:
            logger.warning("[result_id=%s] 文件解析失败: %s", ctx.result_id, e, exc_info=True)
            ctx.logs.append(create_processing_log("parse", f"解析失败: {e}", "warning"))


class OcrStep:
    """步骤 5b: OCR 增强 —— 对图片类文件执行 OCR 文字识别"""

    # 需要 OCR 的图片类 FileType
    _OCR_TARGET_TYPES = {FileType.IMAGE}

    def process(self, ctx):
        if not ctx.parsed_file:
            return
        if ctx.parsed_file.fileType not in self._OCR_TARGET_TYPES:
            return

        ctx.logs.append(create_processing_log("ocr", "检测到图片文件，尝试 OCR 文字识别..."))
        logger.info("[result_id=%s] 开始 OCR 处理: file_type=%s", ctx.result_id, ctx.parsed_file.fileType.value)

        try:
            from core.ocr_engine import OcrEngine

            ocr_engine = OcrEngine()
            if not ocr_engine.is_available():
                logger.info("[result_id=%s] 无可用 OCR 后端，跳过 OCR", ctx.result_id)
                ctx.logs.append(
                    create_processing_log("ocr", "无可用 OCR 后端（Tesseract/PaddleOCR/EasyOCR 均未安装），跳过")
                )
                return

            available = ocr_engine.get_available_backends()
            logger.info("[result_id=%s] 可用 OCR 后端: %s", ctx.result_id, available)
            ctx.logs.append(create_processing_log("ocr", f"可用 OCR 后端: {', '.join(available)}"))

            # 从 input_data 获取文件路径进行 OCR
            temp_path = ctx.input_data.save_to_temp()
            try:
                ocr_result = ocr_engine.extract_text_from_image(temp_path, apply_postprocess=True)
            finally:
                temp_path.unlink(missing_ok=True)

            if ocr_result and ocr_result.text.strip():
                ocr_text = ocr_result.text
                logger.info(
                    "[result_id=%s] OCR 识别成功: chars=%d, confidence=%.2f, method=%s",
                    ctx.result_id,
                    len(ocr_text),
                    ocr_result.confidence,
                    ocr_result.method,
                )
                ctx.logs.append(
                    create_processing_log(
                        "ocr",
                        f"OCR 识别成功: {len(ocr_text)} 字符, "
                        f"置信度={ocr_result.confidence:.2f}, 引擎={ocr_result.method}",
                    )
                )

                # 将 OCR 文字追加到 parsed_file 的页面中
                for page in ctx.parsed_file.pages:
                    if not any(e.elementType == "text" and e.metadata and e.metadata.get("ocr") for e in page.elements):
                        page.elements.append(
                            ExtractedElement(
                                elementId=f"ocr_{len(page.elements)}",
                                elementType="text",
                                content=ocr_text,
                                metadata={
                                    "ocr": True,
                                    "confidence": ocr_result.confidence,
                                    "method": ocr_result.method,
                                    "chars": len(ocr_text),
                                },
                            )
                        )
                    if not page.rawText.strip():
                        page.rawText = ocr_text
                    elif ocr_text not in page.rawText:
                        page.rawText = page.rawText + "\n\n[OCR 识别结果]\n" + ocr_text
            else:
                logger.info("[result_id=%s] OCR 未识别到文字", ctx.result_id)
                ctx.logs.append(create_processing_log("ocr", "OCR 未识别到文字内容（图片可能为纯图形）"))

        except Exception as e:
            logger.warning("[result_id=%s] OCR 处理失败: %s", ctx.result_id, e, exc_info=True)
            ctx.logs.append(create_processing_log("ocr", f"OCR 处理失败: {e}", "warning"))


class DecisionStep:
    """步骤 6: 决策制定 —— 根据格式与解析结果制定转换决策"""

    def __init__(self, decision_engine):
        self._engine = decision_engine

    def process(self, ctx):
        ctx.decision = self._engine.make_decision(ctx.detected, None, ctx.parsed_file)
        logger.info(
            "[result_id=%s] 转换决策: conversion_needed=%s, target_format=%s, preserve_original=%s, strategies=%s",
            ctx.result_id,
            ctx.decision.conversion_needed,
            ctx.decision.target_format,
            ctx.decision.preserve_original,
            ctx.decision.strategies,
        )
        ctx.logs.append(
            create_processing_log(
                "decision",
                f"转换决策: 需要转换={ctx.decision.conversion_needed}, "
                f"目标格式={ctx.decision.target_format}, "
                f"保留原文件={ctx.decision.preserve_original}",
            )
        )


class ConvertStep:
    """步骤 7: 策略转换 —— 选择最佳策略并执行"""

    def process(self, ctx):
        # R3.3 优先兜底：conversion_needed=False → 永远回退「无需转换」说明页
        if ctx.decision and not ctx.decision.conversion_needed:
            ctx.content = _build_raw_content(ctx.input_data, ctx.detected)
            ctx.structured_data = {"raw_data": True, "size": ctx.input_data.size}
            ctx.confidence = 0.5
            ctx.logs.append(create_processing_log("convert", "无需转换，返回原始数据信息"))
            return
        if ctx.parsed_file and ctx.decision.conversion_needed:
            ctx.logs.append(create_processing_log("convert", "执行数据转换..."))
            try:
                strategy = strategy_registry.select_best_strategy(
                    ctx.parsed_file,
                    ctx.conversion_type,
                )
                ctx.logs.append(create_processing_log("convert", f"选择策略: {strategy.strategy_name}"))

                result = strategy.convert(ctx.parsed_file, ctx.output_format, None, ctx.custom_prompt)
                ctx.logs.extend(result.get("logs", []))
                ctx.content = result.get("content", "")
                ctx.structured_data = result.get("structured_data")
                ctx.confidence = result.get("confidence", 0.0)
                ctx.logs.append(create_processing_log("convert", f"转换完成，置信度: {ctx.confidence:.2f}"))
            except Exception as e:
                ctx.logs.append(create_processing_log("convert", f"转换失败: {e}", "error"))
                ctx.content = f"转换失败: {e}"
                ctx.structured_data = None
                ctx.confidence = 0.0
        elif ctx.input_data.data and len(ctx.input_data.data) > 0 and not ctx.parsed_file:
            data = ctx.input_data.data
            text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else str(data)
            ctx.content = text
            ctx.structured_data = None
            ctx.confidence = 1.0
            ctx.logs.append(create_processing_log("convert", f"raw 文本输入，直接透传 ({len(text)} 字符)"))
        else:
            ctx.content = _build_raw_content(ctx.input_data, ctx.detected)
            ctx.structured_data = {"raw_data": True, "size": ctx.input_data.size}
            ctx.confidence = 0.5
            ctx.logs.append(create_processing_log("convert", "无需转换，返回原始数据信息"))


class FormatStep:
    """步骤 9: 格式化输出 —— 按指定格式格式化内容"""

    def process(self, ctx):
        ctx.logs.append(create_processing_log("format", f"格式化输出为 {ctx.output_format.value}..."))
        ctx.formatted_content = format_output(ctx.content, ctx.output_format, ctx.structured_data)
        logger.debug("[result_id=%s] 格式化输出完成: output_length=%d", ctx.result_id, len(ctx.formatted_content))


class BuildResultStep:
    """步骤 10: 构建结果 —— 组装 ConvertResultData 并缓存"""

    def __init__(self, pipeline: Any) -> None:  # pipeline 实为 ConversionPipeline，避免循环引用
        self._pipeline = pipeline

    def process(self, ctx):
        processing_time = int(time.time() - ctx.start_time)
        logger.info(
            "[result_id=%s] 转换完成: processing_time=%ds, final_confidence=%.2f, logs_count=%d",
            ctx.result_id,
            processing_time,
            ctx.confidence,
            len(ctx.logs),
        )
        ctx.logs.append(create_processing_log("complete", f"转换完成，耗时 {processing_time} 秒"))

        recommendation = self._pipeline.decision_engine.build_recommendation(ctx.decision)

        # M1: enhance 判定下沉管线层 —— CLI/ff_translate/inbox 三通道统一产出
        from core.enhance import build_enhance_hint

        hint = build_enhance_hint(ctx.parsed_file, ctx.confidence)

        result_data = ConvertResultData(
            resultId=ctx.result_id,
            parseId=ctx.parsed_file.parseId if ctx.parsed_file else "",
            fileInfo=FileInfo(
                fileName=ctx.input_data.filename or "unknown",
                fileSize=ctx.input_data.size,
                pageCount=ctx.parsed_file.pageCount if ctx.parsed_file else 0,
                # FileType 为 str 枚举，字面量回退值对齐枚举类型。
                fileType=ctx.parsed_file.fileType if ctx.parsed_file else FileType.UNKNOWN,
            ),
            conversionType=ctx.conversion_type,
            outputFormat=ctx.output_format,
            extractedContent=_extract_summary(ctx.parsed_file) if ctx.parsed_file else "",
            convertedContent=ctx.formatted_content,
            structuredData={
                **(ctx.structured_data or {}),
                "conversion_decision": ctx.decision.to_dict(),
            },
            confidence=ctx.confidence,
            enhance=hint.to_dict() if hint else None,
            processingLogs=ctx.logs,
            createdAt=datetime.now(),
        )

        self._pipeline._add_to_cache(ctx.result_id, result_data)
        self._pipeline._try_store_cached(ctx.input_data, ctx.conversion_type, ctx.output_format, result_data)
        logger.debug("[result_id=%s] 结果已缓存", ctx.result_id)

        ctx.result_data = result_data
        ctx.recommendation = recommendation
        ctx.final_response = {
            "result": result_data,
            "decision": ctx.decision.to_dict(),
            "recommendation": recommendation,
        }
