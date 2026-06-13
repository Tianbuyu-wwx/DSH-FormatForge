"""
AI 能力发现模块
自动探测目标 AI 端点支持的能力，为数据转换提供决策依据
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("ai_discovery")


class InputType(str, Enum):
    """AI 支持的输入类型"""
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"


class AiOutputFormat(str, Enum):
    """AI 偏好的输出格式"""
    JSON = "json"
    MARKDOWN = "markdown"
    TEXT = "text"
    HTML = "html"


@dataclass
class AiCapabilities:
    """AI 能力描述"""
    provider: str
    model: str
    supported_inputs: list[InputType] = field(default_factory=list)
    max_tokens: int = 4096
    supports_multimodal: bool = False
    supports_streaming: bool = False
    supports_function_calling: bool = False
    preferred_format: AiOutputFormat = AiOutputFormat.TEXT
    api_version: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def supports_input(self, input_type: InputType) -> bool:
        """检查是否支持特定输入类型"""
        return input_type in self.supported_inputs

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "supported_inputs": [i.value for i in self.supported_inputs],
            "max_tokens": self.max_tokens,
            "supports_multimodal": self.supports_multimodal,
            "supports_streaming": self.supports_streaming,
            "supports_function_calling": self.supports_function_calling,
            "preferred_format": self.preferred_format.value,
            "api_version": self.api_version,
            "extra": self.extra
        }


class BaseAiDiscovery(ABC):
    """AI 能力发现抽象基类"""

    @abstractmethod
    def discover(self, endpoint: str, api_key: str, **kwargs) -> AiCapabilities:
        """探测 AI 端点能力"""
        pass

    @abstractmethod
    def is_compatible(self, endpoint: str) -> bool:
        """检查是否兼容该端点"""
        pass


class OpenAiCompatibleDiscovery(BaseAiDiscovery):
    """OpenAI 兼容 API 能力发现"""

    def is_compatible(self, endpoint: str) -> bool:
        return "openai" in endpoint or "/v1" in endpoint

    def discover(self, endpoint: str, api_key: str, **kwargs) -> AiCapabilities:
        """通过模型列表和接口探测能力"""
        import httpx

        headers = {"Authorization": f"Bearer {api_key}"}
        capabilities = AiCapabilities(
            provider="openai_compatible",
            model="unknown"
        )
        logger.info("开始探测 OpenAI 兼容端点: %s", endpoint)

        try:
            # 尝试获取模型列表
            resp = httpx.get(
                f"{endpoint.rstrip('/')}/models",
                headers=headers,
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                if models:
                    capabilities.model = models[0].get("id", "unknown")
                    capabilities.provider = self._detect_provider(models)
                    logger.info("获取模型列表成功: provider=%s, model=%s, total_models=%d",
                                capabilities.provider, capabilities.model, len(models))
                else:
                    logger.warning("模型列表为空")
            else:
                logger.warning("获取模型列表失败: status=%d", resp.status_code)

            # 根据模型名推断能力
            capabilities = self._infer_capabilities(capabilities)
            logger.debug("推断能力结果: max_tokens=%d, multimodal=%s, inputs=%s",
                         capabilities.max_tokens, capabilities.supports_multimodal,
                         [i.value for i in capabilities.supported_inputs])

        except Exception as e:
            logger.warning("探测 OpenAI 兼容端点失败: %s", e, exc_info=True)
            # 使用默认能力
            capabilities.supported_inputs = [InputType.TEXT]
            capabilities.max_tokens = 4096

        return capabilities

    def _detect_provider(self, models: list[dict]) -> str:
        """根据模型名检测提供商"""
        model_ids = [m.get("id", "").lower() for m in models]
        for mid in model_ids:
            if "minimax" in mid or "m2.5" in mid:
                return "minimax"
            elif "gpt" in mid or "o1" in mid or "o3" in mid:
                return "openai"
            elif "claude" in mid:
                return "anthropic"
            elif "glm" in mid:
                return "zhipu"
            elif "qwen" in mid or "qwq" in mid:
                return "qwen"
            elif "deepseek" in mid:
                return "deepseek"
        return "openai_compatible"

    def _infer_capabilities(self, capabilities: AiCapabilities) -> AiCapabilities:
        """根据提供商和模型名推断能力"""
        model = capabilities.model.lower()
        provider = capabilities.provider.lower()

        # 输入类型推断
        if provider in ["openai", "minimax", "anthropic", "qwen", "gemini"]:
            capabilities.supported_inputs = [InputType.TEXT, InputType.IMAGE]
            capabilities.supports_multimodal = True
        elif provider in ["deepseek", "zhipu"]:
            capabilities.supported_inputs = [InputType.TEXT]
            capabilities.supports_multimodal = False
        else:
            capabilities.supported_inputs = [InputType.TEXT]

        # Token 限制推断
        if "gpt-4o" in model or "o1" in model or "o3" in model:
            capabilities.max_tokens = 128000
        elif "gpt-4" in model:
            capabilities.max_tokens = 8192
        elif "gpt-3.5" in model:
            capabilities.max_tokens = 4096
        elif "minimax" in model or "m2.5" in model:
            capabilities.max_tokens = 8000
        elif "claude-3" in model:
            capabilities.max_tokens = 200000
        elif "glm-4" in model or "qwen2.5" in model or "qwq" in model:
            capabilities.max_tokens = 128000
        elif "deepseek" in model:
            capabilities.max_tokens = 64000
        else:
            capabilities.max_tokens = 4096

        # 功能支持推断
        capabilities.supports_streaming = True
        capabilities.supports_function_calling = provider in [
            "openai", "anthropic", "minimax", "qwen", "zhipu"
        ]

        # 格式偏好
        if provider in ["openai", "anthropic", "minimax"]:
            capabilities.preferred_format = AiOutputFormat.MARKDOWN
        else:
            capabilities.preferred_format = AiOutputFormat.TEXT

        return capabilities


class PresetDiscovery(BaseAiDiscovery):
    """基于预设配置的能力发现（无需网络请求）"""

    PRESETS: dict[str, AiCapabilities] = {
        "minimax": AiCapabilities(
            provider="minimax",
            model="MiniMax-M2.5",
            supported_inputs=[InputType.TEXT, InputType.IMAGE],
            max_tokens=8000,
            supports_multimodal=True,
            supports_streaming=True,
            supports_function_calling=True,
            preferred_format=AiOutputFormat.MARKDOWN,
            api_version="v1"
        ),
        "openai": AiCapabilities(
            provider="openai",
            model="gpt-4o",
            supported_inputs=[InputType.TEXT, InputType.IMAGE, InputType.AUDIO],
            max_tokens=128000,
            supports_multimodal=True,
            supports_streaming=True,
            supports_function_calling=True,
            preferred_format=AiOutputFormat.MARKDOWN,
            api_version="v1"
        ),
        "anthropic": AiCapabilities(
            provider="anthropic",
            model="claude-3-5-sonnet",
            supported_inputs=[InputType.TEXT, InputType.IMAGE, InputType.DOCUMENT],
            max_tokens=200000,
            supports_multimodal=True,
            supports_streaming=True,
            supports_function_calling=True,
            preferred_format=AiOutputFormat.MARKDOWN,
            api_version="v1"
        ),
        "zhipu": AiCapabilities(
            provider="zhipu",
            model="glm-4",
            supported_inputs=[InputType.TEXT, InputType.IMAGE],
            max_tokens=128000,
            supports_multimodal=True,
            supports_streaming=True,
            supports_function_calling=True,
            preferred_format=AiOutputFormat.TEXT,
            api_version="v4"
        ),
        "qwen": AiCapabilities(
            provider="qwen",
            model="qwen2.5-72b",
            supported_inputs=[InputType.TEXT, InputType.IMAGE],
            max_tokens=128000,
            supports_multimodal=True,
            supports_streaming=True,
            supports_function_calling=True,
            preferred_format=AiOutputFormat.MARKDOWN,
            api_version="v1"
        ),
        "deepseek": AiCapabilities(
            provider="deepseek",
            model="deepseek-chat",
            supported_inputs=[InputType.TEXT],
            max_tokens=64000,
            supports_multimodal=False,
            supports_streaming=True,
            supports_function_calling=True,
            preferred_format=AiOutputFormat.MARKDOWN,
            api_version="v1"
        ),
    }

    def is_compatible(self, endpoint: str) -> bool:
        return True  # 总是兼容，作为兜底方案

    def discover(self, endpoint: str, api_key: str, **kwargs) -> AiCapabilities:
        """根据端点或 provider 参数返回预设配置"""
        provider = kwargs.get("provider", "").lower()

        # 从端点推断 provider
        if not provider:
            endpoint_lower = endpoint.lower()
            for key in self.PRESETS:
                if key in endpoint_lower:
                    provider = key
                    break

        if provider and provider in self.PRESETS:
            preset = self.PRESETS[provider]
            logger.info("使用预设配置: %s", provider)
            return AiCapabilities(
                provider=preset.provider,
                model=preset.model,
                supported_inputs=list(preset.supported_inputs),
                max_tokens=preset.max_tokens,
                supports_multimodal=preset.supports_multimodal,
                supports_streaming=preset.supports_streaming,
                supports_function_calling=preset.supports_function_calling,
                preferred_format=preset.preferred_format,
                api_version=preset.api_version
            )

        # 未知 provider，返回默认配置
        logger.warning("未知 AI 提供商，使用默认配置")
        return AiCapabilities(
            provider=provider or "unknown",
            model="unknown",
            supported_inputs=[InputType.TEXT],
            max_tokens=4096
        )


class AiDiscovery:
    """AI 能力发现器 - 统一管理多种发现方式"""

    def __init__(self):
        self._discoveries: list[BaseAiDiscovery] = [
            OpenAiCompatibleDiscovery(),
            PresetDiscovery(),  # 作为兜底
        ]
        self._cache: dict[str, AiCapabilities] = {}

    def discover(
        self,
        endpoint: str,
        api_key: str,
        provider: str | None = None,
        use_cache: bool = True
    ) -> AiCapabilities:
        """
        发现 AI 能力

        Args:
            endpoint: AI API 端点
            api_key: API 密钥
            provider: 指定提供商（可选，用于预设配置）
            use_cache: 是否使用缓存

        Returns:
            AiCapabilities: AI 能力描述
        """
        cache_key = f"{provider or 'auto'}:{endpoint}"
        logger.info("开始AI能力发现: endpoint=%s, provider=%s, use_cache=%s",
                    endpoint, provider, use_cache)

        if use_cache and cache_key in self._cache:
            cached = self._cache[cache_key]
            logger.info("使用缓存的 AI 能力配置: provider=%s, model=%s", cached.provider, cached.model)
            return cached

        # 如果指定了 provider，优先使用预设
        if provider:
            logger.debug("使用指定provider的预设配置: %s", provider)
            preset = PresetDiscovery()
            caps = preset.discover(endpoint, api_key, provider=provider)
            self._cache[cache_key] = caps
            logger.info("AI能力发现完成(预设): provider=%s, model=%s", caps.provider, caps.model)
            return caps

        # 否则尝试各种发现方式
        for discovery in self._discoveries:
            try:
                if discovery.is_compatible(endpoint):
                    logger.debug("尝试发现方式: %s", type(discovery).__name__)
                    caps = discovery.discover(endpoint, api_key)
                    self._cache[cache_key] = caps
                    logger.info(
                        "AI 能力发现成功: provider=%s, model=%s, 支持=%s, max_tokens=%d",
                        caps.provider, caps.model,
                        [i.value for i in caps.supported_inputs],
                        caps.max_tokens
                    )
                    return caps
            except Exception as e:
                logger.warning("发现方式 %s 失败: %s", type(discovery).__name__, e)
                continue

        # 全部失败，返回默认
        logger.error("所有AI能力发现方式均失败，返回默认配置")
        default = AiCapabilities(provider="unknown", model="unknown")
        self._cache[cache_key] = default
        return default

    def get_preset_capabilities(self, provider: str) -> AiCapabilities | None:
        """获取预设的 AI 能力配置"""
        preset = PresetDiscovery()
        if provider.lower() in preset.PRESETS:
            return preset.PRESETS[provider.lower()]
        return None

    def list_supported_providers(self) -> list[str]:
        """列出支持的 AI 提供商"""
        return list(PresetDiscovery.PRESETS.keys())

    def clear_cache(self):
        """清除能力缓存"""
        self._cache.clear()


# 全局发现器实例
ai_discovery = AiDiscovery()
