"""
SVG 解析器单元测试
使用真实的 SVG 字符串构造测试文件
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.svg_parser import SVGParser


class TestSVGParserBasic:
    """基础测试"""

    def test_supported_extensions(self):
        parser = SVGParser()
        assert ".svg" in parser.supported_extensions
        assert ".txt" not in parser.supported_extensions

    def test_supported_magic(self):
        parser = SVGParser()
        assert b"<svg" in parser.supported_magic

    def test_can_parse_svg(self):
        parser = SVGParser()
        assert parser.can_parse(Path("/tmp/test.svg")) == 0.9
        assert parser.can_parse(Path("/tmp/icon.svg")) == 0.9

    def test_can_parse_non_svg(self):
        parser = SVGParser()
        assert parser.can_parse(Path("/tmp/test.txt")) == 0.0
        assert parser.can_parse(Path("/tmp/test.png")) == 0.0


class TestSVGParsing:
    """SVG 解析功能测试"""

    @pytest.fixture
    def parser(self):
        return SVGParser()

    def _create_svg(self, content: str, tmp_path: Path) -> Path:
        path = tmp_path / "test.svg"
        path.write_text(content, encoding="utf-8")
        return path

    def test_parse_text_elements(self, parser, tmp_path):
        """解析 SVG 中的文本元素"""
        svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 100" width="200" height="100">
  <text x="10" y="20">Hello SVG</text>
  <text x="10" y="40">Second Line</text>
</svg>"""
        path = self._create_svg(svg, tmp_path)
        result = parser.parse(path)
        texts = [e for e in result[0].elements if e.elementType == "text"]
        combined = " ".join(t.content for t in texts)
        assert "Hello SVG" in combined
        assert "Second Line" in combined

    def test_parse_metadata(self, parser, tmp_path):
        """解析 SVG 元数据"""
        svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600" width="800" height="600" version="1.1">
  <title>测试图标</title>
  <desc>这是一个用于测试的 SVG 图标</desc>
</svg>"""
        path = self._create_svg(svg, tmp_path)
        result = parser.parse(path)
        headers = [e for e in result[0].elements if e.elementType == "header"]
        header_map = {h.metadata["field"]: h.metadata["value"] for h in headers}
        assert header_map.get("viewBox") == "0 0 800 600"
        assert header_map.get("width") == "800"
        assert header_map.get("height") == "600"

    def test_parse_title_and_desc(self, parser, tmp_path):
        """解析 SVG 标题和描述"""
        svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg">
  <title>我的图标</title>
  <desc>一个蓝色圆形图标</desc>
</svg>"""
        path = self._create_svg(svg, tmp_path)
        result = parser.parse(path)
        headings = [e for e in result[0].elements if e.elementType == "heading"]
        # 标题可能出现在 text 或 heading 中
        combined = " ".join(e.content for e in result[0].elements)
        assert "我的图标" in combined
        assert "蓝色圆形图标" in combined

    def test_parse_tspan(self, parser, tmp_path):
        """解析 tspan 多行文本"""
        svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg">
  <text x="10" y="20">
    <tspan x="10" dy="0">第一行</tspan>
    <tspan x="10" dy="20">第二行</tspan>
  </text>
</svg>"""
        path = self._create_svg(svg, tmp_path)
        result = parser.parse(path)
        texts = [e for e in result[0].elements if e.elementType == "text"]
        combined = " ".join(t.content for t in texts)
        assert "第一行" in combined
        assert "第二行" in combined

    def test_parse_shapes(self, parser, tmp_path):
        """解析图形元素统计"""
        svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg">
  <rect x="0" y="0" width="100" height="50"/>
  <circle cx="50" cy="50" r="20"/>
  <rect x="10" y="10" width="30" height="30"/>
  <ellipse cx="10" cy="10" rx="5" ry="3"/>
  <path d="M10 10 L20 20"/>
</svg>"""
        path = self._create_svg(svg, tmp_path)
        result = parser.parse(path)
        texts = [e for e in result[0].elements if e.elementType == "text"]
        combined = " ".join(t.content for t in texts)
        assert "矩形 × 2" in combined
        assert "圆形 × 1" in combined
        assert "椭圆 × 1" in combined
        assert "路径 × 1" in combined

    def test_parse_with_defs(self, parser, tmp_path):
        """defs 中的元素不应被统计"""
        svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg">
  <defs>
    <rect id="box" width="100" height="50"/>
    <circle id="dot" cx="0" cy="0" r="5"/>
  </defs>
  <use href="#box" x="10" y="10"/>
  <use href="#dot" x="50" y="50"/>
</svg>"""
        path = self._create_svg(svg, tmp_path)
        result = parser.parse(path)
        texts = [e for e in result[0].elements if e.elementType == "text"]
        combined = " ".join(t.content for t in texts)
        # defs 中的 rect/circle 不应被统计
        # 只有 use × 2 和可能的 group
        assert "引用 × 2" in combined

    def test_parse_image_refs(self, parser, tmp_path):
        """解析外部图片引用"""
        svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink">
  <image xlink:href="bg.png" width="800" height="600"/>
  <image href="icon.jpg" width="32" height="32"/>
</svg>"""
        path = self._create_svg(svg, tmp_path)
        result = parser.parse(path)
        texts = [e for e in result[0].elements if e.elementType == "text"]
        combined = " ".join(t.content for t in texts)
        assert "外部图片引用" in combined
        assert "2" in combined

    def test_parse_empty_svg(self, parser, tmp_path):
        """解析空 SVG（无子元素时返回空元素列表）"""
        svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg"/>"""
        path = self._create_svg(svg, tmp_path)
        result = parser.parse(path)
        assert len(result) == 1
        # 空自闭合 SVG 无子元素，元素列表为空
        assert len(result[0].elements) == 0

    def test_parse_group_count(self, parser, tmp_path):
        """统计组数量"""
        svg = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg">
  <g id="layer1">
    <rect x="0" y="0" width="100" height="50"/>
  </g>
  <g id="layer2">
    <circle cx="50" cy="50" r="20"/>
  </g>
</svg>"""
        path = self._create_svg(svg, tmp_path)
        result = parser.parse(path)
        texts = [e for e in result[0].elements if e.elementType == "text"]
        combined = " ".join(t.content for t in texts)
        assert "组 × 2" in combined


class TestSVGParserErrors:
    """异常情况测试"""

    @pytest.fixture
    def parser(self):
        return SVGParser()

    def test_not_svg_xml(self, parser, tmp_path):
        """非 SVG 的 XML 文件"""
        path = tmp_path / "test.svg"
        path.write_text("<root>这不是 SVG</root>", encoding="utf-8")
        result = parser.parse(path)
        # 虽然不是有效 SVG，但 XML 可以解析
        assert len(result) == 1

    def test_invalid_xml(self, parser, tmp_path):
        """无效的 XML"""
        path = tmp_path / "invalid.svg"
        path.write_text("<svg><unclosed>", encoding="utf-8")
        with pytest.raises(ValueError, match="SVG 解析失败"):
            parser.parse(path)

    def test_not_an_svg(self, parser, tmp_path):
        """根本无法解析的文件"""
        path = tmp_path / "test.svg"
        path.write_bytes(b"\x00\x01\x02\x03")
        with pytest.raises(ValueError, match="SVG 解析失败|读取失败"):
            parser.parse(path)