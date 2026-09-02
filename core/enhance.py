"""enhance 提示判定 —— 管线级唯一出口（EVOLUTION_PLAN M1）。

此前逻辑在 formatforge/__main__.py::_build_enhance_hint，仅 CLI 通道能拿到
enhance 字段；下沉到管线后 CLI / ff_translate / inbox 三通道统一产出。

三触发规则与阈值原样搬迁（PLUGIN_PLAN §6 / EVOLUTION_PLAN §1-M1）：
  image_only      多数页无文字层（扫描件）
  low_confidence  转换置信度过低
  table_sparse    检测到表格但未抽取到结构化单元格
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

#: 判定为「多数页无文字层」的页数占比阈值
IMAGE_ONLY_RATIO = 0.5
#: 低置信度阈值
LOW_CONFIDENCE = 0.5
#: v0.14.0/B-P1-6: OCR 后纯图片 PDF 文字层置信度阈值（OCR confidence < 此值触发 enhance）
OCR_LOW_CONFIDENCE = 0.6


@dataclass(frozen=True)
class EnhanceHint:
    """会话模型增强提示（协议字段 enhance）。"""

    needed: bool
    reason: str
    hint: str

    def to_dict(self) -> dict[str, Any]:
        return {"needed": self.needed, "reason": self.reason, "hint": self.hint}


def build_enhance_hint(
    parsed_file: Any,
    confidence: float,
    ocr_confidence: float | None = None,
) -> EnhanceHint | None:
    """按四触发规则判定是否需要调用方模型增强；不需要返回 None。

    v0.14.0/B-P1-6: 新增 ocr_confidence 可选参数——当 OCR 后纯图片 PDF
    文字层已被 OCR 填充（不再 image_only）但 OCR confidence 低时，
    会触发 enhance 让会话模型复核 OCR 文本。
    """
    if not parsed_file:
        return None

    pages = getattr(parsed_file, "pages", []) or []
    total = len(pages)
    if total == 0:
        return None

    # image_only：多数页无文字层（扫描件）
    textless = sum(1 for p in pages if not (getattr(p, "rawText", "") or "").strip())
    if textless / total >= IMAGE_ONLY_RATIO:
        logger.info("[enhance] image_only 触发: textless=%d/%d", textless, total)
        return EnhanceHint(
            needed=True,
            reason="image_only",
            hint=f"{textless}/{total} 页无文字层（疑似扫描件）。请基于 OCR 文本/图片描述重建结构并补齐表格。",
        )

    # v0.14.0/B-P1-6: OCR 后纯图片 PDF 漏判修复——文字层已 OCR 填充，
    # 但 OCR confidence < 0.6 时仍应提示会话模型复核
    if ocr_confidence is not None and ocr_confidence < OCR_LOW_CONFIDENCE:
        logger.info(
            "[enhance] ocr_low_confidence 触发: ocr_confidence=%.2f",
            ocr_confidence,
        )
        return EnhanceHint(
            needed=True,
            reason="ocr_low_confidence",
            hint=(
                f"OCR 文字层置信度仅 {ocr_confidence:.2f}（阈值 {OCR_LOW_CONFIDENCE}）。"
                "文字已被 OCR 填充，但建议会话模型复核关键字段（数字/专名）。"
            ),
        )

    if confidence < LOW_CONFIDENCE:
        logger.info("[enhance] low_confidence 触发: confidence=%.2f", confidence)
        return EnhanceHint(
            needed=True,
            reason="low_confidence",
            hint=f"转换置信度仅 {confidence:.2f}。请检查内容完整性并修复明显的解析噪声。",
        )

    # table_sparse：检测到表格但抽取内容稀疏
    has_table = any(getattr(p, "hasTable", False) for p in pages)
    table_cells = sum(
        1 for p in pages for e in (getattr(p, "elements", []) or []) if getattr(e, "elementType", "") == "table"
    )
    if has_table and table_cells == 0:
        logger.info("[enhance] table_sparse 触发: has_table=True, cells=0")
        return EnhanceHint(
            needed=True,
            reason="table_sparse",
            hint="检测到表格但未抽取到结构化单元格。请从原始文本重建 Markdown 表格。",
        )

    return None
