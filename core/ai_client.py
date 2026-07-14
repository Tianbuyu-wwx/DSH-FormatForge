"""
AI 客户端模块
支持多种 AI 服务：MiniMax、OpenAI、智谱 AI

MiniMax API 调用说明：
- Token Plan API Key 使用方式与标准 API 不同
- 图片输入仅支持通过 Anthropic API 格式的 tool_result 方式
- OpenAI SDK 方式不支持图片输入

参考文档：
- https://platform.minimaxi.com/docs/api-reference/text-openai-api
- https://platform.minimaxi.com/docs/api-reference/text-anthropic-api
- https://platform.minimaxi.com/docs/token-plan/mcp-guide#understand-image
"""

import base64
import logging
import threading
from abc import ABC, abstractmethod

# 尝试导入各种 SDK
try:
    from openai import OpenAI

    OPENAI_SDK_AVAILABLE = True
except ImportError:
    OPENAI_SDK_AVAILABLE = False

try:
    import anthropic

    ANTHROPIC_SDK_AVAILABLE = True
except ImportError:
    ANTHROPIC_SDK_AVAILABLE = False


class AIClient(ABC):
    """AI 客户端抽象基类"""

    @abstractmethod
    def generate_text(self, prompt: str, image_paths: list[str] | None = None) -> str:
        """生成文本"""
        pass


class MiniMaxClient(AIClient):
    """
    MiniMax AI 客户端 (Token Plan 版本)

    Token Plan 特点：
    1. 使用专属 API Key (以 sk-cp- 开头)
    2. 支持 OpenAI SDK 格式（纯文本）
    3. 支持 Anthropic SDK 格式（文本 + 图片）
    4. 图片必须通过 tool_result 方式传入

    API 端点：
    - OpenAI 兼容: https://api.minimaxi.com/v1
    - Anthropic 兼容: https://api.minimaxi.com/anthropic
    """

    _instance = None
    _initialized = False
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, api_key: str, base_url: str = "https://api.minimaxi.com/v1", timeout: int = 120):
        # 避免重复初始化
        if MiniMaxClient._initialized:
            return

        with MiniMaxClient._lock:
            # 双重检查
            if MiniMaxClient._initialized:
                return

            self.api_key = api_key
            self.base_url = base_url.rstrip("/")
            self.timeout = timeout
            self.logger = logging.getLogger("ai_client.minimax")

            # 根据是否有图片输入选择客户端
            self.openai_client = None
            self.anthropic_client = None

            # 初始化 OpenAI 客户端
            if OPENAI_SDK_AVAILABLE:
                try:
                    self.openai_client = OpenAI(api_key=self.api_key, base_url=self.base_url)
                    self.logger.info("OpenAI SDK 初始化成功")
                except Exception as e:
                    self.logger.error("OpenAI SDK 初始化失败: %s", e)

            # 初始化 Anthropic 客户端（用于图片输入）
            if ANTHROPIC_SDK_AVAILABLE:
                try:
                    anthropic_base_url = self.base_url.replace("/v1", "/anthropic")
                    self.anthropic_client = anthropic.Anthropic(api_key=self.api_key, base_url=anthropic_base_url)
                    self.logger.info("Anthropic SDK 初始化成功")
                except Exception as e:
                    self.logger.error("Anthropic SDK 初始化失败: %s", e)

            MiniMaxClient._initialized = True

    def _encode_image(self, image_path: str) -> str | None:
        """将图片编码为 base64"""
        try:
            with open(image_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            self.logger.error("图片编码失败: %s", e)
            return None

    def generate_text(self, prompt: str, image_paths: list[str] | None = None) -> str:
        """
        生成文本

        策略：
        - 无图片：使用 OpenAI SDK（更简单）
        - 有图片：使用 Anthropic SDK + tool_result 方式
        """
        if image_paths and len(image_paths) > 0:
            # 有图片输入，使用 Anthropic SDK
            if not self.anthropic_client:
                raise RuntimeError("Anthropic SDK 未安装，无法处理图片输入。请运行: pip install anthropic")
            return self._generate_with_anthropic(prompt, image_paths)
        else:
            # 纯文本，使用 OpenAI SDK
            if not self.openai_client:
                raise RuntimeError("OpenAI SDK 未安装。请运行: pip install openai")
            return self._generate_with_openai(prompt)

    def _generate_with_openai(self, prompt: str) -> str:
        """
        使用 OpenAI SDK 调用 MiniMax API（纯文本模式）

        注意：OpenAI SDK 方式不支持图片输入
        """
        self.logger.info("使用 OpenAI SDK (纯文本模式)...")

        messages = [
            {"role": "system", "content": "你是一个数据转换助手，擅长将各种格式的数据转换为AI可理解的标准化格式。"},
            {"role": "user", "content": prompt},
        ]

        self.logger.info("OpenAI SDK 请求超时设置: %d秒", self.timeout)
        response = self.openai_client.chat.completions.create(
            model="MiniMax-M2.5", messages=messages, temperature=0.7, max_tokens=8000, timeout=self.timeout
        )

        return response.choices[0].message.content

    def _generate_with_anthropic(self, prompt: str, image_paths: list[str]) -> str:
        """
        使用 Anthropic SDK 调用 MiniMax API（支持图片输入）

        图片处理方式：
        1. 添加 tool_use 消息（assistant 角色）
        2. 添加 tool_result 消息（user 角色）包含图片
        3. 添加用户提示消息

        参考：https://platform.minimaxi.com/docs/api-reference/text-anthropic-api
        """
        self.logger.info("使用 Anthropic SDK (图片模式)，共 %d 张图片...", len(image_paths))

        # 构建消息列表
        messages = []

        # 第一步：添加 assistant 的 tool_use 请求
        tool_call_id = "analyze_images"
        messages.append(
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": tool_call_id, "name": "understand_image", "input": {}}],
            }
        )

        # 第二步：添加 tool_result 消息（包含图片）
        tool_result_content = []
        for img_path in image_paths[:5]:  # 最多5张图片
            base64_image = self._encode_image(img_path)
            if base64_image:
                # Anthropic 格式的图片
                tool_result_content.append(
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64_image}}
                )

        if tool_result_content:
            messages.append(
                {
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": tool_call_id, "content": tool_result_content}],
                }
            )

        # 第三步：添加用户提示
        messages.append({"role": "user", "content": [{"type": "text", "text": prompt}]})

        # 调用 Anthropic API
        self.logger.info("Anthropic SDK 请求超时设置: %d秒", self.timeout)
        response = self.anthropic_client.messages.create(
            model="MiniMax-M2.5",
            max_tokens=8000,
            system="你是一个数据转换助手，擅长将各种格式的数据（包括图片）转换为AI可理解的标准化格式。",
            messages=messages,
        )

        # 提取文本内容
        result_text = ""
        for block in response.content:
            if block.type == "text":
                result_text += block.text

        return result_text

    def _generate_with_http(self, prompt: str, image_paths: list[str] | None = None) -> str:
        """
        使用 HTTP 请求调用 MiniMax API（备用方案，使用 httpx）

        注意：Token Plan 的 API Key 可能不支持标准 HTTP 接口
        """
        import httpx

        self.logger.info("使用 HTTP 请求...")

        url = f"{self.base_url}/chat/completions"

        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        messages = [
            {"role": "system", "content": "你是一个数据转换助手，擅长将各种格式的数据转换为AI可理解的标准化格式。"},
            {"role": "user", "content": prompt},
        ]

        data = {"model": "MiniMax-M2.5", "messages": messages, "temperature": 0.7, "max_tokens": 8000}

        response = httpx.post(url, headers=headers, json=data, timeout=120)
        response.raise_for_status()

        result = response.json()

        if "choices" in result and len(result["choices"]) > 0:
            return result["choices"][0]["message"]["content"]
        else:
            raise RuntimeError(f"MiniMax API 返回异常: {result}")


class OpenAIClient(AIClient):
    """OpenAI 客户端（备选方案）"""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", timeout: int = 120):
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        self.logger = logging.getLogger("ai_client.openai")

        if not OPENAI_SDK_AVAILABLE:
            raise RuntimeError("OpenAI SDK 未安装，请运行: pip install openai")

        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.logger.info("客户端初始化成功")

    def _encode_image(self, image_path: str) -> str | None:
        """将图片编码为 base64"""
        try:
            with open(image_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            self.logger.error("图片编码失败: %s", e)
            return None

    def generate_text(self, prompt: str, image_paths: list[str] | None = None) -> str:
        """生成文本"""
        messages = [
            {"role": "system", "content": "你是一个数据转换助手，擅长将各种格式的数据转换为AI可理解的标准化格式。"}
        ]

        # 构建用户消息
        if image_paths:
            content = [{"type": "text", "text": prompt}]
            for img_path in image_paths[:5]:
                base64_image = self._encode_image(img_path)
                if base64_image:
                    content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}})
            messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": prompt})

        response = self.client.chat.completions.create(
            model="gpt-4o-mini", messages=messages, temperature=0.7, max_tokens=4000, timeout=self.timeout
        )

        return response.choices[0].message.content


def create_ai_client(provider: str = "minimax", timeout: int = 120, **kwargs) -> AIClient:
    """
    创建 AI 客户端工厂函数

    Args:
        provider: AI 服务提供商 (minimax, openai)
        timeout: API 调用超时时间（秒）
        **kwargs: 传递给客户端的参数

    Returns:
        AIClient: AI 客户端实例
    """
    provider = provider.lower()

    if provider == "minimax":
        return MiniMaxClient(
            api_key=kwargs.get("api_key"),
            base_url=kwargs.get("base_url", "https://api.minimaxi.com/v1"),
            timeout=timeout,
        )
    elif provider == "openai":
        return OpenAIClient(
            api_key=kwargs.get("api_key"), base_url=kwargs.get("base_url", "https://api.openai.com/v1"), timeout=timeout
        )
    else:
        raise ValueError(f"不支持的 AI 提供商: {provider}")
