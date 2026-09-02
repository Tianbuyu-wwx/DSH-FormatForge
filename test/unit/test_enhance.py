"""EVOLUTION_PLAN M1 —— enhance 下沉管线层的单元测试。"""

import pytest

from core.enhance import EnhanceHint, build_enhance_hint


class FakeElement:
    def __init__(self, element_type: str):
        self.elementType = element_type


class FakePage:
    def __init__(self, raw_text: str = "", has_table: bool = False, elements=None):
        self.rawText = raw_text
        self.hasTable = has_table
        self.elements = elements or []


def _parsed(pages):
    class P:
        pass

    p = P()
    p.pages = pages
    return p


class TestBuildEnhanceHint:
    def test_none_when_no_parsed_file(self):
        assert build_enhance_hint(None, 0.9) is None

    def test_none_when_no_pages(self):
        assert build_enhance_hint(_parsed([]), 0.9) is None

    def test_image_only_triggered_at_half_textless(self):
        pages = [FakePage(""), FakePage(""), FakePage("has text")]
        hint = build_enhance_hint(_parsed(pages), 0.95)
        assert hint is not None
        assert hint.reason == "image_only"
        assert "2/3" in hint.hint
        assert hint.needed is True

    def test_low_confidence_triggered_below_threshold(self):
        pages = [FakePage("text")]
        hint = build_enhance_hint(_parsed(pages), 0.4)
        assert hint.reason == "low_confidence"
        assert "0.40" in hint.hint

    def test_table_sparse_triggered_when_cells_missing(self):
        pages = [FakePage("text", has_table=True, elements=[FakeElement("paragraph")])]
        hint = build_enhance_hint(_parsed(pages), 0.95)
        assert hint.reason == "table_sparse"

    def test_no_trigger_when_healthy(self):
        pages = [
            FakePage("full text", has_table=True, elements=[FakeElement("table")]),
            FakePage("more text"),
        ]
        assert build_enhance_hint(_parsed(pages), 0.95) is None

    def test_image_only_wins_over_low_confidence(self):
        pages = [FakePage(""), FakePage("")]
        hint = build_enhance_hint(_parsed(pages), 0.3)
        assert hint.reason == "image_only"

    def test_to_dict_shape(self):
        hint = EnhanceHint(needed=True, reason="image_only", hint="h")
        assert hint.to_dict() == {"needed": True, "reason": "image_only", "hint": "h"}


class TestOcrLowConfidence:
    """v0.14.0/B-P1-6: OCR 后纯图片 PDF 文字层置信度低时触发 enhance。

    场景：扫描件 PDF 经过 OCR 文字层已被填充（不再 image_only），
    但 OCR confidence < 0.6 → 触发 ocr_low_confidence 让会话模型复核。
    """

    def test_ocr_low_confidence_triggers(self):
        """OCR confidence 0.4 < 阈值 0.6 → 触发。"""
        pages = [
            FakePage("OCR填充的文字层"),
            FakePage("另一页 OCR 文字"),
        ]
        # confidence 高（0.9）但 OCR confidence 低（0.4）
        hint = build_enhance_hint(_parsed(pages), 0.9, ocr_confidence=0.4)
        assert hint is not None
        assert hint.reason == "ocr_low_confidence"
        assert "OCR" in hint.hint or "0.4" in hint.hint

    def test_ocr_high_confidence_no_trigger(self):
        """OCR confidence 0.85 ≥ 阈值 0.6 → 不触发。"""
        pages = [FakePage("OCR 文字"), FakePage("另一页")]
        hint = build_enhance_hint(_parsed(pages), 0.9, ocr_confidence=0.85)
        assert hint is None

    def test_ocr_confidence_none_unchanged_behavior(self):
        """ocr_confidence 不传 → 行为与 v0.13.0 一致（向后兼容）。"""
        pages = [FakePage("正常文字"), FakePage("另一页")]
        # 不传 ocr_confidence，confidence 高
        hint = build_enhance_hint(_parsed(pages), 0.9)
        assert hint is None
        # 不传 ocr_confidence，confidence 低 → 触发 low_confidence
        hint = build_enhance_hint(_parsed(pages), 0.3)
        assert hint is not None
        assert hint.reason == "low_confidence"

    def test_ocr_low_confidence_wins_over_text_filled(self):
        """关键场景：文字层已 OCR 填充（textless 比例低）但 OCR confidence 低 → 应触发 ocr_low_confidence 而非 None。"""
        pages = [
            FakePage("OCR 填充 1"),  # 文字层有内容（OCR 填的）
            FakePage("OCR 填充 2"),
        ]
        hint = build_enhance_hint(_parsed(pages), 0.9, ocr_confidence=0.3)
        assert hint is not None
        assert hint.reason == "ocr_low_confidence"

    def test_image_only_wins_over_ocr_low_confidence(self):
        """image_only 优先于 ocr_low_confidence（文字层缺失比 OCR 置信度低更严重）。"""
        pages = [FakePage(""), FakePage("")]  # 全空
        hint = build_enhance_hint(_parsed(pages), 0.9, ocr_confidence=0.3)
        assert hint.reason == "image_only"
