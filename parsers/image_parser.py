"""
图片文件解析器
支持解析 JPG/PNG/GIF/WEBP/BMP 等格式
支持 EXIF 元数据提取、OCR 文字识别
"""

import logging
from pathlib import Path
from typing import Any, cast

from core.models import ExtractedElement, PageContent
from parsers import BaseParser

logger = logging.getLogger("parsers.image")

# 可选依赖
try:
    from PIL import Image
    from PIL.ExifTags import TAGS

    IMAGE_AVAILABLE = True
except ImportError:
    IMAGE_AVAILABLE = False
    logger.warning("Pillow 库未安装，图片解析功能不可用")


class ImageParser(BaseParser):
    """图片文件解析器"""

    @property
    def supported_extensions(self) -> list[str]:
        return [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"]

    @property
    def supported_magic(self) -> list[bytes]:
        # 常见图片格式魔数
        return [
            b"\xff\xd8\xff",  # JPEG
            b"\x89PNG\r\n\x1a\n",  # PNG
            b"GIF87a",  # GIF
            b"GIF89a",  # GIF
            b"BM",  # BMP
            b"RIFF",  # WEBP (RIFF....WEBP)
            b"II*\x00",  # TIFF little-endian
            b"MM\x00*",  # TIFF big-endian
        ]

    def __init__(self, ocr_engine=None):
        super().__init__()
        self.ocr_engine = ocr_engine

    def parse(self, file_path: Path, use_ocr: bool = False) -> list[PageContent]:
        """
        解析图片文件

        Args:
            file_path: 图片路径
            use_ocr: 是否使用 OCR 提取图片中的文字
        """
        if not IMAGE_AVAILABLE:
            raise ImportError("Pillow 库未安装，无法处理图片")

        file_path = Path(file_path)
        logger.info("开始解析图片: %s (OCR=%s)", file_path, use_ocr)

        try:
            img = Image.open(file_path)
        except Exception as e:
            logger.error("无法打开图片: %s", e)
            return [
                PageContent(
                    pageNumber=1,
                    elements=[ExtractedElement(elementId="elem_1_0", elementType="text", content=f"无法读取图片: {e}")],
                    rawText=f"[图片读取失败] {e}",
                    hasImage=True,
                    hasTable=False,
                )
            ]

        # 基础信息
        img_info: dict[str, Any] = {
            "format": img.format,
            "size": img.size,
            "mode": img.mode,
            "filename": file_path.name,
        }

        elements = []
        raw_text_parts = [f"[图片文件] {file_path.name}"]

        # 提取 EXIF 元数据
        exif_data = self._extract_exif(img)
        if exif_data:
            img_info["exif"] = exif_data
            exif_text = self._format_exif(exif_data)
            if exif_text:
                elements.append(
                    ExtractedElement(
                        elementId="elem_1_exif", elementType="metadata", content=exif_text, metadata={"exif": exif_data}
                    )
                )
                raw_text_parts.append(exif_text)

        # 基础图片元素
        elements.insert(
            0,
            ExtractedElement(
                elementId="elem_1_0",
                elementType="image",
                content=f"图片: {file_path.name}, 格式={img.format}, 尺寸={img.size}, 模式={img.mode}",
                metadata=img_info,
            ),
        )

        # OCR 文字提取
        ocr_text = ""
        if use_ocr and self.ocr_engine and self.ocr_engine.is_available():
            logger.info("对图片进行 OCR 识别: %s", file_path.name)
            try:
                ocr_result = self.ocr_engine.extract_text_from_image(file_path, use_ai=False)
                ocr_text = ocr_result.text if ocr_result.text else ""
                if ocr_text:
                    elements.append(
                        ExtractedElement(
                            elementId="elem_1_ocr",
                            elementType="text",
                            content=ocr_text,
                            metadata={"ocr": True, "confidence": ocr_result.confidence, "method": ocr_result.method},
                        )
                    )
                    raw_text_parts.append(f"[OCR 识别结果]\n{ocr_text}")
                    logger.info("OCR 识别完成: %d 字符", len(ocr_text))
            except Exception as e:
                logger.error("OCR 识别失败: %s", e)

        img.close()

        return [
            PageContent(
                pageNumber=1, elements=elements, rawText="\n".join(raw_text_parts), hasImage=True, hasTable=False
            )
        ]

    def _extract_exif(self, img: "Image.Image") -> dict[str, Any] | None:
        """提取 EXIF 元数据"""
        try:
            exif = cast(Any, img)._getexif()  # Pillow 私有方法，类型存根未声明
            if not exif:
                return None

            exif_data = {}
            for tag_id, value in exif.items():
                tag_name = TAGS.get(tag_id, f"Tag_{tag_id}")
                # 处理字节数据
                if isinstance(value, bytes):
                    try:
                        value = value.decode("utf-8", errors="ignore")
                    except Exception:
                        value = str(value)
                exif_data[tag_name] = value

            return exif_data
        except Exception as e:
            logger.debug("EXIF 提取失败: %s", e)
            return None

    def _format_exif(self, exif_data: dict[str, Any]) -> str:
        """格式化 EXIF 数据为文本"""
        if not exif_data:
            return ""

        # 选取常用字段
        key_fields = [
            "DateTime",
            "DateTimeOriginal",
            "Make",
            "Model",
            "LensModel",
            "FNumber",
            "ExposureTime",
            "ISOSpeedRatings",
            "FocalLength",
            "ImageWidth",
            "ImageLength",
        ]

        parts = ["[EXIF 信息]"]
        for field in key_fields:
            if field in exif_data:
                parts.append(f"{field}: {exif_data[field]}")

        return "\n".join(parts) if len(parts) > 1 else ""
