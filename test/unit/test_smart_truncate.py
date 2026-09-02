"""EVOLUTION_PLAN E1 —— smart_truncate 结构化截断的单元测试。"""

from core.utils import smart_truncate


TEXT = (
    "para1 line\npara1 line2\n\n## Table\n| a | b |\n| c | d |\n\ntail content"
)


class TestSmartTruncate:
    def test_returns_all_when_short(self):
        chunk, nxt = smart_truncate("short", 100)
        assert chunk == "short"
        assert nxt is None

    def test_empty_beyond_end(self):
        assert smart_truncate("abc", 10, start=3) == ("", None)
        assert smart_truncate("abc", 10, start=99) == ("", None)

    def test_prefers_paragraph_boundary(self):
        # 窗口 40 内有段落边界（line2 后的 \n\n），应切在那里
        chunk, nxt = smart_truncate(TEXT, 40)
        assert chunk.endswith("line2")
        assert TEXT[nxt:].startswith("## Table")

    def test_falls_back_to_line_boundary(self):
        text = "aaaa\nbbbb\ncccc\ndddd"
        chunk, nxt = smart_truncate(text, 10)
        # 无段落边界时按行切割：'aaaa\nbbbb'（10 字符窗口内最后行界）
        assert chunk == "aaaa\nbbbb"
        assert nxt == 10

    def test_hard_cut_for_overlong_single_line(self):
        text = "x" * 200
        chunk, nxt = smart_truncate(text, 50)
        assert len(chunk) == 50
        assert nxt == 50

    def test_roundtrip_lossless(self):
        parts, off = [], 0
        while True:
            c, n = smart_truncate(TEXT, 25, off)
            parts.append(c)
            if n is None:
                break
            off = n
        import re

        norm = lambda s: re.sub(r"\n+", "\n", s).strip()
        joined = "\n".join(parts)
        assert norm(TEXT) == norm(joined)

    def test_last_page_has_none(self):
        off = 0
        result = None
        while True:
            result = smart_truncate(TEXT, 30, off)
            if result[1] is None:
                break
            off = result[1]
        assert result[0].endswith("tail content")

    def test_multi_file_separator_protects_file_boundary(self):
        """v0.14.0/B-P1-7: --- 多文件分隔符优先级高于段落，
        防止多文件拼接 markdown 在文件标题中间被切断。"""
        multi = (
            "## 文件: a.md\n\n短内容\n\n---\n\n"
            "## 文件: b.md\n\n更长的内容段落 1\n更长的内容段落 2\n\n"
            "## 文件: c.md\n\n第三段很长很长很长很长很长很长很长的内容"
        )
        # cap=80 强制截断（total 长度 > 80）；cut 必须在 --- 之前
        chunk, nxt = smart_truncate(multi, 80)
        # chunk 不应越过 --- 进入 b.md
        assert "## 文件: b.md" not in chunk, f"chunk 越过了 --- 边界: {chunk!r}"
        # --- 分隔符本身也被切掉（避免 chunk 末尾留 --- 显得不完整）
        # 但 ## 文件: a.md 必须完整保留
        assert "## 文件: a.md" in chunk
        # 下一段从 b.md 开始
        assert nxt is not None
        assert multi[nxt:].startswith("## 文件: b.md")

    def test_no_separator_falls_back_to_paragraph(self):
        """v0.14.0/B-P1-7: 无 --- 分隔符时回退段落边界（与 v0.13.0 一致）。"""
        text = "## 文件: a.md\n\n短内容段落"
        chunk, nxt = smart_truncate(text, 30)
        assert "## 文件: a.md" in chunk
        # 段落边界\n        assert chunk.endswith("## 文件: a.md")
