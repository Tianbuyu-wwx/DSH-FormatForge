"""
格式检测器
自动检测输入数据的格式类型
"""
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

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
    # 图片
    PNG = "png"
    JPEG = "jpeg"
    GIF = "gif"
    WEBP = "webp"
    BMP = "bmp"
    TIFF = "tiff"
    # 压缩包
    ZIP = "zip"
    SEVEN_Z = "7z"
    RAR = "rar"
    # 其他
    UNKNOWN = "unknown"
    BINARY = "binary"


@dataclass
class FormatDetectionResult:
    """格式检测结果"""
    format: DataFormat
    mime_type: str
    confidence: float  # 0.0-1.0
    extension: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class FormatDetector:
    """格式检测器 - 通过魔数和内容分析检测数据格式"""

    # 魔数签名表
    MAGIC_SIGNATURES: Dict[bytes, Tuple[DataFormat, str]] = {
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
    EXTENSION_MAP: Dict[str, Tuple[DataFormat, str]] = {
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
    }

    def detect(self, data: bytes, filename: Optional[str] = None) -> FormatDetectionResult:
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
                format=DataFormat.UNKNOWN,
                mime_type="application/octet-stream",
                confidence=0.0
            )

        logger.debug("开始格式检测: data_size=%d, filename=%s", len(data), filename)

        # 1. 尝试魔数检测
        magic_result = self._detect_by_magic(data)
        if magic_result and magic_result.confidence >= 0.9:
            logger.info("格式检测(魔数): format=%s, confidence=%.2f", magic_result.format.value, magic_result.confidence)
            return magic_result

        # 2. 尝试扩展名检测
        ext_result = None
        if filename:
            ext_result = self._detect_by_extension(filename)

        # 3. 尝试内容分析
        content_result = self._detect_by_content(data)

        # 综合判断
        if magic_result and magic_result.confidence >= 0.7:
            logger.info("格式检测(魔数): format=%s, confidence=%.2f", magic_result.format.value, magic_result.confidence)
            return magic_result

        if content_result and content_result.confidence >= 0.8:
            logger.info("格式检测(内容): format=%s, confidence=%.2f", content_result.format.value, content_result.confidence)
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
                extension=ext_result.extension
            )

        # 返回最可能的结果
        if magic_result:
            logger.info("格式检测(魔数回退): format=%s, confidence=%.2f", magic_result.format.value, magic_result.confidence)
            return magic_result
        if ext_result:
            logger.info("格式检测(扩展名回退): format=%s, confidence=%.2f", ext_result.format.value, ext_result.confidence)
            return ext_result
        if content_result:
            logger.info("格式检测(内容回退): format=%s, confidence=%.2f", content_result.format.value, content_result.confidence)
            return content_result

        # 检测是否为纯文本
        if self._is_text(data):
            logger.info("格式检测(纯文本回退): format=txt, confidence=0.5")
            return FormatDetectionResult(
                format=DataFormat.TXT,
                mime_type="text/plain",
                confidence=0.5,
                extension=filename and Path(filename).suffix
            )

        logger.info("格式检测(未知): format=binary, confidence=0.3")
        return FormatDetectionResult(
            format=DataFormat.BINARY,
            mime_type="application/octet-stream",
            confidence=0.3,
            extension=filename and Path(filename).suffix
        )

    def _detect_by_magic(self, data: bytes) -> Optional[FormatDetectionResult]:
        """通过魔数检测格式"""
        if len(data) < 4:
            return None

        # 检查 WEBP（特殊处理，需要检查 RIFF 后面的格式）
        if data[:4] == b"RIFF" and len(data) >= 12:
            if data[8:12] == b"WEBP":
                return FormatDetectionResult(
                    format=DataFormat.WEBP,
                    mime_type="image/webp",
                    confidence=0.95
                )

        # 检查 ZIP 子类型（DOCX/PPTX/XLSX）
        if data[:4] == b"PK\x03\x04":
            return self._detect_zip_subtype(data)

        # 检查其他魔数
        for magic, (fmt, mime) in self.MAGIC_SIGNATURES.items():
            if data[:len(magic)] == magic:
                return FormatDetectionResult(
                    format=fmt,
                    mime_type=mime,
                    confidence=0.95
                )

        return None

    def _detect_zip_subtype(self, data: bytes) -> FormatDetectionResult:
        """检测 ZIP 压缩包的子类型（DOCX/PPTX/XLSX）"""
        # 在 ZIP 的前 1024 字节中查找特征目录名
        header = data[:2048]

        if b"word/" in header:
            return FormatDetectionResult(
                format=DataFormat.DOCX,
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                confidence=0.9
            )
        elif b"ppt/" in header:
            return FormatDetectionResult(
                format=DataFormat.PPTX,
                mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                confidence=0.9
            )
        elif b"xl/" in header:
            return FormatDetectionResult(
                format=DataFormat.XLSX,
                mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                confidence=0.9
            )

        return FormatDetectionResult(
            format=DataFormat.ZIP,
            mime_type="application/zip",
            confidence=0.85
        )

    def _detect_by_extension(self, filename: str) -> Optional[FormatDetectionResult]:
        """通过扩展名检测格式"""
        ext = Path(filename).suffix.lower()
        if ext in self.EXTENSION_MAP:
            fmt, mime = self.EXTENSION_MAP[ext]
            return FormatDetectionResult(
                format=fmt,
                mime_type=mime,
                confidence=0.7,
                extension=ext
            )
        return None

    def _detect_by_content(self, data: bytes) -> Optional[FormatDetectionResult]:
        """通过内容分析检测格式"""
        # 尝试解码为文本
        try:
            text = data[:1024].decode('utf-8', errors='ignore').strip()
        except:
            return None

        if not text:
            return None

        # JSON 检测
        if text.startswith(('{', '[')):
            try:
                import json
                json.loads(text[:512])
                return FormatDetectionResult(
                    format=DataFormat.JSON,
                    mime_type="application/json",
                    confidence=0.85
                )
            except:
                pass

        # XML 检测
        if text.startswith('<?xml') or (text.startswith('<') and '>' in text[:100]):
            return FormatDetectionResult(
                format=DataFormat.XML,
                mime_type="application/xml",
                confidence=0.7
            )

        # HTML 检测
        html_tags = ['<!DOCTYPE html', '<html', '<head', '<body', '<div', '<p>', '<span']
        if any(tag in text.lower()[:200] for tag in html_tags):
            return FormatDetectionResult(
                format=DataFormat.HTML,
                mime_type="text/html",
                confidence=0.8
            )

        # YAML 检测
        if ':' in text[:200] and ('\n' in text or '\r' in text):
            lines = text.split('\n')[:10]
            yaml_indicators = 0
            for line in lines:
                stripped = line.strip()
                if stripped and not stripped.startswith('#'):
                    if ':' in stripped and not stripped.startswith(('-', '*', '|', '>')):
                        yaml_indicators += 1
            if yaml_indicators >= 3:
                return FormatDetectionResult(
                    format=DataFormat.YAML,
                    mime_type="application/yaml",
                    confidence=0.6
                )

        # CSV 检测
        lines = text.split('\n')[:5]
        if len(lines) >= 2:
            first_line = lines[0]
            comma_count = first_line.count(',')
            tab_count = first_line.count('\t')
            if comma_count >= 1 and len(lines) >= 2:
                second_line = lines[1]
                if second_line.count(',') == comma_count or abs(second_line.count(',') - comma_count) <= 2:
                    return FormatDetectionResult(
                        format=DataFormat.CSV,
                        mime_type="text/csv",
                        confidence=0.6
                    )
            if tab_count >= 1:
                return FormatDetectionResult(
                    format=DataFormat.CSV,
                    mime_type="text/tab-separated-values",
                    confidence=0.5
                )

        return None

    def _is_text(self, data: bytes) -> bool:
        """检查数据是否为纯文本"""
        try:
            text = data.decode('utf-8', errors='ignore')
            printable = sum(1 for c in text if c.isprintable() or c in '\n\r\t')
            return len(text) > 0 and printable / len(text) > 0.95
        except:
            return False

    def detect_file(self, file_path: Path) -> FormatDetectionResult:
        """检测文件格式"""
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        # 读取前 2048 字节用于检测
        with open(file_path, 'rb') as f:
            data = f.read(2048)

        return self.detect(data, filename=file_path.name)


# 全局检测器实例
format_detector = FormatDetector()
