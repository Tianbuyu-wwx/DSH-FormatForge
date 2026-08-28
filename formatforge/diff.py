"""formatforge diff —— 对比两份文件的内容差异（v0.12.0/B10）。

逐行 LCS diff（最长公共子序列）。可用于合同/法规/脚本版本对照。

用法：
    python -m formatforge diff <path_a> <path_b> [--format text] [--context 3] [--max-chars 12000]
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _read_text_lines(path: Path, fmt: str) -> list[str]:
    """读文件 → 转成目标 format 的文本 → 按行返回。

    为避免重复计算，translate 子命令被内联调用：
    - text / markdown → translate 的 rawText
    - json → translate 的 structured_data 序列化
    """
    from formatforge.__main__ import translate_file_data  # noqa: PLC0415

    data, exit_code = translate_file_data(path, fmt, "auto", quality=False)
    if exit_code != 0 or not isinstance(data, dict) or "content" not in data:
        raise ValueError(f"转换失败: {data if isinstance(data, dict) else 'no data'}")
    content = str(data["content"])
    # markdown/text 直接按行；json 用紧凑 JSON 序列化按 \n 拆
    if fmt in ("text", "markdown"):
        return content.splitlines()
    elif fmt == "json":
        try:
            obj = json.loads(content)
            return json.dumps(obj, ensure_ascii=False, indent=2).splitlines()
        except json.JSONDecodeError:
            return content.splitlines()
    else:
        return content.splitlines()


def cmd_diff(args: argparse.Namespace) -> int:
    from core.errors import ErrorCode, exit_code_of  # noqa: PLC0415

    path_a = Path(args.path_a)
    path_b = Path(args.path_b)

    for p in (path_a, path_b):
        if not p.exists():
            return _emit_diff(
                ok=False,
                code=4000 + exit_code_of(ErrorCode.FILE_NOT_FOUND),
                data={},
                error={
                    "kind": ErrorCode.FILE_NOT_FOUND.value,
                    "message": f"源不存在: {p}",
                },
            )

    fmt = args.format or "text"
    try:
        lines_a = _read_text_lines(path_a, fmt)
        lines_b = _read_text_lines(path_b, fmt)
    except Exception as e:
        return _emit_diff(
            ok=False,
            code=4000 + exit_code_of(ErrorCode.PARSE_FAILED),
            data={},
            error={
                "kind": ErrorCode.PARSE_FAILED.value,
                "message": f"读取/转换失败: {e}",
            },
        )

    # 上下文行数（--context 默认 3）
    context = max(0, int(args.context or 3))

    # LCS diff → unified diff
    matcher = difflib.SequenceMatcher(a=lines_a, b=lines_b, autojunk=False)
    opcodes = matcher.get_opcodes()

    additions = 0
    deletions = 0
    unchanged = 0
    diff_chunks: list[str] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            unchanged += i2 - i1
            # 上下文：保留前后几行
            ctx_start = max(i1, i1 - context) if i1 > 0 else i1
            ctx_end_a = min(i2, i2 + context) if i2 < len(lines_a) else i2
            for ln in lines_a[ctx_start:ctx_end_a]:
                diff_chunks.append(" " + ln)
        elif tag == "delete":
            deletions += i2 - i1
            for ln in lines_a[i1:i2]:
                diff_chunks.append("-" + ln)
        elif tag == "insert":
            additions += j2 - j1
            for ln in lines_b[j1:j2]:
                diff_chunks.append("+" + ln)
        elif tag == "replace":
            deletions += i2 - i1
            additions += j2 - j1
            for ln in lines_a[i1:i2]:
                diff_chunks.append("-" + ln)
            for ln in lines_b[j1:j2]:
                diff_chunks.append("+" + ln)

    similarity = round(unchanged * 2 / (len(lines_a) + len(lines_b) + 1e-9), 3) if (lines_a or lines_b) else 1.0
    diff_text = "\n".join(diff_chunks)
    max_chars = max(500, int(args.max_chars or 12000))
    truncated = len(diff_text) > max_chars
    diff_preview = diff_text[:max_chars]

    return _emit_diff(
        ok=True,
        code=200,
        data={
            "path_a": str(path_a),
            "path_b": str(path_b),
            "format": fmt,
            "lines_a": len(lines_a),
            "lines_b": len(lines_b),
            "additions": additions,
            "deletions": deletions,
            "unchanged_count": unchanged,
            "similarity": similarity,
            "diff_preview": diff_preview,
            "truncated": truncated,
            "max_chars": max_chars,
            "diff_total_chars": len(diff_text),
        },
    )


def _emit_diff(ok: bool, code: int, data: dict, error: dict | None = None) -> int:
    payload: dict[str, Any] = {"ok": ok, "code": code, "data": data}
    if error:
        payload["error"] = error
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()
    from formatforge.__main__ import EXIT_OK

    return EXIT_OK if ok else 1


def register(sub: argparse._SubParsersAction) -> None:
    p_d = sub.add_parser("diff", help="对比两份文件内容差异（合同/法规/脚本版本对照）")
    p_d.add_argument("path_a", help="文件 A 路径（旧版本）")
    p_d.add_argument("path_b", help="文件 B 路径（新版本）")
    p_d.add_argument("--format", default="text", choices=["json", "markdown", "html", "text"])
    p_d.add_argument("--context", type=int, default=3, help="diff 上下文行数（默认 3）")
    p_d.add_argument("--max-chars", type=int, default=12000, help="diff 文本截断上限（默认 12000）")
    p_d.set_defaults(func=cmd_diff)
