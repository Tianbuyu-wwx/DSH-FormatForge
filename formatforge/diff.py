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
import logging
import math
from pathlib import Path
from typing import Any

from formatforge.protocol import emit

logger = logging.getLogger(__name__)


def _read_text_lines(path: Path, fmt: str) -> list[str]:
    """读文件 → 转成目标 format 的文本 → 按行返回。

    为避免重复计算，translate 子命令被内联调用：
    - text / markdown → translate 的 rawText
    - json → translate 的 structured_data 序列化（原样切行，不重新美化）
    """
    from formatforge.__main__ import translate_file_data  # noqa: PLC0415

    data, exit_code = translate_file_data(path, fmt, "auto", quality=False)
    if exit_code != 0 or not isinstance(data, dict) or "content" not in data:
        raise ValueError(f"转换失败: {data if isinstance(data, dict) else 'no data'}")
    content = str(data["content"])
    # FF-M-diff/audit: 不再对 json 重新 indent=2 序列化——那会让 lines_a/lines_b
    # 描述「美化后的形态」而不是源内容本身（行数/行号全是假的）。
    # 所有 format 一律按 translate 产出的内容直接切行。
    return content.splitlines()


def _int_opt(value: Any, default: int, floor: int) -> int:
    """FF-M-diff/audit: 数值选项归一化。

    旧写法 `int(args.context or 3)` 会把合法的 ``--context 0``（只看变更行）
    静默换成默认值 3 —— 显式传入的 0 与「未传」必须区分开。
    """
    if value is None:
        return max(floor, default)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return max(floor, default)
    return max(floor, parsed)


def _resolve_paths(args: argparse.Namespace) -> tuple[str | None, str | None]:
    """H12/audit: 双文件情形显式按文档顺序解析。

    用法文档约定 `diff <path_a> <path_b>`（path_a=旧版本在前）。argparse 因
    option-in-positional 限制把两个 positional 都注册为 optional，但注册顺序
    是 path_b 在前——这意味着双文件调用时 CLI 第一个实参落在 path_b 变量上、
    第二个落在 path_a 变量上，additions/deletions 从此 report 反了。
    两个都给了 → 按「位置语义」恢复文档顺序（第一个 = path_a，第二个 = path_b）；
    单文件（增量模式 path_a 缺省）不交换。
    """
    pa = args.path_a
    pb = args.path_b
    if pa and pb:
        # 双文件：CLI 实参顺序是 文档 path_a, path_b；当前变量是互换存着的 → 换回
        return pb, pa
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
            since_value = float(args.since_mtime)
        except (TypeError, ValueError):
            since_value = None
        if since_value is None or not math.isfinite(since_value):
            # FF-M-diff/audit: float("nan") 会「解析成功」但所有比较恒为 False
            # → 过滤器被静默禁用；NaN/inf 一律按参数错误处理。
            return _emit_diff(
                ok=False,
                code=4000 + exit_code_of(ErrorCode.BAD_REQUEST),
                data={},
                error={
                    "kind": ErrorCode.BAD_REQUEST.value,
                    "message": f"--since-mtime 必须是有限数字（Unix timestamp）: {args.since_mtime}",
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

    # FF-L-diff/audit: 同一文件 self-diff 此前是「无操作空 diff」却返回 ok:true
    # —— 调用方无法区分「真的没差异」和「传错了同一个路径」。显式报参数错误。
    try:
        same_file = path_a.resolve() == path_b.resolve()
    except OSError:
        same_file = str(path_a) == str(path_b)
    if same_file:
        return _emit_diff(
            ok=False,
            code=4000 + exit_code_of(ErrorCode.BAD_REQUEST),
            data={},
            error={
                "kind": ErrorCode.BAD_REQUEST.value,
                "message": f"path_a 与 path_b 是同一文件（{path_a.name}），无 diff 意义；请传入两个不同路径",
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
        context=_int_opt(getattr(args, "context", None), 3, 0),
        max_chars=_int_opt(getattr(args, "max_chars", None), 12000, 500),
    )
    return _emit_diff(ok=True, code=200, data=diff_payload)


def _cmd_diff_against_dir(args: argparse.Namespace, fmt: str) -> int:
    """v0.14.0/B-P0-2: 与 dir 内同 stem 文件做批量 diff。

    行为：
      - path_b 必填
      - path_a 可选（自动取 dir 内与 path_b 同 stem 的文件；多个候选按 mtime 确定性择新）
      - --since-mtime 过滤：path_a / path_b 任一侧 mtime < ts 即跳过（skipped=True）
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
        # FF-M-diff/audit: 多个同 stem 候选时不再取 glob 顺序的 candidates[0]
        # （顺序不确定 → 「旧版本」在两次运行间可能不同）；按 mtime 新→旧、
        # 同 mtime 按路径名排序，取确定性最优者。
        try:
            self_key = path_b.resolve()
        except OSError:  # pragma: no cover - 防御
            self_key = path_b
        candidates = []
        for p in list(against_dir.glob(f"{stem}.*")) + list(against_dir.glob(stem)):
            if not p.exists():
                continue
            try:
                if p.resolve() == self_key:
                    continue
            except OSError:  # pragma: no cover - 防御
                if p == path_b:
                    continue
            candidates.append(p)
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
        # FF-M-diff/audit: 确定性选择「旧版本」——mtime 新→旧，同 mtime 按路径名
        path_a = sorted(candidates, key=lambda p: (-p.stat().st_mtime, str(p)))[0]

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
            since_mtime_f = None
        if since_mtime_f is None or not math.isfinite(since_mtime_f):
            # FF-M-diff/audit: NaN/inf 会让所有比较恒为 False → 过滤器被静默禁用
            return _emit_diff(
                ok=False,
                code=4000 + exit_code_of(ErrorCode.BAD_REQUEST),
                data={},
                error={
                    "kind": ErrorCode.BAD_REQUEST.value,
                    "message": f"--since-mtime 必须是有限数字（Unix timestamp）: {since_mtime}",
                },
            )
        # FF-M-diff/audit: 两侧都过滤（注释此前声称二者皆需新于 ts，代码却只看
        # path_b）——哪一侧过旧就报哪一侧，不再静默产出 diff。
        for side, p in (("path_b", path_b), ("path_a", path_a)):
            side_mtime = p.stat().st_mtime
            if side_mtime < since_mtime_f:
                return _emit_diff(
                    ok=True,
                    code=200,
                    data={
                        "mode": "against_dir",
                        "skipped": True,
                        "reason": f"{side} mtime {side_mtime:.0f} < --since-mtime {since_mtime_f:.0f}",
                        "skipped_side": side,
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
        context=_int_opt(getattr(args, "context", None), 3, 0),
        max_chars=_int_opt(getattr(args, "max_chars", None), 12000, 500),
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
    elided = 0
    # FF-L-diff/audit: 不再先把完整 diff（含全部未变更上下文行）一次性拼成整串
    # 再 [:max_chars] 截断——那样会先物化整份公共内容（大文件 O(N) 内存）才丢。
    # 这里按行增量累计预算，超过 max_chars 即封顶并标记 truncated。
    diff_chunks: list[str] = []
    budget = max_chars
    truncated = False
    # T2-6/audit: diff_total_chars 是冻结字段，名字承诺的是「整份 diff 的长度」。
    # 封顶之后 diff_chunks 只剩保留下来的前缀，len(diff_text) 只会报到 ~max_chars。
    # 每一行都会流经 _emit_line（opcode 循环不提前 break，只是不再 append），所以
    # 在这里按行累加即可拿到真实总长，不需要把整份 diff 再物化一遍。
    total_chars = 0

    def _emit_line(s: str) -> bool:
        """把一行计入 diff 输出；预算耗尽返回 False（调用方停止追加）。"""
        nonlocal budget, truncated, total_chars
        # 先记账：无论这一行是否还进得了 diff_chunks，它都属于整份 diff。
        # +1 是 "\n".join 的连接符（末行多算的那个在返回时减掉）。
        total_chars += len(s) + 1
        if truncated:
            return False
        diff_chunks.append(s)
        budget -= len(s) + 1
        if budget < 0:
            truncated = True
        return not truncated

    last_opcode = len(opcodes) - 1
    for idx, (tag, i1, i2, j1, j2) in enumerate(opcodes):
        if tag == "equal":
            unchanged += i2 - i1
            # FF-M-diff/audit: 旧实现 `max(i1, i1 - context)` 恒等于 i1、`i2 + context`
            # 恒等于 i2 —— --context 完全无效，全部未变更内容都被吐出来。现在只保留
            # 变更前后各 context 行；中段省略并以显式标记 + elided_lines 报数。
            #
            # T2-9/audit: "变更前后各 context 行" 在首尾块上此前并没有真正实现——
            # 每个 equal 块都吐首尾两端。可首块的**前面**没有变更、尾块的**后面**
            # 也没有变更，那两端与任何改动都不相邻：白搭进去 context 行无关内容，
            # 外加一个指向文件开头/结尾的省略标记。按 unified diff 的语义，
            # 首块只保留尾部、尾块只保留头部，中间块两端都留。
            block = i2 - i1
            head_n = 0 if idx == 0 else context
            tail_n = 0 if idx == last_opcode else context
            if block <= head_n + tail_n:
                for ln in lines_a[i1:i2]:
                    _emit_line(" " + ln)
            else:
                if head_n:
                    for ln in lines_a[i1 : i1 + head_n]:
                        _emit_line(" " + ln)
                skipped = block - head_n - tail_n
                elided += skipped
                # 省略标记只在「夹在两处变更之间」的块上才有意义。首尾块省掉的是
                # 文件开头/结尾那段与改动无关的内容，unified diff 根本不会提它；
                # 总量仍由 elided_count 如实报出。
                if idx != 0 and idx != last_opcode:
                    _emit_line(f"... 省略 {skipped} 行未变更内容 ...")
                if tail_n:
                    for ln in lines_a[i2 - tail_n : i2]:
                        _emit_line(" " + ln)
        elif tag == "delete":
            deletions += i2 - i1
            for ln in lines_a[i1:i2]:
                _emit_line("-" + ln)
        elif tag == "insert":
            additions += j2 - j1
            for ln in lines_b[j1:j2]:
                _emit_line("+" + ln)
        elif tag == "replace":
            deletions += i2 - i1
            additions += j2 - j1
            for ln in lines_a[i1:i2]:
                _emit_line("-" + ln)
            for ln in lines_b[j1:j2]:
                _emit_line("+" + ln)

    similarity = round(unchanged * 2 / (len(lines_a) + len(lines_b) + 1e-9), 3) if (lines_a or lines_b) else 1.0
    diff_text = "\n".join(diff_chunks)
    # 预算封顶 + 尾部再保险截断，保证 diff_preview 长度 ≤ max_chars
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
        "elided_count": elided,
        "similarity": similarity,
        "diff_preview": diff_preview,
        "truncated": truncated,
        "max_chars": max_chars,
        # T2-6/audit: 未封顶时与 len(diff_text) 逐字节相等；封顶时报的是整份 diff
        # 的长度（即 max_chars 无限大时会得到的那个数），不是保留下来的前缀长度。
        # 口径里不含被 --context 省略掉的未变更行——那些行在任何预算下都不属于 diff。
        "diff_total_chars": max(0, total_chars - 1),
    }


def _emit_diff(ok: bool, code: int, data: dict, error: dict | None = None) -> int:
    payload: dict[str, Any] = {"ok": ok, "code": code, "data": data}
    if error:
        payload["error"] = error
    # T1-6: 与 __main__._emit 共用同一个出口（编码已钉死、失败也不自爆）
    emit(payload)
    from formatforge.__main__ import EXIT_OK

    if ok:
        return EXIT_OK

    # T3-9/audit: stdout 协议 code 和进程退出码必须表达同一错误类型。
    # 与 __main__._fail 一样以 core.errors 为权威，未知 kind 按 internal 收敛。
    from core.errors import ErrorCode, exit_code_of

    try:
        error_code = ErrorCode(str((error or {}).get("kind", "internal")))
    except ValueError:
        error_code = ErrorCode.INTERNAL
    return exit_code_of(error_code)


def register(sub: argparse._SubParsersAction) -> None:
    p_d = sub.add_parser("diff", help="对比两份文件内容差异（合同/法规/脚本版本对照）")
    # v0.14.0: path_a/path_b 都变 optional（增量模式只需 path_b），
    # argparse 限制：当 positional 是 [optional, required] 时中间夹 --option value 会解析失败，
    # 所以两个都 optional + 内部互斥检查。
    # 注册顺序仍是 path_b 在前；H12 修复后双文件调用在 _resolve_paths 里按
    # 位置语义恢复文档顺序（首个实参 = path_a 旧版）。
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
        help="增量模式：path_a/path_b 任一侧 mtime < 此 Unix timestamp 即跳过（NaN/inf 报参数错误）",
    )
    p_d.set_defaults(func=cmd_diff)
