"""R2 语料生成器 —— 为 R2.1/R2.2/R2.3 生成 golden fixture 源文件。

产物（test/fixtures/golden/）：
  r2_scanned.pdf          4 页纯图片页（模拟扫描件）→ 应触发 image_only → OCR 接线后应转出正文
  r2_watermark.pdf        3 页：文字层 + 全页背景图（水印混排）→ 不应误判 image_only；R2.1 合并 OCR
  r2_multipage_table.pdf  2 页跨页表格（第 2 页无表头）→ R2.2 表头续接合并
  r2_structure.pdf        标题层级（大字号→小字号）+ 嵌套列表 + 目录页 → R2.3 结构保真
  r2_merged_cells.pdf     含空单元格与合并单元格的表格 → R2.2 语义区分

运行：PYTHONPATH= python -m test.fixtures.golden.create_r2_corpus
（或直接 python test/fixtures/golden/create_r2_corpus.py）
"""

from io import BytesIO
from pathlib import Path
import contextlib

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

HERE = Path(__file__).parent

FONT_PATHS = [
    ("C:/Windows/Fonts/simhei.ttf", "SimHei"),
    ("C:/Windows/Fonts/simsun.ttc", "SimSun"),
    ("C:/Windows/Fonts/msyh.ttc", "MSYaHei"),
]


def _register_font() -> tuple[str, str]:
    for path, name in FONT_PATHS:
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            return name, path
        except Exception:
            continue
    return "Helvetica", ""


FONT_NAME, FONT_PATH = _register_font()


def _pil_font(size: int):
    if FONT_PATH:
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except Exception:
            pass
    return ImageFont.load_default()


def text_to_image(lines: list[str], width=760, height=1000, font_size=26, title: str | None = None) -> Image.Image:
    """把文字行渲染成图片（模拟扫描件页面）。"""
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = 60
    if title:
        draw.text((60, y), title, fill="black", font=_pil_font(font_size + 8))
        y += font_size + 30
    for ln in lines:
        draw.text((60, y), ln, fill="black", font=_pil_font(font_size))
        y += int(font_size * 1.7)
    return img


def _save_png(img: Image.Image) -> str:
    """落盘 PNG 供 reportlab 引用（它不接受 BytesIO），调用方负责删除。"""
    import os
    import tempfile

    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    img.save(tmp, format="PNG")
    return tmp


def _img_to_pdf_page(c: canvas.Canvas, img: Image.Image) -> None:
    """整页贴图（reportlab 需要 on-disk 文件路径，不接受 BytesIO）。"""
    import contextlib
    import os

    tmp = _save_png(img)
    try:
        c.drawImage(tmp, 0, 0, width=A4[0], height=A4[1])
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def make_scanned() -> Path:
    """5 页：前 4 页纯图片扫描件（含表格页与列表页），第 5 页混合页（短文字层+图）专测 OCR 合并去重。"""
    p = HERE / "r2_scanned.pdf"
    c = canvas.Canvas(str(p), pagesize=A4)
    pages = [
        text_to_image(["项目背景与目标", "本项目旨在验证 OCR 管线的端到端质量。", "扫描件解析是文档锻造层最难的场景。"], title="年度技术报告"),
        text_to_image(["第一章 综述", "本章介绍整体架构与实施路径。", "第一周完成基线测量。", "第二周完成质量加固。"], title="目录草案"),
        text_to_image(["指标 | 数值 | 备注", "覆盖率 | 95% | 全量", "准确率 | 92% | 抽样", "召回率 | 88% | 抽样"], title="关键指标"),
        text_to_image(["结论：管线可用。", "建议：持续扩充语料。"], title="总结"),
    ]
    for img in pages:
        _img_to_pdf_page(c, img)
        c.showPage()
    # 第 5 页：混合页 —— 文字层只有一行标题（<20 字符触发 OCR），图中含术语列表，
    # 考察合并去重（OCR 新内容并入、文字层已有行不得重复出现）
    c.setFont(FONT_NAME, 16)
    c.drawString(3 * cm, A4[1] - 4 * cm, "附录")
    _img_to_pdf_page(c, text_to_image(["术语表：", "锻造 Forge：格式到结构化数据的转换", "收件箱 Inbox：产物落盘目录"]))
    c.showPage()
    c.save()
    return p


def _watermark_png() -> Image.Image:
    """浅灰大字水印图。"""
    img = Image.new("RGBA", (500, 700), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in (100, 350, 600):
        d.text((40, y), "内部资料", fill=(200, 200, 200, 90), font=_pil_font(72))
    return img


def make_watermark() -> Path:
    """3 页正常文字层 + 背景水印图。正文逐页唯一（防止 60% furniture 规则误剔），
    断言：有图片的页面不被误判 image_only、不触发多余 OCR、文字层完整保留。"""
    p = HERE / "r2_watermark.pdf"
    c = canvas.Canvas(str(p), pagesize=A4)
    wm = _watermark_png()
    page_bodies = [
        ["第 1 节：数据治理总则", "资产目录需要登记到统一平台。", "元数据每月核对一次。"],
        ["第 2 节：敏感数据分级", "机密级数据必须加密存储。", "导出需要双人复核。"],
        ["第 3 节：访问审计", "所有访问记录保留六个月。", "异常访问实时告警。"],
    ]
    for i, body in enumerate(page_bodies):
        import contextlib
        import os

        tmp = _save_png(wm)
        try:
            c.drawImage(tmp, 2 * cm, 2 * cm, width=A4[0] - 4 * cm, height=A4[1] - 4 * cm, mask="auto")
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
        c.setFont(FONT_NAME, 14)
        y = A4[1] - 120
        for ln in body:
            c.drawString(4 * cm, y, ln)
            y -= 24
        c.showPage()
    c.save()
    return p


def make_multipage_table() -> Path:
    """跨页表格：页 1 表头+3 行，页 2 仅数据行（真·无表头续页）。"""
    p = HERE / "r2_multipage_table.pdf"
    c = canvas.Canvas(str(p), pagesize=A4)
    rows = [["编号", "项目", "负责人", "状态"]]
    for i in range(1, 7):
        rows.append([f"T-{i:02d}", f"任务{i}", f"张三{i % 3}", "进行中" if i % 2 else "已完成"])

    def draw_table(data_rows, y_top, with_header=True):
        t = Table([rows[0]] + data_rows if with_header else data_rows, colWidths=[3 * cm, 5 * cm, 4 * cm, 3 * cm])
        t.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
                    ("FONTSIZE", (0, 0), (-1, -1), 11),
                    ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
                ]
            )
        )
        t.wrapOn(c, A4[0] - 3 * cm, A4[1])
        t.drawOn(c, 1.5 * cm, y_top)

    draw_table(rows[1:4], A4[1] - 5 * cm)
    c.showPage()
    draw_table(rows[4:7], A4[1] - 4 * cm, with_header=False)  # 续页：真·无表头
    c.showPage()
    c.save()
    return p


def make_merged_cells() -> Path:
    """合并/空单元格表格。"""
    p = HERE / "r2_merged_cells.pdf"
    c = canvas.Canvas(str(p), pagesize=A4)
    data = [
        ["部门", "季度", "营收(万)", "同比"],
        ["研发部", "Q1", "120", "+5%"],
        [None, "Q2", "135", "+8%"],  # 部门纵向合并 → 次格为空
        ["市场部", "Q1", "90", "+2%"],
        ["市场部", "", "95", "+3%"],  # 季度合并 → 空串
    ]
    t = Table(data, colWidths=[4 * cm, 3 * cm, 4 * cm, 3 * cm])
    t.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), FONT_NAME),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
                ("SPAN", (0, 1), (0, 2)),  # 研发部 跨两行
                ("SPAN", (1, 3), (1, 4)),  # 市场部季度 Q1 跨两行（第二行画空串）
            ]
        )
    )
    t.wrapOn(c, A4[0] - 4 * cm, A4[1])
    t.drawOn(c, 2 * cm, A4[1] - 9 * cm)
    c.showPage()
    c.save()
    return p


def make_structure() -> Path:
    """标题层级 + 嵌套列表 + 目录页（字号区分层级）。"""
    p = HERE / "r2_structure.pdf"
    c = canvas.Canvas(str(p), pagesize=A4)

    # 第 1 页：目录（章节行 + 页码）
    c.setFont(FONT_NAME, 20)
    c.drawString(4 * cm, A4[1] - 4 * cm, "目录")
    c.setFont(FONT_NAME, 12)
    y = A4[1] - 6 * cm
    for title, page in [("第一章 总体设计", "2"), ("1.1 架构原则", "2"), ("1.2 模块划分", "2"), ("第二章 实施计划", "3"), ("2.1 里程碑", "3")]:
        c.drawString(4 * cm, y, f"{title}{'.' * 40} {page}")
        y -= 22
    c.showPage()

    # 第 2 页：h1 + h2 + 正文 + 嵌套列表
    c.setFont(FONT_NAME, 22)
    c.drawString(3 * cm, A4[1] - 4 * cm, "第一章 总体设计")
    c.setFont(FONT_NAME, 16)
    c.drawString(3.5 * cm, A4[1] - 6 * cm, "1.1 架构原则")
    c.setFont(FONT_NAME, 11)
    y = A4[1] - 8 * cm
    for ln in ("系统采用分层架构，内核与插件壳分离。", "所有转换走统一协议 JSON。"):
        c.drawString(3.5 * cm, y, ln)
        y -= 20
    c.setFont(FONT_NAME, 14)
    c.drawString(3.5 * cm, y - 4, "1.2 模块划分")
    y -= 30
    c.setFont(FONT_NAME, 11)
    # 嵌套层级用真实缩进（x0 差 ~0.8cm）表达：子项比父项右移
    for ln, x in (
        ("• core/ 内核", 4 * cm),
        ("- pipeline 编排", 4.8 * cm),
        ("- quality 质量", 4.8 * cm),
        ("• parsers/ 解析器", 4 * cm),
        ("• packages/ 插件壳", 4 * cm),
    ):
        c.drawString(x, y, ln)
        y -= 18
    c.showPage()

    # 第 3 页：另一组标题
    c.setFont(FONT_NAME, 22)
    c.drawString(3 * cm, A4[1] - 4 * cm, "第二章 实施计划")
    c.setFont(FONT_NAME, 16)
    c.drawString(3.5 * cm, A4[1] - 6 * cm, "2.1 里程碑")
    c.setFont(FONT_NAME, 11)
    y = A4[1] - 8 * cm
    for ln in ("M1: OCR 管线（第 1 周）", "M2: 表格语义（第 2 周）", "M3: 结构保真（第 3 周）"):
        c.drawString(3.5 * cm, y, ln)
        y -= 20
    c.showPage()
    c.save()
    return p


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    for fn in (make_scanned, make_watermark, make_multipage_table, make_merged_cells, make_structure):
        p = fn()
        print("created", p.name, p.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
