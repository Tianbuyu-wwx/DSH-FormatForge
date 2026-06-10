"""
压缩包文件解析器
支持解析 ZIP、RAR、7Z 等压缩格式
递归解析压缩包内的文件内容
"""
import logging
import tempfile
from pathlib import Path
from typing import List, Optional, Generator

from parsers import BaseParser
from core.models import PageContent, ExtractedElement

logger = logging.getLogger("parsers.archive")

# 可选依赖
try:
    import zipfile
    ZIP_AVAILABLE = True
except ImportError:
    ZIP_AVAILABLE = False

try:
    import py7zr
    SEVENZ_AVAILABLE = True
except ImportError:
    SEVENZ_AVAILABLE = False
    logger.warning("py7zr 库未安装，7Z 解析功能不可用")

# RAR 支持（较少见，作为可选）
try:
    import rarfile
    RAR_AVAILABLE = True
except ImportError:
    RAR_AVAILABLE = False
    logger.warning("rarfile 库未安装，RAR 解析功能不可用")


class ArchiveParser(BaseParser):
    """压缩包文件解析器（ZIP/RAR/7Z）"""

    @property
    def supported_extensions(self) -> List[str]:
        exts = [".zip"]
        if SEVENZ_AVAILABLE:
            exts.append(".7z")
        if RAR_AVAILABLE:
            exts.extend([".rar", ".rev"])
        return exts

    @property
    def supported_magic(self) -> List[bytes]:
        return [
            b"PK\x03\x04",      # ZIP
            b"PK\x05\x06",      # ZIP 空归档
            b"PK\x07\x08",      # ZIP 分卷
            b"Rar!",            # RAR
            b"7z\xbc\xaf\x27\x1c",  # 7Z
        ]

    def __init__(self, inner_parser=None):
        super().__init__()
        self.inner_parser = inner_parser  # 用于递归解析内部文件

    def parse(self, file_path: Path) -> List[PageContent]:
        """解析压缩包文件"""
        file_path = Path(file_path)
        ext = file_path.suffix.lower()

        logger.info("开始解析压缩包: %s", file_path)

        if ext == '.zip':
            return self._parse_zip(file_path)
        elif ext == '.7z' and SEVENZ_AVAILABLE:
            return self._parse_7z(file_path)
        elif ext == '.rar' and RAR_AVAILABLE:
            return self._parse_rar(file_path)
        else:
            raise ValueError(f"不支持的压缩格式: {ext}")

    def _parse_zip(self, file_path: Path) -> List[PageContent]:
        """解析 ZIP 文件"""
        elements = []
        raw_lines = [f"[ZIP 压缩包] {file_path.name}"]

        try:
            with zipfile.ZipFile(str(file_path), 'r') as zf:
                # 文件列表
                file_list = zf.namelist()
                logger.info("ZIP 包含 %d 个文件", len(file_list))

                # 添加文件列表元素
                for idx, name in enumerate(file_list[:100]):  # 限制数量
                    info = zf.getinfo(name)
                    size = info.file_size
                    elements.append(ExtractedElement(
                        elementId=f"elem_1_file_{idx}",
                        elementType="text",
                        content=f"{name} ({self._format_size(size)})",
                        metadata={
                            "filename": name,
                            "size": size,
                            "compressed_size": info.compress_size,
                            "is_dir": name.endswith('/')
                        }
                    ))

                # 尝试提取文本文件内容
                text_files = [n for n in file_list if not n.endswith('/') and self._is_text_file(n)]
                for idx, name in enumerate(text_files[:20]):  # 限制解析数量
                    try:
                        content = zf.read(name).decode('utf-8', errors='ignore')
                        if content.strip():
                            # 截断过长的内容
                            display_content = content[:500] + "..." if len(content) > 500 else content
                            elements.append(ExtractedElement(
                                elementId=f"elem_1_content_{idx}",
                                elementType="code",
                                content=f"[{name}]\n{display_content}",
                                metadata={
                                    "filename": name,
                                    "content_length": len(content)
                                }
                            ))
                            raw_lines.append(f"\n--- {name} ---\n{display_content}")
                    except Exception as e:
                        logger.debug("无法读取 ZIP 内文件 %s: %s", name, e)

        except zipfile.BadZipFile as e:
            logger.error("ZIP 文件损坏: %s", e)
            raise ValueError(f"ZIP 文件损坏: {e}")
        except Exception as e:
            logger.error("ZIP 解析失败: %s", e)
            raise ValueError(f"ZIP 解析失败: {e}")

        return [PageContent(
            pageNumber=1,
            elements=elements,
            rawText="\n".join(raw_lines),
            hasImage=False,
            hasTable=False
        )]

    def _parse_7z(self, file_path: Path) -> List[PageContent]:
        """解析 7Z 文件"""
        if not SEVENZ_AVAILABLE:
            raise ImportError("py7zr 库未安装，无法解析 7Z 文件")

        elements = []
        raw_lines = [f"[7Z 压缩包] {file_path.name}"]

        try:
            with py7zr.SevenZipFile(str(file_path), 'r') as sz:
                file_list = sz.getnames()
                logger.info("7Z 包含 %d 个文件", len(file_list))

                for idx, name in enumerate(file_list[:100]):
                    elements.append(ExtractedElement(
                        elementId=f"elem_1_file_{idx}",
                        elementType="text",
                        content=name,
                        metadata={"filename": name}
                    ))

                # 尝试读取文本文件
                text_files = [n for n in file_list if self._is_text_file(n)]
                for idx, name in enumerate(text_files[:20]):
                    try:
                        data = sz.read([name])
                        if name in data:
                            content = data[name].read().decode('utf-8', errors='ignore')
                            if content.strip():
                                display_content = content[:500] + "..." if len(content) > 500 else content
                                elements.append(ExtractedElement(
                                    elementId=f"elem_1_content_{idx}",
                                    elementType="code",
                                    content=f"[{name}]\n{display_content}",
                                    metadata={
                                        "filename": name,
                                        "content_length": len(content)
                                    }
                                ))
                                raw_lines.append(f"\n--- {name} ---\n{display_content}")
                    except Exception as e:
                        logger.debug("无法读取 7Z 内文件 %s: %s", name, e)

        except Exception as e:
            logger.error("7Z 解析失败: %s", e)
            raise ValueError(f"7Z 解析失败: {e}")

        return [PageContent(
            pageNumber=1,
            elements=elements,
            rawText="\n".join(raw_lines),
            hasImage=False,
            hasTable=False
        )]

    def _parse_rar(self, file_path: Path) -> List[PageContent]:
        """解析 RAR 文件"""
        if not RAR_AVAILABLE:
            raise ImportError("rarfile 库未安装，无法解析 RAR 文件")

        elements = []
        raw_lines = [f"[RAR 压缩包] {file_path.name}"]

        try:
            with rarfile.RarFile(str(file_path), 'r') as rf:
                file_list = rf.namelist()
                logger.info("RAR 包含 %d 个文件", len(file_list))

                for idx, name in enumerate(file_list[:100]):
                    info = rf.getinfo(name)
                    elements.append(ExtractedElement(
                        elementId=f"elem_1_file_{idx}",
                        elementType="text",
                        content=f"{name} ({self._format_size(info.file_size)})",
                        metadata={
                            "filename": name,
                            "size": info.file_size
                        }
                    ))

                # 尝试读取文本文件
                text_files = [n for n in file_list if self._is_text_file(n)]
                for idx, name in enumerate(text_files[:20]):
                    try:
                        content = rf.read(name).decode('utf-8', errors='ignore')
                        if content.strip():
                            display_content = content[:500] + "..." if len(content) > 500 else content
                            elements.append(ExtractedElement(
                                elementId=f"elem_1_content_{idx}",
                                elementType="code",
                                content=f"[{name}]\n{display_content}",
                                metadata={
                                    "filename": name,
                                    "content_length": len(content)
                                }
                            ))
                            raw_lines.append(f"\n--- {name} ---\n{display_content}")
                    except Exception as e:
                        logger.debug("无法读取 RAR 内文件 %s: %s", name, e)

        except Exception as e:
            logger.error("RAR 解析失败: %s", e)
            raise ValueError(f"RAR 解析失败: {e}")

        return [PageContent(
            pageNumber=1,
            elements=elements,
            rawText="\n".join(raw_lines),
            hasImage=False,
            hasTable=False
        )]

    def _is_text_file(self, filename: str) -> bool:
        """判断是否为文本文件（基于扩展名）"""
        text_exts = {
            '.txt', '.md', '.csv', '.json', '.yaml', '.yml', '.xml',
            '.html', '.htm', '.css', '.js', '.py', '.java', '.c', '.cpp',
            '.h', '.hpp', '.go', '.rs', '.rb', '.php', '.sh', '.bat',
            '.log', '.ini', '.conf', '.cfg', '.properties', '.sql'
        }
        ext = Path(filename).suffix.lower()
        return ext in text_exts

    def _format_size(self, size: int) -> str:
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"
