"""
自定义中间件模块
请求频率限制、请求体积限制等
"""

import logging
import time
import uuid
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from core.models import ResponseCode

logger = logging.getLogger("middleware")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    请求频率限制中间件

    基于客户端 IP 限制请求频率，超过限制返回 429
    """

    def __init__(self, app: ASGIApp, max_requests: int = 60, window_seconds: int = 60, enabled: bool = True):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.enabled = enabled
        # IP -> [(timestamp, count)]
        self._requests: dict[str, list] = defaultdict(list)
        logger.info("RateLimitMiddleware 初始化: max=%d/%ds, enabled=%s", max_requests, window_seconds, enabled)

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        client_ip = self._get_client_ip(request)

        if not self._check_rate_limit(client_ip):
            logger.warning("请求频率超限: ip=%s, path=%s", client_ip, request.url.path)
            return JSONResponse(
                status_code=429,
                content={
                    "code": ResponseCode.SERVICE_UNAVAILABLE,
                    "msg": f"请求频率超限，请稍后重试（限制: {self.max_requests}/{self.window_seconds}秒）",
                    "data": None,
                    "requestId": "",
                },
            )

        response = await call_next(request)
        return response

    def _get_client_ip(self, request: Request) -> str:
        """获取客户端 IP"""
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            return real_ip
        return request.client.host if request.client else "unknown"

    def _check_rate_limit(self, client_ip: str) -> bool:
        """检查是否超过频率限制"""
        now = time.time()
        window_start = now - self.window_seconds

        # 清理过期记录
        self._requests[client_ip] = [t for t in self._requests[client_ip] if t > window_start]

        # 检查是否超限
        if len(self._requests[client_ip]) >= self.max_requests:
            return False

        # 记录请求
        self._requests[client_ip].append(now)
        return True


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    请求体积限制中间件

    限制请求 body 大小
    """

    def __init__(self, app: ASGIApp, max_body_size: int = 100 * 1024 * 1024):
        super().__init__(app)
        self.max_body_size = max_body_size

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("Content-Length")
        if content_length and int(content_length) > self.max_body_size:
            logger.warning("请求体积超限: Content-Length=%s, max=%d", content_length, self.max_body_size)
            return JSONResponse(
                status_code=413,
                content={
                    "code": ResponseCode.PARAM_ERROR,
                    "msg": f"请求体积超过限制，最大支持 {self.max_body_size // 1024 // 1024}MB",
                    "data": None,
                    "requestId": "",
                },
            )
        return await call_next(request)


class TraceIDMiddleware(BaseHTTPMiddleware):
    """
    Trace ID 中间件

    为每个请求分配唯一 Trace ID，注入到请求状态和日志中
    """

    def __init__(self, app: ASGIApp, header_name: str = "X-Trace-ID"):
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next):
        # 从请求头获取 Trace ID，不存在则生成
        trace_id = request.headers.get(self.header_name) or uuid.uuid4().hex
        request.state.trace_id = trace_id

        # 记录请求开始
        start = time.time()
        method = request.method
        path = request.url.path

        logger.info(
            "请求开始",
            extra={"trace_id": trace_id, "request_method": method, "request_path": path},
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = int((time.time() - start) * 1000)
            logger.error(
                "请求异常: %s",
                exc,
                extra={
                    "trace_id": trace_id,
                    "request_method": method,
                    "request_path": path,
                    "duration_ms": duration_ms,
                },
            )
            raise

        # 记录请求完成
        duration_ms = int((time.time() - start) * 1000)
        logger.info(
            "请求完成",
            extra={
                "trace_id": trace_id,
                "request_method": method,
                "request_path": path,
                "duration_ms": duration_ms,
                "status_code": response.status_code,
            },
        )

        response.headers[self.header_name] = trace_id
        return response
