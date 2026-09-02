"""v1.0/iter2: 生成协议 JSON shape snapshot。

实际跑 CLI 拿真 JSON，转 shape（值 → 类型）落盘。
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(r"E:\项目\DSH-FormatForge")
PYFG = REPO / ".venv-fg" / "Scripts" / "python.exe"
sys.path.insert(0, str(REPO))
from core.errors import EXIT_CODES, MESSAGES  # noqa: E402

PROTO = REPO / "packages" / "dsh-formatforge" / "protocol" / "v1"
PROTO.mkdir(parents=True, exist_ok=True)


def run(args, stdin=None):
    r = subprocess.run(
        [str(PYFG), "-m", "formatforge"] + list(args),
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env={**os.environ, "PYTHONPATH": str(REPO)},
        input=stdin,
        timeout=30,
    )
    if r.returncode not in (0, 1):
        print(f"WARN {args} rc={r.returncode} stderr={r.stderr[:200]}")
    return r


def shape(payload, depth=0, max_list_items=1):
    """把协议 JSON 转成 shape 文档——值用类型占位符。"""
    if depth > 6:
        return "<deep>"
    if isinstance(payload, dict):
        return {k: shape(v, depth + 1, max_list_items) for k, v in payload.items()}
    if isinstance(payload, list):
        if not payload:
            return []
        # 保留第一个 item 作为示例（list 类型也可能是异构，但协议应一致）
        if len(payload) <= max_list_items:
            return [shape(item, depth + 1, max_list_items) for item in payload]
        return [shape(payload[0], depth + 1, max_list_items), f"...({len(payload)} items)"]
    if isinstance(payload, bool):
        return "<bool>"
    if isinstance(payload, int):
        return "<int>"
    if isinstance(payload, float):
        return "<float>"
    if payload is None:
        return "<null>"
    return "<string>"


def save(name, payload):
    shape_doc = shape(payload)
    out_path = PROTO / name
    out_path.write_text(
        json.dumps(shape_doc, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return shape_doc


# 1. version
print("[1/6] version")
r = run(["version"])
save("version.schema.json", json.loads(r.stdout))

# 2. formats (含 details/capabilities)
print("[2/6] formats")
r = run(["formats"])
save("formats.schema.json", json.loads(r.stdout))

# 3. translate happy path
print("[3/6] translate")
with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
    f.write("hello forge\n")
    tmp = f.name
try:
    r = run(["translate", tmp, "--format", "text"])
    save("translate.schema.json", json.loads(r.stdout))
finally:
    os.unlink(tmp)

# 4. translate error path
print("[4/6] translate-error")
r = run(["translate", "Z:/no/such/file.pdf"])
save("translate-error.schema.json", json.loads(r.stdout))

# 5. batch
print("[5/6] batch")
td = tempfile.mkdtemp()
try:
    for i, content in enumerate(["x content\n", "y content\n"]):
        p = Path(td) / f"f{i}.txt"
        p.write_text(content, encoding="utf-8")
    out = tempfile.mkdtemp()
    r = run(["batch", td, "--out", out, "--force", "--workers", "2"])
    save("batch.schema.json", json.loads(r.stdout))
finally:
    import shutil

    shutil.rmtree(td, ignore_errors=True)

# 6. diff
print("[6/6] diff")
td = tempfile.mkdtemp()
try:
    a = Path(td) / "a.txt"
    b = Path(td) / "b.txt"
    a.write_text("a\nb\nc\n", encoding="utf-8")
    b.write_text("a\nB\nc\nd\n", encoding="utf-8")
    r = run(["diff", str(b), str(a)])  # CLI: path_b path_a
    save("diff.schema.json", json.loads(r.stdout))
finally:
    shutil.rmtree(td, ignore_errors=True)

# 7. error code 列表（不依赖 CLI，直接从 core.errors 拉）
print("[7/7] error codes")

codes_doc = {
    "note": "v1.0 错误码冻结——新增只能 append，已有的不能改语义",
    "exit_codes": {k.value: v for k, v in EXIT_CODES.items()},
    "messages_template": {k.value: v for k, v in MESSAGES.items()},
}
(PROTO / "error-codes.json").write_text(
    json.dumps(codes_doc, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print(f"  -> {len(EXIT_CODES)} codes")

print("\nDone. Files in", PROTO)
for p in sorted(PROTO.iterdir()):
    print(f"  {p.name} ({p.stat().st_size} bytes)")
