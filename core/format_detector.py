"""
格式检测器
自动检测输入数据的格式类型
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger("format_detector")


class DataFormat(str, Enum):
    """支持的数据格式"""

    # 文档
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    TXT = "txt"
    RTF = "rtf"
    # 表格
    XLSX = "xlsx"
    CSV = "csv"
    # 数据
    JSON = "json"
    YAML = "yaml"
    XML = "xml"
    HTML = "html"
    # 配置
    TOML = "toml"
    # 开放文档格式
    ODT = "odt"
    ODS = "ods"
    ODP = "odp"
    # 邮件
    EML = "eml"
    MSG = "msg"
    # 电子书
    EPUB = "epub"
    # 图片
    PNG = "png"
    JPEG = "jpeg"
    GIF = "gif"
    WEBP = "webp"
    BMP = "bmp"
    TIFF = "tiff"
    SVG = "svg"
    # 压缩包
    ZIP = "zip"
    SEVEN_Z = "7z"
    RAR = "rar"
    # 其他
    UNKNOWN = "unknown"
    BINARY = "binary"
    # v2.3 新增
    SRT = "srt"  # 字幕
    LATEX = "latex"  # LaTeX
    SQL = "sql"  # SQL 转储
    AUDIO = "audio"  # 音频元数据


@dataclass
class FormatDetectionResult:
    """格式检测结果"""

    format: DataFormat
    mime_type: str
    confidence: float  # 0.0-1.0
    extension: str | None = None
    metadata: dict[str, Any] | None = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class FormatDetector:
    """格式检测器 - 通过魔数和内容分析检测数据格式"""

    # 魔数签名表
    MAGIC_SIGNATURES: dict[bytes, tuple[DataFormat, str]] = {
        # PDF
        b"%PDF": (DataFormat.PDF, "application/pdf"),
        # 图片
        b"\x89PNG": (DataFormat.PNG, "image/png"),
        b"\xff\xd8\xff": (DataFormat.JPEG, "image/jpeg"),
        b"GIF87a": (DataFormat.GIF, "image/gif"),
        b"GIF89a": (DataFormat.GIF, "image/gif"),
        b"RIFF": (DataFormat.WEBP, "image/webp"),  # 需要进一步检查
        b"BM": (DataFormat.BMP, "image/bmp"),
        b"II*\x00": (DataFormat.TIFF, "image/tiff"),  # Little endian
        b"MM\x00*": (DataFormat.TIFF, "image/tiff"),  # Big endian
        # 压缩包
        b"PK\x03\x04": (DataFormat.ZIP, "application/zip"),
        b"7z\xbc\xaf\x27\x1c": (DataFormat.SEVEN_Z, "application/x-7z-compressed"),
        b"Rar!": (DataFormat.RAR, "application/x-rar"),
    }

    # 扩展名映射
    EXTENSION_MAP: dict[str, tuple[DataFormat, str]] = {
        ".pdf": (DataFormat.PDF, "application/pdf"),
        ".docx": (DataFormat.DOCX, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ".pptx": (DataFormat.PPTX, "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
        ".xlsx": (DataFormat.XLSX, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ".txt": (DataFormat.TXT, "text/plain"),
        ".text": (DataFormat.TXT, "text/plain"),
        ".md": (DataFormat.TXT, "text/markdown"),
        ".markdown": (DataFormat.TXT, "text/markdown"),
        ".rtf": (DataFormat.RTF, "application/rtf"),
        ".csv": (DataFormat.CSV, "text/csv"),
        ".tsv": (DataFormat.CSV, "text/tab-separated-values"),
        ".json": (DataFormat.JSON, "application/json"),
        ".yaml": (DataFormat.YAML, "application/yaml"),
        ".yml": (DataFormat.YAML, "application/yaml"),
        ".xml": (DataFormat.XML, "application/xml"),
        ".html": (DataFormat.HTML, "text/html"),
        ".htm": (DataFormat.HTML, "text/html"),
        ".png": (DataFormat.PNG, "image/png"),
        ".jpg": (DataFormat.JPEG, "image/jpeg"),
        ".jpeg": (DataFormat.JPEG, "image/jpeg"),
        ".gif": (DataFormat.GIF, "image/gif"),
        ".webp": (DataFormat.WEBP, "image/webp"),
        ".bmp": (DataFormat.BMP, "image/bmp"),
        ".tiff": (DataFormat.TIFF, "image/tiff"),
        ".tif": (DataFormat.TIFF, "image/tiff"),
        ".zip": (DataFormat.ZIP, "application/zip"),
        ".7z": (DataFormat.SEVEN_Z, "application/x-7z-compressed"),
        ".rar": (DataFormat.RAR, "application/x-rar"),
        ".toml": (DataFormat.TOML, "application/toml"),
        # ODF
        ".odt": (DataFormat.ODT, "application/vnd.oasis.opendocument.text"),
        ".ods": (DataFormat.ODS, "application/vnd.oasis.opendocument.spreadsheet"),
        ".odp": (DataFormat.ODP, "application/vnd.oasis.opendocument.presentation"),
        # 邮件
        ".eml": (DataFormat.EML, "message/rfc822"),
        ".msg": (DataFormat.MSG, "application/vnd.ms-outlook"),
        # 电子书
        ".epub": (DataFormat.EPUB, "application/epub+zip"),
        # 矢量图
        ".svg": (DataFormat.SVG, "image/svg+xml"),
        # v2.3 新增
        ".srt": (DataFormat.SRT, "text/srt"),
        ".vtt": (DataFormat.SRT, "text/vtt"),
        ".tex": (DataFormat.LATEX, "application/x-tex"),
        ".latex": (DataFormat.LATEX, "application/x-tex"),
        ".ltx": (DataFormat.LATEX, "application/x-tex"),
        ".sql": (DataFormat.SQL, "application/sql"),
        ".wav": (DataFormat.AUDIO, "audio/wav"),
        ".mp3": (DataFormat.AUDIO, "audio/mpeg"),
        ".flac": (DataFormat.AUDIO, "audio/flac"),
        ".ogg": (DataFormat.AUDIO, "audio/ogg"),
        ".m4a": (DataFormat.AUDIO, "audio/mp4"),
        ".aiff": (DataFormat.AUDIO, "audio/aiff"),
        ".aif": (DataFormat.AUDIO, "audio/aiff"),
    }

    def detect(self, data: bytes, filename: str | None = None) -> FormatDetectionResult:
        """
        检测数据格式

        Args:
            data: 原始数据字节
            filename: 文件名（可选，用于辅助检测）

        Returns:
            FormatDetectionResult: 检测结果
        """
        if not data:
            logger.debug("格式检测: 空数据")
            return FormatDetectionResult(
                format=DataFormat.UNKNOWN, mime_type="application/octet-stream", confidence=0.0
            )

        logger.debug("开始格式检测: data_size=%d, filename=%s", len(data), filename)

        # 1. 尝试魔数检测
        magic_result = self._detect_by_magic(data)
        if magic_result and magic_result.confidence >= 0.9:
            logger.info(
                "格式检测(魔数): format=%s, confidence=%.2f", magic_result.format.value, magic_result.confidence
            )
            return magic_result

        # 2. 尝试扩展名检测
        ext_result = None
        if filename:
            ext_result = self._detect_by_extension(filename)

        # 3. 尝试内容分析
        content_result = self._detect_by_content(data)

        # 综合判断
        if magic_result and magic_result.confidence >= 0.7:
            logger.info(
                "格式检测(魔数): format=%s, confidence=%.2f", magic_result.format.value, magic_result.confidence
            )
            return magic_result

        if content_result and content_result.confidence >= 0.8:
            logger.info(
                "格式检测(内容): format=%s, confidence=%.2f", content_result.format.value, content_result.confidence
            )
            return content_result

        if ext_result and ext_result.confidence >= 0.6:
            logger.info("格式检测(扩展名): format=%s, confidence=%.2f", ext_result.format.value, ext_result.confidence)
            return ext_result

        # 如果魔数和扩展名一致，提高置信度
        if magic_result and ext_result and magic_result.format == ext_result.format:
            logger.info("格式检测(魔数+扩展名一致): format=%s, confidence=0.95", magic_result.format.value)
            return FormatDetectionResult(
                format=magic_result.format,
                mime_type=magic_result.mime_type,
                confidence=0.95,
                extension=ext_result.extension,
            )

        # 返回最可能的结果
        if magic_result:
            logger.info(
                "格式检测(魔数回退): format=%s, confidence=%.2f", magic_result.format.value, magic_result.confidence
            )
            return magic_result
        if ext_result:
            logger.info(
                "格式检测(扩展名回退): format=%s, confidence=%.2f", ext_result.format.value, ext_result.confidence
            )
            return ext_result
        if content_result:
            logger.info(
                "格式检测(内容回退): format=%s, confidence=%.2f", content_result.format.value, content_result.confidence
            )
            return content_result

        # 检测是否为纯文本
        if self._is_text(data):
            logger.info("格式检测(纯文本回退): format=txt, confidence=0.5")
            return FormatDetectionResult(
                format=DataFormat.TXT,
                mime_type="text/plain",
                confidence=0.5,
                extension=filename and Path(filename).suffix,
            )

        logger.info("格式检测(未知): format=binary, confidence=0.3")
        return FormatDetectionResult(
            format=DataFormat.BINARY,
            mime_type="application/octet-stream",
            confidence=0.3,
            extension=filename and Path(filename).suffix,
        )

    def _detect_by_magic(self, data: bytes) -> FormatDetectionResult | None:
        """通过魔数检测格式"""
        if len(data) < 4:
            return None

        # 检查 WEBP（特殊处理，需要检查 RIFF 后面的格式）
        if data[:4] == b"RIFF" and len(data) >= 12 and data[8:12] == b"WEBP":
            return FormatDetectionResult(format=DataFormat.WEBP, mime_type="image/webp", confidence=0.95)

        # 检查 ZIP 子类型（DOCX/PPTX/XLSX）
        if data[:4] == b"PK\x03\x04":
            return self._detect_zip_subtype(data)

        # 检查其他魔数
        for magic, (fmt, mime) in self.MAGIC_SIGNATURES.items():
            if data[: len(magic)] == magic:
                return FormatDetectionResult(format=fmt, mime_type=mime, confidence=0.95)

        return None

    def _detect_zip_subtype(self, data: bytes) -> FormatDetectionResult:
        """检测 ZIP 压缩包的子类型（DOCX/PPTX/XLSX/ODF）"""
        # 在 ZIP 的前 2048 字节中查找特征目录名
        header = data[:2048]

        # Office Open XML 格式
        if b"word/" in header:
            return FormatDetectionResult(
                format=DataFormat.DOCX,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                confidence=0.9,
            )
        elif b"ppt/" in header:
            return FormatDetectionResult(
                format=DataFormat.PPTX,
                mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                confidence=0.9,
            )
        elif b"xl/" in header:
            return FormatDetectionResult(
                format=DataFormat.XLSX,
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                confidence=0.9,
            )

        # EPUB 电子书（检查 META-INF/container.xml）
        if b"META-INF/container.xml" in header:
            return FormatDetectionResult(format=DataFormat.EPUB, mime_type="application/epub+zip", confidence=0.9)

        # ODF 格式（通过 mimetype 条目识别）
        if b"mimetype" in header or b"content.xml" in header:
            # 区分 ODT/ODS/ODP
            mimetype_field = header[header.find(b"mimetype") : header.find(b"mimetype") + 200]
            if b"opendocument.text" in mimetype_field:
                return FormatDetectionResult(
                    format=DataFormat.ODT, mime_type="application/vnd.oasis.opendocument.text", confidence=0.9
                )
            elif b"opendocument.spreadsheet" in mimetype_field:
                return FormatDetectionResult(
                    format=DataFormat.ODS, mime_type="application/vnd.oasis.opendocument.spreadsheet", confidence=0.9
                )
            elif b"opendocument.presentation" in mimetype_field:
                return FormatDetectionResult(
                    format=DataFormat.ODP, mime_type="application/vnd.oasis.opendocument.presentation", confidence=0.9
                )
            return FormatDetectionResult(format=DataFormat.ZIP, mime_type="application/zip", confidence=0.85)

        return FormatDetectionResult(format=DataFormat.ZIP, mime_type="application/zip", confidence=0.85)

    def _detect_by_extension(self, filename: str) -> FormatDetectionResult | None:
        """通过扩展名检测格式"""
        ext = Path(filename).suffix.lower()
        if ext in self.EXTENSION_MAP:
            fmt, mime = self.EXTENSION_MAP[ext]
            return FormatDetectionResult(format=fmt, mime_type=mime, confidence=0.7, extension=ext)
        return None

    def _detect_by_content(self, data: bytes) -> FormatDetectionResult | None:
        """通过内容分析检测格式"""
        # 尝试解码为文本
        try:
            text = data[:1024].decode("utf-8", errors="ignore").strip()
        except UnicodeDecodeError:
            return None

        if not text:
            return None

        # JSON 检测
        if text.startswith(("{", "[")):
            try:
                import json

                json.loads(text)
                return FormatDetectionResult(format=DataFormat.JSON, mime_type="application/json", confidence=0.85)
            except (json.JSONDecodeError, ValueError):
                pass

        # XML 检测
        if text.startswith("<?xml") or (text.startswith("<") and ">" in text[:100]):
            return FormatDetectionResult(format=DataFormat.XML, mime_type="application/xml", confidence=0.7)

        # HTML 检测
        html_tags = ["<!DOCTYPE html", "<html", "<head", "<body", "<div", "<p>", "<span"]
        if any(tag in text.lower()[:200] for tag in html_tags):
            return FormatDetectionResult(format=DataFormat.HTML, mime_type="text/html", confidence=0.8)

        # YAML 检测
        if ":" in text[:200] and ("\n" in text or "\r" in text):
            lines = text.split("\n")[:10]
            yaml_indicators = 0
            for line in lines:
                stripped = line.strip()
                if (
                    stripped
                    and not stripped.startswith("#")
                    and ":" in stripped
                    and not stripped.startswith(("-", "*", "|", ">"))
                ):
                    yaml_indicators += 1
            if yaml_indicators >= 3:
                return FormatDetectionResult(format=DataFormat.YAML, mime_type="application/yaml", confidence=0.6)

        # TOML 检测
        if "=" in text[:200] and text.strip().startswith(("#", "[")):
            toml_indicators = 0
            lines = text.split("\n")[:15]
            for line in lines:
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if re.match(r"^\[[\w.]+\]$", stripped):
                    toml_indicators += 2
                elif "=" in stripped and not stripped.startswith(("-", "+", "*", "{", "[")):
                    toml_indicators += 1
            if toml_indicators >= 3:
                return FormatDetectionResult(format=DataFormat.TOML, mime_type="application/toml", confidence=0.7)

        # EML 检测（邮件以 From: 或 Return-Path: 等邮件头开头）
        first_line = text.split("\n")[0].strip()
        if (
            first_line.startswith("From:")
            or first_line.startswith("Return-Path:")
            or first_line.startswith("Received:")
        ):
            eml_headers = ["From:", "To:", "Subject:", "Date:", "Message-ID:", "MIME-Version:", "Content-Type:"]
            header_count = sum(1 for h in eml_headers if h in text[:2048])
            if header_count >= 3:
                return FormatDetectionResult(format=DataFormat.EML, mime_type="message/rfc822", confidence=0.8)

        # SVG 检测
        if 'xmlns="http://www.w3.org/2000/svg"' in text[:1024] or "<svg" in text[:256]:
            return FormatDetectionResult(format=DataFormat.SVG, mime_type="image/svg+xml", confidence=0.8)

        # CSV 检测
        lines = text.split("\n")[:5]
        if len(lines) >= 2:
            first_line = lines[0]
            comma_count = first_line.count(",")
            tab_count = first_line.count("\t")
            if comma_count >= 1 and len(lines) >= 2:
                second_line = lines[1]
                if second_line.count(",") == comma_count or abs(second_line.count(",") - comma_count) <= 2:
                    return FormatDetectionResult(format=DataFormat.CSV, mime_type="text/csv", confidence=0.6)
            if tab_count >= 1:
                return FormatDetectionResult(
                    format=DataFormat.CSV, mime_type="text/tab-separated-values", confidence=0.5
                )

        return None

    def _is_text(self, data: bytes) -> bool:
        """检查数据是否为纯文本"""
        try:
            text = data.decode("utf-8", errors="ignore")
            printable = sum(1 for c in text if c.isprintable() or c in "\n\r\t")
            return len(text) > 0 and printable / len(text) > 0.95
        except Exception:
            return False

    def detect_file(self, file_path: Path) -> FormatDetectionResult:
        """检测文件格式"""
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 读取前 2048 字节用于检测
        with open(file_path, "rb") as f:
            data = f.read(2048)

        return self.detect(data, filename=file_path.name)


# 全局检测器实例
format_detector = FormatDetector()

# 模块级别名：作为整个项目的扩展名映射权威来源
EXTENSION_MAP = FormatDetector.EXTENSION_MAP
