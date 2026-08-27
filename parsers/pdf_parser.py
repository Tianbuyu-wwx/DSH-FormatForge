"""
PDF 文件解析器
支持解析 PDF 文档，包含流式解析、表格提取、图片检测、OCR 识别
"""

import logging
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

from core.models import ExtractedElement, PageContent
from parsers import BaseParser

logger = logging.getLogger("parsers.pdf")

# 可选依赖
try:
    import pdfplumber as _pdfplumber_module

    # 模块级别名，使 unittest.mock.patch('parsers.pdf_parser.pdfplumber.open') 能正确解析
    pdfplumber = _pdfplumber_module
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False
    # 模块级占位符，使 unittest.mock.patch('parsers.pdf_parser.pdfplumber.open') 能解析
    # 同时实现上下文管理器协议，避免 stub 在真实代码路径中抛出 TypeError
    import contextlib

    @contextlib.contextmanager
    def _pdfplumber_open_stub(*args, **kwargs):
        """pdfplumber.open 占位实现"""
        yield type("_PdfPage", (), {"pages": [], "__len__": lambda s: 0})()

    pdfplumber = type("_PdfplumberStub", (), {"open": staticmethod(_pdfplumber_open_stub)})  # type: ignore
    logger.warning("pdfplumber 库未安装，PDF 解析功能不可用")


try:
    from PIL import Image  # noqa: F401  (defensive: ensure PIL.Image can be imported)

    IMAGE_AVAILABLE = True
except ImportError:
    IMAGE_AVAILABLE = False


class PDFParser(BaseParser):
    """PDF 文件解析器 - 支持 OCR 识别图片中的文字"""

    def __init__(self, ocr_engine=None):
        super().__init__()
        self.ocr_engine = ocr_engine

    @property
    def supported_extensions(self) -> list[str]:
        return [".pdf"]

    @property
    def supported_magic(self) -> list[bytes]:
        return [b"%PDF"]

    def parse(
        self,
        file_path: Path,
        use_ocr: bool = False,
        ocr_backend: str | None = None,
        ocr_min_confidence: float = 0.5,
        pages: str | None = None,
        drop_furniture: bool = True,
        two_column: bool = True,
    ) -> list[PageContent]:
        """
        解析 PDF 文件

        Args:
            file_path: PDF 文件路径
            use_ocr: 是否对纯图片页使用 OCR
            ocr_backend: 指定 OCR 后端（tesseract/paddleocr/easyocr）
            ocr_min_confidence: OCR 最小置信度阈值
            pages: 页选择表达式，如 "1-3,7"（1-based；None=全部）
            drop_furniture: 剔除跨页重复的页眉/页脚行（E2）
            two_column: 启用双栏阅读序还原（E2）
        """
        return list(
            self.parse_stream(file_path, use_ocr, ocr_backend, ocr_min_confidence, pages, drop_furniture, two_column)
        )

    def parse_stream(
        self,
        file_path: Path,
        use_ocr: bool = False,
        ocr_backend: str | None = None,
        ocr_min_confidence: float = 0.5,
        pages: str | None = None,
        drop_furniture: bool = True,
        two_column: bool = True,
    ) -> Generator[PageContent, None, None]:
        """
        流式解析 PDF 文件，逐页生成（减少内存占用）

        Args:
            file_path: PDF 文件路径
            use_ocr: 是否对纯图片页使用 OCR
            ocr_backend: 指定 OCR 后端
            ocr_min_confidence: OCR 最小置信度阈值
            pages: 页选择表达式 "1-3,7"（1-based；None=全部）
            drop_furniture: 剔除页眉/页脚
            two_column: 双栏阅读序还原

        Yields:
            PageContent: 每一页的内容
        """
        selected = self._parse_page_selection(pages)
        logger.info(
            "开始流式解析 PDF: %s (OCR=%s, backend=%s, pages=%s, furniture=%s)",
            file_path,
            use_ocr,
            ocr_backend,
            pages or "all",
            not drop_furniture,
        )

        try:
            with pdfplumber.open(str(file_path)) as pdf:
                total_pages = len(pdf.pages)
                logger.info("PDF 共 %d 页", total_pages)

                # E2-2: 先扫全书的页首/尾候选行（跨页重复 ≥60% 才判为 furniture）
                furniture = self._detect_furniture(pdf) if drop_furniture else set()

                out_pages: list[PageContent] = []
                for idx, page in enumerate(pdf.pages, 1):
                    if selected and idx not in selected:
                        continue
                    out_pages.append(
                        self._parse_page(
                            page, idx, total_pages, use_ocr, ocr_backend, ocr_min_confidence, furniture, two_column
                        )
                    )

                # R2.3: 结构保真标注（标题层级/列表嵌套/目录锚点），管线唯一入口
                if out_pages:
                    from core.structure_fidelity import annotate

                    stats = annotate(out_pages)
                    if stats.get("headings") or stats.get("toc_entries"):
                        logger.info("[structure] 标注完成: %s", stats)

                # R2.2: 表格语义（None=合并覆盖填充 / 空单元格保留 / 数值列右对齐 / 跨页续接）
                if out_pages and any(p.hasTable for p in out_pages):
                    from core.table_semantics import upgrade_table_elements

                    tstats = upgrade_table_elements(out_pages)
                    if tstats.get("normalized"):
                        logger.info("[table-semantics] %s", tstats)

                yield from out_pages
        except Exception as e:
            logger.error("PDF 解析失败: %s", e)
            raise ValueError(f"PDF 解析失败: {e}") from e

    @staticmethod
    def _parse_page_selection(pages: str | None) -> set[int] | None:
        """解析 "1-3,7" 形式的页选择表达式为 1-based 页号集合。"""
        if not pages or not pages.strip():
            return None
        selected: set[int] = set()
        for part in pages.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                lo_s, hi_s = part.split("-", 1)
                lo, hi = int(lo_s), int(hi_s)
                if lo < 1 or hi < lo:
                    raise ValueError(f"非法页范围: {part}")
                selected.update(range(lo, hi + 1))
            else:
                n = int(part)
                if n < 1:
                    raise ValueError(f"非法页号: {part}")
                selected.add(n)
        return selected or None

    #: furniture 判定：某行文本在全书出现于页首/尾的比例阈值
    _FURNITURE_RATIO = 0.6
    #: 只检查每页前/后 N 行
    _FURNITURE_EDGE_LINES = 3

    def _detect_furniture(self, pdf) -> set[str]:
        """扫描全书，返回判定为页眉/页脚的文本行集合。

        判定：出现在 ≥60% 页面的前 3 行或后 3 行中的相同文本行。
        单页文档不启用（无统计意义）。
        """
        from collections import Counter

        try:
            total = len(pdf.pages)
            if total < 3:
                return set()
            counter: Counter[str] = Counter()
            for page in pdf.pages:
                text = (page.extract_text() or "").strip()
                if not text:
                    continue
                lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
                edges = lines[: self._FURNITURE_EDGE_LINES] + lines[-self._FURNITURE_EDGE_LINES :]
                for ln in set(edges):
                    counter[ln] += 1
            threshold = max(total * self._FURNITURE_RATIO, 2)
            found = {ln for ln, n in counter.items() if n >= threshold}
            if found:
                logger.info("[furniture] 检测到 %d 条页眉/页脚行", len(found))
            return found
        except Exception as e:
            logger.debug("furniture 检测失败（忽略）: %s", e)
            return set()

    @staticmethod
    def _strip_furniture(text: str, furniture: set[str]) -> tuple[str, int]:
        """从页面文本中剔除 furniture 行，返回 (新文本, 剔除行数)。"""
        if not text or not furniture:
            return text, 0
        lines = text.splitlines()
        kept = [ln for ln in lines if ln.strip() not in furniture]
        removed = len(lines) - len(kept)
        return "\n".join(kept).strip("\n"), removed

    def _parse_page(
        self,
        page,
        page_number: int,
        total_pages: int,
        use_ocr: bool = False,
        ocr_backend: str | None = None,
        ocr_min_confidence: float = 0.5,
        furniture: set[str] | None = None,
        two_column: bool = True,
    ) -> PageContent:
        """解析单页 PDF，支持 OCR 识别纯图片页和混合页"""
        text = page.extract_text() or ""

        # E2-3: 双栏阅读序还原 —— 页宽>高且词框呈左右两簇时按栏拼接
        if two_column and self._looks_two_column(page):
            text = self._reorder_two_column(page)

        # E2-2: 剔除页眉/页脚行
        furniture_removed = 0
        if furniture:
            text, furniture_removed = self._strip_furniture(text, furniture)

        elements = []
        ocr_used = False
        ocr_confidence = 0.0

        # 尝试提取表格
        tables = page.extract_tables()
        has_table = len(tables) > 0

        # 检测页面是否有图片
        has_image = self._detect_images(page)

        # 智能 OCR 触发策略
        should_ocr = self._should_use_ocr(text, has_image, use_ocr)

        if should_ocr and self.ocr_engine and self.ocr_engine.is_available():
            logger.info("第 %d 页触发 OCR (文字=%s, 图片=%s)", page_number, bool(text.strip()), has_image)
            ocr_result = self._ocr_page(page, page_number, ocr_backend)

            if ocr_result.text:
                ocr_confidence = ocr_result.confidence

                # 如果 OCR 置信度足够高，使用 OCR 结果
                if ocr_confidence >= ocr_min_confidence:
                    if not text.strip():
                        # 纯图片页：完全使用 OCR 结果
                        text = ocr_result.text
                        ocr_used = True
                        has_image = True
                    else:
                        # 混合页：合并文字层和 OCR 结果
                        text = self._merge_text_and_ocr(text, ocr_result.text)
                        ocr_used = True
                else:
                    logger.warning(
                        "第 %d 页 OCR 置信度 %.2f 低于阈值 %.2f，跳过", page_number, ocr_confidence, ocr_min_confidence
                    )

        # 将文本按行分割为元素（R2.3: 附带字号/加粗/行首x0元数据供结构保真判定）
        from core.structure_fidelity import line_font_stats

        font_by_line: dict[str, tuple[float, bool, float]] = {}
        for st in line_font_stats(page):
            font_by_line.setdefault(st["text"], (st["size"], st["bold"], st["x0"]))

        lines = text.strip().split("\n")
        for line_idx, line in enumerate(lines):
            if line.strip():
                elem_type = self._detect_element_type(line)
                metadata: dict[str, Any] = {}
                if ocr_used:
                    metadata["ocr"] = True
                    metadata["ocr_confidence"] = ocr_confidence
                    metadata["ocr_backend"] = ocr_backend or "default"
                font_info = font_by_line.get(self._norm_line(line))
                if font_info:
                    metadata["font_size"], metadata["bold"], metadata["line_x0"] = font_info
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_{page_number}_{line_idx}",
                        elementType=elem_type,
                        content=line.strip(),
                        metadata=metadata if metadata else None,
                    )
                )

        # 如果有表格，添加表格元素（R2.2: 原始 grid 随 metadata 携带，供表格语义层使用）
        if tables:
            for table_idx, table in enumerate(tables):
                table_text = self._format_table(table)
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_{page_number}_table_{table_idx}",
                        elementType="table",
                        content=table_text,
                        metadata={
                            "table_index": table_idx,
                            "rows": len(table),
                            "cols": len(table[0]) if table else 0,
                            "page": page_number,
                            "grid": table,
                        },
                    )
                )

        logger.debug(
            "PDF 第 %d/%d 页解析完成: %d 个元素, 表格=%s, 图片=%s, OCR=%s, 置信度=%.2f",
            page_number,
            total_pages,
            len(elements),
            has_table,
            has_image,
            ocr_used,
            ocr_confidence,
        )

        page_content = PageContent(
            pageNumber=page_number, elements=elements, rawText=text, hasImage=has_image, hasTable=has_table
        )
        # E2-2: furniture 剔除统计挂到页元数据（供质量报告引用）
        if furniture_removed > 0:
            page_content.metadata = {"furniture_removed": furniture_removed}
        return page_content

    # ==================== E2-3: 双栏阅读序 ====================

    #: 双栏判定：页面宽高比下限
    _TWO_COL_ASPECT = 1.0
    #: 中缝空白带宽度（相对页宽）
    _GUTTER_RATIO = 0.04

    def _looks_two_column(self, page) -> bool:
        """检测页面是否为双栏排版：宽>高 + 词框 x 分布呈左右两簇且中缝清晰。"""
        try:
            w, h = float(page.width), float(page.height)
            if h == 0 or w / h < self._TWO_COL_ASPECT:
                return False
            words = page.extract_words() or []
            if len(words) < 30:
                return False
            gutter_lo = w * (0.5 - self._GUTTER_RATIO)
            gutter_hi = w * (0.5 + self._GUTTER_RATIO)
            crossing = [wd for wd in words if wd["x0"] < gutter_hi and wd["x1"] > gutter_lo]
            left = [wd for wd in words if wd["x1"] <= gutter_lo]
            right = [wd for wd in words if wd["x0"] >= gutter_hi]
            total = len(words)
            return len(crossing) / total < 0.05 and len(left) > total * 0.25 and len(right) > total * 0.25
        except Exception as e:
            logger.debug("双栏检测失败（按单栏处理）: %s", e)
            return False

    def _reorder_two_column(self, page) -> str:
        """按左栏全部行 → 右栏全部行的顺序重建文本。"""
        try:
            w = float(page.width)
            gutter_lo = w * (0.5 - self._GUTTER_RATIO)
            gutter_hi = w * (0.5 + self._GUTTER_RATIO)
            words = page.extract_words() or []

            def cluster_text(side_words):
                lines_by_top: dict[float, list[tuple[float, str]]] = {}
                for wd in side_words:
                    key = round(wd["top"] / 3) * 3  # 3pt 容差聚行
                    lines_by_top.setdefault(key, []).append((float(wd["x0"]), str(wd["text"])))
                out = []
                for key in sorted(lines_by_top):
                    line = " ".join(t for _, t in sorted(lines_by_top[key]))
                    if line.strip():
                        out.append(line.strip())
                return out

            left = [wd for wd in words if wd["x1"] <= gutter_hi]
            right = [wd for wd in words if wd["x0"] >= gutter_lo]
            full = [wd for wd in words if wd["x0"] < gutter_hi and wd["x1"] > gutter_lo]
            # 跨中缝的整行元素（如标题）保持原顺序放在最前
            head_lines = cluster_text(full)
            body = cluster_text(left) + cluster_text(right)
            return "\n".join(head_lines + body)
        except Exception as e:
            logger.debug("双栏重排失败（回退原文本）: %s", e)
            return page.extract_text() or ""

    def _should_use_ocr(self, text: str, has_image: bool, use_ocr: bool) -> bool:
        """
        智能判断是否应该使用 OCR

        策略：
        1. 如果未启用 OCR，不使用
        2. 如果页面无文字但有图片，使用 OCR
        3. 如果页面有文字但文字很少（<20 字符）且有图片，使用 OCR 补充
        4. 如果页面有文字但文字看起来是乱码（非中文/英文/数字比例低），使用 OCR
        """
        if not use_ocr:
            return False

        text = text.strip()

        # 无文字但有图片
        if not text and has_image:
            return True

        # 文字很少但有图片（可能是扫描件中的少量文字）
        if len(text) < 20 and has_image:
            return True

        # 文字看起来像乱码
        return bool(text and self._looks_like_garbage(text))

    def _looks_like_garbage(self, text: str) -> bool:
        """判断文字是否看起来像乱码"""
        if not text:
            return False

        # 计算可打印字符比例
        printable_chars = sum(1 for c in text if c.isprintable() or c.isspace())
        if len(text) > 0 and printable_chars / len(text) < 0.8:
            return True

        # 计算中文字符比例
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        total_chars = len([c for c in text if c.isalpha()])

        if total_chars > 0 and chinese_chars / total_chars < 0.1:
            # 如果字母很多但中文很少，可能是乱码或纯英文
            # 进一步检查是否有常见乱码特征
            garbage_patterns = ["ï¿½", "Ã", "Â", "�", "æ", "ç"]
            if any(p in text for p in garbage_patterns):
                return True

        return False

    def _merge_text_and_ocr(self, pdf_text: str, ocr_text: str) -> str:
        """合并 PDF 文字层和 OCR 识别结果"""
        pdf_lines = set(line.strip() for line in pdf_text.split("\n") if line.strip())
        ocr_lines = [line.strip() for line in ocr_text.split("\n") if line.strip()]

        merged = []
        for line in ocr_lines:
            # 如果 OCR 行与 PDF 文字层高度相似，使用 PDF 文字（更准确）
            if any(self._text_similarity(line, pdf_line) > 0.8 for pdf_line in pdf_lines):
                # 找到最相似的 PDF 行
                best_match = max(pdf_lines, key=lambda p: self._text_similarity(line, p))
                merged.append(best_match)
            else:
                # OCR 识别到的新内容
                merged.append(line)

        # 添加 PDF 中独有的内容
        ocr_set = set(merged)
        for pdf_line in pdf_lines:
            if not any(self._text_similarity(pdf_line, o) > 0.8 for o in ocr_set):
                merged.append(pdf_line)

        return "\n".join(merged)

    def _text_similarity(self, a: str, b: str) -> float:
        """计算两段文字的相似度（简单版本）"""
        if not a or not b:
            return 0.0

        a = a.lower().replace(" ", "")
        b = b.lower().replace(" ", "")

        if a == b:
            return 1.0

        # 计算最长公共子序列比例
        from difflib import SequenceMatcher

        return SequenceMatcher(None, a, b).ratio()

    def _ocr_page(self, page, page_number: int, ocr_backend: str | None = None):
        """对单页进行 OCR 识别"""
        try:
            page_image = page.to_image(resolution=200)

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                temp_path = Path(tmp.name)
            page_image.save(str(temp_path), format="PNG")

            result = self.ocr_engine.extract_text_from_image(temp_path, backend=ocr_backend, apply_postprocess=True)

            if temp_path.exists():
                temp_path.unlink()

            return result
        except Exception as e:
            logger.error("OCR 第 %d 页失败: %s", page_number, e)
            from ocr_engine import OcrResult

            return OcrResult(page_number=page_number, text="", confidence=0.0, method="none")

    def _detect_images(self, page) -> bool:
        """检测页面是否包含图片"""
        try:
            if hasattr(page, "images") and page.images:
                return len(page.images) > 0

            if hasattr(page, "objects"):
                for obj_type in page.objects:
                    if "image" in obj_type.lower():
                        return True

            return False
        except Exception:
            return False

    @staticmethod
    def _norm_line(line: str) -> str:
        """与 structure_fidelity.line_font_stats 对齐的行规范化（多空白折叠）。"""
        import re

        return re.sub(r"\s+", " ", (line or "").strip())

    def _detect_element_type(self, text: str) -> str:
        """检测文本元素类型"""
        text = text.strip()
        if not text:
            return "empty"

        if len(text) < 100 and (text.endswith("：") or text.endswith(":")):
            return "heading"

        if "\t" in text or ("|" in text and text.count("|") > 2):
            return "table"

        if text.startswith(("•", "-", "*", "1.", "2.", "（", "(")):
            return "list"

        if text.lower() in ["image", "图片", "[image]", "[图片]"]:
            return "image"

        return "text"

    def _format_table(self, table: list[list[str | None]]) -> str:
        """格式化表格为文本"""
        if not table:
            return ""

        lines = []
        for row in table:
            cells = [str(cell) if cell is not None else "" for cell in row]
            lines.append(" | ".join(cells))

        return "\n".join(lines)

    def extract_text_summary(self, file_path: Path, max_length: int = 8000) -> str:
        """提取 PDF 文本摘要"""
        summary_parts = []
        current_length = 0

        for page in self.parse_stream(file_path):
            page_text = f"""
【第 {page.pageNumber} 页】
{page.rawText}
"""
            if current_length + len(page_text) > max_length:
                remaining = max_length - current_length
                if remaining > 0:
                    summary_parts.append(page_text[:remaining])
                summary_parts.append("\n... (内容已截断)")
                break

            summary_parts.append(page_text)
            current_length += len(page_text)

        return "\n---\n".join(summary_parts)

    def extract_tables(self, file_path: Path) -> list[dict]:
        """提取 PDF 中的所有表格"""
        if not PDFPLUMBER_AVAILABLE:
            raise ImportError("pdfplumber 库未安装，无法提取表格")

        tables = []

        with pdfplumber.open(str(file_path)) as pdf:
            for page_idx, page in enumerate(pdf.pages, 1):
                page_tables = page.extract_tables()
                for table_idx, table in enumerate(page_tables):
                    tables.append(
                        {
                            "page": page_idx,
                            "table_index": table_idx,
                            "data": table,
                            "rows": len(table),
                            "cols": len(table[0]) if table else 0,
                        }
                    )

        return tables
