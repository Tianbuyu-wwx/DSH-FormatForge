"""formatforge batch —— 批量转换命令（EVOLUTION_PLAN N3）。

用法：
    python -m formatforge batch <dir|glob> --to markdown --out out/ [--workers 4] [--recursive]

行为：
  - 目录或 glob 展开目标文件（按扩展名白名单过滤）
  - ThreadPoolExecutor 并发转换（解析是 CPU/IO 混合，线程池足够）
  - 每个文件独立调用 translate 主流程；失败不中断整体，汇总报告列出
  - 续跑：out/ 下已有同名产物且比源新 → 跳过
"""

from __future__ import annotations

import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from core.errors import ErrorCode, exit_code_of

#: 支持的输入扩展名（与 inbox watcher 白名单保持一致；v0.13.0/B2: 移除 .doc）
KNOWN_EXT = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".xlsm",
    ".csv",
    ".txt",
    ".md",
    ".markdown",
    ".rtf",
    ".odt",
    ".ods",
    ".odp",
    ".html",
    ".htm",
    ".xml",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".eml",
    ".msg",
    ".epub",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".tiff",
    ".zip",
    ".7z",
    ".rar",
    ".srt",
    ".sql",
    ".latex",
    ".tex",
}

_EXT_FORMAT_HINT = {
    ".json": "json",
    ".yaml": "json",
    ".yml": "json",
    ".toml": "json",
    ".xml": "json",
    ".csv": "table",
}


def _collect_targets(source: Path, recursive: bool) -> list[Path]:
    """展开目录/glob 为文件列表（按扩展名过滤、去重、排序）。"""
    if source.is_dir():
        pattern = "**/*" if recursive else "*"
        candidates = sorted(source.glob(pattern))
    else:
        # glob 模式（Path.glob 不支持绝对模式）：拆出锚目录再匹配剩余模式
        pattern = str(source)
        m = re.match(r"^([A-Za-z]:[\\/][^/\\]*[\\/]|[\\/][^/\\]+[\\/]|[^*/\\]+[\\/])", pattern)
        if m:
            anchor = Path(m.group(1))
            rel = pattern[len(m.group(1)) :]
        else:
            anchor = Path(".")
            rel = pattern
        candidates = sorted(anchor.glob(rel)) if rel else []
    return [p for p in candidates if p.is_file() and p.suffix.lower() in KNOWN_EXT]


def _translate_one(
    path: Path,
    out_dir: Path,
    to_format: str,
    conv_type: str,
    timeout_s: int,
    pages: str | None = None,
    quality: bool = False,
    encoding: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """转换单个文件，返回结果行。v0.13.0/A3: 透传 quality/encoding/language。"""
    from formatforge.__main__ import cmd_translate_main

    started = time.time()
    try:
        content, meta, enhance = cmd_translate_main(
            path, to_format, conv_type, timeout_s, pages, quality, encoding, language
        )
    except Exception as e:  # 单文件失败不拖垮整批
        return {
            "file": str(path),
            "ok": False,
            "kind": "parse_failed",
            "message": str(e),
            "elapsed_ms": 0,
        }

    elapsed = int((time.time() - started) * 1000)
    # 产物命名：<stem>.<to_format>（markdown→.md）；源已是目标扩展名时不重复后缀
    ext_map = {"markdown": ".md", "html": ".html", "json": ".json", "text": ".txt"}
    out_ext = ext_map.get(to_format, f".{to_format}")
    stem = path.stem if path.suffix.lower() == out_ext else path.stem
    out_path = out_dir / f"{stem}{out_ext}"
    out_path.write_text(content, encoding="utf-8")
    row: dict[str, Any] = {
        "file": str(path),
        "ok": True,
        "out": str(out_path),
        "parser": meta.get("parser", "?"),
        "confidence": meta.get("confidence", 0.0),
        "chars": len(content),
        "elapsed_ms": elapsed,
    }
    # A3: 把 enhance 透传到结果行（让 batch 报告/产物消费者能感知增强提示）
    if enhance:
        row["enhance"] = enhance
    return row


def cmd_batch(args: argparse.Namespace) -> int:
    from core.config import settings

    started_all = time.time()
    source = Path(args.source)
    # 存在性检查：目录直接查；glob 模式用 _collect_targets 判空（Path().glob 不支持绝对模式）
    if not source.exists() and not _collect_targets(source, getattr(args, "recursive", False)):
        print(
            __import__("json").dumps(
                {
                    "ok": False,
                    "code": 4000 + exit_code_of(ErrorCode.FILE_NOT_FOUND),
                    "error": {"kind": ErrorCode.FILE_NOT_FOUND.value, "message": f"源不存在: {source}"},
                },
                ensure_ascii=False,
            )
        )
        return exit_code_of(ErrorCode.FILE_NOT_FOUND)

    targets = _collect_targets(source, args.recursive)
    if not targets:
        # 空结果也写报告（测试契约：out/_batch_report.json 必须存在）
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        empty_report = {
            "ok": True,
            "code": 200,
            "total": 0,
            "ok_count": 0,
            "failed": 0,
            "skipped": 0,
            "avg_confidence": 0.0,
            "elapsed_ms": 0,
            "out_dir": str(out_dir),
            "results": [],
            "failures": [],
            "message": "没有匹配的可转换文件",
        }
        (out_dir / "_batch_report.json").write_text(
            json.dumps(empty_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(empty_report, ensure_ascii=False))
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    workers = max(1, min(args.workers, 8))
    conv_type = _EXT_FORMAT_HINT.get(targets[0].suffix.lower(), args.type) if args.type == "auto" else args.type

    # 续跑：产物比源新 → 跳过（--force 强制重转）
    ext_map = {"markdown": ".md", "html": ".html", "json": ".json", "text": ".txt"}
    out_ext = ext_map.get(args.format, f".{args.format}")
    pending: list[Path] = []
    skipped = 0
    for t in targets:
        if args.force:
            pending.append(t)
            continue
        existing = out_dir / f"{t.stem}{out_ext}"
        if existing.exists() and existing.stat().st_mtime >= t.stat().st_mtime:
            skipped += 1
        else:
            pending.append(t)

    results: list[dict[str, Any]] = []
    # v0.13.0/A3: 透传 quality/encoding/language 给每个文件
    batch_quality = bool(getattr(args, "quality", False))
    batch_encoding = getattr(args, "encoding", None)
    batch_language = getattr(args, "language", None)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _translate_one,
                t,
                out_dir,
                args.format,
                conv_type,
                settings.FF_TIMEOUT_S,
                args.pages,
                batch_quality,
                batch_encoding,
                batch_language,
            ): t
            for t in pending
        }
        for fut in as_completed(futures):
            results.append(fut.result())

    ok_rows = [r for r in results if r["ok"]]
    fail_rows = [r for r in results if not r["ok"]]
    avg_conf = (sum(r.get("confidence", 0.0) for r in ok_rows) / len(ok_rows)) if ok_rows else 0.0
    elapsed_ms = int((time.time() - started_all) * 1000)

    summary = {
        "ok": True,
        "code": 200,
        # 测试契约字段（EVOLUTION N3）：ok=成功数
        "total": len(targets),
        "ok_count": len(ok_rows),
        "failed": len(fail_rows),
        "skipped": skipped,
        "avg_confidence": round(avg_conf, 3),
        "elapsed_ms": elapsed_ms,
        "out_dir": str(out_dir),
        "results": results,
        "failures": [{"file": r["file"], "kind": r["kind"], "message": r["message"]} for r in fail_rows],
    }

    # 报告落盘（供续跑判断与人工查看），同时 stdout 输出协议 JSON
    report_path = out_dir / "_batch_report.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if not fail_rows else exit_code_of(ErrorCode.PARSE_FAILED)
