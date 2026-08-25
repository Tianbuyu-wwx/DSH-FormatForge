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
