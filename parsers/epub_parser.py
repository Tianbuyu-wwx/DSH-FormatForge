"""EPUB 电子书解析器
支持解析 .epub 格式电子书
纯 Python 标准库实现（zipfile + xml.etree.ElementTree + html.parser + posixpath），零外部依赖
"""

import logging
import posixpath
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from core.models import ExtractedElement, PageContent
from parsers import BaseParser

logger = logging.getLogger("parsers.epub")

# EPUB 通用命名空间
CONTAINER_NS = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
OPF_NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
}


class _HTMLTextExtractor(HTMLParser):
    """HTML 纯文本提取器"""

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        # H6/audit: 记录当前跳过的标签名——未闭合 <script>/<style> 之前会让
        # _skip_tag 永远为 True，后面整章都被静默丢弃
        self._skip_tag: str | None = None

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style") and self._skip_tag is None:
            self._skip_tag = tag
            return
        if tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._parts.append("\n")

    def handle_endtag(self, tag):
        # 只有配对的结束标签才解除跳过（未闭合则到文档尾自然失效）
        if self._skip_tag and tag == self._skip_tag:
            self._skip_tag = None
            return
        if tag in ("p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip_tag:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        # 合并多余空行
        import re

        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _ns(tag: str, ns_map: dict) -> str:
    """将带前缀的标签名转为 Clark 表示法"""
    prefix, local = tag.split(":", 1)
    return f"{{{ns_map[prefix]}}}{local}"


def _extract_html_text(html_content: str | bytes) -> str:
    """从 HTML/XHTML 中提取纯文本"""
    text: str
    if isinstance(html_content, bytes):
        # FF-L-epub-odf/audit: latin-1 对任意字节都解码成功，放在候选链里会
        # 静默「赢」过真实编码（gbk 字节解成 latin-1 得到合法乱码）。先用 XML
        # 声明的 encoding（XHTML 章节通常自带），再严格尝试候选；全部失败才用
        # utf-8/replace 兜底并以 U+FFFD 显式标记低置信，绝不裸回退 latin-1。
        declared = None
        head = html_content[:1024].decode("ascii", errors="ignore")
        import re

        m = re.search(r"""encoding\s*=\s*['"]([A-Za-z0-9._-]+)['"]""", head)
        if m:
            declared = m.group(1)
        candidates = ([declared] if declared else []) + ["utf-8", "utf-16", "gbk"]
        for encoding in candidates:
            try:
                text = html_content.decode(encoding)
                break
            except (UnicodeDecodeError, UnicodeError, LookupError):
                continue
        else:
            logger.debug("EPUB 章节编码检测失败，以 utf-8/replace 低置信兜底")
            text = html_content.decode("utf-8", errors="replace")
    else:
        text = html_content

    extractor = _HTMLTextExtractor()
    extractor.feed(text)
    return extractor.get_text()


class EPUBParser(BaseParser):
    """EPUB 电子书解析器"""

    @property
    def supported_extensions(self) -> list[str]:
        return [".epub"]

    @property
    def supported_magic(self) -> list[bytes]:
        # EPUB 是 ZIP 格式
        return [b"PK\x03\x04"]

    def parse(self, file_path: Path) -> list[PageContent]:
        """解析 EPUB 文件"""
        file_path = Path(file_path)

        logger.info("开始解析 EPUB: %s", file_path)

        try:
            with zipfile.ZipFile(file_path, "r") as zf:
                # 1. 读取 container.xml 定位 OPF
                if "META-INF/container.xml" not in zf.namelist():
                    raise ValueError("缺少 META-INF/container.xml")
                container_xml = zf.read("META-INF/container.xml")
                opf_path = self._get_opf_path(container_xml)
                logger.debug("OPF 路径: %s", opf_path)

                # 2. 解析 OPF
                opf_dir = str(Path(opf_path).parent).replace("\\", "/")
                opf_xml = zf.read(opf_path)
                title, author, spine_items = self._parse_opf(opf_xml, opf_dir)

                # B8/v0.11.0: 解析 NCX 拿章节标题映射
                # NCX 键是 navPoint-id / src stem；spine itemref 是 manifest id（如 "ch1"）。
                # 需通过 manifest 反查：manifest_id -> href stem -> NCX title
                chapter_titles_raw = self._parse_ncx(zf, opf_xml, opf_dir)
                # 反向映射 manifest_id -> href stem
                opf_root_local = ET.fromstring(opf_xml)
                manifest_map: dict[str, str] = {}
                for item in opf_root_local.findall(".//opf:item", OPF_NS):
                    mid = item.get("id")
                    href = item.get("href")
                    if mid and href:
                        stem = href.split("/")[-1].split("#")[0]
                        manifest_map[mid] = stem
                chapter_titles: dict[str, str] = {}
                for spine_id, href in spine_items:
                    stem = href.split("/")[-1].split("#")[0]
                    title = chapter_titles_raw.get(spine_id, "") or chapter_titles_raw.get(stem, "")
                    chapter_titles[spine_id] = title
                logger.info(
                    "EPUB 元数据: title=%s, author=%s, chapters=%d (with titles=%d)",
                    title,
                    author,
                    len(spine_items),
                    len(chapter_titles),
                )

                # 3. 按 spine 顺序解析各章节
                pages: list[PageContent] = []
                for page_num, (item_id, href) in enumerate(spine_items, 1):
                    # H6/audit: 无条件 join opf_dir 与 href——标准 OEBPS/content.opf +
                    # Text/ch1.xhtml 布局的 href 带 "/"，此前被直接丢掉 opf_dir 导致
                    # 每章都 KeyError、整本书只剩空占位。normpath 顺带去掉 "./"、"/.." 与斜杠。
                    content_path = posixpath.normpath(f"{opf_dir}/{href}")

                    try:
                        raw_content = zf.read(content_path)
                        text = _extract_html_text(raw_content)
                    except KeyError:
                        logger.warning("章节文件未找到: %s", content_path)
                        continue

                    elements: list[ExtractedElement] = []
                    raw_lines: list[str] = []
                    elem_idx = [0]

                    if text:
                        # 按段落拆分为元素
                        import re

                        paragraphs = re.split(r"\n\s*\n", text)
                        for para in paragraphs:
                            para = para.strip()
                            if para:
                                elements.append(
                                    ExtractedElement(
                                        elementId=f"elem_{page_num}_{elem_idx[0]}",
                                        elementType="text",
                                        content=para,
                                        metadata={
                                            "chapter": item_id,
                                            "chapter_index": page_num - 1,
                                            "chapter_title": chapter_titles.get(item_id, ""),
                                        },
                                    )
                                )
                                raw_lines.append(para)
                                elem_idx[0] += 1

                    # 检测是否有图片
                    has_image = b"<img" in raw_content if isinstance(raw_content, bytes) else "<img" in raw_content

                    pages.append(
                        PageContent(
                            pageNumber=page_num,
                            elements=elements,
                            rawText="\n".join(raw_lines) if raw_lines else f"[章节 {item_id}]",
                            hasImage=has_image,
                            hasTable=False,
                        )
                    )

                if not pages:
                    pages.append(
                        PageContent(
                            pageNumber=1,
                            elements=[],
                            rawText="",
                            hasImage=False,
                            hasTable=False,
                        )
                    )

        except zipfile.BadZipFile as e:
            logger.error("不是有效的 ZIP/EPUB 文件: %s", file_path)
            raise ValueError(f"不是有效的 EPUB 文件: {file_path}") from e
        except KeyError as e:
            logger.error("EPUB 缺少必要文件: %s", e)
            raise ValueError(f"无效的 EPUB 文件：缺少 {e}") from e
        except ET.ParseError as e:
            logger.error("EPUB XML 解析失败: %s", e)
            raise ValueError(f"EPUB XML 解析失败: {e}") from e
        except Exception as e:
            logger.error("EPUB 解析失败: %s", e)
            raise ValueError(f"EPUB 解析失败: {e}") from e

        logger.info("EPUB 解析完成: %d 章", len(pages))
        return pages

    def _get_opf_path(self, container_xml: bytes) -> str:
        """从 container.xml 中获取 OPF 文件路径"""
        root = ET.fromstring(container_xml)
        rootfile = root.find(".//c:rootfile", CONTAINER_NS)
        if rootfile is None:
            raise ValueError("container.xml 中未找到 rootfile")
        path = rootfile.get("full-path")
        if not path:
            raise ValueError("container.xml 中缺少 full-path 属性")
        return path

    def _parse_opf(self, opf_xml: bytes, opf_dir: str) -> tuple[str, str, list[tuple[str, str]]]:
        """解析 OPF 文件，返回 (title, author, spine_items)"""
        root = ET.fromstring(opf_xml)

        # 书名
        title = ""
        title_elem = root.find(".//dc:title", OPF_NS)
        if title_elem is not None and title_elem.text:
            title = title_elem.text.strip()

        # 作者
        author = ""
        creator_elem = root.find(".//dc:creator", OPF_NS)
        if creator_elem is not None and creator_elem.text:
            author = creator_elem.text.strip()

        # 构建 manifest: id → href 映射
        manifest: dict[str, str] = {}
        for item in root.findall(".//opf:item", OPF_NS):
            item_id = item.get("id")
            href = item.get("href")
            if item_id and href:
                manifest[item_id] = href

        # 构建 spine 顺序 (idref → href)
        spine_items: list[tuple[str, str]] = []
        for itemref in root.findall(".//opf:itemref", OPF_NS):
            idref = itemref.get("idref")
            if idref and idref in manifest:
                spine_items.append((idref, manifest[idref]))

        return title, author, spine_items

    def _parse_ncx(self, zf: "zipfile.ZipFile", opf_xml: bytes, opf_dir: str) -> dict[str, str]:
        """B8/v0.11.0: 解析 NCX toc.ncx 返回 chapter_id → title。

        返回空 dict 时不影响主流程（章节用 spine itemref idref 占位）。
        支持 EPUB 2 NCX 优先；EPUB 3 nav.xhtml 暂简化为读 toc.ncx 即可。
        """
        result: dict[str, str] = {}
        try:
            ns_ncx = {"ncx": "http://www.daisy.org/z3986/2005/ncx/"}
            # 找 NCX 路径（从 OPF manifest 的 'ncx' 项）
            opf_root = ET.fromstring(opf_xml)
            ncx_href = None
            for item in opf_root.findall(".//opf:item", OPF_NS):
                if item.get("media-type") == "application/x-dtbncx+xml":
                    ncx_href = item.get("href")
                    break
            if not ncx_href:
                return result
            # H6/audit: 同样无条件 join + normpath——根目录 OPF（opf_dir='.'）时
            # f"{opf_dir}/{href}" 是 './toc.ncx'，逐一字符串 ZIP 查找必 KeyError。
            ncx_path = posixpath.normpath(f"{opf_dir}/{ncx_href}")
            try:
                ncx_xml = zf.read(ncx_path)
            except KeyError:
                return result
            ncx_root = ET.fromstring(ncx_xml)
            for nav_point in ncx_root.findall(".//ncx:navPoint", ns_ncx):
                label_text = nav_point.find("ncx:navLabel/ncx:text", ns_ncx)
                content = nav_point.find("ncx:content", ns_ncx)
                if label_text is None or content is None:
                    continue
                title = (label_text.text or "").strip()
                src = content.get("src", "")
                src_stem = src.split("/")[-1].split("#")[0]
                nav_id = nav_point.get("id", "")
                if title:
                    if nav_id:
                        result[nav_id] = title
                    if src_stem:
                        result[src_stem] = title
        except Exception as e:
            logger.debug("NCX 解析失败（非致命）: %s", e)
        return result
