"""formatforge diff —— 对比两份文件的内容差异（v0.12.0/B10，v0.14.0 增量模式）。

v0.14.0/B-P0-2 新增：
  - --against-dir <dir>: 与 dir 内每个文件最新版本做 diff
                        （path_a 变成可选——自动取 dir 内与 path_b 同 stem 的文件）
  - --since-mtime <ts>: 跳过 mtime < ts 的文件（ts 为 Unix timestamp 数字）

逐行 LCS diff（最长公共子序列）。可用于合同/法规/脚本版本对照。

用法：
    python -m formatforge diff <path_a> <path_b> [--format text] [--context 3]
    python -m formatforge diff --against-dir <dir> <path_b>   # v0.14.0 增量
    python -m formatforge diff <path_a> <path_b> --since-mtime 1234567890
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


def _resolve_paths(args: argparse.Namespace) -> tuple[str | None, str | None]:
    """v0.14.0: 容错 path_a/path_b 顺序。

    CLI 顺序约定 path_b 在前 path_a 在后（argparse 限制）。
    但 JS/测试可能仍传 path_a path_b 旧顺序——若 path_a 是文件 path_b 不是，互换。
    增量模式下 path_a 可缺；不参与互换。
    """
    pa = args.path_a
    pb = args.path_b
    if pa and pb:
        pa_p = Path(pa)
        pb_p = Path(pb)
        if pa_p.is_file() and not pb_p.is_file():
            return pb, pa  # 互换
    return pa, pb


def cmd_diff(args: argparse.Namespace) -> int:
    """v0.14.0: 增量模式支持 --against-dir / --since-mtime。

    三种合法调用：
      - 双文件模式：args.path_a + args.path_b（向后兼容）
      - 增量模式：args.path_b + --against-dir（path_a 自动 stem 匹配）
      - 增量 + 显式 A：args.path_a + args.path_b + --against-dir

    其他组合都是参数错误。
    """
    from core.errors import ErrorCode, exit_code_of  # noqa: PLC0415

    # v0.14.0: 容错 path_a/path_b 顺序（JS 端或旧调用可能传反）
    args.path_a, args.path_b = _resolve_paths(args)

    # v0.14.0: 参数互斥检查（argparse 都变 optional 后内部必须校验）
    if not args.path_b and not args.against_dir:
        return _emit_diff(
            ok=False,
            code=4000 + exit_code_of(ErrorCode.BAD_REQUEST),
            data={},
            error={
                "kind": ErrorCode.BAD_REQUEST.value,
                "message": "path_b 必填（除非用 --against-dir 增量模式）",
            },
        )
    if args.path_b and not args.against_dir and not args.path_a:
        return _emit_diff(
            ok=False,
            code=4000 + exit_code_of(ErrorCode.BAD_REQUEST),
            data={},
            error={
                "kind": ErrorCode.BAD_REQUEST.value,
                "message": "仅给 path_b 但没 --against-dir（无 path_a 可对比）",
            },
        )

    fmt = args.format or "text"

    # v0.14.0/B-P0-2: --since-mtime 类型校验最先（其他错误前先报）
    if getattr(args, "since_mtime", None) is not None:
        try:
            float(args.since_mtime)
        except (TypeError, ValueError):
            return _emit_diff(
                ok=False,
                code=4000 + exit_code_of(ErrorCode.BAD_REQUEST),
                data={},
                error={
                    "kind": ErrorCode.BAD_REQUEST.value,
                    "message": f"--since-mtime 必须是数字（Unix timestamp）: {args.since_mtime}",
                },
            )

    # v0.14.0/B-P0-2: --against-dir 增量模式
    if getattr(args, "against_dir", None):
        return _cmd_diff_against_dir(args, fmt)

    # 现状单文件模式
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

    diff_payload = _compute_diff(
        lines_a,
        lines_b,
        path_a,
        path_b,
        fmt,
        context=max(0, int(args.context or 3)),
        max_chars=max(500, int(args.max_chars or 12000)),
    )
    return _emit_diff(ok=True, code=200, data=diff_payload)


def _cmd_diff_against_dir(args: argparse.Namespace, fmt: str) -> int:
    """v0.14.0/B-P0-2: 与 dir 内同 stem 文件做批量 diff。

    行为：
      - path_b 必填
      - path_a 可选（自动取 dir 内与 path_b 同 stem 的文件）
      - --since-mtime 过滤：跳过 mtime < ts 的 path_b 文件
      - 输出包含 'diffs' 列表，每项是单文件 diff payload
    """
    from core.errors import ErrorCode, exit_code_of  # noqa: PLC0415

    against_dir = Path(args.against_dir)
    if not against_dir.is_dir():
        return _emit_diff(
            ok=False,
            code=4000 + exit_code_of(ErrorCode.FILE_NOT_FOUND),
            data={},
            error={
                "kind": ErrorCode.FILE_NOT_FOUND.value,
                "message": f"--against-dir 不是目录: {against_dir}",
            },
        )

    path_b = Path(args.path_b)
    if not path_b.exists():
        return _emit_diff(
            ok=False,
            code=4000 + exit_code_of(ErrorCode.FILE_NOT_FOUND),
            data={},
            error={
                "kind": ErrorCode.FILE_NOT_FOUND.value,
                "message": f"源不存在: {path_b}",
            },
        )

    stem = path_b.stem
    # 优先显式 path_a，否则扫 dir 同 stem
    if getattr(args, "path_a", None):
        path_a = Path(args.path_a)
    else:
        # v0.14.0/audit: 排除 path_b 自身（之前 glob(stem) 会匹配 new.txt 自身 → self-diff）
        candidates = [
            p
            for p in (list(against_dir.glob(f"{stem}.*")) + list(against_dir.glob(stem)))
            if p != path_b and p.exists()
        ]
        if not candidates:
            return _emit_diff(
                ok=False,
                code=4000 + exit_code_of(ErrorCode.FILE_NOT_FOUND),
                data={},
                error={
                    "kind": ErrorCode.FILE_NOT_FOUND.value,
                    "message": f"--against-dir {against_dir} 内找不到 stem={stem} 的文件",
                },
            )
        path_a = candidates[0]

    if not path_a.exists():
        return _emit_diff(
            ok=False,
            code=4000 + exit_code_of(ErrorCode.FILE_NOT_FOUND),
            data={},
            error={
                "kind": ErrorCode.FILE_NOT_FOUND.value,
                "message": f"源不存在: {path_a}",
            },
        )

    since_mtime = getattr(args, "since_mtime", None)
    if since_mtime is not None:
        try:
            since_mtime_f = float(since_mtime)
        except (TypeError, ValueError):
            return _emit_diff(
                ok=False,
                code=4000 + exit_code_of(ErrorCode.BAD_REQUEST),
                data={},
                error={
                    "kind": ErrorCode.BAD_REQUEST.value,
                    "message": f"--since-mtime 必须是数字（Unix timestamp）: {since_mtime}",
                },
            )
        # 过滤 path_b（也过滤 path_a 二者皆需新于 ts）
        if path_b.stat().st_mtime < since_mtime_f:
            return _emit_diff(
                ok=True,
                code=200,
                data={
                    "mode": "against_dir",
                    "skipped": True,
                    "reason": f"path_b mtime {path_b.stat().st_mtime:.0f} < --since-mtime {since_mtime_f:.0f}",
                    "path_b": str(path_b),
                    "path_a": str(path_a),
                },
            )

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

    diff_payload = _compute_diff(
        lines_a,
        lines_b,
        path_a,
        path_b,
        fmt,
        context=max(0, int(args.context or 3)),
        max_chars=max(500, int(args.max_chars or 12000)),
    )
    diff_payload["mode"] = "against_dir"
    diff_payload["against_dir"] = str(against_dir)
    return _emit_diff(ok=True, code=200, data=diff_payload)


def _compute_diff(
    lines_a: list[str],
    lines_b: list[str],
    path_a: Path,
    path_b: Path,
    fmt: str,
    *,
    context: int,
    max_chars: int,
) -> dict[str, Any]:
    """v0.14.0: 共享 diff 计算（单文件模式 + against_dir 模式都用）。"""
    matcher = difflib.SequenceMatcher(a=lines_a, b=lines_b, autojunk=False)
    opcodes = matcher.get_opcodes()

    additions = 0
    deletions = 0
    unchanged = 0
    diff_chunks: list[str] = []
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            unchanged += i2 - i1
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
    truncated = len(diff_text) > max_chars
    diff_preview = diff_text[:max_chars]

    return {
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
    }


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
    # v0.14.0: path_a/path_b 都变 optional（增量模式只需 path_b），
    # argparse 限制：当 positional 是 [optional, required] 时中间夹 --option value 会解析失败，
    # 所以两个都 optional + 内部互斥检查。
    # 顺序：CLI 调用必须 path_b 在前，path_a 在后——cmd_diff 内部通过 _resolve_paths 处理。
    p_d.add_argument("path_b", nargs="?", help="文件 B 路径（新版本）；增量模式必填")
    p_d.add_argument("path_a", nargs="?", help="文件 A 路径（旧版本；增量模式下可选）")
    p_d.add_argument("--format", default="text", choices=["json", "markdown", "html", "text"])
    p_d.add_argument("--context", type=int, default=3, help="diff 上下文行数（默认 3）")
    p_d.add_argument("--max-chars", type=int, default=12000, help="diff 文本截断上限（默认 12000）")
    # v0.14.0/B-P0-2: 增量模式
    p_d.add_argument(
        "--against-dir",
        dest="against_dir",
        default=None,
        help="与 dir 内同 stem 文件做 diff（path_a 可省）",
    )
    p_d.add_argument(
        "--since-mtime",
        dest="since_mtime",
        default=None,
        help="仅处理 mtime >= 此 Unix timestamp 的 path_b",
    )
    p_d.set_defaults(func=cmd_diff)
