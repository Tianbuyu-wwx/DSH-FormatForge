"""
AI 预设配置库
支持多种AI提供商的预设配置，自动发现本地模型
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("ai_presets")


class AiProvider(str, Enum):
    """AI提供商枚举"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE = "google"
    ZHIPU = "zhipu"
    BAIDU = "baidu"
    ALIBABA = "alibaba"
    MOONSHOT = "moonshot"
    DEEPSEEK = "deepseek"
    MINIMAX = "minimax"
    LOCAL = "local"


@dataclass
class AiPreset:
    """AI预设配置"""
    provider: str
    model: str
    base_url: str
    api_key_env: str  # 环境变量名
    max_tokens: int
    supports_multimodal: bool = False
    supports_vision: bool = False
    supports_tools: bool = False
    preferred_format: str = "text"
    headers: dict[str, str] = field(default_factory=dict)
    request_format: str = "openai"  # openai, anthropic, google 等
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "max_tokens": self.max_tokens,
            "supports_multimodal": self.supports_multimodal,
            "supports_vision": self.supports_vision,
            "supports_tools": self.supports_tools,
            "preferred_format": self.preferred_format,
            "request_format": self.request_format,
            "description": self.description
        }


class AiPresetLibrary:
    """AI预设配置库"""

    def __init__(self):
        self._presets: dict[str, AiPreset] = {}
        self._register_default_presets()

    def _register_default_presets(self):
        """注册默认预设配置"""
        presets = [
            # OpenAI
            AiPreset(
                provider=AiProvider.OPENAI,
                model="gpt-4o",
                base_url="https://api.openai.com/v1",
                api_key_env="OPENAI_API_KEY",
                max_tokens=128000,
                supports_multimodal=True,
                supports_vision=True,
                supports_tools=True,
                preferred_format="text",
                request_format="openai",
                description="OpenAI GPT-4o - 多模态旗舰模型"
            ),
            AiPreset(
                provider=AiProvider.OPENAI,
                model="gpt-4o-mini",
                base_url="https://api.openai.com/v1",
                api_key_env="OPENAI_API_KEY",
                max_tokens=128000,
                supports_multimodal=True,
                supports_vision=True,
                supports_tools=True,
                preferred_format="text",
                request_format="openai",
                description="OpenAI GPT-4o Mini - 高性价比多模态模型"
            ),

            # Anthropic
            AiPreset(
                provider=AiProvider.ANTHROPIC,
                model="claude-3-5-sonnet-20241022",
                base_url="https://api.anthropic.com/v1",
                api_key_env="ANTHROPIC_API_KEY",
                max_tokens=200000,
                supports_multimodal=True,
                supports_vision=True,
                supports_tools=True,
                preferred_format="text",
                request_format="anthropic",
                headers={"anthropic-version": "2023-06-01"},
                description="Anthropic Claude 3.5 Sonnet - 强大的推理能力"
            ),
            AiPreset(
                provider=AiProvider.ANTHROPIC,
                model="claude-3-opus-20240229",
                base_url="https://api.anthropic.com/v1",
                api_key_env="ANTHROPIC_API_KEY",
                max_tokens=200000,
                supports_multimodal=True,
                supports_vision=True,
                supports_tools=True,
                preferred_format="text",
                request_format="anthropic",
                headers={"anthropic-version": "2023-06-01"},
                description="Anthropic Claude 3 Opus - 最强推理模型"
            ),

            # Google
            AiPreset(
                provider=AiProvider.GOOGLE,
                model="gemini-1.5-pro",
                base_url="https://generativelanguage.googleapis.com/v1beta",
                api_key_env="GOOGLE_API_KEY",
                max_tokens=1000000,
                supports_multimodal=True,
                supports_vision=True,
                supports_tools=True,
                preferred_format="text",
                request_format="google",
                description="Google Gemini 1.5 Pro - 超长上下文"
            ),
            AiPreset(
                provider=AiProvider.GOOGLE,
                model="gemini-1.5-flash",
                base_url="https://generativelanguage.googleapis.com/v1beta",
                api_key_env="GOOGLE_API_KEY",
                max_tokens=1000000,
                supports_multimodal=True,
                supports_vision=True,
                supports_tools=True,
                preferred_format="text",
                request_format="google",
                description="Google Gemini 1.5 Flash - 快速响应"
            ),

            # 智谱AI
            AiPreset(
                provider=AiProvider.ZHIPU,
                model="glm-4",
                base_url="https://open.bigmodel.cn/api/paas/v4",
                api_key_env="ZHIPU_API_KEY",
                max_tokens=128000,
                supports_multimodal=True,
                supports_vision=True,
                supports_tools=True,
                preferred_format="text",
                request_format="openai",
                description="智谱GLM-4 - 国产大模型"
            ),
            AiPreset(
                provider=AiProvider.ZHIPU,
                model="glm-4v",
                base_url="https://open.bigmodel.cn/api/paas/v4",
                api_key_env="ZHIPU_API_KEY",
                max_tokens=8000,
                supports_multimodal=True,
                supports_vision=True,
                supports_tools=False,
                preferred_format="text",
                request_format="openai",
                description="智谱GLM-4V - 视觉理解模型"
            ),

            # 百度
            AiPreset(
                provider=AiProvider.BAIDU,
                model="ernie-4.0",
                base_url="https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat",
                api_key_env="BAIDU_API_KEY",
                max_tokens=8000,
                supports_multimodal=False,
                supports_vision=False,
                supports_tools=True,
                preferred_format="text",
                request_format="baidu",
                description="百度文心ERNIE 4.0"
            ),

            # 阿里
            AiPreset(
                provider=AiProvider.ALIBABA,
                model="qwen-max",
                base_url="https://dashscope.aliyuncs.com/api/v1",
                api_key_env="DASHSCOPE_API_KEY",
                max_tokens=32000,
                supports_multimodal=True,
                supports_vision=True,
                supports_tools=True,
                preferred_format="text",
                request_format="openai",
                description="阿里通义千问Max"
            ),
            AiPreset(
                provider=AiProvider.ALIBABA,
                model="qwen-vl-max",
                base_url="https://dashscope.aliyuncs.com/api/v1",
                api_key_env="DASHSCOPE_API_KEY",
                max_tokens=32000,
                supports_multimodal=True,
                supports_vision=True,
                supports_tools=False,
                preferred_format="text",
                request_format="openai",
                description="阿里通义千问VL - 视觉理解"
            ),

            # Moonshot (Kimi)
            AiPreset(
                provider=AiProvider.MOONSHOT,
                model="moonshot-v1-128k",
                base_url="https://api.moonshot.cn/v1",
                api_key_env="MOONSHOT_API_KEY",
                max_tokens=128000,
                supports_multimodal=False,
                supports_vision=False,
                supports_tools=True,
                preferred_format="text",
                request_format="openai",
                description="Moonshot Kimi - 长文本专家"
            ),

            # DeepSeek
            AiPreset(
                provider=AiProvider.DEEPSEEK,
                model="deepseek-chat",
                base_url="https://api.deepseek.com/v1",
                api_key_env="DEEPSEEK_API_KEY",
                max_tokens=64000,
                supports_multimodal=False,
                supports_vision=False,
                supports_tools=True,
                preferred_format="text",
                request_format="openai",
                description="DeepSeek Chat - 高性价比"
            ),
            AiPreset(
                provider=AiProvider.DEEPSEEK,
                model="deepseek-reasoner",
                base_url="https://api.deepseek.com/v1",
                api_key_env="DEEPSEEK_API_KEY",
                max_tokens=64000,
                supports_multimodal=False,
                supports_vision=False,
                supports_tools=True,
                preferred_format="text",
                request_format="openai",
                description="DeepSeek Reasoner - 推理专家"
            ),

            # MiniMax
            AiPreset(
                provider=AiProvider.MINIMAX,
                model="abab6.5s-chat",
                base_url="https://api.minimaxi.com/v1",
                api_key_env="MINIMAX_API_KEY",
                max_tokens=8000,
                supports_multimodal=False,
                supports_vision=False,
                supports_tools=True,
                preferred_format="text",
                request_format="openai",
                description="MiniMax abab6.5s"
            ),

            # 本地模型 (Ollama)
            AiPreset(
                provider=AiProvider.LOCAL,
                model="llama3.2",
                base_url="http://localhost:11434/v1",
                api_key_env="",
                max_tokens=128000,
                supports_multimodal=False,
                supports_vision=False,
                supports_tools=False,
                preferred_format="text",
                request_format="openai",
                description="Ollama Llama 3.2 - 本地运行"
            ),
            AiPreset(
                provider=AiProvider.LOCAL,
                model="qwen2.5",
                base_url="http://localhost:11434/v1",
                api_key_env="",
                max_tokens=128000,
                supports_multimodal=False,
                supports_vision=False,
                supports_tools=False,
                preferred_format="text",
                request_format="openai",
                description="Ollama Qwen 2.5 - 本地运行"
            ),
        ]

        for preset in presets:
            provider_val = preset.provider.value if isinstance(preset.provider, Enum) else str(preset.provider)
            key = f"{provider_val}/{preset.model}"
            self._presets[key] = preset

    def get_preset(self, provider: str, model: str | None = None) -> AiPreset | None:
        """获取预设配置"""
        provider_str = provider.value if isinstance(provider, Enum) else str(provider)
        if model:
            key = f"{provider_str}/{model}"
            return self._presets.get(key)

        # 如果没有指定模型，返回该提供商的第一个预设
        for preset in self._presets.values():
            preset_provider = preset.provider.value if isinstance(preset.provider, Enum) else str(preset.provider)
            if preset_provider == provider_str:
                return preset
        return None

    def get_all_presets(self) -> list[AiPreset]:
        """获取所有预设"""
        return list(self._presets.values())

    def get_providers(self) -> list[str]:
        """获取所有提供商"""
        return list(set(
            p.provider.value if isinstance(p.provider, Enum) else str(p.provider)
            for p in self._presets.values()
        ))

    def get_models_by_provider(self, provider: str) -> list[AiPreset]:
        """获取指定提供商的所有模型"""
        provider_str = provider.value if isinstance(provider, Enum) else str(provider)
        return [
            p for p in self._presets.values()
            if (p.provider.value if isinstance(p.provider, Enum) else str(p.provider)) == provider_str
        ]

    def add_preset(self, preset: AiPreset):
        """添加自定义预设"""
        provider_val = preset.provider.value if isinstance(preset.provider, Enum) else str(preset.provider)
        key = f"{provider_val}/{preset.model}"
        self._presets[key] = preset
        logger.info(f"添加预设: {key}")

    def detect_local_models(self) -> list[AiPreset]:
        """检测本地模型（Ollama, LM Studio）"""
        local_models = []

        # 检测 Ollama
        try:
            import requests
            response = requests.get("http://localhost:11434/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                for model in data.get("models", []):
                    model_name = model.get("name", "")
                    if model_name:
                        preset = AiPreset(
                            provider=AiProvider.LOCAL,
                            model=model_name,
                            base_url="http://localhost:11434/v1",
                            api_key_env="",
                            max_tokens=128000,
                            supports_multimodal=False,
                            supports_vision=False,
                            supports_tools=False,
                            preferred_format="text",
                            request_format="openai",
                            description=f"Ollama本地模型: {model_name}"
                        )
                        local_models.append(preset)
                        self.add_preset(preset)
        except Exception as e:
            logger.debug(f"Ollama检测失败: {e}")

        # 检测 LM Studio
        try:
            import requests
            response = requests.get("http://localhost:1234/v1/models", timeout=5)
            if response.status_code == 200:
                data = response.json()
                for model in data.get("data", []):
                    model_id = model.get("id", "")
                    if model_id:
                        preset = AiPreset(
                            provider=AiProvider.LOCAL,
                            model=model_id,
                            base_url="http://localhost:1234/v1",
                            api_key_env="",
                            max_tokens=128000,
                            supports_multimodal=False,
                            supports_vision=False,
                            supports_tools=False,
                            preferred_format="text",
                            request_format="openai",
                            description=f"LM Studio本地模型: {model_id}"
                        )
                        local_models.append(preset)
                        self.add_preset(preset)
        except Exception as e:
            logger.debug(f"LM Studio检测失败: {e}")

        if local_models:
            logger.info(f"检测到 {len(local_models)} 个本地模型")

        return local_models

    def get_preset_from_endpoint(self, endpoint: str) -> AiPreset | None:
        """从端点URL推断预设"""
        endpoint_lower = endpoint.lower()

        url_patterns = {
            "openai.com": ("openai", "gpt-4o"),
            "anthropic.com": ("anthropic", "claude-3-5-sonnet-20241022"),
            "googleapis.com": ("google", "gemini-1.5-pro"),
            "bigmodel.cn": ("zhipu", "glm-4"),
            "baidubce.com": ("baidu", "ernie-4.0"),
            "dashscope.aliyuncs.com": ("alibaba", "qwen-max"),
            "moonshot.cn": ("moonshot", "moonshot-v1-128k"),
            "deepseek.com": ("deepseek", "deepseek-chat"),
            "minimaxi.com": ("minimax", "abab6.5s-chat"),
            "localhost:11434": ("local", "llama3.2"),
            "localhost:1234": ("local", "local-model"),
        }

        for pattern, (provider, default_model) in url_patterns.items():
            if pattern in endpoint_lower:
                preset = self.get_preset(provider, default_model)
                if preset:
                    return preset

        return None

    def create_client_config(self, preset: AiPreset, api_key: str | None = None) -> dict[str, Any]:
        """创建客户端配置"""
        import os

        key = api_key or os.getenv(preset.api_key_env, "")

        return {
            "provider": preset.provider,
            "model": preset.model,
            "base_url": preset.base_url,
            "api_key": key,
            "max_tokens": preset.max_tokens,
            "headers": preset.headers,
            "request_format": preset.request_format
        }


# 全局预设库
ai_preset_library = AiPresetLibrary()
