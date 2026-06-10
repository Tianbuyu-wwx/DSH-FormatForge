"""
图表数据提取模块单元测试
"""
import pytest
import tempfile
from pathlib import Path
from datetime import datetime

from core.chart_extraction import (
    ChartData,
    TextBasedChartExtractor,
    ChartDataExtractionStrategy,
    ChartReconstructor
)
from core.models import ParsedFile, PageContent, ExtractedElement, FileType, OutputFormat


class TestChartData:
    """测试图表数据类"""

    def test_default_values(self):
        """测试默认值"""
        chart = ChartData(chart_type="bar")
        assert chart.chart_type == "bar"
        assert chart.categories == []
        assert chart.series == []
        assert chart.data_points == []

    def test_to_dict(self):
        """测试转换为字典"""
        chart = ChartData(
            chart_type="line",
            title="Test Chart",
            categories=["A", "B", "C"],
            series=[{"name": "Series1", "data": [1, 2, 3]}]
        )
        d = chart.to_dict()
        assert d["chart_type"] == "line"
        assert d["title"] == "Test Chart"
        assert len(d["categories"]) == 3


class TestTextBasedChartExtractor:
    """测试基于文本的图表提取器"""

    def setup_method(self):
        self.extractor = TextBasedChartExtractor()

    def test_can_handle_image(self):
        """测试能处理图片文件"""
        assert self.extractor.can_handle(Path("chart.png")) is True
        assert self.extractor.can_handle(Path("graph.jpg")) is True

    def test_can_handle_non_image(self):
        """测试不能处理非图片文件"""
        assert self.extractor.can_handle(Path("data.txt")) is False
        assert self.extractor.can_handle(Path("doc.pdf")) is False

    def test_detect_chart_type_pie(self):
        """测试饼图类型检测"""
        text = "This is a pie chart showing percentages"
        chart_type = self.extractor._detect_chart_type(text)
        assert chart_type == "pie"

    def test_detect_chart_type_line(self):
        """测试折线图类型检测"""
        text = "Line chart showing trends over time"
        chart_type = self.extractor._detect_chart_type(text)
        assert chart_type == "line"

    def test_detect_chart_type_bar(self):
        """测试柱状图类型检测"""
        text = "Bar chart comparing values"
        chart_type = self.extractor._detect_chart_type(text)
        assert chart_type == "bar"

    def test_extract_title(self):
        """测试标题提取"""
        lines = ["Sales Report 2024", "Some content", "More content"]
        title = self.extractor._extract_title(lines)
        assert "Sales" in title or "Report" in title

    def test_extract_axis_labels(self):
        """测试轴标签提取"""
        text = "X轴: 月份\nY轴: 销售额"
        x_label, y_label = self.extractor._extract_axis_labels(text)
        assert x_label == "月份"
        assert y_label == "销售额"

    def test_extract_data_points(self):
        """测试数据点提取"""
        lines = [
            "January: 100",
            "February: 150",
            "March: 200"
        ]
        result = self.extractor._extract_data_points(lines)

        assert result is not None
        assert len(result["categories"]) == 3
        assert result["categories"] == ["January", "February", "March"]
        assert result["series"][0]["data"] == [100.0, 150.0, 200.0]

    def test_extract_data_points_no_data(self):
        """测试无数据情况"""
        lines = ["No numbers here", "Just text"]
        result = self.extractor._extract_data_points(lines)
        assert result is None

    def test_parse_chart_text(self):
        """测试解析图表文本"""
        text = """Sales Chart
        Q1: 100
        Q2: 200
        Q3: 300"""

        chart = self.extractor._parse_chart_text(text)
        assert chart is not None
        assert chart.chart_type == "bar"  # 默认类型
        assert len(chart.categories) == 3


class TestChartDataExtractionStrategy:
    """测试图表数据提取策略"""

    def setup_method(self):
        self.strategy = ChartDataExtractionStrategy()

    def test_can_handle_image_file(self):
        """测试能处理图片文件"""
        parsed = ParsedFile(
            parseId="test",
            fileName="chart.png",
            fileSize=1024,
            pageCount=1,
            fileType=FileType.IMAGE,
            pages=[],
            createdAt=datetime.now(),
            status="completed"
        )
        score = self.strategy.can_handle(parsed)
        assert score > 0.8

    def test_can_handle_non_image(self):
        """测试不能处理非图片"""
        parsed = ParsedFile(
            parseId="test",
            fileName="doc.txt",
            fileSize=1024,
            pageCount=1,
            fileType=FileType.TXT,
            pages=[],
            createdAt=datetime.now(),
            status="completed"
        )
        score = self.strategy.can_handle(parsed)
        assert score < 0.5

    def test_convert_no_images(self):
        """测试无图片转换"""
        parsed = ParsedFile(
            parseId="test",
            fileName="doc.txt",
            fileSize=1024,
            pageCount=1,
            fileType=FileType.TXT,
            pages=[
                PageContent(
                    pageNumber=1,
                    elements=[ExtractedElement(
                        elementId="e1",
                        elementType="text",
                        content="some text"
                    )],
                    rawText="some text"
                )
            ],
            createdAt=datetime.now(),
            status="completed"
        )

        result = self.strategy.convert(parsed, OutputFormat.JSON)
        assert result["confidence"] < 0.5
        assert "未检测到" in result["content"]

    def test_format_as_markdown(self):
        """测试Markdown格式化"""
        charts = [{
            "chart_type": "bar",
            "title": "Test",
            "categories": ["A", "B"],
            "series": [{"name": "Data", "data": [10, 20]}]
        }]
        md = self.strategy._format_as_markdown(charts)
        assert "# 图表数据提取结果" in md
        assert "| 类别 |" in md

    def test_format_as_text(self):
        """测试文本格式化"""
        charts = [{
            "chart_type": "bar",
            "title": "Test",
            "categories": ["A", "B"],
            "series": [{"name": "Data", "data": [10, 20]}]
        }]
        text = self.strategy._format_as_text(charts)
        assert "图表 1" in text
        assert "bar" in text


class TestChartReconstructor:
    """测试图表重建器"""

    def setup_method(self):
        self.chart = ChartData(
            chart_type="bar",
            title="Test Chart",
            categories=["A", "B", "C"],
            series=[{"name": "Series1", "data": [10, 20, 30]}]
        )

    def test_to_json(self):
        """测试转换为JSON"""
        json_str = ChartReconstructor.to_json(self.chart)
        import json
        data = json.loads(json_str)
        assert data["chart_type"] == "bar"
        assert data["title"] == "Test Chart"

    def test_to_csv(self):
        """测试转换为CSV"""
        csv = ChartReconstructor.to_csv(self.chart)
        lines = csv.split("\n")
        assert "Category,Series1" in lines[0]
        assert "A,10" in lines[1]

    def test_to_html(self):
        """测试转换为HTML"""
        html = ChartReconstructor.to_html(self.chart)
        assert "<table" in html
        assert "Test Chart" in html
        assert "<td>A</td>" in html

    def test_to_chart_js(self):
        """测试生成Chart.js配置"""
        config = ChartReconstructor.to_chart_js(self.chart)
        import json
        data = json.loads(config)
        assert data["type"] == "bar"
        assert "data" in data
        assert "labels" in data["data"]
