"""
RichText 解析器单元测试（Markdown/RTF）
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.richtext_parser import RichTextParser


class TestRichTextParserBasic:
    """基础测试"""

    def test_supported_extensions(self):
        parser = RichTextParser()
        # Markdown 已由独立的 MarkdownParser 负责
        assert ".md" not in parser.supported_extensions
        assert ".markdown" not in parser.supported_extensions

    def test_can_parse_md(self):
        parser = RichTextParser()
        # .md 不再由 RichTextParser 解析
        assert parser.can_parse(Path("/tmp/test.md")) == 0.0


class TestRichTextParserMarkdown:
    """Markdown 解析测试"""

    @pytest.fixture
    def parser(self):
        return RichTextParser()

    def test_parse_headings(self, parser, tmp_path):
        """测试标题解析"""
        md_path = tmp_path / "headings.md"
        md_path.write_text("# 一级标题\n## 二级标题\n### 三级标题", encoding='utf-8')

        result = parser.parse(md_path)

        headings = [e for e in result[0].elements if e.elementType == "heading"]
        assert len(headings) == 3
        assert any("一级标题" in e.content for e in headings)

    def test_parse_code_block(self, parser, tmp_path):
        """测试代码块"""
        md_path = tmp_path / "code.md"
        md_path.write_text("```python\nprint('hello')\n```", encoding='utf-8')

        result = parser.parse(md_path)

        code_elems = [e for e in result[0].elements if e.elementType == "code"]
        assert len(code_elems) == 1
        assert "print" in code_elems[0].content

    def test_parse_list(self, parser, tmp_path):
        """测试列表"""
        md_path = tmp_path / "list.md"
        md_path.write_text("- 项目 1\n- 项目 2\n- 项目 3", encoding='utf-8')

        result = parser.parse(md_path)

        list_elems = [e for e in result[0].elements if e.elementType == "list"]
        assert len(list_elems) == 1
        assert "项目 1" in list_elems[0].content

    def test_parse_ordered_list(self, parser, tmp_path):
        """测试有序列表"""
        md_path = tmp_path / "ordered.md"
        md_path.write_text("1. 第一项\n2. 第二项\n3. 第三项", encoding='utf-8')

        result = parser.parse(md_path)

        list_elems = [e for e in result[0].elements if e.elementType == "list"]
        assert len(list_elems) == 1
        assert list_elems[0].metadata["ordered"] is True

    def test_parse_table(self, parser, tmp_path):
        """测试表格"""
        md_path = tmp_path / "table.md"
        md_path.write_text("| 列1 | 列2 |\n|-----|-----|\n| A | B |", encoding='utf-8')

        result = parser.parse(md_path)

        assert result[0].hasTable is True
        table_elems = [e for e in result[0].elements if e.elementType == "table"]
        assert len(table_elems) == 1
        assert "A" in table_elems[0].content

    def test_parse_quote(self, parser, tmp_path):
        """测试引用块"""
        md_path = tmp_path / "quote.md"
        md_path.write_text("> 引用内容\n> 第二行", encoding='utf-8')

        result = parser.parse(md_path)

        quote_elems = [e for e in result[0].elements if e.elementType == "quote"]
        assert len(quote_elems) == 1
        assert "引用内容" in quote_elems[0].content

    def test_parse_image(self, parser, tmp_path):
        """测试图片"""
        md_path = tmp_path / "image.md"
        md_path.write_text("![alt text](image.jpg)", encoding='utf-8')

        result = parser.parse(md_path)

        assert result[0].hasImage is True
        img_elems = [e for e in result[0].elements if e.elementType == "image"]
        assert len(img_elems) == 1
        assert "alt text" in img_elems[0].content

    def test_parse_link(self, parser, tmp_path):
        """测试链接"""
        md_path = tmp_path / "link.md"
        md_path.write_text("[链接文字](https://example.com)", encoding='utf-8')

        result = parser.parse(md_path)

        link_elems = [e for e in result[0].elements if e.elementType == "link"]
        assert len(link_elems) == 1
        assert "链接文字" in link_elems[0].content

    def test_parse_inline_formatting(self, parser, tmp_path):
        """测试内联格式清理"""
        md_path = tmp_path / "inline.md"
        md_path.write_text("这是**粗体**和*斜体*和`代码`文本", encoding='utf-8')

        result = parser.parse(md_path)

        text_elems = [e for e in result[0].elements if e.elementType == "text"]
        assert len(text_elems) == 1
        assert "粗体" in text_elems[0].content
        assert "**" not in text_elems[0].content
        assert "`" not in text_elems[0].content

    def test_parse_complex_markdown(self, parser, tmp_path):
        """测试复杂 Markdown 文档"""
        md_path = tmp_path / "complex.md"
        md_path.write_text("""# 文档标题

这是介绍段落。

## 功能列表

- 功能 A
- 功能 B
- 功能 C

## 代码示例

```python
def hello():
    print("world")
```

## 表格

| 名称 | 值 |
|------|-----|
| 键1 | 值1 |
| 键2 | 值2 |
""", encoding='utf-8')

        result = parser.parse(md_path)

        assert len(result[0].elements) > 5
        assert result[0].hasTable is True
        assert any(e.elementType == "heading" for e in result[0].elements)
        assert any(e.elementType == "code" for e in result[0].elements)
        assert any(e.elementType == "list" for e in result[0].elements)


class TestRichTextParserRTF:
    """RTF 解析测试"""

    def test_parse_rtf_without_lib(self, tmp_path):
        """测试未安装 striprtf"""
        with patch('parsers.richtext_parser.RTF_AVAILABLE', False):
            parser = RichTextParser()
            rtf_path = tmp_path / "test.rtf"
            rtf_path.write_text("{\\rtf1 test}", encoding='utf-8')

            # 当 RTF 不可用时，.rtf 不在 supported_extensions 中
            # 解析器会抛出 ValueError（不支持的格式）
            with pytest.raises((ImportError, ValueError)):
                parser.parse(rtf_path)


class TestRichTextParserEdgeCases:
    """边界情况测试"""

    def test_empty_markdown(self, tmp_path):
        parser = RichTextParser()
        md_path = tmp_path / "empty.md"
        md_path.write_text("", encoding='utf-8')

        result = parser.parse(md_path)

        assert len(result) == 1
        assert len(result[0].elements) == 0

    def test_markdown_with_empty_lines(self, tmp_path):
        parser = RichTextParser()
        md_path = tmp_path / "spaces.md"
        md_path.write_text("\n\n# 标题\n\n\n段落\n\n", encoding='utf-8')

        result = parser.parse(md_path)

        assert "标题" in result[0].rawText
        assert "段落" in result[0].rawText


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
