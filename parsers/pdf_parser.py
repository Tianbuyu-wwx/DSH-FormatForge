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
from core.table_semantics import escape_md_cell
from parsers import BaseParser

logger = logging.getLogger("parsers.pdf")

#: FF-M-pdf/audit: 加密 PDF 的稳定标记。ParseStep 依赖它把错误上抛（而不是吞掉
#: 之后退化成 raw 透传假成功），入口据此报 parse_failed。
PDF_PASSWORD_MARKER = "password-protected"

#: 判为「加密/密码」失败的异常类名（pdfminer / pypdf / PyPDF2 系）
_PASSWORD_ERROR_NAMES = frozenset(
    {"PDFEncryptionError", "PDFPasswordIncorrect", "FileNotDecryptedError", "PdfReadError"}
)
#: 兜底文本线索（小写匹配）
_PASSWORD_ERROR_HINTS = ("password", "decrypt", "encrypt")

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


def _iter_exc_chain(exc: BaseException) -> list[BaseException]:
    """展开异常链（外层→内层）：含 ``__cause__``/``__context__`` 与 args 包装。

    pdfplumber 用 ``PdfminerException(e)`` 把 pdfminer 异常塞进 ``args``，所以
    只看 ``isinstance`` 不够。
    """
    seen: set[int] = set()
    queue: list[BaseException] = [exc]
    chain: list[BaseException] = []
    while queue:
        cur = queue.pop(0)
        if id(cur) in seen:
            continue
        seen.add(id(cur))
        chain.append(cur)
        for attr in ("__cause__", "__context__"):
            nxt = getattr(cur, attr, None)
            if isinstance(nxt, BaseException):
                queue.append(nxt)
        for arg in getattr(cur, "args", ()) or ():
            if isinstance(arg, BaseException):
                queue.append(arg)
    return chain


def _is_password_error(exc: BaseException) -> bool:
    """FF-M-pdf/audit: 判断异常链里是否有「PDF 需要密码/已加密」信号。

    覆盖 pdfminer / pypdf / PyPDF2 系的类名，另加文本线索兜底。
    """
    for cur in _iter_exc_chain(exc):
        if any(cls.__name__ in _PASSWORD_ERROR_NAMES for cls in type(cur).__mro__):
            return True
        if any(hint in str(cur).lower() for hint in _PASSWORD_ERROR_HINTS):
            return True
    return False


def _password_error_detail(exc: BaseException) -> str:
    """给「需要密码」错误取一段可读细节（包装层 ``str()`` 常为空）。"""
    chain = _iter_exc_chain(exc)
    for idx, cur in enumerate(chain):
        text = str(cur).strip()
        if text:
            return text if idx == 0 else f"{type(cur).__name__}: {text}"
    return type(chain[-1]).__name__ if len(chain) > 1 else type(exc).__name__


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
        解析 PDF 文件，返回选中页的 PageContent 序列。

        FF-L-pdf/audit: 这个方法名为 parse_stream 且旧 docstring 声称「逐页生成
        （减少内存占用）」，但实际实现是把所有选中页解析完、做完全书级标注
        （structure_fidelity 需要跨页字号中位数、table_semantics 需要跨页表格
        合并）后才一次性 yield —— 即「缓冲全部选中页」。逐页真流式会牺牲这两项
        全书级质量增强，故这里选择修正文档而非改语义：本方法是“生成器形态的批量
        解析”，调用方拿到的是完整的选中页列表（顺序按 pages 请求序）。

        Args:
            file_path: PDF 文件路径
            use_ocr: 是否对纯图片页使用 OCR
            ocr_backend: 指定 OCR 后端
            ocr_min_confidence: OCR 最小置信度阈值
            pages: 页选择表达式 "1-3,7"（1-based；None=全部）
            drop_furniture: 剔除页眉/页脚
            two_column: 双栏阅读序还原

        Yields:
            PageContent: 选中页的内容（在全部解析与全书标注完成后按请求序产出）
        """
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
                # FF-M-pdf/audit: 有些加密 PDF 能打开但不可提取（owner 口令 +
                # 限制位）——同样必须显式报「需要密码」，不能静默产出空内容。
                doc = getattr(pdf, "doc", None)
                if doc is not None and getattr(doc, "is_extractable", True) is False:
                    raise ValueError(
                        f"PDF 已加密（{PDF_PASSWORD_MARKER}）：{file_path.name} 不允许内容提取，"
                        f"当前不支持密码输入；请提供已解密副本。"
                    )
                total_pages = len(pdf.pages)
                logger.info("PDF 共 %d 页", total_pages)

                # T2-4: PDF 页数已知后先校验端点与选择上限，再展开一次有序列表；
                # lookup set 只从这个已受限列表构建，攻击者不能控制巨型分配。
                from core.pdf_enhance import parse_pages_spec_ordered

                selection_order = parse_pages_spec_ordered(pages, max_page=total_pages)
                selected = set(selection_order) if selection_order else None

                # E2-2: 先扫全书的页首/尾候选行（跨页重复 ≥60% 才判为 furniture）
                furniture = self._detect_furniture(pdf) if drop_furniture else set()

                out_map: dict[int, PageContent] = {}
                for idx, page in enumerate(pdf.pages, 1):
                    if selected and idx not in selected:
                        continue
                    out_map[idx] = self._parse_page(
                        page, idx, total_pages, use_ocr, ocr_backend, ocr_min_confidence, furniture, two_column
                    )

                # H16/audit: 保留请求顺序——selection 是 set 时输出曾按文档升序重排
                if selection_order:
                    out_pages = [out_map[i] for i in selection_order if i in out_map]
                else:
                    out_pages = [out_map[k] for k in sorted(out_map)]

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
            # FF-M-pdf/audit: 加密 PDF 此前只有笼统的 ValueError（且措辞不含任何
            # 稳定标记 → 被 ParseStep 吞掉 → raw 透传假成功）。这里给出明确
            # 「需要密码」的错误与稳定标记，让入口能报 parse_failed。
            if isinstance(e, ValueError) and PDF_PASSWORD_MARKER in str(e):
                raise  # 上面 is_extractable 分支已构造好的加密错误，勿重复包装
            if _is_password_error(e):
                logger.error("PDF 已加密（需密码）: %s", file_path)
                raise ValueError(
                    f"PDF 已加密（{PDF_PASSWORD_MARKER}）：{file_path.name} 需要密码才能解析"
                    f"（{_password_error_detail(e)}）。当前不支持密码输入，请先解密或提供无密码副本。"
                ) from e
            logger.error("PDF 解析失败: %s", e)
            raise ValueError(f"PDF 解析失败: {e}") from e

    @staticmethod
    def _parse_page_selection(pages: str | None) -> set[int] | None:
        """解析 "1-3,7" 形式的页选择表达式为 1-based 页号集合。

        H13/audit: 与 core/pdf_enhance.py::parse_pages_spec 统一为同一条解析路径/
        同一套规则/同一错误 marker（此前这里自持一份解析器，错误措辞不同且被
        ParseStep 吞掉）。
        """
        from core.pdf_enhance import parse_pages_spec

        return parse_pages_spec(pages)

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
        if two_column:
            # FF-L-pdf/audit: 检测与重排共用一次 extract_words（原为两次整页词级提取）
            try:
                _words = page.extract_words() or []
            except Exception:
                _words = None
            if self._looks_two_column(page, _words):
                text = self._reorder_two_column(page, _words)

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

    def _looks_two_column(self, page, words=None) -> bool:
        """检测页面是否为双栏排版：宽>高 + 词框 x 分布呈左右两簇且中缝清晰。"""
        try:
            w, h = float(page.width), float(page.height)
            if h == 0 or w / h < self._TWO_COL_ASPECT:
                return False
            # FF-L-pdf/audit: words 可由调用方传入复用，避免与 _reorder_two_column
            # 各自 page.extract_words()（每页两次词级提取）。
            if words is None:
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

    def _reorder_two_column(self, page, words=None) -> str:
        """按左栏全部行 → 右栏全部行的顺序重建文本。"""
        try:
            w = float(page.width)
            gutter_lo = w * (0.5 - self._GUTTER_RATIO)
            gutter_hi = w * (0.5 + self._GUTTER_RATIO)
            # FF-L-pdf/audit: 复用检测阶段已提取的 words，省一次整页 extract_words。
            if words is None:
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
        """合并 PDF 文字层和 OCR 识别结果。

        FF-L-pdf/audit: 此前把 PDF 行塞进 set —— 行序丢失、max() 打平分时
        结果不确定、且对每行做 O(n) 相似度扫描（整体 O(n²)）。改为保序去重
        的 list + 有序遍历，输出确定且保留文档原始行序。
        """
        # 保序去重（dict.fromkeys 保持首次出现顺序）
        pdf_lines = list(dict.fromkeys(line.strip() for line in pdf_text.split("\n") if line.strip()))
        ocr_lines = list(dict.fromkeys(line.strip() for line in ocr_text.split("\n") if line.strip()))

        merged: list[str] = []
        for line in ocr_lines:
            # 如果 OCR 行与 PDF 文字层高度相似，使用 PDF 文字（更准确）
            if any(self._text_similarity(line, pdf_line) > 0.8 for pdf_line in pdf_lines):
                # 找到最相似的 PDF 行（保序 list，max 打平分时取行序靠前者，结果确定）
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
        """对单页进行 OCR 识别

        FF-M-pdf/audit: 临时 PNG 用 ``delete=False`` 落盘，此前只在成功路径
        unlink → 任何 OCR 异常都留下泄漏文件。现在统一在 finally 清理。
        """
        temp_path: Path | None = None
        try:
            page_image = page.to_image(resolution=200)

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                temp_path = Path(tmp.name)
            try:
                page_image.save(str(temp_path), format="PNG")
                return self.ocr_engine.extract_text_from_image(temp_path, backend=ocr_backend, apply_postprocess=True)
            finally:
                temp_path.unlink(missing_ok=True)
        except Exception as e:
            logger.error("OCR 第 %d 页失败: %s", page_number, e)
            # FF-M-pdf/audit 顺带修正：模块路径应为 core.ocr_engine——原
            # `from ocr_engine import ...` 在本仓库不存在，OCR 失败路径会
            # 直接 ModuleNotFoundError（失败兜底形同虚设）。
            from core.ocr_engine import OcrResult

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
        """格式化表格为文本

        FF-M-table/audit: 单元格内的 | / 换行会撕开伪 Markdown 表格几何。
        """
        if not table:
            return ""

        lines = []
        for row in table:
            cells = [escape_md_cell(cell) if cell is not None else "" for cell in row]
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
