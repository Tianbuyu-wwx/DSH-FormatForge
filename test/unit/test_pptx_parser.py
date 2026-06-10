"""
PPTX 解析器单元测试
"""
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.pptx_parser import PPTXParser


class TestPPTXParserBasic:
    """基础测试"""

    def test_supported_extensions(self):
        parser = PPTXParser()
        assert ".pptx" in parser.supported_extensions
        assert ".ppt" in parser.supported_extensions

    def test_supported_magic(self):
        parser = PPTXParser()
        assert b"PK\x03\x04" in parser.supported_magic

    def test_can_parse_pptx(self):
        parser = PPTXParser()
        assert parser.can_parse(Path("/tmp/test.pptx")) == 0.9

    def test_can_parse_non_pptx(self):
        parser = PPTXParser()
        assert parser.can_parse(Path("/tmp/test.txt")) == 0.0


class TestPPTXParserMock:
    """Mock 测试"""

    @pytest.fixture
    def parser(self):
        return PPTXParser()

    @pytest.fixture
    def mock_slide(self):
        """创建模拟幻灯片"""
        slide = MagicMock()

        # 标题
        title_shape = MagicMock()
        title_shape.text = "幻灯片标题"

        # 普通文本形状
        text_shape = MagicMock()
        text_shape.text = "这是正文内容"
        text_shape.has_table = False
        text_shape.shape_type = None

        # shapes 需要同时支持列表迭代和 .title 属性访问
        shapes = MagicMock()
        shapes.title = title_shape
        shapes.__iter__ = MagicMock(return_value=iter([title_shape, text_shape]))
        shapes.__getitem__ = MagicMock(side_effect=lambda i: [title_shape, text_shape][i])
        shapes.__len__ = MagicMock(return_value=2)
        slide.shapes = shapes
        slide.has_notes_slide = False
        return slide

    def test_parse_single_slide(self, parser, mock_slide):
        """测试单页幻灯片解析"""
        with patch('parsers.pptx_parser.PPTX_AVAILABLE', True), \
             patch('parsers.pptx_parser.Presentation') as mock_pres:
            mock_prs = MagicMock()
            mock_prs.slides = [mock_slide]
            mock_pres.return_value = mock_prs

            result = parser.parse(Path("/tmp/test.pptx"))

            assert len(result) == 1
            assert result[0].pageNumber == 1
            assert "幻灯片标题" in result[0].rawText

    def test_parse_multiple_slides(self, parser, mock_slide):
        """测试多页幻灯片"""
        with patch('parsers.pptx_parser.PPTX_AVAILABLE', True), \
             patch('parsers.pptx_parser.Presentation') as mock_pres:
            mock_prs = MagicMock()
            mock_prs.slides = [mock_slide, mock_slide]
            mock_pres.return_value = mock_prs

            result = parser.parse(Path("/tmp/test.pptx"))

            assert len(result) == 2
            assert result[0].pageNumber == 1
            assert result[1].pageNumber == 2

    def test_parse_slide_with_table(self, parser):
        """测试包含表格的幻灯片"""
        slide = MagicMock()
        slide.shapes.title = None

        table_shape = MagicMock()
        table_shape.has_table = True
        table_shape.shape_type = None
        table_shape.text = ""

        table = MagicMock()
        row = MagicMock()
        cell = MagicMock()
        cell.text = "单元格"
        row.cells = [cell, cell]
        table.rows = [row]
        table.columns = [MagicMock(), MagicMock()]
        table_shape.table = table

        slide.shapes = [table_shape]
        slide.has_notes_slide = False

        with patch('parsers.pptx_parser.PPTX_AVAILABLE', True), \
             patch('parsers.pptx_parser.Presentation') as mock_pres:
            mock_prs = MagicMock()
            mock_prs.slides = [slide]
            mock_pres.return_value = mock_prs

            result = parser.parse(Path("/tmp/test.pptx"))

            assert result[0].hasTable is True
            table_elements = [e for e in result[0].elements if e.elementType == "table"]
            assert len(table_elements) == 1

    def test_parse_slide_with_image(self, parser):
        """测试包含图片的幻灯片"""
        slide = MagicMock()
        slide.shapes.title = None

        img_shape = MagicMock()
        img_shape.has_table = False
        img_shape.shape_type.name = "PICTURE"
        img_shape.name = "图片1"
        img_shape.text = ""

        slide.shapes = [img_shape]
        slide.has_notes_slide = False

        with patch('parsers.pptx_parser.PPTX_AVAILABLE', True), \
             patch('parsers.pptx_parser.Presentation') as mock_pres:
            mock_prs = MagicMock()
            mock_prs.slides = [slide]
            mock_pres.return_value = mock_prs

            result = parser.parse(Path("/tmp/test.pptx"))

            assert result[0].hasImage is True
            img_elements = [e for e in result[0].elements if e.elementType == "image"]
            assert len(img_elements) == 1

    def test_parse_slide_with_notes(self, parser):
        """测试包含备注的幻灯片"""
        slide = MagicMock()
        slide.shapes.title = None

        notes_slide = MagicMock()
        notes_text_frame = MagicMock()
        notes_text_frame.text = "这是备注内容"
        notes_slide.notes_text_frame = notes_text_frame
        slide.notes_slide = notes_slide
        slide.has_notes_slide = True
        slide.shapes = []

        with patch('parsers.pptx_parser.PPTX_AVAILABLE', True), \
             patch('parsers.pptx_parser.Presentation') as mock_pres:
            mock_prs = MagicMock()
            mock_prs.slides = [slide]
            mock_pres.return_value = mock_prs

            result = parser.parse(Path("/tmp/test.pptx"))

            note_elements = [e for e in result[0].elements if e.elementType == "note"]
            assert len(note_elements) == 1
            assert "备注内容" in note_elements[0].content

    def test_parse_without_pptx_lib(self, parser):
        """测试未安装 python-pptx"""
        with patch('parsers.pptx_parser.PPTX_AVAILABLE', False):
            with pytest.raises(ImportError):
                parser.parse(Path("/tmp/test.pptx"))


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
