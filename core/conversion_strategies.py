"""
数据转换策略模块
提供多种转换策略，根据AI能力自动选择最佳方案
"""
import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from core.ai_discovery import AiCapabilities, InputType
from core.models import ConversionType, FileType, OutputFormat, ParsedFile, ProcessingLog

logger = logging.getLogger("conversion_strategies")


class ConversionStrategy(ABC):
    """转换策略抽象基类"""

    def __init__(self):
        self.strategy_id = "base"
        self.strategy_name = "基础策略"
        self.description = "基础转换策略"
        self.supported_types: list[FileType] = []

    @abstractmethod
    def can_handle(self, parsed_file: ParsedFile, ai_caps: AiCapabilities | None = None) -> float:
        """
        评估对输入数据的处理能力
        Args:
            parsed_file: 解析后的文件
            ai_caps: 目标AI能力（可选，用于决策）
        Returns: 置信度 0.0-1.0
        """
        pass

    @abstractmethod
    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: AiCapabilities | None = None,
        custom_prompt: str | None = None
    ) -> dict[str, Any]:
        """
        执行转换
        Returns: {"content": str, "structured_data": dict, "confidence": float}
        """
        pass

    def _create_log(self, step: str, message: str, level: str = "info") -> ProcessingLog:
        """创建处理日志"""
        return ProcessingLog(
            timestamp=datetime.now(),
            level=level,
            message=message,
            step=step
        )

    def _format_output(self, content: str, output_format: OutputFormat) -> str:
        """根据输出格式格式化内容"""
        if output_format == OutputFormat.JSON:
            try:
                return json.dumps({"content": content}, ensure_ascii=False, indent=2)
            except Exception:
                return content
        elif output_format == OutputFormat.MARKDOWN:
            return f"# 转换结果\n\n{content}"
        else:
            return content


class AutoDetectStrategy(ConversionStrategy):
    """自动检测策略 - 分析内容特征和AI能力，选择最佳子策略"""

    def __init__(self):
        super().__init__()
        self.strategy_id = "auto_detect"
        self.strategy_name = "自动检测"
        self.description = "自动分析内容特征和AI能力，选择最合适的转换策略"
        self.supported_types = [FileType.PPT, FileType.PDF, FileType.IMAGE, FileType.DOC, FileType.TXT, FileType.CSV, FileType.XLS]

    def can_handle(self, parsed_file: ParsedFile, ai_caps: AiCapabilities | None = None) -> float:
        return 0.9

    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: AiCapabilities | None = None,
        custom_prompt: str | None = None
    ) -> dict[str, Any]:
        logs = [self._create_log("auto_detect", "开始自动检测内容特征")]
        logger.info("[strategy=auto_detect] 开始自动检测: file_type=%s, output_format=%s",
                    parsed_file.fileType.value, output_format.value)

        # 分析内容特征
        has_tables = any(page.hasTable for page in parsed_file.pages)
        has_images = any(page.hasImage for page in parsed_file.pages)
        total_text = sum(len(page.rawText) for page in parsed_file.pages)

        logger.debug("[strategy=auto_detect] 内容特征: text=%d chars, has_tables=%s, has_images=%s",
                     total_text, has_tables, has_images)
        logs.append(self._create_log(
            "feature_analysis",
            f"分析结果: 文本量={total_text}字符, 含表格={has_tables}, 含图片={has_images}"
        ))

        # 如果提供了AI能力，考虑AI支持情况
        ai_supports_images = ai_caps and ai_caps.supports_input(InputType.IMAGE) if ai_caps else False

        # 根据特征和AI能力选择策略
        if has_tables and not has_images:
            logger.info("[strategy=auto_detect] 选择表格提取策略")
            logs.append(self._create_log("strategy_select", "选择表格提取策略"))
            strategy = TableExtractionStrategy()
        elif parsed_file.fileType == FileType.IMAGE or (has_images and not ai_supports_images):
            # 如果AI不支持图片输入，需要图片描述
            logger.info("[strategy=auto_detect] 选择图片描述策略（AI不支持图片输入）")
            logs.append(self._create_log("strategy_select", "选择图片描述策略（AI不支持图片输入）"))
            strategy = ImageDescriptionStrategy()
        elif total_text > 5000:
            logger.info("[strategy=auto_detect] 选择结构化提取策略")
            logs.append(self._create_log("strategy_select", "选择结构化提取策略"))
            strategy = StructuredExtractionStrategy()
        else:
            logger.info("[strategy=auto_detect] 选择纯文本提取策略")
            logs.append(self._create_log("strategy_select", "选择纯文本提取策略"))
            strategy = TextExtractionStrategy()

        result = strategy.convert(parsed_file, output_format, ai_caps, custom_prompt)
        result["logs"] = logs + result.get("logs", [])
        logger.info("[strategy=auto_detect] 子策略执行完成: sub_strategy=%s, confidence=%.2f",
                    strategy.strategy_id, result.get("confidence", 0))
        return result


class TextExtractionStrategy(ConversionStrategy):
    """纯文本提取策略"""

    def __init__(self):
        super().__init__()
        self.strategy_id = "text_extraction"
        self.strategy_name = "纯文本提取"
        self.description = "提取文件中的纯文本内容，保留原始格式"
        self.supported_types = [FileType.PPT, FileType.PDF, FileType.DOC, FileType.TXT]

    def can_handle(self, parsed_file: ParsedFile, ai_caps: AiCapabilities | None = None) -> float:
        if parsed_file.fileType in self.supported_types:
            return 0.95
        return 0.3

    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: AiCapabilities | None = None,
        custom_prompt: str | None = None
    ) -> dict[str, Any]:
        logs = [self._create_log("text_extract", "开始提取纯文本")]
        logger.info("[strategy=text_extract] 开始提取纯文本: pages=%d", len(parsed_file.pages))

        parts = []
        for page in parsed_file.pages:
            parts.append(f"--- 第 {page.pageNumber} 页 ---")
            parts.append(page.rawText)

        content = "\n\n".join(parts)

        logger.info("[strategy=text_extract] 提取完成: total_chars=%d", len(content))
        logs.append(self._create_log("text_extract", f"提取完成，共 {len(content)} 字符"))

        return {
            "content": self._format_output(content, output_format),
            "structured_data": {"pages": len(parsed_file.pages), "total_chars": len(content)},
            "confidence": 0.95,
            "logs": logs
        }


class StructuredExtractionStrategy(ConversionStrategy):
    """结构化数据提取策略"""

    def __init__(self):
        super().__init__()
        self.strategy_id = "structured_extraction"
        self.strategy_name = "结构化提取"
        self.description = "将内容提取为结构化格式（JSON/Markdown），保留层级关系"
        self.supported_types = [FileType.PPT, FileType.PDF, FileType.DOC]

    def can_handle(self, parsed_file: ParsedFile, ai_caps: AiCapabilities | None = None) -> float:
        if parsed_file.fileType in [FileType.PPT, FileType.PDF]:
            for page in parsed_file.pages:
                for elem in page.elements:
                    if elem.elementType in ["heading", "title"]:
                        return 0.9
            return 0.6
        return 0.4

    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: AiCapabilities | None = None,
        custom_prompt: str | None = None
    ) -> dict[str, Any]:
        logs = [self._create_log("structured", "开始结构化提取")]
        logger.info("[strategy=structured] 开始结构化提取: pages=%d", len(parsed_file.pages))

        structure = {"document": {"title": parsed_file.fileName, "pages": []}}

        for page in parsed_file.pages:
            page_data = {
                "page_number": page.pageNumber,
                "elements": []
            }
            for elem in page.elements:
                page_data["elements"].append({
                    "type": elem.elementType,
                    "content": elem.content[:500]
                })
            structure["document"]["pages"].append(page_data)

        logger.info("[strategy=structured] 结构化完成: pages=%d, elements=%d",
                    len(parsed_file.pages),
                    sum(len(p["elements"]) for p in structure["document"]["pages"]))
        logs.append(self._create_log("structured", f"结构化完成，共 {len(parsed_file.pages)} 页"))

        content = json.dumps(structure, ensure_ascii=False, indent=2)

        return {
            "content": content,
            "structured_data": structure,
            "confidence": 0.85,
            "logs": logs
        }


class TableExtractionStrategy(ConversionStrategy):
    """表格提取策略"""

    def __init__(self):
        super().__init__()
        self.strategy_id = "table_extraction"
        self.strategy_name = "表格提取"
        self.description = "识别并提取文档中的表格数据，转换为Markdown表格或JSON"
        self.supported_types = [FileType.PDF, FileType.PPT, FileType.CSV, FileType.XLS]

    def can_handle(self, parsed_file: ParsedFile, ai_caps: AiCapabilities | None = None) -> float:
        if any(page.hasTable for page in parsed_file.pages):
            return 0.95
        if parsed_file.fileType in [FileType.CSV, FileType.XLS]:
            return 0.95
        return 0.2

    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: AiCapabilities | None = None,
        custom_prompt: str | None = None
    ) -> dict[str, Any]:
        logs = [self._create_log("table", "开始提取表格数据")]
        logger.info("[strategy=table] 开始提取表格数据: pages=%d", len(parsed_file.pages))

        tables = []
        for page in parsed_file.pages:
            for elem in page.elements:
                if elem.elementType == "table":
                    tables.append({
                        "page": page.pageNumber,
                        "content": elem.content
                    })

        md_tables = []
        for idx, table in enumerate(tables, 1):
            md_table = self._text_to_markdown_table(table["content"])
            md_tables.append(f"### 表格 {idx} (第 {table['page']} 页)\n\n{md_table}")

        content = "\n\n".join(md_tables) if md_tables else "未检测到表格数据"

        logger.info("[strategy=table] 提取完成: tables_found=%d, content_length=%d", len(tables), len(content))
        logs.append(self._create_log("table", f"提取完成，共 {len(tables)} 个表格"))

        return {
            "content": content,
            "structured_data": {"tables_found": len(tables), "tables": tables},
            "confidence": 0.8 if tables else 0.3,
            "logs": logs
        }

    def _text_to_markdown_table(self, text: str) -> str:
        """尝试将文本转换为Markdown表格"""
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        if len(lines) < 2:
            return text

        for sep in ['\t', '|', ',', '  ']:
            rows = [l.split(sep) for l in lines]
            if all(len(r) == len(rows[0]) for r in rows) and len(rows[0]) > 1:
                md = ["| " + " | ".join(rows[0]) + " |"]
                md.append("| " + " | ".join(["---"] * len(rows[0])) + " |")
                for row in rows[1:]:
                    md.append("| " + " | ".join(row) + " |")
                return "\n".join(md)

        return text


class ImageDescriptionStrategy(ConversionStrategy):
    """图片描述策略 - 将图片内容转换为文字描述"""

    def __init__(self):
        super().__init__()
        self.strategy_id = "image_description"
        self.strategy_name = "图片描述"
        self.description = "将图片转换为详细的文字描述，使文本AI能够理解图片内容"
        self.supported_types = [FileType.IMAGE, FileType.PPT, FileType.PDF]

    def can_handle(self, parsed_file: ParsedFile, ai_caps: AiCapabilities | None = None) -> float:
        if parsed_file.fileType == FileType.IMAGE:
            return 0.95
        if any(page.hasImage for page in parsed_file.pages):
            return 0.85
        return 0.1

    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: AiCapabilities | None = None,
        custom_prompt: str | None = None
    ) -> dict[str, Any]:
        logs = [self._create_log("image_desc", "开始处理图片内容")]
        logger.info("[strategy=image_desc] 开始处理图片内容: pages=%d", len(parsed_file.pages))

        # 如果AI支持图片输入，标记为可保留原图
        ai_supports_images = ai_caps and ai_caps.supports_input(InputType.IMAGE) if ai_caps else False

        image_info = []
        for page in parsed_file.pages:
            for elem in page.elements:
                if elem.elementType == "image":
                    image_info.append({
                        "page": page.pageNumber,
                        "description": elem.content or "图片"
                    })

        parts = ["# 图片内容描述\n"]
        for idx, img in enumerate(image_info, 1):
            parts.append(f"## 图片 {idx} (第 {img['page']} 页)")
            parts.append(f"- 位置: 第 {img['page']} 页")
            parts.append(f"- 描述: {img['description']}")
            if ai_supports_images:
                parts.append("- 状态: AI支持图片输入，建议保留原图")
            parts.append("")

        content = "\n".join(parts) if image_info else "未检测到图片内容"

        logger.info("[strategy=image_desc] 处理完成: images_found=%d, ai_supports_images=%s",
                    len(image_info), ai_supports_images)
        logs.append(self._create_log("image_desc", f"处理完成，共 {len(image_info)} 张图片"))

        return {
            "content": content,
            "structured_data": {
                "images_found": len(image_info),
                "images": image_info,
                "ai_supports_images": ai_supports_images
            },
            "confidence": 0.75 if image_info else 0.3,
            "logs": logs
        }


class OcrStrategy(ConversionStrategy):
    """OCR文字识别策略"""

    def __init__(self):
        super().__init__()
        self.strategy_id = "ocr"
        self.strategy_name = "OCR文字识别"
        self.description = "识别图片中的文字内容"
        self.supported_types = [FileType.IMAGE, FileType.PDF, FileType.PPT]

    def can_handle(self, parsed_file: ParsedFile, ai_caps: AiCapabilities | None = None) -> float:
        if parsed_file.fileType == FileType.IMAGE:
            return 0.9
        if any(page.hasImage for page in parsed_file.pages):
            return 0.7
        return 0.1

    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: AiCapabilities | None = None,
        custom_prompt: str | None = None
    ) -> dict[str, Any]:
        logs = [self._create_log("ocr", "开始OCR文字识别")]
        logger.info("[strategy=ocr] 开始OCR文字识别: pages=%d", len(parsed_file.pages))

        all_text = []
        for page in parsed_file.pages:
            if page.rawText.strip():
                all_text.append(f"--- 第 {page.pageNumber} 页 ---")
                all_text.append(page.rawText)

        content = "\n\n".join(all_text) if all_text else "未识别到文字内容"

        logger.info("[strategy=ocr] 识别完成: segments=%d, content_length=%d", len(all_text), len(content))
        logs.append(self._create_log("ocr", f"识别完成，共 {len(all_text)} 段文字"))

        return {
            "content": content,
            "structured_data": {"pages_processed": len(parsed_file.pages)},
            "confidence": 0.8 if all_text else 0.2,
            "logs": logs
        }


class EncodingFixStrategy(ConversionStrategy):
    """编码修复策略"""

    def __init__(self):
        super().__init__()
        self.strategy_id = "encoding_fix"
        self.strategy_name = "编码修复"
        self.description = "检测并修复文本编码问题"
        self.supported_types = [FileType.TXT, FileType.CSV, FileType.UNKNOWN]

    def can_handle(self, parsed_file: ParsedFile, ai_caps: AiCapabilities | None = None) -> float:
        for page in parsed_file.pages:
            text = page.rawText
            if self._has_garbled_text(text):
                return 0.95
        return 0.3

    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: AiCapabilities | None = None,
        custom_prompt: str | None = None
    ) -> dict[str, Any]:
        logs = [self._create_log("encoding", "开始检测编码问题")]
        logger.info("[strategy=encoding_fix] 开始检测编码问题: pages=%d", len(parsed_file.pages))

        fixed_pages = []
        for page in parsed_file.pages:
            fixed_text = self._fix_encoding(page.rawText)
            fixed_pages.append(fixed_text)

        content = "\n\n".join(fixed_pages)

        logger.info("[strategy=encoding_fix] 编码修复完成: pages_fixed=%d, content_length=%d",
                    len(fixed_pages), len(content))
        logs.append(self._create_log("encoding", "编码修复完成"))

        return {
            "content": content,
            "structured_data": {"pages_fixed": len(fixed_pages)},
            "confidence": 0.85,
            "logs": logs
        }

    def _has_garbled_text(self, text: str) -> bool:
        """检测文本是否包含乱码"""
        garbled_patterns = [
            r'[\x00-\x08\x0b-\x0c\x0e-\x1f]',
            r'ï¿½',
            r'Ã[\x80-\xBF]',
        ]
        return any(re.search(p, text) for p in garbled_patterns)

    def _fix_encoding(self, text: str) -> str:
        """尝试修复编码"""
        text = text.replace('ï¿½', '?')
        text = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', text)
        return text


class AiNativeStrategy(ConversionStrategy):
    """AI原生策略 - 为支持多模态的AI保留原始媒体"""

    def __init__(self):
        super().__init__()
        self.strategy_id = "ai_native"
        self.strategy_name = "AI原生格式"
        self.description = "为支持多模态的AI保留原始媒体文件，同时提取文本索引"
        self.supported_types = [FileType.PDF, FileType.PPT, FileType.IMAGE]

    def can_handle(self, parsed_file: ParsedFile, ai_caps: AiCapabilities | None = None) -> float:
        if not ai_caps:
            return 0.1
        # 如果AI支持图片输入，且文件包含图片，此策略优先级高
        if ai_caps.supports_multimodal and any(page.hasImage for page in parsed_file.pages):
            return 0.95
        return 0.1

    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: AiCapabilities | None = None,
        custom_prompt: str | None = None
    ) -> dict[str, Any]:
        logs = [self._create_log("ai_native", "生成AI原生格式（保留媒体+文本索引）")]
        logger.info("[strategy=ai_native] 生成AI原生格式: file=%s, pages=%d", parsed_file.fileName, parsed_file.pageCount)

        # 提取文本索引
        text_index = []
        for page in parsed_file.pages:
            page_summary = {
                "page": page.pageNumber,
                "text_preview": page.rawText[:200] if page.rawText else "",
                "has_image": page.hasImage,
                "has_table": page.hasTable,
                "elements": [
                    {"type": e.elementType, "content": e.content[:100]}
                    for e in page.elements[:5]
                ]
            }
            text_index.append(page_summary)

        content = f"""# AI原生格式数据

## 文件信息
- 文件名: {parsed_file.fileName}
- 页数: {parsed_file.pageCount}
- 类型: {parsed_file.fileType.value}

## 内容索引

{json.dumps(text_index, ensure_ascii=False, indent=2)}

## 说明
此文件包含媒体内容，建议将原始文件直接发送给AI进行处理。
上述索引可用于快速了解文件内容结构。
"""

        logger.info("[strategy=ai_native] 索引生成完成: index_pages=%d", len(text_index))
        logs.append(self._create_log("ai_native", f"生成索引，共 {len(text_index)} 页"))

        return {
            "content": content,
            "structured_data": {
                "type": "ai_native",
                "pages": text_index,
                "recommendation": "保留原始文件直接发送给AI"
            },
            "confidence": 0.9,
            "logs": logs
        }


# ==================== 策略注册表 ====================

class StrategyRegistry:
    """策略注册表 - 管理所有可用策略"""

    def __init__(self):
        self._strategies: dict[str, ConversionStrategy] = {}
        self._register_default_strategies()

    def _register_default_strategies(self):
        """注册默认策略"""
        strategies = [
            AutoDetectStrategy(),
            TextExtractionStrategy(),
            StructuredExtractionStrategy(),
            TableExtractionStrategy(),
            ImageDescriptionStrategy(),
            OcrStrategy(),
            EncodingFixStrategy(),
            AiNativeStrategy(),  # 新增：AI原生策略
        ]
        for s in strategies:
            self._strategies[s.strategy_id] = s
        logger.info("策略注册表初始化完成，共 %d 个策略", len(self._strategies))

    def get_strategy(self, strategy_id: str) -> ConversionStrategy | None:
        """获取指定策略"""
        strategy = self._strategies.get(strategy_id)
        if strategy is None:
            logger.warning("请求未知策略: %s", strategy_id)
        return strategy

    def get_all_strategies(self) -> list[ConversionStrategy]:
        """获取所有策略"""
        return list(self._strategies.values())

    def select_best_strategy(
        self,
        parsed_file: ParsedFile,
        conversion_type: ConversionType,
        ai_caps: AiCapabilities | None = None
    ) -> ConversionStrategy:
        """
        选择最佳策略
        1. 如果指定了具体转换类型，选择对应策略
        2. 否则根据 can_handle 评分选择
        3. 考虑AI能力进行决策
        """
        logger.debug("选择最佳策略: file_type=%s, conversion_type=%s, has_ai_caps=%s",
                     parsed_file.fileType.value, conversion_type.value, bool(ai_caps))

        type_to_strategy = {
            ConversionType.TEXT: "text_extraction",
            ConversionType.STRUCTURED: "structured_extraction",
            ConversionType.TABLE: "table_extraction",
            ConversionType.IMAGE_DESC: "image_description",
            ConversionType.OCR: "ocr",
            ConversionType.ENCODING: "encoding_fix",
        }

        if conversion_type != ConversionType.AUTO:
            strategy_id = type_to_strategy.get(conversion_type)
            if strategy_id and strategy_id in self._strategies:
                logger.info("按指定类型选择策略: conversion_type=%s -> strategy=%s",
                            conversion_type.value, strategy_id)
                return self._strategies[strategy_id]

        # 自动选择：评分最高的策略
        scores = []
        for sid, strategy in self._strategies.items():
            if sid == "auto_detect":
                continue
            score = strategy.can_handle(parsed_file, ai_caps)
            scores.append((sid, score))
            logger.debug("策略评分: %s -> %.2f", sid, score)

        scores.sort(key=lambda x: x[1], reverse=True)

        if scores:
            best_id = scores[0][0]
            best_score = scores[0][1]
            logger.info("自动选择最佳策略: %s (score=%.2f)", best_id, best_score)
            return self._strategies[best_id]

        logger.warning("未找到合适策略，回退到文本提取")
        return self._strategies.get("text_extraction", TextExtractionStrategy())


# 全局策略注册表
strategy_registry = StrategyRegistry()
