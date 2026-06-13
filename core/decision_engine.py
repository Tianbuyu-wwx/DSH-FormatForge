"""
转换决策引擎
负责分析输入格式、AI能力，制定最优转换策略
"""
import logging
from typing import Any

from core.provider_registry import AiCapabilities

logger = logging.getLogger("decision_engine")


class ConversionDecision:
    """转换决策记录"""

    def __init__(
        self,
        input_format: str,
        target_ai_capabilities: AiCapabilities | None = None,
        conversion_needed: bool = True,
        target_format: str = "text",
        strategies: list[str] = None,
        preserve_original: bool = False
    ):
        self.input_format = input_format
        self.target_ai_capabilities = target_ai_capabilities
        self.conversion_needed = conversion_needed
        self.target_format = target_format
        self.strategies = strategies or []
        self.preserve_original = preserve_original

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_format": self.input_format,
            "target_ai": self.target_ai_capabilities.to_dict() if self.target_ai_capabilities else None,
            "conversion_needed": self.conversion_needed,
            "target_format": self.target_format,
            "strategies": self.strategies,
            "preserve_original": self.preserve_original
        }


class DecisionEngine:
    """
    转换决策引擎

    职责：
    1. 根据输入格式、AI能力、文件内容制定转换决策
    2. 判断是否需要转换
    3. 生成使用建议
    """

    def __init__(self):
        logger.debug("DecisionEngine 初始化完成")

    def make_decision(
        self,
        detected: Any,
        ai_caps: AiCapabilities | None,
        parsed_file: Any
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

    def build_recommendation(
        self,
        decision: ConversionDecision,
        ai_caps: AiCapabilities | None
    ) -> str:
        """构建使用建议"""
        if not decision.conversion_needed:
            return f"目标AI ({ai_caps.provider if ai_caps else 'unknown'}) 支持直接处理此格式，建议保留原始文件直接发送。"

        if decision.preserve_original:
            return "转换完成。建议同时发送原始文件和转换后的文本，以获得最佳效果。"

        return "转换完成。请将转换后的文本发送给目标AI。"
