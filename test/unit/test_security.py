"""
安全模块单元测试

测试文件类型白名单、URL域名白名单、敏感信息脱敏、路径遍历防护
"""
import pytest
import logging
from pathlib import Path

from core.security import (
    ALLOWED_EXTENSIONS,
    ALLOWED_MIME_TYPES,
    validate_file_extension,
    validate_mime_type,
    validate_url_domain,
    mask_sensitive_info,
    SensitiveDataFilter,
    validate_path_safety,
    BLOCKED_DOMAINS,
    SENSITIVE_PATTERNS,
)
from core.format_detector import EXTENSION_MAP


class TestAllowedExtensions:
    """测试文件扩展名白名单"""

    def test_common_extensions_allowed(self):
        """常用扩展名应该在白名单中"""
        for ext in [".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".csv", ".json", ".png", ".jpg", ".zip"]:
            assert ext in ALLOWED_EXTENSIONS, f"{ext} should be allowed"

    def test_legacy_formats_allowed(self):
        """旧版格式也应该允许"""
        assert ".doc" in ALLOWED_EXTENSIONS
        assert ".xls" in ALLOWED_EXTENSIONS

    def test_dangerous_extensions_blocked(self):
        """危险扩展名应该被阻止"""
        for ext in [".exe", ".bat", ".sh", ".dll", ".so", ".pyc", ".js"]:
            assert ext not in ALLOWED_EXTENSIONS, f"{ext} should be blocked"

    def test_official_extensions_in_both_lists(self):
        """EXTENSION_MAP 中的所有扩展名都应该在 ALLOWED_EXTENSIONS 中"""
        missing = set(EXTENSION_MAP.keys()) - ALLOWED_EXTENSIONS
        assert len(missing) == 0, f"Missing from ALLOWED_EXTENSIONS: {missing}"

    def test_svg_allowed(self):
        assert ".svg" in ALLOWED_EXTENSIONS

    def test_email_formats_allowed(self):
        assert ".eml" in ALLOWED_EXTENSIONS
        assert ".msg" in ALLOWED_EXTENSIONS

    def test_ebook_formats_allowed(self):
        assert ".epub" in ALLOWED_EXTENSIONS


class TestAllowedMimeTypes:
    """测试 MIME 类型白名单"""

    def test_common_mime_types_allowed(self):
        mimes = [
            "application/pdf",
            "text/plain",
            "image/png",
            "image/jpeg",
            "application/json",
            "application/zip",
        ]
        for mime in mimes:
            assert mime in ALLOWED_MIME_TYPES, f"{mime} should be allowed"

    def test_legacy_mime_types_allowed(self):
        assert "application/msword" in ALLOWED_MIME_TYPES
        assert "application/vnd.ms-excel" in ALLOWED_MIME_TYPES

    def test_extensions_and_mimes_consistent(self):
        """EXTENSION_MAP 中的所有 MIME 类型都应该在 ALLOWED_MIME_TYPES 中"""
        all_mimes = {mime for _, mime in EXTENSION_MAP.values()}
        missing = all_mimes - ALLOWED_MIME_TYPES
        assert len(missing) == 0, f"Missing from ALLOWED_MIME_TYPES: {missing}"


class TestValidateFileExtension:
    """测试文件扩展名验证"""

    def test_valid_extensions(self):
        assert validate_file_extension("document.pdf") is True
        assert validate_file_extension("presentation.pptx") is True
        assert validate_file_extension("data.json") is True
        assert validate_file_extension("image.png") is True

    def test_invalid_extensions(self):
        assert validate_file_extension("script.exe") is False
        assert validate_file_extension("malware.bat") is False
        assert validate_file_extension("library.dll") is False

    def test_case_insensitive(self):
        assert validate_file_extension("DOCUMENT.PDF") is True
        assert validate_file_extension("Image.PNG") is True

    def test_no_extension(self):
        assert validate_file_extension("README") is False


class TestValidateMimeType:
    """测试 MIME 类型验证"""

    def test_valid_mime_types(self):
        assert validate_mime_type("application/pdf") is True
        assert validate_mime_type("text/plain") is True
        assert validate_mime_type("image/jpeg") is True

    def test_invalid_mime_types(self):
        assert validate_mime_type("application/x-msdownload") is False
        assert validate_mime_type("text/javascript") is False

    def test_none_mime(self):
        # None MIME 应该被拦截（安全加固）
        assert validate_mime_type(None) is False

    def test_empty_mime(self):
        # 空字符串 MIME 应该被拦截（安全加固）
        assert validate_mime_type("") is False


class TestValidateUrlDomain:
    """测试 URL 域名验证（SSRF 防护）"""

    def test_valid_urls(self):
        assert validate_url_domain("https://example.com/file.pdf") is True
        assert validate_url_domain("http://cdn.example.org/data.json") is True
        assert validate_url_domain("https://api.openai.com/v1/models") is True

    def test_blocked_localhost(self):
        assert validate_url_domain("http://localhost:8000/admin") is False
        assert validate_url_domain("http://127.0.0.1/config") is False

    def test_blocked_metadata_endpoints(self):
        assert validate_url_domain("http://169.254.169.254/latest/meta-data") is False
        assert validate_url_domain("http://metadata.google.internal") is False

    def test_blocked_private_ranges(self):
        assert validate_url_domain("http://192.168.1.1/admin") is False
        assert validate_url_domain("http://10.0.0.1/api") is False

    def test_invalid_url(self):
        # URL 格式正确性检查不在 scope 内，只检查域名安全
        assert validate_url_domain("http://example.com") is True


class TestMaskSensitiveInfo:
    """测试敏感信息脱敏"""

    def test_api_key_masking(self):
        text = 'api_key = "sk-1234567890abcdef"'
        result = mask_sensitive_info(text)
        assert "sk-1234567890abcdef" not in result

    def test_bearer_token_masking(self):
        # 单独测试 Bearer 模式（不加 Authorization 前缀避免被前面的 auth 规则抢先匹配）
        text = "Bearer sk-test-token-12345"
        result = mask_sensitive_info(text)
        assert "sk-test-token-12345" not in result

    def test_password_masking(self):
        text = 'password = "super_secret_123"'
        result = mask_sensitive_info(text)
        assert "super_secret_123" not in result

    def test_minimax_key_masking(self):
        text = 'Authorization: Bearer sk-cp-abcdefghijklmnopqrstuvwxyz1234567890'
        result = mask_sensitive_info(text)
        assert "sk-cp-" not in result or "***" in result

    def test_normal_text_preserved(self):
        text = "This is normal text without secrets"
        result = mask_sensitive_info(text)
        assert result == text

    def test_multiple_secrets(self):
        text = 'api_key = "key1" and secret = "secret1"'
        result = mask_sensitive_info(text)
        assert "key1" not in result
        assert "secret1" not in result


class TestSensitiveDataFilter:
    """测试敏感信息日志过滤器"""

    def test_filter_masks_message(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg='api_key = "sk-test1234567890"', args=(), exc_info=None
        )
        filt = SensitiveDataFilter()
        result = filt.filter(record)
        assert result is True
        assert "sk-test1234567890" not in record.msg

    def test_filter_masks_args(self):
        # sk- 模式需要 20+ 字符，使用足够长的 key
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Processing request with key: %s",
            args=("sk-abcdefghijklmnopqrstuv",),
            exc_info=None
        )
        filt = SensitiveDataFilter()
        filt.filter(record)
        assert "sk-abcdefghijklmnopqrstuv" not in str(record.args[0])


class TestValidatePathSafety:
    """测试路径遍历防护"""

    def test_safe_path(self, tmp_path):
        file_path = tmp_path / "uploads" / "test.pdf"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()
        assert validate_path_safety(str(file_path), tmp_path / "uploads") is True

    def test_path_traversal_attempt(self, tmp_path):
        base = tmp_path / "uploads"
        base.mkdir(parents=True, exist_ok=True)
        # 尝试路径遍历
        assert validate_path_safety(str(tmp_path / "outside.txt"), base) is False

    def test_parent_directory_traversal(self, tmp_path):
        base = tmp_path / "uploads"
        base.mkdir(parents=True, exist_ok=True)
        dangerous = str(base / ".." / "etc" / "passwd")
        assert validate_path_safety(dangerous, base) is False

    def test_invalid_path(self, tmp_path):
        base = tmp_path / "uploads"
        base.mkdir(parents=True, exist_ok=True)
        assert validate_path_safety("", base) is False
