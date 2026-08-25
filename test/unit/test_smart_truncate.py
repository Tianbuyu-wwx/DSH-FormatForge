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
