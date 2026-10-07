"""
OCR 引擎单元测试
覆盖多后端切换、后处理、PDF 集成等场景
"""
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from core.ocr_engine import (
    OcrEngine, OcrResult, OcrPostProcessor,
    TesseractBackend, PaddleOcrBackend, EasyOcrBackend,
    TESSERACT_AVAILABLE, PADDLEOCR_AVAILABLE, EASYOCR_AVAILABLE
)


class TestOcrPostProcessor:
    """OCR 后处理器测试"""

    def test_process_empty(self):
        assert OcrPostProcessor.process("") == ""

    def test_process_paragraph_merge(self):
        text = "这是第一行\n这是第二行\n这是第三行"
        result = OcrPostProcessor.process(text)
        assert "这是第一行" in result
        # 三行应被合并为一个段落（因为没有新段落特征）
        # 结果中不应有双换行（因为只有一个段落）
        assert result.count('\n') <= 1

    def test_process_list_detection(self):
        text = "• 项目1\n• 项目2\n• 项目3"
        result = OcrPostProcessor.process(text)
        assert "• 项目1" in result
        assert "• 项目2" in result

    def test_process_table_detection(self):
        text = "列1  列2  列3\nA    B    C\nD    E    F"
        result = OcrPostProcessor.process(text)
        assert "|" in result  # 表格应被格式化

    def test_process_ordered_list(self):
        text = "1. 第一项\n2. 第二项\n3. 第三项"
        result = OcrPostProcessor.process(text)
        assert "1. 第一项" in result

    def test_process_chinese_number_list(self):
        text = "一、第一项\n二、第二项"
        result = OcrPostProcessor.process(text)
        assert "一、第一项" in result

    def test_is_table_line(self):
        assert OcrPostProcessor._is_table_line("A\tB\tC") is True
        assert OcrPostProcessor._is_table_line("A | B | C") is True
        assert OcrPostProcessor._is_table_line("普通文本") is False

    def test_is_list_item(self):
        assert OcrPostProcessor._is_list_item("- 项目") is True
        assert OcrPostProcessor._is_list_item("1. 项目") is True
        assert OcrPostProcessor._is_list_item("普通文本") is False

    def test_is_new_paragraph(self):
        assert OcrPostProcessor._is_new_paragraph("# 标题") is True
        assert OcrPostProcessor._is_new_paragraph("1. 列表") is True
        assert OcrPostProcessor._is_new_paragraph("普通文本") is False


class TestTesseractBackend:
    """Tesseract 后端测试"""

    def test_name(self):
        backend = TesseractBackend()
        assert backend.name == "tesseract"

    def test_recognize_not_available(self):
        with patch('core.ocr_engine.TESSERACT_AVAILABLE', False):
            backend = TesseractBackend()
            text, conf = backend.recognize(Path("/tmp/test.png"))
            assert text == ""
            assert conf == 0.0


class TestPaddleOcrBackend:
    """PaddleOCR 后端测试"""

    def test_name(self):
        backend = PaddleOcrBackend()
        assert backend.name == "paddleocr"

    def test_recognize_not_available(self):
        with patch('core.ocr_engine.PADDLEOCR_AVAILABLE', False):
            backend = PaddleOcrBackend()
            text, conf = backend.recognize(Path("/tmp/test.png"))
            assert text == ""
            assert conf == 0.0


class TestEasyOcrBackend:
    """EasyOCR 后端测试"""

    def test_name(self):
        backend = EasyOcrBackend()
        assert backend.name == "easyocr"

    def test_recognize_not_available(self):
        with patch('core.ocr_engine.EASYOCR_AVAILABLE', False):
            backend = EasyOcrBackend()
            text, conf = backend.recognize(Path("/tmp/test.png"))
            assert text == ""
            assert conf == 0.0


class TestOcrEngineInit:
    """OCR 引擎初始化测试"""

    def test_init_default(self):
        # R2.1: 默认引擎按优先级选第一个可用（本机装了 rapidocr 时不再是 tesseract）
        with patch("core.ocr_engine.TESSERACT_AVAILABLE", True), patch("core.ocr_engine.RAPIDOCR_AVAILABLE", False), patch(
            "core.ocr_engine.PADDLEOCR_AVAILABLE", False
        ):
            engine = OcrEngine()
            assert engine.default_backend == "tesseract"
            assert "tesseract" in engine.get_available_backends()

        # rapidocr 优先于 tesseract
        with patch("core.ocr_engine.TESSERACT_AVAILABLE", True), patch("core.ocr_engine.RAPIDOCR_AVAILABLE", True):
            engine = OcrEngine()
            assert engine.default_backend == "rapidocr"

    def test_init_no_backends(self):
        with patch("core.ocr_engine.TESSERACT_AVAILABLE", False), patch("core.ocr_engine.PADDLEOCR_AVAILABLE", False), patch(
            "core.ocr_engine.EASYOCR_AVAILABLE", False
        ), patch("core.ocr_engine.RAPIDOCR_AVAILABLE", False):
            engine = OcrEngine()
            assert engine.get_available_backends() == []
            assert engine.is_available() is False

    def test_set_default_backend(self):
        with patch('core.ocr_engine.TESSERACT_AVAILABLE', True), \
             patch('core.ocr_engine.PADDLEOCR_AVAILABLE', True):
            engine = OcrEngine()
            engine.set_default_backend("paddleocr")
            assert engine.default_backend == "paddleocr"

    def test_set_invalid_backend(self):
        engine = OcrEngine()
        with pytest.raises(ValueError):
            engine.set_default_backend("invalid")

    def test_get_status(self):
        with patch("core.ocr_engine.TESSERACT_AVAILABLE", True), patch("core.ocr_engine.RAPIDOCR_AVAILABLE", False), patch(
            "core.ocr_engine.PADDLEOCR_AVAILABLE", False
        ):
            engine = OcrEngine()
            status = engine.get_status()
            assert "tesseract" in status
            assert "available_backends" in status
            assert status["default_backend"] == "tesseract"


class TestOcrEngineImageOcr:
    """图片 OCR 测试"""

    @pytest.fixture
    def mock_backend(self):
        backend = MagicMock()
        backend.name = "mock"
        backend.recognize.return_value = ("识别文字", 0.9)
        return backend

    def test_extract_text_from_image(self, mock_backend):
        with patch('core.ocr_engine.IMAGE_AVAILABLE', True):
            engine = OcrEngine()
            engine._backends["mock"] = mock_backend
            engine.default_backend = "mock"

            result = engine.extract_text_from_image(Path("/tmp/test.png"))

            assert result.text == "识别文字"
            assert result.confidence == 0.9
            assert result.method == "mock"

    def test_extract_text_with_postprocess(self, mock_backend):
        with patch('core.ocr_engine.IMAGE_AVAILABLE', True):
            engine = OcrEngine()
            engine._backends["mock"] = mock_backend
            engine.default_backend = "mock"

            mock_backend.recognize.return_value = ("行1\n行2\n行3", 0.8)

            result = engine.extract_text_from_image(
                Path("/tmp/test.png"),
                apply_postprocess=True
            )

            assert result.text is not None
            assert result.confidence == 0.8

    def test_extract_text_no_backend(self):
        with patch('core.ocr_engine.IMAGE_AVAILABLE', True):
            engine = OcrEngine()
            engine._backends = {}

            result = engine.extract_text_from_image(Path("/tmp/test.png"))

            assert result.text == ""
            assert result.method == "none"

    def test_batch_ocr(self, mock_backend):
        with patch('core.ocr_engine.IMAGE_AVAILABLE', True):
            engine = OcrEngine()
            engine._backends["mock"] = mock_backend
            engine.default_backend = "mock"

            paths = [Path("/tmp/1.png"), Path("/tmp/2.png")]
            results = engine.batch_ocr(paths)

            assert len(results) == 2
            assert results[0].page_number == 1
            assert results[1].page_number == 2


class TestOcrEnginePdfOcr:
    """PDF OCR 测试"""

    def test_extract_text_from_pdf_no_pdfplumber(self):
        with patch('core.ocr_engine.PDFPLUMBER_AVAILABLE', False):
            engine = OcrEngine()
            with pytest.raises(ImportError):
                engine.extract_text_from_pdf(Path("/tmp/test.pdf"))


class TestOcrEngineIntegration:
    """集成测试"""

    def test_multiple_backends_available(self):
        with patch('core.ocr_engine.TESSERACT_AVAILABLE', True), \
             patch('core.ocr_engine.PADDLEOCR_AVAILABLE', True), \
             patch('core.ocr_engine.EASYOCR_AVAILABLE', True):
            engine = OcrEngine()
            backends = engine.get_available_backends()
            assert "tesseract" in backends
            assert "paddleocr" in backends
            assert "easyocr" in backends

    def test_backend_priority(self):
        """测试后端优先级"""
        with patch('core.ocr_engine.TESSERACT_AVAILABLE', True), \
             patch('core.ocr_engine.PADDLEOCR_AVAILABLE', True):
            engine = OcrEngine(default_backend="paddleocr")
            assert engine.default_backend == "paddleocr"

            result = engine.extract_text_from_image(
                Path("/tmp/test.png"),
                backend="tesseract"
            )
            # 应使用指定的 tesseract 后端
            assert result.method == "tesseract"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])


class TestH17AvailabilityHonesty:
    """H17/audit: is_available() 必须验证 tesseract 二进制，而非只看 pytesseract 可导入。"""

    def test_tesseract_backend_without_binary_is_unavailable(self):
        import core.ocr_engine as ocr

        # 环境里没有 tesseract 二进制时，可用性标志必须是 False（而不是 import 成功就 True）
        if not ocr.TESSERACT_AVAILABLE:
            from core.ocr_engine import OcrEngine

            engine = OcrEngine()
            assert "tesseract" not in engine.get_available_backends()
            assert not engine.is_available() or engine.get_available_backends()

    def test_recognize_returns_empty_at_zero_confidence_when_unavailable(self, tmp_path):
        import core.ocr_engine as ocr

        if ocr.TESSERACT_AVAILABLE:
            pytest.skip("本机装了 tesseract")
        backend = ocr.TesseractBackend()
        text, conf = backend.recognize(tmp_path / "whatever.png")
        assert text == "" and conf == 0.0

    def test_fallback_locates_binary_in_standard_location(self, tmp_path, monkeypatch):
        """H17 跟进：PATH 没有 tesseract 时，标准安装位置探测应找到二进制并启用。"""
        import core.ocr_engine as ocr

        fake_exe = tmp_path / "tesseract.exe"
        fake_exe.write_bytes(b"")  # 只验证「文件存在即命中探测」，版本由 mock 验证
        monkeypatch.setattr(ocr, "_TESSERACT_FALLBACK_PATHS", (str(fake_exe),))
        assert ocr._locate_standard_tesseract_binary() == str(fake_exe)

    def test_fallback_returns_none_when_no_standard_location(self, tmp_path, monkeypatch):
        import core.ocr_engine as ocr

        monkeypatch.setattr(ocr, "_TESSERACT_FALLBACK_PATHS", (str(tmp_path / "missing.exe"),))
        assert ocr._locate_standard_tesseract_binary() is None
