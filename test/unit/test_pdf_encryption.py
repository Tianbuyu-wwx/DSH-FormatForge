"""
FF-M-pdf/audit 回归测试：加密 PDF 的显式报错 + OCR 临时文件不泄漏。

1. 加密 PDF 此前没有密码路径，被笼统包成 `ValueError`（措辞无稳定标记）→
   ParseStep 吞掉 → ConvertStep 把原始 PDF 字节当 content 返回（error-as-success）。
   现在给出含 `password-protected` 标记的明确错误，ParseStep 上抛，入口报
   parse_failed。
2. `_ocr_page` 的临时 PNG 用 `delete=False` 落盘，此前只在成功路径 unlink →
   OCR 异常即泄漏。现在统一在 finally 清理。

fixture 是测试内用纯标准库手工构造的 RC4-40 加密 PDF（V=1/R=2，用户口令
`secret`），不引入新依赖，也不需要二进制 fixture。
"""

import hashlib
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

pytest.importorskip("pdfplumber")

from parsers.pdf_parser import PDF_PASSWORD_MARKER, PDFParser, _is_password_error, _password_error_detail

#: PDF 标准安全处理器的 32 字节口令填充串（PDF 32000-1 §7.6.3.3）
_PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")


def _rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i], s[j] = s[j], s[i]
    out = bytearray()
    i = j = 0
    for byte in data:
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out.append(byte ^ s[(s[i] + s[j]) & 0xFF])
    return bytes(out)


def _make_encrypted_pdf(path: Path, user_pw: str = "secret", owner_pw: str = "owner") -> None:
    """手工写一个 RC4-40（V=1/R=2）加密的最小 PDF。"""
    user = (user_pw.encode("latin-1") + _PAD)[:32]
    owner = (owner_pw.encode("latin-1") + _PAD)[:32]
    o_val = _rc4(hashlib.md5(owner).digest()[:5], user)
    perm = -1
    id0 = b"\x01" * 16
    enc_key = hashlib.md5(user + o_val + struct.pack("<i", perm) + id0).digest()[:5]
    u_val = _rc4(enc_key, _PAD)

    # 对象 4（内容流）的对象密钥：MD5(文件密钥 + 对象号 + 世代号)[:10]
    obj_key = hashlib.md5(enc_key + struct.pack("<i", 4)[:3] + struct.pack("<i", 0)[:2]).digest()[:10]
    stream = _rc4(obj_key, b"BT /F1 12 Tf 20 100 Td (secret) Tj ET")

    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        4: b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        6: (
            b"<< /Filter /Standard /V 1 /R 2 /O <"
            + o_val.hex().encode()
            + b"> /U <"
            + u_val.hex().encode()
            + b"> /P -1 >>"
        ),
    }

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + objs[num] + b"\nendobj\n"
    xref_pos = len(out)
    out += b"xref\n0 7\n0000000000 65535 f \n"
    for num in sorted(objs):
        out += b"%010d 00000 n \n" % offsets[num]
    out += (
        b"trailer\n<< /Size 7 /Root 1 0 R /Encrypt 6 0 R /ID [<"
        + id0.hex().encode()
        + b"> <"
        + id0.hex().encode()
        + b">] >>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )
    path.write_bytes(bytes(out))


class TestEncryptedPdf:
    def test_parse_raises_password_marker(self, tmp_path):
        pdf = tmp_path / "locked.pdf"
        _make_encrypted_pdf(pdf)
        with pytest.raises(ValueError) as excinfo:
            PDFParser().parse(pdf)
        message = str(excinfo.value)
        assert PDF_PASSWORD_MARKER in message
        assert "已加密" in message
        # 不是笼统的「PDF 解析失败」
        assert not message.startswith("PDF 解析失败")

    def test_stream_parse_also_raises(self, tmp_path):
        """parse_stream 是 parse() 的实现路径，同样不得静默。"""
        pdf = tmp_path / "locked2.pdf"
        _make_encrypted_pdf(pdf)
        with pytest.raises(ValueError) as excinfo:
            list(PDFParser().parse_stream(pdf))
        assert PDF_PASSWORD_MARKER in str(excinfo.value)

    def test_pipeline_reports_parse_failed_not_raw_passthrough(self, tmp_path):
        """端到端：ParseStep 不得吞掉加密错误后把原始 PDF 字节当 content。"""
        from formatforge.__main__ import translate_file_data

        pdf = tmp_path / "locked3.pdf"
        _make_encrypted_pdf(pdf)
        data, code = translate_file_data(pdf, "text", "auto", quality=False)
        assert code != 0, f"加密 PDF 不应成功: {data}"
        assert data.get("kind") == "parse_failed", data
        assert PDF_PASSWORD_MARKER in str(data.get("message", ""))

    def test_detection_helpers(self):
        """包装层（pdfplumber 的 PdfminerException(e)）必须能穿透识别。"""

        class PDFPasswordIncorrect(Exception):
            pass

        class PdfminerException(Exception):
            pass

        wrapped = PdfminerException(PDFPasswordIncorrect())
        assert str(wrapped) == ""  # 包装层自身没有文本 → 只能靠类名
        assert _is_password_error(wrapped) is True
        assert _password_error_detail(wrapped) == "PDFPasswordIncorrect"
        assert _is_password_error(ValueError("Incorrect password")) is True
        assert _is_password_error(ValueError("syntax error at line 3")) is False


class TestOcrTempFileCleanup:
    class _FakeImage:
        def save(self, path, format=None):  # noqa: A002 - 对齐 PIL 签名
            Path(path).write_bytes(b"\x89PNG\r\n\x1a\n fake")

    class _FakePage:
        def to_image(self, resolution=200):
            return TestOcrTempFileCleanup._FakeImage()

    class _ExplodingEngine:
        def extract_text_from_image(self, path, backend=None, apply_postprocess=True):
            assert Path(path).exists(), "OCR 调用时临时文件必须已存在"
            raise RuntimeError("OCR 后端崩溃")

    def test_temp_png_removed_on_ocr_exception(self, tmp_path, monkeypatch):
        from parsers import pdf_parser as module

        created: list[Path] = []
        real_ntf = tempfile.NamedTemporaryFile

        def _factory(*_args, **_kwargs):
            handle = real_ntf(dir=tmp_path, suffix=".png", delete=False)
            created.append(Path(handle.name))
            return handle

        # 用命名空间 shim 替换（避免直接改全局 tempfile → 自递归）
        monkeypatch.setattr(module, "tempfile", type("_TF", (), {"NamedTemporaryFile": staticmethod(_factory)}))

        parser = PDFParser(ocr_engine=self._ExplodingEngine())
        result = parser._ocr_page(self._FakePage(), 1)

        assert created, "未创建临时文件（测试前提失效）"
        assert all(not p.exists() for p in created), f"临时 PNG 泄漏: {[str(p) for p in created]}"
        assert list(tmp_path.glob("*.png")) == []
        # 失败仍返回空 OcrResult（不向上抛）
        assert result.text == ""
        assert result.confidence == 0.0

    def test_temp_png_removed_on_success(self, tmp_path, monkeypatch):
        from parsers import pdf_parser as module

        class _OkEngine:
            def extract_text_from_image(self, path, backend=None, apply_postprocess=True):
                from core.ocr_engine import OcrResult

                return OcrResult(page_number=1, text="ok", confidence=0.9, method="stub")

        created: list[Path] = []
        real_ntf = tempfile.NamedTemporaryFile

        def _factory(*_args, **_kwargs):
            handle = real_ntf(dir=tmp_path, suffix=".png", delete=False)
            created.append(Path(handle.name))
            return handle

        monkeypatch.setattr(module, "tempfile", type("_TF", (), {"NamedTemporaryFile": staticmethod(_factory)}))

        parser = PDFParser(ocr_engine=_OkEngine())
        result = parser._ocr_page(self._FakePage(), 1)

        assert result.text == "ok"
        assert all(not p.exists() for p in created)
