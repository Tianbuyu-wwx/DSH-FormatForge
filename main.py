"""
AI 数据转换器服务
自动将各种格式数据转换为AI可识别的标准化数据
"""
import os
import webbrowser
import threading
import time
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

from core.config import settings
from core.models import ResponseCode, ResponseMsg
from core.utils import generate_request_id
from core.security import SensitiveDataFilter
from core.middleware import RateLimitMiddleware, RequestSizeLimitMiddleware

from api.v1 import router as v1_router
from api.v2 import router as v2_router

# 导出关键组件以支持测试和外部导入
from core.di import data_converter, file_parser

# ==================== 日志配置 ====================

class SensitiveFormatter(logging.Formatter):
    """敏感信息脱敏格式化器"""
    def format(self, record: logging.LogRecord) -> str:
        from core.security import mask_sensitive_info
        original = super().format(record)
        return mask_sensitive_info(original)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

# 为关键日志器添加敏感信息过滤
for logger_name in ["main", "api", "converter_engine", "ai_client", "file_parser"]:
    logger_instance = logging.getLogger(logger_name)
    logger_instance.addFilter(SensitiveDataFilter())

logger = logging.getLogger("main")
logger.info("日志系统初始化完成，敏感信息过滤已启用")

# ==================== 创建 FastAPI 应用 ====================

app = FastAPI(
    title="AI 数据转换器",
    description="自动将各种格式数据转换为AI可识别的标准化数据",
    version="2.1.0"
)

# ==================== 全局中间件 ====================

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 请求频率限制中间件
app.add_middleware(
    RateLimitMiddleware,
    max_requests=settings.RATE_LIMIT_MAX,
    window_seconds=60,
    enabled=settings.RATE_LIMIT_ENABLED
)

# 请求体积限制中间件
app.add_middleware(
    RequestSizeLimitMiddleware,
    max_body_size=settings.MAX_REQUEST_SIZE
)

# ==================== 全局异常处理器 ====================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器 - 统一错误响应格式"""
    logger.error("未捕获的异常: %s, path=%s, method=%s",
                 exc, request.url.path, request.method, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "code": ResponseCode.SERVER_ERROR,
            "msg": f"服务器内部错误: {str(exc)}",
            "data": None,
            "requestId": generate_request_id()
        }
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    """参数验证异常处理器"""
    logger.warning("参数验证错误: %s, path=%s", exc, request.url.path)
    return JSONResponse(
        status_code=400,
        content={
            "code": ResponseCode.PARAM_ERROR,
            "msg": str(exc),
            "data": None,
            "requestId": generate_request_id()
        }
    )


@app.exception_handler(FileNotFoundError)
async def file_not_found_handler(request: Request, exc: FileNotFoundError):
    """文件未找到异常处理器"""
    logger.warning("文件未找到: %s, path=%s", exc, request.url.path)
    return JSONResponse(
        status_code=404,
        content={
            "code": ResponseCode.NOT_FOUND,
            "msg": str(exc),
            "data": None,
            "requestId": generate_request_id()
        }
    )

# ==================== 注册路由 ====================

# 挂载前端静态文件
frontend_path = Path(__file__).parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path), html=True), name="static")

# 注册 API 路由
app.include_router(v1_router)
app.include_router(v2_router)


# ==================== 基础路由 ====================

@app.get("/")
async def root():
    """根路径 - 返回服务信息和 API 文档链接"""
    return {
        "name": "AI 数据转换器",
        "version": "2.1.0",
        "description": "自动将各种格式数据转换为AI可识别的标准化数据",
        "docs": "/docs",
        "health": "/health",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """健康检查"""
    from core.utils import create_response
    return create_response(
        code=ResponseCode.SUCCESS,
        msg="服务运行正常",
        data={
            "status": "healthy",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "version": "2.1.0"
        }
    )


@app.get("/debug/config")
async def debug_config():
    """调试配置接口 - 返回非敏感配置信息"""
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
            "file_type_validation": settings.FILE_TYPE_VALIDATION
        }
    )


# ==================== 启动服务 ====================

def open_browser(url: str):
    """延迟打开浏览器，确保服务已启动"""
    time.sleep(3)
    logger.info("正在打开前端页面: %s", url)
    webbrowser.open(url)


if __name__ == "__main__":
    frontend_url = f"http://localhost:{settings.APP_PORT}/static/index.html"

    logger.info("=" * 60)
    logger.info("       AI 数据转换器")
    logger.info("       自动将各种格式数据转换为AI可识别的标准化数据")
    logger.info("=" * 60)
    logger.info("服务地址: http://%s:%d", settings.APP_HOST, settings.APP_PORT)
    logger.info("API 文档: http://%s:%d/docs", settings.APP_HOST, settings.APP_PORT)
    logger.info("前端页面: %s", frontend_url)
    logger.info("=" * 60)

    # 在新线程中延迟打开浏览器
    browser_thread = threading.Thread(target=open_browser, args=(frontend_url,), daemon=True)
    browser_thread.start()

    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.DEBUG
    )