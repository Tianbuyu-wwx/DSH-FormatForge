"""EVOLUTION_PLAN E2 —— PDF 深度增强单元测试（pages/furniture/双栏）。"""

import pytest

from core.pdf_enhance import (
    detect_furniture,
    is_page_number_line,
    parse_pages_spec,
    reorder_two_columns,
    strip_furniture,
)


class TestParsePagesSpec:
    def test_none_passthrough(self):
        assert parse_pages_spec(None) is None
        assert parse_pages_spec("") is None

    def test_ranges_and_singles(self):
        assert parse_pages_spec("1-3,7") == {1, 2, 3, 7}

    def test_reversed_range(self):
        assert parse_pages_spec("5-3") == {3, 4, 5}

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="pages 参数"):
            parse_pages_spec("abc")
        with pytest.raises(ValueError, match="pages 参数"):
            parse_pages_spec("1-")


class TestPageNumberLine:
    def test_variants(self):
        for s in ["12", "- 12 -", "第 3 页", "第 3 页 / 共 10 页", "Page 7 of 20"]:
            assert is_page_number_line(s), s
        for s in ["正文内容", "1. 引言", "2026 年度报告"]:
            assert not is_page_number_line(s), s


class TestFurniture:
    def _texts(self, header="年度报告 2026", footer="机密文件"):
        # 6 页：前两行是页眉、后两行是页脚，中间是不同正文
        return [
            [header, "目录", f"正文 {i}a", f"正文 {i}b", footer, "12"]
            for i in range(1, 7)
        ]

    def test_detects_repeated_head_tail(self):
        head, tail = detect_furniture(self._texts())
        assert "年度报告 2026" in head
        assert "机密文件" in tail

    def test_skips_small_documents(self):
        texts = self._texts()[:3]  # 只有 3 页
        head, tail = detect_furniture(texts)
        assert head == set()
        assert tail == set()

    def test_strip_removes_and_keeps_body(self):
        texts = self._texts()
        head_set, tail_set = detect_furniture(texts)
        out = strip_furniture(texts[0], index=1, total_pages=6, head_set=head_set, tail_set=tail_set)
        joined = "\n".join(out)
        assert "年度报告" not in joined and "机密" not in joined and "12" != out[-1]
        assert "正文 1a" in joined


def _words_from_rows(rows):
    """把 (top, text) 行转成 pdfplumber extract_words 形状的词列表。"""
    words = []
    for top, line in rows:
        x = 0.0
        for token in line.split():
            words.append({"text": token, "x0": x, "x1": x + len(token) * 5, "top": float(top)})
            x += len(token) * 5 + 8
    return words


class TestTwoColumns:
    def test_none_for_narrow_or_sparse(self):
        # 词太少
        few = _words_from_rows([(100, "hello world foo bar baz qux")])[:6]
        assert reorder_two_columns(lambda: few) is None
        # 单栏横跨中线 → None
        single = _words_from_rows([(100, "a very long single column sentence crossing the middle line here")])
        assert reorder_two_columns(lambda: single) is None

    def test_left_then_right_order(self):
        # 左栏 x≈50 起、右栏 x≈350 起（真实两栏布局）；每栏 15 行
        def col_rows(prefix):
            return [(50 + i * 12, f"{prefix}{i+1} {prefix}栏内容{i+1}") for i in range(15)]

        def words_from(rows, x_base):
            words = []
            for top, line in rows:
                x = x_base
                for token in line.split():
                    words.append({"text": token, "x0": x, "x1": x + len(token) * 5, "top": float(top)})
                    x += len(token) * 5 + 8
            return words

        words = words_from(col_rows("L"), x_base=50) + words_from(col_rows("R"), x_base=350)
        out = reorder_two_columns(lambda: words)
        assert out is not None
        assert out.find("L1") < out.find("R1")
        assert out.find("L15") < out.find("R1")  # 左栏全部读完才进右栏
