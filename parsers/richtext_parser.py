"""
富文本文件解析器
支持解析 Markdown、RTF 等富文本格式
保留格式标记和结构信息
"""

import logging
import re
from pathlib import Path

from core.models import ExtractedElement, PageContent
from parsers import BaseParser

logger = logging.getLogger("parsers.richtext")

# 可选依赖
try:
    from striprtf.striprtf import rtf_to_text

    RTF_AVAILABLE = True
except ImportError:
    RTF_AVAILABLE = False
    logger.warning("striprtf 库未安装，RTF 解析功能不可用")


class RichTextParser(BaseParser):
    """富文本文件解析器（Markdown/RTF）"""

    @property
    def supported_extensions(self) -> list[str]:
        exts = []
        if RTF_AVAILABLE:
            exts.append(".rtf")
        return exts

    @property
    def supported_magic(self) -> list[bytes]:
        return [
            b"{\\rtf",  # RTF 文件头
        ]

    def parse(self, file_path: Path) -> list[PageContent]:
        """解析富文本文件"""
        file_path = Path(file_path)
        ext = file_path.suffix.lower()

        if ext in (".md", ".markdown"):
            return self._parse_markdown(file_path)
        elif ext == ".rtf" and RTF_AVAILABLE:
            return self._parse_rtf(file_path)
        else:
            raise ValueError(f"不支持的富文本格式: {ext}")

    def _parse_markdown(self, file_path: Path) -> list[PageContent]:
        """解析 Markdown 文件"""
        logger.info("开始解析 Markdown: %s", file_path)

        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            logger.error("无法读取 Markdown 文件: %s", e)
            raise ValueError(f"无法读取 Markdown 文件: {e}") from e

        elements = []
        raw_lines = []
        elem_idx = 0

        # 按行解析 Markdown
        lines = content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            if not stripped:
                i += 1
                continue

            # 检测标题
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading_match:
                level = len(heading_match.group(1))
                text = heading_match.group(2)
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_1_{elem_idx}",
                        elementType="heading",
                        content=text,
                        metadata={"level": level, "markdown": stripped},
                    )
                )
                raw_lines.append(text)
                elem_idx += 1
                i += 1
                continue

            # 检测代码块
            if stripped.startswith("```"):
                lang = stripped[3:].strip()
                code_lines = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    code_lines.append(lines[i])
                    i += 1
                i += 1  # 跳过结束标记

                code_content = "\n".join(code_lines)
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_1_{elem_idx}",
                        elementType="code",
                        content=code_content,
                        metadata={"language": lang, "markdown": f"```{lang}\n{code_content}\n```"},
                    )
                )
                raw_lines.append(code_content)
                elem_idx += 1
                continue

            # 检测引用块
            if stripped.startswith(">"):
                quote_lines = []
                while i < len(lines) and lines[i].strip().startswith(">"):
                    quote_lines.append(lines[i].strip()[1:].strip())
                    i += 1

                quote_text = "\n".join(quote_lines)
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_1_{elem_idx}",
                        elementType="quote",
                        content=quote_text,
                        metadata={"markdown": "\n".join(lines[i - len(quote_lines) : i])},
                    )
                )
                raw_lines.append(quote_text)
                elem_idx += 1
                continue

            # 检测无序列表
            if re.match(r"^[-*+]\s+", stripped):
                list_items = []
                while i < len(lines) and re.match(r"^[-*+]\s+", lines[i].strip()):
                    item_text = re.sub(r"^[-*+]\s+", "", lines[i].strip())
                    list_items.append(item_text)
                    i += 1

                list_text = "\n".join(list_items)
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_1_{elem_idx}",
                        elementType="list",
                        content=list_text,
                        metadata={"items": list_items, "ordered": False},
                    )
                )
                raw_lines.append(list_text)
                elem_idx += 1
                continue

            # 检测有序列表
            if re.match(r"^\d+\.\s+", stripped):
                list_items = []
                while i < len(lines) and re.match(r"^\d+\.\s+", lines[i].strip()):
                    item_text = re.sub(r"^\d+\.\s+", "", lines[i].strip())
                    list_items.append(item_text)
                    i += 1

                list_text = "\n".join(list_items)
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_1_{elem_idx}",
                        elementType="list",
                        content=list_text,
                        metadata={"items": list_items, "ordered": True},
                    )
                )
                raw_lines.append(list_text)
                elem_idx += 1
                continue

            # 检测表格
            if "|" in stripped:
                table_lines = []
                while i < len(lines) and "|" in lines[i]:
                    table_lines.append(lines[i].strip())
                    i += 1

                # 过滤分隔行（如 |---|---|）
                content_lines = [l for l in table_lines if not re.match(r"^\|?[\s\-:|]+\|?$", l)]
                if content_lines:
                    table_text = "\n".join(content_lines)
                    elements.append(
                        ExtractedElement(
                            elementId=f"elem_1_{elem_idx}",
                            elementType="table",
                            content=table_text,
                            metadata={"markdown": "\n".join(table_lines)},
                        )
                    )
                    raw_lines.append(table_text)
                    elem_idx += 1
                continue

            # 检测图片
            img_match = re.match(r"^!\[(.*?)\]\((.*?)\)$", stripped)
            if img_match:
                alt_text = img_match.group(1)
                img_url = img_match.group(2)
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_1_{elem_idx}",
                        elementType="image",
                        content=f"[图片] {alt_text}",
                        metadata={"alt": alt_text, "url": img_url},
                    )
                )
                raw_lines.append(f"[图片] {alt_text}")
                elem_idx += 1
                i += 1
                continue

            # 检测链接
            link_match = re.match(r"^\[(.*?)\]\((.*?)\)$", stripped)
            if link_match:
                link_text = link_match.group(1)
                link_url = link_match.group(2)
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_1_{elem_idx}",
                        elementType="link",
                        content=f"{link_text} ({link_url})",
                        metadata={"text": link_text, "url": link_url},
                    )
                )
                raw_lines.append(link_text)
                elem_idx += 1
                i += 1
                continue

            # 普通段落
            para_lines = []
            while i < len(lines) and lines[i].strip() and not self._is_special_line(lines[i]):
                para_lines.append(lines[i].strip())
                i += 1

            if para_lines:
                para_text = " ".join(para_lines)
                # 处理内联格式（粗体、斜体等）
                para_text = self._clean_inline_formatting(para_text)
                elements.append(ExtractedElement(elementId=f"elem_1_{elem_idx}", elementType="text", content=para_text))
                raw_lines.append(para_text)
                elem_idx += 1

        logger.info("Markdown 解析完成: %d 个元素", len(elements))

        return [
            PageContent(
                pageNumber=1,
                elements=elements,
                rawText="\n".join(raw_lines),
                hasImage=any(e.elementType == "image" for e in elements),
                hasTable=any(e.elementType == "table" for e in elements),
            )
        ]

    def _parse_rtf(self, file_path: Path) -> list[PageContent]:
        """解析 RTF 文件"""
        if not RTF_AVAILABLE:
            raise ImportError("striprtf 库未安装，无法解析 RTF 文件")

        logger.info("开始解析 RTF: %s", file_path)

        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                rtf_content = f.read()
        except Exception as e:
            logger.error("无法读取 RTF 文件: %s", e)
            raise ValueError(f"无法读取 RTF 文件: {e}") from e

        # 转换为纯文本
        plain_text = rtf_to_text(rtf_content)

        elements = []
        raw_lines = []
        elem_idx = 0

        # 按段落分割
        paragraphs = plain_text.split("\n\n")
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            elem_type = self._detect_element_type(para)
            elements.append(ExtractedElement(elementId=f"elem_1_{elem_idx}", elementType=elem_type, content=para))
            raw_lines.append(para)
            elem_idx += 1

        logger.info("RTF 解析完成: %d 个元素", len(elements))

        return [
            PageContent(pageNumber=1, elements=elements, rawText="\n\n".join(raw_lines), hasImage=False, hasTable=False)
        ]

    def _is_special_line(self, line: str) -> bool:
        """判断是否为特殊 Markdown 行"""
        stripped = line.strip()
        if not stripped:
            return False
        return bool(
            re.match(r"^#{1,6}\s+", stripped)
            or stripped.startswith("```")
            or stripped.startswith(">")
            or re.match(r"^[-*+]\s+", stripped)
            or re.match(r"^\d+\.\s+", stripped)
            or stripped.startswith("![")
            or stripped.startswith("|")
        )

    def _clean_inline_formatting(self, text: str) -> str:
        """清理内联格式标记（保留纯文本）"""
        # 粗体 **text** 或 __text__
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"__(.*?)__", r"\1", text)
        # 斜体 *text* 或 _text_
        text = re.sub(r"\*(.*?)\*", r"\1", text)
        text = re.sub(r"_(.*?)_", r"\1", text)
        # 行内代码 `text`
        text = re.sub(r"`(.*?)`", r"\1", text)
        # 删除线 ~~text~~
        text = re.sub(r"~~(.*?)~~", r"\1", text)
        return text.strip()

    def _detect_element_type(self, text: str) -> str:
        """检测元素类型"""
        text = text.strip()
        if not text:
            return "empty"
        if len(text) < 100 and text.endswith(("：", ":")):
            return "heading"
        if text.startswith(("•", "-", "*")):
            return "list"
        return "text"
