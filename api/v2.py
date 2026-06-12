"""
API v2 路由 - 新架构接口
"""
import logging
from pathlib import Path

from fastapi import APIRouter, File, Form, UploadFile

from core.config import settings
from core.di import batch_converter, data_converter
from core.models import ConversionType, OutputFormat, ResponseCode, ResponseMsg
from core.security import validate_file_extension, validate_url_domain
from core.utils import build_convert_response_data, create_response, save_upload_file

logger = logging.getLogger("api.v2")

router = APIRouter(prefix="/api/v2")


@router.post("/convert")
async def convert_data(
    source: str = Form(..., description="输入源（文件路径/URL/文本内容）"),
    source_type: str = Form(default="auto", description="输入源类型: auto, file, url, raw"),
    target_ai_endpoint: str | None = Form(default=None, description="目标AI端点"),
    target_ai_key: str | None = Form(default=None, description="目标AI密钥"),
    target_ai_provider: str | None = Form(default=None, description="目标AI提供商"),
    conversion_type: ConversionType = Form(default=ConversionType.AUTO),
    output_format: OutputFormat = Form(default=OutputFormat.JSON),
    custom_prompt: str | None = Form(default=None, description="自定义转换指令"),
    use_ai_enhance: bool = Form(default=True)
):
    """
    数据转换接口（新架构）
    """
    try:
        # URL 域名白名单验证
        if settings.URL_DOMAIN_VALIDATION and source_type == "url":
            if not validate_url_domain(source):
                return create_response(
                    code=ResponseCode.PARAM_ERROR,
                    msg="不允许访问的 URL 域名"
                )

        # 根据source_type构建输入源
        if source_type == "raw":
            input_source = source.encode('utf-8') if isinstance(source, str) else source
        elif source_type == "auto":
            if source.startswith(("http://", "https://")):
                if settings.URL_DOMAIN_VALIDATION and not validate_url_domain(source):
                    return create_response(code=ResponseCode.PARAM_ERROR, msg=ResponseMsg.URL_DOMAIN_BLOCKED)
                input_source = source
            elif Path(source).exists():
                input_source = source
            else:
                input_source = source.encode('utf-8')
        else:
            input_source = source

        result = data_converter.convert_with_ai_target(
            source=input_source,
            target_ai_endpoint=target_ai_endpoint,
            target_ai_key=target_ai_key,
            target_ai_provider=target_ai_provider,
            conversion_type=conversion_type,
            output_format=output_format,
            custom_prompt=custom_prompt,
            use_ai_enhance=use_ai_enhance
        )

        result_data = result.get("result")
        if not result_data:
            return create_response(
                code=ResponseCode.SERVER_ERROR,
                msg=ResponseMsg.CONVERT_FAILED
            )

        response_data = build_convert_response_data(result_data)
        response_data["decision"] = result.get("decision")
        response_data["aiCapabilities"] = result.get("ai_capabilities")
        response_data["recommendation"] = result.get("recommendation")

        return create_response(
            code=ResponseCode.SUCCESS,
            msg=ResponseMsg.CONVERT_SUCCESS,
            data=response_data
        )

    except ValueError as e:
        logger.warning("参数验证失败: %s", e)
        return create_response(code=ResponseCode.PARAM_ERROR, msg=str(e))
    except Exception as e:
        import traceback
        logger.error("转换失败: %s\n%s", e, traceback.format_exc())
        return create_response(
            code=ResponseCode.SERVER_ERROR,
            msg=f"转换失败: {str(e)}"
        )


@router.post("/convert/upload")
async def convert_upload(
    file: UploadFile = File(..., description="待转换文件"),
    target_ai_endpoint: str | None = Form(default=None),
    target_ai_key: str | None = Form(default=None),
    target_ai_provider: str | None = Form(default=None),
    conversion_type: ConversionType = Form(default=ConversionType.AUTO),
    output_format: OutputFormat = Form(default=OutputFormat.JSON),
    custom_prompt: str | None = Form(default=None),
    use_ai_enhance: bool = Form(default=True)
):
    """
    上传文件并转换（新架构）
    """
    try:
        # 文件类型白名单验证
        if settings.FILE_TYPE_VALIDATION and file.filename:
            if not validate_file_extension(file.filename):
                return create_response(
                    code=ResponseCode.PARAM_ERROR,
                    msg=f"不支持的文件类型: {Path(file.filename).suffix}"
                )

        file_path = await save_upload_file(settings.UPLOAD_DIR, file, settings.MAX_FILE_SIZE)

        result = data_converter.convert_with_ai_target(
            source=str(file_path),
            target_ai_endpoint=target_ai_endpoint,
            target_ai_key=target_ai_key,
            target_ai_provider=target_ai_provider,
            conversion_type=conversion_type,
            output_format=output_format,
            custom_prompt=custom_prompt,
            use_ai_enhance=use_ai_enhance
        )

        result_data = result.get("result")
        if not result_data:
            return create_response(
                code=ResponseCode.SERVER_ERROR,
                msg=ResponseMsg.CONVERT_FAILED
            )

        response_data = build_convert_response_data(result_data)
        response_data["decision"] = result.get("decision")
        response_data["aiCapabilities"] = result.get("ai_capabilities")
        response_data["recommendation"] = result.get("recommendation")

        return create_response(
            code=ResponseCode.SUCCESS,
            msg=ResponseMsg.CONVERT_SUCCESS,
            data=response_data
        )

    except ValueError as e:
        logger.warning("文件上传验证失败: %s", e)
        return create_response(code=ResponseCode.PARAM_ERROR, msg=str(e))
    except Exception as e:
        import traceback
        logger.error("处理失败: %s\n%s", e, traceback.format_exc())
        return create_response(
            code=ResponseCode.SERVER_ERROR,
            msg=f"处理失败: {str(e)}"
        )


@router.post("/convert/batch")
async def convert_batch(
    files: list[UploadFile] = File(...),
    target_ai_endpoint: str | None = Form(default=None),
    target_ai_key: str | None = Form(default=None),
    conversion_type: ConversionType = Form(default=ConversionType.AUTO),
    output_format: OutputFormat = Form(default=OutputFormat.JSON)
):
    """
    批量转换接口
    """
    try:
        sources = []
        for file in files:
            # 文件类型白名单验证
            if settings.FILE_TYPE_VALIDATION and file.filename:
                if not validate_file_extension(file.filename):
                    return create_response(
                        code=ResponseCode.PARAM_ERROR,
                        msg=f"不支持的文件类型: {Path(file.filename).suffix}"
                    )
            file_path = await save_upload_file(settings.UPLOAD_DIR, file, settings.MAX_FILE_SIZE)
            sources.append(str(file_path))

        results = batch_converter.convert_batch(
            sources=sources,
            target_ai_endpoint=target_ai_endpoint,
            target_ai_key=target_ai_key,
            conversion_type=conversion_type,
            output_format=output_format
        )

        return create_response(
            code=ResponseCode.SUCCESS,
            msg=f"批量转换完成，成功 {len([r for r in results if 'error' not in r])}/{len(files)}",
            data={"results": results}
        )

    except ValueError as e:
        logger.warning("批量转换验证失败: %s", e)
        return create_response(code=ResponseCode.PARAM_ERROR, msg=str(e))
    except Exception as e:
        logger.error("批量转换失败: %s", e)
        return create_response(
            code=ResponseCode.SERVER_ERROR,
            msg=f"批量转换失败: {str(e)}"
        )
