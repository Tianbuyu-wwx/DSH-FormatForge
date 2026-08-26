"""verify-install.py — dsh-formatforge 安装自检（EVOLUTION_PLAN M2）。

四道检查（对应 Phase 3/6 踩过的全部坑）：
  1. bundle 注册   —— profile package.json bundles 数组含本包
  2. boot 日志     —— web 日志有 "tools registered: ff_translate" 行（含 python 探测结果）
  3. HTTP 面       —— /formatforge/health 200 + client.js 可被宿主服务
  4. inbox 冒烟    —— 写一个 .txt 进 inbox，等 watcher 锻出 .ff.md（可 --skip-inbox 跳过）

用法：
  python scripts/verify-install.py            # 全量
  python scripts/verify-install.py --skip-inbox
  python scripts/verify-install.py --log <web日志路径>   # 指定日志文件

退出码：0=全过；1=有失败项（逐条列出修法提示）。
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

DSH_WEB = "http://127.0.0.1:3080"
PKG_NAME = "@tianbuyu-wwx/dsh-formatforge"
ENTRY_ID = "dsh-formatforge"

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str, str]] = []  # (status, name, detail)


def check(name: str, fn, fix_hint: str = "") -> bool:
    try:
        detail = fn()
        results.append((PASS, name, detail or ""))
        return True
    except Exception as e:
        results.append((FAIL, name, f"{e}{'  |  修法: ' + fix_hint if fix_hint else ''}"))
        return False


def check_bundle_declared() -> str:
    profile = Path.home() / ".dsh" / "profiles" / "web" / "package.json"
    d = json.loads(profile.read_text(encoding="utf-8"))
    bundles = d.get("dsh", {}).get("profile", {}).get("bundles", [])
    if PKG_NAME not in bundles and ENTRY_ID not in bundles:
        raise AssertionError(f"profile bundles 里没有 {PKG_NAME}（实际: {bundles}）")
    return f"bundles 含 {PKG_NAME}"


def check_boot_log(log_path: str | None) -> str:
    candidates = []
    if log_path:
        candidates.append(Path(log_path))
    tmp = os.environ.get("LOCALAPPDATA")
    if tmp:
        tmp_dir = Path(tmp) / "Temp"
        candidates += sorted(tmp_dir.glob("dsh_web*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        candidates += sorted(Path(tmp).glob("dsh_web*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    for p in candidates:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "tools registered: ff_translate" in text:
            line = next(ln for ln in text.splitlines() if "tools registered" in ln and "ff_translate" in ln)
            return f"{p.name}: {line.strip()[:90]}"
    raise AssertionError("没找到 'tools registered: ff_translate' 启动行（web 可能没重启或插件没加载）")


def check_health() -> str:
    with urllib.request.urlopen(f"{DSH_WEB}/formatforge/health", timeout=5) as r:
        body = json.loads(r.read().decode("utf-8"))
    if body.get("ok") is not True:
        raise AssertionError(f"health 返回异常: {body}")
    return f"inbox={body.get('inbox', '?')}"


def check_client_js() -> str:
    # manifest 里有本模块 + client.js 可访问且 id 一致
    with urllib.request.urlopen(f"{DSH_WEB}/", timeout=5) as r:
        html = r.read().decode("utf-8")
    if ENTRY_ID not in html:
        raise AssertionError("boot manifest 里没有 dsh-formatforge 模块")
    with urllib.request.urlopen(f"{DSH_WEB}/plugins/{ENTRY_ID}/client.js", timeout=5) as r:
        src = r.read().decode("utf-8")
    if f'id: "{ENTRY_ID}"' not in src:
        raise AssertionError("client.js 的 __ModuleLoader__.load id 与 loader entry 不一致")
    if ".apply =" not in src:
        raise AssertionError("client.js exports 缺 apply（cordis 插件形状）")
    return "manifest 收录 + id 一致 + apply 形状齐全"


def check_inbox_smoke() -> str:
    inbox = Path.home() / ".dsh" / "formatforge" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    marker = f"verify-install-{int(time.time())}"
    src = inbox / f"{marker}.txt"
    src.write_text(f"verify-install smoke test {marker}\n", encoding="utf-8")
    deadline = time.time() + 30
    while time.time() < deadline:
        md = inbox / f"{marker}.ff.md"
        if md.exists():
            # 清理冒烟产物
            with contextlib.suppress(OSError):
                (inbox / f"{marker}.ff.md").unlink()
                (inbox / f"{marker}.ff.json").unlink()
                src.unlink()
            return "watcher 30s 内完成锻造（产物已清理）"
        time.sleep(2)
    raise AssertionError("30s 内 watcher 没有产出 .ff.md（inbox watcher 未运行？）")


def main() -> int:
    ap = argparse.ArgumentParser(description="dsh-formatforge 安装自检")
    ap.add_argument("--log", default=None, help="dsh web 启动日志路径（默认自动找 %LOCALAPPDATA%/dsh_web*.log）")
    ap.add_argument("--skip-inbox", action="store_true", help="跳过 inbox 冒烟（不写测试文件）")
    args = ap.parse_args()

    check(
        "bundle 注册（profile package.json）",
        check_bundle_declared,
        "重跑 npx @deepseek-ai/dsh plugin add --profile web <路径或包名>",
    )
    check("boot 日志（工具注册行）", lambda: check_boot_log(args.log), "重启 dsh web；若仍无此行查插件 loader 报错")
    check("HTTP /formatforge/health", check_health, "确认 web 在 3080 端口运行且插件 v0.3+ 已加载")
    check(
        "client.js 模块契约",
        check_client_js,
        "跑 node packages/dsh-formatforge/test-manifest.mjs 定位；exports./client 与 load id 必须一致",
    )
    if not args.skip_inbox:
        check(
            "inbox watcher 冒烟",
            check_inbox_smoke,
            "web 启动日志应有 '[ff-inbox] watching'；FF_INBOX_NOTIFY 只影响通知不影响转换",
        )

    print()
    fails = 0
    for status, name, detail in results:
        mark = "✅" if status == PASS else "❌"
        print(f"{mark} {name}")
        if detail:
            print(f"   {detail}")
        if status == FAIL:
            fails += 1
    print(f"\n{'ALL GREEN' if fails == 0 else f'{fails} 项失败'}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
