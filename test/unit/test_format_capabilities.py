"""v0.14.0/B-P0-1: format capabilities 检测单测。"""

from core.format_capabilities import (
    build_format_details,
    detect_capabilities,
    _CAPABILITY_PROBES,
)


class TestCapabilityProbes:
    """capability 检测必须真实反映 parser 代码实现。"""

    def test_pdf_has_furniture_ocr_two_column(self):
        """pdf_parser 实现了 _detect_furniture / _should_use_ocr / _looks_two_column → 必须能检测到。"""
        from parsers.pdf_parser import PDFParser

        caps = detect_capabilities(PDFParser(ocr_engine=None))
        assert "furniture_strip" in caps
        assert "ocr" in caps
        assert "two_column" in caps

    def test_pptx_has_animation_and_notes(self):
        """pptx_parser 实现了 _extract_animations → 必须能检测到。"""
        from parsers.pptx_parser import PPTXParser

        caps = detect_capabilities(PPTXParser())
        assert "animation_order" in caps
        assert "speaker_notes" in caps

    def test_epub_has_chapter_split(self):
        """epub_parser 实现了 _parse_ncx → chapter_split 必须有。"""
        from parsers.epub_parser import EPUBParser

        caps = detect_capabilities(EPUBParser())
        assert "chapter_split" in caps

    def test_xlsx_has_multi_sheet(self):
        """xlsx_parser 有 _parse_xlsx → multi_sheet 必须有。"""
        from parsers.xlsx_parser import XLSXParser

        caps = detect_capabilities(XLSXParser())
        assert "multi_sheet" in caps

    def test_text_parser_has_no_capabilities(self):
        """纯文本解析器没有 _extract_animations 等方法 → capabilities 应为空。"""
        from parsers.txt_parser import TXTParser

        caps = detect_capabilities(TXTParser())
        assert caps == []


class TestBuildFormatDetails:
    """build_format_details 必须与 cmd_formats 输出对齐。"""

    def test_returns_sorted_unique_format_list(self):
        from core.file_parser import FileParser
        from pathlib import Path

        fp = FileParser(upload_dir=Path("./uploads"))
        details = build_format_details(fp.registry)
        formats = [d["format"] for d in details]
        # 排序 + 无重复
        assert formats == sorted(formats)
        assert len(formats) == len(set(formats))

    def test_pdf_has_all_known_capabilities(self):
        from core.file_parser import FileParser
        from pathlib import Path

        fp = FileParser(upload_dir=Path("./uploads"))
        details = build_format_details(fp.registry)
        pdf = next((d for d in details if d["format"] == "pdf"), None)
        assert pdf is not None
        assert "furniture_strip" in pdf["capabilities"]
        assert "ocr" in pdf["capabilities"]
        assert "table" in pdf["capabilities"]
        assert "two_column" in pdf["capabilities"]

    def test_only_real_extmap_formats_included(self):
        """不要冒 cfg/conf/log 等非 DataFormat 的扩展。"""
        from core.file_parser import FileParser
        from pathlib import Path

        fp = FileParser(upload_dir=Path("./uploads"))
        details = build_format_details(fp.registry)
        formats = {d["format"] for d in details}
        # cmd_formats 总共输出 34 种；我们只放有 parser 注册的（约 29）
        assert formats <= {"pdf", "docx", "xlsx", "pptx", "csv", "txt", "epub", "html",
                          "json", "yaml", "xml", "toml", "sql", "odt", "ods", "odp",
                          "eml", "msg", "svg", "png", "jpeg", "gif", "webp", "bmp",
                          "tiff", "zip", "srt", "latex", "audio"}

    def test_capabilities_are_sorted(self):
        """capabilities 列表必须按字母序排列（输出稳定）。"""
        from core.file_parser import FileParser
        from pathlib import Path

        fp = FileParser(upload_dir=Path("./uploads"))
        details = build_format_details(fp.registry)
        for d in details:
            assert d["capabilities"] == sorted(d["capabilities"])


class TestCapabilityProbesRegistry:
    """probe 注册表本身不应漏掉 v0.14.0 已交付的关键能力。"""

    def test_all_probes_non_empty(self):
        """每个 capability 至少配一个 method probe。"""
        for cap_id, probes in _CAPABILITY_PROBES.items():
            assert probes, f"capability {cap_id} 没有任何 probe method"

    def test_probe_method_names_unique(self):
        """同一 method 不应被两个 capability 共用（会语义混淆）。"""
        seen: dict[str, str] = {}
        for cap_id, probes in _CAPABILITY_PROBES.items():
            for m in probes:
                assert m not in seen, (
                    f"method {m} 被 {seen[m]} 和 {cap_id} 共享"
                )
                seen[m] = cap_id
