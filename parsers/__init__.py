"""
文件解析器插件包
支持多种文件格式的解析

v2.3 - 统一 Parser 接口：
  - 所有解析器必须实现 parse() 和 parse_bytes()
  - name/description 用于 UI 展示和调试
  - supported_formats 返回 FileType 枚举值
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.models import ExtractedElement, FileType, PageContent, ParsedFile, TaskStatus


class BaseParser(ABC):
    """解析器基类 - v2.3 统一接口"""

    # ── 必须实现的属性 ──

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """支持的文件扩展名列表，如 ['.pdf', '.PDF']"""
        pass

    @property
    @abstractmethod
    def supported_magic(self) -> list[bytes]:
        """支持的文件魔数列表，如 [b'%PDF']"""
        pass

    @property
    def name(self) -> str:
        """解析器名称，默认从类名推断"""
        return self.__class__.__name__

    @property
    def description(self) -> str:
        """解析器描述"""
        return f"解析 {', '.join(self.supported_extensions[:3])} 格式文件"

    @property
    def supported_formats(self) -> list[FileType]:
        """支持的 FileType 枚举值列表"""
        return []

    # ── 必须实现的解析方法 ──

    @abstractmethod
    def parse(self, file_path: Path) -> list[PageContent]:
        """解析文件路径，返回页面内容列表"""
        pass

    def parse_bytes(self, data: bytes, file_name: str = "") -> list[PageContent]:
        """
        解析字节数据，返回页面内容列表

        默认实现：写入临时文件后调用 parse()。
        子类可覆盖以提供更高效的内存解析。
        """
        import tempfile

        suffix = Path(file_name).suffix if file_name else ""
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            return self.parse(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)

    # ── 可选覆盖的方法 ──

    def can_parse(self, file_path: Path, content: bytes | None = None) -> float:
        """
        判断是否能解析该文件，返回置信度 0.0-1.0
        """
        ext = file_path.suffix.lower()
        if ext in self.supported_extensions:
            return 0.9

        if content:
            for magic in self.supported_magic:
                if content.startswith(magic):
                    return 0.95

        return 0.0

    def get_metadata(self, file_path: Path) -> dict[str, Any]:
        """
        获取文件元数据（可选覆盖）
        返回如 {pages, author, creator, ...} 等
        """
        return {}


class ParserRegistry:
    """解析器注册表"""

    def __init__(self):
        self._parsers: list[BaseParser] = []
        self._ext_map: dict[str, BaseParser] = {}
        self._magic_map: list[tuple] = []

    def register(self, parser: BaseParser):
        """注册解析器"""
        self._parsers.append(parser)
        for ext in parser.supported_extensions:
            self._ext_map[ext.lower()] = parser
        for magic in parser.supported_magic:
            self._magic_map.append((magic, parser))

    def get_parser_by_ext(self, ext: str) -> BaseParser | None:
        """通过扩展名获取解析器"""
        return self._ext_map.get(ext.lower())

    def get_parser_by_magic(self, content: bytes) -> BaseParser | None:
        """通过魔数获取解析器"""
        for magic, parser in self._magic_map:
            if content.startswith(magic):
                return parser
        return None

    def find_best_parser(self, file_path: Path, content: bytes | None = None) -> BaseParser | None:
        """查找最佳解析器"""
        # 先按扩展名匹配
        parser = self.get_parser_by_ext(file_path.suffix)
        if parser:
            return parser

        # 再按魔数匹配
        if content:
            parser = self.get_parser_by_magic(content)
            if parser:
                return parser

        return None

    @property
    def parsers(self) -> list[BaseParser]:
        """获取所有注册的解析器"""
        return self._parsers.copy()
