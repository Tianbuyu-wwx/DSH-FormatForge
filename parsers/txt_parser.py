"""
TXT 文件解析器
支持解析纯文本文件，具备编码自动检测与大文件流式读取能力
"""
import logging
from collections.abc import Generator
from pathlib import Path

from core.models import ExtractedElement, PageContent
from parsers import BaseParser

logger = logging.getLogger("parsers.txt")

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

    def parse(self, file_path: Path) -> list[PageContent]:
        """解析 TXT 文件"""
        return list(self.parse_stream(file_path))

    def parse_stream(self, file_path: Path, chunk_size: int = 8192) -> Generator[PageContent, None, None]:
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

        # 检测文件编码
        encoding = self._detect_encoding(file_path)
        logger.debug("检测到编码: %s", encoding)

        elements = []
        elem_idx = 0
        buffer = ""
        total_lines = 0

        try:
            with open(file_path, encoding=encoding, errors='ignore') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    buffer += chunk

                    # 处理完整的段落（以双换行分隔）
                    while '\n\n' in buffer:
                        para, buffer = buffer.split('\n\n', 1)
                        if para.strip():
                            elem_type = self._detect_element_type(para)
                            elements.append(ExtractedElement(
                                elementId=f"elem_1_{elem_idx}",
                                elementType=elem_type,
                                content=para.strip()
                            ))
                            elem_idx += 1
                            total_lines += para.count('\n') + 1

                # 处理剩余内容
                if buffer.strip():
                    elem_type = self._detect_element_type(buffer)
                    elements.append(ExtractedElement(
                        elementId=f"elem_1_{elem_idx}",
                        elementType=elem_type,
                        content=buffer.strip()
                    ))
                    total_lines += buffer.count('\n') + 1

        except Exception as e:
            logger.error("TXT 解析失败: %s", e)
            raise ValueError(f"TXT 解析失败: {e}")

        logger.info("TXT 解析完成: %d 个元素, %d 行", len(elements), total_lines)

        yield PageContent(
            pageNumber=1,
            elements=elements,
            rawText="\n\n".join(e.content for e in elements),
            hasImage=False,
            hasTable=False
        )

    def _detect_encoding(self, file_path: Path) -> str:
        """
        检测文件编码

        优先使用 chardet 进行自动检测，
        失败时回退到 UTF-8
        """
        if CHARDET_AVAILABLE:
            try:
                with open(file_path, 'rb') as f:
                    raw = f.read(min(32768, file_path.stat().st_size))
                    if raw:
                        result = chardet.detect(raw)
                        detected = result.get('encoding', 'utf-8')
                        confidence = result.get('confidence', 0.0)
                        if detected and confidence and confidence > 0.5:
                            logger.debug("编码检测结果: %s (置信度 %.2f)", detected, confidence)
                            return detected.lower()
            except Exception as e:
                logger.warning("编码检测失败: %s", e)

        # 回退：尝试 UTF-8，失败则用 GBK
        try:
            with open(file_path, encoding='utf-8') as f:
                f.read(1024)
            return 'utf-8'
        except UnicodeDecodeError:
            logger.debug("UTF-8 解码失败，回退到 GBK")
            return 'gbk'

    def _detect_element_type(self, text: str) -> str:
        """检测文本元素类型"""
        text = text.strip()
        if not text:
            return "empty"

        # 检测标题（短文本 + 结束符）
        if len(text) < 100 and (text.endswith('：') or text.endswith(':')):
            return "heading"

        # 检测 Markdown 标题
        if text.startswith('#') and len(text.split('\n')[0]) < 100:
            return "heading"

        # 检测代码块
        if text.startswith('```') or text.startswith('    '):
            return "code"

        # 检测列表
        first_line = text.split('\n')[0]
        if first_line.startswith(('•', '-', '*', '1.', '2.', '（', '(')):
            return "list"

        # 检测引用
        if first_line.startswith('>'):
            return "quote"

        return "text"
