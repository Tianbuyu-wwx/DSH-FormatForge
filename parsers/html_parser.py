"""
HTML 文件解析器
支持解析 HTML/HTM 文件，去除标签提取正文内容
保留标题、段落、列表、表格等结构
"""
import logging
import re
from pathlib import Path
from typing import List, Optional

from parsers import BaseParser
from core.models import PageContent, ExtractedElement

logger = logging.getLogger("parsers.html")

# 可选依赖
try:
    from html.parser import HTMLParser
    HTML_PARSER_AVAILABLE = True
except ImportError:
    HTML_PARSER_AVAILABLE = False


class HTMLParserExtractor(HTMLParser):
    """简单的 HTML 内容提取器"""

    def __init__(self):
        super().__init__()
        self.elements = []
        self.current_text = []
        self.current_tag = None
        self.current_attribs = {}
        self.skip_tags = {'script', 'style', 'nav', 'footer', 'header', 'aside'}
        self.in_skip = False
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.skip_tags:
            if not self.in_skip:
                self.in_skip = True
                self.skip_depth = 1
            else:
                self.skip_depth += 1
            return

        if self.in_skip:
            return

        self.current_tag = tag
        self.current_attribs = dict(attrs)

        # 处理特定标签
        if tag == 'br':
            self.current_text.append('\n')
        elif tag in ('p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'tr'):
            if self.current_text:
                self._flush_text()

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.skip_depth -= 1
            if self.skip_depth <= 0:
                self.in_skip = False
                self.skip_depth = 0
            return

        if self.in_skip:
            return

        if self.current_text:
            self._flush_text()
        self.current_tag = None

    def handle_data(self, data):
        if self.in_skip:
            return
        self.current_text.append(data)

    def handle_entityref(self, name):
        if self.in_skip:
            return
        import html
        self.current_text.append(html.unescape(f'&{name};'))

    def handle_charref(self, name):
        if self.in_skip:
            return
        import html
        self.current_text.append(html.unescape(f'&#{name};'))

    def _flush_text(self):
        text = ''.join(self.current_text).strip()
        self.current_text = []
        if not text:
            return

        elem_type = self._detect_type(self.current_tag, text)
        self.elements.append({
            'type': elem_type,
            'content': text,
            'tag': self.current_tag,
            'attribs': self.current_attribs
        })

    def _detect_type(self, tag, text):
        if tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            return 'heading'
        elif tag == 'li':
            return 'list'
        elif tag in ('td', 'th'):
            return 'table'
        elif tag == 'a':
            return 'link'
        elif tag == 'blockquote':
            return 'quote'
        elif tag == 'code':
            return 'code'
        else:
            return 'text'

    def get_elements(self):
        if self.current_text:
            self._flush_text()
        return self.elements


class HTMLParser(BaseParser):
    """HTML 网页文件解析器"""

    @property
    def supported_extensions(self) -> List[str]:
        return [".html", ".htm", ".xhtml"]

    @property
    def supported_magic(self) -> List[bytes]:
        return [
            b"<!DOCTYPE html",
            b"<html",
            b"<HTML",
            b"<?xml",  # XHTML
        ]

    def parse(self, file_path: Path) -> List[PageContent]:
        """解析 HTML 文件"""
        file_path = Path(file_path)
        logger.info("开始解析 HTML: %s", file_path)

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                html_content = f.read()
        except Exception as e:
            logger.error("无法读取 HTML 文件: %s", e)
            raise ValueError(f"无法读取 HTML 文件: {e}")

        # 提取标题
        title = self._extract_title(html_content)

        # 使用解析器提取内容
        extractor = HTMLParserExtractor()
        try:
            extractor.feed(html_content)
            extracted = extractor.get_elements()
        except Exception as e:
            logger.warning("HTML 解析器出错，使用正则回退: %s", e)
            extracted = self._fallback_extract(html_content)

        elements = []
        raw_text_parts = []
        elem_idx = 0

        # 添加标题
        if title:
            elements.append(ExtractedElement(
                elementId=f"elem_1_{elem_idx}",
                elementType="title",
                content=title
            ))
            raw_text_parts.append(title)
            elem_idx += 1

        # 处理提取的元素
        for item in extracted:
            elements.append(ExtractedElement(
                elementId=f"elem_1_{elem_idx}",
                elementType=item['type'],
                content=item['content'],
                metadata={
                    "tag": item['tag'],
                    "attribs": item['attribs']
                }
            ))
            raw_text_parts.append(item['content'])
            elem_idx += 1

        logger.info("HTML 解析完成: %d 个元素", len(elements))

        return [PageContent(
            pageNumber=1,
            elements=elements,
            rawText="\n".join(raw_text_parts),
            hasImage='img' in html_content.lower(),
            hasTable='<table' in html_content.lower()
        )]

    def _extract_title(self, html_content: str) -> str:
        """提取 HTML 标题"""
        match = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
        if match:
            return self._clean_text(match.group(1))

        # 尝试提取 h1
        match = re.search(r'<h1[^>]*>(.*?)</h1>', html_content, re.IGNORECASE | re.DOTALL)
        if match:
            return self._clean_text(match.group(1))

        return ""

    def _fallback_extract(self, html_content: str) -> List[dict]:
        """正则回退提取（当 HTMLParser 失败时使用）"""
        elements = []

        # 提取段落
        for match in re.finditer(r'<p[^>]*>(.*?)</p>', html_content, re.IGNORECASE | re.DOTALL):
            text = self._clean_text(match.group(1))
            if text:
                elements.append({'type': 'text', 'content': text, 'tag': 'p', 'attribs': {}})

        # 提取标题
        for level in range(1, 7):
            for match in re.finditer(rf'<h{level}[^>]*>(.*?)</h{level}>', html_content, re.IGNORECASE | re.DOTALL):
                text = self._clean_text(match.group(1))
                if text:
                    elements.append({'type': 'heading', 'content': text, 'tag': f'h{level}', 'attribs': {}})

        # 提取列表项
        for match in re.finditer(r'<li[^>]*>(.*?)</li>', html_content, re.IGNORECASE | re.DOTALL):
            text = self._clean_text(match.group(1))
            if text:
                elements.append({'type': 'list', 'content': text, 'tag': 'li', 'attribs': {}})

        return elements

    def _clean_text(self, text: str) -> str:
        """清理 HTML 文本"""
        # 移除剩余标签
        text = re.sub(r'<[^>]+>', '', text)
        # 解码 HTML 实体
        import html
        text = html.unescape(text)
        # 合并空白
        text = ' '.join(text.split())
        return text.strip()
