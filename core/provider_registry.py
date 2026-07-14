"""
统一 AI Provider 注册表

合并原有分散在多处的 AI 配置：
- ai_discovery.py 的能力预设 (PresetDiscovery.PRESETS)
- ai_client.py 的客户端工厂 (create_ai_client)
- config.py 的 Provider 配置项

提供统一的 Provider 注册、能力查询、客户端创建接口。
"""

import logging
from dataclasses import dataclass
from typing import Any

from core.ai_client import (
    AIClient,
    MiniMaxClient,
    OpenAIClient,
)
from core.ai_discovery import (
    AiCapabilities,
    AiDiscovery,
    AiOutputFormat,
    InputType,
)
from core.config import settings

logger = logging.getLogger("provider_registry")


# ═══════════════════════════════════════════════════════════
# Provider 注册信息
# ═══════════════════════════════════════════════════════════


@dataclass
class ProviderInfo:
    """Provider 完整注册信息"""

    name: str
    capabilities: AiCapabilities
    client_class: type[AIClient] | None = None
    env_prefix: str = ""
    default_base_url: str = ""
    default_model: str = ""

    @property
    def is_available(self) -> bool:
        """检查该 Provider 是否已配置 API Key"""
        if not self.env_prefix:
            return False
        key_attr = f"{self.env_prefix}_API_KEY"
        api_key = getattr(settings, key_attr, "")
        return bool(api_key)


class ProviderRegistry:
    """
    统一 AI Provider 注册表

    功能：
    - 管理所有支持的 AI Provider（运行时客户端 + 能力预设）
    - 提供统一的客户端创建接口
    - 提供能力查询接口
    """

    def __init__(self):
        self._providers: dict[str, ProviderInfo] = {}
        self._ai_discovery = AiDiscovery()
        self._register_defaults()
        logger.info("ProviderRegistry 初始化完成: 已注册 %d 个Provider", len(self._providers))

    def _register_defaults(self):
        """注册 6 个内置 Provider"""
        self._providers = {
            "minimax": ProviderInfo(
                name="minimax",
                capabilities=AiCapabilities(
                    provider="minimax",
                    model="MiniMax-M2.5",
                    supported_inputs=[InputType.TEXT, InputType.IMAGE],
                    max_tokens=8000,
                    supports_multimodal=True,
                    supports_streaming=True,
                    supports_function_calling=True,
                    preferred_format=AiOutputFormat.MARKDOWN,
                    api_version="v1",
                ),
                client_class=MiniMaxClient,
                env_prefix="MINIMAX",
                default_base_url="https://api.minimaxi.com/v1",
                default_model="MiniMax-M2.5",
            ),
            "openai": ProviderInfo(
                name="openai",
                capabilities=AiCapabilities(
                    provider="openai",
                    model="gpt-4o",
                    supported_inputs=[InputType.TEXT, InputType.IMAGE, InputType.AUDIO],
                    max_tokens=128000,
                    supports_multimodal=True,
                    supports_streaming=True,
                    supports_function_calling=True,
                    preferred_format=AiOutputFormat.MARKDOWN,
                    api_version="v1",
                ),
                client_class=OpenAIClient,
                env_prefix="OPENAI",
                default_base_url="https://api.openai.com/v1",
                default_model="gpt-4o-mini",
            ),
            "anthropic": ProviderInfo(
                name="anthropic",
                capabilities=AiCapabilities(
                    provider="anthropic",
                    model="claude-3-5-sonnet",
                    supported_inputs=[InputType.TEXT, InputType.IMAGE, InputType.DOCUMENT],
                    max_tokens=200000,
                    supports_multimodal=True,
                    supports_streaming=True,
                    supports_function_calling=True,
                    preferred_format=AiOutputFormat.MARKDOWN,
                    api_version="v1",
                ),
                env_prefix="ANTHROPIC",
                default_model="claude-3-5-sonnet",
            ),
            "zhipu": ProviderInfo(
                name="zhipu",
                capabilities=AiCapabilities(
                    provider="zhipu",
                    model="glm-4",
                    supported_inputs=[InputType.TEXT, InputType.IMAGE],
                    max_tokens=128000,
                    supports_multimodal=True,
                    supports_streaming=True,
                    supports_function_calling=True,
                    preferred_format=AiOutputFormat.TEXT,
                    api_version="v4",
                ),
                client_class=OpenAIClient,
                env_prefix="ZHIPU",
                default_base_url="https://open.bigmodel.cn/api/paas/v4",
                default_model="glm-4-flash",
            ),
            "qwen": ProviderInfo(
                name="qwen",
                capabilities=AiCapabilities(
                    provider="qwen",
                    model="qwen2.5-72b",
                    supported_inputs=[InputType.TEXT, InputType.IMAGE],
                    max_tokens=128000,
                    supports_multimodal=True,
                    supports_streaming=True,
                    supports_function_calling=True,
                    preferred_format=AiOutputFormat.MARKDOWN,
                    api_version="v1",
                ),
                env_prefix="QWEN",
                default_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                default_model="qwen-turbo",
            ),
            "deepseek": ProviderInfo(
                name="deepseek",
                capabilities=AiCapabilities(
                    provider="deepseek",
                    model="deepseek-chat",
                    supported_inputs=[InputType.TEXT],
                    max_tokens=64000,
                    supports_multimodal=False,
                    supports_streaming=True,
                    supports_function_calling=True,
                    preferred_format=AiOutputFormat.MARKDOWN,
                    api_version="v1",
                ),
                client_class=OpenAIClient,
                env_prefix="DEEPSEEK",
                default_base_url="https://api.deepseek.com/v1",
                default_model="deepseek-chat",
            ),
        }

    # ═══════════════════════════════════════════
    # Provider 查询
    # ═══════════════════════════════════════════

    def get(self, name: str) -> ProviderInfo | None:
        """根据名称获取 Provider 信息"""
        return self._providers.get(name.lower())

    def list_providers(self) -> list[str]:
        """列出所有已注册的 Provider 名称"""
        return list(self._providers.keys())

    def list_available(self) -> list[str]:
        """列出已配置 API Key 的 Provider"""
        return [name for name, info in self._providers.items() if info.is_available]

    def get_capabilities(self, name: str) -> AiCapabilities | None:
        """获取指定 Provider 的能力描述"""
        info = self.get(name)
        return info.capabilities if info else None

    def get_all_capabilities(self) -> dict[str, AiCapabilities]:
        """获取所有 Provider 的能力描述"""
        return {name: info.capabilities for name, info in self._providers.items()}

    def discover(
        self,
        endpoint: str,
        api_key: str,
        provider: str | None = None,
        use_cache: bool = True,
    ) -> AiCapabilities:
        """AI 能力发现（委托给 AiDiscovery）"""
        return self._ai_discovery.discover(endpoint, api_key, provider=provider, use_cache=use_cache)

    # ═══════════════════════════════════════════
    # 客户端创建
    # ═══════════════════════════════════════════

    def create_client(
        self,
        provider: str = "minimax",
        timeout: int = 120,
        **kwargs: Any,
    ) -> AIClient | None:
        """
        根据 Provider 名称创建 AI 客户端实例

        优先从 kwargs 获取配置，否则从 settings 获取。

        Args:
            provider: Provider 名称 (minimax, openai, zhipu, qwen, deepseek)
            timeout: API 超时时间
            **kwargs: api_key, base_url, model 等覆盖参数

        Returns:
            AIClient 实例，如果无法创建返回 None
        """
        provider_name = provider.lower()
        info = self.get(provider_name)

        if info is None:
            logger.error("未知的 AI Provider: %s", provider_name)
            raise ValueError(f"不支持的 AI 提供商: {provider_name}，支持: {self.list_providers()}")

        # 获取配置：kwargs > env > defaults
        api_key = kwargs.get("api_key") or getattr(settings, f"{info.env_prefix}_API_KEY", "")
        base_url = (
            kwargs.get("base_url") or getattr(settings, f"{info.env_prefix}_BASE_URL", "") or info.default_base_url
        )

        if not api_key:
            logger.warning(
                "Provider %s 未配置 API Key (env: %s_API_KEY)",
                provider_name,
                info.env_prefix,
            )
            return None

        if info.client_class is None:
            logger.warning("Provider %s 无可用客户端实现", provider_name)
            return None

        try:
            client = info.client_class(api_key=api_key, base_url=base_url, timeout=timeout)
            logger.info(
                "AI 客户端创建成功: provider=%s, base_url=%s",
                provider_name,
                base_url,
            )
            return client
        except Exception as e:
            logger.error("AI 客户端创建失败: provider=%s, error=%s", provider_name, e)
            return None


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

provider_registry = ProviderRegistry()


# ═══════════════════════════════════════════════════════════
# 向后兼容的函数（替代 ai_client.create_ai_client）
# ═══════════════════════════════════════════════════════════


def create_ai_client(provider: str = "minimax", timeout: int = 120, **kwargs: Any) -> AIClient:
    """
    创建 AI 客户端工厂函数（兼容旧接口）

    新代码请直接使用 provider_registry.create_client()
    """
    client = provider_registry.create_client(provider=provider, timeout=timeout, **kwargs)
    if client is None:
        raise ValueError(f"无法创建 AI 客户端: provider={provider}，请检查 API Key 配置")
    return client
