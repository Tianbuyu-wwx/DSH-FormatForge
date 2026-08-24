"""
EPUB 解析器单元测试
使用 zipfile + xml.etree 动态构建有效的 EPUB 测试文件
"""
import sys
import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.epub_parser import EPUBParser


def _make_epub(
    title: str = "测试电子书",
    author: str = "测试作者",
    chapters: list[tuple[str, str]] | None = None,
    opf_dir: str = "OEBPS",
) -> bytes:
    """
    构建一个最小的有效 EPUB 文件字节

    Args:
        title: 书名
        author: 作者
        chapters: 章节列表 [(chapter_id, html_content), ...]
        opf_dir: OPF 文件所在目录
    """
    if chapters is None:
        chapters = [("chapter1", "<html><body><p>第一章内容</p></body></html>")]

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # mimetype 必须为第一个条目且不压缩
        zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)

        # container.xml
        container_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="{opf_dir}/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
        zf.writestr("META-INF/container.xml", container_xml)

        # 构建 manifest 和 spine
        manifest_entries = []
        spine_entries = []
        for i, (cid, html) in enumerate(chapters):
            filename = f"{cid}.xhtml"
            path = f"{opf_dir}/{filename}"
            zf.writestr(path, f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head><title>{cid}</title></head>
<body>{html}</body>
</html>""")
            manifest_entries.append(
                f'<item id="{cid}" href="{filename}" media-type="application/xhtml+xml"/>'
            )
            spine_entries.append(f'<itemref idref="{cid}"/>')

        # OPF
        opf_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         unique-identifier="book-id">
  <metadata>
    <dc:identifier id="book-id">urn:uuid:test-book</dc:identifier>
    <dc:title>{title}</dc:title>
    <dc:creator>{author}</dc:creator>
    <dc:language>zh-CN</dc:language>
  </metadata>
  <manifest>
    {chr(10).join(manifest_entries)}
  </manifest>
  <spine>
    {chr(10).join(spine_entries)}
  </spine>
</package>"""
        zf.writestr(f"{opf_dir}/content.opf", opf_xml)

    return buf.getvalue()


class TestEPUBParserBasic:
    """基础测试"""

    @pytest.fixture
    def parser(self):
        return EPUBParser()

    def test_supported_extensions(self, parser):
        assert ".epub" in parser.supported_extensions
        assert ".txt" not in parser.supported_extensions

    def test_supported_magic(self, parser):
        assert b"PK\x03\x04" in parser.supported_magic

    def test_can_parse_epub(self, parser):
        assert parser.can_parse(Path("/tmp/book.epub")) == 0.9

    def test_can_parse_non_epub(self, parser):
        assert parser.can_parse(Path("/tmp/test.txt")) == 0.0
        assert parser.can_parse(Path("/tmp/test.pdf")) == 0.0


class TestEPUBParserParsing:
    """EPUB 解析测试"""

    @pytest.fixture
    def parser(self):
        return EPUBParser()

    def _create_epub(self, epub_bytes: bytes, tmp_path: Path) -> Path:
        path = tmp_path / "test.epub"
        path.write_bytes(epub_bytes)
        return path

    def test_parse_single_chapter(self, parser, tmp_path):
        """解析单章节 EPUB"""
        epub = _make_epub(
            title="我的书",
            author="作者甲",
            chapters=[("ch1", "<p>这是第一章的内容。</p>")]
        )
        path = self._create_epub(epub, tmp_path)
        result = parser.parse(path)
        assert len(result) == 1

        texts = [e for e in result[0].elements if e.elementType == "text"]
        combined = " ".join(t.content for t in texts)
        assert "第一章" in combined

    def test_parse_multiple_chapters(self, parser, tmp_path):
        """解析多章节 EPUB"""
        epub = _make_epub(
            chapters=[
                ("ch1", "<h1>第一章</h1><p>第一章内容。</p>"),
                ("ch2", "<h1>第二章</h1><p>第二章内容。</p>"),
                ("ch3", "<h1>第三章</h1><p>第三章内容。</p>"),
            ]
        )
        path = self._create_epub(epub, tmp_path)
        result = parser.parse(path)
        assert len(result) == 3  # 三章 = 三页

        # 每章应有文本
        for page in result:
            texts = [e for e in page.elements if e.elementType == "text"]
            assert len(texts) > 0

        # 验证章节顺序
        all_texts = []
        for page in result:
            for e in page.elements:
                if e.elementType == "text":
                    all_texts.append(e.content)
        combined = " ".join(all_texts)
        assert "第一章" in combined
        assert "第二章" in combined
        assert "第三章" in combined

    def test_parse_with_image(self, parser, tmp_path):
        """解析含图片的章节"""
        epub = _make_epub(
            chapters=[("ch1", '<p>文字内容</p><img src="pic.jpg" alt="图片"/>')]
        )
        path = self._create_epub(epub, tmp_path)
        result = parser.parse(path)
        assert result[0].hasImage

    def test_parse_html_stripping(self, parser, tmp_path):
        """HTML 标签应被正确移除"""
        epub = _make_epub(
            chapters=[("ch1", """
                <h1>标题</h1>
                <p>段落<strong>加粗</strong>文字</p>
                <ul>
                    <li>列表项一</li>
                    <li>列表项二</li>
                </ul>
            """)]
        )
        path = self._create_epub(epub, tmp_path)
        result = parser.parse(path)
        texts = [e for e in result[0].elements if e.elementType == "text"]
        combined = " ".join(t.content for t in texts)
        assert "标题" in combined
        assert "段落" in combined
        assert "列表项一" in combined
        assert "<h1>" not in combined
        assert "<p>" not in combined
        assert "<strong>" not in combined

    def test_parse_with_script_style_removed(self, parser, tmp_path):
        """script 和 style 内容应被移除"""
        epub = _make_epub(
            chapters=[("ch1", """
                <html>
                <head>
                    <style>.css { color: red; }</style>
                    <script>alert("test");</script>
                </head>
                <body>
                    <p>正文内容</p>
                </body>
                </html>
            """)]
        )
        path = self._create_epub(epub, tmp_path)
        result = parser.parse(path)
        texts = [e for e in result[0].elements if e.elementType == "text"]
        combined = " ".join(t.content for t in texts)
        assert "正文内容" in combined
        assert "alert" not in combined
        assert "color: red" not in combined


class TestEPUBParserErrors:
    """异常情况测试"""

    @pytest.fixture
    def parser(self):
        return EPUBParser()

    def test_not_a_zip_file(self, parser, tmp_path):
        """非 ZIP 文件"""
        path = tmp_path / "invalid.epub"
        path.write_text("这不是一个 EPUB 文件", encoding="utf-8")
        with pytest.raises(ValueError, match="不是有效的 EPUB 文件"):
            parser.parse(path)

    def test_missing_container_xml(self, parser, tmp_path):
        """缺少 META-INF/container.xml"""
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        path = tmp_path / "broken.epub"
        path.write_bytes(buf.getvalue())
        with pytest.raises(ValueError, match="缺少 META-INF/container.xml"):
            parser.parse(path)

    def test_empty_book(self, parser, tmp_path):
        """无章节的空 EPUB"""
        epub = _make_epub(chapters=[])
        path = tmp_path / "empty.epub"
        path.write_bytes(epub)
        result = parser.parse(path)
        # 无章节时返回空 page
        assert len(result) == 1
        assert len(result[0].elements) == 0