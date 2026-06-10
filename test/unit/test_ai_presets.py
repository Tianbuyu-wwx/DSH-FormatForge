"""
AI预设配置库单元测试
"""
import pytest
import os

from core.ai_presets import (
    AiPreset,
    AiPresetLibrary,
    AiProvider,
    ai_preset_library
)


class TestAiPreset:
    """测试AI预设配置"""

    def test_to_dict(self):
        """测试转换为字典"""
        preset = AiPreset(
            provider="openai",
            model="gpt-4o",
            base_url="https://api.openai.com/v1",
            api_key_env="OPENAI_API_KEY",
            max_tokens=128000,
            supports_multimodal=True,
            description="Test preset"
        )
        d = preset.to_dict()
        assert d["provider"] == "openai"
        assert d["model"] == "gpt-4o"
        assert d["supports_multimodal"] is True
        assert d["description"] == "Test preset"

    def test_default_values(self):
        """测试默认值"""
        preset = AiPreset(
            provider="test",
            model="test-model",
            base_url="http://test.com",
            api_key_env="TEST_KEY",
            max_tokens=1000
        )
        assert preset.supports_multimodal is False
        assert preset.supports_vision is False
        assert preset.preferred_format == "text"


class TestAiPresetLibrary:
    """测试AI预设库"""

    def setup_method(self):
        self.library = AiPresetLibrary()

    def test_get_preset_by_provider_and_model(self):
        """测试通过提供商和模型获取预设"""
        preset = self.library.get_preset("openai", "gpt-4o")
        assert preset is not None
        assert preset.provider == "openai"
        assert preset.model == "gpt-4o"

    def test_get_preset_by_provider_only(self):
        """测试仅通过提供商获取预设"""
        preset = self.library.get_preset("openai")
        assert preset is not None
        assert preset.provider == "openai"

    def test_get_nonexistent_preset(self):
        """测试获取不存在的预设"""
        preset = self.library.get_preset("nonexistent", "model")
        assert preset is None

    def test_get_all_presets(self):
        """测试获取所有预设"""
        presets = self.library.get_all_presets()
        assert len(presets) > 0
        # 检查是否包含主要提供商
        providers = [p.provider for p in presets]
        assert "openai" in providers
        assert "anthropic" in providers

    def test_get_providers(self):
        """测试获取所有提供商"""
        providers = self.library.get_providers()
        assert "openai" in providers
        assert "anthropic" in providers
        assert "google" in providers
        assert "zhipu" in providers

    def test_get_models_by_provider(self):
        """测试获取指定提供商的模型"""
        models = self.library.get_models_by_provider("openai")
        assert len(models) >= 2  # gpt-4o, gpt-4o-mini
        assert all(m.provider == "openai" for m in models)

    def test_add_preset(self):
        """测试添加自定义预设"""
        preset = AiPreset(
            provider="custom",
            model="custom-model",
            base_url="http://custom.com",
            api_key_env="CUSTOM_KEY",
            max_tokens=10000,
            description="Custom preset"
        )
        self.library.add_preset(preset)

        retrieved = self.library.get_preset("custom", "custom-model")
        assert retrieved is not None
        assert retrieved.model == "custom-model"

    def test_get_preset_from_endpoint_openai(self):
        """测试从OpenAI端点推断预设"""
        preset = self.library.get_preset_from_endpoint("https://api.openai.com/v1")
        assert preset is not None
        assert preset.provider == "openai"

    def test_get_preset_from_endpoint_anthropic(self):
        """测试从Anthropic端点推断预设"""
        preset = self.library.get_preset_from_endpoint("https://api.anthropic.com/v1")
        assert preset is not None
        assert preset.provider == "anthropic"

    def test_get_preset_from_endpoint_unknown(self):
        """测试从未知端点推断预设"""
        preset = self.library.get_preset_from_endpoint("https://unknown.com")
        assert preset is None

    def test_create_client_config(self):
        """测试创建客户端配置"""
        preset = self.library.get_preset("openai", "gpt-4o")
        config = self.library.create_client_config(preset, api_key="test-key")

        assert config["provider"] == "openai"
        assert config["model"] == "gpt-4o"
        assert config["api_key"] == "test-key"
        assert "max_tokens" in config

    def test_create_client_config_from_env(self):
        """测试从环境变量创建客户端配置"""
        os.environ["OPENAI_API_KEY"] = "env-key"
        preset = self.library.get_preset("openai", "gpt-4o")
        config = self.library.create_client_config(preset)

        assert config["api_key"] == "env-key"
        del os.environ["OPENAI_API_KEY"]

    def test_preset_capabilities(self):
        """测试预设能力标志"""
        # OpenAI GPT-4o 应该支持多模态
        gpt4o = self.library.get_preset("openai", "gpt-4o")
        assert gpt4o.supports_multimodal is True
        assert gpt4o.supports_vision is True

        # DeepSeek 不支持多模态
        deepseek = self.library.get_preset("deepseek", "deepseek-chat")
        assert deepseek.supports_multimodal is False

    def test_local_presets(self):
        """测试本地模型预设"""
        local_presets = self.library.get_models_by_provider("local")
        assert len(local_presets) >= 2  # llama3.2, qwen2.5
        assert all(p.base_url.startswith("http://localhost") for p in local_presets)

    def test_chinese_providers(self):
        """测试中文提供商预设"""
        zhipu = self.library.get_preset("zhipu", "glm-4")
        assert zhipu is not None
        assert "bigmodel.cn" in zhipu.base_url

        alibaba = self.library.get_preset("alibaba", "qwen-max")
        assert alibaba is not None
        assert "dashscope" in alibaba.base_url

        baidu = self.library.get_preset("baidu", "ernie-4.0")
        assert baidu is not None
        assert "baidubce" in baidu.base_url

    def test_max_tokens_range(self):
        """测试max_tokens范围"""
        presets = self.library.get_all_presets()
        for preset in presets:
            assert preset.max_tokens > 0
            assert preset.max_tokens <= 2000000  # 合理上限


class TestAiProvider:
    """测试AI提供商枚举"""

    def test_provider_values(self):
        """测试提供商枚举值"""
        assert AiProvider.OPENAI == "openai"
        assert AiProvider.ANTHROPIC == "anthropic"
        assert AiProvider.GOOGLE == "google"
        assert AiProvider.LOCAL == "local"


class TestGlobalPresetLibrary:
    """测试全局预设库"""

    def test_global_instance(self):
        """测试全局实例存在"""
        assert isinstance(ai_preset_library, AiPresetLibrary)

    def test_global_has_presets(self):
        """测试全局实例包含预设"""
        presets = ai_preset_library.get_all_presets()
        assert len(presets) > 0
