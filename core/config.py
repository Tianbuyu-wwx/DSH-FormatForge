"""
应用配置模块
使用 Pydantic Settings 统一管理所有配置
"""
import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class AppSettings(BaseSettings):
    """
    应用配置 - 使用 Pydantic BaseSettings

    支持从环境变量、.env 文件加载配置
    """

    # 路径配置
    BASE_DIR: Path = Field(default_factory=lambda: Path(__file__).parent.parent)
    UPLOAD_DIR: Path = Field(default=Path("./uploads"))

    # AI 服务提供商配置
    AI_PROVIDER: str = Field(default="minimax", description="可选: minimax, openai, zhipu")

    # MiniMax API 配置
    MINIMAX_API_KEY: str = Field(default="")
    MINIMAX_GROUP_ID: str = Field(default="")
    MINIMAX_BASE_URL: str = Field(default="https://api.minimaxi.com/v1")

    # OpenAI API 配置
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_BASE_URL: str = Field(default="https://api.openai.com/v1")

    # 智谱 AI 配置
    ZHIPU_API_KEY: str = Field(default="")

    # 应用配置
    APP_HOST: str = Field(default="0.0.0.0")
    APP_PORT: int = Field(default=8000)
    DEBUG: bool = Field(default=False)
    LOG_LEVEL: str = Field(default="INFO")

    # 文件上传配置
    MAX_FILE_SIZE: int = Field(default=52428800, description="50MB")
    MAX_REQUEST_SIZE: int = Field(default=104857600, description="100MB - 请求体积限制")

    # 签名密钥
    STATIC_KEY: str = Field(default="your_static_key_here")

    # 缓存配置
    CACHE_MAX_ENTRIES: int = Field(default=1000)
    CACHE_TTL: int = Field(default=3600, description="缓存过期时间（秒）")
    CACHE_PERSIST_ENABLED: bool = Field(default=True)
    CACHE_PERSIST_PATH: Optional[Path] = Field(default=None)

    # 并发配置
    MAX_CONCURRENT_AI: int = Field(default=5)
    AI_TIMEOUT: int = Field(default=120, description="AI 调用超时时间（秒）")

    # 安全配置
    RATE_LIMIT_ENABLED: bool = Field(default=True)
    RATE_LIMIT_MAX: int = Field(default=60, description="每分钟最大请求数")
    FILE_TYPE_VALIDATION: bool = Field(default=True)
    URL_DOMAIN_VALIDATION: bool = Field(default=True)
    ALLOWED_ORIGINS: list = Field(default=["*"], description="CORS 允许的域名，生产环境应设为具体域名")

    # 支持的配置
    SUPPORTED_FILE_TYPES: dict = Field(default={
        "ppt": [".ppt", ".pptx"],
        "pdf": [".pdf"]
    })

    @field_validator("UPLOAD_DIR", mode="before")
    @classmethod
    def ensure_upload_dir(cls, v):
        path = Path(v)
        path.mkdir(exist_ok=True)
        return path

    @field_validator("CACHE_PERSIST_PATH", mode="before")
    @classmethod
    def ensure_cache_path(cls, v):
        if v is None:
            return Path(__file__).parent.parent / "cache"
        path = Path(v)
        path.mkdir(parents=True, exist_ok=True)
        return path

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


# 全局配置实例
settings = AppSettings()

# 兼容旧版导入（保持向后兼容）
BASE_DIR = settings.BASE_DIR
UPLOAD_DIR = settings.UPLOAD_DIR
AI_PROVIDER = settings.AI_PROVIDER
MINIMAX_API_KEY = settings.MINIMAX_API_KEY
MINIMAX_GROUP_ID = settings.MINIMAX_GROUP_ID
MINIMAX_BASE_URL = settings.MINIMAX_BASE_URL
OPENAI_API_KEY = settings.OPENAI_API_KEY
OPENAI_BASE_URL = settings.OPENAI_BASE_URL
ZHIPU_API_KEY = settings.ZHIPU_API_KEY
APP_HOST = settings.APP_HOST
APP_PORT = settings.APP_PORT
DEBUG = settings.DEBUG
MAX_FILE_SIZE = settings.MAX_FILE_SIZE
STATIC_KEY = settings.STATIC_KEY