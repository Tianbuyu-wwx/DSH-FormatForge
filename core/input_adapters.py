"""
输入适配器模块
统一处理多种输入源：文件、URL、原始数据、流式数据
"""

import logging
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse

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


class UrlInputAdapter(InputAdapter):
    """URL 输入适配器 - 下载远程内容"""

    def can_handle(self, source: Any) -> bool:
        if isinstance(source, str):
            parsed = urlparse(source)
            return parsed.scheme in ("http", "https") and parsed.netloc
        return False

    def read(self, source: str, timeout: int = 30, max_size: int = 100 * 1024 * 1024) -> InputData:
        import httpx

        url = source
        logger.info("正在下载: %s", url)

        try:
            with httpx.Client(timeout=timeout) as client:
                resp = client.get(url)
            resp.raise_for_status()
            logger.debug(
                "URL请求成功: status=%d, content_length=%s", resp.status_code, resp.headers.get("Content-Length")
            )

            # 检查内容长度
            content_length = resp.headers.get("Content-Length")
            if content_length and int(content_length) > max_size:
                logger.error("文件大小超过限制: %s > %d", content_length, max_size)
                raise ValueError(f"文件大小超过限制: {content_length} > {max_size}")

            data = resp.content
            if len(data) > max_size:
                raise ValueError(f"下载内容超过最大限制 {max_size} 字节")

            # 从 URL 或响应头获取文件名
            filename = self._extract_filename(url, dict(resp.headers))
            mime_type = resp.headers.get("Content-Type")

            logger.info("下载完成: %s, 大小=%d 字节, filename=%s, mime=%s", url, len(data), filename, mime_type)

            return InputData(
                source_type="url",
                data=data,
                filename=filename,
                mime_type=mime_type,
                metadata={
                    "url": url,
                    "size": len(data),
                    "status_code": resp.status_code,
                    "headers": dict(resp.headers),
                },
            )

        except httpx.RequestError as e:
            logger.error("下载失败: %s, error=%s", url, e)
            raise RuntimeError(f"下载失败: {e}") from e

    def _extract_filename(self, url: str, headers: dict) -> str | None:
        """从 URL 或响应头提取文件名"""
        # 从 Content-Disposition 提取
        cd = headers.get("Content-Disposition", "")
        if "filename=" in cd:
            import re

            match = re.search(r'filename=["\']?([^"\';]+)', cd)
            if match:
                return match.group(1)

        # 从 URL 路径提取
        parsed = urlparse(url)
        path = Path(parsed.path)
        if path.name:
            return path.name

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
            UrlInputAdapter(),
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
