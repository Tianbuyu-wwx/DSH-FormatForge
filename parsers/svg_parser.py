"""
SVG 矢量图解析器
支持解析 .svg 格式矢量图文件
提取文本内容、图形元数据和结构信息
纯 Python 标准库实现（xml.etree.ElementTree），零外部依赖
"""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

from core.models import ExtractedElement, PageContent
from parsers import BaseParser

logger = logging.getLogger("parsers.svg")

# SVG 命名空间
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"

# 基本图形元素
SHAPE_TAGS = {"rect", "circle", "ellipse", "line", "polyline", "polygon", "path"}


class SVGParser(BaseParser):
    """SVG 矢量图解析器"""

    @property
    def supported_extensions(self) -> list[str]:
        return [".svg"]

    @property
    def supported_magic(self) -> list[bytes]:
        return [b"<svg"]

    def parse(self, file_path: Path) -> list[PageContent]:
        """解析 SVG 文件"""
        file_path = Path(file_path)

        logger.info("开始解析 SVG: %s", file_path)

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
        except ET.ParseError as e:
            logger.error("SVG XML 解析失败: %s", e)
            raise ValueError(f"SVG 解析失败（XML 格式错误）: {e}") from e
        except Exception as e:
            logger.error("SVG 文件读取失败: %s", e)
            raise ValueError(f"SVG 文件读取失败: {e}") from e

        elements: list[ExtractedElement] = []
        raw_lines: list[str] = []
        elem_idx = [0]

        # 1. 元数据
        meta = self._extract_metadata(root)
        if meta:
            for key, value in meta.items():
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_1_{elem_idx[0]}",
                        elementType="header",
                        content=f"{key}: {value}",
                        metadata={"field": key, "value": value},
                    )
                )
                raw_lines.append(f"# {key}: {value}")
                elem_idx[0] += 1

        # 2. 文档标题
        title_text = self._find_text_content(root, "title")
        if title_text:
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}", elementType="heading", content=title_text, metadata={"level": 1}
                )
            )
            raw_lines.append(title_text)
            elem_idx[0] += 1

        # 3. 文档描述
        desc_text = self._find_text_content(root, "desc")
        if desc_text:
            elements.append(
                ExtractedElement(elementId=f"elem_1_{elem_idx[0]}", elementType="text", content=desc_text, metadata={})
            )
            raw_lines.append(desc_text)
            elem_idx[0] += 1

        # 4. 文本元素
        text_count = self._extract_text_elements(root, elements, raw_lines, elem_idx)

        # 5. 图形统计摘要
        shape_counts = self._count_shapes(root)
        if shape_counts:
            shape_summary = self._format_shape_summary(shape_counts)
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="text",
                    content=shape_summary,
                    metadata={"shapes": shape_counts},
                )
            )
            raw_lines.append(shape_summary)
            elem_idx[0] += 1

        # 6. 外部资源
        image_refs = self._find_image_refs(root)
        if image_refs:
            img_summary = f"外部图片引用: {len(image_refs)} 个"
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="text",
                    content=img_summary,
                    metadata={"images": image_refs},
                )
            )
            raw_lines.append(img_summary)
            elem_idx[0] += 1

        logger.info(
            "SVG 解析完成: %d 个元素, 文本段数=%d, 图形数=%s",
            len(elements),
            text_count,
            dict(shape_counts) if shape_counts else {},
        )

        return [
            PageContent(
                pageNumber=1,
                elements=elements,
                rawText="\n".join(raw_lines),
                hasImage=bool(image_refs),
                hasTable=False,
            )
        ]

    def _extract_metadata(self, root: ET.Element) -> dict[str, str]:
        """提取 SVG 文档元数据"""
        meta: dict[str, str] = {}
        viewbox = root.get("viewBox")
        if viewbox:
            meta["viewBox"] = viewbox
        w = root.get("width")
        if w:
            meta["width"] = w
        h = root.get("height")
        if h:
            meta["height"] = h
        version = root.get("version")
        if version:
            meta["SVG 版本"] = version
        return meta

    def _find_text_content(self, root: ET.Element, tag: str) -> str:
        """在 SVG 命名空间中查找指定标签的文本内容"""
        elem = root.find(f"{{{SVG_NS}}}{tag}")
        if elem is not None and elem.text:
            return elem.text.strip()
        return ""

    def _extract_text_elements(self, parent: ET.Element, elements: list, raw_lines: list, elem_idx: list) -> int:
        """提取所有文本元素内容"""
        count = 0
        for text_elem in parent.iter(f"{{{SVG_NS}}}text"):
            # 获取位置信息
            x = text_elem.get("x")
            y = text_elem.get("y")
            transform = text_elem.get("transform", "")

            # 收集 tspan 子元素中的文本
            full_text = ""
            tspan_texts: list[str] = []

            for child in text_elem:
                if child.tag == f"{{{SVG_NS}}}tspan":
                    tspan_content = (child.text or "").strip()
                    if tspan_content:
                        tspan_texts.append(tspan_content)
                        child.get("x")
                        child.get("y")

            # 如果无 tspan 子元素，取直接文本
            full_text = (text_elem.text or "").strip() if not tspan_texts else "\n".join(tspan_texts)

            if full_text:
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_1_{elem_idx[0]}",
                        elementType="text",
                        content=full_text,
                        metadata={
                            "x": x,
                            "y": y,
                            "transform": transform,
                            "lines": tspan_texts if tspan_texts else [full_text],
                        },
                    )
                )
                raw_lines.append(full_text)
                elem_idx[0] += 1
                count += 1

        return count

    def _count_shapes(self, root: ET.Element) -> dict[str, int]:
        """统计基本图形元素的数量"""
        counts: dict[str, int] = {}
        # 跳过 defs 中的元素（定义不统计为实际图形）
        defs_elements: set[ET.Element] = set()
        for defs in root.iter(f"{{{SVG_NS}}}defs"):
            defs_elements.update(defs.iter())

        for tag in SHAPE_TAGS:
            for elem in root.iter(f"{{{SVG_NS}}}{tag}"):
                if elem in defs_elements:
                    continue
                counts[tag] = counts.get(tag, 0) + 1

        # 统计 <use> 引用
        use_count = sum(1 for _ in root.iter(f"{{{SVG_NS}}}use") if _ not in defs_elements)
        if use_count:
            counts["use"] = use_count

        # 统计 <g> 组数
        g_count = sum(1 for _ in root.iter(f"{{{SVG_NS}}}g") if _ not in defs_elements)
        if g_count:
            counts["group"] = g_count

        return counts

    def _format_shape_summary(self, shape_counts: dict[str, int]) -> str:
        """格式化图形统计摘要"""
        name_map = {
            "rect": "矩形",
            "circle": "圆形",
            "ellipse": "椭圆",
            "line": "直线",
            "polyline": "折线",
            "polygon": "多边形",
            "path": "路径",
            "use": "引用",
            "group": "组",
        }
        parts = ["图形元素统计: "]
        items = []
        for tag, count in sorted(shape_counts.items(), key=lambda x: -x[1]):
            name = name_map.get(tag, tag)
            items.append(f"{name} × {count}")
        parts.append(", ".join(items))
        return "".join(parts)

    def _find_image_refs(self, root: ET.Element) -> list[dict[str, str]]:
        """查找外部图片引用"""
        refs: list[dict[str, str]] = []
        for image in root.iter(f"{{{SVG_NS}}}image"):
            href = image.get(f"{{{XLINK_NS}}}href") or image.get("href")
            if href:
                refs.append(
                    {
                        "href": href,
                        "width": image.get("width", ""),
                        "height": image.get("height", ""),
                    }
                )
        return refs
