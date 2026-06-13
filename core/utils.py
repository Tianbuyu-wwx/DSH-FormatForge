"""
公共工具函数
提取文件保存、响应构建等重复代码
"""
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import UploadFile

from core.models import (
    BaseResponse,
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


def create_response(code: int, msg: str, data: dict[str, Any] | None = None) -> BaseResponse:
    """创建统一响应"""
    return BaseResponse(
        code=code,
        msg=msg,
        data=data,
        requestId=generate_request_id()
    )


async def save_upload_file(upload_dir: Path, file: UploadFile, max_size: int) -> Path:
    """
    保存上传文件，带大小检查

    Args:
        upload_dir: 上传目录
        file: 上传文件对象
        max_size: 最大允许大小（字节）

    Returns:
        保存后的文件路径
    """
    content = await file.read()

    if len(content) > max_size:
        raise ValueError(f"文件大小超过限制，最大支持 {max_size // 1024 // 1024}MB")

    file_path = upload_dir / f"{generate_request_id()}_{file.filename}"
    with open(file_path, "wb") as f:
        f.write(content)

    logger.info("保存上传文件: %s, 大小: %d 字节", file.filename, len(content))
    return file_path


def build_convert_response_data(result_data: ConvertResultData, base_url: str = "") -> dict[str, Any]:
    """
    构建转换响应数据（统一所有接口的响应结构）

    Args:
        result_data: 转换结果数据
        base_url: 基础URL（用于构建导出链接）

    Returns:
        Dict: 标准化响应数据
    """
    return {
        "resultId": result_data.resultId,
        "fileName": result_data.fileInfo.fileName,
        "conversionType": result_data.conversionType.value,
        "outputFormat": result_data.outputFormat.value,
        "confidence": result_data.confidence,
        "convertedContent": result_data.convertedContent,
        "structuredData": result_data.structuredData,
        "processingLogs": [
            {"step": log.step, "level": log.level, "message": log.message}
            for log in result_data.processingLogs
        ],
        "exportUrl": f"{base_url}/api/v2/convert/export/{result_data.resultId}?format=txt"
    }


def build_parse_response_data(result_data: ConvertResultData) -> dict[str, Any]:
    """构建解析响应数据"""
    return {
        "parseId": result_data.resultId,
        "fileInfo": {
            "fileName": result_data.fileInfo.fileName,
            "fileSize": result_data.fileInfo.fileSize,
            "pageCount": result_data.fileInfo.pageCount,
            "fileType": result_data.fileInfo.fileType.value
        },
        "taskStatus": TaskStatus.COMPLETED.value
    }


def create_processing_log(step: str, message: str, level: str = "info") -> ProcessingLog:
    """创建处理日志"""
    return ProcessingLog(
        timestamp=datetime.now(),
        level=level,
        message=message,
        step=step
    )


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
