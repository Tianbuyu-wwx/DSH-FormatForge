"""
内容缓存模块单元测试
"""
import pytest
import tempfile
from pathlib import Path
import time

from core.content_cache import (
    ContentHashCache,
    SimilarityCache,
    CacheEntry,
    content_cache
)


class TestContentHashCache:
    """测试内容哈希缓存"""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cache = ContentHashCache(
            max_memory_entries=10,
            default_ttl=60,
            persist_path=Path(self.temp_dir),
            enable_disk_cache=True
        )

    def teardown_method(self):
        # 清理临时目录
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_compute_hash(self):
        """测试哈希计算"""
        hash1 = self.cache._compute_hash(b"test data", "text", "json")
        hash2 = self.cache._compute_hash(b"test data", "text", "json")
        hash3 = self.cache._compute_hash(b"different", "text", "json")

        assert hash1 == hash2  # 相同输入相同输出
        assert hash1 != hash3  # 不同输入不同输出

    def test_set_and_get(self):
        """测试设置和获取缓存"""
        source = b"test content"
        result_data = {"converted": "result"}

        self.cache.set(source, "text", "json", result_data)
        cached = self.cache.get(source, "text", "json")

        assert cached == result_data

    def test_get_nonexistent(self):
        """测试获取不存在的缓存"""
        cached = self.cache.get(b"nonexistent", "text", "json")
        assert cached is None

    def test_ttl_expiration(self):
        """测试TTL过期"""
        cache = ContentHashCache(
            max_memory_entries=10,
            default_ttl=1,  # 1秒过期
            persist_path=Path(self.temp_dir),
            enable_disk_cache=False
        )

        source = b"test content"
        cache.set(source, "text", "json", {"data": "value"})

        # 立即获取应该成功
        assert cache.get(source, "text", "json") is not None

        # 等待过期
        time.sleep(2)

        # 过期后获取应该失败
        assert cache.get(source, "text", "json") is None

    def test_memory_limit(self):
        """测试内存限制"""
        cache = ContentHashCache(
            max_memory_entries=3,
            default_ttl=3600,
            persist_path=Path(self.temp_dir),
            enable_disk_cache=False
        )

        # 添加超过限制的条目
        for i in range(5):
            cache.set(f"content{i}".encode(), "text", "json", {"id": i})

        # 应该只保留最近访问的3个
        assert len(cache._memory_cache) <= 3

    def test_invalidate_single(self):
        """测试使单个缓存失效"""
        source = b"test content"
        self.cache.set(source, "text", "json", {"data": "value"})

        # 获取哈希
        hash_key = self.cache._get_content_hash(source, "text", "json")

        # 使缓存失效
        self.cache.invalidate(hash_key)

        # 应该获取不到
        assert self.cache.get(source, "text", "json") is None

    def test_invalidate_all(self):
        """测试使所有缓存失效"""
        self.cache.set(b"content1", "text", "json", {"id": 1})
        self.cache.set(b"content2", "text", "json", {"id": 2})

        self.cache.invalidate()

        assert len(self.cache._memory_cache) == 0

    def test_file_hash(self):
        """测试文件哈希计算"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            f.write("test content for hashing")
            temp_path = f.name

        try:
            hash1 = self.cache._compute_file_hash(Path(temp_path))
            hash2 = self.cache._compute_file_hash(Path(temp_path))

            assert len(hash1) == 64  # SHA-256是64位十六进制
            assert hash1 == hash2
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_get_stats(self):
        """测试获取统计信息"""
        self.cache.set(b"content1", "text", "json", {"id": 1})
        self.cache.set(b"content2", "text", "json", {"id": 2})

        stats = self.cache.get_stats()

        assert stats["memory_entries"] == 2
        assert stats["memory_limit"] == 10
        assert stats["disk_cache_enabled"] is True

    def test_custom_prompt_in_hash(self):
        """测试自定义提示词影响哈希"""
        source = b"test content"

        self.cache.set(source, "text", "json", {"data": "no prompt"})
        self.cache.set(source, "text", "json", {"data": "with prompt"}, custom_prompt="custom")

        # 应该能分别获取到
        no_prompt = self.cache.get(source, "text", "json")
        with_prompt = self.cache.get(source, "text", "json", custom_prompt="custom")

        assert no_prompt == {"data": "no prompt"}
        assert with_prompt == {"data": "with prompt"}


class TestSimilarityCache:
    """测试相似度缓存"""

    def setup_method(self):
        self.cache = SimilarityCache(similarity_threshold=0.8)

    def test_compute_simhash(self):
        """测试SimHash计算"""
        hash1 = self.cache._compute_simhash("hello world test")
        hash2 = self.cache._compute_simhash("hello world test")
        hash3 = self.cache._compute_simhash("completely different content")

        assert hash1 == hash2
        assert hash1 != hash3

    def test_hash_similarity(self):
        """测试哈希相似度计算"""
        similarity = self.cache._hash_similarity("abcd1234", "abcd1234")
        assert similarity == 1.0

        similarity = self.cache._hash_similarity("abcd1234", "wxyz5678")
        assert similarity == 0.0

    def test_store_and_find_similar(self):
        """测试存储和查找相似内容"""
        content = "This is a test document about Python programming"
        result = {"converted": "data"}

        self.cache.store(content, result)

        # 查找相似内容
        similar_content = "This is a test document about Python coding"
        found = self.cache.find_similar(similar_content)

        assert found == result

    def test_find_similar_not_found(self):
        """测试查找不存在的相似内容"""
        self.cache.store("some content", {"data": 1})

        found = self.cache.find_similar("completely different content here")
        assert found is None


class TestGlobalCache:
    """测试全局缓存实例"""

    def test_global_instance(self):
        """测试全局缓存实例存在"""
        assert isinstance(content_cache, ContentHashCache)
