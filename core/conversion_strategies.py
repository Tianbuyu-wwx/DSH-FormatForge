"""
数据转换策略模块
提供多种转换策略，根据AI能力自动选择最佳方案
"""

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

from core.models import ConversionType, FileType, OutputFormat, ParsedFile

# 插件形态：ai_caps 参数保留占位（恒为 None），增强由 dsh 会话模型完成。
from core.utils import create_processing_log

logger = logging.getLogger("conversion_strategies")


class ConversionStrategy(ABC):
    """转换策略抽象基类"""

    def __init__(self):
        self.strategy_id = "base"
        self.strategy_name = "基础策略"
        self.description = "基础转换策略"
        self.supported_types: list[FileType] = []

    @abstractmethod
    def can_handle(self, parsed_file: ParsedFile, ai_caps: Any = None) -> float:
        """
        评估对输入数据的处理能力
        Args:
            parsed_file: 解析后的文件
            ai_caps: 目标AI能力（可选，用于决策）
        Returns: 置信度 0.0-1.0
        """
        pass

    @abstractmethod
    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: Any = None,
        custom_prompt: str | None = None,
    ) -> dict[str, Any]:
        """
        执行转换
        Returns: {"content": str, "structured_data": dict, "confidence": float}
        """
        pass

    def _format_output(self, content: str, output_format: OutputFormat) -> str:
        """根据输出格式格式化内容"""
        if output_format == OutputFormat.JSON:
            try:
                return json.dumps({"content": content}, ensure_ascii=False, indent=2)
            except Exception:
                return content
        elif output_format == OutputFormat.MARKDOWN:
            return f"# 转换结果\n\n{content}"
        else:
            return content


class AutoDetectStrategy(ConversionStrategy):
    """自动检测策略 - 分析内容特征和AI能力，选择最佳子策略"""

    def __init__(self):
        super().__init__()
        self.strategy_id = "auto_detect"
        self.strategy_name = "自动检测"
        self.description = "自动分析内容特征和AI能力，选择最合适的转换策略"
        self.supported_types = [
            FileType.PPT,
            FileType.PDF,
            FileType.IMAGE,
            FileType.DOC,
            FileType.TXT,
            FileType.CSV,
            FileType.XLS,
        ]

    def can_handle(self, parsed_file: ParsedFile, ai_caps: Any = None) -> float:
        return 0.9

    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: Any = None,
        custom_prompt: str | None = None,
    ) -> dict[str, Any]:
        logs = [create_processing_log("auto_detect", "开始自动检测内容特征")]
        logger.info(
            "[strategy=auto_detect] 开始自动检测: file_type=%s, output_format=%s",
            parsed_file.fileType.value,
            output_format.value,
        )

        # 分析内容特征
        has_tables = any(page.hasTable for page in parsed_file.pages)
        has_images = any(page.hasImage for page in parsed_file.pages)
        total_text = sum(len(page.rawText) for page in parsed_file.pages)

        logger.debug(
            "[strategy=auto_detect] 内容特征: text=%d chars, has_tables=%s, has_images=%s",
            total_text,
            has_tables,
            has_images,
        )
        logs.append(
            create_processing_log(
                "feature_analysis", f"分析结果: 文本量={total_text}字符, 含表格={has_tables}, 含图片={has_images}"
            )
        )

        # 如果提供了AI能力，考虑AI支持情况
        # 无内置 AI 客户端：图片保留与否由调用方模型决定，此处恒按不支持处理。
        ai_supports_images = False

        # 根据特征和AI能力选择策略
        # 四个分支产出的都是 ConversionStrategy 子类，统一按基类标注。
        strategy: ConversionStrategy
        if has_tables and not has_images:
            logger.info("[strategy=auto_detect] 选择表格提取策略")
            logs.append(create_processing_log("strategy_select", "选择表格提取策略"))
            strategy = TableExtractionStrategy()
        elif parsed_file.fileType == FileType.IMAGE or (has_images and not ai_supports_images):
            # 如果AI不支持图片输入，需要图片描述
            logger.info("[strategy=auto_detect] 选择图片描述策略（AI不支持图片输入）")
            logs.append(create_processing_log("strategy_select", "选择图片描述策略（AI不支持图片输入）"))
            strategy = ImageDescriptionStrategy()
        elif total_text > 5000:
            logger.info("[strategy=auto_detect] 选择结构化提取策略")
            logs.append(create_processing_log("strategy_select", "选择结构化提取策略"))
            strategy = StructuredExtractionStrategy()
        else:
            logger.info("[strategy=auto_detect] 选择纯文本提取策略")
            logs.append(create_processing_log("strategy_select", "选择纯文本提取策略"))
            strategy = TextExtractionStrategy()

        result = strategy.convert(parsed_file, output_format, ai_caps, custom_prompt)
        result["logs"] = logs + result.get("logs", [])
        logger.info(
            "[strategy=auto_detect] 子策略执行完成: sub_strategy=%s, confidence=%.2f",
            strategy.strategy_id,
            result.get("confidence", 0),
        )
        return result


class TextExtractionStrategy(ConversionStrategy):
    """纯文本提取策略"""

    def __init__(self):
        super().__init__()
        self.strategy_id = "text_extraction"
        self.strategy_name = "纯文本提取"
        self.description = "提取文件中的纯文本内容，保留原始格式"
        self.supported_types = [FileType.PPT, FileType.PDF, FileType.DOC, FileType.TXT]

    def can_handle(self, parsed_file: ParsedFile, ai_caps: Any = None) -> float:
        if parsed_file.fileType in self.supported_types:
            return 0.95
        return 0.3

    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: Any = None,
        custom_prompt: str | None = None,
    ) -> dict[str, Any]:
        logs = [create_processing_log("text_extract", "开始提取纯文本")]
        logger.info("[strategy=text_extract] 开始提取纯文本: pages=%d", len(parsed_file.pages))

        # R2.3: markdown 输出 + 解析层已产出结构标注 → 按层级渲染（标题/列表/目录锚点）
        if output_format == OutputFormat.MARKDOWN:
            has_structure = any(
                (e.metadata or {}).get("heading_level")
                or (e.metadata or {}).get("toc")
                or (e.metadata or {}).get("list_level")
                for page in parsed_file.pages
                for e in page.elements
            )
            if has_structure:
                from core.structure_fidelity import render_markdown

                content = render_markdown(parsed_file.pages)
                logger.info("[strategy=text_extract] 结构化 markdown 渲染: chars=%d", len(content))
                logs.append(create_processing_log("text_extract", f"结构保真渲染完成，共 {len(content)} 字符"))
                return {
                    "content": content,
                    "structured_data": {
                        "pages": len(parsed_file.pages),
                        "total_chars": len(content),
                        "structured": True,
                    },
                    "confidence": 0.92,
                    "logs": logs,
                }

        parts = []
        for page in parsed_file.pages:
            text = self._fix_encoding(page.rawText)
            parts.append(f"--- 第 {page.pageNumber} 页 ---")
            parts.append(text)

        content = "\n\n".join(parts)

        logger.info("[strategy=text_extract] 提取完成: total_chars=%d", len(content))
        logs.append(create_processing_log("text_extract", f"提取完成，共 {len(content)} 字符"))

        return {
            "content": self._format_output(content, output_format),
            "structured_data": {"pages": len(parsed_file.pages), "total_chars": len(content)},
            "confidence": 0.95,
            "logs": logs,
        }

    @staticmethod
    def _fix_encoding(text: str) -> str:
        """修复常见编码问题（合并自 EncodingFixStrategy）"""
        text = text.replace("\u00ef\u00bf\u00bd", "?")
        text = re.sub(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]", "", text)
        return text


class StructuredExtractionStrategy(ConversionStrategy):
    """结构化数据提取策略"""

    def __init__(self):
        super().__init__()
        self.strategy_id = "structured_extraction"
        self.strategy_name = "结构化提取"
        self.description = "将内容提取为结构化格式（JSON/Markdown），保留层级关系"
        self.supported_types = [FileType.PPT, FileType.PDF, FileType.DOC]

    def can_handle(self, parsed_file: ParsedFile, ai_caps: Any = None) -> float:
        if parsed_file.fileType in [FileType.PPT, FileType.PDF]:
            for page in parsed_file.pages:
                for elem in page.elements:
                    if elem.elementType in ["heading", "title"]:
                        return 0.9
            return 0.6
        return 0.4

    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: Any = None,
        custom_prompt: str | None = None,
    ) -> dict[str, Any]:
        logs = [create_processing_log("structured", "开始结构化提取")]
        logger.info("[strategy=structured] 开始结构化提取: pages=%d", len(parsed_file.pages))

        # 显式标注嵌套结构，避免字面量被推断成 dict[str, object] 导致 append 报错。
        structure: dict[str, dict[str, Any]] = {"document": {"title": parsed_file.fileName, "pages": []}}

        for page in parsed_file.pages:
            page_data: dict[str, Any] = {"page_number": page.pageNumber, "elements": []}
            for elem in page.elements:
                page_data["elements"].append({"type": elem.elementType, "content": elem.content[:500]})
            structure["document"]["pages"].append(page_data)

        logger.info(
            "[strategy=structured] 结构化完成: pages=%d, elements=%d",
            len(parsed_file.pages),
            sum(len(p["elements"]) for p in structure["document"]["pages"]),
        )
        logs.append(create_processing_log("structured", f"结构化完成，共 {len(parsed_file.pages)} 页"))

        content = json.dumps(structure, ensure_ascii=False, indent=2)

        return {"content": content, "structured_data": structure, "confidence": 0.85, "logs": logs}


class TableExtractionStrategy(ConversionStrategy):
    """表格提取策略 - 增强版：合并单元格识别 + 数值格式化 + 多 Sheet 支持"""

    def __init__(self):
        super().__init__()
        self.strategy_id = "table_extraction"
        self.strategy_name = "表格提取"
        self.description = "识别并提取文档中的表格数据，转换为Markdown表格或JSON，支持合并单元格检测与数值格式化"
        self.supported_types = [FileType.PDF, FileType.PPT, FileType.CSV, FileType.XLS]

    def can_handle(self, parsed_file: ParsedFile, ai_caps: Any = None) -> float:
        if any(page.hasTable for page in parsed_file.pages):
            return 0.95
        if parsed_file.fileType in [FileType.CSV, FileType.XLS]:
            return 0.95
        return 0.2

    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: Any = None,
        custom_prompt: str | None = None,
    ) -> dict[str, Any]:
        logs = [create_processing_log("table", "开始提取表格数据（增强模式）")]
        logger.info("[strategy=table] 开始提取表格数据: pages=%d", len(parsed_file.pages))

        # 收集所有表格元素（v2.1.0: 显式类型注解避免 mypy 推断为 list[object]）
        all_tables: list[dict[str, Any]] = []
        for page in parsed_file.pages:
            for elem in page.elements:
                if elem.elementType == "table":
                    all_tables.append(
                        {
                            "page": page.pageNumber,
                            "content": elem.content,
                            "metadata": elem.metadata or {},
                        }
                    )

        if not all_tables:
            return {
                "content": "未检测到表格数据",
                "structured_data": {"tables_found": 0, "tables": []},
                "confidence": 0.3,
                "logs": logs,
            }

        # 处理每个表格
        structured_tables = []
        md_output_parts = []
        total_rows = 0
        total_merged = 0

        for idx, table in enumerate(all_tables, 1):
            sheet_name = table["metadata"].get("sheet_name", "")
            sheet_label = f" (Sheet: {sheet_name})" if sheet_name else ""

            # 解析表格为二维数组
            rows = self._parse_table_rows(table["content"])

            if not rows:
                continue

            # 检测并标记合并单元格
            merged_info = self._detect_merged_cells(rows)
            total_merged += merged_info["merged_count"]

            # 格式化数值
            formatted_rows = self._format_numeric_values(rows)

            # 生成 Markdown 表格
            md_table = self._generate_markdown_table(formatted_rows, merged_info, title=f"表格 {idx}{sheet_label}")
            md_output_parts.append(md_table)

            # 结构化数据
            structured_tables.append(
                {
                    "table_index": idx,
                    "page": table["page"],
                    "sheet_name": sheet_name,
                    "rows": len(formatted_rows),
                    "cols": len(formatted_rows[0]) if formatted_rows else 0,
                    "has_header": table["metadata"].get("has_header", False),
                    "merged_cells": merged_info["merged_count"],
                    "headers": formatted_rows[0] if formatted_rows else [],
                    "data": formatted_rows,
                }
            )
            total_rows += len(formatted_rows)

        content = "\n\n".join(md_output_parts)

        logger.info(
            "[strategy=table] 提取完成: tables=%d, total_rows=%d, merged_cells=%d",
            len(structured_tables),
            total_rows,
            total_merged,
        )
        logs.append(
            create_processing_log(
                "table", f"提取完成，共 {len(structured_tables)} 个表格, {total_rows} 行, {total_merged} 个合并单元格"
            )
        )

        return {
            "content": content,
            "structured_data": {
                "tables_found": len(structured_tables),
                "total_rows": total_rows,
                "merged_cells": total_merged,
                "tables": structured_tables,
            },
            "confidence": 0.85 if structured_tables else 0.3,
            "logs": logs,
        }

    # ═══════════════════════════════════════════
    # 表格行解析
    # ═══════════════════════════════════════════

    def _parse_table_rows(self, text: str) -> list[list[str]]:
        """解析表格文本为二维数组，自动检测分隔符"""
        # 去掉 sheet 前缀
        lines = text.split("\n")
        if lines and lines[0].startswith("Sheet:"):
            lines = lines[1:]
        if lines and lines[0].startswith("[Sheet:"):
            lines = lines[1:]

        # 过滤空行
        lines = [line.strip() for line in lines if line.strip() and not line.strip().startswith("Sheet:")]

        if not lines:
            return []

        # 检测分隔符
        delimiter = self._detect_delimiter(lines)
        rows = []

        for line in lines:
            if delimiter == "|":
                cells = [c.strip() for c in line.split("|")]
                # 去掉首尾空元素（| 开头或结尾产生的）
                if cells and cells[0] == "":
                    cells = cells[1:]
                if cells and cells[-1] == "":
                    cells = cells[:-1]
            elif delimiter == "\t":
                cells = [c.strip() for c in line.split("\t")]
            elif delimiter == ",":
                cells = [c.strip() for c in line.split(",")]
            else:
                # 多空格分隔
                cells = [c.strip() for c in line.split("  ") if c.strip()]

            if cells:
                rows.append(cells)

        # 对齐列数
        if rows:
            max_cols = max(len(r) for r in rows)
            for row in rows:
                while len(row) < max_cols:
                    row.append("")

        return rows

    def _detect_delimiter(self, lines: list[str]) -> str:
        """检测表格分隔符"""
        if not lines:
            return "|"

        # 优先检查竖线
        pipe_count = sum(line.count("|") for line in lines)
        tab_count = sum(line.count("\t") for line in lines)
        comma_count = sum(line.count(",") for line in lines)

        if pipe_count > tab_count and pipe_count > comma_count:
            return "|"
        if tab_count > comma_count:
            return "\t"
        if comma_count > 0:
            return ","
        return "  "

    # ═══════════════════════════════════════════
    # 合并单元格检测
    # ═══════════════════════════════════════════

    def _detect_merged_cells(self, rows: list[list[str]]) -> dict[str, Any]:
        """
        检测合并单元格

        策略：
        1. 纵向合并：连续多行同一列出现相同值（非空），且相邻列为空或不同值
        2. 横向合并：同一行连续多列为空，且上下列对应位置有值

        Returns:
            {"merged_count": int, "merged_cells": [{row, col, rowspan, colspan, value}]}
        """
        if len(rows) < 2:
            return {"merged_count": 0, "merged_cells": []}

        max_cols = max(len(r) for r in rows) if rows else 0
        merged_cells = []
        processed = set()

        # 纵向合并检测
        for col in range(max_cols):
            row_idx = 0
            while row_idx < len(rows):
                if col >= len(rows[row_idx]):
                    row_idx += 1
                    continue
                cell_value = rows[row_idx][col].strip()
                if not cell_value:
                    row_idx += 1
                    continue

                # 检查下方连续相同值
                span = 1
                for next_row in range(row_idx + 1, len(rows)):
                    if col >= len(rows[next_row]):
                        break
                    if rows[next_row][col].strip() == cell_value:
                        span += 1
                    else:
                        break

                if span >= 2:
                    merged_cells.append(
                        {
                            "row": row_idx,
                            "col": col,
                            "rowspan": span,
                            "colspan": 1,
                            "value": cell_value,
                        }
                    )
                    # 标记已处理
                    for r in range(row_idx, row_idx + span):
                        processed.add((r, col))
                    row_idx += span
                else:
                    row_idx += 1

        # 横向合并检测（同一行连续空单元格）
        for row_idx, row in enumerate(rows):
            col_idx = 0
            while col_idx < len(row):
                if row[col_idx].strip():
                    col_idx += 1
                    continue
                # 检查连续空单元格
                span = 1
                for next_col in range(col_idx + 1, len(row)):
                    if not row[next_col].strip():
                        span += 1
                    else:
                        break
                if span >= 2:
                    # 确认上下列对应位置有值（真正的合并单元格）
                    has_value_above = (
                        row_idx > 0 and col_idx < len(rows[row_idx - 1]) and rows[row_idx - 1][col_idx].strip()
                    )
                    if has_value_above:
                        merged_cells.append(
                            {
                                "row": row_idx,
                                "col": col_idx,
                                "rowspan": 1,
                                "colspan": span,
                                "value": rows[row_idx - 1][col_idx].strip(),
                            }
                        )
                    col_idx += span
                else:
                    col_idx += 1

        return {
            "merged_count": len(merged_cells),
            "merged_cells": merged_cells,
        }

    # ═══════════════════════════════════════════
    # 数值格式化
    # ═══════════════════════════════════════════

    def _format_numeric_values(self, rows: list[list[str]]) -> list[list[str]]:
        """
        格式化数值：检测数字并统一格式

        规则：
        - 整数: 添加千分位分隔符（可选）
        - 浮点数: 保留合理精度
        - 百分比字符串: 保持原样
        - 日期/时间: 保持原样
        - 纯文本: 保持原样
        """
        formatted = []
        for row in rows:
            formatted_row = []
            for cell in row:
                formatted_row.append(self._format_cell(cell))
            formatted.append(formatted_row)
        return formatted

    def _format_cell(self, value: str) -> str:
        """格式化单个单元格"""
        stripped = value.strip()
        if not stripped:
            return ""

        # 跳过明显非数值的内容
        if any(c in stripped for c in ["http", "www", "@", "：", "："]):
            return stripped

        # 先声明联合类型：下方两个分支分别赋 int / float。
        num: int | float
        # 尝试解析为整数
        try:
            num = int(stripped.replace(",", "").replace(" ", ""))
            return str(num)
        except ValueError:
            pass

        # 尝试解析为浮点数
        try:
            num = float(stripped.replace(",", "").replace(" ", ""))
            # 保留合理精度
            if abs(num) >= 1e6 or (abs(num) < 1e-4 and num != 0):
                return f"{num:.6g}"
            if num == int(num):
                return str(int(num))
            # 最多保留 4 位小数
            return f"{num:.4f}".rstrip("0").rstrip(".")
        except ValueError:
            pass

        return stripped

    # ═══════════════════════════════════════════
    # Markdown 表格生成
    # ═══════════════════════════════════════════

    def _generate_markdown_table(
        self,
        rows: list[list[str]],
        merged_info: dict[str, Any],
        title: str = "",
    ) -> str:
        """
        生成 Markdown 表格，支持合并单元格标记

        Args:
            rows: 二维数组
            merged_info: 合并单元格信息
            title: 表格标题

        Returns:
            Markdown 格式表格字符串
        """
        if not rows:
            return f"*{title}* (空表格)"

        parts = []
        if title:
            parts.append(f"### {title}\n")

        max_cols = max(len(r) for r in rows)
        # 补齐列
        aligned_rows = [list(r) + [""] * (max_cols - len(r)) for r in rows]

        # 创建合并单元格查找表
        merged_map = {}
        for mc in merged_info.get("merged_cells", []):
            for r_offset in range(mc["rowspan"]):
                for c_offset in range(mc["colspan"]):
                    if r_offset == 0 and c_offset == 0:
                        continue  # 保留原始单元格
                    merged_map[(mc["row"] + r_offset, mc["col"] + c_offset)] = {
                        "rowspan": mc["rowspan"] - r_offset,
                        "colspan": mc["colspan"] - c_offset,
                    }

        # 转义管道符
        def _escape(cell: str) -> str:
            return cell.replace("|", "\\|").replace("\n", " ")

        # 表头行
        header_cells = []
        for c, cell in enumerate(aligned_rows[0]):
            key = (0, c)
            if key in merged_map:
                info = merged_map[key]
                if info["colspan"] > 1:
                    header_cells.append(_escape(cell))
                    for _ in range(info["colspan"] - 1):
                        header_cells.append("")  # 合并占位
                else:
                    header_cells.append(_escape(cell))
            else:
                header_cells.append(_escape(cell))
        # 截断到 max_cols
        header_cells = header_cells[:max_cols]
        while len(header_cells) < max_cols:
            header_cells.append("")
        parts.append("| " + " | ".join(header_cells) + " |")

        # 分隔行
        align_parts = ["---"] * max_cols
        parts.append("| " + " | ".join(align_parts) + " |")

        # 数据行
        for r in range(1, len(aligned_rows)):
            row_cells = []
            for c in range(max_cols):
                cell = aligned_rows[r][c] if c < len(aligned_rows[r]) else ""
                row_cells.append(_escape(cell))
            parts.append("| " + " | ".join(row_cells) + " |")

        # 合并单元格标注
        if merged_info.get("merged_cells"):
            merged_count = merged_info["merged_count"]
            parts.append(f"\n> 检测到 {merged_count} 个合并单元格")

        return "\n".join(parts)


class ImageDescriptionStrategy(ConversionStrategy):
    """图片描述策略 - 将图片内容转换为文字描述"""

    def __init__(self):
        super().__init__()
        self.strategy_id = "image_description"
        self.strategy_name = "图片描述"
        self.description = "将图片转换为详细的文字描述，使文本AI能够理解图片内容"
        self.supported_types = [FileType.IMAGE, FileType.PPT, FileType.PDF]

    def can_handle(self, parsed_file: ParsedFile, ai_caps: Any = None) -> float:
        if parsed_file.fileType == FileType.IMAGE:
            return 0.95
        if any(page.hasImage for page in parsed_file.pages):
            return 0.85
        return 0.1

    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: Any = None,
        custom_prompt: str | None = None,
    ) -> dict[str, Any]:
        logs = [create_processing_log("image_desc", "开始处理图片内容")]
        logger.info("[strategy=image_desc] 开始处理图片内容: pages=%d", len(parsed_file.pages))

        # 如果AI支持图片输入，标记为可保留原图
        # 无内置 AI 客户端：图片保留与否由调用方模型决定，此处恒按不支持处理。
        ai_supports_images = False

        image_info = []
        for page in parsed_file.pages:
            for elem in page.elements:
                if elem.elementType == "image":
                    image_info.append({"page": page.pageNumber, "description": elem.content or "图片"})

        parts = ["# 图片内容描述\n"]
        for idx, img in enumerate(image_info, 1):
            parts.append(f"## 图片 {idx} (第 {img['page']} 页)")
            parts.append(f"- 位置: 第 {img['page']} 页")
            parts.append(f"- 描述: {img['description']}")
            if ai_supports_images:
                parts.append("- 状态: AI支持图片输入，建议保留原图")
            parts.append("")

        content = "\n".join(parts) if image_info else "未检测到图片内容"

        logger.info(
            "[strategy=image_desc] 处理完成: images_found=%d, ai_supports_images=%s",
            len(image_info),
            ai_supports_images,
        )
        logs.append(create_processing_log("image_desc", f"处理完成，共 {len(image_info)} 张图片"))

        return {
            "content": content,
            "structured_data": {
                "images_found": len(image_info),
                "images": image_info,
                "ai_supports_images": ai_supports_images,
            },
            "confidence": 0.75 if image_info else 0.3,
            "logs": logs,
        }


class OcrStrategy(ConversionStrategy):
    """OCR文字识别策略"""

    def __init__(self):
        super().__init__()
        self.strategy_id = "ocr"
        self.strategy_name = "OCR文字识别"
        self.description = "识别图片中的文字内容"
        self.supported_types = [FileType.IMAGE, FileType.PDF, FileType.PPT]

    def can_handle(self, parsed_file: ParsedFile, ai_caps: Any = None) -> float:
        if parsed_file.fileType == FileType.IMAGE:
            return 0.9
        if any(page.hasImage for page in parsed_file.pages):
            return 0.7
        return 0.1

    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: Any = None,
        custom_prompt: str | None = None,
    ) -> dict[str, Any]:
        logs = [create_processing_log("ocr", "开始OCR文字识别")]
        logger.info("[strategy=ocr] 开始OCR文字识别: pages=%d", len(parsed_file.pages))

        all_text = []
        for page in parsed_file.pages:
            if page.rawText.strip():
                all_text.append(f"--- 第 {page.pageNumber} 页 ---")
                all_text.append(page.rawText)

        content = "\n\n".join(all_text) if all_text else "未识别到文字内容"

        logger.info("[strategy=ocr] 识别完成: segments=%d, content_length=%d", len(all_text), len(content))
        logs.append(create_processing_log("ocr", f"识别完成，共 {len(all_text)} 段文字"))

        return {
            "content": content,
            "structured_data": {"pages_processed": len(parsed_file.pages)},
            "confidence": 0.8 if all_text else 0.2,
            "logs": logs,
        }


class MediaIndexStrategy(ConversionStrategy):
    """媒体索引策略 - 保留原始媒体的文本索引（原 AiNativeStrategy，去 AI 探测后更名）"""

    def __init__(self):
        super().__init__()
        self.strategy_id = "media_index"
        self.strategy_name = "媒体索引格式"
        self.description = "保留原始媒体文件，同时提取文本索引供模型快速了解结构"
        self.supported_types = [FileType.PDF, FileType.PPT, FileType.IMAGE]

    def can_handle(self, parsed_file: ParsedFile, ai_caps: Any = None) -> float:
        # 无内置 AI 客户端：仅当文件含图片时提供中等优先级的索引方案
        if any(page.hasImage for page in parsed_file.pages):
            return 0.6
        return 0.1

    def convert(
        self,
        parsed_file: ParsedFile,
        output_format: OutputFormat,
        ai_caps: Any = None,
        custom_prompt: str | None = None,
    ) -> dict[str, Any]:
        logs = [create_processing_log("media_index", "生成媒体索引（保留媒体+文本索引）")]
        logger.info(
            "[strategy=media_index] 生成媒体索引: file=%s, pages=%d", parsed_file.fileName, parsed_file.pageCount
        )

        # 提取文本索引
        text_index = []
        for page in parsed_file.pages:
            page_summary = {
                "page": page.pageNumber,
                "text_preview": page.rawText[:200] if page.rawText else "",
                "has_image": page.hasImage,
                "has_table": page.hasTable,
                "elements": [{"type": e.elementType, "content": e.content[:100]} for e in page.elements[:5]],
            }
            text_index.append(page_summary)

        content = f"""# 媒体索引格式数据

## 文件信息
- 文件名: {parsed_file.fileName}
- 页数: {parsed_file.pageCount}
- 类型: {parsed_file.fileType.value}

## 内容索引

{json.dumps(text_index, ensure_ascii=False, indent=2)}

## 说明
此文件包含媒体内容，建议将原始文件直接发送给AI进行处理。
上述索引可用于快速了解文件内容结构。
"""

        logger.info("[strategy=media_index] 索引生成完成: index_pages=%d", len(text_index))
        logs.append(create_processing_log("media_index", f"生成索引，共 {len(text_index)} 页"))

        return {
            "content": content,
            "structured_data": {
                "type": "media_index",
                "pages": text_index,
                "recommendation": "保留原始文件直接发送给模型",
            },
            "confidence": 0.9,
            "logs": logs,
        }


# ==================== 策略注册表 ====================


class StrategyRegistry:
    """策略注册表 - 管理所有可用策略"""

    def __init__(self):
        self._strategies: dict[str, ConversionStrategy] = {}
        self._register_default_strategies()

    def _register_default_strategies(self):
        """注册默认策略"""
        strategies = [
            AutoDetectStrategy(),
            TextExtractionStrategy(),
            StructuredExtractionStrategy(),
            TableExtractionStrategy(),
            ImageDescriptionStrategy(),
            OcrStrategy(),
            MediaIndexStrategy(),
        ]
        for s in strategies:
            self._strategies[s.strategy_id] = s
        logger.info("策略注册表初始化完成，共 %d 个策略", len(self._strategies))

    def get_strategy(self, strategy_id: str) -> ConversionStrategy | None:
        """获取指定策略"""
        strategy = self._strategies.get(strategy_id)
        if strategy is None:
            logger.warning("请求未知策略: %s", strategy_id)
        return strategy

    def get_all_strategies(self) -> list[ConversionStrategy]:
        """获取所有策略"""
        return list(self._strategies.values())

    def select_best_strategy(
        self, parsed_file: ParsedFile, conversion_type: ConversionType, ai_caps: Any = None
    ) -> ConversionStrategy:
        """
        选择最佳策略
        1. 如果指定了具体转换类型，选择对应策略
        2. 否则根据 can_handle 评分选择
        3. 考虑AI能力进行决策
        """
        logger.debug(
            "选择最佳策略: file_type=%s, conversion_type=%s, has_ai_caps=%s",
            parsed_file.fileType.value,
            conversion_type.value,
            bool(ai_caps),
        )

        type_to_strategy = {
            ConversionType.TEXT: "text_extraction",
            ConversionType.STRUCTURED: "structured_extraction",
            ConversionType.TABLE: "table_extraction",
            ConversionType.IMAGE_DESC: "image_description",
            ConversionType.OCR: "ocr",
            ConversionType.ENCODING: "text_extraction",
        }

        if conversion_type != ConversionType.AUTO:
            strategy_id = type_to_strategy.get(conversion_type)
            if strategy_id and strategy_id in self._strategies:
                logger.info("按指定类型选择策略: conversion_type=%s -> strategy=%s", conversion_type.value, strategy_id)
                return self._strategies[strategy_id]

        # 自动选择：评分最高的策略
        scores = []
        for sid, strategy in self._strategies.items():
            if sid == "auto_detect":
                continue
            score = strategy.can_handle(parsed_file, ai_caps)
            scores.append((sid, score))
            logger.debug("策略评分: %s -> %.2f", sid, score)

        scores.sort(key=lambda x: x[1], reverse=True)

        if scores:
            best_id = scores[0][0]
            best_score = scores[0][1]
            logger.info("自动选择最佳策略: %s (score=%.2f)", best_id, best_score)
            return self._strategies[best_id]

        logger.warning("未找到合适策略，回退到文本提取")
        return self._strategies.get("text_extraction", TextExtractionStrategy())


# 全局策略注册表
strategy_registry = StrategyRegistry()
