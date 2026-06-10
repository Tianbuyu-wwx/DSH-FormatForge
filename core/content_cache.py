"""
智能缓存与去重模块
基于内容哈希的转换结果缓存，支持持久化和跨实例共享
"""
import hashlib
import json
import logging
import pickle
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta

logger = logging.getLogger("content_cache")


@dataclass
class CacheEntry:
    """缓存条目"""
    content_hash: str
    result_data: Any
    created_at: datetime
    expires_at: datetime
    access_count: int = 0
    last_accessed: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class ContentHashCache:
    """基于内容哈希的智能缓存"""

    def __init__(
        self,
        max_memory_entries: int = 1000,
        default_ttl: int = 3600,
        persist_path: Optional[Path] = None,
        enable_disk_cache: bool = True
    ):
        self._memory_cache: Dict[str, CacheEntry] = {}
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
        custom_prompt: Optional[str] = None
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
        custom_prompt: Optional[str] = None
    ) -> Optional[Any]:
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
        custom_prompt: Optional[str] = None,
        ttl: Optional[int] = None
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
        custom_prompt: Optional[str] = None
    ) -> Optional[str]:
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
        """保存到磁盘缓存"""
        try:
            cache_file = self._persist_path / f"{content_hash}.pkl"
            entry = {
                "content_hash": content_hash,
                "result_data": result_data,
                "created_at": datetime.now().isoformat(),
                "expires_at": (datetime.now() + timedelta(seconds=ttl)).isoformat(),
                "version": 1
            }
            with open(cache_file, "wb") as f:
                pickle.dump(entry, f)
        except Exception as e:
            logger.warning(f"保存磁盘缓存失败: {e}")

    def _load_from_disk_by_hash(self, content_hash: str) -> Optional[Any]:
        """从磁盘加载指定哈希的缓存"""
        try:
            cache_file = self._persist_path / f"{content_hash}.pkl"
            if not cache_file.exists():
                return None

            with open(cache_file, "rb") as f:
                entry = pickle.load(f)

            expires_at = datetime.fromisoformat(entry["expires_at"])
            if datetime.now() > expires_at:
                # 过期，删除文件
                cache_file.unlink(missing_ok=True)
                return None

            return entry["result_data"]
        except Exception as e:
            logger.warning(f"加载磁盘缓存失败: {e}")
            return None

    def _load_from_disk(self):
        """启动时从磁盘加载有效缓存"""
        if not self._persist_path.exists():
            return

        loaded = 0
        for cache_file in self._persist_path.glob("*.pkl"):
            try:
                with open(cache_file, "rb") as f:
                    entry = pickle.load(f)

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

        if loaded > 0:
            logger.info(f"从磁盘加载 {loaded} 个缓存条目")

    def invalidate(self, content_hash: Optional[str] = None):
        """使缓存失效"""
        if content_hash:
            self._memory_cache.pop(content_hash, None)
            if self._enable_disk_cache:
                cache_file = self._persist_path / f"{content_hash}.pkl"
                cache_file.unlink(missing_ok=True)
        else:
            # 清除所有缓存
            self._memory_cache.clear()
            if self._enable_disk_cache:
                for f in self._persist_path.glob("*.pkl"):
                    f.unlink(missing_ok=True)

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        total_memory = len(self._memory_cache)
        expired = sum(1 for v in self._memory_cache.values() if self._is_expired(v))
        disk_files = len(list(self._persist_path.glob("*.pkl"))) if self._enable_disk_cache else 0

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


class SimilarityCache:
    """相似内容缓存（基于内容相似度而非完全匹配）"""

    def __init__(self, similarity_threshold: float = 0.95):
        self._cache: Dict[str, Any] = {}
        self._threshold = similarity_threshold

    def _compute_simhash(self, content: str) -> str:
        """计算 SimHash（局部敏感哈希）"""
        # 简化实现：使用前缀哈希
        words = content.split()
        if not words:
            return ""

        hashes = []
        for word in words[:100]:  # 取前100个词
            h = hashlib.md5(word.encode()).hexdigest()
            hashes.append(h)

        return "".join(hashes)[:32]

    def find_similar(self, content: str) -> Optional[Any]:
        """查找相似内容的缓存"""
        target_hash = self._compute_simhash(content)
        if not target_hash:
            return None

        # 简单实现：查找哈希前缀匹配
        for cached_hash, result in self._cache.items():
            similarity = self._hash_similarity(target_hash, cached_hash)
            if similarity >= self._threshold:
                return result

        return None

    def _hash_similarity(self, hash1: str, hash2: str) -> float:
        """计算哈希相似度"""
        if len(hash1) != len(hash2):
            return 0.0

        matches = sum(1 for a, b in zip(hash1, hash2) if a == b)
        return matches / len(hash1)

    def store(self, content: str, result: Any):
        """存储内容缓存"""
        content_hash = self._compute_simhash(content)
        self._cache[content_hash] = result


# 全局缓存实例
content_cache = ContentHashCache()
similarity_cache = SimilarityCache()
