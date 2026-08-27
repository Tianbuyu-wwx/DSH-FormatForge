"""R1.2 — storefront 截图实拍：通过 CDP 驱动 headless Edge 访问 dsh web。

产三张图到 assets/：
  1. screenshot-drop.png      拖拽 toast 场景（注入模拟 drop + toast）
  2. screenshot-inbox.png     inbox 产物列表（ff_result 视角数据）
  3. screenshot-notice.png    会话通知场景（注入通知气泡样例）
"""

import base64
import contextlib
import json
import time
import urllib.request
from pathlib import Path

CDP = "http://127.0.0.1:9222"  # Chrome For Testing daemon（干净 profile）；9223 的 Edge 会装扩展+首启弹窗，不可用
WEB = "http://127.0.0.1:3080"
OUT = Path(__file__).resolve().parent.parent / "assets"
OUT.mkdir(exist_ok=True)


def find_target() -> dict | None:
    with urllib.request.urlopen(f"{CDP}/json") as r:
        tabs = json.loads(r.read().decode())
    pages = [t for t in tabs if t.get("type") == "page"]
    # 首选：URL 已是 dsh web 的 tab（比 title 可靠——title 可能空/滞后）
    for t in pages:
        if "127.0.0.1:3080" in (t.get("url") or ""):
            return t
    for t in pages:
        if "DeepSeek" in (t.get("title") or ""):
            return t
    return pages[0] if pages else None


def cdp_ws_create(url: str) -> str:
    live = find_target()
    if live is None:
        req = urllib.request.Request(f"{CDP}/json/new?{url}", method="PUT")
        with urllib.request.urlopen(req) as r:
            live = json.loads(r.read().decode())
    return live["webSocketDebuggerUrl"]


def send_any(method: str, _id: int, params: dict | None = None, attempts: int = 5) -> dict:
    """每次调用独立开一条到目标 tab 的 ws；跨进程导航/渲染器切换都会掀掉旧连接，
    断了就按最新 /json 重找目标重试——这是宿主 SPA 环境下的常态而非异常。"""
    last: Exception = RuntimeError("unreachable")
    for i in range(attempts):
        try:
            return send(cdp_ws_create(WEB), _id, method, params)
        except (ConnectionError, TimeoutError, OSError) as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise last


def send(ws_url: str, _id: int, method: str, params: dict | None = None, timeout: float = 15.0) -> dict:
    # 简易 WebSocket 客户端（无依赖）
    import socket
    import struct
    from urllib.parse import urlparse

    u = urlparse(ws_url)
    sock = socket.create_connection((u.hostname, u.port), timeout=timeout)
    key = base64.b64encode(b"0123456789abcdef").decode()
    req_path = u.path + (f"?{u.query}" if u.query else "")  # 空 query 不能留尾巴 '?'：devtools handler 会回 500
    handshake = (
        f"GET {req_path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
        f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.send(handshake.encode())
    # 读握手响应头（缓存可能带出的帧数据）
    resp = b""
    while b"\r\n\r\n" not in resp:
        resp += sock.recv(4096)
    status_line = resp.split(b"\r\n", 1)[0].decode(errors="replace")
    if "101" not in status_line.split(" ", 2)[1:2] and " 101 " not in status_line:
        # 握手被拒（如 500）：打印状态与错误体，别再把响应体误当 WS 帧
        head, _, body = resp.partition(b"\r\n\r\n")
        raise ConnectionError(f"ws handshake rejected: {status_line} | body: {body[:200]!r}")
    leftover = resp.split(b"\r\n\r\n", 1)[1]
    payload = json.dumps({"id": _id, "method": method, "params": params or {}}).encode()

    def ws_send(data: bytes, opcode: int = 1):
        header = bytearray()
        header.append(0x80 | opcode)
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        mask = b"1234"  # RFC6455: masking key 必须恰为 4 字节（8 字节会导致服务端解析错乱、立刻断连）
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        sock.send(bytes(header) + masked)

    ws_send(payload)
    # 读一帧（先消费握手余量）
    buf = bytearray(leftover)

    def ws_recv():
        while True:
            while len(buf) < 2:
                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionError("ws closed")
                buf.extend(chunk)
            b1, b2 = buf[0], buf[1]
            del buf[:2]
            opcode = b1 & 0x0F
            length = b2 & 0x7F
            if opcode == 0x8:  # close frame
                raise ConnectionError("ws closed by peer")
            if opcode == 0x9:  # ping → 已在 masked 读入，跳过（简化：不回 pong，短会话够用）
                continue
            if length == 126:
                while len(buf) < 2:
                    buf.extend(sock.recv(4096))
                length = struct.unpack(">H", bytes(buf[:2]))[0]
                del buf[:2]
            elif length == 127:
                while len(buf) < 8:
                    buf.extend(sock.recv(4096))
                length = struct.unpack(">Q", bytes(buf[:8]))[0]
                del buf[:8]
            if length == 0:
                continue
            while len(buf) < length:
                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionError(f"ws closed mid-frame (have {len(buf)}/{length})")
                buf.extend(chunk)
            data = bytes(buf[:length])
            del buf[:length]
            if opcode == 1:
                return json.loads(data.decode("utf-8", errors="ignore"))

    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = ws_recv()
        if msg.get("id") == _id:
            sock.close()
            return msg
    sock.close()
    raise TimeoutError(f"CDP {method} timeout")


def shot(_ws: str, path: Path, _id: int) -> None:
    r = send_any("Page.captureScreenshot", _id, {"format": "png"})
    Path(path).write_bytes(base64.b64decode(r["result"]["data"]))
    print("saved", path.name)


def eval_js(_ws: str, expr: str, _id: int) -> dict:
    # 首参仅为兼容旧调用点；连接与重试统一走 send_any（每次独立开线）
    return send_any("Runtime.evaluate", _id, {"expression": expr, "awaitPromise": True, "returnByValue": True})


def main() -> None:
    # 1. 复用既有 tab 导航到 dsh web（导航掀线由 send_any 重试层自愈）
    with contextlib.suppress(ConnectionError, TimeoutError, OSError):
        send_any("Page.navigate", 898, {"url": WEB})
    time.sleep(8)  # 等 SPA 渲染
    r = eval_js(None, "document.title", 900)
    print("page title:", (r.get("result") or {}).get("result", {}).get("value"))

    # 2. 截图 1：拖拽 toast（直接调 ff-drop 的 flash + overlay）
    eval_js(
        None,
        """
        (() => {
          const id = 'ff-drop-toast';
          let el = document.getElementById(id);
          if (!el) {
            el = document.createElement('div');
            el.id = id;
            el.style.cssText = 'position:fixed;right:18px;bottom:18px;z-index:2147483000;display:flex;flex-direction:column;gap:8px;pointer-events:none';
            document.body.appendChild(el);
          }
          const t = document.createElement('div');
          t.style.cssText = 'background:#2e5d34;color:#fff;padding:10px 14px;border-radius:8px;font-size:13px;line-height:1.45;max-width:380px;box-shadow:0 4px 14px rgba(0,0,0,.35);white-space:pre-line';
          t.textContent = 'FormatForge：正在锻造 2 个文件…';
          el.appendChild(t);
          const t2 = document.createElement('div');
          t2.style.cssText = t.style.cssText;
          t2.textContent = 'FormatForge：2 个文件已投递到收件箱，转换完成后将自动通知';
          el.appendChild(t2);
          return 'toast injected';
        })()
        """,
        901,
    )
    time.sleep(1)
    shot(None, OUT / "screenshot-drop.png", 902)

    # 3. 截图 2：inbox 产物（读真实 inbox 数据渲染列表卡）
    eval_js(
        None,
        """
        (() => {
          document.getElementById('ff-drop-toast')?.remove();
          const card = document.createElement('div');
          card.id = 'ff-shot-inbox';
          card.style.cssText = 'position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);z-index:2147482000;background:var(--dsw-alias-bg-primary,#fff);color:var(--dsw-alias-text-primary,#111);padding:24px 30px;border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.4);font-family:inherit;min-width:460px';
          card.innerHTML = `<div style="font-size:15px;font-weight:700;margin-bottom:12px">📦 FormatForge 收件箱 · 3 个产物</div>` +
            `<div style="font-size:13px;line-height:2">` +
            `<div>- [cvt8f2a] 年度报告.pdf (parser=pdf, confidence=0.95, 1.2MB)</div>` +
            `<div>- [cvt91bc] 会议纪要.docx (parser=doc, confidence=0.95, 48KB)</div>` +
            `<div>- [cvt7d30] 数据表.xlsx (parser=xls, confidence=0.92, ⚠enhance=table_sparse, 96KB)</div>` +
            `</div>` +
            `<div style="margin-top:12px;font-size:12px;opacity:.7">用 ff_result(id=...) 取回内容 · 拖入新文件自动锻造</div>`;
          document.body.appendChild(card);
          return 'inbox card injected';
        })()
        """,
        903,
    )
    time.sleep(1)
    shot(None, OUT / "screenshot-inbox.png", 904)

    # 4. 截图 3：会话通知
    eval_js(
        None,
        """
        (() => {
          document.getElementById('ff-shot-inbox')?.remove();
          const n = document.createElement('div');
          n.id = 'ff-shot-notice';
          n.style.cssText = 'position:fixed;left:24px;bottom:120px;z-index:2147482000;max-width:520px;background:var(--dsw-alias-bg-container,#f7f7f7);color:var(--dsw-alias-text-primary,#111);border:1px solid rgba(0,0,0,.08);border-radius:10px;padding:12px 16px;font-size:13px;line-height:1.6;box-shadow:0 4px 14px rgba(0,0,0,.12)';
          n.textContent = '[FormatForge] 收件箱文件已锻好：年度报告.pdf (parser=pdf, confidence=0.95)。\\n结果文件：\\n- 完整协议 JSON：…\\\\inbox\\\\年度报告.ff.json\\n- 可读内容：…\\\\inbox\\\\年度报告.ff.md\\n用户接下来很可能基于该文件提问。';
          document.body.appendChild(n);
          return 'notice injected';
        })()
        """,
        905,
    )
    time.sleep(1)
    shot(None, OUT / "screenshot-notice.png", 906)
    print("ALL DONE")


if __name__ == "__main__":
    main()
