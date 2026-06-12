"""
安全模块
文件类型白名单、URL域名白名单、敏感信息脱敏等
"""
import logging
import re
from pathlib import Path

logger = logging.getLogger("security")

# ==================== 文件类型白名单 ====================

# 允许的文件扩展名白名单
ALLOWED_EXTENSIONS: set[str] = {
    # 文档
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".txt", ".rtf", ".md",
    # 表格
    ".xls", ".xlsx", ".csv", ".tsv",
    # 图片
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif",
    # 数据
    ".json", ".yaml", ".yml", ".xml", ".html", ".htm",
    # 压缩包
    ".zip", ".7z", ".rar",
    # 其他
    ".epub", ".log",
}

# 允许的 MIME 类型白名单
ALLOWED_MIME_TYPES: set[str] = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain", "text/csv", "text/markdown", "text/html",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/png", "image/jpeg", "image/gif", "image/bmp", "image/webp", "image/tiff",
    "application/json", "application/xml", "application/yaml",
    "application/zip", "application/x-7z-compressed", "application/x-rar",
    "application/rtf",
    "application/epub+zip",
}


def validate_file_extension(filename: str) -> bool:
    """
    验证文件扩展名是否在白名单中

    Args:
        filename: 文件名

    Returns:
        bool: 是否合法
    """
    ext = Path(filename).suffix.lower()
    is_allowed = ext in ALLOWED_EXTENSIONS
    if not is_allowed:
        logger.warning("文件扩展名不在白名单中: %s (ext=%s)", filename, ext)
    return is_allowed


def validate_mime_type(mime_type: str | None) -> bool:
    """
    验证 MIME 类型是否在白名单中

    Args:
        mime_type: MIME 类型

    Returns:
        bool: 是否合法
    """
    if not mime_type:
        return True  # 无 MIME 类型时不拦截
    is_allowed = mime_type.lower() in ALLOWED_MIME_TYPES
    if not is_allowed:
        logger.warning("MIME 类型不在白名单中: %s", mime_type)
    return is_allowed


# ==================== URL 域名白名单 ====================

# 允许下载的域名白名单（空列表表示不做限制，仅阻止已知危险域名）
ALLOWED_DOMAINS: list[str] = []  # 例如: ["example.com", "cdn.example.com"]

# 明确禁止的域名（防止 SSRF 攻击）
BLOCKED_DOMAINS: set[str] = {
    "localhost", "127.0.0.1", "0.0.0.0",
    "169.254.169.254",  # AWS/阿里云元数据
    "metadata.google.internal",
    "100.100.100.200",  # 阿里云元数据
}

# 禁止的内网 IP 段
BLOCKED_PRIVATE_RANGES: list[str] = [
    "10.", "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.",
    "172.24.", "172.25.", "172.26.", "172.27.",
    "172.28.", "172.29.", "172.30.", "172.31.",
    "192.168.",
]


def validate_url_domain(url: str) -> bool:
    """
    验证 URL 域名是否允许下载（防止 SSRF）

    Args:
        url: 完整的 URL

    Returns:
        bool: 是否允许
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        hostname = parsed.hostname.lower() if parsed.hostname else ""
    except Exception:
        logger.warning("URL 解析失败: %s", url)
        return False

    # 检查被禁止的域名
    if hostname in BLOCKED_DOMAINS:
        logger.warning("URL 域名在禁止列表中: %s", url)
        return False

    # 检查内网 IP 段
    if hostname and hostname.replace(".", "").isdigit():  # 是 IP 地址
        for prefix in BLOCKED_PRIVATE_RANGES:
            if hostname.startswith(prefix):
                logger.warning("URL 指向内网地址: %s (匹配: %s)", url, prefix)
                return False

    # 如果设置了域名白名单且非空，检查是否在白名单中
    if ALLOWED_DOMAINS:
        is_allowed = any(
            hostname == domain or hostname.endswith("." + domain)
            for domain in ALLOWED_DOMAINS
        )
        if not is_allowed:
            logger.warning("URL 域名不在白名单中: %s", url)
            return False

    return True


# ==================== 敏感信息脱敏 ====================

SENSITIVE_PATTERNS: list[str] = [
    r'(api[_-]?key["\']?\s*[:=]\s*["\']?)([^"\'\s,;}]+)',
    r'(api[_-]?secret["\']?\s*[:=]\s*["\']?)([^"\'\s,;}]+)',
    r'(secret["\']?\s*[:=]\s*["\']?)([^"\'\s,;}]+)',
    r'(token["\']?\s*[:=]\s*["\']?)([^"\'\s,;}]+)',
    r'(password["\']?\s*[:=]\s*["\']?)([^"\'\s,;}]+)',
    r'(auth["\']?\s*[:=]\s*["\']?)([^"\'\s,;}]+)',
    r'(authorization["\']?\s*[:=]\s*["\']?)([^"\'\s,;}]+)',
    r'(Bearer\s+)([A-Za-z0-9\-._~+/]{8,})',
    r'(sk-[A-Za-z0-9]{20,})',
    r'(sk-cp-[A-Za-z0-9]{20,})',
]


def mask_sensitive_info(text: str) -> str:
    """
    脱敏敏感信息（如 API Key、密码等）

    Args:
        text: 原始文本（如日志）

    Returns:
        str: 脱敏后的文本
    """
    result = text
    for pattern in SENSITIVE_PATTERNS:
        result = re.sub(
            pattern,
            lambda m: m.group(1) + "***" + m.group(2)[-4:] if len(m.groups()) >= 2 and len(m.group(2)) > 4
            else "***",
            result,
            flags=re.IGNORECASE
        )
    return result


class SensitiveDataFilter(logging.Filter):
    """日志过滤器 - 自动脱敏日志中的敏感信息"""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_sensitive_info(record.msg)
        if record.args:
            record.args = tuple(
                mask_sensitive_info(str(arg)) if isinstance(arg, str) else arg
                for arg in record.args
            )
        return True


# ==================== 路径遍历防护 ====================

def validate_path_safety(file_path: str, base_dir: Path) -> bool:
    """
    验证文件路径是否安全（防止路径遍历攻击）

    Args:
        file_path: 待验证的文件路径
        base_dir: 基准目录（所有文件必须在此目录下）

    Returns:
        bool: 是否安全
    """
    try:
        resolved = Path(file_path).resolve()
        base_resolved = base_dir.resolve()
        is_safe = str(resolved).startswith(str(base_resolved))
        if not is_safe:
            logger.warning("路径遍历攻击检测: %s (不在基准目录 %s 下)",
                           resolved, base_resolved)
        return is_safe
    except Exception as e:
        logger.warning("路径验证异常: %s, error=%s", file_path, e)
        return False
