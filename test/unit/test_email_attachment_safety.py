"""
FF-M-email/audit 回归测试：附件尺寸不再物化整块内容 + 未知字符集不再炸正文。

审计发现（Medium 行 79）：
- 附件只为了一个字节数就 `len(part.get_payload(decode=True) or b"")` —— 把任意
  大小的附件完整解码进内存（带大附件的邮件可拖垮进程）。
  现在 base64 按编码长度换算（零解码），其他 CTE 超过上限只报下限。
- 正文解码把 `get_content_charset()` 直接交给 `bytes.decode` → 未知字符集抛
  `LookupError`，被 ParseStep 吞掉后退化成 raw 透传假成功。
"""

import base64
import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from parsers.email_parser import (
    ATTACHMENT_SIZE_CAP_BYTES,
    EmailParser,
    _attachment_size,
    _decode_body,
)


class _FakePart:
    """最小 MIME part 替身（只有 _attachment_size 需要的两个接口）。"""

    def __init__(self, payload, cte=None, *, explode=False):
        self._payload = payload
        self._cte = cte
        self._explode = explode
        self.decode_calls = 0

    def get(self, header, default=None):
        if header == "Content-Transfer-Encoding":
            return self._cte
        return default

    def get_payload(self, decode=False):
        if not decode:
            return self._payload
        self.decode_calls += 1
        if self._explode:
            raise ValueError("损坏的 CTE")
        return base64.b64decode(self._payload) if self._cte == "base64" else self._payload.encode()


class _VirtualBase64(str):
    """Near-limit str without a near-limit allocation; traps known full-copy operations."""

    def __new__(cls, encoded_length):
        obj = super().__new__(cls, "A")
        obj.encoded_length = encoded_length
        return obj

    def __len__(self):
        return self.encoded_length

    def __iter__(self):
        return itertools.repeat("A", self.encoded_length)

    def split(self, *_args, **_kwargs):
        raise AssertionError("base64 payload must not be split into copies")

    def rstrip(self, *_args, **_kwargs):
        raise AssertionError("base64 payload must not be copied by rstrip")

    def __getitem__(self, key):
        if isinstance(key, slice):
            raise AssertionError("base64 payload must not be sliced")
        return super().__getitem__(key)


class TestAttachmentSize:
    def test_base64_size_without_decoding(self):
        raw = base64.b64encode(b"x" * 3000).decode()
        part = _FakePart(raw, "base64")
        size, exact = _attachment_size(part)
        assert size == 3000
        assert exact is True
        assert part.decode_calls == 0, "base64 路径不得调用 get_payload(decode=True)"

    def test_base64_padding_is_accounted_for(self):
        for n in (1, 2, 3, 4, 5):
            raw = base64.b64encode(b"y" * n).decode()
            size, exact = _attachment_size(_FakePart(raw, "base64"))
            assert (size, exact) == (n, True), n

    def test_base64_with_line_breaks(self):
        raw = "\r\n".join(base64.b64encode(b"z" * 1000).decode()[i : i + 76] for i in range(0, 1340, 76))
        size, exact = _attachment_size(_FakePart(raw, "base64"))
        assert size == 1000
        assert exact is True

    def test_near_file_limit_base64_is_capped_without_copying(self):
        """T3-12: code-path proof only; this does not measure peak RSS."""
        from core.config import settings

        raw = _VirtualBase64(settings.FF_MAX_BYTES - 1)
        part = _FakePart(raw, "base64")
        assert _attachment_size(part) == (ATTACHMENT_SIZE_CAP_BYTES, False)
        assert part.decode_calls == 0

    def test_large_8bit_attachment_reports_lower_bound_only(self):
        part = _FakePart("a" * (ATTACHMENT_SIZE_CAP_BYTES + 10), "8bit")
        size, exact = _attachment_size(part)
        assert size == ATTACHMENT_SIZE_CAP_BYTES
        assert exact is False
        assert part.decode_calls == 0, "超限附件不得被解码"

    def test_small_8bit_attachment_is_exact(self):
        part = _FakePart("hello", "8bit")
        assert _attachment_size(part) == (5, True)

    def test_broken_payload_does_not_kill_the_parse(self):
        size, exact = _attachment_size(_FakePart("boom", "x-unknown", explode=True))
        assert (size, exact) == (0, False)


class TestDecodeBody:
    def test_unknown_charset_falls_back_to_utf8(self):
        text = _decode_body("中文".encode(), "x-not-a-real-charset")
        assert text == "中文"

    def test_none_charset_uses_utf8(self):
        assert _decode_body("abc".encode(), None) == "abc"

    def test_declared_charset_is_honoured(self):
        assert _decode_body("中文".encode("gbk"), "gbk") == "中文"

    def test_invalid_bytes_are_replaced_not_raised(self):
        assert _decode_body(b"\xff\xfe\x00bad", "utf-8") != ""


class TestEndToEnd:
    def test_eml_with_unknown_charset_and_big_attachment(self, tmp_path):
        payload = base64.b64encode(b"A" * 100).decode()
        eml = (
            "From: a@example.com\r\n"
            "To: b@example.com\r\n"
            "Subject: =?x-unknown-charset?B?5Lit5paH?=\r\n"
            "MIME-Version: 1.0\r\n"
            'Content-Type: multipart/mixed; boundary="BOUND"\r\n'
            "\r\n"
            "--BOUND\r\n"
            "Content-Type: text/plain; charset=x-not-a-real-charset\r\n"
            "Content-Transfer-Encoding: base64\r\n"
            "\r\n" + base64.b64encode("正文中文".encode()).decode() + "\r\n"
            "--BOUND\r\n"
            'Content-Type: application/octet-stream; name="big.bin"\r\n'
            "Content-Transfer-Encoding: base64\r\n"
            'Content-Disposition: attachment; filename="big.bin"\r\n'
            "\r\n" + payload + "\r\n"
            "--BOUND--\r\n"
        )
        path = tmp_path / "sample.eml"
        # 必须二进制写入：Windows 文本模式会把 \n 再翻成 \r\n，把 CRLF 变成 \r\r\n，
        # 邮件头解析随即错位（同一个坑在 fixture 层踩一次就够了）。
        path.write_bytes(eml.encode("utf-8"))

        pages = EmailParser().parse(path)
        assert pages, "解析不得因未知字符集而失败"
        raw = pages[0].rawText
        assert "正文中文" in raw
        assert "big.bin" in raw
        att = None
        for el in pages[0].elements:
            if el.metadata and "attachments" in el.metadata:
                att = el.metadata["attachments"][0]
        assert att is not None
        assert att["size"] == 100
        assert att["size_exact"] is True
