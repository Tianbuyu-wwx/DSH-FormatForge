"""API v2 路由 - 新架构接口"""
import io
import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

from core.config import settings
from core.di import batch_converter, data_converter, file_parser
from core.history_store import get_history_store
from core.models import ConversionType, OutputFormat, ResponseCode, ResponseMsg
from core.output_templates import apply_template, get_template_list
from core.quality_report import QualityReport
from core.metrics import get_metrics_collector
from core.security import validate_file_extension, validate_url_domain
from core.stream_handler import streaming_convert
from core.webhook_manager import get_webhook_manager
from core.utils import build_convert_response_data, create_response, generate_request_id, save_upload_file
from __version__ import __version__, __version_name__
from core.auth import verify_api_key

logger = logging.getLogger("api.v2")

router = APIRouter(prefix="/api/v2")


@router.post("/convert", dependencies=[Depends(verify_api_key)])
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


@router.post("/convert/upload", dependencies=[Depends(verify_api_key)])
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

        # v2.3: 自动保存到历史记录
        try:
            get_history_store().save(response_data)
        except Exception as e:
            logger.warning("保存历史记录失败: %s", e)

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


@router.post("/convert/url", dependencies=[Depends(verify_api_key)])
async def convert_url(
    url: str = Form(..., description="目标 URL"),
    target_ai_endpoint: str | None = Form(default=None),
    target_ai_key: str | None = Form(default=None),
    conversion_type: ConversionType = Form(default=ConversionType.AUTO),
    output_format: OutputFormat = Form(default=OutputFormat.JSON),
    custom_prompt: str | None = Form(default=None),
):
    """
    通过 URL 获取内容并转换（v2.3）
    """
    try:
        if settings.URL_DOMAIN_VALIDATION and not validate_url_domain(url):
            return create_response(code=ResponseCode.PARAM_ERROR, msg=ResponseMsg.URL_DOMAIN_BLOCKED)

        result = data_converter.convert_with_ai_target(
            source=url,
            target_ai_endpoint=target_ai_endpoint,
            target_ai_key=target_ai_key,
            conversion_type=conversion_type,
            output_format=output_format,
            custom_prompt=custom_prompt,
        )

        result_data = result.get("result")
        if not result_data:
            return create_response(code=ResponseCode.SERVER_ERROR, msg=ResponseMsg.CONVERT_FAILED)

        response_data = build_convert_response_data(result_data)
        response_data["decision"] = result.get("decision")
        return create_response(code=ResponseCode.SUCCESS, msg=ResponseMsg.CONVERT_SUCCESS, data=response_data)

    except Exception as e:
        logger.error("URL 转换失败: %s", e)
        return create_response(code=ResponseCode.SERVER_ERROR, msg=f"URL 转换失败: {str(e)}")


@router.post("/convert/text", dependencies=[Depends(verify_api_key)])
async def convert_text(
    text: str = Form(..., description="待转换的文本内容"),
    file_name: str = Form(default="raw_text.txt", description="虚拟文件名，用于格式检测"),
    target_ai_endpoint: str | None = Form(default=None),
    target_ai_key: str | None = Form(default=None),
    conversion_type: ConversionType = Form(default=ConversionType.AUTO),
    output_format: OutputFormat = Form(default=OutputFormat.JSON),
    custom_prompt: str | None = Form(default=None),
):
    """
    直接转换文本内容（v2.3）
    """
    try:
        import tempfile

        # 保存文本为临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8') as tmp:
            tmp.write(text)
            tmp_path = Path(tmp.name)

        try:
            result = data_converter.convert_with_ai_target(
                source=str(tmp_path),
                target_ai_endpoint=target_ai_endpoint,
                target_ai_key=target_ai_key,
                conversion_type=conversion_type,
                output_format=output_format,
                custom_prompt=custom_prompt,
            )
        finally:
            tmp_path.unlink(missing_ok=True)

        result_data = result.get("result")
        if not result_data:
            return create_response(code=ResponseCode.SERVER_ERROR, msg=ResponseMsg.CONVERT_FAILED)

        response_data = build_convert_response_data(result_data)
        response_data["decision"] = result.get("decision")
        return create_response(code=ResponseCode.SUCCESS, msg=ResponseMsg.CONVERT_SUCCESS, data=response_data)

    except Exception as e:
        logger.error("文本转换失败: %s", e)
        return create_response(code=ResponseCode.SERVER_ERROR, msg=f"文本转换失败: {str(e)}")


# ==================== 历史记录 API ====================

@router.get("/history")
async def get_history(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    file_type: str | None = Query(default=None),
):
    """获取转换历史记录列表"""
    try:
        store = get_history_store()
        records = store.list(limit=limit, offset=offset, file_type=file_type)
        total = store.count(file_type=file_type)
        return create_response(
            code=ResponseCode.SUCCESS,
            msg="查询成功",
            data={"items": records, "total": total, "limit": limit, "offset": offset}
        )
    except Exception as e:
        logger.error("获取历史记录失败: %s", e)
        return create_response(code=ResponseCode.SERVER_ERROR, msg=f"获取历史记录失败: {str(e)}")


@router.get("/history/{result_id}")
async def get_history_detail(result_id: str):
    """获取单条历史记录详情"""
    try:
        store = get_history_store()
        record = store.get(result_id)
        if not record:
            return create_response(code=ResponseCode.NOT_FOUND, msg="历史记录不存在")
        return create_response(code=ResponseCode.SUCCESS, msg="查询成功", data=record)
    except Exception as e:
        logger.error("获取历史记录详情失败: %s", e)
        return create_response(code=ResponseCode.SERVER_ERROR, msg=f"获取失败: {str(e)}")


@router.delete("/history/{result_id}", dependencies=[Depends(verify_api_key)])
async def delete_history(result_id: str):
    """删除单条历史记录"""
    try:
        store = get_history_store()
        deleted = store.delete(result_id)
        if not deleted:
            return create_response(code=ResponseCode.NOT_FOUND, msg="历史记录不存在")
        return create_response(code=ResponseCode.SUCCESS, msg="删除成功")
    except Exception as e:
        logger.error("删除历史记录失败: %s", e)
        return create_response(code=ResponseCode.SERVER_ERROR, msg=f"删除失败: {str(e)}")


@router.delete("/history", dependencies=[Depends(verify_api_key)])
async def clear_history():
    """清空所有历史记录"""
    try:
        store = get_history_store()
        count = store.clear()
        return create_response(code=ResponseCode.SUCCESS, msg=f"已清空 {count} 条历史记录")
    except Exception as e:
        logger.error("清空历史记录失败: %s", e)
        return create_response(code=ResponseCode.SERVER_ERROR, msg=f"清空失败: {str(e)}")


@router.get("/history/stats")
async def get_history_stats():
    """获取历史统计信息"""
    try:
        store = get_history_store()
        stats = store.stats()
        return create_response(code=ResponseCode.SUCCESS, msg="查询成功", data=stats)
    except Exception as e:
        logger.error("获取统计信息失败: %s", e)
        return create_response(code=ResponseCode.SERVER_ERROR, msg=f"获取失败: {str(e)}")


# ==================== 导出 API ====================

@router.get("/export/{result_id}")
async def export_result(result_id: str, format: str = Query(default="markdown")):
    """
    导出转换结果（v2.3）
    支持格式: json, markdown, text, html, csv, xml
    """
    try:
        store = get_history_store()
        record = store.get(result_id)
        if not record:
            return create_response(code=ResponseCode.NOT_FOUND, msg="转换结果不存在或已过期")

        content = record.get("converted_content", "") or record.get("convertedContent", "")
        file_name = record.get("file_name", "export").rsplit(".", 1)[0]

        format = format.lower()
        content_type_map = {
            "json": "application/json",
            "markdown": "text/markdown",
            "text": "text/plain",
            "html": "text/html",
            "csv": "text/csv",
            "xml": "application/xml",
        }
        ext_map = {
            "json": ".json",
            "markdown": ".md",
            "text": ".txt",
            "html": ".html",
            "csv": ".csv",
            "xml": ".xml",
        }

        content_type = content_type_map.get(format, "text/plain")
        ext = ext_map.get(format, ".txt")

        if format == "csv" and record.get("structured_data"):
            # 尝试从结构化数据中提取表格
            try:
                sd = record.get("structured_data", {})
                if isinstance(sd, str):
                    sd = json.loads(sd)
                tables = sd.get("tables", [])
                if tables:
                    csv_rows = []
                    # 用第一个表格的数据
                    first_table = tables[0] if isinstance(tables[0], dict) else {}
                    data = first_table.get("data", [])
                    if data:
                        csv_rows = [",".join(str(c).replace(",", "\\,") for c in row) for row in data]
                        content = "\n".join(csv_rows)
            except Exception:
                pass

        return StreamingResponse(
            io.BytesIO(content.encode("utf-8")),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{file_name}{ext}"'}
        )
    except Exception as e:
        logger.error("导出失败: %s", e)
        return create_response(code=ResponseCode.SERVER_ERROR, msg=f"导出失败: {str(e)}")


# ==================== SSE 流式转换 API ====================

@router.post("/convert/stream", dependencies=[Depends(verify_api_key)])
async def convert_stream(
    file: UploadFile = File(...),
    conversion_type: ConversionType = Form(default=ConversionType.AUTO),
    output_format: OutputFormat = Form(default=OutputFormat.JSON),
    custom_prompt: str | None = Form(default=None),
):
    """
    流式转换接口 - 通过 SSE 实时推送转换进度
    """
    if settings.FILE_TYPE_VALIDATION and file.filename:
        if not validate_file_extension(file.filename):
            return create_response(
                code=ResponseCode.PARAM_ERROR,
                msg=f"不支持的文件类型: {Path(file.filename).suffix}"
            )

    file_path = await save_upload_file(settings.UPLOAD_DIR, file, settings.MAX_FILE_SIZE)

    return StreamingResponse(
        streaming_convert(
            file_path=str(file_path),
            conversion_type=conversion_type,
            output_format=output_format,
            custom_prompt=custom_prompt,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== 输出模板 API ====================

@router.get("/templates")
async def list_templates():
    """获取可用的输出模板列表"""
    try:
        templates = get_template_list()
        return create_response(
            code=ResponseCode.SUCCESS,
            msg="查询成功",
            data={"templates": templates},
        )
    except Exception as e:
        logger.error("获取模板列表失败: %s", e)
        return create_response(code=ResponseCode.SERVER_ERROR, msg=f"获取模板列表失败: {str(e)}")


@router.post("/convert/template", dependencies=[Depends(verify_api_key)])
async def convert_with_template(
    file: UploadFile = File(...),
    template_name: str = Form(...),
    conversion_type: ConversionType = Form(default=ConversionType.AUTO),
    output_format: OutputFormat = Form(default=OutputFormat.JSON),
    custom_prompt: str | None = Form(default=None),
):
    """
    使用输出模板进行转换
    """
    try:
        if settings.FILE_TYPE_VALIDATION and file.filename:
            if not validate_file_extension(file.filename):
                return create_response(
                    code=ResponseCode.PARAM_ERROR,
                    msg=f"不支持的文件类型: {Path(file.filename).suffix}"
                )

        file_path = await save_upload_file(settings.UPLOAD_DIR, file, settings.MAX_FILE_SIZE)

        result = data_converter.convert_with_ai_target(
            source=str(file_path),
            conversion_type=conversion_type,
            output_format=output_format,
            custom_prompt=custom_prompt,
        )

        result_data = result.get("result")
        if not result_data:
            return create_response(
                code=ResponseCode.SERVER_ERROR,
                msg=ResponseMsg.CONVERT_FAILED
            )

        content = result_data.convertedContent or ""
        structured_data = result_data.structuredData
        file_name = result_data.fileInfo.fileName

        transformed = apply_template(template_name, content, structured_data, file_name)

        return create_response(
            code=ResponseCode.SUCCESS,
            msg="转换成功",
            data={
                "template_name": template_name,
                "result": transformed,
            },
        )

    except ValueError as e:
        logger.warning("模板转换参数错误: %s", e)
        return create_response(code=ResponseCode.PARAM_ERROR, msg=str(e))
    except Exception as e:
        import traceback
        logger.error("模板转换失败: %s\n%s", e, traceback.format_exc())
        return create_response(code=ResponseCode.SERVER_ERROR, msg=f"模板转换失败: {str(e)}")


# ==================== 质量报告 API ====================

@router.get("/quality/{result_id}")
async def get_quality_report(result_id: str):
    """获取历史记录的质量报告"""
    try:
        store = get_history_store()
        record = store.get(result_id)
        if not record:
            return create_response(code=ResponseCode.NOT_FOUND, msg="历史记录不存在")

        report = QualityReport.from_history_record(record)
        return create_response(
            code=ResponseCode.SUCCESS,
            msg="质量报告生成成功",
            data=report.to_dict(),
        )
    except Exception as e:
        logger.error("生成质量报告失败: %s", e)
        return create_response(code=ResponseCode.SERVER_ERROR, msg=f"生成质量报告失败: {str(e)}")


@router.post("/quality/analyze", dependencies=[Depends(verify_api_key)])
async def analyze_quality(file: UploadFile = File(...)):
    """分析上传文件的质量并返回质量报告"""
    try:
        if settings.FILE_TYPE_VALIDATION and file.filename:
            if not validate_file_extension(file.filename):
                return create_response(
                    code=ResponseCode.PARAM_ERROR,
                    msg=f"不支持的文件类型: {Path(file.filename).suffix}"
                )

        file_path = await save_upload_file(settings.UPLOAD_DIR, file, settings.MAX_FILE_SIZE)

        # 确定文件类型
        ext = file_path.suffix.lower()
        ext_type_map = {
            '.pdf': 'pdf', '.doc': 'doc', '.docx': 'doc',
            '.ppt': 'ppt', '.pptx': 'ppt',
            '.xls': 'xls', '.xlsx': 'xls',
            '.txt': 'txt', '.csv': 'csv', '.tsv': 'csv',
            '.jpg': 'image', '.jpeg': 'image', '.png': 'image',
            '.gif': 'image', '.bmp': 'image', '.webp': 'image',
            '.md': 'txt', '.json': 'txt', '.xml': 'txt',
            '.html': 'txt', '.htm': 'txt',
        }
        file_type = ext_type_map.get(ext, 'unknown')

        # 解析文件
        parsed = file_parser.parse_file(file_path, file_type)
        report = QualityReport.from_parsed_file(parsed)

        return create_response(
            code=ResponseCode.SUCCESS,
            msg="质量分析完成",
            data=report.to_dict(),
        )
    except ValueError as e:
        logger.warning("质量分析参数错误: %s", e)
        return create_response(code=ResponseCode.PARAM_ERROR, msg=str(e))
    except Exception as e:
        import traceback
        logger.error("质量分析失败: %s\n%s", e, traceback.format_exc())
        return create_response(code=ResponseCode.SERVER_ERROR, msg=f"质量分析失败: {str(e)}")


# ==================== 监控与健康检查 API ====================

@router.get("/metrics", response_class=PlainTextResponse)
async def get_metrics():
    """返回 Prometheus 格式的指标数据"""
    collector = get_metrics_collector()
    return collector.export_prometheus()


@router.get("/health")
async def health_v2():
    """健康检查 (v2)"""
    import time as _time
    return {
        "status": "ok",
        "version": __version__,
        "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


# ==================== Webhook 回调 API ====================

from pydantic import BaseModel


class WebhookRegisterRequest(BaseModel):
    """Webhook 注册请求"""
    task_id: str
    callback_url: str
    secret: str = ""


@router.post("/webhook/register", dependencies=[Depends(verify_api_key)])
async def register_webhook(req: WebhookRegisterRequest):
    """注册 Webhook 回调

    转换完成后，系统将 POST 结果到 callback_url。
    请求头包含 X-Webhook-Signature (HMAC-SHA256) 用于验签。
    """
    manager = get_webhook_manager()
    try:
        result = manager.register(req.task_id, req.callback_url, req.secret)
        return create_response(200, "Webhook 注册成功", result)
    except ValueError as e:
        return create_response(400, str(e))


@router.get("/webhook/status/{task_id}")
async def get_webhook_status(task_id: str):
    """查询 Webhook 投递状态"""
    manager = get_webhook_manager()
    status = manager.get_status(task_id)
    if status is None:
        return create_response(404, "Webhook 未找到")
    return create_response(200, "查询成功", status)


@router.delete("/webhook/{task_id}", dependencies=[Depends(verify_api_key)])
async def cancel_webhook(task_id: str):
    """取消 Webhook"""
    manager = get_webhook_manager()
    cancelled = manager.cancel(task_id)
    if cancelled:
        return create_response(200, "Webhook 已取消")
    return create_response(404, "Webhook 未找到或已投递")


@router.get("/webhook/stats")
async def get_webhook_stats():
    """Webhook 统计信息"""
    manager = get_webhook_manager()
    return create_response(200, "查询成功", manager.stats())
