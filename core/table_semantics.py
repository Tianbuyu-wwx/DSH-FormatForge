"""R2.2 表格语义还原 —— 跨页续接合并 / 数字列对齐 / 空 vs 合并单元格。

pdfplumber 表格抽取的关键信号：
  cell is None  → 该格被纵向/横向合并覆盖（无边框）→ 填充宿主值并标记 merged
  cell == ''    → 真空单元格（有边框）→ 保留空串
跨页表格：续页表无表头（首行与上表表头相异）且列数一致 → 合并进上一表。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

#: 数值单元格（允许货币符号/千分位/百分号/正负号）
_NUMERIC_RE = re.compile(r"^\s*[-+（(]?[￥$€£]?[\d,，.]+%?\s*[）)]?\s*$")
#: 同列判定为「数值列」所需的最少非空值
_MIN_NUMERIC_CELLS = 2
#: 跨页续接：首行与上一表表头的最小相异度（低于此值视为已有表头，不合并）
_HEADER_SIM_THRESHOLD = 0.55
#: 跨页续接：列数必须一致
_COL_TOLERANCE = 0


def _norm_cell(v: Any) -> str:
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()


def _sim(a: str, b: str) -> float:
    a, b = a.replace(" ", ""), b.replace(" ", "")
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def is_numeric_column(values: list[str]) -> bool:
    """一列是否数值列（全部非空值皆数值，且至少 2 个非空）。"""
    vals = [v for v in values if v]
    if len(vals) < _MIN_NUMERIC_CELLS:
        return False
    return all(_NUMERIC_RE.match(v) for v in vals)


def normalize_grid(grid: list[list[Any]]) -> tuple[list[list[str]], int]:
    """None（合并覆盖）→ 继承上方宿主值；返回 (规范化网格, 合并格数)。

    只做纵向合并填充；横向合并（同一行右侧 None）不属于跨行语义，保留空串。
    """
    out: list[list[str]] = []
    merged = 0
    prev_row: list[str] | None = None
    for row in grid:
        norm = [_norm_cell(c) for c in row]
        if prev_row is not None and len(prev_row) == len(norm):
            for i, v in enumerate(norm):
                if v == "" and row[i] is None and prev_row[i]:
                    norm[i] = prev_row[i]
                    merged += 1
        out.append(norm)
        prev_row = norm
    return out, merged


def render_markdown_table(grid: list[list[str]], title: str | None = None) -> str:
    """网格 → 标准 Markdown 表格：数值列右对齐（---:），其余默认对齐。"""
    if not grid:
        return ""
    width = max(len(r) for r in grid)
    padded = [r + [""] * (width - len(r)) for r in grid]
    header, body = padded[0], padded[1:]

    aligns = []
    for col in range(width):
        values = [row[col] for row in body]
        aligns.append("---:" if is_numeric_column(values) else "---")

    def fmt(row: list[str]) -> str:
        return "| " + " | ".join(c.replace("|", "\\|") for c in row) + " |"

    lines = []
    if title:
        lines.append(f"**{title}**")
        lines.append("")
    lines.append(fmt(header))
    lines.append("| " + " | ".join(aligns) + " |")
    for row in body:
        lines.append(fmt(row))
    return "\n".join(lines)


def merge_cross_page_tables(pages: list[Any]) -> int:
    """跨页表格续接合并（就地修改 pages）。

    判定：当前表首行与上一表表头相异度 < 阈值 且 列数一致（±容差）→ 续表。
    合并后上一表元素更新内容与 metadata；续表元素从页面移除。
    返回合并次数。
    """
    merged_count = 0
    prev: Any = None  # (element, grid)
    for pg in pages:
        kept: list[Any] = []
        for elem in getattr(pg, "elements", []) or []:
            if elem.elementType != "table":
                kept.append(elem)
                continue
            grid = (elem.metadata or {}).get("grid")
            if not grid:
                kept.append(elem)
                prev = None
                continue

            if prev is not None:
                prev_elem, prev_grid = prev
                same_cols = abs(len(grid[0]) - len(prev_grid[0])) <= _COL_TOLERANCE
                first_row = [_norm_cell(c) for c in grid[0]]
                header_sim = _sim(" ".join(first_row), " ".join(prev_grid[0]))
                if same_cols and header_sim < _HEADER_SIM_THRESHOLD:
                    # 无表头续表：首行即数据，整表并入
                    prev_grid.extend([_norm_cell(c) for c in r] for r in grid)
                    prev_elem.metadata["grid"] = prev_grid
                    prev_elem.metadata["merged_pages"] = (
                        prev_elem.metadata.get("merged_pages") or [prev_elem.metadata.get("page")]
                    ) + [(elem.metadata or {}).get("page")]
                    prev_elem.metadata["rows"] = len(prev_grid)
                    prev_elem.content = render_markdown_table(prev_grid, title=prev_elem.metadata.get("title"))
                    merged_count += 1
                    continue  # 丢弃续表元素
                if same_cols and header_sim >= _HEADER_SIM_THRESHOLD and len(grid) > 1:
                    # 重复表头续表：跳过表头行并入其余
                    prev_grid.extend([_norm_cell(c) for c in r] for r in grid[1:])
                    prev_elem.metadata["grid"] = prev_grid
                    prev_elem.metadata["merged_pages"] = (
                        prev_elem.metadata.get("merged_pages") or [prev_elem.metadata.get("page")]
                    ) + [(elem.metadata or {}).get("page")]
                    prev_elem.metadata["rows"] = len(prev_grid)
                    prev_elem.content = render_markdown_table(prev_grid, title=prev_elem.metadata.get("title"))
                    merged_count += 1
                    continue

            norm_grid, _ = normalize_grid(grid)
            kept.append(elem)
            prev = (elem, [r[:] for r in norm_grid])
        pg.elements = kept
    return merged_count


def upgrade_table_elements(pages: list[Any]) -> dict[str, int]:
    """规范化所有表格元素：None 语义填充 + markdown 重渲染（数值列对齐）。

    返回 {"normalized": 处理表数, "merged_cells": 合并格数, "cross_page": 跨页合并次数}。
    """
    n_tables = n_merged = 0
    for pg in pages:
        for elem in getattr(pg, "elements", []) or []:
            if elem.elementType != "table":
                continue
            meta = elem.metadata or {}
            grid = meta.get("grid")
            if grid is None:
                continue
            norm, merged = normalize_grid(grid)
            n_merged += merged
            n_tables += 1
            meta["grid"] = norm
            meta["merged_cells"] = merged
            elem.metadata = meta
            elem.content = render_markdown_table(norm)
    cross = merge_cross_page_tables(pages)
    return {"normalized": n_tables, "merged_cells": n_merged, "cross_page": cross}
