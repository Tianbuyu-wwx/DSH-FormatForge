"""
OCR 触发策略验证测试
使用真实 PDF 文件验证 OCR 触发逻辑
"""
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.pdf_parser import PDFParser
from core.ocr_engine import OcrEngine, OcrResult


FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


class TestOcrTriggerStrategy:
    """OCR 触发策略测试"""

    @pytest.fixture
    def mock_ocr_engine(self):
        """创建模拟 OCR 引擎"""
        engine = Mock(spec=OcrEngine)
        engine.is_available.return_value = True

        def mock_extract_text_from_image(image_path, **kwargs):
            return OcrResult(
                page_number=1,
                text="[OCR 识别结果] 这是从图片中识别出的文字内容。",
                confidence=0.85,
                method="mock"
            )

        engine.extract_text_from_image.side_effect = mock_extract_text_from_image
        return engine

    def test_pure_image_pdf_triggers_ocr(self, mock_ocr_engine):
        """测试纯图片 PDF 应触发 OCR"""
        pdf_path = FIXTURES_DIR / "image_only_test.pdf"
        if not pdf_path.exists():
            pytest.skip("测试文件不存在")

        parser = PDFParser(ocr_engine=mock_ocr_engine)
        pages = parser.parse(pdf_path, use_ocr=True)

        assert len(pages) == 4
        # 所有页面都应触发 OCR（纯图片页无文字层）
        for page in pages:
            assert page.rawText.strip() != ""
            # 检查是否有 OCR 标记的元素
            ocr_elems = [e for e in page.elements
                         if e.metadata and e.metadata.get("ocr")]
            assert len(ocr_elems) > 0, f"第 {page.pageNumber} 页未触发 OCR"

        # 验证 OCR 引擎被调用
        assert mock_ocr_engine.extract_text_from_image.call_count >= 4

    def test_mixed_pdf_selective_ocr(self, mock_ocr_engine):
        """测试混合 PDF 的选择性 OCR"""
        pdf_path = FIXTURES_DIR / "mixed_content_test.pdf"
        if not pdf_path.exists():
            pytest.skip("测试文件不存在")

        parser = PDFParser(ocr_engine=mock_ocr_engine)
        pages = parser.parse(pdf_path, use_ocr=True)

        assert len(pages) == 3

        # 第1页：纯文字，不应触发 OCR
        page1 = pages[0]
        assert "Text Only" in page1.rawText
        page1_ocr = [e for e in page1.elements
                     if e.metadata and e.metadata.get("ocr")]
        assert len(page1_ocr) == 0, "纯文字页不应触发 OCR"

        # 第2页：纯图片，应触发 OCR
        page2 = pages[1]
        page2_ocr = [e for e in page2.elements
                     if e.metadata and e.metadata.get("ocr")]
        assert len(page2_ocr) > 0, "纯图片页应触发 OCR"

    def test_ocr_disabled_no_trigger(self, mock_ocr_engine):
        """测试禁用 OCR 时不触发"""
        pdf_path = FIXTURES_DIR / "image_only_test.pdf"
        if not pdf_path.exists():
            pytest.skip("测试文件不存在")

        parser = PDFParser(ocr_engine=mock_ocr_engine)
        pages = parser.parse(pdf_path, use_ocr=False)

        # 禁用 OCR 时，纯图片页应无文字
        for page in pages:
            ocr_elems = [e for e in page.elements
                         if e.metadata and e.metadata.get("ocr")]
            assert len(ocr_elems) == 0, "禁用 OCR 时不应有 OCR 元素"

        # OCR 引擎不应被调用
        mock_ocr_engine.extract_text_from_image.assert_not_called()

    def test_ocr_confidence_threshold(self, mock_ocr_engine):
        """测试 OCR 置信度阈值"""
        pdf_path = FIXTURES_DIR / "image_only_test.pdf"
        if not pdf_path.exists():
            pytest.skip("测试文件不存在")

        # 模拟低置信度 OCR 结果
        def low_confidence_ocr(image_path, **kwargs):
            return OcrResult(
                page_number=1,
                text="低置信度结果",
                confidence=0.3,  # 低于默认阈值 0.5
                method="mock"
            )

        mock_ocr_engine.extract_text_from_image.side_effect = low_confidence_ocr

        parser = PDFParser(ocr_engine=mock_ocr_engine)
        pages = parser.parse(pdf_path, use_ocr=True, ocr_min_confidence=0.5)

        # 低置信度结果应被丢弃
        for page in pages:
            assert "低置信度" not in page.rawText

    def test_no_ocr_engine_available(self):
        """测试无 OCR 引擎时的行为"""
        pdf_path = FIXTURES_DIR / "image_only_test.pdf"
        if not pdf_path.exists():
            pytest.skip("测试文件不存在")

        parser = PDFParser(ocr_engine=None)
        pages = parser.parse(pdf_path, use_ocr=True)

        # 无 OCR 引擎时，纯图片页应无文字但不应报错
        assert len(pages) == 4
        for page in pages:
            assert len(page.elements) >= 0

    def test_ocr_backend_selection(self, mock_ocr_engine):
        """测试 OCR 后端选择"""
        pdf_path = FIXTURES_DIR / "image_only_test.pdf"
        if not pdf_path.exists():
            pytest.skip("测试文件不存在")

        parser = PDFParser(ocr_engine=mock_ocr_engine)
        pages = parser.parse(pdf_path, use_ocr=True, ocr_backend="paddleocr")

        # 验证解析成功
        assert len(pages) == 4
        # 检查后端参数传递（通过 mock 调用参数验证）
        for call in mock_ocr_engine.extract_text_from_image.call_args_list:
            kwargs = call[1] if len(call) > 1 else call.kwargs
            assert kwargs.get('backend') == "paddleocr"


class TestOcrTriggerDetection:
    """OCR 触发检测逻辑测试"""

    def test_should_use_ocr_no_text_with_image(self):
        """测试无文字+有图片应触发 OCR"""
        parser = PDFParser()
        assert parser._should_use_ocr("", True, True) is True

    def test_should_use_ocr_no_text_no_image(self):
        """测试无文字+无图片不应触发 OCR"""
        parser = PDFParser()
        assert parser._should_use_ocr("", False, True) is False

    def test_should_use_ocr_with_text_no_image(self):
        """测试有文字+无图片不应触发 OCR"""
        parser = PDFParser()
        assert parser._should_use_ocr("这是一段文字", False, True) is False

    def test_should_use_ocr_short_text_with_image(self):
        """测试文字很少+有图片应触发 OCR"""
        parser = PDFParser()
        assert parser._should_use_ocr("短", True, True) is True

    def test_should_use_ocr_disabled(self):
        """测试禁用 OCR"""
        parser = PDFParser()
        assert parser._should_use_ocr("", True, False) is False

    def test_looks_like_garbage(self):
        """测试乱码检测"""
        parser = PDFParser()
        assert parser._looks_like_garbage("ï¿½ÃÂæç") is True
        assert parser._looks_like_garbage("正常中文文字") is False
        assert parser._looks_like_garbage("") is False

    def test_merge_text_and_ocr(self):
        """测试文字层和 OCR 结果合并"""
        parser = PDFParser()
        pdf_text = "PDF 文字\n另一行"
        ocr_text = "PDF 文字\nOCR 新内容"
        merged = parser._merge_text_and_ocr(pdf_text, ocr_text)
        assert "PDF 文字" in merged
        assert "OCR 新内容" in merged

    def test_text_similarity(self):
        """测试文字相似度计算"""
        parser = PDFParser()
        assert parser._text_similarity("hello", "hello") == 1.0
        assert parser._text_similarity("hello", "world") < 0.5
        assert parser._text_similarity("", "test") == 0.0


class TestOcrRealFiles:
    """使用真实文件验证 OCR 效果"""

    def test_image_only_pdf_structure(self):
        """验证纯图片 PDF 的结构"""
        pdf_path = FIXTURES_DIR / "image_only_test.pdf"
        if not pdf_path.exists():
            pytest.skip("测试文件不存在")

        parser = PDFParser()
        pages = parser.parse(pdf_path, use_ocr=False)

        assert len(pages) == 4
        # 纯图片页无文字层
        for page in pages:
            assert page.rawText.strip() == ""
            assert page.hasImage is True

    def test_mixed_pdf_structure(self):
        """验证混合 PDF 的结构"""
        pdf_path = FIXTURES_DIR / "mixed_content_test.pdf"
        if not pdf_path.exists():
            pytest.skip("测试文件不存在")

        parser = PDFParser()
        pages = parser.parse(pdf_path, use_ocr=False)

        assert len(pages) == 3
        # 第1页有文字
        assert "Text Only" in pages[0].rawText
        # 第2页无文字（纯图片）
        assert pages[1].rawText.strip() == ""


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
