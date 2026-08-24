"""
转换决策引擎
根据输入格式与文件解析结果，制定确定性转换策略。
插件形态下不探测远端 AI 能力；「是否保留原始内容交给模型」由调用方决定。
"""

import logging
from typing import Any

logger = logging.getLogger("decision_engine")

# 无文字层、需要 OCR/描述的图片格式
_IMAGE_FORMATS = {"png", "jpeg", "gif", "webp", "bmp", "tiff"}


class ConversionDecision:
    """转换决策记录"""

    def __init__(
        self,
        input_format: str,
        conversion_needed: bool = True,
        target_format: str = "text",
        strategies: list[str] | None = None,
        preserve_original: bool = False,
    ):
        self.input_format = input_format
        self.conversion_needed = conversion_needed
        self.target_format = target_format
        self.strategies = strategies or []
        self.preserve_original = preserve_original

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_format": self.input_format,
            "conversion_needed": self.conversion_needed,
            "target_format": self.target_format,
            "strategies": self.strategies,
            "preserve_original": self.preserve_original,
        }


class DecisionEngine:
    """
    转换决策引擎

    职责：
    1. 根据输入格式与文件内容制定转换决策（确定性规则）
    2. 判断是否需要转换
    3. 生成使用建议

    注：ai_caps 参数保留占位以兼容旧调用签名，恒为 None。
    """

    def __init__(self):
        logger.debug("DecisionEngine 初始化完成")

    def make_decision(self, detected: Any, ai_caps: Any = None, parsed_file: Any = None) -> ConversionDecision:
        """制定转换决策"""
        decision = ConversionDecision(input_format=detected.format.value)
        logger.debug(
            "制定转换决策: input_format=%s, has_parsed_file=%s",
            detected.format.value,
            bool(parsed_file),
        )

        if detected.format.value in _IMAGE_FORMATS:
            # 图片输入：需要 OCR / 结构化描述
            decision.conversion_needed = True
            decision.target_format = "text"
            decision.strategies = ["ocr", "image_description"]
            logger.debug("图片输入，需要 OCR/描述转换")
            return decision

        if detected.format.value in ("pdf", "pptx"):
            has_image = bool(parsed_file and any(page.hasImage for page in parsed_file.pages))
            logger.debug("文档输入: has_image=%s", has_image)
            decision.conversion_needed = True
            decision.strategies = ["text_extraction", "ocr"] if has_image else ["text_extraction"]
            decision.target_format = "text"
            return decision

        # 其他格式，默认走自动检测策略
        decision.conversion_needed = True
        decision.target_format = "text"
        decision.strategies = ["auto_detect"]
        logger.debug("其他格式，使用自动检测策略")
        return decision

    def build_recommendation(self, decision: ConversionDecision) -> str:
        """构建使用建议"""
        if not decision.conversion_needed:
            return "目标模型支持直接处理此格式，建议保留原始文件直接发送。"

        if decision.preserve_original:
            return "转换完成。建议同时发送原始文件和转换后的文本，以获得最佳效果。"

        return "转换完成。请将转换后的文本发送给目标模型。"
