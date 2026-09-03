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


def smart_truncate(text: str, max_chars: int, start: int = 0) -> tuple[str, int | None]:
    """结构化截断（EVOLUTION_PLAN E1）。

    v0.14.0/B-P1-7: 优先级 --- 多文件分隔符 > 段落 > 行 > 硬切。
    --- 分隔符（translate.mjs 多文件拼接）保护不被切在文件标题中间。

    v0.14.0/audit: 加入 <!-- ff-file-sep --> 多文件分隔符——比 --- 更稳，
    因为 markdown --- 水平线（含 --- 第 N 页 ---）会与多文件 --- 模式冲突，
    smartTruncate 误识别会让分页把单文件内容切断。

    返回 (chunk, next_offset)；next_offset 为 None 表示已到末尾。
    保证不把表格行/列表项从中间切断（除非单行超长才硬切）。
    """
    if start >= len(text):
        return "", None
    window_end = min(start + max_chars, len(text))
    if window_end == len(text):
        return text[start:], None

    window = text[start:window_end]
    # 多文件分隔符（按优先级查找）；找到就用，不应用 cap/2 阈值
    cut = -1
    sep_len = 0
    file_seps = ("\n\n---\n\n", "<!-- ff-file-sep -->")
    for sep in file_seps:
        idx = window.rfind(sep)
        if idx >= 0 and (cut < 0 or idx > cut):
            cut = idx
            sep_len = len(sep)
    if cut < 0:
        # 没找到多文件分隔符 → 走原有逻辑：段落 > 行 > 硬切
        cut = window.rfind("\n\n")
        sep_len = 2  # "\n\n"
        if cut < max_chars // 2:
            cut = window.rfind("\n")
            sep_len = 1  # "\n"
    if cut <= 0:
        chunk = window
        nxt = start + window_end
    else:
        chunk = window[:cut]
        nxt = start + cut + sep_len
    next_offset: int | None = nxt if nxt < len(text) else None
    return chunk, next_offset


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
