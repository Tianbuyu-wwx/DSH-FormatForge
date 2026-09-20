"""
TXT 文件解析器
支持解析纯文本文件，具备编码自动检测与大文件流式读取能力
"""

import codecs
import logging
from collections.abc import Generator
from pathlib import Path

from core.models import ExtractedElement, PageContent
from parsers import BaseParser

logger = logging.getLogger("parsers.txt")

# FF-M-txt/audit: BOM 必须优先识别（否则 utf-8 BOM 会变成正文首个 U+FEFF，
# 而 utf-16 文件会被当 gbk/gb18030 解出满屏乱码）。
_BOM_ENCODINGS: tuple[tuple[bytes, str], ...] = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

# FF-M-txt/audit: 回退链——utf-8 全量严格校验 → gb18030（GBK/GB2312 超集）
# → latin-1（永不失败，但标记 lossy，不假装是正确解码）。
# T1-2: 链上的 gb18030 额外要求 _looks_like_gb() 佐证，未通过则让位给 chardet
# 的单字节猜测（见 _detect_encoding）。
_FALLBACK_CHAIN: tuple[str, ...] = ("utf-8", "utf-8-sig", "gb18030")
_LAST_RESORT = "latin-1"

# FF-M-txt/audit: 这些单字节编码族能解码**任意**字节流（永不失败），因此 chardet
# 对它们的高置信度猜测没有证据价值——例如「ASCII 前缀 + GBK 尾部」的混合文件会被
# 猜成 ISO-8859-9 / Windows-1252，直接采信就把中文静默解成乱码。
_NO_EVIDENCE_CHARSET_PREFIXES = ("iso8859", "cp125", "mac-")

# T1-2: gb18030「解得开」并不等于「解得对」。高位字节 + 紧跟的 ASCII 字母正好构成
# 合法双字节序列，于是整篇 cp1252 西文会被吞成汉字；而 gb18030 是 _is_verified →
# True 的多字节编码，lossy_decode / encoding_verified 标记根本不会触发 → 静默乱码。
# 佐证判据：真实 GB2312/GBK 正文的双字节 trail 几乎都落在 0xA1-0xFE（GB2312 区），
# 西文误判时 trail 恰恰是被吞掉的 ASCII 字母（<0xA1）。实测比例：
#   德语/西语 cp1252 乱码样本 0.09 / 0.07 ·真实 gbk/gb2312 语料 1.00
# 阈值取 0.5，两侧各留一个数量级的余量。
_GB_STRUCTURE_MIN_RATIO = 0.5
_GB_SAMPLE_BYTES = 32768

# 可选依赖
try:
    import chardet

    CHARDET_AVAILABLE = True
except ImportError:
    CHARDET_AVAILABLE = False
    logger.warning("chardet 库未安装，编码自动检测功能受限")


class TXTParser(BaseParser):
    """TXT 纯文本解析器"""

    @property
    def supported_extensions(self) -> list[str]:
        return [".txt", ".text", ".md", ".log", ".ini", ".conf", ".cfg", ".properties"]

    @property
    def supported_magic(self) -> list[bytes]:
        # 纯文本无固定魔数，通过扩展名识别
        return []

    def parse(self, file_path: Path, encoding: str | None = None) -> list[PageContent]:
        """解析 TXT 文件（R3.3: encoding 覆写供自愈重试）"""
        return list(self.parse_stream(file_path, encoding=encoding))

    def parse_stream(
        self, file_path: Path, chunk_size: int = 8192, encoding: str | None = None
    ) -> Generator[PageContent, None, None]:
        """
        流式解析 TXT 文件，按段落生成（减少大文件内存占用）

        Args:
            file_path: 文件路径
            chunk_size: 每次读取的块大小

        Yields:
            PageContent: 每一页的内容（TXT 视为单页）
        """
        file_path = Path(file_path)
        logger.info("开始流式解析 TXT: %s", file_path)

        # 检测文件编码（R3.3: 显式覆写优先——自愈重试路径）
        encoding = encoding or self._detect_encoding(file_path)
        logger.debug("检测到编码: %s", encoding)
        lossy = self._is_last_resort(encoding)
        if not self._is_verified(encoding):
            # FF-M-txt/audit: 单字节兜底/猜测（latin-1、未验证的 chardet 猜测）
            # 可能是 mojibake，必须显式标记而不是静默当作正确解码。
            logger.warning("编码 %s 未经验证，结果可能为乱码: %s", encoding, file_path)

        elements = []
        elem_idx = 0
        buffer = ""
        total_lines = 0
        first_chunk = True

        try:
            with open(file_path, encoding=encoding, errors="replace") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    if first_chunk:
                        # BOM 若仍以字符形式出现（显式 encoding 覆写路径），剥掉
                        chunk = chunk.lstrip("\ufeff")
                        first_chunk = False
                    buffer += chunk

                    # 处理完整的段落（以双换行分隔）
                    while "\n\n" in buffer:
                        para, buffer = buffer.split("\n\n", 1)
                        if para.strip():
                            elem_type = self._detect_element_type(para)
                            elements.append(
                                ExtractedElement(
                                    elementId=f"elem_1_{elem_idx}", elementType=elem_type, content=para.strip()
                                )
                            )
                            elem_idx += 1
                            total_lines += para.count("\n") + 1

                # 处理剩余内容
                if buffer.strip():
                    elem_type = self._detect_element_type(buffer)
                    elements.append(
                        ExtractedElement(elementId=f"elem_1_{elem_idx}", elementType=elem_type, content=buffer.strip())
                    )
                    total_lines += buffer.count("\n") + 1

        except Exception as e:
            logger.error("TXT 解析失败: %s", e)
            raise ValueError(f"TXT 解析失败: {e}") from e

        logger.info("TXT 解析完成: %d 个元素, %d 行", len(elements), total_lines)

        metadata: dict[str, object] = {"encoding": encoding}
        if not self._is_verified(encoding):
            metadata["encoding_verified"] = False
        if lossy:
            metadata["encoding_fallback"] = _LAST_RESORT
            metadata["lossy_decode"] = True

        yield PageContent(
            pageNumber=1,
            elements=elements,
            rawText="\n\n".join(e.content for e in elements),
            hasImage=False,
            hasTable=False,
            metadata=metadata,
        )

    def _detect_encoding(self, file_path: Path) -> str:
        """
        检测文件编码

        顺序：BOM → chardet（多字节/有证据价值的判定）→ 全量严格校验回退链
        （utf-8 → utf-8-sig → 经佐证的 gb18030）→ chardet 的单字节猜测 →
        latin-1（lossy 兜底，由调用方标记）。

        FF-M-txt/audit: 旧实现只在**前 1024 字节**上试 utf-8（合法前缀 + 非法
        尾部会误判为 utf-8 → 静默乱码），且不识别 BOM。
        """
        bom_encoding = self._detect_bom(file_path)
        if bom_encoding:
            logger.debug("按 BOM 判定编码: %s", bom_encoding)
            return bom_encoding

        chardet_hint: str | None = None
        if CHARDET_AVAILABLE:
            try:
                with open(file_path, "rb") as f:
                    raw = f.read(min(32768, file_path.stat().st_size))
                    if raw:
                        result = chardet.detect(raw)
                        detected = result.get("encoding", "utf-8")
                        confidence = result.get("confidence", 0.0)
                        if detected and confidence and confidence > 0.5:
                            name = detected.lower()
                            if self._is_verified(name):
                                logger.debug("编码检测结果: %s (置信度 %.2f)", detected, confidence)
                                return name
                            # 「永不失败」的单字节猜测：无证据价值，留给严格回退链裁决
                            logger.debug("chardet 猜测 %s 无证据价值，改走严格回退链", name)
                            chardet_hint = name
            except Exception as e:
                logger.warning("编码检测失败: %s", e)

        # 回退：对**整个文件**做严格解码校验（分块增量解码，不整文件载入内存）
        for candidate in _FALLBACK_CHAIN:
            if not self._decodes_fully(file_path, candidate):
                continue
            # T1-2: gb18030 必须先自证。它对大量 cp1252 字节流「解码成功」却输出
            # 汉字乱码，而且不会触发任何 lossy/未验证标记——在这个位置无条件采信
            # 它，等于让最坏的一类错误成为最安静的一类。未通过佐证就把裁决权交回
            # 下面的 chardet 单字节猜测（那是真实的统计证据，不是「永不失败」）。
            if candidate == "gb18030" and not self._looks_like_gb(file_path):
                logger.debug("gb18030 可解码但结构不像 GB 正文（疑似西文误判），跳过: %s", file_path)
                continue
            logger.debug("回退链命中编码: %s", candidate)
            return candidate

        if chardet_hint:
            logger.warning("严格解码全部失败，采信未验证的 chardet 猜测 %s: %s", chardet_hint, file_path)
            return chardet_hint

        logger.warning("所有候选编码均失败，回退 latin-1（结果可能为乱码）: %s", file_path)
        return _LAST_RESORT

    @staticmethod
    def _looks_like_gb(file_path: Path) -> bool:
        """gb18030 解码成功后的结构佐证：这些多字节序列真的像 GB 正文吗？

        真实 GB2312/GBK 汉字的 trail 字节几乎都在 0xA1-0xFE；cp1252 西文被
        gb18030 吞掉时，trail 恰恰是被吞进去的 ASCII 字母（<0xA1）。判定用
        codec 自身回编每个字符，而不是手写一套 GB18030 状态机。

        GB18030 四字节序列在西文字节流里几乎凑不出来，计入佐证。
        """
        try:
            decoder = codecs.getincrementaldecoder("gb18030")()
            with open(file_path, "rb") as f:
                sample = f.read(_GB_SAMPLE_BYTES)
            # 不传 final=True：样本尾部被截断的半个序列自动挂起，不算错
            text = decoder.decode(sample)
        except (OSError, UnicodeDecodeError, LookupError):  # pragma: no cover - 调用前已全量校验
            return False

        multibyte = 0
        structured = 0
        for ch in text:
            try:
                raw = ch.encode("gb18030")
            except UnicodeEncodeError:  # pragma: no cover - 解码所得必可回编
                continue
            if len(raw) == 1:
                continue
            multibyte += 1
            if len(raw) >= 4 or raw[1] >= 0xA1:
                structured += 1

        if multibyte == 0:
            # 纯 ASCII 样本：gb18030 与 ASCII 等价，无从解错
            return True
        return structured / multibyte >= _GB_STRUCTURE_MIN_RATIO

    @staticmethod
    def _is_verified(encoding: str) -> bool:
        """该编码名是否具备证据价值（多字节/ASCII；单字节兜底族不算）。"""
        try:
            name = codecs.lookup(encoding).name
        except LookupError:
            return False
        return not name.startswith(_NO_EVIDENCE_CHARSET_PREFIXES)

    @staticmethod
    def _is_last_resort(encoding: str) -> bool:
        """latin-1 兜底（含 iso-8859-1 别名）判定。"""
        try:
            return codecs.lookup(encoding).name == "iso8859-1"
        except LookupError:
            return False

    @staticmethod
    def _detect_bom(file_path: Path) -> str | None:
        """按文件头 BOM 判定编码（utf-8-sig 同时负责剥离 BOM）。"""
        try:
            with open(file_path, "rb") as f:
                head = f.read(4)
        except OSError:  # pragma: no cover - 由 parse_stream 的异常路径接管
            return None
        for bom, enc in _BOM_ENCODINGS:
            if head.startswith(bom):
                return enc
        return None

    @staticmethod
    def _decodes_fully(file_path: Path, encoding: str, chunk_size: int = 1 << 20) -> bool:
        """分块严格解码整个文件；任何一处非法序列即判定该编码不可用。"""
        try:
            decoder = codecs.getincrementaldecoder(encoding)()
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    decoder.decode(chunk)
            decoder.decode(b"", final=True)
            return True
        except UnicodeDecodeError:
            return False
        except LookupError:  # pragma: no cover - 链内编码均存在
            return False

    def _detect_element_type(self, text: str) -> str:
        """检测文本元素类型"""
        text = text.strip()
        if not text:
            return "empty"

        # 检测标题（短文本 + 结束符）
        if len(text) < 100 and (text.endswith("：") or text.endswith(":")):
            return "heading"

        # 检测 Markdown 标题
        if text.startswith("#") and len(text.split("\n")[0]) < 100:
            return "heading"

        # 检测代码块
        if text.startswith("```") or text.startswith("    "):
            return "code"

        # 检测列表
        first_line = text.split("\n")[0]
        if first_line.startswith(("•", "-", "*", "1.", "2.", "（", "(")):
            return "list"

        # 检测引用
        if first_line.startswith(">"):
            return "quote"

        return "text"
