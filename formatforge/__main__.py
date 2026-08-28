"""
FormatForge CLI 入口

协议契约（JS 侧 python-runner 依赖此形状，勿随意改动）：
    成功: {"ok": true,  "code": 200, "data": {content, format, meta, quality?, enhance?}}
    失败: {"ok": false, "code": <int>, "error": {"kind": str, "message": str}}
退出码: 0 成功 / 2 参数错 / 3 解析失败 / 4 超限
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# 确保仓库根目录在 sys.path（以 `python -m formatforge` 从任意 cwd 运行时）
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

EXIT_OK = 0

# M4: 错误码协议固化（core/errors.py 为唯一权威；旧 kind 字符串映射到新枚举）
from core.errors import ErrorCode, exit_code_of  # noqa: E402

_LEGACY_KIND = {
    "not_found": ErrorCode.FILE_NOT_FOUND,
    "is_directory": ErrorCode.IS_DIRECTORY,
    "unsupported_format": ErrorCode.UNSUPPORTED_FORMAT,
    "parse_failed": ErrorCode.PARSE_FAILED,
    "too_large": ErrorCode.TOO_LARGE,
}


from formatforge.batch import cmd_batch  # noqa: E402  (须在 sys.path 注入之后)


def _emit(payload: dict[str, Any]) -> None:
    """stdout 唯一出口：单行协议 JSON"""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _fail(kind: str, message: str, *, code: ErrorCode | None = None) -> int:
    """失败出口。kind 为旧字符串兼容参数；优先用 code 枚举。"""
    ec = code or _LEGACY_KIND.get(kind, ErrorCode.INTERNAL)
    exit_code = exit_code_of(ec)
    err = {"kind": ec.value, "message": message}
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
        return {"kind": "parse_failed", "message": str(err)}, 4
    if (
        result.structuredData
        and result.structuredData.get("error")
        and "pages 参数格式错误" in str(result.convertedContent)
    ):
        return {"kind": "bad_request", "message": result.convertedContent}, 7

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
        source = sys.stdin.read()
    else:
        path = Path(args.path) if args.path else None
        if not path:
            return _fail("internal", "必须提供 <path> 或 --stdin-text")
        if not path.exists():
            return _fail("not_found", f"文件不存在: {path}")
        if not path.is_file():
            return _fail("not_found", f"路径不是文件: {path}")
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
    if exit_code != 0:
        return _fail(str(data.get("kind", "internal")), str(data.get("message", data)))

    meta = data.get("meta")
    if isinstance(meta, dict):
        meta["elapsed_ms"] = elapsed_ms
        # R3.1 契约字段：标记 quality 是否自动开启（与会话模型对齐）
        meta["quality_auto"] = want_quality and not args.quality
    _emit({"ok": True, "code": 200, "data": data})
    return EXIT_OK


def cmd_formats(_args: argparse.Namespace) -> int:
    from core.format_detector import DataFormat

    values = sorted({m.value for m in DataFormat})
    _emit(
        {
            "ok": True,
            "code": 200,
            "data": {
                "formats": values,
                "count": len(values),
                "output_formats": ["json", "markdown", "html", "text"],
                "conversion_types": ["auto", "text", "structured", "table", "image_desc", "ocr"],
            },
        }
    )
    return EXIT_OK


def cmd_version(_args: argparse.Namespace) -> int:
    from formatforge.__version__ import __version__

    _emit({"ok": True, "code": 200, "data": {"name": "dsh-formatforge", "version": __version__}})
    return EXIT_OK


def cmd_translate_main(
    path: Path, to_format: str, conv_type: str, timeout_s: int, pages: str | None = None
) -> tuple[str, dict[str, Any]]:
    """供 batch 复用的单文件转换入口：返回 (content, meta)。异常向上抛。"""
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
    )
    response = pipeline.run(ctx)
    result = response.get("result")
    if result is None:
        raise ValueError(str(ctx.error or "未知错误"))
    meta = {
        "parser": result.fileInfo.fileType.value if result.fileInfo else "unknown",
        "file_size": result.fileInfo.fileSize if result.fileInfo else 0,
        "result_id": result.resultId,
        "confidence": result.confidence,
        "elapsed_ms": int((time.time() - started) * 1000),
    }
    return result.convertedContent, meta


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
    p_tr.set_defaults(func=cmd_translate)

    # ── batch（EVOLUTION N3）──
    p_b = sub.add_parser("batch", help="批量转换目录或 glob 匹配的文件")
    p_b.add_argument("source", help="目录路径或 glob 模式（如 docs/*.pdf）")
    p_b.add_argument("--to", dest="format", default="markdown", choices=["json", "markdown", "html", "text"])
    p_b.add_argument("--out", default="ff-out", help="产物输出目录（默认 ./ff-out）")
    p_b.add_argument("--type", default="auto", choices=["auto", "text", "structured", "table", "image_desc", "ocr"])
    p_b.add_argument("--workers", type=int, default=4, help="并发线程数（默认 4）")
    p_b.add_argument("--recursive", action="store_true", help="递归子目录")
    p_b.add_argument("--quality", action="store_true", help="结果附 enhance 提示")
    p_b.add_argument("--pages", default=None, help="PDF 页选择，如 1-3,7（仅 PDF 生效）")
    p_b.add_argument("--force", action="store_true", help="忽略已有产物强制重转")
    p_b.set_defaults(func=cmd_batch)

    p_fm = sub.add_parser("formats", help="列出支持的格式")
    p_fm.set_defaults(func=cmd_formats)

    p_ver = sub.add_parser("version", help="版本信息")
    p_ver.set_defaults(func=cmd_version)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result_code: int = exit_code_of(ErrorCode.BAD_REQUEST)
    try:
        result_code = int(args.func(args))
    except SystemExit as e:
        result_code = int(e.code or 0) if isinstance(e.code, (int, str)) else exit_code_of(ErrorCode.BAD_REQUEST)
    except BrokenPipeError:
        return EXIT_OK
    except Exception as e:  # 兜底：任何未捕获异常都以协议 JSON 报告
        print(f"[formatforge] 未捕获异常: {e}", file=sys.stderr)
        return _fail("internal", str(e))
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
