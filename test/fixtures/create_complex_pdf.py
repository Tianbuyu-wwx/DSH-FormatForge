"""
创建包含复杂表格和图表的 PDF 测试文件
用于验证 PDF 解析器的实际效果
"""
import os
import sys
from pathlib import Path

# 确保项目根目录在路径中
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    Image, PageBreak, ListFlowable, ListItem
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics import renderPDF

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def create_matplotlib_charts(output_dir: Path):
    """使用 matplotlib 创建图表并保存为图片"""
    charts = {}

    # 1. 柱状图 - 季度销售额
    fig, ax = plt.subplots(figsize=(6, 4))
    quarters = ['Q1', 'Q2', 'Q3', 'Q4']
    sales_2023 = [120, 150, 180, 200]
    sales_2024 = [140, 170, 210, 230]
    x = np.arange(len(quarters))
    width = 0.35
    ax.bar(x - width/2, sales_2023, width, label='2023', color='#5B9BD5')
    ax.bar(x + width/2, sales_2024, width, label='2024', color='#ED7D31')
    ax.set_xlabel('季度')
    ax.set_ylabel('销售额 (万元)')
    ax.set_title('季度销售额对比')
    ax.set_xticks(x)
    ax.set_xticklabels(quarters)
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    chart_path = output_dir / 'chart_bar.png'
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close()
    charts['bar'] = chart_path

    # 2. 折线图 - 用户增长趋势
    fig, ax = plt.subplots(figsize=(6, 4))
    months = ['1月', '2月', '3月', '4月', '5月', '6月']
    users = [1000, 1500, 2200, 3000, 4500, 6000]
    ax.plot(months, users, marker='o', linewidth=2, markersize=8, color='#70AD47')
    ax.fill_between(months, users, alpha=0.3, color='#70AD47')
    ax.set_xlabel('月份')
    ax.set_ylabel('用户数')
    ax.set_title('2024年上半年用户增长趋势')
    ax.grid(True, alpha=0.3)
    for i, v in enumerate(users):
        ax.text(i, v + 200, str(v), ha='center', va='bottom', fontsize=9)
    plt.tight_layout()
    chart_path = output_dir / 'chart_line.png'
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close()
    charts['line'] = chart_path

    # 3. 饼图 - 市场份额
    fig, ax = plt.subplots(figsize=(5, 5))
    labels = ['产品A', '产品B', '产品C', '产品D', '其他']
    sizes = [35, 25, 20, 15, 5]
    colors_pie = ['#5B9BD5', '#ED7D31', '#70AD47', '#FFC000', '#4472C4']
    explode = (0.05, 0, 0, 0, 0)
    ax.pie(sizes, explode=explode, labels=labels, colors=colors_pie,
           autopct='%1.1f%%', shadow=True, startangle=90)
    ax.set_title('产品市场份额分布')
    plt.tight_layout()
    chart_path = output_dir / 'chart_pie.png'
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close()
    charts['pie'] = chart_path

    # 4. 热力图 - 区域销售数据
    fig, ax = plt.subplots(figsize=(6, 5))
    regions = ['华北', '华东', '华南', '华中', '西南', '西北']
    products = ['产品A', '产品B', '产品C', '产品D']
    data = np.array([
        [85, 92, 78, 65],
        [95, 88, 82, 70],
        [90, 85, 88, 75],
        [75, 80, 85, 90],
        [70, 75, 80, 85],
        [65, 70, 75, 80]
    ])
    im = ax.imshow(data, cmap='YlOrRd', aspect='auto')
    ax.set_xticks(np.arange(len(products)))
    ax.set_yticks(np.arange(len(regions)))
    ax.set_xticklabels(products)
    ax.set_yticklabels(regions)
    ax.set_xlabel('产品')
    ax.set_ylabel('区域')
    ax.set_title('区域产品销售热力图')
    # 添加数值标注
    for i in range(len(regions)):
        for j in range(len(products)):
            text = ax.text(j, i, data[i, j], ha="center", va="center", color="black", fontsize=10)
    plt.colorbar(im, ax=ax, label='销售额 (万元)')
    plt.tight_layout()
    chart_path = output_dir / 'chart_heatmap.png'
    plt.savefig(chart_path, dpi=150, bbox_inches='tight')
    plt.close()
    charts['heatmap'] = chart_path

    return charts


def create_complex_pdf(output_path: Path):
    """创建包含复杂表格和图表的 PDF"""

    # 创建输出目录
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    # 创建图表
    print("正在生成图表...")
    charts = create_matplotlib_charts(output_dir)

    # 创建 PDF
    print("正在创建 PDF...")
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    # 样式
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#1F4E79'),
        spaceAfter=20,
        alignment=TA_CENTER
    )
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#2E75B5'),
        spaceAfter=12,
        spaceBefore=12
    )
    body_style = styles['BodyText']
    body_style.fontSize = 10

    story = []

    # ===== 封面 =====
    story.append(Spacer(1, 3*cm))
    story.append(Paragraph("2024年度销售数据分析报告", title_style))
    story.append(Spacer(1, 1*cm))
    story.append(Paragraph("<i>包含复杂表格、图表和多页布局的测试文档</i>",
                          ParagraphStyle('Subtitle', parent=styles['Normal'],
                                       alignment=TA_CENTER, fontSize=12, textColor=colors.grey)))
    story.append(Spacer(1, 2*cm))
    story.append(Paragraph("生成日期: 2024年12月", body_style))
    story.append(Paragraph("文档版本: v1.0", body_style))
    story.append(PageBreak())

    # ===== 第一页：概述 =====
    story.append(Paragraph("一、概述", heading_style))
    story.append(Paragraph(
        "本报告详细分析了2024年度各区域、各产品的销售表现。数据涵盖四个季度，"
        "涉及六个销售区域和四个主要产品类别。通过对销售额、市场份额、用户增长等"
        "关键指标的分析，为2025年的销售策略制定提供数据支持。",
        body_style
    ))
    story.append(Spacer(1, 0.5*cm))

    # 关键指标表格
    story.append(Paragraph("1.1 关键指标概览", styles['Heading3']))
    key_metrics = [
        ['指标', '2023年', '2024年', '同比增长', '完成率'],
        ['总销售额 (万元)', '650', '750', '+15.4%', '100.2%'],
        ['活跃用户', '12,500', '18,000', '+44.0%', '105.3%'],
        ['新客户数', '3,200', '4,500', '+40.6%', '98.7%'],
        ['客户满意度', '4.2/5', '4.5/5', '+7.1%', '102.4%'],
        ['市场份额', '28%', '32%', '+14.3%', '106.7%'],
    ]
    key_table = Table(key_metrics, colWidths=[4*cm, 3*cm, 3*cm, 3*cm, 3*cm])
    key_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F4E79')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F2F2F2')),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#E6F2FF')]),
    ]))
    story.append(key_table)
    story.append(Spacer(1, 0.5*cm))

    # 要点列表
    story.append(Paragraph("1.2 核心发现", styles['Heading3']))
    findings = ListFlowable([
        ListItem(Paragraph("华东区域销售额最高，占总销售额的35%", body_style)),
        ListItem(Paragraph("产品A市场份额稳步增长，从28%提升至32%", body_style)),
        ListItem(Paragraph("用户增长超出预期，上半年新增用户6000人", body_style)),
        ListItem(Paragraph("客户满意度提升至4.5分，达到年度目标", body_style)),
        ListItem(Paragraph("Q4季度销售额创历史新高达230万元", body_style)),
    ], bulletType='bullet', leftIndent=20)
    story.append(findings)
    story.append(PageBreak())

    # ===== 第二页：详细数据表格 =====
    story.append(Paragraph("二、详细销售数据", heading_style))
    story.append(Paragraph(
        "以下表格展示了各区域各产品的详细销售数据，包括销售额、增长率和市场份额。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 复杂数据表格
    sales_data = [
        ['区域', '产品A', '产品B', '产品C', '产品D', '区域合计', '占比'],
        ['华北', '85', '92', '78', '65', '320', '18.3%'],
        ['华东', '95', '88', '82', '70', '335', '19.1%'],
        ['华南', '90', '85', '88', '75', '338', '19.3%'],
        ['华中', '75', '80', '85', '90', '330', '18.8%'],
        ['西南', '70', '75', '80', '85', '310', '17.7%'],
        ['西北', '65', '70', '75', '80', '290', '16.6%'],
        ['产品合计', '480', '490', '488', '465', '1923', '100%'],
        ['平均', '80', '81.7', '81.3', '77.5', '320.5', '-'],
    ]
    sales_table = Table(sales_data, colWidths=[2.5*cm, 2.2*cm, 2.2*cm, 2.2*cm, 2.2*cm, 2.5*cm, 2*cm])
    sales_table.setStyle(TableStyle([
        # 表头样式
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E75B5')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        # 数据行样式
        ('FONTNAME', (0, 1), (0, -3), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (-1, -3), 9),
        ('GRID', (0, 0), (-1, -3), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -3), [colors.white, colors.HexColor('#E6F2FF')]),
        # 合计行样式
        ('BACKGROUND', (0, -2), (-1, -2), colors.HexColor('#D9E2F3')),
        ('FONTNAME', (0, -2), (-1, -2), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, -2), (-1, -2), colors.HexColor('#1F4E79')),
        # 平均行样式
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#F2F2F2')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Oblique'),
        ('GRID', (0, -2), (-1, -1), 0.5, colors.grey),
    ]))
    story.append(sales_table)
    story.append(Spacer(1, 0.5*cm))

    # 季度数据表格
    story.append(Paragraph("2.1 季度销售趋势", styles['Heading3']))
    quarterly_data = [
        ['季度', '销售额(万元)', '环比增长', '同比增长', '目标完成率', '备注'],
        ['Q1', '140', '-', '+16.7%', '93.3%', '春节影响'],
        ['Q2', '170', '+21.4%', '+18.1%', '100.0%', '促销活动'],
        ['Q3', '210', '+23.5%', '+22.1%', '105.0%', '新品发布'],
        ['Q4', '230', '+9.5%', '+15.0%', '115.0%', '年终冲刺'],
        ['全年', '750', '-', '+15.4%', '100.2%', '超额完成'],
    ]
    quarterly_table = Table(quarterly_data, colWidths=[2.5*cm, 3*cm, 2.5*cm, 2.5*cm, 3*cm, 3*cm])
    quarterly_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#5B9BD5')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#E6F2FF')]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#D9E2F3')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]))
    story.append(quarterly_table)
    story.append(PageBreak())

    # ===== 第三页：图表 =====
    story.append(Paragraph("三、数据可视化", heading_style))
    story.append(Paragraph(
        "通过图表直观展示销售数据的关键趋势和分布特征。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 柱状图
    story.append(Paragraph("3.1 季度销售额对比", styles['Heading3']))
    story.append(Image(str(charts['bar']), width=14*cm, height=9*cm))
    story.append(Spacer(1, 0.3*cm))

    # 折线图
    story.append(Paragraph("3.2 用户增长趋势", styles['Heading3']))
    story.append(Image(str(charts['line']), width=14*cm, height=9*cm))
    story.append(PageBreak())

    # ===== 第四页：更多图表 =====
    story.append(Paragraph("3.3 市场份额分布", styles['Heading3']))
    story.append(Image(str(charts['pie']), width=12*cm, height=12*cm))
    story.append(Spacer(1, 0.5*cm))

    story.append(Paragraph("3.4 区域销售热力图", styles['Heading3']))
    story.append(Image(str(charts['heatmap']), width=14*cm, height=11*cm))
    story.append(PageBreak())

    # ===== 第五页：嵌套表格 =====
    story.append(Paragraph("四、复杂嵌套数据", heading_style))
    story.append(Paragraph(
        "以下展示多层嵌套的表格结构，用于测试解析器对复杂表格的处理能力。",
        body_style
    ))
    story.append(Spacer(1, 0.3*cm))

    # 嵌套表格 - 产品明细
    story.append(Paragraph("4.1 产品详细规格", styles['Heading3']))
    product_detail = [
        ['产品名称', '规格参数', '单价(元)', '库存', '状态'],
        ['产品A-标准版', 'CPU: 8核 | 内存: 16GB | 存储: 512GB SSD', '¥2,999', '1,250', '正常'],
        ['产品A-专业版', 'CPU: 16核 | 内存: 32GB | 存储: 1TB SSD', '¥4,999', '850', '正常'],
        ['产品A-企业版', 'CPU: 32核 | 内存: 64GB | 存储: 2TB SSD', '¥8,999', '320', '缺货'],
        ['产品B-基础版', 'CPU: 4核 | 内存: 8GB | 存储: 256GB SSD', '¥1,999', '2,100', '正常'],
        ['产品B-高级版', 'CPU: 8核 | 内存: 16GB | 存储: 512GB SSD', '¥3,499', '980', '正常'],
        ['产品C-入门版', 'CPU: 2核 | 内存: 4GB | 存储: 128GB SSD', '¥999', '3,500', '促销'],
        ['产品C-旗舰版', 'CPU: 16核 | 内存: 32GB | 存储: 1TB SSD', '¥5,999', '450', '正常'],
    ]
    product_table = Table(product_detail, colWidths=[3*cm, 7*cm, 2.5*cm, 2*cm, 2*cm])
    product_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#70AD47')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#E2EFDA')]),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(product_table)
    story.append(Spacer(1, 0.5*cm))

    # 合并单元格表格
    story.append(Paragraph("4.2 部门预算分配", styles['Heading3']))
    budget_data = [
        ['部门', 'Q1', 'Q2', 'Q3', 'Q4', '年度总计'],
        ['研发部', '50', '55', '60', '65', '230'],
        ['市场部', '30', '35', '40', '45', '150'],
        ['销售部', '40', '45', '50', '55', '190'],
        ['运营部', '20', '25', '25', '30', '100'],
        ['总计', '140', '160', '175', '195', '670'],
    ]
    budget_table = Table(budget_data, colWidths=[3*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm, 3*cm])
    budget_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#ED7D31')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -2), [colors.white, colors.HexColor('#FCE4D6')]),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#F4B084')),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
    ]))
    story.append(budget_table)
    story.append(Spacer(1, 0.5*cm))

    # 结论
    story.append(Paragraph("五、结论与建议", heading_style))
    story.append(Paragraph(
        "基于以上数据分析，2024年度整体销售表现良好，超额完成年度目标。"
        "建议2025年继续加强华东和华南区域的市场投入，同时关注产品A企业版的库存管理。"
        "用户增长势头强劲，建议加大获客渠道的多元化布局。",
        body_style
    ))

    # 生成 PDF
    doc.build(story)
    print(f"PDF 创建成功: {output_path}")
    print(f"文件大小: {output_path.stat().st_size / 1024:.1f} KB")

    # 清理临时图表文件
    for chart_path in charts.values():
        if chart_path.exists():
            chart_path.unlink()
            print(f"已清理临时文件: {chart_path.name}")

    return output_path


if __name__ == '__main__':
    output_dir = Path(__file__).parent
    output_path = output_dir / 'complex_test.pdf'
    create_complex_pdf(output_path)
