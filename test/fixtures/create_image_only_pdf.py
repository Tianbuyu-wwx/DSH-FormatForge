"""
创建包含纯图片页的 PDF 测试文件
用于验证 OCR 触发策略

生成三种类型的页面：
1. 纯图片页（无文字层）- 应触发 OCR
2. 文字+图片混合页 - 根据策略决定是否 OCR
3. 纯文字页（有文字层）- 不应触发 OCR
"""
import sys
from pathlib import Path
from io import BytesIO

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from PIL import Image, ImageDraw, ImageFont


def create_text_image(text_lines, width=800, height=1000, bg_color=(255, 255, 255),
                      text_color=(0, 0, 0), font_size=28, title=None):
    """创建包含文字的图片（模拟扫描件）"""
    img = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # 尝试加载中文字体
    font_paths = [
        "C:/Windows/Fonts/simhei.ttf",      # 黑体
        "C:/Windows/Fonts/simsun.ttc",      # 宋体
        "C:/Windows/Fonts/msyh.ttc",        # 微软雅黑
    ]
    font = None
    for fp in font_paths:
        try:
            font = ImageFont.truetype(fp, font_size)
            title_font = ImageFont.truetype(fp, font_size + 8)
            break
        except Exception:
            continue

    if font is None:
        font = ImageFont.load_default()
        title_font = font

    y = 60
    x = 60

    # 绘制标题
    if title:
        draw.text((x, y), title, fill=text_color, font=title_font)
        y += font_size + 30

    # 绘制文字行
    for line in text_lines:
        draw.text((x, y), line, fill=text_color, font=font)
        y += font_size + 15

    return img


def create_table_image(headers, rows, width=800, height=600):
    """创建包含表格的图片"""
    img = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    font_paths = [
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ]
    font = None
    for fp in font_paths:
        try:
            font = ImageFont.truetype(fp, 22)
            header_font = ImageFont.truetype(fp, 24)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
        header_font = font

    # 计算列宽
    col_count = len(headers)
    col_width = (width - 100) // col_count
    row_height = 50
    start_x = 50
    start_y = 50

    # 绘制表头背景
    draw.rectangle([start_x, start_y, width - 50, start_y + row_height],
                   fill=(31, 78, 121))

    # 绘制表头文字
    for i, header in enumerate(headers):
        x = start_x + i * col_width + 10
        y = start_y + 12
        draw.text((x, y), header, fill=(255, 255, 255), font=header_font)

    # 绘制数据行
    for row_idx, row in enumerate(rows):
        y = start_y + (row_idx + 1) * row_height
        # 行背景
        bg = (230, 242, 255) if row_idx % 2 == 0 else (255, 255, 255)
        draw.rectangle([start_x, y, width - 50, y + row_height], fill=bg)

        for col_idx, cell in enumerate(row):
            x = start_x + col_idx * col_width + 10
            draw.text((x, y + 12), str(cell), fill=(0, 0, 0), font=font)

    # 绘制边框
    total_height = start_y + (len(rows) + 1) * row_height
    draw.rectangle([start_x, start_y, width - 50, total_height],
                   outline=(128, 128, 128), width=2)

    # 列分隔线
    for i in range(1, col_count):
        x = start_x + i * col_width
        draw.line([(x, start_y), (x, total_height)], fill=(128, 128, 128), width=1)

    # 行分隔线
    for i in range(1, len(rows) + 2):
        y = start_y + i * row_height
        draw.line([(start_x, y), (width - 50, y)], fill=(128, 128, 128), width=1)

    return img


def create_mixed_content_image(width=800, height=1000):
    """创建文字+图片混合内容的图片"""
    img = Image.new('RGB', (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    font_paths = [
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ]
    font = None
    for fp in font_paths:
        try:
            font = ImageFont.truetype(fp, 24)
            title_font = ImageFont.truetype(fp, 32)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()
        title_font = font

    # 标题
    draw.text((60, 40), "混合内容测试页", fill=(0, 0, 0), font=title_font)

    # 文字段落
    paragraphs = [
        "这是一段测试文字，用于验证 OCR 对混合页面的处理能力。",
        "页面包含文字和图片两种元素。",
        "下方的图表展示了销售数据的可视化结果。",
    ]
    y = 100
    for para in paragraphs:
        draw.text((60, y), para, fill=(0, 0, 0), font=font)
        y += 40

    # 绘制一个简单的柱状图
    chart_y = 280
    chart_height = 300
    chart_width = 600
    bar_width = 80
    gap = 50
    values = [120, 180, 150, 220, 190]
    labels = ['Q1', 'Q2', 'Q3', 'Q4', 'Q5']
    colors_bar = [(91, 155, 213), (237, 125, 49), (112, 173, 71),
                  (255, 192, 0), (68, 114, 196)]

    max_val = max(values)
    for i, (val, label, color) in enumerate(zip(values, labels, colors_bar)):
        bar_height = (val / max_val) * (chart_height - 60)
        x = 80 + i * (bar_width + gap)
        y_bottom = chart_y + chart_height - 40
        y_top = y_bottom - bar_height

        # 绘制柱子
        draw.rectangle([x, y_top, x + bar_width, y_bottom], fill=color, outline=(0, 0, 0))

        # 绘制数值
        draw.text((x + 10, y_top - 25), str(val), fill=(0, 0, 0), font=font)

        # 绘制标签
        draw.text((x + 15, y_bottom + 10), label, fill=(0, 0, 0), font=font)

    # 坐标轴
    draw.line([(60, chart_y + chart_height - 40), (700, chart_y + chart_height - 40)],
              fill=(0, 0, 0), width=2)
    draw.line([(60, chart_y), (60, chart_y + chart_height - 40)],
              fill=(0, 0, 0), width=2)

    # 底部文字
    draw.text((60, chart_y + chart_height + 20),
              "图1：季度销售数据对比", fill=(100, 100, 100), font=font)

    return img


def create_image_only_pdf(output_path: Path):
    """创建包含纯图片页的 PDF"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("正在生成纯图片页 PDF...")

    # 创建临时图片文件
    temp_dir = output_path.parent / "temp_ocr_images"
    temp_dir.mkdir(exist_ok=True)

    # 第1页：纯中文文字图片（模拟扫描文档）
    page1_lines = [
        "第一章 概述",
        "",
        "本文档用于测试 OCR 识别功能。",
        "页面内容为纯图片格式，无文字层。",
        "",
        "关键要点：",
        "• 支持多语言识别",
        "• 支持表格识别",
        "• 支持排版还原",
        "",
        "测试日期：2024年12月",
        "测试人员：自动化测试系统",
    ]
    page1_img = create_text_image(page1_lines, title="OCR 测试文档 - 纯图片页",
                                   width=800, height=1000)
    page1_path = temp_dir / "page1_chinese.png"
    page1_img.save(page1_path, dpi=(200, 200))
    print(f"[OK] 第1页中文图片: {page1_path}")

    # 第2页：纯英文文字图片
    page2_lines = [
        "Chapter 2: Technical Specifications",
        "",
        "This page contains English text only.",
        "It is used to test OCR English recognition.",
        "",
        "Key Features:",
        "- Multi-engine OCR support",
        "- Automatic language detection",
        "- Layout preservation",
        "",
        "Version: 1.0.0",
        "Status: Production Ready",
    ]
    page2_img = create_text_image(page2_lines, title="OCR Test - English Page",
                                   width=800, height=1000, font_size=26)
    page2_path = temp_dir / "page2_english.png"
    page2_img.save(page2_path, dpi=(200, 200))
    print(f"[OK] 第2页英文图片: {page2_path}")

    # 第3页：表格图片
    headers = ["产品", "Q1销量", "Q2销量", "Q3销量", "Q4销量", "总计"]
    rows = [
        ["产品A", "120", "150", "180", "200", "650"],
        ["产品B", "80", "100", "120", "140", "440"],
        ["产品C", "200", "180", "160", "140", "680"],
        ["产品D", "50", "60", "70", "80", "260"],
        ["合计", "450", "490", "530", "560", "2030"],
    ]
    page3_img = create_table_image(headers, rows, width=900, height=500)
    page3_path = temp_dir / "page3_table.png"
    page3_img.save(page3_path, dpi=(200, 200))
    print(f"[OK] 第3页表格图片: {page3_path}")

    # 第4页：混合内容（文字+图表）
    page4_img = create_mixed_content_image(width=800, height=1000)
    page4_path = temp_dir / "page4_mixed.png"
    page4_img.save(page4_path, dpi=(200, 200))
    print(f"[OK] 第4页混合内容图片: {page4_path}")

    # 创建 PDF
    c = canvas.Canvas(str(output_path), pagesize=A4)
    page_width, page_height = A4

    # 第1页：中文
    img_w, img_h = page1_img.size
    scale = min(page_width / img_w, page_height / img_h) * 0.95
    new_w = img_w * scale
    new_h = img_h * scale
    x = (page_width - new_w) / 2
    y = (page_height - new_h) / 2
    c.drawImage(str(page1_path), x, y, width=new_w, height=new_h)
    c.showPage()

    # 第2页：英文
    img_w, img_h = page2_img.size
    scale = min(page_width / img_w, page_height / img_h) * 0.95
    new_w = img_w * scale
    new_h = img_h * scale
    x = (page_width - new_w) / 2
    y = (page_height - new_h) / 2
    c.drawImage(str(page2_path), x, y, width=new_w, height=new_h)
    c.showPage()

    # 第3页：表格
    img_w, img_h = page3_img.size
    scale = min(page_width / img_w, page_height / img_h) * 0.9
    new_w = img_w * scale
    new_h = img_h * scale
    x = (page_width - new_w) / 2
    y = page_height - new_h - 50
    c.drawImage(str(page3_path), x, y, width=new_w, height=new_h)
    c.showPage()

    # 第4页：混合内容
    img_w, img_h = page4_img.size
    scale = min(page_width / img_w, page_height / img_h) * 0.95
    new_w = img_w * scale
    new_h = img_h * scale
    x = (page_width - new_w) / 2
    y = (page_height - new_h) / 2
    c.drawImage(str(page4_path), x, y, width=new_w, height=new_h)
    c.showPage()

    c.save()
    print(f"\n[OK] 纯图片 PDF 创建成功: {output_path}")
    print(f"文件大小: {output_path.stat().st_size / 1024:.1f} KB")
    print(f"共 4 页（全部为纯图片页，无文字层）")

    # 清理临时文件
    for f in temp_dir.iterdir():
        f.unlink()
    temp_dir.rmdir()
    print(f"已清理临时图片文件")

    return output_path


def create_mixed_pdf(output_path: Path):
    """创建文字层+图片混合的 PDF（用于测试混合页策略）"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print("正在生成混合页 PDF...")

    c = canvas.Canvas(str(output_path), pagesize=A4)
    page_width, page_height = A4

    # 第1页：纯文字（有文字层）
    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, page_height - 80, "Page 1: Text Only")
    c.setFont("Helvetica", 12)
    text = c.beginText(50, page_height - 120)
    text.textLines("""
This page contains only text content.
It should NOT trigger OCR because it has a text layer.

The quick brown fox jumps over the lazy dog.
1234567890
!@#$%^&*()
    """)
    c.drawText(text)
    c.showPage()

    # 第2页：纯图片（无文字层）
    temp_dir = output_path.parent / "temp_mixed"
    temp_dir.mkdir(exist_ok=True)

    img = create_text_image(
        ["This is an image-only page.", "No text layer exists.", "OCR should be triggered."],
        title="Image Only Page",
        width=600, height=400
    )
    img_path = temp_dir / "page2.png"
    img.save(img_path)

    img_w, img_h = img.size
    scale = min((page_width - 100) / img_w, (page_height - 100) / img_h)
    c.drawImage(str(img_path), 50, page_height - img_h * scale - 50,
                width=img_w * scale, height=img_h * scale)
    c.showPage()

    # 第3页：文字很少 + 图片（应触发 OCR 补充）
    c.setFont("Helvetica", 10)
    c.drawString(50, page_height - 50, "Page 3")

    img2 = create_text_image(
        ["Additional content in image format.", "This should be recognized by OCR."],
        title="Mixed Content",
        width=500, height=300
    )
    img2_path = temp_dir / "page3.png"
    img2.save(img2_path)

    img_w, img_h = img2.size
    scale = 0.8
    c.drawImage(str(img2_path), 50, 200, width=img_w * scale, height=img_h * scale)
    c.showPage()

    c.save()

    # 清理
    for f in temp_dir.iterdir():
        f.unlink()
    temp_dir.rmdir()

    print(f"\n[OK] 混合页 PDF 创建成功: {output_path}")
    print(f"文件大小: {output_path.stat().st_size / 1024:.1f} KB")
    print(f"共 3 页（1页纯文字 + 1页纯图片 + 1页混合）")

    return output_path


if __name__ == '__main__':
    output_dir = Path(__file__).parent

    # 创建纯图片 PDF
    create_image_only_pdf(output_dir / "image_only_test.pdf")

    print()

    # 创建混合页 PDF
    create_mixed_pdf(output_dir / "mixed_content_test.pdf")
