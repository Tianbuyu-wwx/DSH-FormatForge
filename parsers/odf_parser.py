"""
ODF 格式解析器
支持解析开放文档格式：.odt（文档）、.ods（表格）、.odp（演示文稿）
纯 Python 标准库实现（zipfile + xml.etree.ElementTree），零外部依赖
"""

import logging
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from core.models import ExtractedElement, PageContent
from core.table_semantics import escape_md_cell
from parsers import BaseParser

logger = logging.getLogger("parsers.odf")

# ODF 命名空间
NS = {
    "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0",
    "text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0",
    "table": "urn:oasis:names:tc:opendocument:xmlns:table:1.0",
    "draw": "urn:oasis:names:tc:opendocument:xmlns:drawing:1.0",
    "style": "urn:oasis:names:tc:opendocument:xmlns:style:1.0",
    "fo": "urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0",
    "svg": "urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0",
    "meta": "urn:oasis:names:tc:opendocument:xmlns:meta:1.0",
    "xlink": "http://www.w3.org/1999/xlink",
}


def _ns(tag: str) -> str:
    """将带前缀的标签名转为 Clark 表示法"""
    prefix, local = tag.split(":", 1)
    return f"{{{NS[prefix]}}}{local}"


class ODFParser(BaseParser):
    """ODF 开放文档解析器"""

    SUBTYPES = {
        ".odt": "text",
        ".ods": "spreadsheet",
        ".odp": "presentation",
    }

    @property
    def supported_extensions(self) -> list[str]:
        return [".odt", ".ods", ".odp"]

    @property
    def supported_magic(self) -> list[bytes]:
        # ODF 是 ZIP 格式
        return [b"PK\x03\x04"]

    def parse(self, file_path: Path) -> list[PageContent]:
        """解析 ODF 文件"""
        file_path = Path(file_path)
        ext = file_path.suffix.lower()

        logger.info("开始解析 ODF: %s (type=%s)", file_path, ext)

        subtype = self.SUBTYPES.get(ext, "text")

        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                # 读取 content.xml
                if "content.xml" not in zf.namelist():
                    raise ValueError("无效的 ODF 文件：缺少 content.xml")

                content_xml = zf.read("content.xml")
        except zipfile.BadZipFile as e:
            logger.error("不是有效的 ZIP/ODF 文件: %s", file_path)
            raise ValueError(f"不是有效的 ODF 文件: {file_path}") from e
        except Exception as e:
            logger.error("读取 ODF 文件失败: %s", e)
            raise ValueError(f"读取 ODF 文件失败: {e}") from e

        try:
            root = ET.fromstring(content_xml)
        except ET.ParseError as e:
            logger.error("解析 content.xml 失败: %s", e)
            raise ValueError(f"ODF XML 解析失败: {e}") from e

        # 查找 office:body
        body = root.find(_ns("office:body"))
        if body is None:
            raise ValueError("无效的 ODF 文件：缺少 office:body")

        if subtype == "spreadsheet":
            return self._parse_spreadsheet(body)
        elif subtype == "presentation":
            return self._parse_presentation(body)
        else:
            return self._parse_document(body)

    # ==================== ODT 文档解析 ====================

    def _parse_document(self, body: ET.Element) -> list[PageContent]:
        """解析 ODT 文本文档"""
        office_text = body.find(_ns("office:text"))
        if office_text is None:
            return [PageContent(pageNumber=1, elements=[], rawText="", hasImage=False, hasTable=False)]

        elements: list[ExtractedElement] = []
        raw_lines: list[str] = []
        elem_idx = [0]

        self._process_text_body(office_text, elements, raw_lines, elem_idx)

        logger.info("ODT 解析完成: %d 个元素", len(elements))
        return [
            PageContent(
                pageNumber=1,
                elements=elements,
                rawText="\n".join(raw_lines),
                hasImage=any(e.elementType == "image" for e in elements),
                hasTable=any(e.elementType == "table" for e in elements),
            )
        ]

    def _process_text_body(self, parent: ET.Element, elements: list, raw_lines: list, elem_idx: list):
        """递归处理文本 body 中的子元素"""
        for child in parent:
            # H15/audit: 每个 child 独立处理——一个畸形 attribute 不能让整个文档中止
            # （此前 outline-level 等出现在 try 块之外，一路 abort 到底）
            try:
                self._process_body_child(child, elements, raw_lines, elem_idx)
            except Exception as e:  # noqa: BLE001  单元素失败不拖垮整份文档
                logger.warning("ODF 单元素解析失败（跳过）: %s", e)

    def _process_body_child(self, child: ET.Element, elements: list, raw_lines: list, elem_idx: list):
        """单个 body 子元素的分派处理（供 _process_text_body 的 per-element 隔离调用）。"""
        tag = child.tag

        # 标题
        if tag == _ns("text:h"):
            level = max(1, min(self._safe_int(child.get(_ns("text:outline-level")), default=1), 6)) or 1
            text = self._get_text(child)
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="heading",
                    content=text,
                    metadata={"level": level},
                )
            )
            raw_lines.append(text)
            elem_idx[0] += 1

        # 段落
        elif tag == _ns("text:p"):
            text = self._get_text(child)
            if text.strip():
                elements.append(
                    ExtractedElement(elementId=f"elem_1_{elem_idx[0]}", elementType="text", content=text, metadata={})
                )
                raw_lines.append(text)
                elem_idx[0] += 1

        # 列表
        elif tag == _ns("text:list"):
            items = []
            for li in child.findall(_ns("text:list-item")):
                item_text = self._get_text(li)
                if item_text.strip():
                    items.append(item_text)
            if items:
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_1_{elem_idx[0]}",
                        elementType="list",
                        content="\n".join(items),
                        metadata={
                            "ordered": False,
                            "items": [{"text": t} for t in items],
                        },
                    )
                )
                raw_lines.extend(items)
                elem_idx[0] += 1

        # 表格
        elif tag == _ns("table:table"):
            self._extract_table(child, elements, raw_lines, elem_idx)

        # 图片
        elif tag == _ns("draw:frame"):
            image_href = None
            image_node = child.find(_ns("draw:image"))
            if image_node is not None:
                image_href = image_node.get(_ns("xlink:href"))
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="image",
                    content="[图片]",
                    metadata={"url": image_href or "[embedded]"},
                )
            )
            raw_lines.append(f"[图片] {image_href or ''}")
            elem_idx[0] += 1

        # 递归处理其他容器元素
        else:
            self._process_text_body(child, elements, raw_lines, elem_idx)

    # ==================== ODS 表格解析 ====================

    def _parse_spreadsheet(self, body: ET.Element) -> list[PageContent]:
        """解析 ODS 电子表格"""
        office_spreadsheet = body.find(_ns("office:spreadsheet"))
        if office_spreadsheet is None:
            return [PageContent(pageNumber=1, elements=[], rawText="", hasImage=False, hasTable=False)]

        pages: list[PageContent] = []
        for page_num, table_elem in enumerate(office_spreadsheet.findall(_ns("table:table")), start=1):
            sheet_name = table_elem.get(_ns("table:name")) or f"Sheet{page_num}"

            elements: list[ExtractedElement] = []
            raw_lines: list[str] = []
            elem_idx = [0]

            # 表头：工作表名称
            elements.append(
                ExtractedElement(
                    elementId=f"elem_{page_num}_{elem_idx[0]}",
                    elementType="heading",
                    content=f"工作表: {sheet_name}",
                    metadata={"level": 1, "sheet_name": sheet_name},
                )
            )
            raw_lines.append(f"[{sheet_name}]")
            elem_idx[0] += 1

            # 解析行
            for row_elem in table_elem.findall(_ns("table:table-row")):
                cells: list[str] = []
                for cell_elem in row_elem.findall(_ns("table:table-cell")):
                    # H15/audit: 处理列重复——钳制上限（曾用裸 int() 直接扩展）
                    repeat = self._safe_int(cell_elem.get(_ns("table:number-columns-repeated")), default=1)
                    cell_text = self._get_text(cell_elem).strip()
                    for _ in range(repeat):
                        cells.append(cell_text)

                if any(c for c in cells):
                    # FF-M-table/audit: 单元格内的 | / 换行会撕开伪 Markdown 表格几何
                    rendered = [escape_md_cell(c) for c in cells]
                    elements.append(
                        ExtractedElement(
                            elementId=f"elem_{page_num}_{elem_idx[0]}",
                            elementType="table_row",
                            content=" | ".join(rendered),
                            metadata={"cells": cells, "col_count": len(cells), "sheet": sheet_name},
                        )
                    )
                    raw_lines.append(" | ".join(rendered))
                    elem_idx[0] += 1

            pages.append(
                PageContent(
                    pageNumber=page_num,
                    elements=elements,
                    rawText="\n".join(raw_lines),
                    hasImage=False,
                    hasTable=True,
                )
            )

        if not pages:
            pages.append(
                PageContent(
                    pageNumber=1,
                    elements=[],
                    rawText="",
                    hasImage=False,
                    hasTable=False,
                )
            )

        logger.info("ODS 解析完成: %d 个工作表", len(pages))
        return pages

    # ==================== ODP 演示文稿解析 ====================

    def _parse_presentation(self, body: ET.Element) -> list[PageContent]:
        """解析 ODP 演示文稿"""
        office_presentation = body.find(_ns("office:presentation"))
        if office_presentation is None:
            return [PageContent(pageNumber=1, elements=[], rawText="", hasImage=False, hasTable=False)]

        pages: list[PageContent] = []
        for page_num, draw_page in enumerate(office_presentation.findall(_ns("draw:page")), start=1):
            page_name = draw_page.get(_ns("draw:name")) or f"幻灯片 {page_num}"

            elements: list[ExtractedElement] = []
            raw_lines: list[str] = []
            elem_idx = [0]

            # 幻灯片标题
            elements.append(
                ExtractedElement(
                    elementId=f"elem_{page_num}_{elem_idx[0]}",
                    elementType="heading",
                    content=page_name,
                    metadata={"level": 1},
                )
            )
            raw_lines.append(f"--- {page_name} ---")
            elem_idx[0] += 1

            # 提取幻灯片中的文本
            for frame in draw_page.findall(f".//{_ns('draw:frame')}"):
                for text_box in frame.findall(_ns("draw:text-box")):
                    for text_p in text_box.findall(_ns("text:p")):
                        text = self._get_text(text_p)
                        if text.strip():
                            elements.append(
                                ExtractedElement(
                                    elementId=f"elem_{page_num}_{elem_idx[0]}",
                                    elementType="text",
                                    content=text,
                                    metadata={},
                                )
                            )
                            raw_lines.append(text)
                            elem_idx[0] += 1

            # 图片
            for frame in draw_page.findall(f".//{_ns('draw:frame')}"):
                image_node = frame.find(_ns("draw:image"))
                if image_node is not None:
                    image_href = image_node.get(_ns("xlink:href"))
                    elements.append(
                        ExtractedElement(
                            elementId=f"elem_{page_num}_{elem_idx[0]}",
                            elementType="image",
                            content="[图片]",
                            metadata={"url": image_href or "[embedded]"},
                        )
                    )
                    raw_lines.append(f"[图片] {image_href or ''}")
                    elem_idx[0] += 1

            pages.append(
                PageContent(
                    pageNumber=page_num,
                    elements=elements,
                    rawText="\n".join(raw_lines),
                    hasImage=any(e.elementType == "image" for e in elements),
                    hasTable=False,
                )
            )

        if not pages:
            pages.append(
                PageContent(
                    pageNumber=1,
                    elements=[],
                    rawText="",
                    hasImage=False,
                    hasTable=False,
                )
            )

        logger.info("ODP 解析完成: %d 页", len(pages))
        return pages

    # ==================== 公共方法 ====================

    #: H15/audit: int 属性展开上限（repeat/text:c/outline-level 等任何尺寸的
    #: 整数属性都不允许触发 GB 级分配/列表构造）
    _MAX_EXPANSION = 10000

    @staticmethod
    def _safe_int(value: str | None, default: int) -> int:
        """H15/audit: 容错解析 int 属性并钳制——非数字回 default，超大值钳上限，
        阻断 text:c / number-columns-repeated / outline-level 的整数扩展炸弹。"""
        try:
            return max(0, min(int(value), ODFParser._MAX_EXPANSION))
        except (TypeError, ValueError):
            return default

    def _extract_table(self, table_elem: ET.Element, elements: list, raw_lines: list, elem_idx: list):
        """提取表格数据"""
        header: list[str] = []
        rows: list[list[str]] = []
        is_header = True

        for row_elem in table_elem.findall(_ns("table:table-row")):
            cells: list[str] = []
            for cell_elem in row_elem.findall(_ns("table:table-cell")):
                repeat = self._safe_int(cell_elem.get(_ns("table:number-columns-repeated")), default=1)
                cell_text = self._get_text(cell_elem).strip()
                for _ in range(repeat):
                    cells.append(cell_text)

            if not any(c for c in cells):
                continue

            if is_header and cells:
                header = cells
                is_header = False
            else:
                rows.append(cells)

        if rows or header:
            # FF-M-table/audit: 单元格内的 | / 换行会撕开伪 Markdown 表格几何
            safe_header = [escape_md_cell(c) for c in header]
            table_text = (
                " | ".join(safe_header) + "\n" + "\n".join(" | ".join(escape_md_cell(c) for c in r) for r in rows)
                if rows
                else " | ".join(safe_header)
            )
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="table",
                    content=table_text,
                    metadata={
                        "header": header,
                        "rows": rows,
                        "row_count": len(rows),
                        "col_count": max(len(header), max((len(r) for r in rows), default=0)),
                    },
                )
            )
            raw_lines.append(table_text)
            elem_idx[0] += 1

    def _get_text(self, element: ET.Element) -> str:
        """递归提取元素中的纯文本内容"""
        parts: list[str] = []
        # 处理 text:tab
        for tab in element.findall(_ns("text:tab")):
            tab.text = "\t"
        # 处理 text:line-break
        for lb in element.findall(_ns("text:line-break")):
            lb.text = "\n"
        # 处理 text:s (空格)
        for sp in element.findall(_ns("text:s")):
            # H15/audit: text:c 展开钳制（曾用裸 int()）
            count = self._safe_int(sp.get(_ns("text:c")), default=1) or 1
            sp.text = " " * count

        self._element_text(element, parts)
        return "".join(parts).strip()

    def _element_text(self, element: ET.Element, parts: list):
        """递归收集元素文本"""
        if element.text:
            parts.append(element.text)
        for child in element:
            tag = child.tag
            # 跳过特殊元素
            if tag in (_ns("draw:image"), _ns("draw:frame")):
                continue
            self._element_text(child, parts)
            if child.tail:
                parts.append(child.tail)
