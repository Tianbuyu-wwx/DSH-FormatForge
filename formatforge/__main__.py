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
EXIT_USAGE = 2
EXIT_PARSE_FAILED = 3
EXIT_LIMIT = 4

_KIND_EXIT = {
    "not_found": EXIT_USAGE,
    "unsupported_format": EXIT_PARSE_FAILED,
    "parse_failed": EXIT_PARSE_FAILED,
    "too_large": EXIT_LIMIT,
}


def _emit(payload: dict[str, Any]) -> None:
    """stdout 唯一出口：单行协议 JSON"""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _fail(kind: str, message: str) -> int:
    _emit({"ok": False, "code": 4000 + _KIND_EXIT.get(kind, EXIT_USAGE), "error": {"kind": kind, "message": message}})
    return _KIND_EXIT.get(kind, EXIT_USAGE)


def _build_enhance_hint(parsed_file: Any, confidence: float) -> dict[str, Any] | None:
    """按 PLUGIN_PLAN §6 判定是否需要调用方模型增强，返回 enhance 字段或 None。"""
    if not parsed_file:
        return None

    pages = getattr(parsed_file, "pages", []) or []
    total = len(pages)
    if total == 0:
        return None

    # image_only：多数页无文字层（扫描件）
    textless = sum(1 for p in pages if not (getattr(p, "rawText", "") or "").strip())
    if textless / total >= 0.5:
        return {
            "needed": True,
            "reason": "image_only",
            "hint": f"{textless}/{total} 页无文字层（疑似扫描件）。请基于 OCR 文本/图片描述重建结构并补齐表格。",
        }

    if confidence < 0.5:
        return {
            "needed": True,
            "reason": "low_confidence",
            "hint": f"转换置信度仅 {confidence:.2f}。请检查内容完整性并修复明显的解析噪声。",
        }

    # table_sparse：检测到表格但抽取内容稀疏
    has_table = any(getattr(p, "hasTable", False) for p in pages)
    table_cells = sum(
        1 for p in pages for e in (getattr(p, "elements", []) or []) if getattr(e, "elementType", "") == "table"
    )
    if has_table and table_cells == 0:
        return {
            "needed": True,
            "reason": "table_sparse",
            "hint": "检测到表格但未抽取到结构化单元格。请从原始文本重建 Markdown 表格。",
        }

    return None


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
        custom_prompt=args.prompt,
    )
    response = pipeline.run(ctx)
    elapsed_ms = int((time.time() - started) * 1000)

    result = response.get("result")
    if result is None:
        err = ctx.error or "未知错误"
        return _fail("parse_failed" if ctx.error else "internal", str(err))

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
            data["quality"] = report.analyze(
                content=result.convertedContent,
                file_size=result.fileInfo.fileSize if result.fileInfo else 0,
                file_type=result.fileInfo.fileType.value if result.fileInfo else "unknown",
                structured_data=result.structuredData,
            )
        except Exception as e:  # 质量报告失败不影响主结果
            print(f"[formatforge] 质量报告生成失败: {e}", file=sys.stderr)

    enhance = _build_enhance_hint(ctx.parsed_file, result.confidence)
    if enhance and not args.no_enhance_hint:
        data["enhance"] = enhance

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
    result_code: int = EXIT_USAGE
    try:
        result_code = int(args.func(args))
    except SystemExit as e:
        result_code = int(e.code or 0) if isinstance(e.code, (int, str)) else EXIT_USAGE
    except BrokenPipeError:
        return EXIT_OK
    except Exception as e:  # 兜底：任何未捕获异常都以协议 JSON 报告
        print(f"[formatforge] 未捕获异常: {e}", file=sys.stderr)
        return _fail("internal", str(e))
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
