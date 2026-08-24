"""
AI 数据转换器服务
自动将各种格式数据转换为AI可识别的标准化数据
"""

import logging
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from __version__ import __version__
from api.v1 import router as v1_router
from api.v2 import router as v2_router
from core.config import settings

# 导出关键组件以支持测试和外部导入
from core.di import data_converter, file_parser  # noqa: F401

# ==================== 日志配置 ====================
from core.logging_config import setup_logging
from core.metrics import MetricsMiddleware, get_metrics_collector
from core.middleware import RateLimitMiddleware, RequestSizeLimitMiddleware, TraceIDMiddleware
from core.models import ResponseCode
from core.utils import generate_request_id

setup_logging(level=getattr(settings, "LOG_LEVEL", "INFO"), json_format=not settings.DEBUG)

logger = logging.getLogger("main")
logger.info("日志系统初始化完成，敏感信息过滤已启用")

# ==================== 创建 FastAPI 应用 ====================

app = FastAPI(title="AI 数据转换器", description="自动将各种格式数据转换为AI可识别的标准化数据", version=__version__)


# ==================== API_KEY 认证依赖 ====================
# 移到 core/auth.py 以避免 main ↔ api.v2 循环导入


# ==================== 全局中间件 ====================

# CORS 中间件
# 注意：allow_origins=["*"] 与 allow_credentials=True 不能共存（浏览器会拒绝）
# 当 ALLOWED_ORIGINS 包含 "*" 时自动设为 allow_credentials=False
_cors_origins = settings.ALLOWED_ORIGINS
_cors_credentials = True
if isinstance(_cors_origins, list) and "*" in _cors_origins:
    _cors_credentials = False
elif _cors_origins == "*":
    _cors_origins = ["*"]
    _cors_credentials = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求频率限制中间件
app.add_middleware(
    RateLimitMiddleware, max_requests=settings.RATE_LIMIT_MAX, window_seconds=60, enabled=settings.RATE_LIMIT_ENABLED
)

# 请求体积限制中间件
app.add_middleware(RequestSizeLimitMiddleware, max_body_size=settings.MAX_REQUEST_SIZE)

# Trace ID 中间件（放在最后，最先执行）
app.add_middleware(TraceIDMiddleware)

# 指标收集中间件（最外层，捕获完整请求耗时）
metrics_collector = get_metrics_collector()
app.add_middleware(MetricsMiddleware, collector=metrics_collector)


# API v1 废弃提示中间件
@app.middleware("http")
async def api_v1_deprecation_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/v1"):
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = "Sat, 01 Jan 2027 00:00:00 GMT"
        response.headers["Link"] = '</api/v2>; rel="successor-version"'
    return response


# ==================== 全局异常处理器 ====================


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器 - 统一错误响应格式（生产环境不泄漏堆栈）"""
    logger.error("未捕获的异常: %s, path=%s, method=%s", exc, request.url.path, request.method, exc_info=True)
    msg = f"服务器内部错误: {str(exc)}" if settings.DEBUG else "服务器内部错误"
    return JSONResponse(
        status_code=500,
        content={"code": ResponseCode.SERVER_ERROR, "msg": msg, "data": None, "requestId": generate_request_id()},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """参数验证异常处理器"""
    logger.warning("参数验证错误: %s, path=%s", exc, request.url.path)
    return JSONResponse(
        status_code=400,
        content={"code": ResponseCode.PARAM_ERROR, "msg": str(exc), "data": None, "requestId": generate_request_id()},
    )


@app.exception_handler(FileNotFoundError)
async def file_not_found_handler(request: Request, exc: FileNotFoundError):
    """文件未找到异常处理器"""
    logger.warning("文件未找到: %s, path=%s", exc, request.url.path)
    return JSONResponse(
        status_code=404,
        content={"code": ResponseCode.NOT_FOUND, "msg": str(exc), "data": None, "requestId": generate_request_id()},
    )


# ==================== 注册路由 ====================

# 只挂载 Vite 的生产构建，避免把 TypeScript 源文件当作可运行的静态站点。
# 开发环境仍由 ``npm run dev`` 提供热更新服务（见 start_frontend_dev）。
frontend_path = Path(__file__).resolve().parent / "frontend"
frontend_dist_path = frontend_path / "dist"
frontend_index_path = frontend_dist_path / "index.html"
frontend_build_available = frontend_index_path.is_file()

if frontend_build_available:
    app.mount("/static", StaticFiles(directory=str(frontend_dist_path), html=True), name="static")
    logger.info("已挂载前端生产构建: %s", frontend_dist_path)
else:
    logger.warning(
        "未找到前端生产构建（%s），/static 未挂载。"
        "开发请运行 npm --prefix frontend run dev；生产请先运行 npm --prefix frontend run build。",
        frontend_index_path,
    )

# 注册 API 路由
app.include_router(v1_router)
app.include_router(v2_router)


# ==================== 基础路由 ====================


@app.get("/")
async def root():
    """根路径 - 返回服务信息和 API 文档链接"""
    return {
        "name": "AI 数据转换器",
        "version": __version__,
        "description": "自动将各种格式数据转换为AI可识别的标准化数据",
        "docs": "/docs",
        "health": "/health",
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    from core.utils import create_response

    return create_response(
        code=ResponseCode.SUCCESS,
        msg="服务运行正常",
        data={"status": "healthy", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"), "version": __version__},
    )


@app.get("/debug/config")
async def debug_config():
    """调试配置接口 - 仅 DEBUG 模式下可用"""
    if not settings.DEBUG:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=403, content={"code": 403, "msg": "调试接口仅在 DEBUG 模式下可用", "data": None}
        )
    from core.utils import create_response

    return create_response(
        code=ResponseCode.SUCCESS,
        msg="调试配置信息",
        data={
            "app_host": settings.APP_HOST,
            "app_port": settings.APP_PORT,
            "debug": settings.DEBUG,
            "minimax_base_url": settings.MINIMAX_BASE_URL,
            "ai_provider": settings.AI_PROVIDER,
            "upload_dir": str(settings.UPLOAD_DIR),
            "max_file_size": settings.MAX_FILE_SIZE,
            "rate_limit_max": settings.RATE_LIMIT_MAX,
            "rate_limit_enabled": settings.RATE_LIMIT_ENABLED,
            "ai_timeout": settings.AI_TIMEOUT,
            "file_type_validation": settings.FILE_TYPE_VALIDATION,
        },
    )


# ==================== 启动服务 ====================


def is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    """检测指定端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def start_frontend_dev():
    """启动前端开发服务器（npm run dev）"""
    frontend_dir = Path(__file__).parent / "frontend"
    if not frontend_dir.exists():
        logger.warning("前端目录不存在: %s", frontend_dir)
        return None

    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    try:
        logger.info("正在启动前端开发服务器...")
        proc = subprocess.Popen(
            [npm_cmd, "run", "dev"],
            cwd=str(frontend_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=(sys.platform == "win32"),
        )
        return proc
    except Exception as e:
        logger.error("启动前端开发服务器失败: %s", e)
        return None


def open_browser_delayed(url: str, delay: int = 4):
    """延迟打开浏览器，确保服务已启动"""
    time.sleep(delay)
    logger.info("正在打开前端页面: %s", url)
    webbrowser.open(url)


if __name__ == "__main__":
    FRONTEND_PORT = 3000
    FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}/"
    BACKEND_URL = f"http://localhost:{settings.APP_PORT}/static/index.html"
    API_URL = f"http://localhost:{settings.APP_PORT}/"

    logger.info("=" * 60)
    logger.info("       AI 数据转换器")
    logger.info("       自动将各种格式数据转换为AI可识别的标准化数据")
    logger.info("=" * 60)
    logger.info("后端服务: http://%s:%d", settings.APP_HOST, settings.APP_PORT)
    logger.info("API 文档: http://%s:%d/docs", settings.APP_HOST, settings.APP_PORT)

    # 检测前端开发服务器是否已在运行
    if is_port_open(FRONTEND_PORT):
        logger.info("前端开发服务器已在运行: %s", FRONTEND_URL)
        target_url = FRONTEND_URL
    else:
        # 尝试启动前端开发服务器
        frontend_proc = start_frontend_dev()
        if frontend_proc:
            logger.info("前端开发服务器启动中，请稍候...")
            time.sleep(5)  # 等待前端启动
            target_url = FRONTEND_URL
        elif frontend_build_available:
            logger.info("前端开发服务器未启动，使用生产构建: %s", BACKEND_URL)
            target_url = BACKEND_URL
        else:
            logger.warning("前端开发服务器和生产构建均不可用，打开 API 服务页: %s", API_URL)
            target_url = API_URL

    logger.info("打开页面: %s", target_url)
    logger.info("=" * 60)

    # 在新线程中延迟打开浏览器
    browser_thread = threading.Thread(target=open_browser_delayed, args=(target_url,), daemon=True)
    browser_thread.start()

    uvicorn.run("main:app", host=settings.APP_HOST, port=settings.APP_PORT, reload=settings.DEBUG)
