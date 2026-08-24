"""
安全模块
文件类型白名单、URL域名白名单、敏感信息脱敏等
"""

import logging
import re
from pathlib import Path

from core.format_detector import EXTENSION_MAP

logger = logging.getLogger("security")

# ==================== 文件类型白名单 ====================

# 允许的文件扩展名白名单（从 EXTENSION_MAP 自动生成）
# 额外添加一些历史兼容格式（.doc/.xls 等）
_ALLOWED_BASE: set[str] = set(EXTENSION_MAP.keys())

# 额外允许但不在检测映射中的扩展名（出于安全验证的兼容性）
_ADDITIONAL_EXTENSIONS: set[str] = {
    ".doc",  # 旧版 Word
    ".xls",  # 旧版 Excel
    ".log",  # 日志文件
}

ALLOWED_EXTENSIONS: set[str] = _ALLOWED_BASE | _ADDITIONAL_EXTENSIONS

# 允许的 MIME 类型白名单（从 EXTENSION_MAP 自动生成）
_ALLOWED_MIME_BASE: set[str] = {mime for _, mime in EXTENSION_MAP.values()}

# 额外允许的 MIME 类型
_ADDITIONAL_MIME_TYPES: set[str] = {
    "application/msword",
    "application/vnd.ms-powerpoint",
    "application/vnd.ms-excel",
    "application/x-rar",
    "application/rtf",
}

ALLOWED_MIME_TYPES: set[str] = _ALLOWED_MIME_BASE | _ADDITIONAL_MIME_TYPES


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
        logger.warning("MIME 类型为空，拒绝访问")
        return False  # 无 MIME 类型时拦截（安全加固）
    is_allowed = mime_type.lower() in ALLOWED_MIME_TYPES
    if not is_allowed:
        logger.warning("MIME 类型不在白名单中: %s", mime_type)
    return is_allowed


# ==================== URL 域名白名单 ====================

# 允许下载的域名白名单（空列表表示不做限制，仅阻止已知危险域名）
ALLOWED_DOMAINS: list[str] = []  # 例如: ["example.com", "cdn.example.com"]

# 允许的 URL scheme 白名单
ALLOWED_URL_SCHEMES: set[str] = {"http", "https"}

# 明确禁止的域名（防止 SSRF 攻击）
BLOCKED_DOMAINS: set[str] = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "169.254.169.254",  # AWS/阿里云元数据
    "metadata.google.internal",
    "100.100.100.200",  # 阿里云元数据
}


def _resolve_and_check_ip(hostname: str) -> bool:
    """
    解析域名并检查是否指向内网地址。
    使用 socket.getaddrinfo 做 DNS 解析 + ipaddress 模块做内网检测。

    Returns:
        True 如果安全（非内网），False 如果应阻止
    """
    import ipaddress
    import socket

    # 先尝试直接用 ipaddress 解析 hostname（处理标准 IPv4/IPv6 字面量）
    try:
        addr = ipaddress.ip_address(hostname)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast:
            logger.warning("URL 指向内网地址: %s", hostname)
            return False
        if addr.is_private is False and addr.is_global is False:
            logger.warning("URL 指向保留地址: %s", hostname)
            return False
        # IP 直接解析成功且非内网 → 安全
        return True
    except ValueError:
        pass  # 不是标准 IP 字面量，继续走 DNS 解析

    # 尝试解析 obfuscated IP（整数 IP、单字节 IP 等）
    # 在 Windows 上 socket.getaddrinfo 不处理这些，所以先手动尝试
    try:
        resolved = _try_parse_obfuscated_ip(hostname)
        if resolved is not None:
            addr = ipaddress.ip_address(resolved)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast:
                logger.warning("URL 指向内网地址(obfuscated): %s -> %s", hostname, resolved)
                return False
            if addr.is_private is False and addr.is_global is False:
                logger.warning("URL 指向保留地址(obfuscated): %s -> %s", hostname, resolved)
                return False
            return True
    except Exception:
        pass

    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, OSError):
        # DNS 解析失败 — 允许（后续请求时会失败）
        return True

    for _family, _, _, _, sockaddr in addrinfo:
        ip_str = sockaddr[0]
        try:
            addr = ipaddress.ip_address(ip_str)
            if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast:
                logger.warning("URL 指向内网地址: %s -> %s", hostname, ip_str)
                return False
            # 检查保留地址 (100.64.0.0/10 等)
            if addr.is_private is False and addr.is_global is False:
                logger.warning("URL 指向保留地址: %s -> %s", hostname, ip_str)
                return False
        except ValueError:
            continue

    return True


def _try_parse_obfuscated_ip(hostname: str) -> str | None:
    """
    尝试解析 obfuscated IP 地址到标准 IPv4 字符串。
    处理：整数 IP (2130706433)、单字节/多字节 (127.1)、十六进制、混合格式。

    Returns:
        标准 IP 字符串 (如 "127.0.0.1") 或 None
    """
    import socket
    import struct

    # 1. 纯数字 → 整数 IP
    if hostname.isdigit():
        try:
            n = int(hostname)
            if n > 0xFFFFFFFF:
                return None
            return socket.inet_ntoa(struct.pack("!I", n))
        except (ValueError, OSError):
            return None

    # 2. 十六进制（0x 开头）
    if hostname.startswith("0x"):
        try:
            n = int(hostname, 16)
            if n > 0xFFFFFFFF:
                return None
            return socket.inet_ntoa(struct.pack("!I", n))
        except (ValueError, OSError):
            return None

    # 3. 八进制（0 开头但不含点号）
    if hostname.startswith("0") and len(hostname) > 1 and hostname[1].isdigit() and "." not in hostname:
        try:
            n = int(hostname, 8)
            if n > 0xFFFFFFFF:
                return None
            return socket.inet_ntoa(struct.pack("!I", n))
        except (ValueError, OSError):
            return None

    # 4. 点分十进制但不标准（如 127.1 = 127.0.0.1）
    parts = hostname.split(".")
    if 2 <= len(parts) <= 3:
        try:
            nums = [int(p) for p in parts]
            if any(n < 0 or n > 0xFFFFFFFF for n in nums):
                return None
            if len(parts) == 2:
                # a.b = (a << 24) | (b)
                val = (nums[0] << 24) | nums[1]
            elif len(parts) == 3:
                # a.b.c = (a << 24) | (b << 16) | c
                val = (nums[0] << 24) | (nums[1] << 16) | nums[2]
            if val > 0xFFFFFFFF:
                return None
            return socket.inet_ntoa(struct.pack("!I", val))
        except (ValueError, OSError):
            return None

    return None


def validate_url_domain(url: str) -> bool:
    """
    验证 URL 域名是否允许下载（防止 SSRF 攻击）

    检查项：
    1. URL scheme 白名单（不允许 file:/// 等）
    2. 域名黑名单（阻止 localhost/127.0.0.1/169.254.169.254 等）
    3. IP 地址解析后 ipaddress 库内网检测
    4. 域名白名单（如果设置）

    Args:
        url: 完整的 URL

    Returns:
        bool: 是否允许
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname.lower() if parsed.hostname else ""
    except Exception:
        logger.warning("URL 解析失败: %s", url)
        return False

    # 1. Scheme 白名单
    if scheme not in ALLOWED_URL_SCHEMES:
        logger.warning("URL scheme 不在白名单: %s (scheme=%s)", url, scheme)
        return False

    if not hostname:
        logger.warning("URL 缺少 hostname: %s", url)
        return False

    # 2. 检查被禁止的域名
    if hostname in BLOCKED_DOMAINS:
        logger.warning("URL 域名在禁止列表中: %s", url)
        return False

    # 3. 检查内网 IP 段 (ipaddress 模块)
    if not _resolve_and_check_ip(hostname):
        return False

    # 4. 如果设置了域名白名单且非空，检查是否在白名单中
    if ALLOWED_DOMAINS:
        is_allowed = any(hostname == domain or hostname.endswith("." + domain) for domain in ALLOWED_DOMAINS)
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
    r"(Bearer\s+)([A-Za-z0-9\-._~+/]{8,})",
    r"(sk-[A-Za-z0-9]{20,})",
    r"(sk-cp-[A-Za-z0-9]{20,})",
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
            lambda m: m.group(1) + "***" + m.group(2)[-4:] if len(m.groups()) >= 2 and len(m.group(2)) > 4 else "***",
            result,
            flags=re.IGNORECASE,
        )
    return result


class SensitiveDataFilter(logging.Filter):
    """日志过滤器 - 自动脱敏日志中的敏感信息"""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_sensitive_info(record.msg)
        if record.args:
            record.args = tuple(mask_sensitive_info(str(arg)) if isinstance(arg, str) else arg for arg in record.args)
        return True


# ==================== 路径遍历防护 ====================


def validate_path_safety(file_path: str, base_dir: Path) -> bool:
    """
    验证文件路径是否安全（防止路径遍历攻击）

    防御：
    - `../` 相对路径跳转
    - 绝对路径 `/etc/passwd`
    - Windows UNC 路径 `\\\\server\\share`
    - 符号链接指向 base_dir 外
    - 8.3 短文件名绕过 (C:\\PROGRA~1)
    - NTFS 备用数据流 (`file.txt:hidden`)
    - 大小写绕过（Windows 上 PROGRA~1 vs Program Files）

    Args:
        file_path: 待验证的文件路径
        base_dir: 基准目录（所有文件必须在此目录下）

    Returns:
        bool: 是否安全
    """
    import os

    try:
        # 1. 字符串层防御：拒绝 NUL/控制字符 + UNC 路径 + 备用数据流
        if "\x00" in file_path:
            logger.warning("路径含 NUL 字节: %r", file_path[:50])
            return False
        if file_path.startswith("\\\\"):
            logger.warning("UNC 路径拒绝: %s", file_path[:80])
            return False
        if ":" in file_path.replace(":", "", 1):  # 仅允许 `C:` 这种驱动器前缀
            # Windows 备用数据流：`file.txt:stream` 攻击
            if file_path[1:2] == ":" and len(file_path) > 2 and file_path[2] not in ("/", "\\"):
                pass  # 相对路径不带分隔符，正常
            elif file_path.count(":") > 1:
                logger.warning("备用数据流/NTFS 流攻击检测: %s", file_path[:80])
                return False
            elif not (len(file_path) >= 2 and file_path[1] == ":" and file_path[0].isalpha()):
                # 驱动器字母必须是英文字母开头
                logger.warning("非法驱动器前缀: %s", file_path[:80])
                return False

        # 2. 解析绝对路径 + 解析符号链接
        try:
            resolved = Path(file_path).resolve()
        except (OSError, RuntimeError) as e:
            # 在 Windows 上 resolve() 可能因路径不存在或太长而失败
            # 用 realpath 兜底（不要求路径存在）
            try:
                resolved = Path(os.path.realpath(file_path))
            except Exception:
                logger.warning("路径解析失败: %s, error=%s", file_path, e)
                return False

        base_resolved = base_dir.resolve()

        # 3. Windows 8.3 短文件名绕过：在 Windows 上比较短路径
        # 短路径 `C:\\PROGRA~1` 和长路径 `C:\\Program Files` 应视为同一目录
        if hasattr(os.path, "getshortpathname") and resolved.exists():
            try:
                short = os.path.getshortpathname(str(resolved))
                resolved = Path(short).resolve() if short else resolved
            except Exception:
                pass

        # 4. 规范化比较：用 commonpath 替代 startswith（更鲁棒）
        try:
            resolved_str = os.path.normcase(str(resolved))
            base_str = os.path.normcase(str(base_resolved))
            # commonpath 抛 ValueError 时表示不在同一驱动器或完全不同路径
            common = os.path.commonpath([resolved_str, base_str])
            is_safe = common == base_str
        except ValueError:
            # 不同驱动器（如 C:\ 和 D:\）→ 直接拒绝
            is_safe = False

        if not is_safe:
            logger.warning("路径遍历攻击检测: %s 不在基准目录 %s 下", resolved, base_resolved)
        return is_safe
    except Exception as e:
        logger.warning("路径验证异常: %s, error=%s", file_path, e)
        return False
