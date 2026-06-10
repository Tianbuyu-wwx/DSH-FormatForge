"""
图表数据提取模块
支持从图片中提取图表数据并重建为结构化格式
"""
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass

logger = logging.getLogger("chart_extraction")


@dataclass
class ChartData:
    """图表数据"""
    chart_type: str  # bar, line, pie, scatter, etc.
    title: Optional[str] = None
    x_label: Optional[str] = None
    y_label: Optional[str] = None
    categories: List[str] = None
    series: List[Dict[str, Any]] = None
    data_points: List[Dict[str, Any]] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.categories is None:
            self.categories = []
        if self.series is None:
            self.series = []
        if self.data_points is None:
            self.data_points = []
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chart_type": self.chart_type,
            "title": self.title,
            "x_label": self.x_label,
            "y_label": self.y_label,
            "categories": self.categories,
            "series": self.series,
            "data_points": self.data_points,
            "metadata": self.metadata
        }


class ChartExtractor(ABC):
    """图表提取器抽象基类"""

    @abstractmethod
    def can_extract(self, image_path: Path) -> bool:
        """是否能从该图片提取图表"""
        pass

    @abstractmethod
    def extract(self, image_path: Path) -> Optional[ChartData]:
        """提取图表数据"""
        pass


class TextBasedChartExtractor(ChartExtractor):
    """基于文本识别的图表提取器（使用OCR）"""

    def __init__(self, ocr_engine=None):
        self.ocr_engine = ocr_engine

    def can_handle(self, image_path: Path) -> bool:
        """检查图片是否包含图表特征（别名，用于测试兼容性）"""
        return self.can_extract(image_path)

    def can_extract(self, image_path: Path) -> bool:
        """检查图片是否包含图表特征"""
        # 这里可以添加图像分析逻辑
        # 简化实现：假设所有图片都可能包含图表
        return image_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

    def extract(self, image_path: Path) -> Optional[ChartData]:
        """使用OCR提取图表中的文本数据"""
        try:
            # 如果有OCR引擎，使用OCR
            if self.ocr_engine:
                text = self.ocr_engine.recognize(str(image_path))
            else:
                # 尝试使用pytesseract
                try:
                    import pytesseract
                    from PIL import Image
                    image = Image.open(image_path)
                    text = pytesseract.image_to_string(image, lang="chi_sim+eng")
                except ImportError:
                    logger.warning("OCR引擎不可用，无法提取图表数据")
                    return None

            return self._parse_chart_text(text)

        except Exception as e:
            logger.error(f"图表提取失败: {e}")
            return None

    def _parse_chart_text(self, text: str) -> Optional[ChartData]:
        """从OCR文本中解析图表数据"""
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if not lines:
            return None

        chart = ChartData(chart_type="unknown")

        # 尝试识别图表类型
        chart.chart_type = self._detect_chart_type(text)

        # 尝试提取标题
        chart.title = self._extract_title(lines)

        # 尝试提取轴标签
        chart.x_label, chart.y_label = self._extract_axis_labels(text)

        # 尝试提取数据
        data_result = self._extract_data_points(lines)
        if data_result:
            chart.categories = data_result.get("categories", [])
            chart.series = data_result.get("series", [])
            chart.data_points = data_result.get("data_points", [])

        return chart

    def _detect_chart_type(self, text: str) -> str:
        """检测图表类型"""
        text_lower = text.lower()
        if any(word in text_lower for word in ["pie", "饼图", "占比", "百分比"]):
            return "pie"
        elif any(word in text_lower for word in ["line", "折线", "趋势", "变化"]):
            return "line"
        elif any(word in text_lower for word in ["bar", "柱状", "条形", "column"]):
            return "bar"
        elif any(word in text_lower for word in ["scatter", "散点", "分布"]):
            return "scatter"
        return "bar"  # 默认为柱状图

    def _extract_title(self, lines: List[str]) -> Optional[str]:
        """提取图表标题"""
        # 通常标题在第一行或包含"图"、"chart"等关键词
        for line in lines[:3]:
            if any(kw in line for kw in ["图", "chart", "graph", "统计", "分析", "report"]):
                return line
        return lines[0] if lines else None

    def _extract_axis_labels(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """提取轴标签"""
        x_label = None
        y_label = None

        # 匹配常见的轴标签格式
        x_patterns = [
            r'[Xx]轴[：:]\s*(.+?)(?:\n|$)',
            r'横轴[：:]\s*(.+?)(?:\n|$)',
            r'[Xx]-axis[：:]?\s*(.+?)(?:\n|$)',
        ]
        y_patterns = [
            r'[Yy]轴[：:]\s*(.+?)(?:\n|$)',
            r'纵轴[：:]\s*(.+?)(?:\n|$)',
            r'[Yy]-axis[：:]?\s*(.+?)(?:\n|$)',
        ]

        for pattern in x_patterns:
            match = re.search(pattern, text)
            if match:
                x_label = match.group(1).strip()
                break

        for pattern in y_patterns:
            match = re.search(pattern, text)
            if match:
                y_label = match.group(1).strip()
                break

        return x_label, y_label

    def _extract_data_points(self, lines: List[str]) -> Optional[Dict[str, Any]]:
        """提取数据点"""
        # 尝试识别表格格式的数据
        # 查找包含数字的行
        data_lines = []
        for line in lines:
            if re.search(r'\d', line):
                data_lines.append(line)

        if not data_lines:
            return None

        # 尝试解析为键值对
        categories = []
        values = []

        for line in data_lines:
            # 匹配 "标签: 数值" 或 "标签 数值" 格式
            match = re.match(r'(.+?)[：:\s]+(\d+(?:\.\d+)?)', line)
            if match:
                categories.append(match.group(1).strip())
                values.append(float(match.group(2)))

        if categories and values:
            return {
                "categories": categories,
                "series": [{
                    "name": "数据",
                    "data": values
                }],
                "data_points": [
                    {"category": cat, "value": val}
                    for cat, val in zip(categories, values)
                ]
            }

        return None


class ChartDataExtractionStrategy:
    """图表数据提取策略（用于集成到转换策略系统）"""

    def __init__(self):
        self.strategy_id = "chart_extraction"
        self.strategy_name = "图表数据提取"
        self.description = "从图片中提取图表数据并转换为结构化格式"
        self.extractor = TextBasedChartExtractor()

    def can_handle(self, parsed_file) -> float:
        """检查是否能处理该文件"""
        from core.models import FileType
        if parsed_file.fileType == FileType.IMAGE:
            return 0.85
        # 检查是否包含图表相关的图片
        for page in parsed_file.pages:
            for elem in page.elements:
                if elem.elementType == "image" and any(
                    kw in elem.content.lower()
                    for kw in ["chart", "graph", "图", "统计", "plot"]
                ):
                    return 0.8
        return 0.2

    def convert(
        self,
        parsed_file,
        output_format,
        ai_caps=None,
        custom_prompt=None
    ) -> Dict[str, Any]:
        """执行图表数据提取"""
        from core.models import ProcessingLog
        from datetime import datetime

        logs = [ProcessingLog(
            timestamp=datetime.now(),
            level="info",
            message="开始图表数据提取",
            step="chart_extract"
        )]

        charts = []

        # 提取图片元素
        for page in parsed_file.pages:
            for elem in page.elements:
                if elem.elementType == "image":
                    image_path = elem.metadata.get("path") if elem.metadata else None
                    if image_path:
                        chart_data = self.extractor.extract(Path(image_path))
                        if chart_data:
                            charts.append(chart_data.to_dict())

        if not charts:
            logs.append(ProcessingLog(
                timestamp=datetime.now(),
                level="warning",
                message="未检测到图表数据",
                step="chart_extract"
            ))
            return {
                "content": "未检测到图表数据",
                "structured_data": {"charts_found": 0},
                "confidence": 0.3,
                "logs": logs
            }

        # 格式化输出
        if output_format.value == "json":
            content = json.dumps({"charts": charts}, ensure_ascii=False, indent=2)
        elif output_format.value == "markdown":
            content = self._format_as_markdown(charts)
        else:
            content = self._format_as_text(charts)

        logs.append(ProcessingLog(
            timestamp=datetime.now(),
            level="info",
            message=f"提取完成，共 {len(charts)} 个图表",
            step="chart_extract"
        ))

        return {
            "content": content,
            "structured_data": {"charts_found": len(charts), "charts": charts},
            "confidence": 0.85,
            "logs": logs
        }

    def _format_as_markdown(self, charts: List[Dict]) -> str:
        """格式化为Markdown"""
        parts = ["# 图表数据提取结果\n"]
        for i, chart in enumerate(charts, 1):
            parts.append(f"## 图表 {i}: {chart.get('title', '未命名')}\n")
            parts.append(f"- 类型: {chart['chart_type']}")
            parts.append(f"- X轴: {chart.get('x_label', 'N/A')}")
            parts.append(f"- Y轴: {chart.get('y_label', 'N/A')}")
            parts.append("")

            if chart.get("categories") and chart.get("series"):
                parts.append("| 类别 | " + " | ".join(s["name"] for s in chart["series"]) + " |")
                parts.append("|" + "---|" * (len(chart["series"]) + 1))
                for j, cat in enumerate(chart["categories"]):
                    row = f"| {cat} |"
                    for series in chart["series"]:
                        val = series["data"][j] if j < len(series["data"]) else "N/A"
                        row += f" {val} |"
                    parts.append(row)
                parts.append("")

        return "\n".join(parts)

    def _format_as_text(self, charts: List[Dict]) -> str:
        """格式化为纯文本"""
        parts = ["图表数据提取结果:\n"]
        for i, chart in enumerate(charts, 1):
            parts.append(f"图表 {i}: {chart.get('title', '未命名')}")
            parts.append(f"  类型: {chart['chart_type']}")
            if chart.get("categories"):
                parts.append(f"  类别: {', '.join(chart['categories'])}")
            if chart.get("series"):
                for series in chart["series"]:
                    parts.append(f"  {series['name']}: {series['data']}")
            parts.append("")
        return "\n".join(parts)


class ChartReconstructor:
    """图表重建器 - 将提取的数据重建为可渲染格式"""

    @staticmethod
    def to_json(chart: ChartData) -> str:
        """转换为JSON格式"""
        return json.dumps(chart.to_dict(), ensure_ascii=False, indent=2)

    @staticmethod
    def to_csv(chart: ChartData) -> str:
        """转换为CSV格式"""
        lines = []
        if chart.categories and chart.series:
            header = "Category," + ",".join(s["name"] for s in chart.series)
            lines.append(header)
            for i, cat in enumerate(chart.categories):
                row = cat
                for series in chart.series:
                    val = series["data"][i] if i < len(series["data"]) else ""
                    row += f",{val}"
                lines.append(row)
        return "\n".join(lines)

    @staticmethod
    def to_html(chart: ChartData) -> str:
        """转换为HTML表格"""
        html = [f"<h3>{chart.title or 'Chart'}</h3>"]
        html.append("<table border='1'>")

        if chart.categories and chart.series:
            html.append("<tr><th>Category</th>" +
                       "".join(f"<th>{s['name']}</th>" for s in chart.series) +
                       "</tr>")
            for i, cat in enumerate(chart.categories):
                row = f"<tr><td>{cat}</td>"
                for series in chart.series:
                    val = series["data"][i] if i < len(series["data"]) else ""
                    row += f"<td>{val}</td>"
                row += "</tr>"
                html.append(row)

        html.append("</table>")
        return "\n".join(html)

    @staticmethod
    def to_chart_js(chart: ChartData) -> str:
        """生成Chart.js配置"""
        config = {
            "type": chart.chart_type,
            "data": {
                "labels": chart.categories,
                "datasets": [
                    {
                        "label": s.get("name", "Data"),
                        "data": s.get("data", [])
                    }
                    for s in chart.series
                ]
            },
            "options": {
                "responsive": True,
                "plugins": {
                    "title": {
                        "display": bool(chart.title),
                        "text": chart.title
                    }
                }
            }
        }
        return json.dumps(config, ensure_ascii=False, indent=2)
