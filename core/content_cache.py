"""
智能缓存与去重模块
基于内容哈希的转换结果缓存，支持持久化和跨实例共享

磁盘缓存采用 JSON 序列化（取代 pickle）以避免反序列化任意代码漏洞。
向后兼容：仍可读取旧版 .pkl 文件，但下次写入会迁移为 .json。
"""
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger("content_cache")


@dataclass
class CacheEntry:
    """缓存条目"""
    content_hash: str
    result_data: Any
    created_at: datetime
    expires_at: datetime
    access_count: int = 0
    last_accessed: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ContentHashCache:
    """基于内容哈希的智能缓存"""

    def __init__(
        self,
        max_memory_entries: int = 1000,
        default_ttl: int = 3600,
        persist_path: Path | None = None,
        enable_disk_cache: bool = True
    ):
        self._memory_cache: dict[str, CacheEntry] = {}
        self._max_memory_entries = max_memory_entries
        self._default_ttl = default_ttl
        self._persist_path = persist_path or Path("./cache")
        self._enable_disk_cache = enable_disk_cache

        if self._enable_disk_cache:
            self._persist_path.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

    def _compute_hash(
        self,
        source_data: bytes,
        conversion_type: str,
        output_format: str,
        custom_prompt: str | None = None
    ) -> str:
        """计算内容哈希（包含转换参数）"""
        hasher = hashlib.sha256()
        hasher.update(source_data)
        hasher.update(conversion_type.encode("utf-8"))
        hasher.update(output_format.encode("utf-8"))
        if custom_prompt:
            hasher.update(custom_prompt.encode("utf-8"))
        return hasher.hexdigest()

    def _compute_file_hash(self, file_path: Path) -> str:
        """计算文件哈希（支持大文件分块读取）"""
        hasher = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def get(
        self,
        source: Any,
        conversion_type: str,
        output_format: str,
        custom_prompt: str | None = None
    ) -> Any | None:
        """
        获取缓存结果

        Args:
            source: 输入源（文件路径/字节数据/字符串）
            conversion_type: 转换类型
            output_format: 输出格式
            custom_prompt: 自定义提示词

        Returns:
            缓存的结果数据，或 None
        """
        content_hash = self._get_content_hash(source, conversion_type, output_format, custom_prompt)
        if not content_hash:
            return None

        # 1. 检查内存缓存
        entry = self._memory_cache.get(content_hash)
        if entry and not self._is_expired(entry):
            entry.access_count += 1
            entry.last_accessed = datetime.now()
            logger.debug(f"内存缓存命中: {content_hash[:16]}...")
            return entry.result_data

        # 2. 检查磁盘缓存
        if self._enable_disk_cache:
            disk_result = self._load_from_disk_by_hash(content_hash)
            if disk_result:
                # 加载到内存缓存
                self._add_to_memory(content_hash, disk_result, custom_ttl=self._default_ttl)
                logger.debug(f"磁盘缓存命中: {content_hash[:16]}...")
                return disk_result

        return None

    def set(
        self,
        source: Any,
        conversion_type: str,
        output_format: str,
        result_data: Any,
        custom_prompt: str | None = None,
        ttl: int | None = None
    ):
        """
        设置缓存

        Args:
            source: 输入源
            conversion_type: 转换类型
            output_format: 输出格式
            result_data: 结果数据
            custom_prompt: 自定义提示词
            ttl: 自定义过期时间（秒）
        """
        content_hash = self._get_content_hash(source, conversion_type, output_format, custom_prompt)
        if not content_hash:
            return

        ttl = ttl or self._default_ttl
        self._add_to_memory(content_hash, result_data, custom_ttl=ttl)

        if self._enable_disk_cache:
            self._save_to_disk(content_hash, result_data, ttl)

        logger.debug(f"缓存已设置: {content_hash[:16]}...")

    def _get_content_hash(
        self,
        source: Any,
        conversion_type: str,
        output_format: str,
        custom_prompt: str | None = None
    ) -> str | None:
        """根据输入源获取内容哈希"""
        try:
            if isinstance(source, (str, Path)):
                path = Path(source)
                if path.exists():
                    file_hash = self._compute_file_hash(path)
                    return self._compute_hash(
                        file_hash.encode("utf-8"),
                        conversion_type,
                        output_format,
                        custom_prompt
                    )
                else:
                    # 可能是原始数据字符串
                    return self._compute_hash(
                        str(source).encode("utf-8"),
                        conversion_type,
                        output_format,
                        custom_prompt
                    )
            elif isinstance(source, bytes):
                return self._compute_hash(source, conversion_type, output_format, custom_prompt)
            else:
                return self._compute_hash(
                    str(source).encode("utf-8"),
                    conversion_type,
                    output_format,
                    custom_prompt
                )
        except Exception as e:
            logger.warning(f"计算内容哈希失败: {e}")
            return None

    def _add_to_memory(self, content_hash: str, result_data: Any, custom_ttl: int):
        """添加到内存缓存"""
        now = datetime.now()
        entry = CacheEntry(
            content_hash=content_hash,
            result_data=result_data,
            created_at=now,
            expires_at=now + timedelta(seconds=custom_ttl),
            last_accessed=now
        )

        # 清理过期条目
        self._cleanup_expired()

        # 如果超出容量，移除最少使用的
        while len(self._memory_cache) >= self._max_memory_entries:
            self._evict_lru()

        self._memory_cache[content_hash] = entry

    def _is_expired(self, entry: CacheEntry) -> bool:
        """检查条目是否过期"""
        return datetime.now() > entry.expires_at

    def _cleanup_expired(self):
        """清理过期条目"""
        expired = [
            k for k, v in self._memory_cache.items()
            if self._is_expired(v)
        ]
        for k in expired:
            del self._memory_cache[k]

        if expired:
            logger.debug(f"清理 {len(expired)} 个过期缓存条目")

    def _evict_lru(self):
        """移除最少使用的条目"""
        if not self._memory_cache:
            return

        # 优先移除未访问过的，然后是最早访问的
        lru_key = min(
            self._memory_cache.keys(),
            key=lambda k: (
                self._memory_cache[k].access_count,
                self._memory_cache[k].last_accessed or datetime.min
            )
        )
        del self._memory_cache[lru_key]

    def _save_to_disk(self, content_hash: str, result_data: Any, ttl: int):
        """保存到磁盘缓存（JSON 格式，取代 pickle）"""
        try:
            cache_file = self._persist_path / f"{content_hash}.json"
            entry = {
                "content_hash": content_hash,
                "result_data": self._serialize_for_disk(result_data),
                "created_at": datetime.now().isoformat(),
                "expires_at": (datetime.now() + timedelta(seconds=ttl)).isoformat(),
                "version": 2
            }
            cache_file.write_text(
                json.dumps(entry, ensure_ascii=False, default=str),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"保存磁盘缓存失败: {e}")

    def _serialize_for_disk(self, data: Any) -> Any:
        """将数据序列化为 JSON 可序列化形式"""
        if isinstance(data, dict):
            return {str(k): self._serialize_for_disk(v) for k, v in data.items()}
        if isinstance(data, (list, tuple)):
            return [self._serialize_for_disk(v) for v in data]
        if hasattr(data, "model_dump"):  # Pydantic v2
            try:
                return data.model_dump(mode="json")
            except Exception:
                pass
        if hasattr(data, "dict"):  # Pydantic v1
            try:
                return data.dict()
            except Exception:
                pass
        if isinstance(data, (str, int, float, bool, type(None))):
            return data
        # 无法序列化的类型 → str fallback（避免任何情况下的崩溃）
        return str(data)

    def _load_from_disk_by_hash(self, content_hash: str) -> Any | None:
        """从磁盘加载指定哈希的缓存（优先 .json，回退到 .pkl 向后兼容）"""
        try:
            cache_file = self._persist_path / f"{content_hash}.json"
            legacy_file = self._persist_path / f"{content_hash}.pkl"

            if cache_file.exists():
                entry = json.loads(cache_file.read_text(encoding="utf-8"))
            elif legacy_file.exists():
                # 旧格式：仍用 pickle 读取一次性，迁移到 JSON
                import pickle as _pickle
                with open(legacy_file, "rb") as f:
                    entry = _pickle.load(f)
                legacy_file.unlink(missing_ok=True)
                logger.info("迁移旧版 .pkl 缓存: %s", content_hash[:16])
            else:
                return None

            expires_at = datetime.fromisoformat(entry["expires_at"])
            if datetime.now() > expires_at:
                cache_file.unlink(missing_ok=True)
                return None

            return entry["result_data"]
        except Exception as e:
            logger.warning(f"加载磁盘缓存失败: {e}")
            # 任何解析失败都删除损坏文件（pickle/JSON 损坏 → 触发攻击面）
            for ext in (".json", ".pkl"):
                p = self._persist_path / f"{content_hash}{ext}"
                if p.exists():
                    p.unlink(missing_ok=True)
                    logger.warning("损坏缓存文件已删除: %s", p.name)
            return None

    def _load_from_disk(self):
        """启动时从磁盘加载有效缓存（支持 .json 新格式和 .pkl 旧格式）"""
        if not self._persist_path.exists():
            return

        loaded = 0
        # 先扫 .json（新格式）
        for cache_file in self._persist_path.glob("*.json"):
            try:
                entry = json.loads(cache_file.read_text(encoding="utf-8"))
                expires_at = datetime.fromisoformat(entry["expires_at"])
                if datetime.now() > expires_at:
                    cache_file.unlink(missing_ok=True)
                    continue
                content_hash = entry["content_hash"]
                self._memory_cache[content_hash] = CacheEntry(
                    content_hash=content_hash,
                    result_data=entry["result_data"],
                    created_at=datetime.fromisoformat(entry["created_at"]),
                    expires_at=expires_at,
                    last_accessed=datetime.now()
                )
                loaded += 1
            except Exception as e:
                logger.warning(f"加载缓存文件失败 {cache_file}: {e}")
                cache_file.unlink(missing_ok=True)

        # 再扫 .pkl（旧格式，仅迁移到内存，下次写入自动转 JSON）
        for cache_file in self._persist_path.glob("*.pkl"):
            try:
                import pickle as _pickle
                with open(cache_file, "rb") as f:
                    entry = _pickle.load(f)
                expires_at = datetime.fromisoformat(entry["expires_at"])
                if datetime.now() > expires_at:
                    cache_file.unlink(missing_ok=True)
                    continue
                content_hash = entry["content_hash"]
                self._memory_cache[content_hash] = CacheEntry(
                    content_hash=content_hash,
                    result_data=entry["result_data"],
                    created_at=datetime.fromisoformat(entry["created_at"]),
                    expires_at=expires_at,
                    last_accessed=datetime.now()
                )
                loaded += 1
                logger.info("迁移 .pkl → 内存: %s", content_hash[:16])
            except Exception as e:
                logger.warning(f"加载旧 .pkl 缓存失败 {cache_file}: {e}")
                cache_file.unlink(missing_ok=True)

        if loaded > 0:
            logger.info(f"从磁盘加载 {loaded} 个缓存条目")

    def invalidate(self, content_hash: str | None = None):
        """使缓存失效"""
        if content_hash:
            self._memory_cache.pop(content_hash, None)
            if self._enable_disk_cache:
                for ext in (".json", ".pkl"):
                    (self._persist_path / f"{content_hash}{ext}").unlink(missing_ok=True)
        else:
            # 清除所有缓存
            self._memory_cache.clear()
            if self._enable_disk_cache:
                for f in self._persist_path.glob("*.json"):
                    f.unlink(missing_ok=True)
                for f in self._persist_path.glob("*.pkl"):
                    f.unlink(missing_ok=True)

    def get_stats(self) -> dict[str, Any]:
        """获取缓存统计信息"""
        total_memory = len(self._memory_cache)
        expired = sum(1 for v in self._memory_cache.values() if self._is_expired(v))
        disk_files = 0
        if self._enable_disk_cache:
            disk_files = len(list(self._persist_path.glob("*.json")))
            disk_files += len(list(self._persist_path.glob("*.pkl")))  # 旧文件也算

        total_access = sum(v.access_count for v in self._memory_cache.values())

        return {
            "memory_entries": total_memory,
            "expired_entries": expired,
            "disk_entries": disk_files,
            "total_access_count": total_access,
            "memory_limit": self._max_memory_entries,
            "default_ttl": self._default_ttl,
            "disk_cache_enabled": self._enable_disk_cache,
            "persist_path": str(self._persist_path)
        }


# 全局缓存实例
content_cache = ContentHashCache()

