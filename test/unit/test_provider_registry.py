"""
ProviderRegistry 单元测试

测试统一的 AI Provider 注册表：
- Provider 注册和查询
- 能力描述获取
- 客户端创建
- 向后兼容的 create_ai_client 函数
"""
import pytest
from unittest.mock import patch, MagicMock

from core.provider_registry import (
    ProviderRegistry,
    ProviderInfo,
    provider_registry,
    create_ai_client,
    AiCapabilities,
    AIClient,
    InputType,
    AiOutputFormat,
)


class TestProviderInfo:
    """测试 ProviderInfo 数据类"""

    def test_create_minimal(self):
        info = ProviderInfo(name="test", capabilities=AiCapabilities(provider="test", model="test"))
        assert info.name == "test"
        assert info.capabilities.provider == "test"
        assert info.client_class is None
        assert info.env_prefix == ""
        assert info.default_base_url == ""

    def test_is_available_no_prefix(self):
        info = ProviderInfo(name="test", capabilities=AiCapabilities(provider="test", model="test"))
        assert info.is_available is False

    def test_is_available_with_key(self, monkeypatch):
        monkeypatch.setattr("core.provider_registry.settings.MINIMAX_API_KEY", "sk-test-key", raising=False)
        info = provider_registry.get("minimax")
        assert info is not None
        assert info.is_available is True


class TestProviderRegistryQuery:
    """测试 Provider 查询接口"""

    def test_list_providers(self):
        providers = provider_registry.list_providers()
        assert "minimax" in providers
        assert "openai" in providers
        assert "anthropic" in providers
        assert "zhipu" in providers
        assert "qwen" in providers
        assert "deepseek" in providers
        assert len(providers) == 6

    def test_get_known_provider(self):
        info = provider_registry.get("minimax")
        assert info is not None
        assert info.name == "minimax"
        assert info.env_prefix == "MINIMAX"
        assert info.default_model == "MiniMax-M2.5"

    def test_get_unknown_provider(self):
        info = provider_registry.get("nonexistent")
        assert info is None

    def test_get_case_insensitive(self):
        info = provider_registry.get("OPENAI")
        assert info is not None
        assert info.name == "openai"

    def test_get_capabilities(self):
        caps = provider_registry.get_capabilities("openai")
        assert caps is not None
        assert caps.provider == "openai"
        assert caps.model == "gpt-4o"
        assert InputType.TEXT in caps.supported_inputs
        assert caps.supports_multimodal is True

    def test_get_capabilities_unknown(self):
        caps = provider_registry.get_capabilities("unknown")
        assert caps is None

    def test_get_all_capabilities(self):
        all_caps = provider_registry.get_all_capabilities()
        assert len(all_caps) == 6
        assert "minimax" in all_caps
        assert isinstance(all_caps["minimax"], AiCapabilities)

    def test_list_available_empty_when_no_keys(self):
        available = provider_registry.list_available()
        assert isinstance(available, list)


class TestProviderRegistryClientCreation:
    """测试客户端创建"""

    def test_create_client_unknown_provider(self):
        with pytest.raises(ValueError, match="不支持的 AI 提供商"):
            provider_registry.create_client(provider="unknown")

    def test_create_client_no_api_key(self):
        """无 API Key 时返回 None"""
        client = provider_registry.create_client(provider="deepseek")
        assert client is None

    def test_create_client_minimax_with_key(self, monkeypatch):
        monkeypatch.setattr("core.provider_registry.settings.MINIMAX_API_KEY", "sk-test-key", raising=False)
        monkeypatch.setattr("core.provider_registry.settings.MINIMAX_BASE_URL", "https://test.example.com/v1", raising=False)

        with patch("core.ai_client.OPENAI_SDK_AVAILABLE", True), \
             patch("core.ai_client.ANTHROPIC_SDK_AVAILABLE", False), \
             patch("core.ai_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            client = provider_registry.create_client(provider="minimax", timeout=60)

            assert client is not None
            assert isinstance(client, AIClient)

    def test_create_client_openai_with_key(self, monkeypatch):
        monkeypatch.setattr("core.provider_registry.settings.OPENAI_API_KEY", "sk-test-key", raising=False)
        monkeypatch.setattr("core.provider_registry.settings.OPENAI_BASE_URL", "https://api.openai.com/v1", raising=False)

        with patch("core.ai_client.OPENAI_SDK_AVAILABLE", True), \
             patch("core.ai_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            client = provider_registry.create_client(provider="openai")

            assert client is not None
            assert isinstance(client, AIClient)

    def test_create_client_zhipu_with_key(self, monkeypatch):
        """智谱使用 OpenAI 兼容客户端"""
        monkeypatch.setattr("core.provider_registry.settings.ZHIPU_API_KEY", "test-key", raising=False)

        with patch("core.ai_client.OPENAI_SDK_AVAILABLE", True), \
             patch("core.ai_client.OpenAI") as mock_openai:
            mock_client = MagicMock()
            mock_openai.return_value = mock_client

            client = provider_registry.create_client(provider="zhipu")

            assert client is not None
            assert isinstance(client, AIClient)


class TestCreateAiClientCompat:
    """测试向后兼容的 create_ai_client 函数"""

    def test_create_client_success(self, monkeypatch):
        monkeypatch.setattr("core.provider_registry.settings.OPENAI_API_KEY", "sk-test", raising=False)

        with patch("core.ai_client.OPENAI_SDK_AVAILABLE", True), \
             patch("core.ai_client.OpenAI") as mock_openai:
            mock_openai.return_value = MagicMock()

            client = create_ai_client(provider="openai", timeout=30)

            assert isinstance(client, AIClient)

    def test_create_client_failure(self):
        with pytest.raises(ValueError, match="无法创建 AI 客户端"):
            create_ai_client(provider="deepseek")


class TestProviderCapabilities:
    """测试各 Provider 的能力预设"""

    @pytest.mark.parametrize("provider,expected_inputs", [
        ("minimax", [InputType.TEXT, InputType.IMAGE]),
        ("openai", [InputType.TEXT, InputType.IMAGE, InputType.AUDIO]),
        ("anthropic", [InputType.TEXT, InputType.IMAGE, InputType.DOCUMENT]),
        ("zhipu", [InputType.TEXT, InputType.IMAGE]),
        ("qwen", [InputType.TEXT, InputType.IMAGE]),
        ("deepseek", [InputType.TEXT]),
    ])
    def test_supported_inputs(self, provider, expected_inputs):
        caps = provider_registry.get_capabilities(provider)
        assert caps.supported_inputs == expected_inputs

    @pytest.mark.parametrize("provider,multimodal", [
        ("minimax", True),
        ("openai", True),
        ("deepseek", False),
    ])
    def test_multimodal_support(self, provider, multimodal):
        caps = provider_registry.get_capabilities(provider)
        assert caps.supports_multimodal == multimodal

    @pytest.mark.parametrize("provider,min_tokens", [
        ("minimax", 8000),
        ("openai", 100000),
        ("deepseek", 60000),
    ])
    def test_max_tokens_reasonable(self, provider, min_tokens):
        caps = provider_registry.get_capabilities(provider)
        assert caps.max_tokens >= min_tokens

    def test_all_providers_support_streaming(self):
        for name in provider_registry.list_providers():
            caps = provider_registry.get_capabilities(name)
            assert caps.supports_streaming is True, f"{name} should support streaming"

    def test_all_providers_have_model(self):
        for name in provider_registry.list_providers():
            caps = provider_registry.get_capabilities(name)
            assert caps.model, f"{name} should have a model name"
            assert caps.provider, f"{name} should have a provider name"


class TestProviderRegistryDiscover:
    """测试能力发现委托"""

    def test_discover_delegates_to_ai_discovery(self):
        with patch.object(provider_registry._ai_discovery, "discover") as mock_discover:
            mock_caps = AiCapabilities(provider="test", model="test-model")
            mock_discover.return_value = mock_caps

            result = provider_registry.discover("http://test.com", "key123", provider="test")

            assert result == mock_caps
            mock_discover.assert_called_once_with(
                "http://test.com", "key123", provider="test", use_cache=True
            )
