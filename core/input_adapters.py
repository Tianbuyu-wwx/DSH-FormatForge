"""
输入适配器模块
插件形态只保留本地输入：文件、原始数据、流式数据。
（URL 适配器随 SSRF 攻击面一起移除，见 PLUGIN_PLAN.md §4.1）
"""

import logging
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

logger = logging.getLogger("input_adapters")


@dataclass
class InputData:
    """统一输入数据结构"""

    source_type: str  # "file", "url", "raw", "stream"
    data: bytes
    filename: str | None = None
    mime_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.data)

    def save_to_temp(self) -> Path:
        """保存到临时文件"""
        suffix = Path(self.filename).suffix if self.filename else ".tmp"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(self.data)
            return Path(f.name)


class InputAdapter(ABC):
    """输入适配器抽象基类"""

    @abstractmethod
    def read(self, source: Any) -> InputData:
        """读取输入源，返回统一数据结构"""
        pass

    @abstractmethod
    def can_handle(self, source: Any) -> bool:
        """检查是否能处理该输入源"""
        pass


class FileInputAdapter(InputAdapter):
    """文件输入适配器"""

    def can_handle(self, source: Any) -> bool:
        if isinstance(source, (str, Path)):
            path = Path(source)
            return path.exists() and path.is_file()
        return False

    def read(self, source: str | Path) -> InputData:
        file_path = Path(source)

        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        if not file_path.is_file():
            raise ValueError(f"路径不是文件: {file_path}")

        with open(file_path, "rb") as f:
            data = f.read()

        # 尝试检测 mime_type
        mime_type = self._detect_mime_type(file_path)

        return InputData(
            source_type="file",
            data=data,
            filename=file_path.name,
            mime_type=mime_type,
            metadata={"path": str(file_path.absolute()), "size": len(data), "modified": file_path.stat().st_mtime},
        )

    def _detect_mime_type(self, file_path: Path) -> str | None:
        """检测文件 MIME 类型"""
        try:
            import mimetypes

            mime, _ = mimetypes.guess_type(str(file_path))
            return mime
        except Exception:
            return None


class RawDataAdapter(InputAdapter):
    """原始数据输入适配器 - 处理字节或字符串"""

    def can_handle(self, source: Any) -> bool:
        return isinstance(source, (bytes, str))

    def read(self, source: bytes | str, filename: str | None = None) -> InputData:
        if isinstance(source, str):
            data = source.encode("utf-8")
            logger.debug("原始数据适配器: 字符串输入, length=%d", len(source))
        else:
            data = source
            logger.debug("原始数据适配器: 字节输入, size=%d", len(source))

        return InputData(
            source_type="raw", data=data, filename=filename or "raw_data", mime_type=None, metadata={"size": len(data)}
        )


class StreamInputAdapter(InputAdapter):
    """流式数据输入适配器"""

    def can_handle(self, source: Any) -> bool:
        return hasattr(source, "read")

    def read(self, source: BinaryIO, filename: str | None = None, chunk_size: int = 8192) -> InputData:
        chunks = []
        total = 0
        while True:
            chunk = source.read(chunk_size)
            if not chunk:
                break
            chunk_bytes = chunk if isinstance(chunk, bytes) else chunk.encode("utf-8")
            chunks.append(chunk_bytes)
            total += len(chunk_bytes)

        data = b"".join(chunks)
        logger.info("流式读取完成: size=%d bytes", total)

        return InputData(
            source_type="stream",
            data=data,
            filename=filename or "stream_data",
            mime_type=None,
            metadata={"size": len(data)},
        )


class InputAdapterManager:
    """输入适配器管理器 - 自动选择最佳适配器"""

    def __init__(self):
        self._adapters: list[InputAdapter] = [
            FileInputAdapter(),
            RawDataAdapter(),
            StreamInputAdapter(),
        ]

    def read(self, source: Any, **kwargs) -> InputData:
        """
        读取输入源

        Args:
            source: 输入源（文件路径/URL/字节/流）
            **kwargs: 额外参数（如 filename, timeout 等）

        Returns:
            InputData: 统一的输入数据
        """
        logger.debug("InputAdapterManager 尝试读取输入源: type=%s", type(source).__name__)
        # 找到第一个能处理的适配器
        for adapter in self._adapters:
            if adapter.can_handle(source):
                logger.info("使用适配器: %s", type(adapter).__name__)
                return adapter.read(source, **kwargs)

        logger.error("无法处理的输入源类型: %s", type(source).__name__)
        raise ValueError(f"无法处理的输入源类型: {type(source)}")

    def register(self, adapter: InputAdapter):
        """注册自定义适配器"""
        self._adapters.insert(0, adapter)  # 新适配器优先

    def can_handle(self, source: Any) -> bool:
        """检查是否有适配器能处理该输入源"""
        return any(adapter.can_handle(source) for adapter in self._adapters)


# 全局管理器实例
input_manager = InputAdapterManager()
