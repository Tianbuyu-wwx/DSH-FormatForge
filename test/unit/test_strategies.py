"""
单元测试 - 转换策略
测试所有转换策略的 can_handle 和 convert 方法
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from core.models import (
    ParsedFile, PageContent, ExtractedElement,
    FileType, TaskStatus, ConversionType, OutputFormat
)
from core.conversion_strategies import (
    AutoDetectStrategy,
    TextExtractionStrategy,
    StructuredExtractionStrategy,
    TableExtractionStrategy,
    ImageDescriptionStrategy,
    OcrStrategy,
    StrategyRegistry
)


class TestFixtures:
    """测试数据工厂"""

    @staticmethod
    def create_parsed_file(file_type: FileType, pages_data: list = None) -> ParsedFile:
        """创建测试用的 ParsedFile"""
        pages = []
        if pages_data:
            for i, data in enumerate(pages_data, 1):
                elements = []
                for j, elem_data in enumerate(data.get("elements", [])):
                    elements.append(ExtractedElement(
                        elementId=f"elem_{i}_{j}",
                        elementType=elem_data.get("type", "text"),
                        content=elem_data.get("content", "")
                    ))
                pages.append(PageContent(
                    pageNumber=i,
                    elements=elements,
                    rawText=data.get("raw_text", ""),
                    hasImage=data.get("has_image", False),
                    hasTable=data.get("has_table", False)
                ))

        return ParsedFile(
            parseId="test_parse_123",
            fileName="test_file",
            fileSize=1024,
            pageCount=len(pages),
            fileType=file_type,
            pages=pages,
            createdAt=datetime.now(),
            status=TaskStatus.COMPLETED
        )

    @staticmethod
    def create_text_page(text: str) -> dict:
        return {
            "elements": [{"type": "text", "content": text}],
            "raw_text": text,
            "has_image": False,
            "has_table": False
        }

    @staticmethod
    def create_table_page(table_text: str) -> dict:
        return {
            "elements": [{"type": "table", "content": table_text}],
            "raw_text": table_text,
            "has_image": False,
            "has_table": True
        }

    @staticmethod
    def create_image_page() -> dict:
        return {
            "elements": [{"type": "image", "content": "image.png"}],
            "raw_text": "[image]",
            "has_image": True,
            "has_table": False
        }


class TestAutoDetectStrategy:
    """测试自动检测策略"""

    def setup_method(self):
        self.strategy = AutoDetectStrategy()

    def test_can_handle_always_high(self):
        """自动检测策略应该始终返回高置信度"""
        parsed = TestFixtures.create_parsed_file(FileType.PDF)
        score = self.strategy.can_handle(parsed)
        assert score == 0.9

    def test_convert_text_content(self):
        """测试纯文本内容的自动检测"""
        parsed = TestFixtures.create_parsed_file(
            FileType.PDF,
            [TestFixtures.create_text_page("Hello World")]
        )
        result = self.strategy.convert(parsed, OutputFormat.TEXT)

        assert "content" in result
        assert "confidence" in result
        assert "logs" in result
        assert len(result["logs"]) > 0

    def test_convert_table_content(self):
        """测试表格内容的自动检测"""
        parsed = TestFixtures.create_parsed_file(
            FileType.PDF,
            [TestFixtures.create_table_page("col1\tcol2\nval1\tval2")]
        )
        result = self.strategy.convert(parsed, OutputFormat.MARKDOWN)

        assert "content" in result
        assert result["confidence"] > 0

    def test_convert_image_content(self):
        """测试图片内容的自动检测"""
        parsed = TestFixtures.create_parsed_file(
            FileType.PDF,
            [TestFixtures.create_image_page()]
        )
        result = self.strategy.convert(parsed, OutputFormat.TEXT)

        assert "content" in result
        assert "images_found" in result.get("structured_data", {})


class TestTextExtractionStrategy:
    """测试纯文本提取策略"""

    def setup_method(self):
        self.strategy = TextExtractionStrategy()

    def test_can_handle_pdf(self):
        parsed = TestFixtures.create_parsed_file(FileType.PDF)
        score = self.strategy.can_handle(parsed)
        assert score == 0.95

    def test_can_handle_image(self):
        parsed = TestFixtures.create_parsed_file(FileType.IMAGE)
        score = self.strategy.can_handle(parsed)
        assert score == 0.3

    def test_convert_single_page(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.PDF,
            [TestFixtures.create_text_page("Hello World")]
        )
        result = self.strategy.convert(parsed, OutputFormat.TEXT)

        assert "Hello World" in result["content"]
        assert result["confidence"] == 0.95
        assert result["structured_data"]["pages"] == 1

    def test_convert_multiple_pages(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.PDF,
            [
                TestFixtures.create_text_page("Page 1 content"),
                TestFixtures.create_text_page("Page 2 content")
            ]
        )
        result = self.strategy.convert(parsed, OutputFormat.TEXT)

        assert "Page 1 content" in result["content"]
        assert "Page 2 content" in result["content"]
        assert result["structured_data"]["pages"] == 2

    def test_convert_to_json_format(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.TXT,
            [TestFixtures.create_text_page("Test content")]
        )
        result = self.strategy.convert(parsed, OutputFormat.JSON)

        assert "content" in result["content"]


class TestStructuredExtractionStrategy:
    """测试结构化提取策略"""

    def setup_method(self):
        self.strategy = StructuredExtractionStrategy()

    def test_can_handle_with_heading(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.PPT,
            [{
                "elements": [{"type": "heading", "content": "Title"}],
                "raw_text": "Title",
                "has_image": False,
                "has_table": False
            }]
        )
        score = self.strategy.can_handle(parsed)
        assert score == 0.9

    def test_can_handle_without_heading(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.PPT,
            [TestFixtures.create_text_page("Just text")]
        )
        score = self.strategy.can_handle(parsed)
        assert score == 0.6

    def test_convert_structure(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.PPT,
            [
                {
                    "elements": [
                        {"type": "heading", "content": "Chapter 1"},
                        {"type": "text", "content": "Content 1"}
                    ],
                    "raw_text": "Chapter 1\nContent 1",
                    "has_image": False,
                    "has_table": False
                }
            ]
        )
        result = self.strategy.convert(parsed, OutputFormat.JSON)

        assert "document" in result["structured_data"]
        assert result["structured_data"]["document"]["title"] == "test_file"
        assert len(result["structured_data"]["document"]["pages"]) == 1


class TestTableExtractionStrategy:
    """测试表格提取策略"""

    def setup_method(self):
        self.strategy = TableExtractionStrategy()

    def test_can_handle_with_table(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.PDF,
            [TestFixtures.create_table_page("col1\tcol2")]
        )
        score = self.strategy.can_handle(parsed)
        assert score == 0.95

    def test_can_handle_csv(self):
        parsed = TestFixtures.create_parsed_file(FileType.CSV)
        score = self.strategy.can_handle(parsed)
        assert score == 0.95

    def test_can_handle_without_table(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.PDF,
            [TestFixtures.create_text_page("No table")]
        )
        score = self.strategy.can_handle(parsed)
        assert score == 0.2

    def test_convert_tab_separated_table(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.PDF,
            [TestFixtures.create_table_page("Name\tAge\nAlice\t30\nBob\t25")]
        )
        result = self.strategy.convert(parsed, OutputFormat.MARKDOWN)

        assert "|" in result["content"]  # Markdown表格应该包含 |
        assert "tables_found" in result["structured_data"]

    def test_convert_comma_separated_table(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.CSV,
            [{
                "elements": [{"type": "table", "content": "Name, Age\nAlice, 30"}],
                "raw_text": "Name, Age\nAlice, 30",
                "has_image": False,
                "has_table": True
            }]
        )
        result = self.strategy.convert(parsed, OutputFormat.MARKDOWN)

        assert result["structured_data"]["tables_found"] == 1

    def test_convert_no_tables(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.PDF,
            [TestFixtures.create_text_page("No tables here")]
        )
        result = self.strategy.convert(parsed, OutputFormat.TEXT)

        assert "未检测到表格数据" in result["content"]
        assert result["confidence"] == 0.3


class TestImageDescriptionStrategy:
    """测试图片描述策略"""

    def setup_method(self):
        self.strategy = ImageDescriptionStrategy()

    def test_can_handle_image_file(self):
        parsed = TestFixtures.create_parsed_file(FileType.IMAGE)
        score = self.strategy.can_handle(parsed)
        assert score == 0.95

    def test_can_handle_pdf_with_images(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.PDF,
            [TestFixtures.create_image_page()]
        )
        score = self.strategy.can_handle(parsed)
        assert score == 0.85

    def test_can_handle_text_only(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.PDF,
            [TestFixtures.create_text_page("Just text")]
        )
        score = self.strategy.can_handle(parsed)
        assert score == 0.1

    def test_convert_with_images(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.PDF,
            [TestFixtures.create_image_page()]
        )
        result = self.strategy.convert(parsed, OutputFormat.TEXT)

        assert "图片" in result["content"]
        assert result["structured_data"]["images_found"] == 1

    def test_convert_no_images(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.PDF,
            [TestFixtures.create_text_page("No images")]
        )
        result = self.strategy.convert(parsed, OutputFormat.TEXT)

        assert "未检测到图片内容" in result["content"]
        assert result["confidence"] == 0.3


class TestOcrStrategy:
    """测试OCR策略"""

    def setup_method(self):
        self.strategy = OcrStrategy()

    def test_can_handle_image(self):
        parsed = TestFixtures.create_parsed_file(FileType.IMAGE)
        score = self.strategy.can_handle(parsed)
        assert score == 0.9

    def test_can_handle_pdf_with_images(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.PDF,
            [TestFixtures.create_image_page()]
        )
        score = self.strategy.can_handle(parsed)
        assert score == 0.7

    def test_convert_with_text(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.IMAGE,
            [TestFixtures.create_text_page("Recognized text")]
        )
        result = self.strategy.convert(parsed, OutputFormat.TEXT)

        assert "Recognized text" in result["content"]
        assert result["confidence"] == 0.8

    def test_convert_no_text(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.IMAGE,
            [{
                "elements": [],
                "raw_text": "",
                "has_image": True,
                "has_table": False
            }]
        )
        result = self.strategy.convert(parsed, OutputFormat.TEXT)

        assert "未识别到文字内容" in result["content"]
        assert result["confidence"] == 0.2




class TestStrategyRegistry:
    """测试策略注册表"""

    def setup_method(self):
        self.registry = StrategyRegistry()

    def test_get_strategy_exists(self):
        strategy = self.registry.get_strategy("text_extraction")
        assert strategy is not None
        assert strategy.strategy_id == "text_extraction"

    def test_get_strategy_not_exists(self):
        strategy = self.registry.get_strategy("non_existent")
        assert strategy is None

    def test_get_all_strategies(self):
        strategies = self.registry.get_all_strategies()
        assert len(strategies) == 7
        strategy_ids = [s.strategy_id for s in strategies]
        assert "auto_detect" in strategy_ids
        assert "text_extraction" in strategy_ids
        assert "table_extraction" in strategy_ids

    def test_select_best_strategy_auto(self):
        parsed = TestFixtures.create_parsed_file(
            FileType.PDF,
            [TestFixtures.create_table_page("col1\tcol2")]
        )
        strategy = self.registry.select_best_strategy(parsed, ConversionType.AUTO)
        assert strategy is not None

    def test_select_specific_strategy(self):
        parsed = TestFixtures.create_parsed_file(FileType.PDF)
        strategy = self.registry.select_best_strategy(parsed, ConversionType.TEXT)
        assert strategy.strategy_id == "text_extraction"

    def test_select_table_strategy(self):
        parsed = TestFixtures.create_parsed_file(FileType.PDF)
        strategy = self.registry.select_best_strategy(parsed, ConversionType.TABLE)
        assert strategy.strategy_id == "table_extraction"

    def test_select_image_strategy(self):
        parsed = TestFixtures.create_parsed_file(FileType.PDF)
        strategy = self.registry.select_best_strategy(parsed, ConversionType.IMAGE_DESC)
        assert strategy.strategy_id == "image_description"

    def test_select_ocr_strategy(self):
        parsed = TestFixtures.create_parsed_file(FileType.PDF)
        strategy = self.registry.select_best_strategy(parsed, ConversionType.OCR)
        assert strategy.strategy_id == "ocr"

    def test_select_encoding_strategy(self):
        parsed = TestFixtures.create_parsed_file(FileType.TXT)
        strategy = self.registry.select_best_strategy(parsed, ConversionType.ENCODING)
        assert strategy.strategy_id == "text_extraction"
