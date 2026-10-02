"""verify-install.py — dsh-formatforge 安装自检。

适配 DSH 0.2.0-rc.2（profile 化 + 桌面端）。

四道检查（对应 Phase 3/6 踩过的全部坑）：
  1. bundle 注册   —— profile package.json 的 dsh.profile.bundles 含本包
  2. boot 日志     —— 启动日志有 "tools registered: ff_translate" 行（含 python 探测结果）
  3. HTTP 面       —— /formatforge/health 200 + client.js 可被宿主服务
  4. inbox 冒烟    —— 写一个 .txt 进 inbox，等 watcher 锻出 .ff.md（可 --skip-inbox 跳过）

用法：
  python scripts/verify-install.py                      # 默认 desktop profile + 19387
  python scripts/verify-install.py --profile web --base-url http://127.0.0.1:3080
  python scripts/verify-install.py --skip-inbox
  python scripts/verify-install.py --log <启动日志路径>

退出码：0=全过；1=有失败项（逐条列出修法提示）。
"""

from __future__ import annotations

import argparse
import contextlib
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_cookiejar = http.cookiejar.CookieJar()

PKG_NAME = "@tianbuyu-wwx/dsh-formatforge"
ENTRY_ID = "dsh-formatforge"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[tuple[str, str, str]] = []  # (status, name, detail)


class SkippedError(Exception):
    """A check that cannot run in this environment.

    Deliberately not a failure: `check()` reports it as SKIP and it does not
    affect the exit code. The name carries the `Error` suffix only because the
    lint rule N818 requires it of every exception class.
    """


def check(name: str, fn, fix_hint: str = "") -> bool:
    try:
        detail = fn()
        results.append((PASS, name, detail or ""))
        return True
    except SkippedError as e:
        results.append((SKIP, name, f"{e}{'  |  ' + fix_hint if fix_hint else ''}"))
        return True
    except Exception as e:
        results.append((FAIL, name, f"{e}{'  |  修法: ' + fix_hint if fix_hint else ''}"))
        return False


class Config:
    profile = "desktop"
    base_url = "http://127.0.0.1:19387"
    log_path: str | None = None
    token: str | None = None


def dsh_home() -> Path:
    """Same precedence as the host's resolveDshHome(): $DSH_HOME, then ~/.dsh."""
    env = os.environ.get("DSH_HOME")
    if env is not None and env.strip():
        return Path(env.strip())
    return Path.home() / ".dsh"


def fetch(path: str, timeout: int = 5, with_token: bool = False) -> tuple[int, str]:
    """GET a host URL; returns (status, body). Never raises on HTTP errors.

    Two host quirks this encodes:
      - The UI token exchange is a 303 that sets a session cookie, so a request
        carrying `?token=` must go through a cookie jar — a bare urlopen follows
        the redirect but arrives without the cookie and the page answers 401.
      - Only the HTML page is token-gated. Bundle URLs are published as combo
        references (`plugins/??<pkg>/client.js&rev=…`) whose query string IS the
        module list, so appending `&token=` to one corrupts the rev and the route
        answers 404. Hence `with_token` is opt-in.
    """
    url = f"{Config.base_url}/{path.lstrip('/')}"
    if with_token and Config.token:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}token={Config.token}"
    req = urllib.request.Request(url, headers={"Accept": "text/html,application/json"})
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(_cookiejar),
        urllib.request.HTTPRedirectHandler(),
    )
    try:
        with opener.open(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def check_bundle_declared() -> str:
    profile = dsh_home() / "profiles" / Config.profile / "package.json"
    if not profile.is_file():
        raise AssertionError(f"profile 未初始化：{profile}（先启动一次宿主）")
    d = json.loads(profile.read_text(encoding="utf-8"))
    bundles = d.get("dsh", {}).get("profile", {}).get("bundles", [])
    deps = d.get("dependencies", {})
    if PKG_NAME not in bundles:
        raise AssertionError(f"bundles 里没有 {PKG_NAME}（实际: {bundles}）")
    if PKG_NAME not in deps:
        raise AssertionError(f"dependencies 里没有 {PKG_NAME}（实际: {list(deps)}）")
    return f"{profile.parent.name}/bundles 含 {PKG_NAME}（{deps[PKG_NAME]}）"


def candidate_logs() -> list[Path]:
    out: list[Path] = []
    if Config.log_path:
        out.append(Path(Config.log_path))
    # 0.2.x 桌面端：%APPDATA%/@deepseek-ai/dsh-desktop/logs/*.log
    appdata = os.environ.get("APPDATA")
    if appdata:
        for sub in ("@deepseek-ai/dsh-desktop/logs", "@deepseek-ai/dsh-desktop"):
            d = Path(appdata) / sub
            if d.is_dir():
                out += sorted(d.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
    # 自定义 DSH_HOME：<home>/logs/*.log
    for d in (dsh_home() / "logs", Path.home() / ".dsh" / "logs"):
        if d.is_dir():
            out += sorted(d.rglob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]
    # 旧 web 形态把 stdout 重定向到 %LOCALAPPDATA%\dsh_web*.log
    tmp = os.environ.get("LOCALAPPDATA")
    if tmp:
        for d in (Path(tmp) / "Temp", Path(tmp)):
            if d.is_dir():
                out += sorted(d.glob("dsh_web*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    return out


def _looks_like_dsh_log(p: Path) -> bool:
    """粗略判定"这份日志可能来自 DSH 宿主"：文件名像启动日志，或内容里出现 DSH 包名。"""
    if p.name.startswith("startup-") or p.name.startswith("dsh") or p.name.startswith("crash-"):
        return True
    try:
        head = p.read_text(encoding="utf-8", errors="ignore")[:4000]
    except OSError:
        return False
    return "@deepseek-ai/dsh" in head or "dsh-formatforge" in head


def _is_failure_log(p: Path) -> bool:
    """崩溃日志 / 启动失败日志：这类日志里当然没有工具注册行，不能据此判插件未加载。"""
    if p.name.startswith("crash-"):
        return True
    try:
        head = p.read_text(encoding="utf-8", errors="ignore")[:8000]
    except OSError:
        return False
    return "startup failed" in head or "StartupError" in head


def check_boot_log() -> str:
    candidates = candidate_logs()
    for p in candidates:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "tools registered: ff_translate" in text:
            line = next(ln for ln in text.splitlines() if "tools registered" in ln and "ff_translate" in ln)
            py = next((ln for ln in reversed(text.splitlines()) if "python=" in ln and "dsh-formatforge" in ln), "")
            return f"{p.name}: {line.strip()[:90]}{('  |  ' + py.strip()[:80]) if py else ''}"
    dsh_logs = [p for p in candidates if _looks_like_dsh_log(p)]
    healthy = [p for p in dsh_logs if not _is_failure_log(p)]
    if not healthy:
        # 桌面端只在启动**失败**/崩溃时落盘日志：手里只有 crash-* 与 startup-failed 日志时，
        # "找不到工具注册行"说明不了插件没加载（HTTP 面那项才是硬证据）。避免自检误报。
        raise SkippedError(
            f"只有崩溃/启动失败日志（{len(dsh_logs)} 份），没有正常启动日志 → 跳过；以 HTTP 面与面板自检为准"
        )
    raise AssertionError(
        f"找到 {len(healthy)} 份正常启动日志但没有 'tools registered: ff_translate' 行（宿主可能没重启，或插件未加载）"
    )


def check_health() -> str:
    status, body = fetch("formatforge/health")
    if status != 200:
        raise AssertionError(f"/formatforge/health 返回 {status}（插件未加载？）")
    payload = json.loads(body)
    if payload.get("ok") is not True:
        raise AssertionError(f"health 返回异常: {payload}")
    return f"inbox={payload.get('inbox', '?')}"


def check_client_js() -> str:
    # 0.2.x：boot manifest 是注入的 window.__DSH_BOOT__ 图，模块行以包名为 id，
    # bundle URL 是宿主发布的 combo 形式 `plugins/??<pkg>/client.js&rev=...`
    # （相对路径；不带 combo 前缀的单资源路径会 404）。web UI 受 token 保护。
    status, html = fetch("", with_token=True)
    if status == 401:
        raise SkippedError(
            "根页面 401：web UI 需要 token（用 --token 提供，值见宿主启动日志的 `dsh web: http://…?token=…`）"
        )
    if status != 200:
        raise AssertionError(f"根页面返回 {status}")
    if PKG_NAME not in html:
        raise AssertionError(f"boot manifest 里没有 {PKG_NAME} 的模块行")
    m = re.search(r'"id":"' + re.escape(PKG_NAME) + r'","url":"([^"]+)"', html)
    if not m:
        raise AssertionError(f"boot graph 里找不到 {PKG_NAME} 的 entry.url")
    rel = m.group(1).replace("&amp;", "&")
    status, src = fetch(rel)
    if status != 200:
        raise AssertionError(f"{rel} 返回 {status}")
    if f'id: "{PKG_NAME}"' not in src:
        raise AssertionError("client.js 的 __ModuleLoader__.load id 不等于包名（宿主会 'loaded without registering'）")
    if "exports.apply" not in src:
        raise AssertionError("client.js exports 缺 apply（cordis 插件形状）")
    return f"graph entry rev={rel.rsplit('rev=', 1)[-1]} + id=包名 + apply 形状齐全"


def check_inbox_smoke() -> str:
    inbox = dsh_home() / "formatforge" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    marker = f"verify-install-{int(time.time())}"
    src = inbox / f"{marker}.txt"
    src.write_text(f"verify-install smoke test {marker}\n", encoding="utf-8")
    deadline = time.time() + 30
    while time.time() < deadline:
        md = inbox / f"{marker}.ff.md"
        if md.exists():
            with contextlib.suppress(OSError):
                (inbox / f"{marker}.ff.md").unlink()
                (inbox / f"{marker}.ff.json").unlink()
                src.unlink()
            return "watcher 30s 内完成锻造（产物已清理）"
        time.sleep(2)
    with contextlib.suppress(OSError):
        src.unlink()
    raise AssertionError("30s 内 watcher 没有产出 .ff.md（inbox watcher 未运行？）")


def main() -> int:
    # Windows 控制台默认 GBK；本脚本输出 ✅/❌ 与中文诊断，必须先切到 UTF-8。
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="dsh-formatforge 安装自检")
    ap.add_argument("--profile", default="desktop", help="要检查的 dsh profile（默认 desktop）")
    ap.add_argument(
        "--base-url",
        default=None,
        help="宿主 HTTP 基址（默认按 profile 猜：desktop→19387，其它→3080）",
    )
    ap.add_argument(
        "--log",
        default=None,
        help="启动日志路径（默认自动扫描 %APPDATA%/@deepseek-ai/dsh-desktop/logs 与 $DSH_HOME/logs）",
    )
    ap.add_argument(
        "--token",
        default=os.environ.get("FF_VERIFY_TOKEN"),
        help="web UI token（根页面 401 时需要；也可用环境变量 FF_VERIFY_TOKEN）",
    )
    ap.add_argument("--skip-inbox", action="store_true", help="跳过 inbox 冒烟（不写测试文件）")
    args = ap.parse_args()

    Config.profile = args.profile
    Config.log_path = args.log
    Config.token = args.token
    Config.base_url = (
        args.base_url or ("http://127.0.0.1:19387" if args.profile == "desktop" else "http://127.0.0.1:3080")
    ).rstrip("/")

    check(
        "bundle 注册（profile package.json）",
        check_bundle_declared,
        f"重跑 dsh plugin --profile {Config.profile} add <本包路径>",
    )
    check("boot 日志（工具注册行）", check_boot_log, "重启宿主；若仍无此行查启动日志里的插件 loader 报错")
    check("HTTP /formatforge/health", check_health, f"确认 {Config.base_url} 上的宿主正在运行且插件已加载")
    check(
        "client.js 模块契约",
        check_client_js,
        "跑 node packages/dsh-formatforge/test-manifest.mjs 与 test-client-bundle.mjs 定位；"
        "拖拽行为单跑 test-client-drag.mjs",
    )
    if not args.skip_inbox:
        check(
            "inbox watcher 冒烟",
            check_inbox_smoke,
            "启动日志应有 '[ff-inbox] watching'；FF_INBOX_NOTIFY 只影响通知不影响转换",
        )

    print()
    fails = 0
    skips = 0
    for status, name, detail in results:
        mark = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}[status]
        print(f"{mark} {name}")
        if detail:
            print(f"   {detail}")
        if status == FAIL:
            fails += 1
        elif status == SKIP:
            skips += 1
    tail = "ALL GREEN" if fails == 0 else f"{fails} 项失败"
    if skips:
        tail += f"（{skips} 项跳过）"
    print(f"\n{tail}")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
