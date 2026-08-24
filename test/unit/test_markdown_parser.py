"""
Markdown 解析器单元测试
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.markdown_parser import MarkdownParser


class TestMarkdownParserBasic:
    """基础测试"""

    def test_supported_extensions(self):
        parser = MarkdownParser()
        assert ".md" in parser.supported_extensions
        assert ".markdown" in parser.supported_extensions
        assert ".txt" not in parser.supported_extensions

    def test_supported_magic_empty(self):
        parser = MarkdownParser()
        assert parser.supported_magic == []

    def test_can_parse_md(self):
        parser = MarkdownParser()
        assert parser.can_parse(Path("/tmp/test.md")) == 0.9

    def test_can_parse_non_md(self):
        parser = MarkdownParser()
        assert parser.can_parse(Path("/tmp/test.pdf")) == 0.0


class TestMarkdownParserRealFile:
    """真实文件解析测试"""

    @pytest.fixture
    def parser(self):
        return MarkdownParser()

    def test_parse_headings(self, parser, tmp_path):
        """解析标题"""
        md_content = """# 一级标题
## 二级标题
### 三级标题
普通段落文本"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding="utf-8")

        result = parser.parse(md_path)
        elements = result[0].elements

        headings = [e for e in elements if e.elementType == "heading"]
        assert len(headings) == 3
        assert headings[0].content == "一级标题"
        assert headings[0].metadata["level"] == 1
        assert headings[1].content == "二级标题"
        assert headings[1].metadata["level"] == 2
        assert headings[2].content == "三级标题"
        assert headings[2].metadata["level"] == 3

        texts = [e for e in elements if e.elementType == "text"]
        assert len(texts) == 1
        assert "普通段落文本" in texts[0].content

    def test_parse_code_block(self, parser, tmp_path):
        """解析代码块"""
        md_content = """```python
def hello():
    print("Hello, World!")
```"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding="utf-8")

        result = parser.parse(md_path)
        elements = result[0].elements

        code_blocks = [e for e in elements if e.elementType == "code"]
        assert len(code_blocks) == 1
        assert code_blocks[0].metadata["language"] == "python"
        assert "def hello():" in code_blocks[0].content

    def test_parse_unordered_list(self, parser, tmp_path):
        """解析无序列表"""
        md_content = """- 项目一
- 项目二
- 项目三"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding="utf-8")

        result = parser.parse(md_path)
        elements = result[0].elements

        lists = [e for e in elements if e.elementType == "list"]
        assert len(lists) == 1
        assert not lists[0].metadata["ordered"]
        assert len(lists[0].metadata["items"]) == 3
        assert lists[0].metadata["items"][0]["text"] == "项目一"

    def test_parse_ordered_list(self, parser, tmp_path):
        """解析有序列表"""
        md_content = """1. 第一步
2. 第二步
3. 第三步"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding="utf-8")

        result = parser.parse(md_path)
        elements = result[0].elements

        lists = [e for e in elements if e.elementType == "list"]
        assert len(lists) == 1
        assert lists[0].metadata["ordered"]
        assert len(lists[0].metadata["items"]) == 3

    def test_parse_table(self, parser, tmp_path):
        """解析表格"""
        md_content = """| 姓名 | 年龄 | 城市 |
|------|------|------|
| 张三 | 25   | 北京 |
| 李四 | 30   | 上海 |"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding="utf-8")

        result = parser.parse(md_path)
        elements = result[0].elements

        tables = [e for e in elements if e.elementType == "table"]
        assert len(tables) == 1
        metadata = tables[0].metadata
        assert metadata["header"] == ["姓名", "年龄", "城市"]
        assert metadata["row_count"] == 2
        assert metadata["col_count"] == 3
        assert "张三" in metadata["rows"][0]

    def test_parse_blockquote(self, parser, tmp_path):
        """解析引用块"""
        md_content = """> 这是一段引用
> 这是引用的第二行"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding="utf-8")

        result = parser.parse(md_path)
        elements = result[0].elements

        quotes = [e for e in elements if e.elementType == "quote"]
        assert len(quotes) == 1
        assert "这是一段引用" in quotes[0].content

    def test_parse_image(self, parser, tmp_path):
        """解析图片"""
        md_content = """![替代文本](https://example.com/image.png "图片标题")"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding="utf-8")

        result = parser.parse(md_path)
        elements = result[0].elements

        images = [e for e in elements if e.elementType == "image"]
        assert len(images) == 1
        assert images[0].metadata["alt"] == "替代文本"
        assert images[0].metadata["url"] == "https://example.com/image.png"
        assert images[0].metadata["title"] == "图片标题"

    def test_parse_front_matter(self, parser, tmp_path):
        """解析 YAML 前言"""
        md_content = """---
title: 测试文档
author: 管理员
date: 2024-01-01
---

# 正文标题"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding="utf-8")

        result = parser.parse(md_path)
        elements = result[0].elements

        front_matters = [e for e in elements if e.elementType == "front_matter"]
        assert len(front_matters) == 1
        assert "title: 测试文档" in front_matters[0].content
        assert front_matters[0].metadata["type"] == "yaml"

        # 确认正文仍被解析
        headings = [e for e in elements if e.elementType == "heading"]
        assert len(headings) == 1
        assert headings[0].content == "正文标题"

    def test_parse_task_list(self, parser, tmp_path):
        """解析任务列表"""
        md_content = """- [x] 已完成任务
- [ ] 未完成任务"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding="utf-8")

        result = parser.parse(md_path)
        elements = result[0].elements

        tasks = [e for e in elements if e.elementType == "task"]
        assert len(tasks) == 2
        assert tasks[0].metadata["checked"] is True
        assert tasks[1].metadata["checked"] is False
        assert tasks[0].content == "已完成任务"

    def test_parse_divider(self, parser, tmp_path):
        """解析分割线"""
        md_content = """标题
---
更多内容"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding="utf-8")

        result = parser.parse(md_path)
        elements = result[0].elements

        dividers = [e for e in elements if e.elementType == "divider"]
        assert len(dividers) == 1

    def test_parse_inline_formatting(self, parser, tmp_path):
        """解析行内格式（粗体、斜体、行内代码、链接）"""
        md_content = """这是一段包含**粗体**、*斜体*和`行内代码`的文字。

这是一个[链接](https://example.com)。"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding="utf-8")

        result = parser.parse(md_path)
        elements = result[0].elements

        texts = [e for e in elements if e.elementType == "text"]
        assert len(texts) >= 1
        # 内联格式被清理，但文本内容保留
        combined = " ".join(e.content for e in texts)
        assert "粗体" in combined
        assert "斜体" in combined
        assert "行内代码" in combined
        assert "链接" in combined

    def test_has_image_table_flags(self, parser, tmp_path):
        """检测 hasImage 和 hasTable 标记"""
        md_content = """# 混合文档

![图片](image.png)

| 列1 | 列2 |
|-----|-----|
| A   | B   |"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding="utf-8")

        result = parser.parse(md_path)
        assert result[0].hasImage is True
        assert result[0].hasTable is True

    def test_parse_empty_md(self, parser, tmp_path):
        """解析空文件"""
        md_path = tmp_path / "empty.md"
        md_path.write_text("", encoding="utf-8")

        result = parser.parse(md_path)
        assert len(result) == 1
        assert len(result[0].elements) == 0

    def test_parse_reference_definition(self, parser, tmp_path):
        """解析链接引用定义"""
        md_content = """[百度]: https://baidu.com "百度搜索"
[Google]: https://google.com"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding="utf-8")

        result = parser.parse(md_path)
        elements = result[0].elements

        refs = [e for e in elements if e.elementType == "reference"]
        assert len(refs) == 2
        assert refs[0].metadata["name"] == "百度"
        assert refs[1].metadata["name"] == "Google"

    def test_parse_footnote(self, parser, tmp_path):
        """解析脚注"""
        md_content = """正文内容[^1]

[^1]: 这里是脚注说明"""
        md_path = tmp_path / "test.md"
        md_path.write_text(md_content, encoding="utf-8")

        result = parser.parse(md_path)
        elements = result[0].elements

        footnotes = [e for e in elements if e.elementType == "footnote"]
        assert len(footnotes) == 1
        assert "脚注说明" in footnotes[0].content