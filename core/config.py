"""
应用配置模块
使用 Pydantic Settings 统一管理配置（插件形态：仅保留转换管线所需字段）
"""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """
    应用配置 - 使用 Pydantic BaseSettings

    支持从环境变量、.env 文件加载配置。
    """

    # 路径配置
    BASE_DIR: Path = Field(default_factory=lambda: Path(__file__).parent.parent)
    UPLOAD_DIR: Path = Field(default=Path("./uploads"))

    # 应用配置
    DEBUG: bool = Field(default=False)
    LOG_LEVEL: str = Field(default="INFO")

    # 文件大小限制（JS 侧 spawn 前也会做同样 clamp）
    FF_MAX_BYTES: int = Field(default=100 * 1024 * 1024, description="单文件最大字节数，默认 100MB")
    FF_TIMEOUT_S: int = Field(default=120, description="单次转换超时秒数（执行方在 JS 侧）")

    # 缓存配置
    CACHE_MAX_ENTRIES: int = Field(default=1000)
    CACHE_TTL: int = Field(default=3600, description="缓存过期时间（秒）")
    CACHE_PERSIST_ENABLED: bool = Field(default=True)
    CACHE_PERSIST_PATH: Path | None = Field(default=None)

    # OCR 可选后端开关（本地 tesseract 等；无 AI 云后端）
    OCR_ENABLED: bool = Field(default=True)

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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


# 全局配置实例
settings = AppSettings()

# 兼容旧版导入（保持向后兼容）
BASE_DIR = settings.BASE_DIR
UPLOAD_DIR = settings.UPLOAD_DIR
DEBUG = settings.DEBUG
MAX_FILE_SIZE = settings.FF_MAX_BYTES
