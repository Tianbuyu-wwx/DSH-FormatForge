"""stdout 协议出口：先钉死编码，再写单行 JSON。

T1-6: 三个出口（`__main__._emit`、`diff._emit_diff`、`batch` 的两处 print）都用
`json.dumps(..., ensure_ascii=False)` 写 `sys.stdout`，而 `sys.stdout` 从来没有
被固定成 UTF-8。Windows 上管道与控制台的默认编码是 locale（本机 cp1252），于是
任何非 ASCII 载荷在**第一行协议 JSON 落地之前**就抛 UnicodeEncodeError ——
调用方拿到的不是转换结果，而是一个 internal(70)：

    $ python -m formatforge translate gbk_chinese.txt --format text
    {"ok": false, "code": 4070, "error": {"kind": "internal",
     "message": "'charmap' codec can't encode character '\\u7b2c' ..."}}

JS 侧的 python-runner 在 `buildChildEnv` 里注入 PYTHONIOENCODING/PYTHONUTF8，
把这个故障盖住了；所以只有直接调用 CLI，以及 pytest 的 `capture_output=True`
子进程，才会踩到它 —— 这正是 test_cli_protocol.py 那批红灯的根因。

契约不变：stdout 仍然只有一行 JSON，仍然 `ensure_ascii=False`。
"""

from __future__ import annotations

import json
import sys
from typing import Any

#: 协议规定的 stdout 编码。JSON 文本本身就是 UTF-8 的，`ensure_ascii=False`
#: 只有在流确实是 UTF-8 时才成立。
PROTOCOL_ENCODING = "utf-8"


def pin_std_streams_utf8() -> None:
    """把 stdin/stdout/stderr 钉到 UTF-8。CLI 入口调用一次，幂等。

    stdin 同属协议面：`--stdin-text` 的调用方（python-runner 的
    `child.stdin.write`）发的是 UTF-8 字节，而 `sys.stdin.read()` 默认按 locale
    解码 —— 不钉的话中文输入会被 cp1252 解成代理对，随后在管线里炸掉。
    这里用 strict：宁可给出一条明确的解码错误，也不要静默的乱码。

    `reconfigure` 只有 TextIOWrapper 才有：pytest 的 capsys、重定向到 StringIO
    的路径都可能没有，缺失时静默跳过（那些路径本来就不经过真实的 locale 编码器）。
    stderr 用 backslashreplace —— 它是人读通道，永远不该因为编码而抛异常，
    把已经写出的诊断信息一起带走。
    """
    for stream, errors in (
        (sys.stdin, "strict"),
        (sys.stdout, "strict"),
        (sys.stderr, "backslashreplace"),
    ):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding=PROTOCOL_ENCODING, errors=errors)
        except (ValueError, OSError, AttributeError):  # pragma: no cover - 非 TextIOWrapper/已分离
            continue


def emit(payload: dict[str, Any]) -> None:
    """stdout 唯一出口：单行协议 JSON。

    即便 `pin_std_streams_utf8()` 没能生效（流被替换成一个不可 reconfigure 的对象，
    且它的编码不是 UTF-8），这里也不允许抛异常：`_fail` 走的就是这条路，
    出口自己抛，进程就会一条协议 JSON 都发不出去。退化为 `ensure_ascii=True`
    的纯 ASCII 形式 —— 内容等价，任何编码都写得出去。
    """
    try:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except UnicodeEncodeError:
        # TextIOWrapper.write 先整体编码再入缓冲，失败时不会留下半行。
        sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()
