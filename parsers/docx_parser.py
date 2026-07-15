"""
DOCX/DOC 文件解析器
支持解析 Word 文档 (.doc, .docx)
"""

import logging
from pathlib import Path

from core.models import ExtractedElement, PageContent
from parsers import BaseParser

logger = logging.getLogger("parsers.docx")

# 可选依赖
try:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    logger.warning("python-docx 库未安装，DOCX 解析功能不可用")


class DOCXParser(BaseParser):
    """DOCX/DOC 文件解析器"""

    @property
    def supported_extensions(self) -> list[str]:
        return [".docx", ".doc"]

    @property
    def supported_magic(self) -> list[bytes]:
        # DOCX 是 ZIP 格式
        # DOC 是 OLE2 格式
        return [b"PK\x03\x04", b"\xd0\xcf\x11\xe0"]

    def parse(self, file_path: Path) -> list[PageContent]:
        """解析 DOCX 文件"""
        if not DOCX_AVAILABLE:
            raise ImportError("python-docx 库未安装，无法解析 DOCX 文件")

        logger.info("开始解析 DOCX: %s", file_path)

        try:
            doc = Document(str(file_path))
        except Exception as e:
            logger.error("无法打开 DOCX 文件: %s", e)
            raise ValueError(f"无法打开 DOCX 文件: {e}") from e

        elements = []
        raw_text_parts = []
        has_table = False
        has_image = False
        elem_idx = 0

        # 遍历文档中的所有元素（保持顺序）
        for element in doc.element.body:
            tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

            if tag == "p":
                # 段落
                para = Paragraph(element, doc)
                text = para.text.strip()
                if text:
                    elem_type = self._detect_paragraph_style(para)
                    elements.append(
                        ExtractedElement(
                            elementId=f"elem_1_{elem_idx}",
                            elementType=elem_type,
                            content=text,
                            metadata={
                                "style": para.style.name if para.style else None,
                                "alignment": str(para.alignment) if para.alignment else None,
                            },
                        )
                    )
                    raw_text_parts.append(text)
                    elem_idx += 1

            elif tag == "tbl":
                # 表格
                has_table = True
                table = Table(element, doc)
                table_text = self._extract_table_text(table)
                if table_text:
                    elements.append(
                        ExtractedElement(
                            elementId=f"elem_1_{elem_idx}",
                            elementType="table",
                            content=table_text,
                            metadata={"rows": len(table.rows), "cols": len(table.columns) if table.rows else 0},
                        )
                    )
                    raw_text_parts.append(f"[表格]\n{table_text}")
                    elem_idx += 1

        # 检查是否有图片
        has_image = len(doc.inline_shapes) > 0 or len(doc.part.package.parts) > 10

        logger.info("DOCX 解析完成: %d 个元素", len(elements))

        return [
            PageContent(
                pageNumber=1,
                elements=elements,
                rawText="\n".join(raw_text_parts),
                hasImage=has_image,
                hasTable=has_table,
            )
        ]

    def _detect_paragraph_style(self, para: "Paragraph") -> str:
        """检测段落样式类型"""
        text = para.text.strip()

        # 空段落
        if not text:
            return "empty"

        # 标题检测
        style_name = para.style.name.lower() if para.style else ""
        if "heading" in style_name or "标题" in style_name:
            return "heading"
        if para.style and para.style.name.startswith("Heading"):
            return "heading"

        # 列表检测
        if text.startswith(("•", "-", "*", "1.", "2.", "（", "(")):
            return "list"
        if para._p is not None:
            numPr = para._p.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr")
            if numPr is not None:
                return "list"

        # 引用检测
        if text.startswith(">") or style_name.startswith("quote"):
            return "quote"

        # 代码检测
        if style_name.startswith("code") or "code" in style_name:
            return "code"

        return "text"

    def _extract_table_text(self, table: "Table") -> str:
        """提取表格文本内容"""
        rows = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows.append(" | ".join(cells))
        return "\n".join(rows)
