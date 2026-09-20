"""
FormatForge CLI 入口

协议契约（JS 侧 python-runner 依赖此形状，勿随意改动）：
    成功: {"ok": true,  "code": 200, "data": {content, format, meta, quality?, enhance?}}
    失败: {"ok": false, "code": <4000+exit>, "error": {"kind": str, "message": str}}
退出码（权威定义见 core/errors.py::EXIT_CODES）:
    0 成功 / 2 文件不存在·是目录·无权限 / 3 格式不支持 / 4 解析失败 /
    5 超时 / 6 超出大小上限 / 7 参数错误 / 70 内部错误
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import time
from pathlib import Path, PureWindowsPath
from typing import Any, cast

logger = logging.getLogger(__name__)

# 确保仓库根目录在 sys.path（以 `python -m formatforge` 从任意 cwd 运行时）
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

EXIT_OK = 0

# M4: 错误码协议固化（core/errors.py 为唯一权威；旧 kind 字符串映射到新枚举）
from core.errors import ErrorCode, exit_code_of  # noqa: E402

#: 旧 kind 字符串 → ErrorCode（表内只有「不是 ErrorCode 值」的历史别名；
#: 其余 kind 由 _kind_to_code 直接按枚举值解析）
_LEGACY_KIND = {
    "not_found": ErrorCode.FILE_NOT_FOUND,
    # FF-M-kinds/audit: 以下别名此前缺失，而上游（管道 error payload、batch）
    # 会按新值语义传 kind（file_not_found / bad_request / permission_denied /
    # timeout）——它们查不到就被 remap 成 INTERNAL(70)，JS 侧据此判错类型。
    "file_not_found": ErrorCode.FILE_NOT_FOUND,
    "permission_denied": ErrorCode.PERMISSION_DENIED,
    "bad_request": ErrorCode.BAD_REQUEST,
    "timeout": ErrorCode.TIMEOUT,
}


def _kind_to_code(kind: str) -> ErrorCode:
    """kind 字符串 → ErrorCode。

    先按枚举值精确匹配（新值语义，含 file_not_found/bad_request 等），失败再退
    到历史别名表，最后兜底 INTERNAL。未知 kind 不再静默变 70 却不留痕迹。
    """
    try:
        return ErrorCode(kind)
    except ValueError:
        return _LEGACY_KIND.get(kind, ErrorCode.INTERNAL)


from formatforge.batch import cmd_batch  # noqa: E402  (须在 sys.path 注入之后)
from formatforge.diff import register as register_diff  # noqa: E402  (v0.12.0/B10)
from formatforge.protocol import emit, pin_std_streams_utf8  # noqa: E402


def _emit(payload: dict[str, Any]) -> None:
    """stdout 唯一出口：单行协议 JSON（编码由 protocol.pin_std_streams_utf8 保证）"""
    emit(payload)


# FF-L-main/audit: 协议 JSON 会把完整本地路径（含用户名目录）和原始异常文本
# （可能夹带内部堆栈/路径片段）回传给调用方 —— 信息泄露。对外 message 一律先过
# 这道收敛：绝对路径收敛为 basename，超长文本截断。错误 kind/exit_code 不变，
# 调用方仍可按类型分支；只有「人读的路径/堆栈细节」被收敛。
_MAX_MESSAGE_CHARS = 400


def _safe_message(message: Any, *, _path_token: Path | None = None) -> str:
    """收敛对外错误消息：绝对路径→basename，长度截断。

    _path_token：调用方已知的源文件路径，其 str() 在消息里替换成 basename；
    其余出现的路径形态（盘符:/ 或 / 开头的长 token）同样按 basename 收敛。
    """
    text = str(message)
    if _path_token is not None:
        try:
            text = text.replace(str(_path_token), Path(_path_token).name)
        except Exception:
            pass
    # 收敛 Windows 盘符路径（两种分隔符）、UNC 路径和 POSIX 绝对路径。
    import re

    windows_basename = lambda m: PureWindowsPath(m.group(0)).name  # noqa: E731
    text = re.sub(r"\\\\[^\\/\s\"':;]+[\\/][^\s\"':;]+", windows_basename, text)
    text = re.sub(r"[A-Za-z]:[\\/][^\s\"':;]+", windows_basename, text)
    text = re.sub(r"(?<![\w:])/(?:[^\s\"':;/]+/)+([^\s\"':;/]+)", r"\1", text)
    if len(text) > _MAX_MESSAGE_CHARS:
        text = text[:_MAX_MESSAGE_CHARS] + "…(truncated)"
    return text


def _fail(kind: str, message: str, *, code: ErrorCode | None = None) -> int:
    """失败出口。kind 为旧字符串兼容参数；优先用 code 枚举。"""
    ec = code or _kind_to_code(kind)
    exit_code = exit_code_of(ec)
    # FF-L-main/audit: 所有协议错误消息统一收敛（绝对路径→basename、超长截断）
    err = {"kind": ec.value, "message": _safe_message(message)}
    _emit({"ok": False, "code": 4000 + exit_code, "error": err})
    return exit_code


def translate_file_data(
    source: Path | str,
    fmt: str = "json",
    conversion_type: str = "auto",
    quality: bool = False,
    pages: str | None = None,
    prompt: str | None = None,
    encoding: str | None = None,
) -> tuple[dict[str, Any] | dict[str, str], int]:
    """单文件转换核心（N3 batch 复用）。

    source 可为 Path（文件）或 str（stdin 原始文本）。
    返回 (data, exit_code)：
      成功 → data 为协议 data 字段 dict（content/meta/quality?/enhance?），exit_code=0
      失败 → data 为 {"kind","message"}，exit_code 非 0
    """
    from core.config import settings
    from core.models import ConversionType, OutputFormat
    from core.pipeline import ConversionPipeline, PipelineContext

    if isinstance(source, str):
        pass  # stdin 文本直接走 RawDataAdapter
    else:
        if not source.exists():
            return {"kind": "file_not_found", "message": f"文件不存在: {source}"}, 2
        if not source.is_file():
            return {"kind": "is_directory", "message": f"路径不是文件: {source}"}, 2
        size = source.stat().st_size
        if size > settings.FF_MAX_BYTES:
            return {"kind": "too_large", "message": f"文件 {size} 字节超过上限 {settings.FF_MAX_BYTES}"}, 6

    type_map = {
        "auto": ConversionType.AUTO,
        "text": ConversionType.TEXT,
        "structured": ConversionType.STRUCTURED,
        "table": ConversionType.TABLE,
        "image_desc": ConversionType.IMAGE_DESC,
        "ocr": ConversionType.OCR,
    }
    fmt_map = {
        "json": OutputFormat.JSON,
        "markdown": OutputFormat.MARKDOWN,
        "html": OutputFormat.HTML,
        "text": OutputFormat.TEXT,
    }
    pipeline = ConversionPipeline(enable_content_cache=False)
    ctx = PipelineContext(
        source=source,
        conversion_type=type_map[conversion_type],
        output_format=fmt_map[fmt],
        pages=pages,
        custom_prompt=prompt,
        encoding=encoding,
    )
    response = pipeline.run(ctx)
    result = response.get("result")
    if result is None:
        err = ctx.error or "未知错误"
        if "pages 参数格式错误" in str(err):
            return {"kind": "bad_request", "message": str(err)}, 7
        if "不支持的文件类型" in str(err):
            # H18/audit: 无解析器的格式（.doc/.ppt/.xlsb 等）报 unsupported_format
            return {"kind": "unsupported_format", "message": str(err)}, 3
        return {"kind": "parse_failed", "message": str(err)}, 4
    sd = getattr(result, "structuredData", None)
    # H1: pipeline 失败也会返回真实 ConvertResultData（_build_error_response 把错误文本
    # 放进 convertedContent、structuredData={"error": True}）——入口必须显式识别，
    # 不能把错误文本当转换产物返回 ok:true。
    if isinstance(sd, dict) and sd.get("error"):
        if "pages 参数格式错误" in str(result.convertedContent):
            return {"kind": "bad_request", "message": result.convertedContent}, 7
        if "不支持的文件类型" in str(result.convertedContent):
            # H18/audit: 无解析器的格式报 unsupported_format（友好收缩后错误）
            return {"kind": "unsupported_format", "message": result.convertedContent}, 3
        return {"kind": "parse_failed", "message": result.convertedContent}, 4

    data: dict[str, Any] = {
        "content": result.convertedContent,
        "format": fmt,
        "meta": {
            "parser": result.fileInfo.fileType.value if result.fileInfo else "unknown",
            "file_size": result.fileInfo.fileSize if result.fileInfo else 0,
            "result_id": result.resultId,
            "confidence": result.confidence,
        },
    }
    assert isinstance(data["meta"], dict)
    # R2.3: 结构保真标记透传（markdown 层级渲染发生时为 True）
    sd = getattr(result, "structuredData", None)
    if isinstance(sd, dict) and sd.get("structured"):
        data["meta"]["structured"] = True
    # B1/v0.11.0: structured_data 透传（让 schema/preview_rows 暴露给会话模型）
    if isinstance(sd, dict) and sd:
        data["structured_data"] = sd
    if quality:
        try:
            from core.quality_report import QualityReport

            report = QualityReport()
            analyzed = report.analyze(
                content=result.convertedContent,
                file_size=result.fileInfo.fileSize if result.fileInfo else 0,
                file_type=result.fileInfo.fileType.value if result.fileInfo else "unknown",
                structured_data=result.structuredData,
                parsed_file=ctx.parsed_file,
            )
            data["quality"] = analyzed.to_dict() if hasattr(analyzed, "to_dict") else analyzed
        except Exception as e:
            print(f"[formatforge] 质量报告生成失败: {e}", file=sys.stderr)
    if not getattr(_current_args(), "no_enhance_hint", False) and getattr(result, "enhance", None):
        data["enhance"] = result.enhance
    return data, 0


_CURRENT_ARGS: argparse.Namespace | None = None


def _current_args() -> argparse.Namespace:
    return _CURRENT_ARGS or argparse.Namespace(no_enhance_hint=False)


def cmd_translate(args: argparse.Namespace) -> int:
    global _CURRENT_ARGS
    _CURRENT_ARGS = args
    from core.config import settings

    source: Any

    if args.stdin_text:
        # T3-7/audit: stdin 也是公开输入面，与文件路径共用同一字节上限。
        # 只多读一个字符，先防止无界 read；再按 CLI 协议的 UTF-8
        # 字节口径校验，所以多字节文本也不会绕过 FF_MAX_BYTES。
        source = sys.stdin.read(settings.FF_MAX_BYTES + 1)
        stdin_size = len(source.encode("utf-8"))
        if stdin_size > settings.FF_MAX_BYTES:
            return _fail(
                "bad_request",
                f"stdin {stdin_size} 字节超过上限 {settings.FF_MAX_BYTES}",
            )
    else:
        path = Path(args.path) if args.path else None
        if not path:
            return _fail("internal", "必须提供 <path> 或 --stdin-text")
        if not path.exists():
            return _fail("not_found", f"文件不存在: {path}")
        if not path.is_file():
            return _fail("is_directory", f"路径不是文件: {path}")
        size = path.stat().st_size
        if size > settings.FF_MAX_BYTES:
            return _fail("too_large", f"文件 {size} 字节超过上限 {settings.FF_MAX_BYTES}")
        source = path

    started = time.time()
    # R3.1 智能默认：auto 模式自动附带 quality（与 JS ff_translate 行为一致）
    want_quality = args.quality or args.type in ("auto", None)
    data, exit_code = translate_file_data(
        source=source,
        fmt=args.format,
        conversion_type=args.type,
        quality=want_quality,
        pages=getattr(args, "pages", None),
        prompt=args.prompt,
        encoding=getattr(args, "encoding", None),
    )
    elapsed_ms = int((time.time() - started) * 1000)
    if exit_code != 0 or not isinstance(data, dict):
        return _fail(str(data.get("kind", "internal")), str(data.get("message", data)))
    # mypy: cast 让后续索引/赋值用 dict[str, Any]
    data = cast(dict[str, Any], data)
    meta = cast(dict[str, Any], data.get("meta")) if isinstance(data.get("meta"), dict) else cast(dict[str, Any], {})

    if meta:
        meta["elapsed_ms"] = elapsed_ms
        # R3.1 契约字段：标记 quality 是否自动开启（与会话模型对齐）
        meta["quality_auto"] = want_quality and not args.quality
        # B9/v0.10.0: 目标语 metadata（让 enhance 阶段按目标语翻译输出）
        target_lang = getattr(args, "language", None)
        if target_lang:
            lang_code = str(target_lang).lower()
            meta["target_language"] = lang_code
            enhance_obj = data.get("enhance")
            if not isinstance(enhance_obj, dict) or not enhance_obj.get("needed"):
                new_hint = (
                    "用户期望目标语言：" + lang_code + "（ISO 639-1）。"
                    "如需翻译输出请按此语种整理；FormatForge 不内置翻译。"
                )
                if isinstance(enhance_obj, dict):
                    data["enhance"] = {**enhance_obj, "needed": False, "hint": new_hint}  # type: ignore[assignment]
                else:
                    data["enhance"] = {"needed": False, "hint": new_hint}  # type: ignore[assignment]
    # A9/v0.10.0: --output-file 把 content 落盘（stdout 协议 JSON 不变）
    # FF-M-protocol/audit: 写入失败不再「logger.warning + ok:true」；目标路径
    # 收敛到用户显式声明的 FF_OUTPUT_ROOT；代码/导入路径始终受保护，越界报 bad_request。
    output_file = getattr(args, "output_file", None)
    if output_file:
        # T1-8/audit: 文件写入走 resolve_output_file —— 包含性 + 输出扩展名白名单。
        from formatforge.output_guard import OutputPathError, resolve_output_file

        try:
            out_path = resolve_output_file(output_file, source=source if isinstance(source, Path) else None)
        except OutputPathError as e:
            return _fail("bad_request", str(e), code=ErrorCode.BAD_REQUEST)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            content_val = data.get("content")
            content_str = (
                content_val if isinstance(content_val, str) else json.dumps(content_val, ensure_ascii=False, indent=2)
            )
            out_path.write_text(content_str, encoding="utf-8")
            meta["output_file"] = str(out_path)
        except OSError as e:
            return _fail(
                "permission_denied",
                f"--output-file 写入失败: {out_path}: {e}",
                code=ErrorCode.PERMISSION_DENIED,
            )
    _emit({"ok": True, "code": 200, "data": data})
    return EXIT_OK


def cmd_formats(args: argparse.Namespace) -> int:
    from core.format_detector import DataFormat

    values = sorted({m.value for m in DataFormat})

    # A10/v0.10.0: 分类标签（按需过滤；不动 DataFormat 本身）
    category_map = {
        # document：排版/文档类
        "pdf": "document",
        "docx": "document",
        "pptx": "document",
        "txt": "document",
        "rtf": "document",
        "odt": "document",
        "odp": "document",
        "epub": "document",
        "srt": "document",
        "latex": "document",
        # data：结构化数据
        "csv": "data",
        "xlsx": "data",
        "ods": "data",
        "json": "data",
        "yaml": "data",
        "xml": "data",
        "toml": "data",
        "html": "data",
        "sql": "data",
        # email
        "eml": "email",
        "msg": "email",
        # image
        "png": "image",
        "jpeg": "image",
        "gif": "image",
        "webp": "image",
        "bmp": "image",
        "tiff": "image",
        "svg": "image",
        # archive
        "zip": "archive",
        "7z": "archive",
        "rar": "archive",
        # audio
        "audio": "audio",
        # unknown / binary 不分类
    }
    requested = getattr(args, "category", None)
    if requested:
        wanted = requested.lower()
        values = [v for v in values if category_map.get(v) == wanted]
        if not values:
            # 提示合法值（避免用户猜测错）
            return _fail(
                "unsupported_format",
                f"未知 category={requested}；合法值：document/data/email/image/archive/audio",
            )

    # v0.14.0/B-P0-1: 每个 format 的能力元数据（机器可读，让会话模型决定何时用哪个）
    details: list[dict[str, Any]] = []
    try:
        from core.file_parser import FileParser
        from core.format_capabilities import build_format_details

        # FileParser 初始化时会注册所有 parser；upload_dir 在 build_format_details 不需要
        fp = FileParser(upload_dir=Path("./uploads"))
        details = build_format_details(fp.registry)
    except Exception as cap_err:
        # capability 元数据是 best-effort；不影响 formats 列表返回
        logger.warning("[B-P0-1] format capabilities 探测失败: %s", cap_err)

    _emit(
        {
            "ok": True,
            "code": 200,
            "data": {
                "formats": values,
                "count": len(values),
                "category": requested or "all",
                "categories": sorted(set(category_map.values())),
                "output_formats": ["json", "markdown", "html", "text"],
                "conversion_types": ["auto", "text", "structured", "table", "image_desc", "ocr"],
                "details": details,  # v0.14.0/B-P0-1: [{format, capabilities}, ...]
            },
        }
    )
    return EXIT_OK


def cmd_version(_args: argparse.Namespace) -> int:
    from formatforge.__version__ import __version__

    _emit({"ok": True, "code": 200, "data": {"name": "dsh-formatforge", "version": __version__}})
    return EXIT_OK


def cmd_translate_main(
    path: Path,
    to_format: str,
    conv_type: str,
    timeout_s: int,
    pages: str | None = None,
    quality: bool = False,
    encoding: str | None = None,
    language: str | None = None,
    custom_prompt: str | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any] | None]:
    """供 batch 复用的单文件转换入口：返回 (content, meta, enhance)。

    v0.13.0/A3: 透传 quality/encoding/language/custom_prompt（之前 batch 路径全部丢失，
    导致 batch 出的 markdown 文件不会带 enhance 提示，会话模型无法决定是否增强）。

    timeout_s 参数保留签名兼容（实际超时由 JS 侧 spawn 控制；Python 内核当前未强制）。
    异常向上抛。
    """
    from core.models import ConversionType, OutputFormat
    from core.pipeline import ConversionPipeline, PipelineContext

    type_map = {
        "auto": ConversionType.AUTO,
        "text": ConversionType.TEXT,
        "structured": ConversionType.STRUCTURED,
        "table": ConversionType.TABLE,
        "image_desc": ConversionType.IMAGE_DESC,
        "ocr": ConversionType.OCR,
    }
    fmt_map = {
        "json": OutputFormat.JSON,
        "markdown": OutputFormat.MARKDOWN,
        "html": OutputFormat.HTML,
        "text": OutputFormat.TEXT,
    }
    started = time.time()
    pipeline = ConversionPipeline(enable_content_cache=False)
    ctx = PipelineContext(
        source=path,
        conversion_type=type_map.get(conv_type, ConversionType.AUTO),
        output_format=fmt_map[to_format],
        pages=pages,
        custom_prompt=custom_prompt,
        encoding=encoding,
    )
    response = pipeline.run(ctx)
    result = response.get("result")
    if result is None:
        raise ValueError(str(ctx.error or "未知错误"))
    # H1: 同 translate_file_data —— structuredData.error=True 说明这是错误响应页，不是转换产物
    result_sd = getattr(result, "structuredData", None)
    if isinstance(result_sd, dict) and result_sd.get("error"):
        raise ValueError(str(result.convertedContent))
    meta = {
        "parser": result.fileInfo.fileType.value if result.fileInfo else "unknown",
        "file_size": result.fileInfo.fileSize if result.fileInfo else 0,
        "result_id": result.resultId,
        "confidence": result.confidence,
        "elapsed_ms": int((time.time() - started) * 1000),
    }
    # A3: 语言 metadata 透传（写入 enhance.hint 让会话模型按目标语整理）
    if language:
        meta["target_language"] = str(language).lower()
    # A3: quality 模式开 → 计算质量报告（增强提示通过 pipeline 已写入 result.enhance）
    # 注意：quality 报告本身由 cmd_translate 出口统一生成；batch 复用这条路径时如果
    # callers 不需要完整 quality 字典，可只关心 enhance（这是会话模型消费的核心字段）
    enhance = result.enhance if isinstance(getattr(result, "enhance", None), dict) else None
    return result.convertedContent, meta, enhance


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="formatforge", description="把任意格式锻造成 AI 可读数据")
    sub = parser.add_subparsers(dest="command", required=True)

    p_tr = sub.add_parser("translate", help="转换文件或文本")
    p_tr.add_argument("path", nargs="?", help="本地文件路径")
    p_tr.add_argument("--stdin-text", action="store_true", help="从 stdin 读原始文本")
    p_tr.add_argument("--format", default="json", choices=["json", "markdown", "html", "text"])
    p_tr.add_argument("--type", default="auto", choices=["auto", "text", "structured", "table", "image_desc", "ocr"])
    p_tr.add_argument("--prompt", default=None, help="自定义转换指令")
    p_tr.add_argument("--quality", action="store_true", help="附带质量报告")
    p_tr.add_argument("--pages", default=None, help="PDF 页选择，如 1-3,7（仅 PDF 生效）")
    p_tr.add_argument("--encoding", default=None, help="文本编码覆写（如 gbk/latin-1，仅 TXT 类生效；自愈重试用）")
    p_tr.add_argument("--no-enhance-hint", action="store_true", help="禁用 enhance 提示字段")
    # B9/v0.10.0: 目标语标记（仅 metadata；实际翻译由会话模型按 enhance.hint 完成）
    p_tr.add_argument(
        "--language",
        default=None,
        help="目标语言代码（ISO 639-1，如 zh/en/ja）；写入 meta.target_language，让 enhance 阶段按此翻译",
    )
    # A9/v0.10.0: 把 content 另存到指定文件（stdout 仍输出协议 JSON）
    p_tr.add_argument("--output-file", default=None, help="把 content 写入此路径（stdout 协议 JSON 不变）。")
    p_tr.set_defaults(func=cmd_translate)

    # ── batch（EVOLUTION N3）──
    p_b = sub.add_parser("batch", help="批量转换目录或 glob 匹配的文件")
    p_b.add_argument("source", help="目录路径或 glob 模式（如 docs/*.pdf）")
    p_b.add_argument("--to", dest="format", default="markdown", choices=["json", "markdown", "html", "text"])
    p_b.add_argument("--out", default="ff-out", help="产物输出目录（默认 ./ff-out）")
    p_b.add_argument("--type", default="auto", choices=["auto", "text", "structured", "table", "image_desc", "ocr"])
    p_b.add_argument("--workers", type=int, default=4, help="并发线程数（默认 4）")
    p_b.add_argument("--recursive", action="store_true", help="递归子目录")
    p_b.add_argument("--quality", action="store_true", help="结果附 enhance 提示（v0.13.0: 透传到每个文件）")
    p_b.add_argument("--pages", default=None, help="PDF 页选择，如 1-3,7（仅 PDF 生效）")
    # v0.13.0/A3: 透传 encoding/language（与 translate 命令对齐）
    p_b.add_argument("--encoding", default=None, help="文本编码覆写（仅 TXT 类生效；自愈重试用）")
    p_b.add_argument(
        "--language",
        default=None,
        help="目标语言代码（ISO 639-1，如 zh/en/ja）；写入 meta.target_language",
    )
    p_b.add_argument("--force", action="store_true", help="忽略已有产物强制重转")
    p_b.set_defaults(func=cmd_batch)

    # B10/v0.12.0: 文件差异对比
    register_diff(sub)

    p_fm = sub.add_parser("formats", help="列出支持的格式")
    p_fm.add_argument(
        "--category",
        default=None,
        choices=["document", "data", "email", "image", "archive", "audio"],
        help="按分类过滤（如 document/data/image）",
    )
    p_fm.set_defaults(func=cmd_formats)

    p_ver = sub.add_parser("version", help="版本信息")
    p_ver.set_defaults(func=cmd_version)

    return parser


def main(argv: list[str] | None = None) -> int:
    # T1-6: 任何东西读写标准流之前先钉死编码。协议两面都是 UTF-8，而 Windows 管道
    # 默认走 locale 编码（cp1252）—— 不钉，非 ASCII 载荷会在第一行 JSON 出去之前
    # 就 UnicodeEncodeError，调用方只看到 internal(70)。
    pin_std_streams_utf8()

    parser = build_parser()

    # v1.0.1: argparse 错误包成协议 JSON 输出（保持 stdout 唯一出口约定）。
    # argparse 默认 print usage + 错误到 stderr 然后 exit 2 —— 破坏 stdout 唯一出口。
    # 方案：临时把 sys.stderr 替换为 _SilentStream（不写入），parse_args 后还原。
    # 这同时覆盖 pytest capsys（它替换 sys.stderr.write 而非 fd）。
    class _SilentStream:
        def write(self, *_args, **_kwargs):
            return 0

        def flush(self):
            pass

        def isatty(self):
            return False

        def writable(self):
            return True

        def readable(self):
            return False

        def seekable(self):
            return False

    _saved_stderr = sys.stderr
    # FF-M-protocol/audit: argparse 的 --help 会 print_help 到 **stdout** 并
    # SystemExit(0) —— usage 直接污染「stdout 唯一 JSON 出口」。这里把 stdout
    # 临时接到缓冲区：捕获到的 usage 走 stderr（人类通道），stdout 只发一条协议
    # JSON（data.help 带全文）。
    _saved_stdout = sys.stdout
    _captured = io.StringIO()
    sys.stdout = _captured
    sys.stderr = _SilentStream()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        # 先还原真实 stdout（_emit/_fail 必须写到真实 stdout），再决定出口
        sys.stdout = _saved_stdout
        sys.stderr = _saved_stderr
        usage_text = _captured.getvalue()
        if usage_text.strip():
            print(usage_text, file=_saved_stderr, end="")
            _emit({"ok": True, "code": 200, "data": {"help": usage_text}})
            return EXIT_OK
        if isinstance(e.code, int) and e.code != 0:
            # FF-M-kinds/audit: argparse 的参数错误此前报 internal(70)，
            # 与 errors.py 的 bad_request(7) 语义不符（且让调用方无法区分
            # 「用法错误」和「内部崩溃」）。
            return _fail("bad_request", f"参数错误（exit {e.code}）。试 --help 看用法。")
        raise
    finally:
        sys.stdout = _saved_stdout
        sys.stderr = _saved_stderr
    result_code: int = exit_code_of(ErrorCode.BAD_REQUEST)
    try:
        result_code = int(args.func(args))
    except SystemExit as e:
        # FF-M-kinds/audit: 原 `int(e.code or 0)` 在 SystemExit("用法提示") 上会抛
        # ValueError——异常处理器内再抛异常不会被下面的 except Exception 接住，
        # 于是「已知的参数错误」变成无协议 JSON 的 traceback。这里显式分类。
        code = e.code
        if code is None:
            result_code = EXIT_OK
        elif isinstance(code, int):
            result_code = code
        else:
            # 字符串 SystemExit 不是正常出口协议，命令也不会输出协议 JSON；
            # 这里补一条 bad_request 保证 stdout 仍只有一条合法 JSON。
            return _fail("bad_request", f"命令中止: {code}")
    except BrokenPipeError:
        return EXIT_OK
    except Exception as e:  # 兜底：任何未捕获异常都以协议 JSON 报告
        print(f"[formatforge] 未捕获异常: {e}", file=sys.stderr)
        return _fail("internal", str(e))
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
