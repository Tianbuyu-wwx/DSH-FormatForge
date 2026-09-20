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
import concurrent.futures
import hashlib
import json
import logging
import queue
import re
import threading
import time
from concurrent.futures import Future, as_completed
from pathlib import Path
from typing import Any

from core.errors import ErrorCode, exit_code_of
from formatforge.protocol import emit

logger = logging.getLogger("formatforge.batch")


class _DaemonThreadPool:
    """Small Future-compatible pool whose running jobs cannot block process exit.

    ThreadPoolExecutor registers every worker for an interpreter-exit join, even
    after ``shutdown(wait=False)``. That defeats the batch deadline when a parser
    hangs. These workers are daemon threads and are not registered for that join.
    """

    def __init__(self, max_workers: int):
        self._queue: queue.Queue[Any] = queue.Queue()
        self._lock = threading.Lock()
        self._shutdown = False
        self._threads = [
            threading.Thread(target=self._worker, name=f"formatforge-batch-{idx}", daemon=True)
            for idx in range(max_workers)
        ]
        for thread in self._threads:
            thread.start()

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            future, fn, args, kwargs = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(fn(*args, **kwargs))
            except BaseException as exc:  # Future must surface worker failures to _record.
                future.set_exception(exc)

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        with self._lock:
            if self._shutdown:
                raise RuntimeError("cannot schedule new futures after shutdown")
            future: Future[Any] = Future()
            self._queue.put((future, fn, args, kwargs))
            return future

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            if cancel_futures:
                while True:
                    try:
                        item = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if item is not None:
                        item[0].cancel()
            for _ in self._threads:
                self._queue.put(None)
        if wait:
            for thread in self._threads:
                thread.join()

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


def _out_path_for(target: Path, source_dir: Path | None, out_dir: Path, out_ext: str, recursive: bool) -> Path:
    """计算单文件产物路径。

    H4/audit: 递归批处理的 stem-only 输出键会在子目录间碰撞（两个 sub/a.txt 和
    sub2/a.txt 都写 out/a.md）——目录源 + recursive 时按相对路径镜像子目录；
    其余情况保持 flat <stem><ext> 命名。
    """
    if recursive and source_dir is not None and source_dir.is_dir():
        try:
            rel = target.relative_to(source_dir)
        except ValueError:
            rel = None
        if rel is not None:
            return out_dir / rel.with_suffix(out_ext)
    return out_dir / f"{target.stem}{out_ext}"


def _out_key(path: Path) -> str:
    """产物键的比较形式。

    统一 casefold：Windows 上 `A.md`/`a.md` 是同一个文件，而 JS 侧（JS-H4）的
    clash 检测也是小写比较。宁可在 Linux 上把仅大小写不同的一对也当碰撞处理，
    也不要让同一批任务在不同平台产出不同的文件名。
    """
    return str(path).casefold()


def _artifact_digest(path: Path) -> tuple[int, str]:
    """Return the on-disk byte size and SHA-256 digest without loading it whole."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _load_integrity_records(report_path: Path) -> dict[str, dict[str, Any]]:
    """Load the prior report's artifact manifest; malformed/legacy reports fail closed."""
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    records: dict[str, dict[str, Any]] = {}
    for item in payload.get("artifacts", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        out = item.get("out")
        size = item.get("size")
        sha256 = item.get("sha256")
        if isinstance(out, str) and isinstance(size, int) and isinstance(sha256, str):
            records[_out_key(Path(out))] = item
    return records


def _artifact_matches(path: Path, record: dict[str, Any] | None) -> bool:
    """Verify a resume candidate against its persisted byte-size and digest."""
    if record is None or not path.is_file():
        return False
    try:
        size, sha256 = _artifact_digest(path)
    except OSError:
        return False
    return size == record.get("size") and sha256 == record.get("sha256")


def _ext_qualified(preferred: Path, target: Path, out_ext: str) -> Path:
    """碰撞消歧第一级：用源扩展名限定（`report.pdf` → `report.pdf.md`）。

    与 JS 侧 inbox-watcher 的产物键同构（`<源文件名>.ff.json`）。
    """
    suffix = target.suffix.lstrip(".")
    return preferred.with_name(f"{target.stem}.{suffix}{out_ext}" if suffix else f"{target.stem}{out_ext}")


def _path_hashed(qualified: Path, target: Path, salt: int = 0) -> Path:
    """碰撞消歧第二级：源路径哈希（同名同扩展名、只是目录不同时用）。

    与 JS 侧 case-clash 的 sha1 前 8 位守卫同构。取绝对路径，好让同一份源在
    `--force` 重跑时拿到稳定的产物名（续跑跳过才不会失效）。

    T2-7/audit: `salt` 只在哈希名本身还撞上已占用键时才递增（见
    `_plan_out_paths`）。salt=0 与加盐前的名字逐字节相同，所以正常批次的产物名
    和续跑跳过都不受影响。
    """
    try:
        raw = str(target.resolve())
    except OSError:
        raw = str(target)
    if salt:
        raw = f"{raw}#{salt}"
    digest = hashlib.sha1(raw.encode("utf-8", "surrogatepass")).hexdigest()[:8]
    return qualified.with_name(f"{qualified.stem}.{digest}{qualified.suffix}")


def _plan_out_paths(
    targets: list[Path], source_dir: Path | None, out_dir: Path, out_ext: str, recursive: bool
) -> dict[Path, Path]:
    """为整批目标一次性定产物路径，保证产物键两两不同。

    review #2/audit: H4 的消歧只覆盖「目录源 + --recursive」（call site 传的是
    `source if source.is_dir() else None`），剩下两类还会静默互相覆盖——
      (a) 跨子目录的 glob（`docs/*/a.pdf`）：sub1/a.pdf 与 sub2/a.pdf 都写 out/a.md；
      (b) 同目录不同扩展名的同名 stem（report.pdf + report.docx → out/report.md）。
    两者都是并发写、后写覆盖先写，而且两行都报 ok。

    消歧只发生在**真碰撞**的那一组上（不碰撞的文件名一个字母都不变）：
    先按扩展名限定，仍撞就再加源路径哈希。`_batch_report.json`
    是批次自身的保留名，源文件映射到该名时也走同一消歧链。
    """
    uniq = list(dict.fromkeys(targets))
    preferred = {t: _out_path_for(t, source_dir, out_dir, out_ext, recursive) for t in uniq}
    groups: dict[str, list[Path]] = {}
    for t in uniq:
        groups.setdefault(_out_key(preferred[t]), []).append(t)

    plan: dict[Path, Path] = {}
    # 不碰撞的键和批次报告名都是「已被占用」的——消歧名不许撞上它们。
    reserved = {_out_key(out_dir / "_batch_report.json")}
    taken = reserved | {key for key, group in groups.items() if len(group) == 1}
    for key, group in groups.items():
        if len(group) == 1 and key not in reserved:
            plan[group[0]] = preferred[group[0]]
            continue
        qualified = {t: _ext_qualified(preferred[t], t, out_ext) for t in group}
        subgroups: dict[str, list[Path]] = {}
        for t in group:
            subgroups.setdefault(_out_key(qualified[t]), []).append(t)
        for subkey, subgroup in subgroups.items():
            if len(subgroup) == 1 and subkey not in taken:
                plan[subgroup[0]] = qualified[subgroup[0]]
                taken.add(subkey)
                continue
            for t in subgroup:
                # T2-7/audit: 哈希级此前只「加入」taken，从不「检查」taken——与上面
                # 扩展名级的 `subkey not in taken` 不对称。`<stem>.<ext>.<sha8>.<out>`
                # 是可预测的名字，所以一个恰好叫 `report.txt.<sha8>.txt` 的源可以占住
                # 另一个源的哈希名，两行都报 ok 而只有一个产物落盘。冲突时换盐重哈希。
                hashed = _path_hashed(qualified[t], t)
                salt = 0
                while _out_key(hashed) in taken:
                    salt += 1
                    hashed = _path_hashed(qualified[t], t, salt)
                plan[t] = hashed
                taken.add(_out_key(hashed))
    return plan


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
    out_path: Path | None = None,
    deadline: float | None = None,
) -> dict[str, Any]:
    """转换单个文件，返回结果行。v0.13.0/A3: 透传 quality/encoding/language。

    H4/audit: conv_type 按文件逐个推断（auto 时按扩展名），不再取自 targets[0]。
    """
    from core.config import settings
    from formatforge.__main__ import cmd_translate_main

    started = time.time()

    # H4/audit: batch 路径此前完全没做 FF_MAX_BYTES 校验（只有 translate CLI 入口有）
    size = path.stat().st_size
    if size > settings.FF_MAX_BYTES:
        return {
            "file": str(path),
            "ok": False,
            "kind": "too_large",
            "message": f"文件 {size} 字节超过上限 {settings.FF_MAX_BYTES}",
            "elapsed_ms": 0,
        }

    # conv_type 逐文件解析（--type auto 时按扩展名提示）
    effective_conv_type = _EXT_FORMAT_HINT.get(path.suffix.lower(), "auto") if conv_type == "auto" else conv_type

    try:
        content, meta, enhance = cmd_translate_main(
            path, to_format, effective_conv_type, timeout_s, pages, quality, encoding, language
        )
    except Exception as e:  # 单文件失败不拖垮整批
        return {
            "file": str(path),
            "ok": False,
            "kind": "parse_failed",
            "message": str(e),
            "elapsed_ms": 0,
        }

    # K-7: a parser that returns after the batch deadline must not publish a
    # late artifact after the timeout summary has already been written.
    if deadline is not None and time.monotonic() >= deadline:
        return {
            "file": str(path),
            "ok": False,
            "kind": "timeout",
            "message": f"单文件转换超时（>{timeout_s}s）",
            "elapsed_ms": int((time.time() - started) * 1000),
        }

    elapsed = int((time.time() - started) * 1000)
    # 产物命名：<stem>.<to_format>（markdown→.md）；源已是目标扩展名时不重复后缀
    ext_map = {"markdown": ".md", "html": ".html", "json": ".json", "text": ".txt"}
    out_ext = ext_map.get(to_format, f".{to_format}")
    stem = path.stem if path.suffix.lower() == out_ext else path.stem
    if out_path is None:
        out_path = out_dir / f"{stem}{out_ext}"
    row: dict[str, Any] = {
        "file": str(path),
        "ok": True,
        "out": str(out_path),
        "parser": meta.get("parser", "?"),
        "confidence": meta.get("confidence", 0.0),
        "chars": len(content),
        "elapsed_ms": elapsed,
    }
    # H5/audit: 产物写入必须在 try 内——一次 OSError 不能让 fut.result() 抛出而拖垮整批
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(content, encoding="utf-8")
        artifact_size, artifact_sha256 = _artifact_digest(out_path)
    except Exception as e:
        return {
            "file": str(path),
            "ok": False,
            "kind": "write_failed",
            "message": f"产物写入失败: {out_path.name}: {e}",
            "elapsed_ms": elapsed,
        }
    row["artifact_size"] = artifact_size
    row["artifact_sha256"] = artifact_sha256
    # A3: 把 enhance 透传到结果行（让 batch 报告/产物消费者能感知增强提示）
    if enhance:
        row["enhance"] = enhance
    return row


def cmd_batch(args: argparse.Namespace) -> int:
    from core.config import settings

    started_all = time.time()
    started_monotonic = time.monotonic()
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

    from formatforge.output_guard import OutputPathError, resolve_output_path

    try:
        out_dir = resolve_output_path(args.out, source=source, label="--out")
    except OutputPathError as e:
        emit(
            {
                "ok": False,
                "code": 4000 + exit_code_of(ErrorCode.BAD_REQUEST),
                "error": {"kind": ErrorCode.BAD_REQUEST.value, "message": str(e)},
            }
        )
        return exit_code_of(ErrorCode.BAD_REQUEST)

    targets = _collect_targets(source, args.recursive)
    if not targets:
        # 空结果也写报告（测试契约：out/_batch_report.json 必须存在）
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
            "artifacts": [],
            "message": "没有匹配的可转换文件",
        }
        (out_dir / "_batch_report.json").write_text(
            json.dumps(empty_report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        emit(empty_report)  # T1-6: 统一出口，编码已钉死
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "_batch_report.json"
    previous_integrity = _load_integrity_records(report_path)
    workers = max(1, min(args.workers, 8))

    # 续跑：产物比源新 → 跳过（--force 强制重转）
    ext_map = {"markdown": ".md", "html": ".html", "json": ".json", "text": ".txt"}
    out_ext = ext_map.get(args.format, f".{args.format}")
    pending: list[tuple[Path, Path]] = []
    preserved_artifacts: list[dict[str, Any]] = []
    skipped = 0
    # H4/audit + review #2: 产物路径在 cmd_batch 统一规划（递归时镜像子目录；
    # glob/同目录混扩展名的真碰撞按扩展名、必要时再按源路径哈希消歧）
    planned = _plan_out_paths(targets, source if source.is_dir() else None, out_dir, out_ext, args.recursive)
    for t in targets:
        out_path = planned[t]
        if args.force:
            pending.append((t, out_path))
            continue
        existing = out_path
        record = previous_integrity.get(_out_key(existing))
        if (
            existing.exists()
            and existing.stat().st_mtime >= t.stat().st_mtime
            and _artifact_matches(existing, record)
        ):
            skipped += 1
            preserved_artifacts.append(
                {
                    "file": str(t),
                    "out": str(existing),
                    "size": record["size"],
                    "sha256": record["sha256"],
                }
            )
        else:
            pending.append((t, out_path))

    results: list[dict[str, Any]] = []
    # v0.13.0/A3: 透传 quality/encoding/language 给每个文件
    batch_quality = bool(getattr(args, "quality", False))
    batch_encoding = getattr(args, "encoding", None)
    batch_language = getattr(args, "language", None)
    per_file_timeout = max(1, int(settings.FF_TIMEOUT_S))
    batch_deadline = started_monotonic + per_file_timeout
    # H4/audit: conv_type 不再取自 targets[0]——把 --type 原值传下去，由 _translate_one
    # 按每个文件的扩展名逐个解析（mixed-extension 目录才能拿到各自正确的输出）
    pool = _DaemonThreadPool(max_workers=workers)
    try:
        futures = {
            pool.submit(
                _translate_one,
                t,
                out_dir,
                args.format,
                args.type,
                settings.FF_TIMEOUT_S,
                args.pages,
                batch_quality,
                batch_encoding,
                batch_language,
                out_path,
                batch_deadline,
            ): t
            for t, out_path in pending
        }
        # K-7: the JS runner kills the whole command at the same configured
        # timeout, so multiplying by N made this deadline almost unreachable.
        # Use the remaining time in one wall-clock window from command start.
        total_budget = max(0.001, batch_deadline - time.monotonic())
        # T2-8/audit: 每个 future 必须恰好产出一行。collected 是「已经记过账」的集合，
        # 超时清扫要靠它区分「完成但没被 as_completed 吐出来」和「真的还在跑」。
        collected: set[Any] = set()

        def _record(fut: Any, target: Path) -> None:
            collected.add(fut)
            try:
                results.append(fut.result())
            except concurrent.futures.CancelledError:
                results.append(
                    {
                        "file": str(target),
                        "ok": False,
                        "kind": "timeout",
                        "message": f"单文件转换超时（>{per_file_timeout}s），任务已取消",
                        "elapsed_ms": 0,
                    }
                )
            except Exception as e:  # noqa: BLE001  单行异常不拖垮整批
                results.append(
                    {
                        "file": str(target),
                        "ok": False,
                        "kind": "parse_failed",
                        "message": str(e),
                        "elapsed_ms": 0,
                    }
                )

        try:
            for fut in as_completed(futures, timeout=total_budget):
                _record(fut, futures[fut])
        except concurrent.futures.TimeoutError:
            # T2-8/audit: 旧代码只处理 `not fut.done()`，于是「预算到点前已经跑完、
            # 但 as_completed 还没来得及 yield」的 future 两边都不落——既不在
            # results 里，也不算 timeout。结果 ok_count + failed + skipped < total，
            # 一个转换成功的文件从 _batch_report.json 里凭空消失；产物却在盘上，
            # 续跑按 mtime 跳过它，用户永远不会知道它成功过。
            for fut, target in futures.items():
                if fut in collected:
                    continue
                if fut.done():
                    _record(fut, target)
                    continue
                fut.cancel()
                collected.add(fut)
                results.append(
                    {
                        "file": str(target),
                        "ok": False,
                        "kind": "timeout",
                        "message": f"单文件转换超时（>{per_file_timeout}s），未被整批拖垮",
                        "elapsed_ms": 0,
                    }
                )
            logger.warning("batch 部分文件超时——注意：worker 线程仍可能在后台运行")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    ok_rows = [r for r in results if r["ok"]]
    fail_rows = [r for r in results if not r["ok"]]
    # T2-8/audit: 记账不变式。targets = pending + skipped，且每个 pending 恰好提交
    # 一个 future，所以 ok + failed + skipped 必须等于 total。先前的审计把这个不变式
    # 当作「构造上必然成立」而驳回了对它的质疑——而 H4/H5 加的超时分支正是打破那个
    # 构造的地方。不用 assert（-O 会被剥掉，且崩掉整批比报出来更糟），出问题就留痕。
    accounted = len(ok_rows) + len(fail_rows) + skipped
    if accounted != len(targets):
        logger.error(
            "batch 记账不变式被破坏: ok=%d + failed=%d + skipped=%d = %d != total=%d",
            len(ok_rows),
            len(fail_rows),
            skipped,
            accounted,
            len(targets),
        )
    avg_conf = (sum(r.get("confidence", 0.0) for r in ok_rows) / len(ok_rows)) if ok_rows else 0.0
    elapsed_ms = int((time.time() - started_all) * 1000)
    artifact_records = preserved_artifacts + [
        {
            "file": r["file"],
            "out": r["out"],
            "size": r["artifact_size"],
            "sha256": r["artifact_sha256"],
        }
        for r in ok_rows
    ]

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
        # K-6: resume 只跳过与上次报告字节大小和 SHA-256 都一致的产物。
        "artifacts": artifact_records,
    }

    # 报告落盘（供续跑判断与人工查看），同时 stdout 输出协议 JSON
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    emit(summary)  # T1-6: 统一出口，编码已钉死
    return 0 if not fail_rows else exit_code_of(ErrorCode.PARSE_FAILED)
