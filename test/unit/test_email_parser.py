"""
邮件解析器单元测试
Eml 测试使用 email 标准库构造真实 EML 文件
MSG 测试验证注册和错误处理（MSG 为二进制 OLE2 格式，不易构造）
"""
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.utils import formatdate
from pathlib import Path
from email import encoders

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.email_parser import EmailParser, MSG_AVAILABLE


def _make_eml(
    subject: str = "测试邮件",
    from_addr: str = "sender@example.com",
    to_addr: str = "recipient@example.com",
    body: str = "邮件正文内容",
    cc: str = "",
    html_body: str = "",
    attachments: list[tuple[str, str, bytes]] | None = None,
) -> str:
    """生成 EML 字符串"""
    if html_body or attachments:
        msg = MIMEMultipart("mixed")
        msg.attach(MIMEText(body, "plain", "utf-8"))
        if html_body:
            msg.attach(MIMEText(html_body, "html", "utf-8"))
    else:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", "utf-8"))

    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Date"] = formatdate(localtime=True)
    if cc:
        msg["Cc"] = cc
    msg["Message-ID"] = "<test123@example.com>"
    msg["MIME-Version"] = "1.0"

    if attachments:
        for filename, content_type, data in attachments:
            part = MIMEBase(*content_type.split("/", 1))
            part.set_payload(data)
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            msg.attach(part)

    return msg.as_string()


class TestEmailParserBasic:
    """基础测试"""

    def test_supported_extensions(self):
        parser = EmailParser()
        assert ".eml" in parser.supported_extensions
        if MSG_AVAILABLE:
            assert ".msg" in parser.supported_extensions
        else:
            assert ".msg" not in parser.supported_extensions

    def test_can_parse_eml(self):
        parser = EmailParser()
        assert parser.can_parse(Path("/tmp/mail.eml")) == 0.9
        if MSG_AVAILABLE:
            assert parser.can_parse(Path("/tmp/mail.msg")) == 0.9

    def test_can_parse_non_email(self):
        parser = EmailParser()
        assert parser.can_parse(Path("/tmp/test.txt")) == 0.0
        assert parser.can_parse(Path("/tmp/test.pdf")) == 0.0


class TestEMLParser:
    """EML 文件解析测试"""

    @pytest.fixture
    def parser(self):
        return EmailParser()

    def _create_eml(self, content: str, tmp_path: Path) -> Path:
        path = tmp_path / "test.eml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_parse_basic_email(self, parser, tmp_path):
        """解析基本邮件"""
        eml = _make_eml(subject="Greeting", from_addr="alice@test.com", to_addr="bob@test.com", body="Hello Bob!")
        path = self._create_eml(eml, tmp_path)
        result = parser.parse(path)
        elements = result[0].elements

        headers = [e for e in elements if e.elementType == "header"]
        assert len(headers) >= 3

        header_map = {h.metadata["field"]: h.metadata["value"] for h in headers}
        assert header_map["from"] == "alice@test.com"
        assert header_map["to"] == "bob@test.com"
        assert header_map["subject"] == "Greeting"

        texts = [e for e in elements if e.elementType == "text"]
        assert any("Hello Bob" in t.content for t in texts)

    def test_parse_with_cc(self, parser, tmp_path):
        """解析含抄送的邮件"""
        eml = _make_eml(subject="Meeting", from_addr="alice@test.com", to_addr="bob@test.com", cc="cc@test.com", body="Reminder")
        path = self._create_eml(eml, tmp_path)
        result = parser.parse(path)

        headers = [h for h in result[0].elements if h.elementType == "header"]
        cc_headers = [h for h in headers if h.metadata["field"] == "cc"]
        assert len(cc_headers) == 1
        assert "cc@test.com" in cc_headers[0].metadata["value"]

    def test_parse_multiple_paragraphs(self, parser, tmp_path):
        """解析多段落正文"""
        body = "第一段。\n\n第二段。\n\n第三段。"
        eml = _make_eml(body=body)
        path = self._create_eml(eml, tmp_path)
        result = parser.parse(path)
        texts = [e for e in result[0].elements if e.elementType == "text"]
        # 正文段落 + 附件摘要
        assert len(texts) >= 3

    def test_parse_html_email(self, parser, tmp_path):
        """解析 HTML-only 邮件（应通过 HTML 提取纯文本）"""
        html = "<html><body><h1>Hello</h1><p>World</p></body></html>"
        eml = _make_eml(html_body=html, body="")
        path = self._create_eml(eml, tmp_path)
        result = parser.parse(path)
        texts = [e for e in result[0].elements if e.elementType == "text"]
        combined = " ".join(t.content for t in texts)
        assert "Hello" in combined
        assert "World" in combined

    def test_parse_with_attachment(self, parser, tmp_path):
        """解析带附件的邮件"""
        attachments = [("report.pdf", "application/pdf", b"%PDF-1.4 fake content")]
        eml = _make_eml(attachments=attachments)
        path = self._create_eml(eml, tmp_path)
        result = parser.parse(path)
        texts = [e for e in result[0].elements if e.elementType == "text"]
        combined = " ".join(t.content for t in texts)
        assert "附件" in combined
        assert "report.pdf" in combined

    def test_parse_encoded_subject(self, parser, tmp_path):
        """解析编码主题（=?UTF-8?B?...?=）"""
        from email.header import Header
        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header("中文主题", "utf-8")
        msg["From"] = "a@b.com"
        msg["To"] = "c@d.com"
        msg["Date"] = formatdate(localtime=True)
        msg.attach(MIMEText("测试", "plain", "utf-8"))
        path = self._create_eml(msg.as_string(), tmp_path)

        result = parser.parse(path)
        headers = [h for h in result[0].elements if h.elementType == "header" and h.metadata["field"] == "subject"]
        assert len(headers) == 1
        assert "中文主题" in headers[0].content

    def test_parse_empty_body(self, parser, tmp_path):
        """解析无正文邮件"""
        eml = _make_eml(body="")
        path = self._create_eml(eml, tmp_path)
        result = parser.parse(path)
        texts = [e for e in result[0].elements if e.elementType == "text"]
        # 应生成占位
        combined = " ".join(t.content for t in texts)
        assert "无正文内容" in combined

    def test_parse_multiple_attachments(self, parser, tmp_path):
        """解析多个附件"""
        attachments = [
            ("a.txt", "text/plain", b"hello"),
            ("b.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"fake docx"),
        ]
        eml = _make_eml(attachments=attachments)
        path = self._create_eml(eml, tmp_path)
        result = parser.parse(path)
        texts = [e for e in result[0].elements if e.elementType == "text"]
        combined = " ".join(t.content for t in texts)
        assert "2 个" in combined
        assert "a.txt" in combined
        assert "b.docx" in combined


class TestEMLParserEncoding:
    """EML 编码处理测试"""

    @pytest.fixture
    def parser(self):
        return EmailParser()

    def _make_eml_bytes(self, content: bytes, tmp_path: Path) -> Path:
        path = tmp_path / "encoded.eml"
        path.write_bytes(content)
        return path

    def test_parse_utf8_bom_subject(self, parser, tmp_path):
        """UTF-8 BOM 编码主题"""
        from email.header import Header
        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header("UTF-8主题", "utf-8")
        msg["From"] = "x@y.com"
        msg["To"] = "a@b.com"
        msg["Date"] = formatdate(localtime=True)
        msg.attach(MIMEText("正文", "plain", "utf-8"))

        path = tmp_path / "utf8.eml"
        path.write_text(msg.as_string(), encoding="utf-8")

        result = parser.parse(path)
        subjects = [h for h in result[0].elements if h.elementType == "header" and h.metadata["field"] == "subject"]
        assert len(subjects) == 1
        assert "UTF-8" in subjects[0].content or "主题" in subjects[0].content


class TestMSGNotAvailable:
    """MSG 不可用时的降级测试"""

    def test_msg_extension_not_available(self):
        if not MSG_AVAILABLE:
            parser = EmailParser()
            assert ".msg" not in parser.supported_extensions
            assert b"\xd0\xcf\x11\xe0" not in parser.supported_magic


class TestEmailParserErrors:
    """异常情况测试"""

    @pytest.fixture
    def parser(self):
        return EmailParser()

    def test_not_an_email(self, parser, tmp_path):
        """非邮件文件"""
        path = tmp_path / "test.eml"
        path.write_text("这不是一个邮件文件", encoding="utf-8")
        result = parser.parse(path)
        assert len(result) == 1
        assert result[0].rawText != ""

    def test_unsupported_format(self, parser, tmp_path):
        """不支持的扩展名"""
        path = tmp_path / "test.pdf"
        path.write_text("dummy", encoding="utf-8")
        with pytest.raises(ValueError, match="不支持的邮件格式"):
            parser.parse(path)