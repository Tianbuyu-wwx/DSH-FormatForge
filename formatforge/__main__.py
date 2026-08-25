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


def cmd_translate(args: argparse.Namespace) -> int:
    from core.config import settings
    from core.models import ConversionType, OutputFormat
    from core.pipeline import ConversionPipeline, PipelineContext

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

    conversion_type = type_map[args.type]
    output_format = fmt_map[args.format]

    started = time.time()
    # CLI 一次性进程：关闭内容哈希缓存（磁盘缓存会让 enhance 提示等派生数据过期失效）
    pipeline = ConversionPipeline(enable_content_cache=False)
    ctx = PipelineContext(
        source=source,
        conversion_type=conversion_type,
        output_format=output_format,
        pages=getattr(args, "pages", None),
        custom_prompt=args.prompt,
    )
    response = pipeline.run(ctx)
    elapsed_ms = int((time.time() - started) * 1000)

    result = response.get("result")
    if result is None:
        err = ctx.error or "未知错误"
        # E2: pages 表达式错误 → 精确的 bad_request；其余按解析失败处理
        if "pages 参数格式错误" in str(err):
            return _fail("bad_request", str(err), code=ErrorCode.BAD_REQUEST)
        return _fail("parse_failed" if ctx.error else "internal", str(err))
    # E2: 管线吞错后仍产出 error 结果对象（convertedContent=错误消息）——识别 pages 错误
    if (
        result.structuredData
        and result.structuredData.get("error")
        and "pages 参数格式错误" in str(result.convertedContent)
    ):
        return _fail("bad_request", result.convertedContent, code=ErrorCode.BAD_REQUEST)

    data: dict[str, Any] = {
        "content": result.convertedContent,
        "format": args.format,
        "meta": {
            "parser": result.fileInfo.fileType.value if result.fileInfo else "unknown",
            "file_size": result.fileInfo.fileSize if result.fileInfo else 0,
            "result_id": result.resultId,
            "confidence": result.confidence,
            "elapsed_ms": elapsed_ms,
        },
    }
    if args.quality:
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
            # analyze() 返回 self（QualityReport 实例），协议 JSON 需要 dict。
            data["quality"] = analyzed.to_dict() if hasattr(analyzed, "to_dict") else analyzed
        except Exception as e:  # 质量报告失败不影响主结果
            print(f"[formatforge] 质量报告生成失败: {e}", file=sys.stderr)

    # M1: enhance 由管线层统一产出（BuildResultStep），CLI 只透传
    if not args.no_enhance_hint and getattr(result, "enhance", None):
        data["enhance"] = result.enhance

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
    _emit({"ok": True, "code": 200, "data": {"name": "dsh-formatforge", "version": "3.0.0-plugin"}})
    return EXIT_OK


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
    p_tr.add_argument("--no-enhance-hint", action="store_true", help="禁用 enhance 提示字段")
    p_tr.set_defaults(func=cmd_translate)

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
