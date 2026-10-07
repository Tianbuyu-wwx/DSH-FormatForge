"""
邮件文件解析器
支持 .eml（MIME 格式，使用 Python 标准库 email）和 .msg（Outlook 格式，使用 extract-msg）
"""

import contextlib
import email
import logging
import re
from email.header import decode_header
from pathlib import Path
from typing import Any, cast

from core.models import ExtractedElement, PageContent
from parsers import BaseParser

logger = logging.getLogger("parsers.email")

#: FF-M-email/audit: 附件尺寸统计的物化上限。旧实现无条件
#: `len(part.get_payload(decode=True) or b"")`——为了一个数字把任意大小的附件
#: 完整解码进内存（一封带 2GB 附件的邮件即可拖垮进程）。现在 base64 流式统计
#: 编码字符（零解码、零整串复制），其他 CTE 只有不超过该上限才真正解码；
#: 两条路径超限都只报「≥ 上限」。
ATTACHMENT_SIZE_CAP_BYTES = 8 * 1024 * 1024


def _attachment_size(part: Any, cap: int = ATTACHMENT_SIZE_CAP_BYTES) -> tuple[int, bool]:
    """附件字节数。返回 ``(size, exact)``；``exact=False`` 表示只报下限（超 cap）。"""
    cte = str(part.get("Content-Transfer-Encoding") or "").strip().lower()
    raw = part.get_payload()
    if cte == "base64" and isinstance(raw, str):
        # T3-12: split/rstrip/slice 都会复制接近 FF_MAX_BYTES 的整块字符串。
        # 单次扫描只保留末两个非空白字符；一旦即使扣除最大 padding 也已超 cap，
        # 立即返回下限，既不解码也不继续遍历剩余编码载荷。
        compact_len = 0
        penultimate = last = ""
        for char in raw:
            if char.isspace():
                continue
            compact_len += 1
            penultimate, last = last, char
            if compact_len // 4 * 3 - 2 > cap:
                return cap, False
        padding = int(last == "=") + int(penultimate == "=")
        size = max(0, compact_len // 4 * 3 - padding)
        return (cap, False) if size > cap else (size, True)
    if isinstance(raw, str) and len(raw) > cap:
        return cap, False
    try:
        payload = part.get_payload(decode=True)
    except Exception as e:  # 损坏的 CTE/编码：不因统计尺寸而整封失败
        logger.warning("附件尺寸解析失败: %s", e)
        return 0, False
    if not payload:
        return 0, True
    if len(payload) > cap:
        return cap, False
    return len(payload), True


def _decode_body(payload: bytes, charset: str | None) -> str:
    """按声明字符集解码正文；未知字符集（``LookupError``）回退 utf-8。

    FF-M-email/audit: 头部路径早有该兜底（`_decode_email_header`），但正文路径
    （multipart 与非 multipart 共 4 处）直接把 `get_content_charset()` 交给
    `bytes.decode` —— 声明了未知字符集的邮件会抛 `LookupError`，被 ParseStep 吞掉
    后退化成 raw 透传假成功。
    """
    for candidate in (charset or "utf-8", "utf-8"):
        try:
            return payload.decode(candidate, errors="replace")
        except LookupError:
            logger.info("未知字符集 %r，回退 utf-8", candidate)
            continue
    return payload.decode("latin-1", errors="replace")


# 可选依赖：MSG 解析
try:
    import extract_msg

    MSG_AVAILABLE = True
except ImportError:
    MSG_AVAILABLE = False
    logger.info("extract-msg 库未安装，MSG 文件解析功能不可用")


def _decode_email_header(header_value: str | None) -> str:
    """解码邮件头中的编码文本（如 =?UTF-8?B?5Lit5paH?=）"""
    if not header_value:
        return ""
    try:
        decoded_parts = decode_header(header_value)
        result = []
        for part, charset in decoded_parts:
            if isinstance(part, bytes):
                try:
                    result.append(part.decode(charset or "utf-8", errors="replace"))
                except (LookupError, UnicodeDecodeError):
                    result.append(part.decode("utf-8", errors="replace"))
            else:
                result.append(part)
        return " ".join(result).strip()
    except Exception:
        return header_value


def _extract_text_from_html(html: str) -> str:
    """从 HTML 中提取纯文本"""
    # 去除 script 和 style 块
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # 将 <br> <p> <div> 等替换为换行
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</p>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</div>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</tr>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</li>", "\n", html, flags=re.IGNORECASE)
    # 去掉剩余的 HTML 标签
    text = re.sub(r"<[^>]+>", "", html)
    # 解码 HTML 实体
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&quot;", '"')
    # 合并多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class EmailParser(BaseParser):
    """邮件文件解析器"""

    @property
    def supported_extensions(self) -> list[str]:
        exts = [".eml"]
        if MSG_AVAILABLE:
            exts.append(".msg")
        return exts

    @property
    def supported_magic(self) -> list[bytes]:
        # H18/audit: OLE2 魔数已移除——它属于 .doc/.ppt/.xls/.msg 四种格式且无法
        # 区分，曾在无扩展名/收缩格式上把文件误路由到本解析器。.msg 由扩展名匹配。
        return []

    def parse(self, file_path: Path) -> list[PageContent]:
        """解析邮件文件"""
        file_path = Path(file_path)
        ext = file_path.suffix.lower()

        logger.info("开始解析邮件: %s", file_path)

        if ext == ".eml":
            return self._parse_eml(file_path)
        elif ext == ".msg":
            return self._parse_msg(file_path)
        else:
            raise ValueError(f"不支持的邮件格式: {ext}")

    # ==================== EML 解析 ====================

    def _parse_eml(self, file_path: Path) -> list[PageContent]:
        """解析 .eml 文件"""
        try:
            with open(file_path, "rb") as f:
                msg = email.message_from_binary_file(f)
        except Exception as e:
            logger.error("EML 文件读取失败: %s", e)
            raise ValueError(f"EML 文件读取失败: {e}") from e

        elements: list[ExtractedElement] = []
        raw_lines: list[str] = []
        elem_idx = [0]

        # 1. 邮件头信息
        headers = {
            "from": _decode_email_header(msg.get("From")),
            "to": _decode_email_header(msg.get("To")),
            "subject": _decode_email_header(msg.get("Subject")),
            "date": _decode_email_header(msg.get("Date")),
            "cc": _decode_email_header(msg.get("Cc")),
            "bcc": _decode_email_header(msg.get("Bcc")),
        }

        # 发件人
        if headers["from"]:
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="header",
                    content=f"发件人: {headers['from']}",
                    metadata={"field": "from", "value": headers["from"]},
                )
            )
            raw_lines.append(f"From: {headers['from']}")
            elem_idx[0] += 1

        # 收件人
        if headers["to"]:
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="header",
                    content=f"收件人: {headers['to']}",
                    metadata={"field": "to", "value": headers["to"]},
                )
            )
            raw_lines.append(f"To: {headers['to']}")
            elem_idx[0] += 1

        # 主题
        if headers["subject"]:
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="header",
                    content=f"主题: {headers['subject']}",
                    metadata={"field": "subject", "value": headers["subject"]},
                )
            )
            raw_lines.append(f"Subject: {headers['subject']}")
            elem_idx[0] += 1

        # 日期
        if headers["date"]:
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="header",
                    content=f"日期: {headers['date']}",
                    metadata={"field": "date", "value": headers["date"]},
                )
            )
            raw_lines.append(f"Date: {headers['date']}")
            elem_idx[0] += 1

        # 抄送
        if headers["cc"]:
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="header",
                    content=f"抄送: {headers['cc']}",
                    metadata={"field": "cc", "value": headers["cc"]},
                )
            )
            raw_lines.append(f"CC: {headers['cc']}")
            elem_idx[0] += 1

        # 2. 解析邮件正文 + 附件
        body_text = ""
        body_html = ""
        attachments: list[dict] = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disp = part.get("Content-Disposition", "")

                # 附件
                if "attachment" in content_disp:
                    filename = part.get_filename()
                    if filename:
                        decoded_name = _decode_email_header(filename)
                        size, size_exact = _attachment_size(part)
                        attachments.append(
                            {
                                "filename": decoded_name,
                                "content_type": content_type,
                                "size": size,
                                # FF-M-email/audit: 超过物化上限时 size 只是下限
                                "size_exact": size_exact,
                            }
                        )
                    continue

                # 正文
                if content_type == "text/plain":
                    try:
                        payload = cast(bytes | None, part.get_payload(decode=True))
                        if payload:
                            body_text += _decode_body(payload, part.get_content_charset())
                    except Exception:
                        pass
                elif content_type == "text/html":
                    try:
                        payload = cast(bytes | None, part.get_payload(decode=True))
                        if payload:
                            body_html += _decode_body(payload, part.get_content_charset())
                    except Exception:
                        pass
        else:
            # 非 multipart
            content_type = msg.get_content_type()
            if content_type == "text/plain":
                payload = cast(bytes | None, msg.get_payload(decode=True))
                if payload:
                    body_text = _decode_body(payload, msg.get_content_charset())
            elif content_type == "text/html":
                payload = cast(bytes | None, msg.get_payload(decode=True))
                if payload:
                    body_html = _decode_body(payload, msg.get_content_charset())

        # 3. 输出正文（优先使用纯文本，回退到 HTML 提取）
        final_body = body_text.strip()
        if not final_body and body_html:
            final_body = _extract_text_from_html(body_html)

        if final_body:
            # 将正文按段落拆分
            paragraphs = re.split(r"\n\s*\n", final_body)
            for para in paragraphs:
                para = para.strip()
                if para:
                    elements.append(
                        ExtractedElement(
                            elementId=f"elem_1_{elem_idx[0]}", elementType="text", content=para, metadata={}
                        )
                    )
                    raw_lines.append(para)
                    elem_idx[0] += 1
        else:
            # 无文本内容时添加占位
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}", elementType="text", content="[无正文内容]", metadata={}
                )
            )
            raw_lines.append("[无正文内容]")
            elem_idx[0] += 1

        # 4. 附件摘要
        if attachments:
            att_summary = f"附件 ({len(attachments)} 个): " + ", ".join(
                f"{a['filename']} ({a['size'] // 1024}KB{'' if a.get('size_exact', True) else '+'})"
                for a in attachments
            )
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="text",
                    content=att_summary,
                    metadata={"attachments": attachments},
                )
            )
            raw_lines.append(att_summary)
            elem_idx[0] += 1

        logger.info("EML 解析完成: %d 个元素, %d 个附件", len(elements), len(attachments))

        return [
            PageContent(
                pageNumber=1,
                elements=elements,
                rawText="\n".join(raw_lines),
                hasImage=False,
                hasTable=False,
            )
        ]

    # ==================== MSG 解析 ====================

    def _parse_msg(self, file_path: Path) -> list[PageContent]:
        """解析 .msg 文件"""
        if not MSG_AVAILABLE:
            raise ImportError("extract-msg 库未安装，无法解析 MSG 文件。请执行: pip install extract-msg")

        elements: list[ExtractedElement] = []
        raw_lines: list[str] = []
        elem_idx = [0]

        try:
            msg = extract_msg.Message(str(file_path))
        except Exception as e:
            logger.error("MSG 文件读取失败: %s", e)
            raise ValueError(f"MSG 文件读取失败: {e}") from e

        # 1. 邮件头
        sender = msg.sender or ""
        to = msg.to or ""
        subject = msg.subject or ""
        date = msg.date or ""
        cc = msg.cc or ""

        if sender:
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="header",
                    content=f"发件人: {sender}",
                    metadata={"field": "from", "value": sender},
                )
            )
            raw_lines.append(f"From: {sender}")
            elem_idx[0] += 1

        if to:
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="header",
                    content=f"收件人: {to}",
                    metadata={"field": "to", "value": to},
                )
            )
            raw_lines.append(f"To: {to}")
            elem_idx[0] += 1

        if subject:
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="header",
                    content=f"主题: {subject}",
                    metadata={"field": "subject", "value": subject},
                )
            )
            raw_lines.append(f"Subject: {subject}")
            elem_idx[0] += 1

        if date:
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="header",
                    content=f"日期: {date}",
                    metadata={"field": "date", "value": date},
                )
            )
            raw_lines.append(f"Date: {date}")
            elem_idx[0] += 1

        if cc:
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="header",
                    content=f"抄送: {cc}",
                    metadata={"field": "cc", "value": cc},
                )
            )
            raw_lines.append(f"CC: {cc}")
            elem_idx[0] += 1

        # 2. 正文
        body = msg.body or ""
        if not body.strip():
            html_body = msg.htmlBody or ""
            if html_body:
                body = _extract_text_from_html(cast(str, html_body))

        if body.strip():
            paragraphs = re.split(r"\n\s*\n", body.strip())
            for para in paragraphs:
                para = para.strip()
                if para:
                    elements.append(
                        ExtractedElement(
                            elementId=f"elem_1_{elem_idx[0]}", elementType="text", content=para, metadata={}
                        )
                    )
                    raw_lines.append(para)
                    elem_idx[0] += 1
        else:
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}", elementType="text", content="[无正文内容]", metadata={}
                )
            )
            raw_lines.append("[无正文内容]")
            elem_idx[0] += 1

        # 3. 附件
        attachments: list[dict[str, Any]] = []
        try:
            for att in msg.attachments:
                attachments.append(
                    {
                        "filename": att.longFilename or att.shortFilename or "(unnamed)",
                        # dataSize 缺失/为 None 时按 0（extract-msg 各版本字段不一）
                        "size": int(getattr(att, "dataSize", 0) or 0),
                        "size_exact": True,
                    }
                )
        except Exception:
            pass

        if attachments:
            att_summary = f"附件 ({len(attachments)} 个): " + ", ".join(
                f"{a['filename']} ({a['size'] // 1024}KB)" for a in attachments
            )
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="text",
                    content=att_summary,
                    metadata={"attachments": attachments},
                )
            )
            raw_lines.append(att_summary)
            elem_idx[0] += 1

        # 关闭 MSG 文件
        with contextlib.suppress(Exception):
            msg.close()

        logger.info("MSG 解析完成: %d 个元素, %d 个附件", len(elements), len(attachments))

        return [
            PageContent(
                pageNumber=1,
                elements=elements,
                rawText="\n".join(raw_lines),
                hasImage=False,
                hasTable=False,
            )
        ]
