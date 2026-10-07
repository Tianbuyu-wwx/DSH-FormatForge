"""
通用文件解析模块
支持解析 .pptx, .pdf, .txt, .csv, .docx, .xls, .xlsx, 图片 等格式
（H18/audit: .doc/.ppt/.xlsb 已从宣称中收缩——无可用解析器）
采用插件化注册表架构，易于扩展新格式
"""

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from core.models import FileType, ParsedFile, TaskStatus

# 导入解析器注册表基类
from parsers import ParserRegistry

# 导入各格式解析器
try:
    from parsers.docx_parser import DOCXParser

    DOCX_PARSER_AVAILABLE = True
except ImportError:
    DOCX_PARSER_AVAILABLE = False

try:
    from parsers.xlsx_parser import XLSXParser

    XLSX_PARSER_AVAILABLE = True
except ImportError:
    XLSX_PARSER_AVAILABLE = False

try:
    from parsers.pdf_parser import PDFParser

    PDF_PARSER_AVAILABLE = True
except ImportError:
    PDF_PARSER_AVAILABLE = False

try:
    from parsers.pptx_parser import PPTXParser

    PPTX_PARSER_AVAILABLE = True
except ImportError:
    PPTX_PARSER_AVAILABLE = False

try:
    from parsers.txt_parser import TXTParser

    TXT_PARSER_AVAILABLE = True
except ImportError:
    TXT_PARSER_AVAILABLE = False

try:
    from parsers.csv_parser import CSVParser

    CSV_PARSER_AVAILABLE = True
except ImportError:
    CSV_PARSER_AVAILABLE = False

try:
    from parsers.image_parser import ImageParser

    IMAGE_PARSER_AVAILABLE = True
except ImportError:
    IMAGE_PARSER_AVAILABLE = False

try:
    from parsers.data_parser import DataParser

    DATA_PARSER_AVAILABLE = True
except ImportError:
    DATA_PARSER_AVAILABLE = False

try:
    from parsers.html_parser import HTMLParser

    HTML_PARSER_AVAILABLE = True
except ImportError:
    HTML_PARSER_AVAILABLE = False

try:
    from parsers.archive_parser import ArchiveParser

    ARCHIVE_PARSER_AVAILABLE = True
except ImportError:
    ARCHIVE_PARSER_AVAILABLE = False

try:
    from parsers.richtext_parser import RichTextParser

    RICHTEXT_PARSER_AVAILABLE = True
except ImportError:
    RICHTEXT_PARSER_AVAILABLE = False

from parsers.audio_parser import AudioParser
from parsers.email_parser import EmailParser
from parsers.epub_parser import EPUBParser
from parsers.latex_parser import LaTeXParser
from parsers.markdown_parser import MarkdownParser
from parsers.odf_parser import ODFParser
from parsers.sql_parser import SQLParser

# v2.3 新增解析器
from parsers.subtitle_parser import SubtitleParser
from parsers.svg_parser import SVGParser
from parsers.toml_parser import TOMLParser

logger = logging.getLogger("file_parser")


def _accepted_parse_kwargs(parser: Any, options: dict) -> dict:
    """
    FF-M-pages/audit: 只把解析器 ``parse()`` 真正接受的选项转发过去。

    pdf_options 里的 ``pages``/``encoding`` 属于 E2/R3.3 的跨解析器选项，
    但 22 个解析器里只有 PDF/TXT 声明了对应形参；盲目 ``**options`` 会
    ``TypeError``，随后被 ParseStep 吞掉并退化为 raw 透传。签名不可内省
    （C 扩展/``*args``）时保守放行原样选项。
    """
    import inspect

    try:
        sig = inspect.signature(parser.parse)
    except (TypeError, ValueError):  # pragma: no cover - 不可内省的实现
        return dict(options)
    accepts_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    if accepts_var_kw:
        return dict(options)
    return {k: v for k, v in options.items() if k in sig.parameters}


class FileParser:
    """通用文件解析器 - 插件化架构"""

    def __init__(self, upload_dir: Path, max_cache_size: int = 1000, cache_ttl: int = 3600):
        self.upload_dir = upload_dir
        self.parsed_cache: dict[str, ParsedFile] = {}
        self._cache_timestamps: dict[str, float] = {}
        self._max_cache_size = max_cache_size
        self._cache_ttl = cache_ttl

        # 初始化解析器注册表
        self.registry = ParserRegistry()
        self._register_default_parsers()

    def _register_default_parsers(self):
        """注册默认解析器"""
        # 注册 PDF 解析器（R2.1: 按 OCR_ENABLED 开关挂 OCR 引擎——此前从未接线，
        # use_ocr 参数虽透传但 engine 恒为 None，扫描件 OCR 形同虚设）
        if PDF_PARSER_AVAILABLE:
            ocr_engine = None
            try:
                from core.config import settings
                from core.ocr_engine import OcrEngine

                if settings.OCR_ENABLED:
                    ocr_engine = OcrEngine()
                    if not ocr_engine.is_available():
                        ocr_engine = None
            except Exception as e:  # noqa: BLE001 — OCR 引擎失败不阻断解析器注册
                logger.warning("OCR 引擎初始化失败，扫描件回退 enhance 提示: %s", e)
                ocr_engine = None
            self.registry.register(PDFParser(ocr_engine=ocr_engine))
            logger.info("已注册 PDF 解析器 (ocr_engine=%s)", type(ocr_engine).__name__ if ocr_engine else "None")

        # 注册 DOCX 解析器
        if DOCX_PARSER_AVAILABLE:
            self.registry.register(DOCXParser())
            logger.info("已注册 DOCX 解析器")

        # 注册 XLSX 解析器
        if XLSX_PARSER_AVAILABLE:
            self.registry.register(XLSXParser())
            logger.info("已注册 XLSX 解析器")

        # 注册 PPTX 解析器
        if PPTX_PARSER_AVAILABLE:
            self.registry.register(PPTXParser())
            logger.info("已注册 PPTX 解析器")

        # 注册 TXT 解析器
        if TXT_PARSER_AVAILABLE:
            self.registry.register(TXTParser())
            logger.info("已注册 TXT 解析器")

        # 注册 CSV 解析器
        if CSV_PARSER_AVAILABLE:
            self.registry.register(CSVParser())
            logger.info("已注册 CSV 解析器")

        # 注册图片解析器
        if IMAGE_PARSER_AVAILABLE:
            self.registry.register(ImageParser())
            logger.info("已注册图片解析器")

        # 注册数据文件解析器
        if DATA_PARSER_AVAILABLE:
            self.registry.register(DataParser())
            logger.info("已注册数据文件解析器")

        # 注册 HTML 解析器
        if HTML_PARSER_AVAILABLE:
            self.registry.register(HTMLParser())
            logger.info("已注册 HTML 解析器")

        # 注册压缩包解析器
        if ARCHIVE_PARSER_AVAILABLE:
            self.registry.register(ArchiveParser())
            logger.info("已注册压缩包解析器")

        # 注册富文本解析器
        if RICHTEXT_PARSER_AVAILABLE:
            self.registry.register(RichTextParser())
            logger.info("已注册富文本解析器")

        # 注册 Markdown 解析器（独立注册，位于 RichtextParser 之后以确保覆盖优先级）
        self.registry.register(MarkdownParser())
        logger.info("已注册 Markdown 解析器")

        # 注册 TOML 解析器
        self.registry.register(TOMLParser())
        logger.info("已注册 TOML 解析器")

        # 注册 ODF 解析器
        self.registry.register(ODFParser())
        logger.info("已注册 ODF 解析器")

        # 注册邮件解析器
        self.registry.register(EmailParser())
        logger.info("已注册邮件解析器")

        # 注册 EPUB 解析器
        self.registry.register(EPUBParser())
        logger.info("已注册 EPUB 解析器")

        # 注册 SVG 解析器
        self.registry.register(SVGParser())
        logger.info("已注册 SVG 解析器")

        # v2.3 新增解析器
        self.registry.register(SubtitleParser())
        logger.info("已注册字幕解析器 (SRT/VTT)")

        self.registry.register(LaTeXParser())
        logger.info("已注册 LaTeX 解析器")

        self.registry.register(SQLParser())
        logger.info("已注册 SQL 解析器")

        self.registry.register(AudioParser())
        logger.info("已注册音频解析器 (WAV/MP3/FLAC/OGG/M4A/AIFF)")

        logger.info("解析器注册完成，共 %d 个解析器", len(self.registry.parsers))

    def _generate_parse_id(self) -> str:
        """生成解析任务ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        random_suffix = uuid.uuid4().hex[:6]
        return f"parse{timestamp}{random_suffix}"

    def parse_file(self, file_path: Path, file_type: str, pdf_options: dict | None = None) -> ParsedFile:
        """
        解析文件 - 使用插件化注册表

        Args:
            file_path: 文件路径
            file_type: 文件类型
            pdf_options: PDF 解析器选项（E2：pages/drop_furniture/two_column/use_ocr 等）

        Returns:
            ParsedFile: 解析后的文件数据
        """
        file_path = Path(file_path)
        logger.info("开始解析文件: %s, 声明类型=%s", file_path, file_type)

        if not file_path.exists():
            logger.error("文件不存在: %s", file_path)
            raise FileNotFoundError(f"文件不存在: {file_path}")

        file_size = file_path.stat().st_size
        file_name = file_path.name
        logger.debug("文件信息: name=%s, size=%d bytes", file_name, file_size)

        # 映射文件类型
        # H18/audit: .doc/.ppt（OLE2 旧格式）无解析器——映射移除，交给
        # unsupported_format 友好错误；.xls 保留（有 xlrd 代码路径）
        type_mapping = {
            "pdf": FileType.PDF,
            "image": FileType.IMAGE,
            "txt": FileType.TXT,
            "csv": FileType.CSV,
            "xls": FileType.XLS,
        }
        # 根据扩展名补充映射
        ext = file_path.suffix.lower()
        ext_mapping = {
            ".pptx": FileType.PPT,
            ".pdf": FileType.PDF,
            ".jpg": FileType.IMAGE,
            ".jpeg": FileType.IMAGE,
            ".png": FileType.IMAGE,
            ".gif": FileType.IMAGE,
            ".bmp": FileType.IMAGE,
            ".webp": FileType.IMAGE,
            ".tiff": FileType.IMAGE,
            ".tif": FileType.IMAGE,
            ".docx": FileType.DOC,
            ".txt": FileType.TXT,
            ".text": FileType.TXT,
            ".md": FileType.TXT,
            ".log": FileType.TXT,
            ".csv": FileType.CSV,
            ".tsv": FileType.CSV,
            ".tab": FileType.CSV,
            ".xls": FileType.XLS,
            ".xlsx": FileType.XLS,
            ".json": FileType.TXT,
            ".yaml": FileType.TXT,
            ".yml": FileType.TXT,
            ".xml": FileType.TXT,
            ".html": FileType.TXT,
            ".htm": FileType.TXT,
            ".zip": FileType.UNKNOWN,
            ".7z": FileType.UNKNOWN,
            ".rar": FileType.UNKNOWN,
            ".rtf": FileType.TXT,
            # v2.3 新增
            ".srt": FileType.TXT,
            ".vtt": FileType.TXT,
            ".tex": FileType.TXT,
            ".latex": FileType.TXT,
            ".ltx": FileType.TXT,
            ".sql": FileType.TXT,
            ".wav": FileType.UNKNOWN,
            ".mp3": FileType.UNKNOWN,
            ".flac": FileType.UNKNOWN,
            ".ogg": FileType.UNKNOWN,
            ".m4a": FileType.UNKNOWN,
            ".aiff": FileType.UNKNOWN,
            ".aif": FileType.UNKNOWN,
        }
        mapped_type = type_mapping.get(file_type, ext_mapping.get(ext, FileType.UNKNOWN))
        logger.debug("文件类型映射: ext=%s -> mapped_type=%s", ext, mapped_type.value)

        # 尝试使用注册表中的解析器（新插件化方式）
        content = None
        if file_path.exists():
            try:
                with open(file_path, "rb") as f:
                    content = f.read(2048)
            except Exception as e:
                logger.warning("读取文件头部失败: %s", e)

        plugin_parser = self.registry.find_best_parser(file_path, content)

        if plugin_parser:
            logger.info("使用插件解析器: %s", type(plugin_parser).__name__)
            try:
                if pdf_options:
                    accepted = _accepted_parse_kwargs(plugin_parser, pdf_options)
                    dropped = sorted(set(pdf_options) - set(accepted))
                    if dropped:
                        # FF-M-pages/audit: 18/22 解析器的 parse() 不接受 pages/encoding；
                        # 盲目 **kwargs 透传会 TypeError 并被吞掉 → raw 透传垃圾。
                        logger.info(
                            "解析器 %s 不接受选项 %s，已丢弃（保留 %s）",
                            type(plugin_parser).__name__,
                            dropped,
                            sorted(accepted) or "无",
                        )
                    pages = plugin_parser.parse(file_path, **accepted)
                else:
                    pages = plugin_parser.parse(file_path)
                logger.info("解析完成: parser=%s, pages=%d", type(plugin_parser).__name__, len(pages))
            except Exception as e:
                logger.error("插件解析器执行失败: %s, error=%s", type(plugin_parser).__name__, e, exc_info=True)
                raise
        else:
            logger.error("未找到支持该文件的解析器: %s", file_path.suffix)
            raise ValueError(f"不支持的文件类型: {file_path.suffix}")

        # 创建解析结果
        parsed = ParsedFile(
            parseId=self._generate_parse_id(),
            fileName=file_name,
            fileSize=file_size,
            pageCount=len(pages),
            fileType=mapped_type,
            pages=pages,
            createdAt=datetime.now(),
            status=TaskStatus.COMPLETED,
            filePath=str(file_path),
        )

        # 缓存解析结果（带容量和TTL管理）
        self._add_to_cache(parsed.parseId, parsed)
        logger.debug("解析结果已缓存: parse_id=%s", parsed.parseId)

        return parsed

    def _add_to_cache(self, parse_id: str, parsed: ParsedFile):
        """添加缓存并管理容量"""
        import time

        # 清理过期缓存
        now = time.time()
        expired = [k for k, v in self._cache_timestamps.items() if now - v > self._cache_ttl]
        for k in expired:
            self.parsed_cache.pop(k, None)
            self._cache_timestamps.pop(k, None)
        if expired:
            logger.debug("清理过期缓存: %d 条", len(expired))

        # 如果超出容量，移除最旧的
        while len(self.parsed_cache) >= self._max_cache_size:
            oldest = min(self._cache_timestamps, key=lambda k: self._cache_timestamps[k])
            self.parsed_cache.pop(oldest, None)
            self._cache_timestamps.pop(oldest, None)
            logger.debug("缓存超出容量，移除最旧项: %s", oldest)

        self.parsed_cache[parse_id] = parsed
        self._cache_timestamps[parse_id] = now
        logger.debug("缓存已更新: count=%d, max=%d", len(self.parsed_cache), self._max_cache_size)

    def get_parsed_result(self, parse_id: str) -> ParsedFile | None:
        """获取解析结果（带TTL检查）"""
        import time

        if parse_id in self._cache_timestamps:
            if time.time() - self._cache_timestamps[parse_id] > self._cache_ttl:
                logger.debug("缓存已过期: %s", parse_id)
                self.parsed_cache.pop(parse_id, None)
                self._cache_timestamps.pop(parse_id, None)
                return None
            logger.debug("缓存命中: %s", parse_id)
            return self.parsed_cache.get(parse_id)
        logger.debug("缓存未命中: %s", parse_id)
        return None

    def extract_text_summary(self, parsed: ParsedFile, max_length: int = 8000) -> str:
        """
        提取文本摘要

        Args:
            parsed: 解析后的文件数据
            max_length: 最大长度限制

        Returns:
            str: 文本摘要
        """
        summary_parts = []

        for page in parsed.pages:
            page_text = f"""
【第 {page.pageNumber} 页】
{page.rawText}
"""
            summary_parts.append(page_text)

        full_text = "\n---\n".join(summary_parts)

        # 如果超过最大长度，进行截断
        if len(full_text) > max_length:
            full_text = full_text[:max_length] + "\n... (内容已截断)"

        return full_text
