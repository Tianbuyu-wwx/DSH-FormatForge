"""
公共工具函数
结果 ID 生成、处理日志、输出格式化等管线公共能力
"""

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from core.models import (
    ConvertResultData,
    ProcessingLog,
    TaskStatus,
)

logger = logging.getLogger("utils")


def generate_request_id() -> str:
    """生成请求唯一标识"""
    timestamp = datetime.now().strftime("%Y%m%d")
    random_suffix = uuid.uuid4().hex[:8]
    return f"req{timestamp}{random_suffix}"


def generate_result_id() -> str:
    """生成结果ID"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_suffix = uuid.uuid4().hex[:6]
    return f"cvt{timestamp}{random_suffix}"


def generate_parse_id() -> str:
    """生成解析任务ID"""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_suffix = uuid.uuid4().hex[:6]
    return f"parse{timestamp}{random_suffix}"


def save_bytes_to_dir(upload_dir: Path, filename: str | None, content: bytes, max_size: int) -> Path:
    """
    保存字节内容到目录，带大小检查（原 save_upload_file 的本地化版本）

    Args:
        upload_dir: 目标目录
        filename: 原始文件名（可为 None）
        content: 文件字节
        max_size: 最大允许大小（字节）

    Returns:
        保存后的文件路径
    """
    if len(content) > max_size:
        raise ValueError(f"文件大小超过限制，最大支持 {max_size // 1024 // 1024}MB")

    safe_name = Path(filename or "upload.bin").name or "upload.bin"
    file_path = upload_dir / f"{generate_request_id()}_{safe_name}"
    with open(file_path, "wb") as f:
        f.write(content)

    logger.info("保存文件: %s, 大小: %d 字节", file_path.name, len(content))
    return file_path


def create_processing_log(step: str, message: str, level: str = "info") -> ProcessingLog:
    """创建处理日志"""
    return ProcessingLog(timestamp=datetime.now(), level=level, message=message, step=step)


def build_parse_response_data(result_data: ConvertResultData) -> dict[str, Any]:
    """构建解析响应数据"""
    return {
        "parseId": result_data.resultId,
        "fileInfo": {
            "fileName": result_data.fileInfo.fileName,
            "fileSize": result_data.fileInfo.fileSize,
            "pageCount": result_data.fileInfo.pageCount,
            "fileType": result_data.fileInfo.fileType.value,
        },
        "taskStatus": TaskStatus.COMPLETED.value,
    }


def format_output(content: str, output_format: Any, structured_data: dict | None = None) -> str:
    """根据输出格式格式化内容"""
    from core.models import OutputFormat

    if output_format == OutputFormat.JSON:
        if structured_data:
            import json

            return json.dumps(structured_data, ensure_ascii=False, indent=2)
        try:
            import json

            return json.dumps({"content": content}, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, TypeError):
            return content
    elif output_format == OutputFormat.MARKDOWN:
        if not content.startswith("#"):
            return f"# 转换结果\n\n{content}"
        return content
    elif output_format == OutputFormat.HTML:
        html = content.replace("\n\n", "</p><p>").replace("\n", "<br>")
        return f"<div class='converted-content'><p>{html}</p></div>"
    else:
        return content
