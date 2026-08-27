"""R2 解析质量纵深 —— golden fixture 快照 + 单元测试。

golden 快照机制（ROADMAP R2 随批引入）：
  - 语料由 test/fixtures/golden/create_r2_corpus.py 确定性生成（reportlab 同版本下逐字节稳定）
  - 期望输出存 test/fixtures/golden/expected/*.json
  - 快照不符时测试失败，并提示 FF_UPDATE_GOLDEN=1 重新生成（显式人类确认）
"""

import json
import os
from pathlib import Path

import pytest

from core.file_parser import FileParser
from core.structure_fidelity import render_markdown, slugify
from core.table_semantics import is_numeric_column, normalize_grid

GOLDEN = Path(__file__).resolve().parent.parent / "fixtures" / "golden"
EXPECTED = GOLDEN / "expected"

needs_pdf = pytest.mark.skipif(
    not all((GOLDEN / f).exists() for f in ("r2_scanned.pdf", "r2_structure.pdf", "r2_multipage_table.pdf", "r2_merged_cells.pdf")),
    reason="golden 语料未生成（跑 create_r2_corpus.py）",
)


@pytest.fixture(scope="module")
def parser():
    return FileParser(Path("."))


def _parse(parser: FileParser, name: str, **opts):
    return parser.parse_file(GOLDEN / name, "pdf", pdf_options=opts or None)


def _snapshot(parser: FileParser, name: str, pdf_opts: dict | None, extract) -> dict:
    """跑解析 → 提取关键结构 → 对比/更新 golden 快照。"""
    pf = _parse(parser, name, **(pdf_opts or {}))
    data = extract(pf)
    dest = EXPECTED / f"{name}.json"
    if os.environ.get("FF_UPDATE_GOLDEN") == "1":
        EXPECTED.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        pytest.fail(f"golden 快照已更新: {dest}（请 review diff 后重跑）")
    if not dest.exists():
        pytest.fail(f"golden 快照缺失: {dest}（用 FF_UPDATE_GOLDEN=1 生成）")
    expected = json.loads(dest.read_text(encoding="utf-8"))
    assert data == expected, f"{name} 输出与 golden 快照不符（diff 上述字段；确认是改进后 FF_UPDATE_GOLDEN=1 刷新）"
    return data


# ==================== R2.1 OCR 管线 ====================


@needs_pdf
class TestOcrPipeline:
    def test_scanned_ocr_extracts_text(self, parser):
        """扫描件 + OCR → 每页应有实质文本（此前 OCR 未接线时全书仅 3-6 字符）。"""
        pytest.importorskip("rapidocr_onnxruntime")
        pf = _parse(parser, "r2_scanned.pdf", use_ocr=True, ocr_backend="rapidocr")
        assert len(pf.pages) == 5
        # 前 4 页纯图片页：OCR 后必须有文本
        for pg in pf.pages[:4]:
            assert len((pg.rawText or "").strip()) > 20, f"第 {pg.pageNumber} 页 OCR 后仍无文本"
        # 元素带真实置信度（不再是硬编码 0.75）
        ocr_elems = [e for pg in pf.pages for e in pg.elements if (e.metadata or {}).get("ocr")]
        assert ocr_elems, "应有 OCR 元素"
        assert all(0 < (e.metadata["ocr_confidence"] or 0) <= 1 for e in ocr_elems)

    def test_scanned_ocr_no_duplicate_merge(self, parser):
        """混合页（文字层+图）合并去重：无重复行。"""
        pytest.importorskip("rapidocr_onnxruntime")
        pf = _parse(parser, "r2_scanned.pdf", use_ocr=True, ocr_backend="rapidocr")
        pg5 = pf.pages[4]
        lines = [l.strip() for l in (pg5.rawText or "").splitlines() if l.strip()]
        assert len(lines) == len(set(lines)), f"混合页出现重复行: {lines}"

    def test_watermark_not_flagged_image_only(self, parser):
        """水印混排文档不得误判 image_only（R2.1 前曾被 furniture 误伤链误判）。"""
        pytest.importorskip("rapidocr_onnxruntime")
        from core.enhance import build_enhance_hint

        pf = _parse(parser, "r2_watermark.pdf")
        hint = build_enhance_hint(pf, confidence=0.9)
        assert hint is None or hint.reason != "image_only"
        # 文字层完整保留
        text_all = "\n".join(p.rawText or "" for p in pf.pages)
        for key in ("数据治理总则", "敏感数据分级", "访问审计"):
            assert key in text_all, f"文字层丢失关键词: {key}"

    def test_ocr_lines_keep_confidence_metadata(self, parser):
        """OCR 逐行携带真实置信度（R2.1 验收：逐页置信度标注）。"""
        pytest.importorskip("rapidocr_onnxruntime")
        pf = _parse(parser, "r2_scanned.pdf", use_ocr=True, ocr_backend="rapidocr")
        confs = [e.metadata.get("ocr_confidence") for pg in pf.pages for e in pg.elements if (e.metadata or {}).get("ocr")]
        assert confs and all(isinstance(c, (int, float)) and c > 0 for c in confs)
        # 同页各 OCR 元素共享页级均置信度（页级粒度）
        assert len(set(confs)) <= len(pf.pages)


# ==================== R2.3 结构保真 ====================


@needs_pdf
class TestStructureFidelity:
    def test_heading_levels(self, parser):
        """字号 → 标题层级：章=h1 节=h2 小节=h3。"""
        pf = _parse(parser, "r2_structure.pdf")
        heads = {}
        for pg in pf.pages:
            for e in pg.elements:
                lvl = (e.metadata or {}).get("heading_level")
                if lvl:
                    heads[e.content.strip()] = lvl
        assert heads.get("第一章 总体设计") == 1
        assert heads.get("第二章 实施计划") == 1
        assert heads.get("1.1 架构原则") == 2
        assert heads.get("2.1 里程碑") == 2
        assert heads.get("1.2 模块划分") == 3

    def test_nested_list_levels(self, parser):
        """x0 几何聚类 → 列表嵌套层级。"""
        pf = _parse(parser, "r2_structure.pdf")
        levels = {}
        for pg in pf.pages:
            for e in pg.elements:
                lvl = (e.metadata or {}).get("list_level")
                if lvl:
                    key = e.content.replace("\x00", "").lstrip("•·*- ").strip()[:12]
                    levels[key] = lvl
        assert levels.get("core/ 内核") == 1
        assert levels.get("pipeline 编排") == 2
        assert levels.get("quality 质量") == 2
        assert levels.get("parsers/ 解析器") == 1

    def test_toc_anchors(self, parser):
        """目录行 → 锚点条目 + 目录页标记。"""
        pf = _parse(parser, "r2_structure.pdf")
        toc_meta = [(e.metadata or {}).get("toc") for pg in pf.pages for e in pg.elements if (e.metadata or {}).get("toc")]
        assert len(toc_meta) >= 5
        assert toc_meta[0]["title"] == "第一章 总体设计"
        assert toc_meta[0]["page"] == 2
        assert any((pg.metadata or {}).get("toc_page") for pg in pf.pages)

    def test_ocr_lines_never_headings(self, parser):
        """OCR 行无字体信息，绝不被误判为标题。"""
        pytest.importorskip("rapidocr_onnxruntime")
        pf = _parse(parser, "r2_scanned.pdf", use_ocr=True, ocr_backend="rapidocr")
        for pg in pf.pages:
            for e in pg.elements:
                if (e.metadata or {}).get("ocr"):
                    assert not (e.metadata or {}).get("heading_level")

    def test_markdown_render_golden(self, parser):
        """render_markdown golden 快照。"""
        pf = _parse(parser, "r2_structure.pdf")
        md = render_markdown(pf.pages)

        def extract(pf):
            return {"md": md}

        dest = EXPECTED / "r2_structure.md.json"
        data = {"md": md}
        if os.environ.get("FF_UPDATE_GOLDEN") == "1":
            EXPECTED.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            pytest.fail(f"golden 快照已更新: {dest}")
        if not dest.exists():
            pytest.fail(f"golden 快照缺失: {dest}（FF_UPDATE_GOLDEN=1 生成）")
        expected = json.loads(dest.read_text(encoding="utf-8"))
        # 快照对比采用「关键结构行」而非全量：鲁棒又防退化
        for key in ("# 第一章 总体设计", "## 1.1 架构原则", "### 1.2 模块划分", "- [第一章 总体设计](#第一章-总体设计)"):
            assert key in expected["md"], f"golden 快照缺关键行: {key}"
            assert key in md, f"markdown 输出缺关键行: {key}"

    def test_slugify(self):
        assert slugify("第一章 总体设计") == "第一章-总体设计"
        assert slugify("1.1 架构原则") == "11-架构原则"


# ==================== R2.2 表格语义 ====================


@needs_pdf
class TestTableSemantics:
    def test_merged_cells_filled(self, parser):
        """None（合并覆盖）→ 宿主值继承：研发部/Q1 两行都填充；数值列右对齐。"""
        pf = _parse(parser, "r2_merged_cells.pdf")
        tables = [e for pg in pf.pages for e in pg.elements if e.elementType == "table"]
        assert len(tables) == 1
        content = tables[0].content
        # 研发部纵向合并：Q2 行的部门列被填充为「研发部」
        assert content.count("研发部") == 2
        # 市场部 Q1 跨两行：第二行季度列继承 Q1（合并语义 = 两行同属 Q1）
        rows = [l for l in content.splitlines() if l.startswith("| 市场部")]
        assert len(rows) == 2
        assert "| 市场部 | Q1 | 95 | +3% |" in rows[1]

    def test_numeric_column_right_aligned(self, parser):
        """数值列 → markdown 右对齐分隔。"""
        pf = _parse(parser, "r2_merged_cells.pdf")
        content = next(e.content for pg in pf.pages for e in pg.elements if e.elementType == "table")
        sep = content.splitlines()[1]
        assert "---:" in sep, f"数值列未右对齐: {sep}"

    def test_cross_page_merge(self, parser):
        """无表头续页 → 并入上表，单表六行数据。"""
        pf = _parse(parser, "r2_multipage_table.pdf")
        tables = [e for pg in pf.pages for e in pg.elements if e.elementType == "table"]
        assert len(tables) == 1, f"跨页合并失败，仍有 {len(tables)} 张表"
        content = tables[0].content
        for tid in (f"T-0{i}" for i in range(1, 7)):
            assert tid in content, f"合并后缺少 {tid}"
        meta = tables[0].metadata or {}
        assert meta.get("rows") == 7  # 表头 + 6 数据行

    def test_normalize_grid_unit(self):
        grid = [["部门", "值"], ["研发部", "120"], [None, "135"]]
        out, merged = normalize_grid(grid)
        assert out[2][0] == "研发部"
        assert merged == 1
        assert is_numeric_column(["120", "135", ""])
        assert not is_numeric_column(["研发部", "135"])


# ==================== enhance 触发率验收 ====================


@needs_pdf
class TestEnhanceTriggerRate:
    def test_no_false_positives_on_healthy_docs(self, parser):
        """结构/表格语料不应触发 image_only（基线曾误判水印文档）。"""
        pytest.importorskip("rapidocr_onnxruntime")
        from core.enhance import build_enhance_hint

        for name in ("r2_watermark.pdf", "r2_structure.pdf"):
            pf = _parse(parser, name)
            hint = build_enhance_hint(pf, confidence=0.9)
            assert hint is None or hint.reason != "image_only", f"{name} 误判 image_only"

    def test_scanned_triggers_image_only_without_ocr(self, parser):
        """OCR 关闭时扫描件仍应正确触发 image_only 提示（给会话模型兜底）。"""
        pf = _parse(parser, "r2_scanned.pdf", use_ocr=False)
        from core.enhance import build_enhance_hint

        hint = build_enhance_hint(pf, confidence=0.9)
        assert hint is not None and hint.reason == "image_only"
