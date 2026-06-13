"""
结构化日志配置模块
提供 JSON 格式日志和请求 Trace ID 跟踪功能
"""
import json
import logging
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """JSON 格式日志格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 添加 trace_id (由 TraceIDMiddleware 注入)
        trace_id = getattr(record, "trace_id", None)
        if trace_id:
            log_entry["trace_id"] = trace_id

        # 添加请求信息
        request_path = getattr(record, "request_path", None)
        if request_path:
            log_entry["request_path"] = request_path
        request_method = getattr(record, "request_method", None)
        if request_method:
            log_entry["request_method"] = request_method
        duration_ms = getattr(record, "duration_ms", None)
        if duration_ms:
            log_entry["duration_ms"] = duration_ms
        status_code = getattr(record, "status_code", None)
        if status_code:
            log_entry["status_code"] = status_code

        # 添加异常信息
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, ensure_ascii=False)


def setup_logging(level: str = "INFO", json_format: bool = True) -> None:
    """配置全局日志

    Args:
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        json_format: 是否使用 JSON 格式输出
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 移除已有 handler，避免重复
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # 控制台输出
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(getattr(logging, level.upper(), logging.INFO))

    if json_format:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s "
            "(%(filename)s:%(lineno)d)"
        )
    console.setFormatter(formatter)

    root_logger.addHandler(console)

    # 调整第三方库日志级别，避免过多噪音
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    # 为关键日志器添加敏感信息过滤
    from core.security import SensitiveDataFilter

    sensitive_filter = SensitiveDataFilter()
    for logger_name in ["main", "api", "converter_engine", "ai_client", "file_parser"]:
        logging.getLogger(logger_name).addFilter(sensitive_filter)
