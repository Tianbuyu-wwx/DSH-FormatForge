"""
OCR 引擎模块
支持从 PDF、图片中提取文字
集成多模态 AI 进行图片文字识别
支持多引擎切换：Tesseract / PaddleOCR / EasyOCR / AI
"""

import logging
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("ocr_engine")

# 可选依赖
try:
    import pdfplumber as _pdfplumber_module

    pdfplumber = _pdfplumber_module
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    import contextlib

    @contextlib.contextmanager
    def _pdfplumber_open_stub(*args, **kwargs):
        yield type("_PdfPage", (), {"pages": [], "__len__": lambda s: 0})()

    pdfplumber = type("_PdfplumberStub", (), {"open": staticmethod(_pdfplumber_open_stub)})  # type: ignore

try:
    from PIL import Image

    IMAGE_AVAILABLE = True
except ImportError:
    IMAGE_AVAILABLE = False

try:
    import pytesseract

    TESSERACT_AVAILABLE = True
except ImportError:
    pytesseract = None
    TESSERACT_AVAILABLE = False

try:
    from paddleocr import PaddleOCR

    PADDLEOCR_AVAILABLE = True
except ImportError:
    PADDLEOCR_AVAILABLE = False

try:
    import easyocr

    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False


@dataclass
class OcrResult:
    """OCR 识别结果"""

    page_number: int
    text: str
    confidence: float
    method: str  # "tesseract" | "paddleocr" | "easyocr" | "ai" | "pdfplumber"
    image_path: str | None = None


class BaseOcrBackend(ABC):
    """OCR 后端抽象基类"""

    @abstractmethod
    def recognize(self, image_path: Path) -> tuple[str, float]:
        """识别图片，返回 (文字, 置信度)"""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """后端名称"""
        pass


class TesseractBackend(BaseOcrBackend):
    """Tesseract OCR 后端"""

    def __init__(self, lang: str = "chi_sim+eng"):
        self.lang = lang

    @property
    def name(self) -> str:
        return "tesseract"

    def recognize(self, image_path: Path) -> tuple[str, float]:
        if not TESSERACT_AVAILABLE:
            return "", 0.0
        try:
            text = pytesseract.image_to_string(str(image_path), lang=self.lang)
            return text.strip(), 0.75
        except Exception as e:
            logger.error("Tesseract 识别失败: %s", e)
            return "", 0.0


class PaddleOcrBackend(BaseOcrBackend):
    """PaddleOCR 后端"""

    def __init__(self, use_angle_cls: bool = True, lang: str = "ch"):
        self.use_angle_cls = use_angle_cls
        self.lang = lang
        self._ocr = None

    @property
    def name(self) -> str:
        return "paddleocr"

    def _get_ocr(self):
        if self._ocr is None:
            self._ocr = PaddleOCR(use_angle_cls=self.use_angle_cls, lang=self.lang, show_log=False)
        return self._ocr

    def recognize(self, image_path: Path) -> tuple[str, float]:
        if not PADDLEOCR_AVAILABLE:
            return "", 0.0
        try:
            result = self._get_ocr().ocr(str(image_path), cls=True)
            if not result or not result[0]:
                return "", 0.0

            lines = []
            total_conf = 0.0
            count = 0
            for line in result[0]:
                bbox, (text, conf) = line
                lines.append(text)
                total_conf += conf
                count += 1

            avg_conf = total_conf / count if count > 0 else 0.0
            return "\n".join(lines), avg_conf
        except Exception as e:
            logger.error("PaddleOCR 识别失败: %s", e)
            return "", 0.0


class EasyOcrBackend(BaseOcrBackend):
    """EasyOCR 后端"""

    def __init__(self, lang_list: list[str] | None = None):
        self.lang_list = lang_list or ["ch_sim", "en"]
        self._reader = None

    @property
    def name(self) -> str:
        return "easyocr"

    def _get_reader(self):
        if self._reader is None:
            self._reader = easyocr.Reader(self.lang_list, gpu=False, verbose=False)
        return self._reader

    def recognize(self, image_path: Path) -> tuple[str, float]:
        if not EASYOCR_AVAILABLE:
            return "", 0.0
        try:
            result = self._get_reader().readtext(str(image_path))
            if not result:
                return "", 0.0

            lines = []
            total_conf = 0.0
            for _bbox, text, conf in result:
                lines.append(text)
                total_conf += conf

            avg_conf = total_conf / len(result) if result else 0.0
            return "\n".join(lines), avg_conf
        except Exception as e:
            logger.error("EasyOCR 识别失败: %s", e)
            return "", 0.0


class AiOcrBackend(BaseOcrBackend):
    """AI 多模态 OCR 后端"""

    def __init__(self, ai_client):
        self.ai_client = ai_client

    @property
    def name(self) -> str:
        return "ai"

    def recognize(self, image_path: Path) -> tuple[str, float]:
        if not self.ai_client:
            return "", 0.0
        try:
            prompt = """
请识别这张图片中的所有文字内容，包括：
1. 标题和正文
2. 表格中的数据
3. 图表中的标签和数值
4. 页眉页脚信息

请按原文格式输出所有识别到的文字，不要添加额外解释。
如果包含表格，请用 Markdown 表格格式输出。
"""
            result = self.ai_client.generate_text(prompt, [str(image_path)])
            return result.strip(), 0.85
        except Exception as e:
            logger.error("AI OCR 失败: %s", e)
            return "", 0.0


class OcrPostProcessor:
    """OCR 后处理器：排版还原"""

    @staticmethod
    def process(text: str) -> str:
        """
        对 OCR 识别结果进行后处理

        包括：
        1. 去除多余空行
        2. 合并断行
        3. 检测并还原段落
        4. 检测并还原列表
        5. 检测并还原表格
        """
        if not text:
            return text

        lines = text.split("\n")
        processed = []

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if not line:
                i += 1
                continue

            # 检测表格行（包含多个空格或制表符分隔）
            if OcrPostProcessor._is_table_line(line):
                table_lines = [line]
                i += 1
                while i < len(lines) and OcrPostProcessor._is_table_line(lines[i]):
                    table_lines.append(lines[i].strip())
                    i += 1
                processed.append(OcrPostProcessor._format_table(table_lines))
                continue

            # 检测列表项
            if OcrPostProcessor._is_list_item(line):
                processed.append(line)
                i += 1
                continue

            # 检测段落（当前行不以标点结尾，下一行不是空行且不以大写/数字开头）
            para_lines = [line]
            i += 1
            while i < len(lines) and lines[i].strip() and not OcrPostProcessor._is_new_paragraph(lines[i].strip()):
                para_lines.append(lines[i].strip())
                i += 1

            if len(para_lines) > 1:
                processed.append(" ".join(para_lines))
            else:
                processed.append(para_lines[0])

        return "\n\n".join(processed)

    @staticmethod
    def _is_table_line(line: str) -> bool:
        """判断是否为表格行"""
        # 包含多个制表符或多个连续空格
        if "\t" in line:
            return line.count("\t") >= 1
        # 或包含竖线分隔符
        if "|" in line and line.count("|") >= 2:
            return True
        # 或包含多个连续空格（至少3个空格分隔）
        parts = [p for p in line.split("  ") if p.strip()]
        return len(parts) >= 2 and len(parts) <= 10

    @staticmethod
    def _format_table(lines: list[str]) -> str:
        """格式化表格行"""
        if not lines:
            return ""
        # 尝试用制表符或竖线分割
        rows = []
        for line in lines:
            if "|" in line:
                cells = [c.strip() for c in line.split("|") if c.strip()]
            elif "\t" in line:
                cells = [c.strip() for c in line.split("\t")]
            else:
                cells = [c.strip() for c in line.split("  ") if c.strip()]
            rows.append(" | ".join(cells))
        return "\n".join(rows)

    @staticmethod
    def _is_list_item(line: str) -> bool:
        """判断是否为列表项"""
        return bool(
            line.startswith(("•", "-", "*", "·"))
            or line.startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "0."))
            or line.startswith(("(1)", "(2)", "(3)", "①", "②", "③"))
            or line.startswith(("一、", "二、", "三、", "四、", "五、"))
        )

    @staticmethod
    def _is_new_paragraph(line: str) -> bool:
        """判断是否为新段落的开头"""
        if not line:
            return True
        # 以标题特征开头
        if line.startswith(("#", "##", "###")):
            return True
        # 以列表特征开头
        if OcrPostProcessor._is_list_item(line):
            return True
        # 以数字或字母开头（可能是新段落）
        if line[0].isdigit() or line[0].isupper():
            return True
        # 以中文数字开头
        return line[0] in "一二三四五六七八九十"


class OcrEngine:
    """
    OCR 引擎

    支持多种识别方式：
    1. pdfplumber 内置 OCR（PDF 文字层）
    2. Tesseract OCR（本地开源 OCR）
    3. PaddleOCR（百度开源，中文效果好）
    4. EasyOCR（支持多语言）
    5. AI 多模态识别（MiniMax 等，用于复杂图片）
    """

    def __init__(self, ai_client=None, default_backend: str = "tesseract"):
        self.ai_client = ai_client
        self.default_backend = default_backend
        self.logger = logging.getLogger("ocr_engine")

        # 初始化后端
        self._backends: dict[str, BaseOcrBackend] = {}
        self._init_backends()

    def _init_backends(self):
        """初始化所有可用的 OCR 后端"""
        if TESSERACT_AVAILABLE:
            self._backends["tesseract"] = TesseractBackend()
        if PADDLEOCR_AVAILABLE:
            self._backends["paddleocr"] = PaddleOcrBackend()
        if EASYOCR_AVAILABLE:
            self._backends["easyocr"] = EasyOcrBackend()
        if self.ai_client:
            self._backends["ai"] = AiOcrBackend(self.ai_client)

    def set_default_backend(self, backend: str):
        """设置默认 OCR 后端"""
        if backend not in self._backends:
            raise ValueError(f"OCR 后端不可用: {backend}。可用后端: {list(self._backends.keys())}")
        self.default_backend = backend
        self.logger.info("默认 OCR 后端设置为: %s", backend)

    def get_available_backends(self) -> list[str]:
        """获取所有可用的后端名称"""
        return list(self._backends.keys())

    def extract_text_from_pdf(
        self, pdf_path: Path, use_ai_for_images: bool = False, backend: str | None = None, apply_postprocess: bool = True
    ) -> list[OcrResult]:
        """
        从 PDF 中提取文字，包括图片中的文字

        Args:
            pdf_path: PDF 文件路径
            use_ai_for_images: 是否使用 AI 识别图片中的文字
            backend: 指定 OCR 后端，None 使用默认
            apply_postprocess: 是否应用后处理

        Returns:
            List[OcrResult]: 每页的识别结果
        """
        if not PDFPLUMBER_AVAILABLE:
            raise ImportError("pdfplumber 库未安装")

        results = []
        ocr_backend = self._backends.get(backend or self.default_backend)

        with pdfplumber.open(str(pdf_path)) as pdf:
            for page_idx, page in enumerate(pdf.pages, 1):
                text = page.extract_text() or ""

                if text.strip():
                    results.append(
                        OcrResult(page_number=page_idx, text=text.strip(), confidence=0.95, method="pdfplumber")
                    )
                else:
                    self.logger.info("第 %d 页无文字层，尝试 OCR", page_idx)
                    ocr_text = self._ocr_page_images(page, page_idx, use_ai=use_ai_for_images, backend=ocr_backend)
                    if apply_postprocess and ocr_text:
                        ocr_text = OcrPostProcessor.process(ocr_text)

                    method = ocr_backend.name if ocr_backend else "none"
                    if use_ai_for_images and self.ai_client:
                        method = "ai"

                    results.append(
                        OcrResult(
                            page_number=page_idx, text=ocr_text, confidence=0.7 if ocr_text else 0.0, method=method
                        )
                    )

        return results

    def _ocr_page_images(self, page, page_number: int, use_ai: bool = False, backend: BaseOcrBackend = None) -> str:
        """对页面的图片进行 OCR"""
        texts = []

        try:
            page_image = page.to_image(resolution=200)

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                temp_path = Path(tmp.name)
            page_image.save(str(temp_path), format="PNG")

            if use_ai and self.ai_client and "ai" in self._backends:
                text, _ = self._backends["ai"].recognize(temp_path)
            elif backend:
                text, _ = backend.recognize(temp_path)
            else:
                text = ""

            if text.strip():
                texts.append(text)

            if temp_path.exists():
                temp_path.unlink()

        except Exception as e:
            self.logger.error("OCR 第 %d 页失败: %s", page_number, e)

        return "\n".join(texts)

    def extract_text_from_image(
        self, image_path: Path, use_ai: bool = False, backend: str | None = None, apply_postprocess: bool = True
    ) -> OcrResult:
        """
        从图片中提取文字

        Args:
            image_path: 图片路径
            use_ai: 是否使用 AI 识别
            backend: 指定 OCR 后端
            apply_postprocess: 是否应用后处理

        Returns:
            OcrResult: 识别结果
        """
        if not IMAGE_AVAILABLE:
            raise ImportError("Pillow 库未安装")

        ocr_backend = None
        if use_ai and self.ai_client and "ai" in self._backends:
            ocr_backend = self._backends["ai"]
        elif backend and backend in self._backends:
            ocr_backend = self._backends[backend]
        elif self.default_backend in self._backends:
            ocr_backend = self._backends[self.default_backend]

        if not ocr_backend:
            return OcrResult(page_number=1, text="", confidence=0.0, method="none", image_path=str(image_path))

        text, confidence = ocr_backend.recognize(image_path)

        if apply_postprocess and text:
            text = OcrPostProcessor.process(text)

        return OcrResult(
            page_number=1, text=text, confidence=confidence, method=ocr_backend.name, image_path=str(image_path)
        )

    def batch_ocr(
        self, image_paths: list[Path], use_ai: bool = False, backend: str | None = None, apply_postprocess: bool = True
    ) -> list[OcrResult]:
        """批量 OCR 识别"""
        results = []
        for idx, path in enumerate(image_paths, 1):
            self.logger.info("OCR 处理: %s (%d/%d)", path.name, idx, len(image_paths))
            result = self.extract_text_from_image(
                path, use_ai=use_ai, backend=backend, apply_postprocess=apply_postprocess
            )
            result.page_number = idx
            results.append(result)
        return results

    def is_available(self) -> bool:
        """检查 OCR 是否可用"""
        return len(self._backends) > 0

    def get_status(self) -> dict[str, Any]:
        """获取 OCR 引擎状态"""
        return {
            "pdfplumber": PDFPLUMBER_AVAILABLE,
            "tesseract": TESSERACT_AVAILABLE,
            "paddleocr": PADDLEOCR_AVAILABLE,
            "easyocr": EASYOCR_AVAILABLE,
            "ai_client": self.ai_client is not None,
            "available_backends": self.get_available_backends(),
            "default_backend": self.default_backend,
            "available": self.is_available(),
        }
