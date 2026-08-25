r"""PDF 深度增强（EVOLUTION_PLAN E2 / 第三批）。

三个能力，全部在 pdf_parser 层实现、由解析选项控制：
  1. 页选择   —— parse_pages("1-3,7") 解析为页码集合
  2. furniture 剔除 —— 跨页重复的页首/页尾行（页眉/页脚）识别与剔除
  3. 双栏阅读序 —— 宽版面两栏文本按「左栏全读再右栏」重排

furniture 判定规则：
  - 仅统计 ≥4 页文档（样本不足不做判断）
  - 行出现在 ≥60% 页面的前 2 行或后 2 行位置 → 视为页眉/页脚
  - 纯页码行（^\d+$ / 第 x 页 / page x of y）无条件视为页脚
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import Any

logger = logging.getLogger(__name__)

#: 启用 furniture 统计的最小页数
FURNITURE_MIN_PAGES = 4
#: 行被视为「跨页重复」的出现比例阈值
FURNITURE_RATIO = 0.6
#: 参与页眉判定的页首行数 / 页尾行数
HEAD_LINES = 2
TAIL_LINES = 2

_PAGE_NO_PATTERNS = [
    re.compile(r"^\s*\d+\s*$"),
    re.compile(r"^\s*[-—–]?\s*\d+\s*[-—–]?\s*$"),
    re.compile(r"^\s*第\s*\d+\s*页(\s*(?:[共/]|of\s*)\s*\d+\s*页?)?\s*$"),
    re.compile(r"^\s*第\s*\d+\s*页\s*/\s*共\s*\d+\s*页\s*$"),
    re.compile(r"^\s*page\s+\d+(\s+of\s+\d+)?\s*$", re.IGNORECASE),
]


def parse_pages_spec(spec: str | None) -> set[int] | None:
    """把 "1-3,7" 解析为 {1,2,3,7}；None/空 返回 None（表示不过滤）。"""
    if not spec or not spec.strip():
        return None
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                raise ValueError(f"pages 参数格式错误: {part!r}（示例：1-3,7）") from None
            if lo > hi:
                lo, hi = hi, lo
            pages.update(range(lo, hi + 1))
        else:
            try:
                pages.add(int(part))
            except ValueError:
                raise ValueError(f"pages 参数格式错误: {part!r}") from None
    return pages or None


def is_page_number_line(line: str) -> bool:
    """纯页码/页脚行判定。"""
    return any(p.match(line) for p in _PAGE_NO_PATTERNS)


def detect_furniture(texts_by_page: list[list[str]]) -> tuple[set[str], set[str]]:
    """从每页行列表中检测页眉行集合与页脚行集合。

    返回 (head_furniture, tail_furniture)——元素是去空白后的行文本。
    """
    heads: dict[str, int] = {}
    tails: dict[str, int] = {}
    total = len(texts_by_page)
    if total < FURNITURE_MIN_PAGES:
        return set(), set()

    threshold = max(2, int(total * FURNITURE_RATIO))
    for lines in texts_by_page:
        cleaned = [ln.strip() for ln in lines if ln.strip()]
        for ln in cleaned[:HEAD_LINES]:
            heads[ln] = heads.get(ln, 0) + 1
        for ln in cleaned[-TAIL_LINES:]:
            tails[ln] = tails.get(ln, 0) + 1

    head_furniture = {ln for ln, n in heads.items() if n >= threshold}
    tail_furniture = {ln for ln, n in tails.items() if n >= threshold}
    # 纯页码行无条件剔除
    tail_furniture |= {ln for ln in list(tail_furniture) if is_page_number_line(ln)}
    logger.info(
        "[pdf-enhance] furniture 检测: %d 页, 页眉候选=%d, 页脚候选=%d",
        total,
        len(head_furniture),
        len(tail_furniture),
    )
    return head_furniture, tail_furniture


def strip_furniture(
    lines: list[str], index: int, total_pages: int, head_set: set[str], tail_set: set[str]
) -> list[str]:
    """对单页行列表执行 furniture 剔除；返回新列表。"""
    cleaned = [ln.rstrip() for ln in lines]
    # 头部：跳过空行后连续匹配 head_set 的行
    out_head = 0
    seen = 0
    i = 0
    while i < len(cleaned) and seen < HEAD_LINES + 1:
        ln = cleaned[i].strip()
        if ln:
            if ln in head_set and is_page_number_line(ln) is False:
                out_head += 1
                i += 1
                seen += 1
                continue
            break
        i += 1

    # 尾部：同理
    out_tail = 0
    j = len(cleaned) - 1
    seen = 0
    while j >= 0 and seen < TAIL_LINES + 1:
        ln = cleaned[j].strip()
        if ln:
            if ln in tail_set or is_page_number_line(ln):
                out_tail += 1
                j -= 1
                seen += 1
                continue
            break
        j -= 1

    result = cleaned[i : j + 1] if out_head + out_tail > 0 else cleaned
    if out_head + out_tail > 0:
        logger.debug(
            "[pdf-enhance] p%d/%d 剔除 furniture: 头 %d 行 + 尾 %d 行",
            index,
            total_pages,
            out_head,
            out_tail,
        )
    return result


def reorder_two_columns(extract_words_fn: Any, tolerance: float = 3.0) -> str | None:
    """双栏阅读序还原：按词框 x 坐标聚类分栏后「先左栏后右栏」拼接。

    extract_words_fn: pdfplumber page.extract_words 的无参调用（便于测试注入）。
    仅当页面为宽版且明显存在两列分布时返回重排文本；否则返回 None（走默认提取）。
    """
    try:
        words = extract_words_fn() or []
    except Exception:
        return None
    if len(words) < 20:
        return None

    xs0 = sorted(w["x0"] for w in words)
    mid = (xs0[0] + xs0[-1]) / 2
    # 中线附近 ±tolerance 内有词横跨中线 → 不是双栏
    spanning = [w for w in words if w["x0"] < mid - tolerance and w["x1"] > mid + tolerance]
    left_count = sum(1 for w in words if w["x1"] <= mid)
    right_count = sum(1 for w in words if w["x0"] >= mid)
    if len(spanning) > len(words) * 0.02 or min(left_count, right_count) < len(words) * 0.25:
        return None

    def col_text(words_in_col: Iterable[Any]) -> list[str]:
        rows: dict[int, list[str]] = {}
        for w in words_in_col:
            top = round(w["top"])
            key = next((k for k in rows if abs(k - top) <= tolerance), top)
            rows.setdefault(key, []).append(w["text"])
        return [" ".join(rows[k]) for k in sorted(rows)]

    left = [w for w in words if w["x1"] <= mid]
    right = [w for w in words if w["x0"] >= mid]
    text = "\n".join(col_text(left) + ["\n"] + col_text(right))
    return text
