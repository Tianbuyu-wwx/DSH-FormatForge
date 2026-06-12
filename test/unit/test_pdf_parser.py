"""
PDF 解析器单元测试
测试 PDFParser 的各种场景
"""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.pdf_parser import PDFParser
from core.models import PageContent, ExtractedElement


class TestPDFParserBasic:
    """PDF 解析器基础测试"""

    def test_supported_extensions(self):
        """测试支持的扩展名"""
        parser = PDFParser()
        assert ".pdf" in parser.supported_extensions
        assert len(parser.supported_extensions) == 1

    def test_supported_magic(self):
        """测试支持的魔数"""
        parser = PDFParser()
        assert b"%PDF" in parser.supported_magic

    def test_can_parse_with_pdf_extension(self):
        """测试 PDF 扩展名匹配"""
        parser = PDFParser()
        pdf_path = Path("/tmp/test.pdf")
        assert parser.can_parse(pdf_path) == 0.9

    def test_can_parse_with_pdf_magic(self):
        """测试 PDF 魔数匹配"""
        parser = PDFParser()
        pdf_path = Path("/tmp/test.txt")
        content = b"%PDF-1.4\n1 0 obj"
        assert parser.can_parse(pdf_path, content) == 0.95

    def test_can_parse_non_pdf(self):
        """测试非 PDF 文件不匹配"""
        parser = PDFParser()
        txt_path = Path("/tmp/test.txt")
        content = b"Hello World"
        assert parser.can_parse(txt_path, content) == 0.0


class TestPDFParserMock:
    """使用 Mock 测试 PDF 解析"""

    @pytest.fixture
    def parser(self):
        return PDFParser()

    @pytest.fixture
    def mock_pdf_page(self):
        """创建模拟的 PDF 页面对象"""
        page = MagicMock()
        page.extract_text.return_value = "第一行文本\n第二行文本\n标题："
        page.extract_tables.return_value = []
        page.images = []
        return page

    @pytest.fixture
    def mock_pdf_with_table(self):
        """创建包含表格的模拟 PDF 页面对象"""
        page = MagicMock()
        page.extract_text.return_value = "表格数据\n"
        page.extract_tables.return_value = [
            [["姓名", "年龄"], ["张三", "25"], ["李四", "30"]]
        ]
        page.images = []
        return page

    def test_parse_single_page(self, parser, mock_pdf_page):
        """测试单页 PDF 解析"""
        with patch('parsers.pdf_parser.pdfplumber.open') as mock_open:
            mock_pdf = MagicMock()
            mock_pdf.pages = [mock_pdf_page]
            mock_open.return_value.__enter__.return_value = mock_pdf

            result = parser.parse(Path("/tmp/test.pdf"))

            assert len(result) == 1
            assert result[0].pageNumber == 1
            assert result[0].rawText == "第一行文本\n第二行文本\n标题："

    def test_parse_multiple_pages(self, parser, mock_pdf_page):
        """测试多页 PDF 解析"""
        with patch('parsers.pdf_parser.pdfplumber.open') as mock_open:
            mock_pdf = MagicMock()
            mock_pdf.pages = [mock_pdf_page, mock_pdf_page]
            mock_open.return_value.__enter__.return_value = mock_pdf

            result = parser.parse(Path("/tmp/test.pdf"))

            assert len(result) == 2
            assert result[0].pageNumber == 1
            assert result[1].pageNumber == 2

    def test_parse_with_table(self, parser, mock_pdf_with_table):
        """测试包含表格的 PDF 解析"""
        with patch('parsers.pdf_parser.pdfplumber.open') as mock_open:
            mock_pdf = MagicMock()
            mock_pdf.pages = [mock_pdf_with_table]
            mock_open.return_value.__enter__.return_value = mock_pdf

            result = parser.parse(Path("/tmp/test.pdf"))

            assert len(result) == 1
            assert result[0].hasTable is True

            # 检查表格元素
            table_elements = [e for e in result[0].elements if e.elementType == "table"]
            assert len(table_elements) == 1
            assert "张三" in table_elements[0].content
            assert "李四" in table_elements[0].content

    def test_parse_empty_page(self, parser):
        """测试空页面解析"""
        empty_page = MagicMock()
        empty_page.extract_text.return_value = ""
        empty_page.extract_tables.return_value = []
        empty_page.images = []

        with patch('parsers.pdf_parser.pdfplumber.open') as mock_open:
            mock_pdf = MagicMock()
            mock_pdf.pages = [empty_page]
            mock_open.return_value.__enter__.return_value = mock_pdf

            result = parser.parse(Path("/tmp/test.pdf"))

            assert len(result) == 1
            assert result[0].rawText == ""
            assert len(result[0].elements) == 0

    def test_parse_page_with_images(self, parser):
        """测试包含图片的页面"""
        image_page = MagicMock()
        image_page.extract_text.return_value = "文本内容"
        image_page.extract_tables.return_value = []
        image_page.images = [{"width": 100, "height": 100}]

        with patch('parsers.pdf_parser.pdfplumber.open') as mock_open:
            mock_pdf = MagicMock()
            mock_pdf.pages = [image_page]
            mock_open.return_value.__enter__.return_value = mock_pdf

            result = parser.parse(Path("/tmp/test.pdf"))

            assert result[0].hasImage is True

    def test_element_types(self, parser, mock_pdf_page):
        """测试元素类型检测"""
        with patch('parsers.pdf_parser.pdfplumber.open') as mock_open:
            mock_pdf = MagicMock()
            mock_pdf.pages = [mock_pdf_page]
            mock_open.return_value.__enter__.return_value = mock_pdf

            result = parser.parse(Path("/tmp/test.pdf"))

            elements = result[0].elements
            assert any(e.elementType == "heading" for e in elements)
            assert any(e.elementType == "text" for e in elements)

    def test_table_metadata(self, parser, mock_pdf_with_table):
        """测试表格元数据"""
        with patch('parsers.pdf_parser.pdfplumber.open') as mock_open:
            mock_pdf = MagicMock()
            mock_pdf.pages = [mock_pdf_with_table]
            mock_open.return_value.__enter__.return_value = mock_pdf

            result = parser.parse(Path("/tmp/test.pdf"))

            table_element = next(e for e in result[0].elements if e.elementType == "table")
            assert table_element.metadata is not None
            assert table_element.metadata["rows"] == 3
            assert table_element.metadata["cols"] == 2
            assert table_element.metadata["table_index"] == 0


class TestPDFParserStream:
    """测试流式解析"""

    def test_stream_parse(self):
        """测试流式解析生成器"""
        parser = PDFParser()

        mock_page = MagicMock()
        mock_page.extract_text.return_value = "流式测试文本"
        mock_page.extract_tables.return_value = []
        mock_page.images = []

        with patch('parsers.pdf_parser.pdfplumber.open') as mock_open:
            mock_pdf = MagicMock()
            mock_pdf.pages = [mock_page, mock_page]
            mock_open.return_value.__enter__.return_value = mock_pdf

            results = list(parser.parse_stream(Path("/tmp/test.pdf")))

            assert len(results) == 2
            assert all(r.rawText == "流式测试文本" for r in results)


class TestPDFParserEdgeCases:
    """边界情况测试"""

    def test_parse_pdf_without_pdfplumber(self):
        """测试未安装 pdfplumber 时的错误"""
        with patch('parsers.pdf_parser.PDFPLUMBER_AVAILABLE', False):
            parser = PDFParser()
            with pytest.raises(ImportError):
                parser.parse(Path("/tmp/test.pdf"))

    def test_parse_corrupted_pdf(self):
        """测试损坏的 PDF"""
        parser = PDFParser()

        with patch('parsers.pdf_parser.pdfplumber.open') as mock_open:
            mock_open.side_effect = Exception("无法打开 PDF")

            with pytest.raises(ValueError):
                parser.parse(Path("/tmp/test.pdf"))

    def test_format_table_with_none(self):
        """测试表格格式化处理 None 值"""
        parser = PDFParser()
        table = [["姓名", None], [None, "25"]]

        result = parser._format_table(table)

        assert "姓名" in result
        assert "25" in result
        assert " | " in result

    def test_format_empty_table(self):
        """测试空表格格式化"""
        parser = PDFParser()
        result = parser._format_table([])
        assert result == ""

    def test_detect_images_exception(self):
        """测试图片检测异常处理"""
        parser = PDFParser()
        page = MagicMock()
        page.images = property(lambda self: (_ for _ in ()).throw(Exception("错误")))

        result = parser._detect_images(page)
        assert result is False


class TestPDFParserRealFile:
    """使用真实 PDF 文件测试"""

    @pytest.fixture
    def sample_pdf(self, tmp_path):
        """创建测试用的 PDF 文件"""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
            from reportlab.lib.units import cm

            pdf_path = tmp_path / "test.pdf"
            c = canvas.Canvas(str(pdf_path), pagesize=A4)
            width, height = A4

            # 第一页
            c.setFont("Helvetica-Bold", 16)
            c.drawString(2*cm, height-2*cm, "Test PDF Document")

            c.setFont("Helvetica", 12)
            c.drawString(2*cm, height-4*cm, "This is the first paragraph of the test document.")
            c.drawString(2*cm, height-5*cm, "This is the second paragraph with some content.")

            c.setFont("Helvetica-Bold", 14)
            c.drawString(2*cm, height-7*cm, "Section 1: Introduction")

            c.setFont("Helvetica", 12)
            c.drawString(2*cm, height-8*cm, "This section introduces the main concepts.")

            c.showPage()

            # 第二页
            c.setFont("Helvetica-Bold", 14)
            c.drawString(2*cm, height-2*cm, "Section 2: Data")

            c.setFont("Helvetica", 12)
            c.drawString(2*cm, height-4*cm, "Name: John Doe")
            c.drawString(2*cm, height-5*cm, "Age: 30")
            c.drawString(2*cm, height-6*cm, "City: New York")

            c.showPage()
            c.save()

            return pdf_path
        except ImportError:
            pytest.skip("reportlab not installed")

    def test_real_pdf_parse(self, sample_pdf):
        """测试真实 PDF 解析"""
        parser = PDFParser()
        result = parser.parse(sample_pdf)

        assert len(result) == 2
        assert result[0].pageNumber == 1
        assert result[1].pageNumber == 2

    def test_real_pdf_content(self, sample_pdf):
        """测试真实 PDF 内容提取"""
        parser = PDFParser()
        result = parser.parse(sample_pdf)

        # 检查第一页内容
        first_page = result[0]
        assert "Test PDF Document" in first_page.rawText
        assert "first paragraph" in first_page.rawText

        # 检查第二页内容
        second_page = result[1]
        assert "Section 2" in second_page.rawText
        assert "John Doe" in second_page.rawText

    def test_real_pdf_elements(self, sample_pdf):
        """测试真实 PDF 元素提取"""
        parser = PDFParser()
        result = parser.parse(sample_pdf)

        # 检查是否有文本元素
        first_page = result[0]
        assert len(first_page.elements) > 0

        # 检查元素类型
        text_elements = [e for e in first_page.elements if e.elementType == "text"]
        assert len(text_elements) > 0

    def test_extract_text_summary(self, sample_pdf):
        """测试文本摘要提取"""
        parser = PDFParser()
        summary = parser.extract_text_summary(sample_pdf)

        assert "Test PDF Document" in summary
        assert "Section 2" in summary
        assert "【第 1 页】" in summary
        assert "【第 2 页】" in summary

    def test_extract_tables_empty(self, sample_pdf):
        """测试提取表格（无表格的 PDF）"""
        parser = PDFParser()
        tables = parser.extract_tables(sample_pdf)

        assert isinstance(tables, list)
        # 简单 PDF 可能没有表格


class TestPDFParserIntegration:
    """集成测试"""

    def test_pdf_parser_registered(self):
        """测试 PDF 解析器已注册到注册表"""
        from core.file_parser import FileParser

        file_parser = FileParser(Path(tempfile.gettempdir()))
        registry = file_parser.registry

        pdf_parser = registry.get_parser_by_ext('.pdf')
        assert pdf_parser is not None
        assert 'PDFParser' in type(pdf_parser).__name__

    def test_pdf_parser_find_by_magic(self, tmp_path):
        """测试通过魔数查找 PDF 解析器"""
        from core.file_parser import FileParser

        pdf_path = tmp_path / "test.pdf"
        # 写入 PDF 魔数
        pdf_path.write_bytes(b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n>>\nendobj\n")

        file_parser = FileParser(Path(tempfile.gettempdir()))
        with open(pdf_path, 'rb') as f:
            content = f.read(2048)

        found_parser = file_parser.registry.get_parser_by_magic(content)
        assert found_parser is not None


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
