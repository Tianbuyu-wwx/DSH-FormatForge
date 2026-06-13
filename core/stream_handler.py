"""
SSE 流式处理器
为大文件转换提供 Server-Sent Events 流式响应
"""
import json
import logging
from typing import Any, AsyncGenerator

from core.models import ConversionType, OutputFormat

logger = logging.getLogger("stream_handler")

SSE_STEPS = [
    {"step": "upload", "progress": 10, "message": "正在读取文件..."},
    {"step": "parse", "progress": 30, "message": "正在解析文件内容..."},
    {"step": "ocr", "progress": 50, "message": "正在识别文本和图像..."},
    {"step": "convert", "progress": 75, "message": "正在执行AI转换..."},
    {"step": "format", "progress": 90, "message": "正在格式化输出结果..."},
    {"step": "done", "progress": 100, "message": "转换完成"},
]


def _build_sse_event(event: str, data: dict[str, Any]) -> str:
    """构建标准 SSE 事件字符串"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def streaming_convert(
    file_path: str,
    conversion_type: ConversionType = ConversionType.AUTO,
    output_format: OutputFormat = OutputFormat.JSON,
    custom_prompt: str | None = None,
    use_ai_enhance: bool = True,
    target_ai_endpoint: str | None = None,
    target_ai_key: str | None = None,
    target_ai_provider: str | None = None,
) -> AsyncGenerator[str, None]:
    """
    流式转换生成器，逐步 yield SSE 事件

    Args:
        file_path: 待转换文件的路径
        conversion_type: 转换类型
        output_format: 输出格式
        custom_prompt: 自定义转换指令
        use_ai_enhance: 是否使用 AI 增强
        target_ai_endpoint: 目标 AI 端点
        target_ai_key: 目标 AI 密钥
        target_ai_provider: 目标 AI 提供商

    Yields:
        SSE 格式的事件字符串
    """
    import asyncio

    from core.di import data_converter

    steps = SSE_STEPS

    try:
        for step_info in steps[:-1]:
            step_name = step_info["step"]
            yield _build_sse_event(step_name, {
                "step": step_name,
                "status": "running",
                "progress": step_info["progress"],
                "message": step_info["message"],
            })
            await asyncio.sleep(0.01)

        # 执行实际转换
        result = data_converter.convert_with_ai_target(
            source=file_path,
            target_ai_endpoint=target_ai_endpoint,
            target_ai_key=target_ai_key,
            target_ai_provider=target_ai_provider,
            conversion_type=conversion_type,
            output_format=output_format,
            custom_prompt=custom_prompt,
            use_ai_enhance=use_ai_enhance,
        )

        result_data = result.get("result")
        if not result_data:
            yield _build_sse_event("error", {
                "step": "error",
                "status": "failed",
                "progress": 0,
                "message": "转换失败：未获取到转换结果",
            })
            return

        yield _build_sse_event("done", {
            "step": "done",
            "status": "completed",
            "progress": 100,
            "message": "转换完成",
            "result": {
                "resultId": result_data.resultId,
                "fileName": result_data.fileInfo.fileName,
                "conversionType": result_data.conversionType.value,
                "outputFormat": result_data.outputFormat.value,
                "confidence": result_data.confidence,
                "convertedContent": result_data.convertedContent,
                "structuredData": result_data.structuredData,
            },
        })

    except Exception as e:
        logger.error("流式转换失败: %s", e, exc_info=True)
        yield _build_sse_event("error", {
            "step": "error",
            "status": "failed",
            "progress": 0,
            "message": f"转换失败: {str(e)}",
        })