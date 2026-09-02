"""v0.14.0/B-P0-1: 格式能力元数据。

自动从已注册的 parser 类检测 capability，避免静态字典漂移。
设计原则：
  - capability 名称来自 parser 代码里真实存在的私有/公开方法名
  - 检测结果反映"该 parser 实际能干什么"，不是静态声明
  - 用于 ff_formats 工具的 formats/details 字段，让会话模型决定何时该用哪个 format

Capability 列表（机器可读，所有 parser 一致）：
  - furniture_strip: PDF header/footer 剔除
  - two_column: PDF 双栏阅读序重排
  - ocr: 调用 OCR 引擎识别文字
  - table: 表格抽取（语义还原）
  - multi_sheet: 多 sheet 处理（XLSX）
  - schema_inference: 列类型推断（CSV/XLSX）
  - animation_order: PPTX 动画时序
  - speaker_notes: PPTX 讲者备注
  - chapter_split: EPUB 章节拆分 + NCX 标题
  - revision_track: DOCX w:ins/w:del 修订追踪
  - metadata_only: 仅元数据（音频）
  - encoding_override: TXT 编码覆写
  - heading_hierarchy: 字号/加粗 → h1-h4
  - toc_anchor: 目录行 → 锚点
"""

from __future__ import annotations

# method_name → capability_id 映射（唯一的机器可读 ID）
_CAPABILITY_PROBES: dict[str, list[str]] = {
    # PDF 能力（pdf_parser.py）
    "furniture_strip": ["_detect_furniture", "_strip_furniture"],
    "two_column": ["_looks_two_column", "_reorder_two_column"],
    "ocr": ["_should_use_ocr", "_ocr_page"],
    # 跨多个 parser：表格抽取
    "table": ["_extract_table", "extract_tables"],
    # XLSX
    "multi_sheet": ["_parse_xlsx"],  # xlsx_parser 内部按 sheet 遍历
    # XLSX/CSV schema 推断在 conversion_strategies.py，不在 parser 内——此处不写
    # PPTX
    "animation_order": ["_extract_animations"],
    "speaker_notes": ["_parse_slide"],  # 备注是 slide 解析的一部分
    # EPUB
    "chapter_split": ["_parse_ncx"],
    # DOCX
    "revision_track": ["_extract_revisions"],
    # 音频：parser 只有元数据解析（看 name/description 可知）
    # TXT：支持 encoding 覆写（txt_parser 接受 encoding 参数）
}


def _probe_parser(parser_obj: object, methods: list[str]) -> bool:
    """检查 parser 类是否实际实现了给定方法集之一。"""
    return any(hasattr(parser_obj, m) and callable(getattr(parser_obj, m, None)) for m in methods)


def detect_capabilities(parser_obj: object) -> list[str]:
    """对一个 parser 实例，返回它实际拥有的 capabilities 列表。

    返回的 capability id 按字母排序，便于 ff_formats 输出稳定。
    """
    caps: list[str] = []
    for cap_id, probes in _CAPABILITY_PROBES.items():
        if _probe_parser(parser_obj, probes):
            caps.append(cap_id)
    return sorted(caps)


def build_format_details(parser_registry) -> list[dict]:
    """从 ParserRegistry 扫描每个 parser，输出 [{format, capabilities}]。

    format 字段权威来源是 core.format_detector.FormatDetector.EXTENSION_MAP
    （与 cmd_formats 输出对齐——只 34 种对外承诺格式）。
    parser 用 supported_extensions 反查 → 命中 EXTENSION_MAP 就输出。
    """
    from core.format_detector import FormatDetector

    ext_to_format_value: dict[str, str] = {}
    for ext, (fmt, _mime) in FormatDetector.EXTENSION_MAP.items():
        ext_to_format_value[ext] = fmt.value

    seen: dict[str, list[str]] = {}  # fmt_id → merged caps
    for parser in parser_registry.parsers:
        caps = detect_capabilities(parser)
        reported: set[str] = set()
        for ext in getattr(parser, "supported_extensions", []):
            fmt_id = ext_to_format_value.get(ext.lower())
            if fmt_id and fmt_id not in reported:
                # 多 parser 共声明同 format 时（如 .txt 被 TXTParser + MarkdownParser 都声明），
                # 合并 capabilities（去重 + 排序保持稳定输出）
                if fmt_id in seen:
                    seen[fmt_id] = sorted(set(seen[fmt_id] + caps))
                else:
                    seen[fmt_id] = sorted(caps)
                reported.add(fmt_id)
    return [{"format": k, "capabilities": v} for k, v in sorted(seen.items())]
