"""R2.3 结构保真 —— 标题层级还原 / 列表嵌套层级 / 目录页识别与锚点。

数据流：PDFParser 逐行挂 font_size/bold 元数据 → annotate() 按全书字号中位数
推导标题级别（h1-h4）与列表嵌套 → render_markdown() 输出带层级的 Markdown。
OCR 行无字体信息，按正文处理（绝不误判为标题）。
"""

from __future__ import annotations

import re
from typing import Any

#: 行长上限（超过视为正文，即使字号大——防止大字号正文段落误判）
_HEADING_MAX_LEN = 60
#: 字号相对正文中位数的各级阈值
_H1_RATIO, _H2_RATIO, _H3_RATIO = 1.5, 1.22, 1.12
#: 加粗（同字号）视为最低级标题
_H4_BOLD = 4
#: 目录行：标题 + 点线/空格 + 页码
_TOC_LINE = re.compile(r"^(.{2,60}?)[\s·.]{3,}\s*(\d{1,3})\s*$")
#: 目录页判定：命中目录行数下限
_TOC_MIN_LINES = 3

# 说明：\u0000 是部分中文字体（如 SimHei）的 • 项目符号被 pdfplumber 提取后的形态；
# `\d+[.)]` 带 (?!\d) 负向断言——"1.1 架构原则"是编号标题不是列表项
#: 嵌套列表标记（\u0000 = SimHei 等字体的 • 被 pdfplumber 提取后的形态）
_BULLET_CHARS = "•·*-\u0000"
_NEST_BULLET_RE = re.compile(r"^[•·*\-\u0000]\s+(.+)$")
#: 通用列表项：符号/编号/中文序号（`\d+[.)）)](?!\d)` 排除 "1.1 架构原则" 这类编号标题）
_LIST_RE = re.compile(r"^\s*([•·*\-\u0000]|\d+[.)）)](?!\d)|[（(]\d+[）)]|[一二三四五六七八九十]+、)\s+(.*)$")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def slugify(title: str) -> str:
    """GitHub 风格锚点：小写、空白→连字符、去非法字符、保留 CJK。"""
    s = title.strip().lower().replace(" ", "-")
    return re.sub(r"[^\w\u4e00-\u9fff-]", "", s)


def line_font_stats(page: Any) -> list[dict[str, Any]]:
    """提取文本层每个可视行的 (文本, 最大字号, 是否加粗, 行首 x0)。

    使用 pdfplumber extract_text_lines（≥0.10）；失败时返回空列表（全部按正文处理）。
    x0 用于列表嵌套的几何聚类（文本层的行首缩进会被 extract_text 丢弃，坐标不会）。
    """
    out: list[dict[str, Any]] = []
    try:
        lines = page.extract_text_lines() or []
    except Exception:
        return out
    for ln in lines:
        chars = ln.get("chars") or []
        if not chars:
            continue
        size = max((float(c.get("size", 0)) for c in chars), default=0.0)
        bold = any("bold" in str(c.get("fontname", "")).lower() for c in chars)
        out.append(
            {
                "text": _norm(ln.get("text", "")),
                "size": round(size, 2),
                "bold": bold,
                "x0": round(float(ln.get("x0", 0.0)), 1),
            }
        )
    return out


def body_median_size(stats: list[dict[str, Any]]) -> float:
    """正文字号中位数：按字符长度加权的中位数估计（行长越长的字号越可能是正文）。"""
    if not stats:
        return 0.0
    weighted: list[float] = []
    for s in stats:
        n = max(len(s["text"]), 1)
        weighted.extend([s["size"]] * min(n, 40))
    weighted.sort()
    if not weighted:
        return 0.0
    return weighted[len(weighted) // 2]


def heading_level(size: float, bold: bool, body: float) -> int | None:
    """字号/加粗 → 标题级别 1-4；非标题返回 None。"""
    if body <= 0 or size <= 0:
        return None
    ratio = size / body
    if ratio >= _H1_RATIO:
        return 1
    if ratio >= _H2_RATIO:
        return 2
    if ratio >= _H3_RATIO:
        return 3
    if bold and ratio >= 1.0:
        return _H4_BOLD
    return None


def annotate(pages: list[Any]) -> dict[str, int]:
    """就地标注各页元素：heading 级别 / 列表嵌套 / 目录条目。

    返回统计 {"headings": n, "toc_entries": n, "list_items": n}。
    元素须带 metadata.font_size（PDFParser 接线注入）；OCR 行无字体信息，按正文处理。
    """
    n_head = n_toc = n_list = 0
    # 全书正文字号中位数：按行长加权（长行更可能是正文），跨页稳定
    weighted: list[float] = []
    for pg in pages:
        for elem in getattr(pg, "elements", []) or []:
            size = (elem.metadata or {}).get("font_size")
            if size:
                weighted.extend([float(size)] * min(len(elem.content or ""), 40))
    weighted.sort()
    body = weighted[len(weighted) // 2] if weighted else 0.0

    for pg in pages:
        toc_hits = 0
        # 列表几何聚类：x0 → 层级映射（同 x0=兄弟同级；明显右移=子级）
        x0_levels: list[tuple[float, int]] = []
        for elem in getattr(pg, "elements", []) or []:
            meta = elem.metadata or {}
            content = elem.content or ""
            stripped = content.strip()

            # --- 目录行（先于列表：目录行常以 "1.1" 开头，会被列表正则抢先误判）---
            tm = _TOC_LINE.match(stripped)
            if tm:
                toc_hits += 1
                meta["toc"] = {"title": _norm(tm.group(1)), "page": int(tm.group(2))}
                elem.metadata = meta
                n_toc += 1
                continue

            # --- 列表嵌套（不依赖字体，OCR 行也适用）---
            # PDF 文本层行首缩进被 extract_text 丢弃，但坐标不会：按行首 x0 聚类定层级
            m = _LIST_RE.match(content)
            is_bullet = bool(_NEST_BULLET_RE.match(stripped))
            if m or is_bullet:
                x0 = meta.get("line_x0")
                level = 1
                if x0 is not None:
                    for seen_x0, seen_lvl in x0_levels:
                        if x0 > seen_x0 + 6:  # 6pt 容差：明显右移 → 更深一级
                            level = max(level, seen_lvl + 1)
                        elif abs(x0 - seen_x0) <= 6:
                            level = max(level, seen_lvl)
                    x0_levels.append((x0, level))
                    x0_levels.sort()
                meta["list_level"] = min(level, 4)
                elem.metadata = meta
                n_list += 1
                continue
            if stripped:  # 非列表正文行打断 x0 语境（防跨段误配）
                x0_levels = []

            # --- 标题（依赖字体元数据）---
            size = meta.get("font_size")
            if size and len(stripped) <= _HEADING_MAX_LEN and not stripped.endswith(("。", "；", ";", ",")):
                lvl = heading_level(float(size), bool(meta.get("bold")), body)
                if lvl:
                    meta["heading_level"] = lvl
                    elem.elementType = "heading"
                    elem.metadata = meta
                    n_head += 1
                    continue

        # 目录页判定：本页 ≥3 条目录行 → 打页标记
        if toc_hits >= _TOC_MIN_LINES:
            pg.metadata = {**(pg.metadata or {}), "toc_page": True}

    return {"headings": n_head, "toc_entries": n_toc, "list_items": n_list}


def render_markdown(pages: list[Any]) -> str:
    """把带结构元数据的页面渲染成 Markdown（R2.3 输出形态）。

    - heading_level → #*n
    - list_level    → 嵌套 "- "
    - toc           → [标题](#锚点)
    - table         → 内容原样（parser 已产出 Markdown 表格）
    - 其余          → 原文行
    """
    out: list[str] = []
    for pg in pages:
        if (pg.metadata or {}).get("furniture_removed"):
            pass  # 剔除信息只留在 metadata，不影响正文
        for elem in getattr(pg, "elements", []) or []:
            meta = elem.metadata or {}
            content = (elem.content or "").strip()
            if not content:
                continue
            if elem.elementType == "table" or "table_index" in meta:
                out.append(content)
                out.append("")
                continue
            lvl = meta.get("heading_level")
            if lvl:
                out.append(f"{'#' * int(lvl)} {content}")
                out.append("")
                continue
            toc = meta.get("toc")
            if toc:
                out.append(f"- [{toc['title']}](#{slugify(toc['title'])})")
                continue
            ll = meta.get("list_level")
            if ll:
                indent = "  " * (int(ll) - 1)
                m = _LIST_RE.match(elem.content or "")
                body = m.group(2) if m else _NEST_BULLET_RE.sub(r"\1", content)
                out.append(f"{indent}- {body.strip()}")
                continue
            out.append(content)
        out.append("")
    return "\n".join(out).strip() + "\n"
