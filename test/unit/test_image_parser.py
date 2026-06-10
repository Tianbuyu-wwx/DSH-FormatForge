"""
Image 解析器单元测试
"""
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.image_parser import ImageParser


class TestImageParserBasic:
    """基础测试"""

    def test_supported_extensions(self):
        parser = ImageParser()
        assert ".jpg" in parser.supported_extensions
        assert ".png" in parser.supported_extensions
        assert ".webp" in parser.supported_extensions

    def test_supported_magic(self):
        parser = ImageParser()
        assert b"\xff\xd8\xff" in parser.supported_magic  # JPEG
        assert b"\x89PNG\r\n\x1a\n" in parser.supported_magic  # PNG

    def test_can_parse_jpg(self):
        parser = ImageParser()
        assert parser.can_parse(Path("/tmp/test.jpg")) == 0.9

    def test_can_parse_by_magic(self):
        parser = ImageParser()
        assert parser.can_parse(Path("/tmp/test"), b"\xff\xd8\xff...") == 0.95

    def test_can_parse_non_image(self):
        parser = ImageParser()
        assert parser.can_parse(Path("/tmp/test.txt")) == 0.0


class TestImageParserMock:
    """Mock 测试"""

    @pytest.fixture
    def parser(self):
        return ImageParser()

    @pytest.fixture
    def mock_image(self):
        """创建模拟图片"""
        img = MagicMock()
        img.format = "JPEG"
        img.size = (800, 600)
        img.mode = "RGB"
        img._getexif.return_value = None
        return img

    def test_parse_jpg(self, parser, mock_image, tmp_path):
        """测试解析 JPG"""
        img_path = tmp_path / "test.jpg"
        img_path.write_bytes(b"\xff\xd8\xfffake_jpeg_data")

        with patch('parsers.image_parser.IMAGE_AVAILABLE', True), \
             patch('parsers.image_parser.Image.open', return_value=mock_image):
            result = parser.parse(img_path)

            assert len(result) == 1
            assert result[0].hasImage is True
            # rawText 只包含文件名，实际格式信息在 elements 中
            assert "test.jpg" in result[0].rawText
            image_elem = next(e for e in result[0].elements if e.elementType == "image")
            assert "JPEG" in image_elem.content
            assert "800" in image_elem.content

    def test_parse_with_exif(self, parser, tmp_path):
        """测试 EXIF 提取"""
        img_path = tmp_path / "test_exif.jpg"
        img_path.write_bytes(b"\xff\xd8\xfffake")

        mock_img = MagicMock()
        mock_img.format = "JPEG"
        mock_img.size = (1024, 768)
        mock_img.mode = "RGB"
        mock_img._getexif.return_value = {
            306: "2024:01:01 12:00:00",  # DateTime
            271: "Canon",                # Make
            272: "EOS 5D",               # Model
        }

        with patch('parsers.image_parser.IMAGE_AVAILABLE', True), \
             patch('parsers.image_parser.Image.open', return_value=mock_img):
            result = parser.parse(img_path)

            exif_elements = [e for e in result[0].elements if e.elementType == "metadata"]
            assert len(exif_elements) == 1
            assert "Canon" in exif_elements[0].content

    def test_parse_with_ocr(self, parser, tmp_path):
        """测试 OCR 识别"""
        img_path = tmp_path / "test_ocr.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake_png")

        mock_img = MagicMock()
        mock_img.format = "PNG"
        mock_img.size = (400, 300)
        mock_img.mode = "RGBA"
        mock_img._getexif.return_value = None

        mock_ocr_engine = MagicMock()
        mock_ocr_engine.is_available.return_value = True
        mock_ocr_result = MagicMock()
        mock_ocr_result.text = "识别出的文字"
        mock_ocr_result.confidence = 0.85
        mock_ocr_result.method = "tesseract"
        mock_ocr_engine.extract_text_from_image.return_value = mock_ocr_result

        parser_with_ocr = ImageParser(ocr_engine=mock_ocr_engine)

        with patch('parsers.image_parser.IMAGE_AVAILABLE', True), \
             patch('parsers.image_parser.Image.open', return_value=mock_img):
            result = parser_with_ocr.parse(img_path, use_ocr=True)

            ocr_elements = [e for e in result[0].elements if e.metadata and e.metadata.get("ocr")]
            assert len(ocr_elements) == 1
            assert ocr_elements[0].content == "识别出的文字"
            assert ocr_elements[0].metadata["confidence"] == 0.85

    def test_parse_ocr_not_available(self, parser, tmp_path):
        """测试 OCR 不可用"""
        img_path = tmp_path / "test_no_ocr.png"
        img_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

        mock_img = MagicMock()
        mock_img.format = "PNG"
        mock_img.size = (100, 100)
        mock_img.mode = "RGB"
        mock_img._getexif.return_value = None

        with patch('parsers.image_parser.IMAGE_AVAILABLE', True), \
             patch('parsers.image_parser.Image.open', return_value=mock_img):
            result = parser.parse(img_path, use_ocr=True)

            # 没有 OCR 引擎，不应有 OCR 元素
            ocr_elements = [e for e in result[0].elements if e.metadata and e.metadata.get("ocr")]
            assert len(ocr_elements) == 0

    def test_parse_image_error(self, parser, tmp_path):
        """测试图片读取失败"""
        img_path = tmp_path / "broken.jpg"
        img_path.write_bytes(b"not_an_image")

        with patch('parsers.image_parser.IMAGE_AVAILABLE', True), \
             patch('parsers.image_parser.Image.open', side_effect=Exception("无法打开")):
            result = parser.parse(img_path)

            assert result[0].hasImage is True
            # 错误信息可能在 rawText 或元素 content 中
            assert "无法" in result[0].rawText or "无法" in result[0].elements[0].content

    def test_parse_without_pillow(self, parser):
        """测试未安装 Pillow"""
        with patch('parsers.image_parser.IMAGE_AVAILABLE', False):
            with pytest.raises(ImportError):
                parser.parse(Path("/tmp/test.jpg"))


class TestImageParserExif:
    """EXIF 测试"""

    def test_extract_exif_none(self):
        parser = ImageParser()
        mock_img = MagicMock()
        mock_img._getexif.return_value = None

        result = parser._extract_exif(mock_img)
        assert result is None

    def test_format_exif_empty(self):
        parser = ImageParser()
        assert parser._format_exif({}) == ""

    def test_format_exif_with_data(self):
        parser = ImageParser()
        exif = {
            'DateTime': '2024:01:01 12:00:00',
            'Make': 'Canon',
            'Model': 'EOS 5D'
        }
        result = parser._format_exif(exif)
        assert "Canon" in result
        assert "EOS 5D" in result


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
