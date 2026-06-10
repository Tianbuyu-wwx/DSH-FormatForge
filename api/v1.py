"""
API v1 路由 - 兼容旧版接口
"""
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import PlainTextResponse

from core.models import (
    ResponseCode, ResponseMsg, ConversionType, OutputFormat,
    ConvertRequest, ConvertResponseData,
    GetResultResponseData, TaskStatus
)
from core.di import data_converter, file_parser
from core.output_formatters import result_exporter
from core.utils import (
    create_response, save_upload_file, build_convert_response_data,
    build_parse_response_data, generate_request_id
)
from core.security import validate_file_extension, validate_path_safety
from core.config import settings

logger = logging.getLogger("api.v1")

router = APIRouter(prefix="/api/v1")


@router.post("/convert/upload")
async def upload_file(
    fileType: str = Form(..., description="文件类型: ppt, pdf, image, doc, txt, csv, xls"),
    file: UploadFile = File(..., description="待转换文件")
):
    """
    文件上传与解析接口（兼容旧版）
    """
    try:
        # 文件类型白名单验证
        if settings.FILE_TYPE_VALIDATION and file.filename:
            if not validate_file_extension(file.filename):
                return create_response(
                    code=ResponseCode.PARAM_ERROR,
                    msg=ResponseMsg.UNSUPPORTED_FILE_TYPE.format(Path(file.filename).suffix)
                )

        file_path = await save_upload_file(settings.UPLOAD_DIR, file, settings.MAX_FILE_SIZE)

        result = data_converter.convert_with_ai_target(
            source=str(file_path),
            conversion_type=ConversionType.AUTO,
            output_format=OutputFormat.JSON
        )

        result_data = result.get("result")
        if not result_data:
            return create_response(
                code=ResponseCode.SERVER_ERROR,
                msg=ResponseMsg.PARSE_FAILED
            )

        return create_response(
            code=ResponseCode.SUCCESS,
            msg=ResponseMsg.FILE_PARSE_SUCCESS,
            data=build_parse_response_data(result_data)
        )

    except ValueError as e:
        logger.warning("文件上传验证失败: %s", e)
        return create_response(code=ResponseCode.PARAM_ERROR, msg=str(e))
    except Exception as e:
        import traceback
        logger.error("文件解析失败: %s\n%s", e, traceback.format_exc())
        return create_response(
            code=ResponseCode.SERVER_ERROR,
            msg=ResponseMsg.PARSE_FAILED_TEMPLATE.format(e)
        )


@router.post("/convert/run")
async def run_conversion(request: ConvertRequest):
    """
    执行数据转换（兼容旧版）
    """
    try:
        # 从解析缓存中查找 ParsedFile
        parsed = file_parser.parsed_cache.get(request.parseId)
        if not parsed:
            return create_response(
                code=ResponseCode.NOT_FOUND,
                msg=ResponseMsg.CONVERT_TASK_NOT_FOUND
            )

        # 执行转换
        result = data_converter.convert(
            parsed,
            conversion_type=request.conversionType,
            output_format=request.outputFormat,
            custom_prompt=request.customPrompt
        )

        if not result:
            return create_response(
                code=ResponseCode.SERVER_ERROR,
                msg=ResponseMsg.CONVERT_FAILED
            )

        response_data = ConvertResponseData(
            resultId=result.resultId,
            fileInfo=result.fileInfo,
            conversionType=result.conversionType,
            outputFormat=result.outputFormat,
            preview=result.convertedContent[:500] + "..." if len(result.convertedContent) > 500 else result.convertedContent,
            confidence=result.confidence,
            resultUrl=f"/api/v1/convert/result/{result.resultId}",
            exportUrl=f"/api/v1/convert/export/{result.resultId}?format=txt"
        )

        return create_response(
            code=ResponseCode.SUCCESS,
            msg=ResponseMsg.CONVERT_SUCCESS,
            data=response_data.model_dump()
        )

    except Exception as e:
        import traceback
        logger.error("转换失败: %s\n%s", e, traceback.format_exc())
        return create_response(
            code=ResponseCode.SERVER_ERROR,
            msg=ResponseMsg.CONVERT_FAILED_TEMPLATE.format(e)
        )


@router.get("/convert/result/{result_id}")
async def get_result(result_id: str):
    """
    获取转换结果
    """
    result = data_converter.get_result(result_id)

    if not result:
        return create_response(
            code=ResponseCode.NOT_FOUND,
            msg=ResponseMsg.RESULT_NOT_FOUND
        )

    response_data = GetResultResponseData(
        resultId=result.resultId,
        fileInfo=result.fileInfo,
        conversionType=result.conversionType,
        outputFormat=result.outputFormat,
        extractedContent=result.extractedContent,
        convertedContent=result.convertedContent,
        structuredData=result.structuredData,
        confidence=result.confidence,
        processingLogs=result.processingLogs
    )

    return create_response(
        code=ResponseCode.SUCCESS,
        msg=ResponseMsg.QUERY_SUCCESS,
        data=response_data.model_dump()
    )


@router.get("/convert/status/{parse_id}")
async def get_parse_status(parse_id: str):
    """
    查询解析任务状态
    同时支持 parsed_cache（手动缓存）和 result_cache（自动转换）两种来源
    """
    # 优先从 FileParser 的解析缓存查找
    parsed = file_parser.parsed_cache.get(parse_id)

    if parsed:
        return create_response(
            code=ResponseCode.SUCCESS,
            msg=ResponseMsg.QUERY_SUCCESS,
            data={
                "parseId": parsed.parseId,
                "fileInfo": {
                    "fileName": parsed.fileName,
                    "fileSize": parsed.fileSize,
                    "pageCount": parsed.pageCount,
                    "fileType": parsed.fileType.value if hasattr(parsed.fileType, 'value') else str(parsed.fileType)
                },
                "taskStatus": parsed.status.value if hasattr(parsed.status, 'value') else TaskStatus.COMPLETED.value
            }
        )

    # 若解析缓存未命中，尝试从转换结果缓存查找（upload 接口返回的 parseId 实为 resultId）
    result = data_converter.result_cache.get(parse_id)
    if result:
        return create_response(
            code=ResponseCode.SUCCESS,
            msg=ResponseMsg.QUERY_SUCCESS,
            data={
                "parseId": result.resultId,
                "fileInfo": {
                    "fileName": result.fileInfo.fileName,
                    "fileSize": result.fileInfo.fileSize,
                    "pageCount": result.fileInfo.pageCount,
                    "fileType": result.fileInfo.fileType.value if hasattr(result.fileInfo.fileType, 'value') else str(result.fileInfo.fileType)
                },
                "taskStatus": TaskStatus.COMPLETED.value
            }
        )

    return create_response(
        code=ResponseCode.NOT_FOUND,
        msg=ResponseMsg.PARSE_TASK_NOT_FOUND
    )


@router.get("/convert/export/{result_id}")
async def export_result(result_id: str, format: str = "txt"):
    """
    导出转换结果
    """
    result = data_converter.get_result(result_id)

    if not result:
        return create_response(
            code=ResponseCode.NOT_FOUND,
            msg=ResponseMsg.RESULT_NOT_FOUND
        )

    format_map = {
        "json": (result_exporter.to_json, "application/json"),
        "md": (result_exporter.to_markdown, "text/markdown"),
        "html": (result_exporter.to_html, "text/html"),
    }

    exporter, media_type = format_map.get(format, (result_exporter.to_text, "text/plain"))
    ext = format if format in ("json", "md", "html") else "txt"
    content = exporter(result)
    filename = f"{result.fileInfo.fileName}_converted.{ext}"

    return PlainTextResponse(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.post("/convert/auto")
async def auto_convert(
    fileType: str = Form(default="auto", description="文件类型，auto为自动检测"),
    conversionType: ConversionType = Form(default=ConversionType.AUTO),
    outputFormat: OutputFormat = Form(default=OutputFormat.JSON),
    customPrompt: Optional[str] = Form(default=None),
    file: UploadFile = File(...)
):
    """
    简化版接口：上传文件直接转换（兼容旧版）
    """
    try:
        # 文件类型白名单验证
        if settings.FILE_TYPE_VALIDATION and file.filename:
            if not validate_file_extension(file.filename):
                return create_response(
                    code=ResponseCode.PARAM_ERROR,
                    msg=ResponseMsg.UNSUPPORTED_FILE_TYPE.format(Path(file.filename).suffix)
                )

        file_path = await save_upload_file(settings.UPLOAD_DIR, file, settings.MAX_FILE_SIZE)

        result = data_converter.convert_with_ai_target(
            source=str(file_path),
            conversion_type=conversionType,
            output_format=outputFormat,
            custom_prompt=customPrompt
        )

        result_data = result.get("result")
        if not result_data:
            return create_response(
                code=ResponseCode.SERVER_ERROR,
                msg=ResponseMsg.CONVERT_FAILED
            )

        return create_response(
            code=ResponseCode.SUCCESS,
            msg=ResponseMsg.CONVERT_SUCCESS,
            data=build_convert_response_data(result_data)
        )

    except ValueError as e:
        logger.warning("文件上传验证失败: %s", e)
        return create_response(code=ResponseCode.PARAM_ERROR, msg=str(e))
    except Exception as e:
        import traceback
        logger.error("处理失败: %s\n%s", e, traceback.format_exc())
        return create_response(
            code=ResponseCode.SERVER_ERROR,
            msg=ResponseMsg.PROCESS_FAILED_TEMPLATE.format(e)
        )


# ==================== AI 能力发现接口 ====================


@router.post("/ai/discover")
async def discover_ai_capabilities(
    endpoint: str = Form(..., description="AI API 端点"),
    api_key: str = Form(..., description="API 密钥"),
    provider: Optional[str] = Form(default=None, description="AI 提供商")
):
    """
    发现目标AI的能力

    探测AI端点支持的输入类型、token限制等能力
    """
    try:
        caps = data_converter.discover_ai_capabilities(endpoint, api_key, provider)
        return create_response(
            code=ResponseCode.SUCCESS,
            msg=ResponseMsg.AI_DISCOVER_SUCCESS,
            data=caps.to_dict()
        )
    except Exception as e:
        logger.error("AI能力发现失败: %s", e)
        return create_response(
            code=ResponseCode.SERVER_ERROR,
            msg=ResponseMsg.AI_DISCOVER_FAILED_TEMPLATE.format(e)
        )


@router.get("/ai/providers")
async def list_ai_providers():
    """列出支持的AI提供商"""
    providers = data_converter.ai_discovery.list_supported_providers()
    return create_response(
        code=ResponseCode.SUCCESS,
        msg=ResponseMsg.QUERY_SUCCESS,
        data={"providers": providers}
    )