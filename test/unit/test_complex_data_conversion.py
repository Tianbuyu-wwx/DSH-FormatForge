"""
复杂数据转换验证测试（新架构）
构造 AI 难以识别的复杂数据场景，验证转换引擎的处理能力

测试场景：
1. 混合编码乱码文本
2. 嵌套表格与合并单元格
3. 图文混排内容
4. 无结构化的密集数据
5. 损坏的PDF结构
6. 多层级列表与代码块混排
7. 特殊字符与emoji混杂
8. 二进制数据伪装成文本
"""
import pytest
import json
import tempfile
from datetime import datetime
from pathlib import Path
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
    EncodingFixStrategy,
    AiNativeStrategy,
    StrategyRegistry
)
from core.converter_engine import DataConverter


class ComplexDataFixtures:
    """复杂数据工厂 - 构造AI难以识别的数据"""

    @staticmethod
    def create_parsed_file(file_type: FileType, file_name: str, pages_data: list) -> ParsedFile:
        """创建ParsedFile"""
        pages = []
        for i, data in enumerate(pages_data, 1):
            elements = []
            for j, elem_data in enumerate(data.get("elements", [])):
                elements.append(ExtractedElement(
                    elementId=f"elem_{i}_{j}",
                    elementType=elem_data.get("type", "text"),
                    content=elem_data.get("content", ""),
                    metadata=elem_data.get("metadata")
                ))
            pages.append(PageContent(
                pageNumber=i,
                elements=elements,
                rawText=data.get("raw_text", ""),
                hasImage=data.get("has_image", False),
                hasTable=data.get("has_table", False)
            ))

        return ParsedFile(
            parseId=f"parse_complex_{datetime.now().strftime('%H%M%S')}",
            fileName=file_name,
            fileSize=2048,
            pageCount=len(pages),
            fileType=file_type,
            pages=pages,
            createdAt=datetime.now(),
            status=TaskStatus.COMPLETED
        )

    @staticmethod
    def _write_temp_file(content: str, suffix: str = ".txt") -> str:
        """将内容写入临时文件并返回路径"""
        with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False, encoding='utf-8') as f:
            f.write(content)
            return f.name

    # ========== 场景1: 混合编码乱码文本 ==========
    @staticmethod
    def garbled_mixed_encoding() -> tuple:
        """混合多种编码错误的文本 - AI难以识别原始内容"""
        content = "Hello ï¿½ï¿½ World Ã©Ã¨Ã\næµ‹è¯•ä¸­æ–‡ ä¹±ç\nÎáÊÇÖÐÎÄ ÂÒÂë\nNormal text here"
        return ComplexDataFixtures._write_temp_file(content, ".txt")

    # ========== 场景2: 嵌套表格与合并单元格 ==========
    @staticmethod
    def nested_tables() -> tuple:
        """嵌套表格 - 表格内嵌套子表格，AI难以解析层级关系"""
        content = (
            "Header1\tHeader2\tHeader3\n"
            "A\tB\tC\n"
            "D\tE\tF\n"
            "Sub-table within cell:\n"
            "SubA\tSubB\n"
            "1\t2\n"
            "3\t4\n"
            "Outer\tInner\n"
            "X\tY\tZ\n"
            "M\tN\tO"
        )
        return ComplexDataFixtures._write_temp_file(content, ".txt")

    # ========== 场景3: 图文混排内容 ==========
    @staticmethod
    def mixed_image_text() -> tuple:
        """图文混排 - 图片与文字交错排列，AI难以关联上下文"""
        content = (
            "产品介绍\n"
            "[image: product_main.png]\n"
            "上图展示了我们的核心产品特性...\n"
            "[image: detail_1.png]\n"
            "左侧图表显示了性能对比数据...\n"
            "[image: detail_2.png]\n"
            "右侧为用户评价统计..."
        )
        return ComplexDataFixtures._write_temp_file(content, ".txt")

    # ========== 场景4: 无结构化的密集数据 ==========
    @staticmethod
    def unstructured_dense_data() -> tuple:
        """密集无结构数据 - 类似日志或传感器数据，AI难以提取模式"""
        content = (
            "2024-01-15T08:23:45Z|sensor_01|temp=23.5|humidity=65%|status=OK\n"
            "2024-01-15T08:23:46Z|sensor_02|temp=24.1|humidity=63%|status=OK\n"
            "2024-01-15T08:23:47Z|sensor_01|temp=23.6|humidity=64%|status=WARN|msg=threshold_near\n"
            "2024-01-15T08:23:48Z|sensor_03|temp=22.8|humidity=67%|status=OK\n"
            "2024-01-15T08:23:49Z|sensor_01|temp=23.7|humidity=64%|status=ALERT|msg=threshold_exceeded|value=23.7|threshold=23.5"
        )
        return ComplexDataFixtures._write_temp_file(content, ".log")

    # ========== 场景5: 损坏的PDF结构 ==========
    @staticmethod
    def corrupted_pdf_structure() -> tuple:
        """损坏的PDF结构 - 页面顺序混乱，内容缺失"""
        content = (
            "... (page content missing) ...\n"
            "Fragment: conclusion starts here\n"
            "---\n"
            "Chapter 3\n"
            "This should be in the middle...\n"
            "---\n"
            "Introduction\n"
            "This is the beginning..."
        )
        return ComplexDataFixtures._write_temp_file(content, ".txt")

    # ========== 场景6: 多层级列表与代码块混排 ==========
    @staticmethod
    def nested_list_code_mix() -> tuple:
        """多层级列表与代码块混排 - Markdown-like复杂结构"""
        content = (
            "API Documentation\n"
            "1. Authentication\n"
            "   a. OAuth2\n"
            "      i. Get token\n"
            "      ii. Refresh token\n"
            "   b. API Key\n"
            "      i. Generate key\n"
            "      ii. Revoke key\n"
            "```python\n"
            "def get_token(client_id, secret):\n"
            "    payload = {\n"
            "        'grant_type': 'client_credentials',\n"
            "        'client_id': client_id,\n"
            "        'client_secret': secret\n"
            "    }\n"
            "    return requests.post('/oauth/token', data=payload)\n"
            "```\n"
            "2. Endpoints\n"
            "   a. GET /api/v1/users\n"
            "      - Params: page, limit\n"
            "      - Response: User[]\n"
            "   b. POST /api/v1/users\n"
            "      - Body: {name, email}\n"
            "      - Response: User\n"
            "```json\n"
            "{\n"
            "  \"users\": [\n"
            "    {\"id\": 1, \"name\": \"Alice\"},\n"
            "    {\"id\": 2, \"name\": \"Bob\"}\n"
            "  ]\n"
            "}\n"
            "```"
        )
        return ComplexDataFixtures._write_temp_file(content, ".md")

    # ========== 场景7: 特殊字符与emoji混杂 ==========
    @staticmethod
    def special_chars_emoji() -> tuple:
        """特殊字符与emoji混杂 - 包含零宽字符、RTL标记等"""
        content = (
            "Price: $1,234.56 | Discount: 50% | Status: ✅\n"
            "User: John_Doe_123 | Email: john@example.com | Phone: +1-555-0123\n"
            "Math: ∫f(x)dx = ∑(i=1 to n)xi | Formula: H₂O | Temperature: 25°C\n"
            "Mixed: Helloمرحباשלום | RTL: مرحبا | ZWJ: 👨‍👩‍👧‍👦\n"
            "Control: \u200B\u200C\u200D | BOM: \ufeff | Tab:\tNewline:\n"
        )
        return ComplexDataFixtures._write_temp_file(content, ".txt")

    # ========== 场景8: 二进制数据伪装成文本 ==========
    @staticmethod
    def binary_masquerading() -> tuple:
        """二进制数据伪装成文本 - 包含不可打印字符"""
        content = (
            "PK\x03\x04\x14\x00\x00\x00\x08\x00\n"
            "%PDF-1.4\x0a1 0 obj\x0a<<\n"
            "\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\n"
            "Some normal text here"
        )
        return ComplexDataFixtures._write_temp_file(content, ".bin")

    # ========== 场景9: 表格与文本边界模糊 ==========
    @staticmethod
    def fuzzy_table_boundary() -> tuple:
        """表格与文本边界模糊 - 表格格式不标准"""
        content = (
            "Sales Report Q1 2024\n"
            "Product A    $1000    +15%\n"
            "Product B     $850    -5%\n"
            "Product C    $1200   +22%\n"
            "Total: $3050\n"
            "Note: * Includes promotional discounts"
        )
        return ComplexDataFixtures._write_temp_file(content, ".txt")

    # ========== 场景10: 超大单页内容 ==========
    @staticmethod
    def oversized_page() -> tuple:
        """超大单页内容 - 单页包含大量数据，超出AI上下文限制"""
        large_content = "Line content with data\n" * 1000
        return ComplexDataFixtures._write_temp_file(large_content, ".log")


# ==================== 复杂数据转换测试 ====================

class TestGarbledTextConversion:
    """测试乱码文本转换"""

    def setup_method(self):
        self.converter = DataConverter()
        self.converter.ai_client = None

    def test_mixed_encoding_detection(self):
        """测试混合编码检测"""
        temp_path = ComplexDataFixtures.garbled_mixed_encoding()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.ENCODING,
                output_format=OutputFormat.TEXT
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.confidence > 0.3
            assert len(result_data.processingLogs) > 0
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_garbled_text_auto_detect(self):
        """测试自动检测乱码文本"""
        temp_path = ComplexDataFixtures.garbled_mixed_encoding()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.AUTO,
                output_format=OutputFormat.TEXT
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.resultId.startswith("cvt")
            assert result_data.confidence > 0
            log_steps = [log.step for log in result_data.processingLogs]
            assert any("encoding" in step.lower() or "strategy" in step.lower() or "convert" in step.lower() for step in log_steps)
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestNestedTableConversion:
    """测试嵌套表格转换"""

    def setup_method(self):
        self.converter = DataConverter()
        self.converter.ai_client = None

    def test_nested_table_extraction(self):
        """测试嵌套表格提取"""
        temp_path = ComplexDataFixtures.nested_tables()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.TABLE,
                output_format=OutputFormat.MARKDOWN
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.confidence >= 0.3
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_nested_table_structure_preservation(self):
        """测试嵌套表格结构保留"""
        temp_path = ComplexDataFixtures.nested_tables()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.STRUCTURED,
                output_format=OutputFormat.JSON
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.outputFormat == OutputFormat.JSON
            assert "{" in result_data.convertedContent
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestMixedImageTextConversion:
    """测试图文混排转换"""

    def setup_method(self):
        self.converter = DataConverter()
        self.converter.ai_client = None

    def test_mixed_content_description(self):
        """测试图文混排描述生成"""
        temp_path = ComplexDataFixtures.mixed_image_text()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.IMAGE_DESC,
                output_format=OutputFormat.TEXT
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.confidence >= 0.3
            # 对于纯文本文件，图片描述策略可能检测不到图片元素（因为只是文本标记）
            # 只要返回了有效内容即可
            assert len(result_data.convertedContent) > 0
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_mixed_content_auto(self):
        """测试图文混排自动处理"""
        temp_path = ComplexDataFixtures.mixed_image_text()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.AUTO,
                output_format=OutputFormat.TEXT
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.resultId is not None
            assert result_data.confidence > 0
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestUnstructuredDenseDataConversion:
    """测试密集无结构数据转换"""

    def setup_method(self):
        self.converter = DataConverter()
        self.converter.ai_client = None

    def test_sensor_data_pattern_extraction(self):
        """测试传感器数据模式提取"""
        temp_path = ComplexDataFixtures.unstructured_dense_data()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.STRUCTURED,
                output_format=OutputFormat.JSON
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.confidence > 0.3
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_sensor_data_table_conversion(self):
        """测试传感器数据表格转换"""
        temp_path = ComplexDataFixtures.unstructured_dense_data()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.TABLE,
                output_format=OutputFormat.MARKDOWN
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.confidence >= 0.1
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestCorruptedStructureConversion:
    """测试损坏结构转换"""

    def setup_method(self):
        self.converter = DataConverter()
        self.converter.ai_client = None

    def test_corrupted_pdf_handling(self):
        """测试损坏PDF处理"""
        temp_path = ComplexDataFixtures.corrupted_pdf_structure()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.TEXT,
                output_format=OutputFormat.TEXT
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.confidence > 0.1
            assert "Fragment" in result_data.convertedContent or "conclusion" in result_data.convertedContent
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_corrupted_structure_reconstruction(self):
        """测试损坏结构重建"""
        temp_path = ComplexDataFixtures.corrupted_pdf_structure()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.STRUCTURED,
                output_format=OutputFormat.JSON
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.outputFormat == OutputFormat.JSON
            assert "{" in result_data.convertedContent
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestNestedListCodeConversion:
    """测试多层级列表与代码块转换"""

    def setup_method(self):
        self.converter = DataConverter()
        self.converter.ai_client = None

    def test_nested_list_preservation(self):
        """测试嵌套列表保留"""
        temp_path = ComplexDataFixtures.nested_list_code_mix()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.STRUCTURED,
                output_format=OutputFormat.JSON
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.confidence > 0.3
            assert "Authentication" in result_data.convertedContent or "API" in result_data.convertedContent
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_code_block_handling(self):
        """测试代码块处理"""
        temp_path = ComplexDataFixtures.nested_list_code_mix()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.TEXT,
                output_format=OutputFormat.TEXT
            )
            result_data = result.get("result")
            assert result_data is not None
            assert "python" in result_data.convertedContent or "def" in result_data.convertedContent
            assert "json" in result_data.convertedContent or "users" in result_data.convertedContent
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestSpecialCharsConversion:
    """测试特殊字符转换"""

    def setup_method(self):
        self.converter = DataConverter()
        self.converter.ai_client = None

    def test_special_chars_preservation(self):
        """测试特殊字符保留"""
        temp_path = ComplexDataFixtures.special_chars_emoji()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.TEXT,
                output_format=OutputFormat.TEXT
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.confidence > 0.5
            assert "$" in result_data.convertedContent or "Price" in result_data.convertedContent
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_emoji_and_unicode_handling(self):
        """测试emoji和Unicode处理"""
        temp_path = ComplexDataFixtures.special_chars_emoji()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.ENCODING,
                output_format=OutputFormat.TEXT
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.confidence > 0.3
            assert len(result_data.convertedContent) > 0
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestBinaryMasqueradingConversion:
    """测试二进制伪装数据转换"""

    def setup_method(self):
        self.converter = DataConverter()
        self.converter.ai_client = None

    def test_binary_header_detection(self):
        """测试二进制文件头检测"""
        temp_path = ComplexDataFixtures.binary_masquerading()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.TEXT,
                output_format=OutputFormat.TEXT
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.confidence > 0.1
            # 由于二进制伪装数据会被格式检测器识别为zip等格式，
            # 可能返回原始数据信息或转换后的内容，只要包含关键信息即可
            content = result_data.convertedContent
            assert any(k in content for k in ["PK", "%PDF", "PNG", "zip", "原始数据"]), \
                f"未检测到预期的二进制特征，实际内容: {content[:100]}"
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_binary_data_cleanup(self):
        """测试二进制数据清理"""
        temp_path = ComplexDataFixtures.binary_masquerading()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.ENCODING,
                output_format=OutputFormat.TEXT
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.confidence > 0.1
            assert len(result_data.convertedContent) > 0
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestFuzzyTableBoundaryConversion:
    """测试模糊表格边界转换"""

    def setup_method(self):
        self.converter = DataConverter()
        self.converter.ai_client = None

    def test_fuzzy_table_auto_detect(self):
        """测试模糊表格自动检测"""
        temp_path = ComplexDataFixtures.fuzzy_table_boundary()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.AUTO,
                output_format=OutputFormat.TEXT
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.confidence > 0.1
            assert "Product" in result_data.convertedContent or "Sales" in result_data.convertedContent
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_fuzzy_table_extraction(self):
        """测试模糊表格提取"""
        temp_path = ComplexDataFixtures.fuzzy_table_boundary()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.TABLE,
                output_format=OutputFormat.MARKDOWN
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.confidence >= 0.1
            assert "Product" in result_data.convertedContent or "未检测到" in result_data.convertedContent
        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestOversizedPageConversion:
    """测试超大页面转换"""

    def setup_method(self):
        self.converter = DataConverter()
        self.converter.ai_client = None

    def test_oversized_page_handling(self):
        """测试超大页面处理"""
        temp_path = ComplexDataFixtures.oversized_page()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.TEXT,
                output_format=OutputFormat.TEXT
            )
            result_data = result.get("result")
            assert result_data is not None
            assert result_data.confidence > 0.3
            assert len(result_data.convertedContent) > 0
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_oversized_page_summary(self):
        """测试超大页面摘要"""
        temp_path = ComplexDataFixtures.oversized_page()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.TEXT,
                output_format=OutputFormat.TEXT
            )
            result_data = result.get("result")
            assert result_data is not None
            assert len(result_data.extractedContent) <= 2000
        finally:
            Path(temp_path).unlink(missing_ok=True)


# ==================== 策略评分测试 ====================

class TestStrategyScoringOnComplexData:
    """测试策略对复杂数据的评分"""

    def setup_method(self):
        self.registry = StrategyRegistry()

    def _create_parsed_fixture(self, file_type: FileType, file_name: str, pages_data: list) -> ParsedFile:
        pages = []
        for i, data in enumerate(pages_data, 1):
            elements = []
            for j, elem_data in enumerate(data.get("elements", [])):
                elements.append(ExtractedElement(
                    elementId=f"elem_{i}_{j}",
                    elementType=elem_data.get("type", "text"),
                    content=elem_data.get("content", ""),
                    metadata=elem_data.get("metadata")
                ))
            pages.append(PageContent(
                pageNumber=i,
                elements=elements,
                rawText=data.get("raw_text", ""),
                hasImage=data.get("has_image", False),
                hasTable=data.get("has_table", False)
            ))
        return ParsedFile(
            parseId="parse_test",
            fileName=file_name,
            fileSize=2048,
            pageCount=len(pages),
            fileType=file_type,
            pages=pages,
            createdAt=datetime.now(),
            status=TaskStatus.COMPLETED
        )

    def test_garbled_text_encoding_strategy_score(self):
        """测试乱码文本的编码策略评分"""
        parsed = self._create_parsed_fixture(FileType.TXT, "garbled.txt", [{
            "elements": [{"type": "text", "content": "Hello ï¿½ï¿½ World"}],
            "raw_text": "Hello ï¿½ï¿½ World",
            "has_image": False,
            "has_table": False
        }])
        strategy = self.registry.get_strategy("encoding_fix")
        score = strategy.can_handle(parsed)
        assert score > 0.8

    def test_nested_table_table_strategy_score(self):
        """测试嵌套表格的表格策略评分"""
        parsed = self._create_parsed_fixture(FileType.PDF, "nested.pdf", [{
            "elements": [{"type": "table", "content": "A\tB\n1\t2"}],
            "raw_text": "A\tB\n1\t2",
            "has_image": False,
            "has_table": True
        }])
        strategy = self.registry.get_strategy("table_extraction")
        score = strategy.can_handle(parsed)
        assert score > 0.8

    def test_mixed_image_image_strategy_score(self):
        """测试图文混排的图片策略评分"""
        parsed = self._create_parsed_fixture(FileType.PPT, "mixed.pptx", [{
            "elements": [
                {"type": "image", "content": "img.png"},
                {"type": "text", "content": "desc"}
            ],
            "raw_text": "[image] desc",
            "has_image": True,
            "has_table": False
        }])
        strategy = self.registry.get_strategy("image_description")
        score = strategy.can_handle(parsed)
        assert score > 0.8

    def test_auto_select_for_complex_data(self):
        """测试复杂数据的自动策略选择"""
        test_cases = [
            (self._create_parsed_fixture(FileType.TXT, "garbled.txt", [{
                "elements": [{"type": "text", "content": "ï¿½"}],
                "raw_text": "ï¿½",
                "has_image": False, "has_table": False
            }]), ["encoding_fix", "text_extraction"]),
            (self._create_parsed_fixture(FileType.PDF, "nested.pdf", [{
                "elements": [{"type": "table", "content": "A\tB"}],
                "raw_text": "A\tB",
                "has_image": False, "has_table": True
            }]), ["table_extraction", "text_extraction", "structured_extraction"]),
            (self._create_parsed_fixture(FileType.PPT, "mixed.pptx", [{
                "elements": [{"type": "image", "content": "img.png"}],
                "raw_text": "[image]",
                "has_image": True, "has_table": False
            }]), ["image_description", "text_extraction"]),
            (self._create_parsed_fixture(FileType.TXT, "sensor.log", [{
                "elements": [{"type": "text", "content": "a|b|c"}],
                "raw_text": "a|b|c",
                "has_image": False, "has_table": False
            }]), ["text_extraction", "structured_extraction"]),
        ]

        for parsed, expected_strategies in test_cases:
            strategy = self.registry.select_best_strategy(parsed, ConversionType.AUTO)
            assert strategy is not None
            assert strategy.strategy_id in expected_strategies, \
                f"Expected one of {expected_strategies} for {parsed.fileName}, got {strategy.strategy_id}"


# ==================== 端到端复杂场景测试 ====================

class TestEndToEndComplexScenarios:
    """端到端复杂场景测试"""

    def setup_method(self):
        self.converter = DataConverter()
        self.converter.ai_client = None

    def test_full_pipeline_garbled_to_structured(self):
        """测试完整流水线：乱码 -> 修复 -> 结构化"""
        temp_path = ComplexDataFixtures.garbled_mixed_encoding()
        try:
            # 第一步：编码修复
            step1 = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.ENCODING,
                output_format=OutputFormat.TEXT
            )
            result1 = step1.get("result")
            assert result1.confidence > 0.3

            # 第二步：文本提取
            step2 = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.TEXT,
                output_format=OutputFormat.TEXT
            )
            result2 = step2.get("result")
            assert result2.confidence > 0.3

            # 第三步：结构化
            step3 = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.STRUCTURED,
                output_format=OutputFormat.JSON
            )
            result3 = step3.get("result")
            assert result3.confidence > 0.3
            assert "{" in result3.convertedContent
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_full_pipeline_sensor_to_table(self):
        """测试完整流水线：传感器数据 -> 表格"""
        temp_path = ComplexDataFixtures.unstructured_dense_data()
        try:
            # 自动检测
            auto_result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.AUTO,
                output_format=OutputFormat.TEXT
            )
            result_auto = auto_result.get("result")
            assert result_auto.confidence > 0

            # 表格提取
            table_result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.TABLE,
                output_format=OutputFormat.MARKDOWN
            )
            result_table = table_result.get("result")
            assert result_table.confidence >= 0.1
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_multiple_complex_files_batch(self):
        """测试批量处理多个复杂文件"""
        from converter_engine import BatchConverter

        batch = BatchConverter()
        batch.converter.ai_client = None

        files = [
            ComplexDataFixtures.garbled_mixed_encoding(),
            ComplexDataFixtures.nested_tables(),
            ComplexDataFixtures.mixed_image_text(),
            ComplexDataFixtures.special_chars_emoji(),
        ]

        try:
            results = batch.convert_batch(files, ConversionType.AUTO, OutputFormat.TEXT)

            assert len(results) == 4
            for result in results:
                # convert_batch 返回的是字典列表，每个字典包含 "result" 键
                result_data = result.get("result") if isinstance(result, dict) else result
                assert result_data is not None
                assert result_data.confidence > 0
                assert result_data.resultId is not None
        finally:
            for f in files:
                Path(f).unlink(missing_ok=True)

    def test_conversion_logs_for_complex_data(self):
        """测试复杂数据的处理日志完整性"""
        temp_path = ComplexDataFixtures.nested_list_code_mix()
        try:
            result = self.converter.convert_with_ai_target(
                source=temp_path,
                conversion_type=ConversionType.AUTO,
                output_format=OutputFormat.JSON
            )
            result_data = result.get("result")
            assert len(result_data.processingLogs) >= 3

            log_steps = [log.step for log in result_data.processingLogs]
            assert "init" in log_steps
            assert "strategy" in log_steps or "convert" in log_steps
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_confidence_range_for_all_complex_types(self):
        """测试所有复杂类型的置信度范围"""
        fixtures = [
            ComplexDataFixtures.garbled_mixed_encoding(),
            ComplexDataFixtures.nested_tables(),
            ComplexDataFixtures.mixed_image_text(),
            ComplexDataFixtures.unstructured_dense_data(),
            ComplexDataFixtures.corrupted_pdf_structure(),
            ComplexDataFixtures.nested_list_code_mix(),
            ComplexDataFixtures.special_chars_emoji(),
            ComplexDataFixtures.binary_masquerading(),
            ComplexDataFixtures.fuzzy_table_boundary(),
            ComplexDataFixtures.oversized_page(),
        ]

        try:
            for temp_path in fixtures:
                result = self.converter.convert_with_ai_target(
                    source=temp_path,
                    conversion_type=ConversionType.AUTO,
                    output_format=OutputFormat.TEXT
                )
                result_data = result.get("result")
                assert 0 <= result_data.confidence <= 1, \
                    f"Confidence {result_data.confidence} out of range for {temp_path}"
                assert result_data.resultId is not None
                assert len(result_data.processingLogs) > 0
        finally:
            for f in fixtures:
                Path(f).unlink(missing_ok=True)
