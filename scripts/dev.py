#!/usr/bin/env python3
"""scripts/dev.py — DSH-FormatForge 一键开发脚本（C3）。

用法：
  python scripts/dev.py                # 全套：pytest + ruff + format + mypy + 烟雾测
  python scripts/dev.py --quick        # 仅烟雾测（CI 之前快速验）
  python scripts/dev.py --no-mypy      # 跳过 mypy（慢）
  python scripts/dev.py --publish      # 全套 + npm publish（需 npm 登录）

烟雾测：v0.10.0 起包含 ff_batch CLI 端到端（造临时目录 → batch → 检查产物）。
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable  # 当前 venv python（hermes 主 venv，3.11）

# 各命令解析（venv 切换规则：pytest/ruff/mypy 用 /e/.venv-common py312；CLI 烟雾测用 .venv-fg）
PY312 = Path(r"E:/.venv-common/Scripts/python.exe")  # 项目主 venv（py312 + 全套工具）
PYFG = (
    REPO / ".venv-fg" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
)  # CLI 烟雾测用 venv-fg（含 rapidocr）


def run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 600, env_extra: dict | None = None) -> int:
    """跑命令，实时流输出；返回 exit code。"""
    print(f"\n>>> {' '.join(cmd)}", flush=True)
    proc = subprocess.run(
        cmd,
        cwd=cwd or REPO,
        timeout=timeout,
        env={**__import__("os").environ, **(env_extra or {})},
    )
    return proc.returncode


def step_pytest(quick: bool) -> int:
    """pytest + R3 golden。"""
    args = [str(PY312), "-m", "pytest", "test/", "-q"]
    if quick:
        args += ["-x", "-k", "not slow"]
    return run(args, env_extra={"PYTHONPATH": str(REPO)})


def step_ruff() -> int:
    rc = run([str(PY312), "-m", "ruff", "check", "."], env_extra={"PYTHONPATH": str(REPO)})
    if rc == 0:
        rc = run([str(PY312), "-m", "ruff", "format", "--check", "."], env_extra={"PYTHONPATH": str(REPO)})
    return rc


def step_mypy() -> int:
    return run(
        [str(PY312), "-m", "mypy", "formatforge/", "core/", "parsers/"],
        env_extra={"PYTHONPATH": str(REPO)},
    )


def step_smoke() -> int:
    """CLI 烟雾测：formats / translate / batch 三个最常用路径。"""
    workdir = Path(tempfile.mkdtemp(prefix="ff-smoke-"))
    in_dir = workdir / "in"
    out_dir = workdir / "out"
    in_dir.mkdir(parents=True, exist_ok=True)
    # 拷一个 fixture（GBK 中文 txt）
    src = REPO / "test" / "fixtures" / "gbk_chinese.txt"
    shutil.copy(src, in_dir / "sample.txt")
    rc = 0

    # 1. translate
    rc |= run(
        [str(PYFG), "-m", "formatforge", "translate", str(in_dir / "sample.txt"), "--format", "json"],
        env_extra={"PYTHONPATH": str(REPO)},
    )

    # 2. formats --category document（v0.10.0 新）
    rc |= run(
        [str(PYFG), "-m", "formatforge", "formats", "--category", "document"], env_extra={"PYTHONPATH": str(REPO)}
    )

    # 3. batch（A9/B3 新）—— 必带 --force（首次跑无产物；后续用 mtime 续跑）
    rc |= run(
        [
            str(PYFG),
            "-m",
            "formatforge",
            "batch",
            str(in_dir),
            "--out",
            str(out_dir),
            "--to",
            "markdown",
            "--workers",
            "2",
            "--type",
            "auto",
            "--force",
        ],
        env_extra={"PYTHONPATH": str(REPO)},
    )

    # 检查产物存在
    md = out_dir / "sample.md"
    print(f"\n[smoke] product exists: {md.exists()} ({md.stat().st_size if md.exists() else 0} bytes)")
    if not md.exists():
        rc = 1

    shutil.rmtree(workdir, ignore_errors=True)
    return rc


def step_npm_publish() -> int:
    pkg_dir = REPO / "packages" / "dsh-formatforge"
    return run(["npm", "publish", "--access", "public"], cwd=pkg_dir, timeout=180)


def main() -> int:
    ap = argparse.ArgumentParser(description="DSH-FormatForge dev script")
    ap.add_argument("--quick", action="store_true", help="仅烟雾测")
    ap.add_argument("--no-mypy", action="store_true", help="跳过 mypy")
    ap.add_argument("--publish", action="store_true", help="npm publish（最后一步）")
    args = ap.parse_args()

    if not args.quick:
        rc = step_pytest(args.quick)
        if rc != 0:
            print(f"\n[FAIL] step_pytest 返回 {rc}")
            return rc
        rc = step_ruff()
        if rc != 0:
            print(f"\n[FAIL] step_ruff 返回 {rc}")
            return rc
        if not args.no_mypy:
            rc = step_mypy()
            if rc != 0:
                print(f"\n[FAIL] step_mypy 返回 {rc}")
                return rc

    rc = step_smoke()
    if rc != 0:
        print("\n[FAIL] 烟雾测失败")
        return rc

    if args.publish:
        rc = step_npm_publish()
        if rc != 0:
            print("\n[FAIL] npm publish 失败")
            return rc

    print("\n✅ dev 全套通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
