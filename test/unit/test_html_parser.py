"""
HTML 解析器单元测试
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.html_parser import HTMLParser


class TestHTMLParserBasic:
    """基础测试"""

    def test_supported_extensions(self):
        parser = HTMLParser()
        assert ".html" in parser.supported_extensions
        assert ".htm" in parser.supported_extensions

    def test_can_parse_html(self):
        parser = HTMLParser()
        assert parser.can_parse(Path("/tmp/test.html")) == 0.9

    def test_can_parse_by_magic(self):
        parser = HTMLParser()
        assert parser.can_parse(Path("/tmp/test"), b"<!DOCTYPE html>") == 0.95


class TestHTMLParserRealFile:
    """真实文件测试"""

    @pytest.fixture
    def parser(self):
        return HTMLParser()

    def test_parse_simple_html(self, parser, tmp_path):
        """测试简单 HTML"""
        html_path = tmp_path / "test.html"
        html_path.write_text("""<!DOCTYPE html>
<html><head><title>测试页面</title></head>
<body>
<h1>主标题</h1>
<p>这是第一段文字。</p>
<p>这是第二段文字。</p>
</body></html>""", encoding='utf-8')

        result = parser.parse(html_path)

        assert len(result) == 1
        assert "测试页面" in result[0].rawText
        assert "主标题" in result[0].rawText
        assert any(e.elementType == "title" for e in result[0].elements)
        assert any(e.elementType == "heading" for e in result[0].elements)

    def test_parse_html_with_list(self, parser, tmp_path):
        """测试包含列表的 HTML"""
        html_path = tmp_path / "list.html"
        html_path.write_text("""<html><body>
<ul>
<li>项目 1</li>
<li>项目 2</li>
<li>项目 3</li>
</ul>
</body></html>""", encoding='utf-8')

        result = parser.parse(html_path)

        list_elems = [e for e in result[0].elements if e.elementType == "list"]
        assert len(list_elems) == 3
        assert "项目 1" in result[0].rawText

    def test_parse_html_skip_script(self, parser, tmp_path):
        """测试跳过 script 标签"""
        html_path = tmp_path / "script.html"
        html_path.write_text("""<html><body>
<p>可见内容</p>
<script>var x = 1;</script>
<p>更多内容</p>
</body></html>""", encoding='utf-8')

        result = parser.parse(html_path)

        assert "可见内容" in result[0].rawText
        assert "var x" not in result[0].rawText

    def test_parse_html_with_table(self, parser, tmp_path):
        """测试表格检测"""
        html_path = tmp_path / "table.html"
        html_path.write_text("""<html><body>
<table><tr><td>单元格</td></tr></table>
</body></html>""", encoding='utf-8')

        result = parser.parse(html_path)

        assert result[0].hasTable is True

    def test_parse_html_with_image(self, parser, tmp_path):
        """测试图片检测"""
        html_path = tmp_path / "image.html"
        html_path.write_text("""<html><body>
<img src="test.jpg" alt="测试图片">
<p>文字内容</p>
</body></html>""", encoding='utf-8')

        result = parser.parse(html_path)

        assert result[0].hasImage is True

    def test_parse_html_entities(self, parser, tmp_path):
        """测试 HTML 实体解码"""
        html_path = tmp_path / "entities.html"
        html_path.write_text("""<html><body>
<p>&lt;div&gt; &amp; &quot;引号&quot;</p>
</body></html>""", encoding='utf-8')

        result = parser.parse(html_path)

        assert "<div>" in result[0].rawText
        assert "&" in result[0].rawText
        assert "引号" in result[0].rawText

    def test_parse_html_fallback(self, parser, tmp_path):
        """测试正则回退提取"""
        html_path = tmp_path / "fallback.html"
        # 故意写一个不完整的 HTML，触发回退
        html_path.write_text("""<html><body>
<h1>标题</h1>
<p>段落内容</p>
<li>列表项</li>
</body></html>""", encoding='utf-8')

        result = parser.parse(html_path)

        assert "标题" in result[0].rawText
        assert "段落内容" in result[0].rawText


class TestHTMLParserEdgeCases:
    """边界情况测试"""

    def test_empty_html(self, tmp_path):
        parser = HTMLParser()
        html_path = tmp_path / "empty.html"
        html_path.write_text("<html><body></body></html>", encoding='utf-8')

        result = parser.parse(html_path)

        assert len(result) == 1
        assert result[0].rawText == ""

    def test_html_no_title(self, tmp_path):
        parser = HTMLParser()
        html_path = tmp_path / "no_title.html"
        html_path.write_text("<html><body><p>内容</p></body></html>", encoding='utf-8')

        result = parser.parse(html_path)

        assert "内容" in result[0].rawText
        assert not any(e.elementType == "title" for e in result[0].elements)


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
