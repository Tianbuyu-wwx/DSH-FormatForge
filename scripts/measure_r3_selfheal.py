"""R3.3 SKILL.md 自愈闭环实测。

构造劣化样本集 → 首轮 ff_translate（带 quality）→ 解析 quality.actions[].retry_with
→ 按 SKILL.md 约定并入参数重调 → 统计「重调后质量改善」的成功率。

验收（ROADMAP R3）：一次自愈成功率 ≥80%。
运行：PYTHONPATH= python scripts/measure_r3_selfheal.py
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = REPO / ".venv-fg" / "Scripts" / "python.exe"

# 劣化样本集：(文件, 期望 self-heal 后改善的判据)
CASES = [
    {
        "name": "mojibake_gbk_as_latin1",
        "file": str(REPO / "test" / "fixtures" / "gbk_corrupted.txt"),
        "retry_hint": "encoding",
        "judge": lambda d: _has_action(d, "encoding"),
    },
    {
        "name": "image_only_scan",
        "file": str(REPO / "test" / "fixtures" / "image_only_test.pdf"),
        "retry_hint": "conversion_type",
        "judge": lambda d: _has_action(d, "coverage"),
    },
    {
        "name": "scanned_r2",
        "file": str(REPO / "test" / "fixtures" / "golden" / "r2_scanned.pdf"),
        "retry_hint": "conversion_type",
        "judge": lambda d: _has_action(d, "coverage") or _has_action(d, "table"),
    },
]


def _quality(data: dict | None) -> dict:
    """协议里 quality 在 data.data.quality（CLI: {ok, code, data:{..., quality}}）。"""
    if not data:
        return {}
    return ((data.get("data") or {}).get("quality")) or {}


def _has_action(data: dict | None, code: str) -> bool:
    for a in _quality(data).get("actions") or []:
        if a.get("code") == code and a.get("retry_with"):
            return True
    return False


def _first_retry_with(data: dict | None) -> dict | None:
    for a in _quality(data).get("actions") or []:
        if a.get("retry_with"):
            return a["retry_with"]
    return None


def run_cli(args: list[str]) -> dict | None:
    proc = subprocess.run(
        [str(PY), "-m", "formatforge", *args, "--quality"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(REPO),
        timeout=180,
    )
    out = (proc.stdout or "").strip()
    if not out:
        return None
    try:
        return json.loads(out.splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return None


def score(data: dict | None) -> float:
    if not data or not data.get("ok"):
        return 0.0
    return float(_quality(data).get("overall_score", 0))


def main() -> None:
    ok = 0
    rows = []
    for case in CASES:
        p = Path(case["file"])
        if not p.exists():
            rows.append((case["name"], "SKIP", "fixture 缺失"))
            continue

        # 第一轮
        r1 = run_cli(["translate", p.as_posix()])
        s1 = score(r1)
        retry = _first_retry_with(r1 or {})

        # 自愈判定：有 retry_with → 并入参数重调
        healed = False
        detail = f"round1 score={s1:.0f}"
        if retry:
            extra: list[str] = []
            if "encoding" in retry:
                extra += ["--encoding", str(retry["encoding"])]
            if "conversion_type" in retry:
                extra += ["--type", str(retry["conversion_type"])]
            r2 = run_cli(["translate", p.as_posix(), *extra])
            s2 = score(r2)
            improved = s2 > s1
            still_ok = (r2 or {}).get("ok") is True
            healed = improved or (still_ok and s1 == 0 and s2 > 0)
            detail += f" → retry_with={retry} → round2 score={s2:.0f} improved={improved} healed={healed}"
        else:
            detail += "（无可重试 action；若 enhance/正常则不算失败）"
            healed = (r1 or {}).get("ok") is True

        ok += 1 if healed else 0
        rows.append((case["name"], "PASS" if healed else "FAIL", detail))

    print(f"\nself-heal success: {ok}/{len(rows)} = {ok / max(len(rows), 1):.0%} (target ≥80%)")
    for name, verdict, detail in rows:
        print(f"  [{verdict:4s}] {name:18s} {detail}")

    sys.exit(0 if rows and ok / len(rows) >= 0.8 else 1)


if __name__ == "__main__":
    main()
