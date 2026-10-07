"""
DOCX 文件解析器
支持解析 Word 文档 (.docx)

H18/audit: .doc（OLE2 旧格式）从未被 python-docx 支持——广告宣称已收缩，
不再假装支持。extensionless OLE2 魔数也随之移除（旧版曾把无扩展名的
.xls/.ppt 误路由到这里）。
"""

import logging
from pathlib import Path

from core.models import ExtractedElement, PageContent
from core.table_semantics import escape_md_cell
from parsers import BaseParser

logger = logging.getLogger("parsers.docx")

# 可选依赖
try:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    logger.warning("python-docx 库未安装，DOCX 解析功能不可用")


class DOCXParser(BaseParser):
    """DOCX 文件解析器"""

    @property
    def supported_extensions(self) -> list[str]:
        return [".docx"]

    @property
    def supported_magic(self) -> list[bytes]:
        # DOCX 是 ZIP 格式；OLE2 魔数属于旧版 .doc/.xls/.ppt，不属于本解析器
        return [b"PK\x03\x04"]

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
        skipped: list[str] = []

        # 遍历文档中的所有元素（保持顺序）
        # FF-M-docx/audit: 旧实现只认 body 的直接子节点 w:p/w:tbl —— w:sdt
        # （内容控件/结构化文档标签）里的正文被整段丢弃；且任一畸形元素抛异常会
        # 直接废掉整篇文档。现按块遍历 + 逐元素隔离。
        for tag, element in self._iter_body_blocks(doc.element.body):
            try:
                if tag == "p":
                    # 段落
                    para = Paragraph(element, doc)
                    text, has_tracked_insert = self._paragraph_text(para)
                    text = text.strip()
                    if not text:
                        continue
                    elem_type = self._detect_paragraph_style(para, text)
                    metadata: dict[str, object] = {
                        "style": para.style.name if para.style else None,
                        "alignment": str(para.alignment) if para.alignment else None,
                    }
                    if has_tracked_insert:
                        # 合并展示（不改写正文），但显式标记：正文含未接受的修订插入
                        metadata["tracked_insert"] = True
                    elements.append(
                        ExtractedElement(
                            elementId=f"elem_1_{elem_idx}",
                            elementType=elem_type,
                            content=text,
                            metadata=metadata,
                        )
                    )
                    raw_text_parts.append(text)
                    elem_idx += 1

                elif tag == "tbl":
                    # 表格
                    table = Table(element, doc)
                    table_text = self._extract_table_text(table)
                    if table_text:
                        has_table = True
                        elements.append(
                            ExtractedElement(
                                elementId=f"elem_1_{elem_idx}",
                                elementType="table",
                                content=table_text,
                                metadata={
                                    "rows": len(table.rows),
                                    "cols": len(table.columns) if table.rows else 0,
                                },
                            )
                        )
                        raw_text_parts.append(f"[表格]\n{table_text}")
                        elem_idx += 1
            except Exception as e:
                # FF-M-docx/audit: 单个畸形元素不得中断整篇文档
                logger.warning("DOCX 元素解析失败（已跳过）: tag=%s, error=%s", tag, e)
                skipped.append(tag)

        # 检查是否有图片
        has_image = len(doc.inline_shapes) > 0 or len(doc.part.package.parts) > 10

        # B5/v0.11.0: 修订追踪（w:ins / w:del）
        revisions: list[dict] = []
        if DOCX_AVAILABLE:
            try:
                body = doc.element.body
                for ins in body.iter(qn("w:ins")):
                    author = ins.get(qn("w:author"), "")
                    date = ins.get(qn("w:date"), "")
                    # 收集该 ins 下所有 w:t 文本
                    text_runs = []
                    for t_node in ins.iter(qn("w:t")):
                        if t_node.text:
                            text_runs.append(t_node.text)
                    if text_runs:
                        revisions.append({"type": "ins", "author": author, "date": date, "text": "".join(text_runs)})
                for del_node in body.iter(qn("w:del")):
                    author = del_node.get(qn("w:author"), "")
                    date = del_node.get(qn("w:date"), "")
                    # w:del 下的删除文本用 w:delText 标签
                    text_runs = []
                    for t_node in del_node.iter(qn("w:delText")):
                        if t_node.text:
                            text_runs.append(t_node.text)
                    if text_runs:
                        revisions.append({"type": "del", "author": author, "date": date, "text": "".join(text_runs)})
            except Exception as e:
                logger.warning("B5 修订追踪扫描失败: %s", e)

        logger.info("DOCX 解析完成: %d 个元素, %d 条修订", len(elements), len(revisions))

        page_metadata: dict[str, object] = {"revisions": revisions, "revisions_count": len(revisions)}
        if skipped:
            # FF-M-docx/audit: 跳过的元素必须可见，不能静默丢内容
            page_metadata["skipped_elements"] = skipped
            page_metadata["skipped_count"] = len(skipped)

        return [
            PageContent(
                pageNumber=1,
                elements=elements,
                rawText="\n".join(raw_text_parts),
                hasImage=has_image,
                hasTable=has_table,
                metadata=page_metadata,
            )
        ]

    @staticmethod
    def _iter_body_blocks(parent):
        """按文档顺序产出 ``(tag, element)`` 块，递归进入 ``w:sdt``/``w:sdtContent``。

        FF-M-docx/audit: 内容控件（w:sdt）里的段落/表格是正文的一部分，旧实现
        只遍历 body 的直接子节点，导致这些内容被整段静默丢弃。
        """
        for element in parent:
            tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag
            if tag == "sdt":
                content = element.find(qn("w:sdtContent"))
                if content is not None:
                    yield from DOCXParser._iter_body_blocks(content)
                else:
                    logger.warning("w:sdt 缺少 w:sdtContent，内容被跳过")
                continue
            yield tag, element

    @staticmethod
    def _paragraph_text(para: "Paragraph") -> tuple[str, bool]:
        """段落文本（含 w:ins 追踪插入与 w:hyperlink 内的文字）。

        FF-M-docx/audit: python-docx 的 ``Paragraph.text`` 只拼接 ``w:p`` 的直接
        ``w:r`` 子节点——被追踪插入（``w:ins``）与超链接里的文字会被静默丢弃
        （插入文本此前只出现在 revisions 元数据里，正文缺失）。这里按 ``w:t``
        收集（删除文本用 ``w:delText``，天然不计入）；插入文本与正文**合并**展示，
        同时返回 ``has_tracked_insert`` 供调用方在 metadata 标记。

        Returns:
            (段落文本, 是否含未接受的 w:ins 插入)
        """
        p = getattr(para, "_p", None)
        if p is None:  # pragma: no cover - 防御
            return para.text, False
        parts = [t.text for t in p.iter(qn("w:t")) if t.text]
        has_ins = p.find(qn("w:ins")) is not None
        return "".join(parts), has_ins

    def _detect_paragraph_style(self, para: "Paragraph", text: str) -> str:
        """检测段落样式类型"""
        text = text.strip()

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
            num_pr = para._p.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr")
            if num_pr is not None:
                return "list"

        # 引用检测
        if text.startswith(">") or style_name.startswith("quote"):
            return "quote"

        # 代码检测
        if style_name.startswith("code") or "code" in style_name:
            return "code"

        return "text"

    def _extract_table_text(self, table: "Table") -> str:
        """提取表格文本内容

        FF-M-table/audit: 单元格里的 ``|``/换行会撕开伪 Markdown 表格的行列边界，
        统一经 ``escape_md_cell``（``|``→``\\|``，换行→``<br>``）。
        """
        rows = []
        for row in table.rows:
            cells = [escape_md_cell(cell.text.strip()) for cell in row.cells]
            rows.append(" | ".join(cells))
        return "\n".join(rows)
