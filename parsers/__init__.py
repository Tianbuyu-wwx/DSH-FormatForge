"""
文件解析器插件包
支持多种文件格式的解析
"""
from typing import List, Optional, Dict, Any
from pathlib import Path
from abc import ABC, abstractmethod

from core.models import ParsedFile, PageContent, ExtractedElement, FileType, TaskStatus


class BaseParser(ABC):
    """解析器基类"""

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """支持的文件扩展名列表"""
        pass

    @property
    @abstractmethod
    def supported_magic(self) -> List[bytes]:
        """支持的文件魔数列表"""
        pass

    @abstractmethod
    def parse(self, file_path: Path) -> List[PageContent]:
        """解析文件，返回页面内容列表"""
        pass

    def can_parse(self, file_path: Path, content: Optional[bytes] = None) -> float:
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


class ParserRegistry:
    """解析器注册表"""

    def __init__(self):
        self._parsers: List[BaseParser] = []
        self._ext_map: Dict[str, BaseParser] = {}
        self._magic_map: List[tuple] = []

    def register(self, parser: BaseParser):
        """注册解析器"""
        self._parsers.append(parser)
        for ext in parser.supported_extensions:
            self._ext_map[ext.lower()] = parser
        for magic in parser.supported_magic:
            self._magic_map.append((magic, parser))

    def get_parser_by_ext(self, ext: str) -> Optional[BaseParser]:
        """通过扩展名获取解析器"""
        return self._ext_map.get(ext.lower())

    def get_parser_by_magic(self, content: bytes) -> Optional[BaseParser]:
        """通过魔数获取解析器"""
        for magic, parser in self._magic_map:
            if content.startswith(magic):
                return parser
        return None

    def find_best_parser(self, file_path: Path, content: Optional[bytes] = None) -> Optional[BaseParser]:
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
    def parsers(self) -> List[BaseParser]:
        """获取所有注册的解析器"""
        return self._parsers.copy()
