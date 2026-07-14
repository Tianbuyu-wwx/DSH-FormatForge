"""
认证依赖 — API Key 验证 (Bearer Token)

设计原则：
- API_KEY 为空时跳过认证（开发模式）
- API_KEY 设置时，验证 `Authorization: Bearer <key>` 头
- 用 hmac.compare_digest 防止时序攻击
- 仅用于写接口（POST/PUT/DELETE/PATCH）；GET 接口保持公开
"""

import hmac

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import settings

_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> bool:
    """
    验证 API Key（Bearer Token）。

    - 若 settings.API_KEY 为空字符串（开发模式），跳过认证
    - 若设置了 API_KEY，则 Authorization: Bearer <key> 必须匹配
    """
    if not settings.API_KEY:
        return True  # 认证未启用

    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Authorization: Bearer <api_key>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not hmac.compare_digest(credentials.credentials, settings.API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API Key 不正确",
        )
    return True
