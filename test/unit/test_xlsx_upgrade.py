"""EVOLUTION_PLAN E3 —— xlsx 表格抽取升级测试（多 sheet / 合并单元格 / 类型保真）。"""

import pytest

openpyxl = pytest.importorskip("openpyxl")

from pathlib import Path

from parsers.xlsx_parser import XLSXParser


def _make_workbook(tmp_path: Path):
    """构造：2 个 sheet + 合并单元格 + 前导零编号列。"""
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "销售明细"
    ws1.append(["订单号", "客户", "金额"])
    ws1.append(["001", "甲", 100])
    ws1.append(["002A", "乙", 200])

    ws2 = wb["Sheet2"] if "Sheet2" in wb.sheetnames else wb.create_sheet("汇总")
    ws2.title = "汇总"
    ws2.append(["区域", "Q1"])
    ws2.append(["华东", 500])

    # 合并单元格：B3:C3（在明细表追加一行做合并演示）
    ws1.append(["003", None, None])  # row4
    ws1.merge_cells("C4:D4") if False else ws1.merge_cells("B4:C4")
    ws1.cell(row=4, column=2).value = "丙（合并值）"

    path = tmp_path / "multi.xlsx"
    wb.save(path)
    return path


@pytest.fixture()
def parsed(tmp_path):
    p = XLSXParser()
    return p.parse(_make_workbook(tmp_path))


class TestXlsxUpgrade:
    def test_multi_sheet_all_extracted(self, parsed):
        raw = parsed[0].rawText
        assert "[Sheet: 销售明细]" in raw
        assert "[Sheet: 汇总]" in raw

    def test_sheet_name_as_anchor(self, parsed):
        tables = [e for e in parsed[0].elements if e.elementType == "table"]
        anchors = [e.content for e in tables if e.content.startswith("## Sheet:")]
        assert len(anchors) == 2

    def test_markdown_separator_row(self, parsed):
        raw = parsed[0].rawText
        assert "|---|" in raw or "| ---" in raw.replace(" ", "")

    def test_merged_cell_filled(self, parsed):
        raw = parsed[0].rawText
        # 合并区 B4:C4 的左上值应填充到 C 列
        line = [ln for ln in raw.splitlines() if "003" in ln]
        assert len(line) == 1
        assert "丙（合并值）" in line[0]

    def test_leading_zero_preserved(self, parsed):
        raw = parsed[0].rawText
        # 订单号 001 不应被数字化成 1
        assert "| 001 |" in raw

    def test_metadata_has_merged_count(self, parsed):
        tables = [e for e in parsed[0].elements if e.elementType == "table"]
        detail = next(e for e in tables if e.metadata.get("sheet_name") == "销售明细")
        assert detail.metadata["merged_cells"] >= 1
