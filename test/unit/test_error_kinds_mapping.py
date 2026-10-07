"""
FF-M-kinds/audit 回归测试：kind → ErrorCode 映射与 CLI 出口码分类。

审计发现（Medium 行 64）：
- `file_not_found` / `bad_request` 不在 `_LEGACY_KIND` 里 → 被 remap 成
  `internal`(exit 70)，而不是 2 / 7；上游按新值语义传 kind 时（管道 error
  payload、batch）全部命中这个坑。
- argparse 的参数错误也报 internal(70)，与 `core/errors.py` 的 bad_request 冲突。
- 头部 docstring 的退出码表已过期。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from core.errors import EXIT_CODES, ErrorCode
from formatforge.__main__ import _fail, _kind_to_code, main


def _stdout_json(capsys) -> dict:
    out = capsys.readouterr().out.strip()
    assert out, "stdout 上没有协议 JSON"
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert len(lines) == 1, f"stdout 必须只有一行 JSON，实际 {len(lines)} 行: {out!r}"
    return json.loads(lines[0])


class TestKindToCode:
    def test_every_error_code_value_maps_to_itself(self):
        """核心不变量：ErrorCode 的值语义必须原样解析（这是上面那个坑的根因）。"""
        for ec in ErrorCode:
            assert _kind_to_code(ec.value) is ec, ec.value

    def test_legacy_alias_not_found(self):
        assert _kind_to_code("not_found") is ErrorCode.FILE_NOT_FOUND

    def test_unknown_kind_falls_back_to_internal(self):
        assert _kind_to_code("no_such_kind_at_all") is ErrorCode.INTERNAL


class TestFailExitCodes:
    @pytest.mark.parametrize("kind", ["file_not_found", "bad_request", "permission_denied", "timeout"])
    def test_fail_uses_errors_py_exit_code(self, kind, capsys):
        exit_code = _fail(kind, "boom")
        payload = _stdout_json(capsys)
        assert exit_code == EXIT_CODES[ErrorCode(kind)]
        assert payload["ok"] is False
        assert payload["error"]["kind"] == kind
        assert payload["code"] == 4000 + exit_code

    def test_fail_unknown_kind_is_internal_70(self, capsys):
        assert _fail("totally_unknown", "boom") == 70
        assert _stdout_json(capsys)["error"]["kind"] == "internal"


class TestMainExitClassification:
    def test_argparse_error_is_bad_request(self, capsys):
        """用法错误 → exit 7（此前是 internal/70）。"""
        exit_code = main(["--definitely-not-a-command"])
        payload = _stdout_json(capsys)
        assert exit_code == 7
        assert payload["error"]["kind"] == "bad_request"

    def test_system_exit_with_string_does_not_crash(self, monkeypatch, capsys):
        """SystemExit("字符串") 此前 int() 抛 ValueError → 无协议 JSON 的 traceback。"""
        import formatforge.__main__ as cli

        def _boom(args):
            raise SystemExit("用法提示：不要这样用")

        monkeypatch.setattr(cli, "cmd_translate", _boom)
        exit_code = main(["translate", "whatever.txt"])
        payload = _stdout_json(capsys)
        assert exit_code == 7
        assert payload["error"]["kind"] == "bad_request"

    def test_logging_does_not_write_stdout(self):
        """FF-M-logging/audit: setup_logging 必须绑 stderr，否则污染 stdout 协议。"""
        import io
        import logging

        from core.logging_config import setup_logging

        captured = io.StringIO()
        root = logging.getLogger()
        saved = root.handlers[:]
        saved_stdout = sys.stdout
        try:
            sys.stdout = captured
            setup_logging(level="INFO", json_format=False)
            logging.getLogger("test.stdout.probe").warning("不应出现在 stdout")
        finally:
            sys.stdout = saved_stdout
            for h in root.handlers[:]:
                root.removeHandler(h)
            for h in saved:
                root.addHandler(h)

        assert captured.getvalue() == "", f"日志写进了 stdout: {captured.getvalue()!r}"
