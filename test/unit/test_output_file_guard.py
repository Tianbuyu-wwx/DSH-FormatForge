"""
FF-M-protocol/audit 回归测试：`--help` 的 stdout 协议 + `--output-file` 写入边界。

1. `--help` 曾把 usage print 到 **stdout** 再 SystemExit(0)：stdout 唯一 JSON 出口
   被污染，JS 侧 python-runner 首行 parse 直接失败。现在 usage 走 stderr，
   stdout 只发一条协议 JSON（data.help 带全文）。
2. `--output-file` 曾 `mkdir(parents=True)` + 直接写任意路径（无沙箱写原语），
   且写入失败只 `logger.warning` 后照样 `ok:true`。现在收敛到用户显式声明的
   FF_OUTPUT_ROOT；CWD、源文件目录和 Python 导入路径都不能扩大边界。越界报
   bad_request，失败报 permission_denied。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest

from formatforge.__main__ import main


def _payload(captured) -> dict:
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1, f"stdout 必须只有一条协议 JSON，实际 {len(lines)} 行: {lines}"
    return json.loads(lines[0])


def _make_source(tmp_path: Path) -> Path:
    src = tmp_path / "src" / "note.txt"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("hello formatforge\n", encoding="utf-8")
    return src


class TestHelpProtocol:
    def test_top_level_help_is_json_and_usage_goes_to_stderr(self, capsys):
        rc = main(["--help"])
        captured = capsys.readouterr()
        assert rc == 0
        payload = _payload(captured)
        assert payload["ok"] is True
        assert payload["code"] == 200
        assert "usage" in payload["data"]["help"].lower()
        # 人类可读的 usage 仍在 stderr（终端体验不丢）
        assert "usage" in captured.err.lower()
        assert "translate" in captured.err

    def test_subcommand_help_is_json(self, capsys):
        rc = main(["translate", "--help"])
        captured = capsys.readouterr()
        assert rc == 0
        payload = _payload(captured)
        assert payload["ok"] is True
        assert "output-file" in payload["data"]["help"]

    def test_help_short_flag(self, capsys):
        rc = main(["-h"])
        assert rc == 0
        assert _payload(capsys.readouterr())["ok"] is True

    def test_bad_args_still_single_json_error(self, capsys):
        """回归：argparse 错误路径不得因为 stdout 捕获而改变形状。"""
        rc = main(["nonexistent_subcmd"])
        captured = capsys.readouterr()
        assert rc != 0
        assert _payload(captured)["ok"] is False


class TestOutputFileGuard:
    def test_writes_next_to_source(self, tmp_path, capsys, monkeypatch):
        src = _make_source(tmp_path)
        dst = tmp_path / "src" / "note.md"
        monkeypatch.setenv("FF_OUTPUT_ROOT", str(tmp_path / "src"))
        rc = main(["translate", str(src), "--format", "markdown", "--output-file", str(dst)])
        payload = _payload(capsys.readouterr())
        assert rc == 0 and payload["ok"] is True, payload
        assert dst.exists()
        assert payload["data"]["meta"]["output_file"] == str(dst.resolve())

    def test_outside_declared_roots_is_bad_request(self, tmp_path, capsys, monkeypatch):
        """越界 → bad_request，且不建目录。"""
        src = _make_source(tmp_path)
        monkeypatch.setenv("FF_OUTPUT_ROOT", str(tmp_path / "declared"))
        outside = tmp_path.parent / "elsewhere" / "leak.md"
        rc = main(["translate", str(src), "--output-file", str(outside)])
        payload = _payload(capsys.readouterr())
        assert payload["ok"] is False, payload
        assert payload["error"]["kind"] == "bad_request"
        assert rc == 7
        assert "FF_OUTPUT_ROOT" in payload["error"]["message"]
        assert not outside.exists()
        assert not outside.parent.exists(), "越界目标不应产生目录副作用"

    def test_ff_output_root_declaration_allows_outside(self, tmp_path, capsys, monkeypatch):
        src = _make_source(tmp_path)
        declared = tmp_path.parent / "declared_root"
        declared.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("FF_OUTPUT_ROOT", str(declared))
        dst = declared / "nested" / "ok.md"

        rc = main(["translate", str(src), "--format", "markdown", "--output-file", str(dst)])
        payload = _payload(capsys.readouterr())
        assert rc == 0 and payload["ok"] is True, payload
        assert dst.exists()

    def test_multiple_roots_use_pathsep(self, tmp_path, capsys, monkeypatch):
        import os

        src = _make_source(tmp_path)
        first = tmp_path.parent / "root_one"
        second = tmp_path.parent / "root_two"
        first.mkdir(parents=True, exist_ok=True)
        second.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("FF_OUTPUT_ROOT", os.pathsep.join([str(first), str(second)]))
        dst = second / "multi.md"

        rc = main(["translate", str(src), "--format", "markdown", "--output-file", str(dst)])
        assert _payload(capsys.readouterr())["ok"] is True
        assert rc == 0
        assert dst.exists()

    def test_write_failure_is_reported_not_swallowed(self, tmp_path, capsys, monkeypatch):
        """父路径是文件 → mkdir 失败：必须 ok:false + permission_denied（不是 warn+ok）。"""
        src = _make_source(tmp_path)
        blocker = tmp_path / "src" / "blocker.txt"
        blocker.write_text("x", encoding="utf-8")
        dst = blocker / "cannot.md"
        monkeypatch.setenv("FF_OUTPUT_ROOT", str(tmp_path / "src"))

        rc = main(["translate", str(src), "--output-file", str(dst)])
        payload = _payload(capsys.readouterr())
        assert payload["ok"] is False, payload
        assert payload["error"]["kind"] == "permission_denied"
        assert rc == 2
        assert "写入失败" in payload["error"]["message"]


class TestOutputGuardUnit:
    def test_missing_root_fails_closed(self, monkeypatch, tmp_path):
        from formatforge.output_guard import OutputPathError, allowed_output_roots, resolve_output_path

        monkeypatch.delenv("FF_OUTPUT_ROOT", raising=False)
        monkeypatch.chdir(tmp_path)
        assert allowed_output_roots() == []
        with pytest.raises(OutputPathError, match="FF_OUTPUT_ROOT"):
            resolve_output_path("sub/out.md")

    def test_traversal_escape_is_denied(self, monkeypatch, tmp_path):
        from formatforge.output_guard import OutputPathError, resolve_output_path

        monkeypatch.delenv("FF_OUTPUT_ROOT", raising=False)
        inner = tmp_path / "inner"
        inner.mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("FF_OUTPUT_ROOT", str(inner))
        monkeypatch.chdir(inner)
        with pytest.raises(OutputPathError):
            resolve_output_path("../escaped.md")

    def test_source_dir_cannot_widen_declared_root(self, tmp_path, monkeypatch):
        from formatforge.output_guard import OutputPathError, allowed_output_roots, resolve_output_path

        declared = tmp_path / "declared"
        monkeypatch.setenv("FF_OUTPUT_ROOT", str(declared))
        src = _make_source(tmp_path)
        roots = allowed_output_roots(source=src)
        assert roots == [declared.resolve()]
        with pytest.raises(OutputPathError):
            resolve_output_path(src.with_suffix(".md"), source=src)

    def test_repo_root_is_denied_even_when_declared(self, monkeypatch):
        from formatforge.output_guard import OutputPathError, resolve_output_path

        repo_root = Path(__file__).resolve().parents[2]
        monkeypatch.setenv("FF_OUTPUT_ROOT", str(repo_root))
        with pytest.raises(OutputPathError):
            resolve_output_path(repo_root / "core" / "pipeline.py")

    def test_sys_path_entry_is_denied_even_when_declared(self, tmp_path, monkeypatch):
        from formatforge.output_guard import OutputPathError, resolve_output_path

        import_root = tmp_path / "importable"
        import_root.mkdir()
        monkeypatch.syspath_prepend(str(import_root))
        monkeypatch.setenv("FF_OUTPUT_ROOT", str(import_root))
        with pytest.raises(OutputPathError):
            resolve_output_path(import_root / "package" / "generated.py")

    def test_declared_root_allows_nested_target(self, tmp_path, monkeypatch):
        from formatforge.output_guard import resolve_output_path

        declared = tmp_path / "declared"
        monkeypatch.setenv("FF_OUTPUT_ROOT", str(declared))
        target = declared / "nested" / "result.md"
        assert resolve_output_path(target) == target.resolve()


class TestOutputFileExtensionAllowlist:
    """T1-8/audit: `--output-file` 只允许写出本产品产出的四种格式。

    这是 CWD 被当作受保护根之外的**第二道锁**：即使输出根配置正确，也不允许把
    任意后缀的文件写进那里——尤其是 `.py`/`.pth` 这类可被 Python 导入的名字。
    """

    def _root(self, tmp_path, monkeypatch):
        """一个位于代码与导入路径之外的、已声明的输出根。"""
        declared = tmp_path / "declared"
        monkeypatch.setenv("FF_OUTPUT_ROOT", str(declared))
        return declared

    @pytest.mark.parametrize("suffix", [".md", ".html", ".json", ".txt"])
    def test_allowed_output_formats_pass(self, tmp_path, monkeypatch, suffix):
        from formatforge.output_guard import resolve_output_file

        declared = self._root(tmp_path, monkeypatch)
        target = declared / f"result{suffix}"
        assert resolve_output_file(target) == target.resolve()

    @pytest.mark.parametrize("suffix", [".py", ".pyw", ".pyd", ".so", ".pth", ".exe", ".bat", ".ps1"])
    def test_importable_and_executable_suffixes_are_denied(self, tmp_path, monkeypatch, suffix):
        from formatforge.output_guard import OutputPathError, resolve_output_file

        declared = self._root(tmp_path, monkeypatch)
        with pytest.raises(OutputPathError, match="扩展名"):
            resolve_output_file(declared / f"payload{suffix}")

    def test_denied_even_though_the_root_itself_is_permitted(self, tmp_path, monkeypatch):
        """关键用例：路径完全在允许根内、且不触及受保护路径——仅因后缀被拒。"""
        from formatforge.output_guard import OutputPathError, allowed_output_roots, resolve_output_file

        declared = self._root(tmp_path, monkeypatch)
        assert declared.resolve() in allowed_output_roots()
        with pytest.raises(OutputPathError, match="扩展名"):
            resolve_output_file(declared / "sneaky.py")

    def test_extensionless_target_is_denied(self, tmp_path, monkeypatch):
        from formatforge.output_guard import OutputPathError, resolve_output_file

        declared = self._root(tmp_path, monkeypatch)
        with pytest.raises(OutputPathError, match="扩展名"):
            resolve_output_file(declared / "noext")

    def test_uppercase_suffix_is_accepted(self, tmp_path, monkeypatch):
        """Windows 语义：`.MD` 与 `.md` 是同一后缀。"""
        from formatforge.output_guard import resolve_output_file

        declared = self._root(tmp_path, monkeypatch)
        target = declared / "REPORT.MD"
        assert resolve_output_file(target) == target.resolve()

    def test_error_message_names_the_allowed_formats(self, tmp_path, monkeypatch):
        from formatforge.output_guard import OutputPathError, resolve_output_file

        declared = self._root(tmp_path, monkeypatch)
        with pytest.raises(OutputPathError) as exc:
            resolve_output_file(declared / "x.py")
        msg = str(exc.value)
        for suffix in (".md", ".html", ".json", ".txt"):
            assert suffix in msg, f"报错未列出允许的 {suffix}"

    def test_directory_entry_point_is_not_extension_restricted(self, tmp_path, monkeypatch):
        """`ff_batch --out` 传的是**目录**，不能受这条规则影响。"""
        from formatforge.output_guard import resolve_output_path

        declared = self._root(tmp_path, monkeypatch)
        out_dir = declared / "batch-output"
        assert resolve_output_path(out_dir, label="--out") == out_dir.resolve()

    def test_cli_rejects_disallowed_suffix(self, tmp_path, monkeypatch, capsys):
        """端到端：协议层报 bad_request，且**不落盘**。"""
        declared = self._root(tmp_path, monkeypatch)
        src = _make_source(tmp_path)
        target = declared / "evil.py"

        rc = main(["translate", str(src), "--format", "markdown", "--output-file", str(target)])
        payload = _payload(capsys.readouterr())

        assert rc != 0
        assert payload["ok"] is False
        assert payload["error"]["kind"] == "bad_request"
        assert not target.exists(), "被拒的目标不得被创建"
