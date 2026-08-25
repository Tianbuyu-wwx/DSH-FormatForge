"""统一错误码协议（EVOLUTION_PLAN M4）。

CLI 与 Node runner 双侧共用同一组稳定错误码；message 保持中英双语一行。
PLUGIN_PLAN §4.3 协议契约的 error.code 取值以此为准。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ErrorCode(str, Enum):
    """协议级稳定错误码（勿改动既有值语义；新增只能追加）。"""

    FILE_NOT_FOUND = "file_not_found"
    IS_DIRECTORY = "is_directory"
    TOO_LARGE = "too_large"
    UNSUPPORTED_FORMAT = "unsupported_format"
    PARSE_FAILED = "parse_failed"
    TIMEOUT = "timeout"
    PERMISSION_DENIED = "permission_denied"
    BAD_REQUEST = "bad_request"
    INTERNAL = "internal"


#: 每个错误码对应的 CLI 退出码
EXIT_CODES: dict[ErrorCode, int] = {
    ErrorCode.FILE_NOT_FOUND: 2,
    ErrorCode.IS_DIRECTORY: 2,
    ErrorCode.PERMISSION_DENIED: 2,
    ErrorCode.UNSUPPORTED_FORMAT: 3,
    ErrorCode.PARSE_FAILED: 4,
    ErrorCode.TIMEOUT: 5,
    ErrorCode.TOO_LARGE: 6,
    ErrorCode.BAD_REQUEST: 7,
    ErrorCode.INTERNAL: 70,
}

#: 双语默认消息模板（{detail} 占位）
MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.FILE_NOT_FOUND: "文件不存在 / file not found: {detail}",
    ErrorCode.IS_DIRECTORY: "路径是目录而非文件 / path is a directory: {detail}",
    ErrorCode.TOO_LARGE: "文件超出大小上限 / file exceeds size limit: {detail}",
    ErrorCode.UNSUPPORTED_FORMAT: "不支持的格式 / unsupported format: {detail}",
    ErrorCode.PARSE_FAILED: "解析失败 / parse failed: {detail}",
    ErrorCode.TIMEOUT: "转换超时 / conversion timed out: {detail}",
    ErrorCode.PERMISSION_DENIED: "无访问权限 / permission denied: {detail}",
    ErrorCode.BAD_REQUEST: "参数错误 / bad request: {detail}",
    ErrorCode.INTERNAL: "内部错误 / internal error: {detail}",
}


@dataclass(frozen=True)
class ProtocolError:
    """可序列化的协议错误。"""

    code: ErrorCode
    detail: str = ""

    @property
    def exit_code(self) -> int:
        return EXIT_CODES.get(self.code, 70)

    def message(self) -> str:
        return MESSAGES[self.code].format(detail=self.detail or "-")

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.code.value, "code": self.code.value, "message": self.message()}


def exit_code_of(code: ErrorCode) -> int:
    """ErrorCode → CLI 退出码（模块级便捷函数，供 _fail/main 使用）。"""
    return EXIT_CODES.get(code, 70)
