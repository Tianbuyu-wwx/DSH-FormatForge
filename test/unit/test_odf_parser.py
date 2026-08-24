"""
ODF 解析器单元测试
使用 zipfile + xml.etree 动态构建有效的 ODF 测试文件
"""
import sys
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.odf_parser import ODFParser


def _make_odf_skeleton(mimetype: str, content_xml: str) -> bytes:
    """构建一个最小的有效 ODF 文件字节"""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype 必须为第一个条目且不压缩（ODF 规范要求）
        zf.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
        zf.writestr("content.xml", content_xml)
        zf.writestr("META-INF/manifest.xml", """<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
                   manifest:version="1.2">
  <manifest:file-entry manifest:full-path="/" manifest:version="1.2" manifest:media-type="application/vnd.oasis.opendocument.text"/>
  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
</manifest:manifest>""")
    return buf.getvalue()


def _make_content_xml(body_content: str, office_type: str = "text") -> str:
    """构建 content.xml"""
    ns = 'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    ns += 'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    ns += 'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    ns += 'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    ns += 'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    ns += 'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    ns += 'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
    ns += 'xmlns:xlink="http://www.w3.org/1999/xlink"'
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<office:document {ns} office:version="1.2">
  <office:body>
    <office:{office_type}>
      {body_content}
    </office:{office_type}>
  </office:body>
</office:document>"""


class TestODFParserBasic:
    """基础测试"""

    def test_supported_extensions(self):
        parser = ODFParser()
        assert ".odt" in parser.supported_extensions
        assert ".ods" in parser.supported_extensions
        assert ".odp" in parser.supported_extensions
        assert ".txt" not in parser.supported_extensions

    def test_supported_magic(self):
        parser = ODFParser()
        assert b"PK\x03\x04" in parser.supported_magic

    def test_can_parse_odf(self):
        parser = ODFParser()
        assert parser.can_parse(Path("/tmp/doc.odt")) == 0.9
        assert parser.can_parse(Path("/tmp/sheet.ods")) == 0.9
        assert parser.can_parse(Path("/tmp/pres.odp")) == 0.9

    def test_can_parse_non_odf(self):
        parser = ODFParser()
        assert parser.can_parse(Path("/tmp/test.txt")) == 0.0
        assert parser.can_parse(Path("/tmp/test.pdf")) == 0.0


class TestODTParser:
    """ODT 文本文档解析测试"""

    @pytest.fixture
    def parser(self):
        return ODFParser()

    def _create_odt(self, body_content: str, tmp_path: Path) -> Path:
        """创建临时 ODT 文件"""
        xml = _make_content_xml(body_content, "text")
        data = _make_odf_skeleton("application/vnd.oasis.opendocument.text", xml)
        path = tmp_path / "test.odt"
        path.write_bytes(data)
        return path

    def test_parse_headings(self, parser, tmp_path):
        """解析标题"""
        body = """
            <text:h text:outline-level="1">一级标题</text:h>
            <text:h text:outline-level="2">二级标题</text:h>
            <text:h text:outline-level="3">三级标题</text:h>
        """
        path = self._create_odt(body, tmp_path)
        result = parser.parse(path)
        elements = result[0].elements

        headings = [e for e in elements if e.elementType == "heading"]
        assert len(headings) == 3
        assert headings[0].content == "一级标题"
        assert headings[0].metadata["level"] == 1
        assert headings[1].content == "二级标题"
        assert headings[1].metadata["level"] == 2

    def test_parse_paragraphs(self, parser, tmp_path):
        """解析段落"""
        body = """
            <text:p>第一段文本</text:p>
            <text:p>第二段文本</text:p>
        """
        path = self._create_odt(body, tmp_path)
        result = parser.parse(path)
        texts = [e for e in result[0].elements if e.elementType == "text"]
        assert len(texts) == 2
        assert texts[0].content == "第一段文本"
        assert texts[1].content == "第二段文本"

    def test_parse_list(self, parser, tmp_path):
        """解析列表"""
        body = """
            <text:list>
                <text:list-item><text:p>项目一</text:p></text:list-item>
                <text:list-item><text:p>项目二</text:p></text:list-item>
                <text:list-item><text:p>项目三</text:p></text:list-item>
            </text:list>
        """
        path = self._create_odt(body, tmp_path)
        result = parser.parse(path)
        lists = [e for e in result[0].elements if e.elementType == "list"]
        assert len(lists) == 1
        assert len(lists[0].metadata["items"]) == 3

    def test_parse_table_in_odt(self, parser, tmp_path):
        """解析文档中的表格"""
        body = """
            <table:table>
                <table:table-row>
                    <table:table-cell><text:p>姓名</text:p></table:table-cell>
                    <table:table-cell><text:p>年龄</text:p></table:table-cell>
                </table:table-row>
                <table:table-row>
                    <table:table-cell><text:p>张三</text:p></table:table-cell>
                    <table:table-cell><text:p>25</text:p></table:table-cell>
                </table:table-row>
            </table:table>
        """
        path = self._create_odt(body, tmp_path)
        result = parser.parse(path)
        tables = [e for e in result[0].elements if e.elementType == "table"]
        assert len(tables) == 1

    def test_empty_document(self, parser, tmp_path):
        """解析空文档"""
        body = ""
        path = self._create_odt(body, tmp_path)
        result = parser.parse(path)
        assert len(result) == 1
        assert len(result[0].elements) == 0


class TestODSParser:
    """ODS 表格解析测试"""

    @pytest.fixture
    def parser(self):
        return ODFParser()

    def _create_ods(self, body_content: str, tmp_path: Path) -> Path:
        xml = _make_content_xml(body_content, "spreadsheet")
        data = _make_odf_skeleton("application/vnd.oasis.opendocument.spreadsheet", xml)
        path = tmp_path / "test.ods"
        path.write_bytes(data)
        return path

    def test_parse_single_sheet(self, parser, tmp_path):
        """解析单个工作表"""
        body = """
            <table:table table:name="Sheet1">
                <table:table-row>
                    <table:table-cell><text:p>姓名</text:p></table:table-cell>
                    <table:table-cell><text:p>分数</text:p></table:table-cell>
                </table:table-row>
                <table:table-row>
                    <table:table-cell><text:p>张三</text:p></table:table-cell>
                    <table:table-cell><text:p>95</text:p></table:table-cell>
                </table:table-row>
            </table:table>
        """
        path = self._create_ods(body, tmp_path)
        result = parser.parse(path)
        assert len(result) == 1
        rows = [e for e in result[0].elements if e.elementType == "table_row"]
        assert len(rows) == 2
        assert rows[0].metadata["sheet"] == "Sheet1"

    def test_parse_multiple_sheets(self, parser, tmp_path):
        """解析多个工作表"""
        body = """
            <table:table table:name="Sheet1">
                <table:table-row>
                    <table:table-cell><text:p>A1</text:p></table:table-cell>
                </table:table-row>
            </table:table>
            <table:table table:name="Sheet2">
                <table:table-row>
                    <table:table-cell><text:p>B1</text:p></table:table-cell>
                </table:table-row>
            </table:table>
        """
        path = self._create_ods(body, tmp_path)
        result = parser.parse(path)
        assert len(result) == 2  # 两个工作表
        assert result[0].pageNumber == 1
        assert result[1].pageNumber == 2

    def test_empty_spreadsheet(self, parser, tmp_path):
        """解析空表格"""
        body = ""
        path = self._create_ods(body, tmp_path)
        result = parser.parse(path)
        assert len(result) == 1
        assert len(result[0].elements) == 0


class TestODPParser:
    """ODP 演示文稿解析测试"""

    @pytest.fixture
    def parser(self):
        return ODFParser()

    def _create_odp(self, body_content: str, tmp_path: Path) -> Path:
        xml = _make_content_xml(body_content, "presentation")
        data = _make_odf_skeleton("application/vnd.oasis.opendocument.presentation", xml)
        path = tmp_path / "test.odp"
        path.write_bytes(data)
        return path

    def test_parse_single_slide(self, parser, tmp_path):
        """解析单页幻灯片"""
        body = """
            <draw:page draw:name="第一页">
                <draw:frame>
                    <draw:text-box>
                        <text:p>幻灯片内容</text:p>
                    </draw:text-box>
                </draw:frame>
            </draw:page>
        """
        path = self._create_odp(body, tmp_path)
        result = parser.parse(path)
        assert len(result) == 1
        texts = [e for e in result[0].elements if e.elementType == "text"]
        assert len(texts) >= 1

    def test_parse_multiple_slides(self, parser, tmp_path):
        """解析多页幻灯片"""
        body = """
            <draw:page draw:name="第一页">
                <draw:frame>
                    <draw:text-box>
                        <text:p>第一页内容</text:p>
                    </draw:text-box>
                </draw:frame>
            </draw:page>
            <draw:page draw:name="第二页">
                <draw:frame>
                    <draw:text-box>
                        <text:p>第二页内容</text:p>
                    </draw:text-box>
                </draw:frame>
            </draw:page>
        """
        path = self._create_odp(body, tmp_path)
        result = parser.parse(path)
        assert len(result) == 2
        assert "第一页" in result[0].elements[0].content

    def test_empty_presentation(self, parser, tmp_path):
        """解析空演示文稿"""
        body = ""
        path = self._create_odp(body, tmp_path)
        result = parser.parse(path)
        assert len(result) == 1
        assert len(result[0].elements) == 0


class TestODFParserErrors:
    """异常情况测试"""

    @pytest.fixture
    def parser(self):
        return ODFParser()

    def test_not_a_zip_file(self, parser, tmp_path):
        """非 ZIP 文件"""
        path = tmp_path / "invalid.odt"
        path.write_text("这不是一个 ODF 文件", encoding="utf-8")
        with pytest.raises(ValueError, match="不是有效的 ODF 文件"):
            parser.parse(path)

    def test_missing_content_xml(self, parser, tmp_path):
        """缺少 content.xml"""
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        path = tmp_path / "broken.odt"
        path.write_bytes(buf.getvalue())
        with pytest.raises(ValueError, match="缺少 content.xml"):
            parser.parse(path)

    def test_bad_xml_content(self, parser, tmp_path):
        """content.xml 不是有效的 XML"""
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
            zf.writestr("content.xml", "<invalid>xml")
        path = tmp_path / "bad.odt"
        path.write_bytes(buf.getvalue())
        with pytest.raises(ValueError, match="ODF XML 解析失败"):
            parser.parse(path)