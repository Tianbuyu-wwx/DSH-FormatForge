"""
FF-M-diff/audit 回归测试：diff 子命令四处缺陷。

1. --context 的 clamp 是 no-op（`max(i1, i1 - context) == i1`）→ 全部未变更行都被吐出
2. --since-mtime 只过滤 path_b（注释声称两侧都过滤）；float("nan") 静默禁用过滤器
3. --against-dir 取 glob 顺序的 candidates[0]（顺序不确定 → 旧版本漂移）
4. --format json 先 indent=2 重新序列化再切行 → 行数描述的是美化形态而非源内容

为避开本机 CLI 子进程 stdout 编码问题，这里在进程内调用 cmd_diff（协议 JSON
由 capsys 捕获），断言与 JS 侧 python-runner 依赖的字段完全一致。
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest


def _run_diff(capsys, *argv: str) -> tuple[dict, int]:
    from formatforge.__main__ import build_parser
    from formatforge.diff import cmd_diff

    args = build_parser().parse_args(["diff", *argv])
    rc = cmd_diff(args)
    out = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert out, "diff 未输出协议 JSON"
    return json.loads(out[0]), rc


def _ctx_lines(preview: str) -> list[str]:
    return [line for line in preview.split("\n") if line.startswith(" ") and line.strip()]


class TestContextClamp:
    """--context 必须真的裁剪未变更上下文。"""

    def _pair(self, tmp_path: Path) -> tuple[Path, Path]:
        a = tmp_path / "old.txt"
        b = tmp_path / "new.txt"
        a.write_text("\n".join(f"line{i}" for i in range(1, 41)) + "\n", encoding="utf-8")
        lines = [f"line{i}" for i in range(1, 41)]
        lines[19] = "CHANGED"
        b.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return a, b

    def test_context_limits_unchanged_context(self, tmp_path, capsys):
        a, b = self._pair(tmp_path)
        payload, rc = _run_diff(capsys, str(a), str(b), "--format", "text", "--context", "1")
        assert rc == 0 and payload["ok"] is True, payload
        d = payload["data"]
        preview = d["diff_preview"]
        ctx = _ctx_lines(preview)
        # 2 个未变更块（首块 + 尾块），每块最多「与变更相邻的 1 行」→ 最多 6 行上下文
        # （旧实现在此会吐出全部 39 行未变更内容）
        assert len(ctx) <= 6, f"context 未生效: {ctx}"
        for far in ("line5", "line10", "line15", "line25", "line30", "line35"):
            assert far not in preview, f"远端未变更行仍在 preview: {far}"
        assert d["elided_count"] > 0
        # T2-9/audit: 这个 fixture 只有一处变更，于是两个 equal 块都是边界块——
        # 省略掉的是文件开头/结尾那段与改动无关的内容，按 unified diff 的语义不再
        # 打标记（总量仍在 elided_count 里）。夹在两处变更之间的块仍然会打标记，
        # 见 TestT29BoundaryContext::test_interior_block_still_keeps_both_ends_and_its_marker。
        assert "省略" not in preview
        # 统计口径不受裁剪影响
        assert d["unchanged_count"] >= 39
        assert d["additions"] == 1 and d["deletions"] == 1

        # 更大的 context 必须给出更多上下文行（旧实现两者完全相同 → no-op）
        payload3, _rc3 = _run_diff(capsys, str(a), str(b), "--context", "3")
        assert len(_ctx_lines(payload3["data"]["diff_preview"])) > len(ctx)

    def test_context_zero_shows_only_changes(self, tmp_path, capsys):
        """--context 0 曾被 `int(args.context or 3)` 静默换成默认 3。"""
        a, b = self._pair(tmp_path)
        payload, rc = _run_diff(capsys, str(a), str(b), "--context", "0")
        assert rc == 0, payload
        d = payload["data"]
        assert _ctx_lines(d["diff_preview"]) == []
        assert "CHANGED" in d["diff_preview"]
        assert d["elided_count"] == d["unchanged_count"]

    def test_small_equal_block_kept_whole(self, tmp_path, capsys):
        """未变更块 <= 2*context 时整块保留（无省略标记）。"""
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("l1\nl2\nl3\n", encoding="utf-8")
        b.write_text("l1\nl2-x\nl3\n", encoding="utf-8")
        payload, rc = _run_diff(capsys, str(a), str(b), "--context", "3")
        assert rc == 0, payload
        assert payload["data"]["elided_count"] == 0
        assert "省略" not in payload["data"]["diff_preview"]


class TestSinceMtime:
    def test_nan_is_bad_request(self, tmp_path, capsys):
        """float('nan') 曾「解析成功」但比较恒 False → 过滤器被静默禁用。"""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        (old_dir / "r.txt").write_text("old\n", encoding="utf-8")
        new_path = tmp_path / "r.txt"
        new_path.write_text("new\n", encoding="utf-8")

        payload, _rc = _run_diff(
            capsys,
            "--against-dir",
            str(old_dir),
            "--since-mtime",
            "nan",
            str(new_path),
        )
        assert payload["ok"] is False, payload
        assert payload["error"]["kind"] == "bad_request"

    def test_inf_is_bad_request(self, tmp_path, capsys):
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        (old_dir / "r.txt").write_text("old\n", encoding="utf-8")
        new_path = tmp_path / "r.txt"
        new_path.write_text("new\n", encoding="utf-8")

        payload, _rc = _run_diff(
            capsys,
            "--against-dir",
            str(old_dir),
            "--since-mtime",
            "inf",
            str(new_path),
        )
        assert payload["ok"] is False, payload
        assert payload["error"]["kind"] == "bad_request"

    def test_stale_path_a_is_skipped(self, tmp_path, capsys):
        """path_a 过旧也必须跳过（旧实现只看 path_b）。"""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        old_a = old_dir / "r.txt"
        old_a.write_text("old\n", encoding="utf-8")
        new_path = tmp_path / "r.txt"
        new_path.write_text("new\n", encoding="utf-8")

        base = 1_000_000_000
        os.utime(old_a, (base, base))  # path_a 远古
        os.utime(new_path, (base + 500, base + 500))  # path_b 较新

        payload, rc = _run_diff(
            capsys,
            "--against-dir",
            str(old_dir),
            "--since-mtime",
            str(base + 100),
            str(new_path),
        )
        assert rc == 0 and payload["ok"] is True, payload
        assert payload["data"]["skipped"] is True
        assert payload["data"]["skipped_side"] == "path_a"
        assert "path_a" in payload["data"]["reason"]

    def test_both_fresh_produces_diff(self, tmp_path, capsys):
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        old_a = old_dir / "r.txt"
        old_a.write_text("old-content\n", encoding="utf-8")
        new_path = tmp_path / "r.txt"
        new_path.write_text("new-content\n", encoding="utf-8")

        base = 1_000_000_000
        os.utime(old_a, (base + 200, base + 200))
        os.utime(new_path, (base + 300, base + 300))

        payload, rc = _run_diff(
            capsys,
            "--against-dir",
            str(old_dir),
            "--since-mtime",
            str(base),
            str(new_path),
        )
        assert rc == 0, payload
        assert payload["data"].get("skipped") is not True
        assert payload["data"]["additions"] == 1


class TestAgainstDirDeterminism:
    def test_picks_newest_candidate_deterministically(self, tmp_path, capsys):
        """同 stem 多候选 → 按 mtime 择新（不再随 glob 顺序漂移）。"""
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        older = old_dir / "r.txt"
        newer = old_dir / "r.md"
        older.write_text("FROM_TXT\n", encoding="utf-8")
        newer.write_text("FROM_MD\n", encoding="utf-8")

        base = 1_000_000_000
        os.utime(older, (base, base))
        os.utime(newer, (base + 100, base + 100))

        new_path = tmp_path / "r.txt"
        new_path.write_text("FROM_TXT\n", encoding="utf-8")

        seen = set()
        for _ in range(3):
            payload, rc = _run_diff(
                capsys,
                "--against-dir",
                str(old_dir),
                "--format",
                "text",
                str(new_path),
            )
            assert rc == 0, payload
            seen.add(payload["data"]["path_a"])
        assert seen == {str(newer)}, f"旧版本选择不确定: {seen}"


class TestJsonFormatLineAccounting:
    def test_json_reader_does_not_reserialize(self, tmp_path, monkeypatch):
        """--format json 必须按 translate 产出的内容原样切行。

        旧实现先 json.loads 再 json.dumps(indent=2)：紧凑 JSON 会被炸成多行，
        lines_a/lines_b/diff_preview 描述的是「美化后的形态」而不是源内容。
        """
        from formatforge import __main__ as ff_main
        from formatforge import diff as ff_diff

        compact = '{"a":1,"b":[1,2,3],"c":{"d":"e"}}'
        monkeypatch.setattr(ff_main, "translate_file_data", lambda *a, **k: ({"content": compact}, 0))

        lines = ff_diff._read_text_lines(tmp_path / "x.json", "json")
        assert lines == [compact], f"json 行被重新美化: {lines}"

    def test_cli_lines_match_content_line_count(self, tmp_path, capsys):
        """端到端口径：lines_a/lines_b 等于 translate content 自身的行数。

        FF-L-diff/audit: self-diff（path_a == path_b）现在报 bad_request，
        所以这里改为「同内容、不同路径」的两份文件来核对行数口径。
        """
        from formatforge.__main__ import translate_file_data

        doc_a = tmp_path / "d_a.json"
        doc_b = tmp_path / "d_b.json"
        body = '{"a": 1, "b": [1, 2, 3], "c": {"d": "e"}}'
        doc_a.write_text(body, encoding="utf-8")
        doc_b.write_text(body, encoding="utf-8")

        data, code = translate_file_data(doc_a, "json", "auto", quality=False)
        assert code == 0, data
        source_lines = len(str(data["content"]).splitlines())

        payload, rc = _run_diff(capsys, str(doc_a), str(doc_b), "--format", "json")
        assert rc == 0, payload
        assert payload["data"]["lines_a"] == source_lines
        assert payload["data"]["lines_b"] == source_lines
        assert payload["data"]["additions"] == 0

    def test_self_diff_is_an_error(self, tmp_path, capsys):
        """FF-L-diff/audit: 同一文件 self-diff 必须报错（不是无操作空 diff）。"""
        doc = tmp_path / "d.json"
        doc.write_text('{"a": 1}', encoding="utf-8")
        payload, rc = _run_diff(capsys, str(doc), str(doc))
        assert rc != 0
        assert payload["ok"] is False
        assert payload["error"]["kind"] == "bad_request"
        assert "同一文件" in payload["error"]["message"]


class TestT26DiffTotalChars:
    """T2-6/audit: diff_total_chars 必须是整份 diff 的长度，不是 preview 的长度。

    预算封顶后 `_emit_line` 不再往 diff_chunks 里追加，于是
    `diff_total_chars = len(diff_text)` 变成「保留下来的前缀有多长」，
    truncated 为真时恒等于 ~max_chars——字段名承诺的总量再也拿不到。
    """

    def _pair(self, tmp_path: Path) -> tuple[Path, Path]:
        a = tmp_path / "old.txt"
        b = tmp_path / "new.txt"
        # 每一行都不同 → 全是 replace，没有可省略的未变更块
        a.write_text("\n".join(f"old line {i:04d} xxxxxxxxxxxxxxxx" for i in range(300)) + "\n", encoding="utf-8")
        b.write_text("\n".join(f"new line {i:04d} yyyyyyyyyyyyyyyy" for i in range(300)) + "\n", encoding="utf-8")
        return a, b

    def test_total_is_the_whole_diff_not_the_kept_prefix(self, tmp_path, capsys):
        a, b = self._pair(tmp_path)
        capped, rc = _run_diff(capsys, str(a), str(b), "--format", "text", "--max-chars", "500")
        assert rc == 0, capped
        d = capped["data"]
        assert d["truncated"] is True
        assert len(d["diff_preview"]) <= 500

        # 参照值：预算足够大时不封顶，此时 preview 就是整份 diff。
        full, rc2 = _run_diff(capsys, str(a), str(b), "--format", "text", "--max-chars", "2000000")
        assert rc2 == 0, full
        assert full["data"]["truncated"] is False
        true_total = len(full["data"]["diff_preview"])

        assert true_total > 500
        assert d["diff_total_chars"] == true_total, "封顶后报的是 preview 长度"
        assert d["diff_total_chars"] > d["max_chars"]
        assert d["diff_total_chars"] > len(d["diff_preview"])

    def test_untruncated_total_still_matches_the_preview(self, tmp_path, capsys):
        """向后兼容：没封顶时这个字段的值一个字节都不许变。"""
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("l1\nl2\nl3\n", encoding="utf-8")
        b.write_text("l1\nl2-x\nl3\n", encoding="utf-8")
        payload, rc = _run_diff(capsys, str(a), str(b), "--format", "text")
        assert rc == 0, payload
        d = payload["data"]
        assert d["truncated"] is False
        assert d["diff_total_chars"] == len(d["diff_preview"])

    def test_marker_only_diff_is_never_negative(self, tmp_path, capsys):
        """几乎没有内容的 diff 不能因为收尾减 1 报成负数。"""
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("same\n", encoding="utf-8")
        b.write_text("same\n", encoding="utf-8")
        payload, _rc = _run_diff(capsys, str(a), str(b), "--format", "text", "--context", "0")
        d = payload["data"]
        assert d["diff_total_chars"] >= 0
        assert d["diff_total_chars"] == len(d["diff_preview"])


class TestT29BoundaryContext:
    """T2-9/audit: 首块只留尾部、尾块只留头部，边界上不出现省略标记。

    旧实现对每个 equal 块都吐首尾两端。首块前面没有变更、尾块后面没有变更，
    那两端与任何改动都不相邻——每份 diff 白白多出最多 2×context 行无关内容，
    外加两个指向文件开头/结尾的省略标记。
    """

    def _pair(self, tmp_path: Path, changed_at: int = 50, n: int = 100) -> tuple[Path, Path]:
        a = tmp_path / "old.txt"
        b = tmp_path / "new.txt"
        base = [f"line{i:03d}" for i in range(n)]
        a.write_text("\n".join(base) + "\n", encoding="utf-8")
        new = list(base)
        new[changed_at] = "CHANGED"
        b.write_text("\n".join(new) + "\n", encoding="utf-8")
        return a, b

    def test_leading_block_contributes_only_its_tail(self, tmp_path, capsys):
        a, b = self._pair(tmp_path)
        payload, rc = _run_diff(capsys, str(a), str(b), "--format", "text", "--context", "3")
        assert rc == 0, payload
        preview = payload["data"]["diff_preview"]
        ctx = _ctx_lines(preview)

        # 首块（line000..line049）只留紧挨变更的三行
        assert [c.strip() for c in ctx[:3]] == ["line047", "line048", "line049"]
        for head in ("line000", "line001", "line002"):
            assert head not in preview, f"首块头部（与变更不相邻）仍被吐出: {head}"

    def test_trailing_block_contributes_only_its_head(self, tmp_path, capsys):
        a, b = self._pair(tmp_path)
        payload, rc = _run_diff(capsys, str(a), str(b), "--format", "text", "--context", "3")
        preview = payload["data"]["diff_preview"]
        ctx = _ctx_lines(preview)

        # 尾块（line051..line099）只留紧挨变更的三行
        assert [c.strip() for c in ctx[-3:]] == ["line051", "line052", "line053"]
        for tail in ("line097", "line098", "line099"):
            assert tail not in preview, f"尾块尾部（与变更不相邻）仍被吐出: {tail}"

    def test_no_elision_marker_at_either_boundary(self, tmp_path, capsys):
        a, b = self._pair(tmp_path)
        payload, _rc = _run_diff(capsys, str(a), str(b), "--format", "text", "--context", "3")
        d = payload["data"]
        assert "省略" not in d["diff_preview"], "文件首尾的省略标记与任何变更都不相邻"
        # 省掉的行数仍然如实统计
        # 省掉的行数仍然如实统计：未变更总数减去实际吐出来的 6 行上下文
        assert d["elided_count"] == d["unchanged_count"] - 6

    def test_context_budget_is_halved_at_the_boundaries(self, tmp_path, capsys):
        """单处变更：上下文行数从 4×context 降到 2×context。"""
        a, b = self._pair(tmp_path)
        payload, _rc = _run_diff(capsys, str(a), str(b), "--format", "text", "--context", "3")
        assert len(_ctx_lines(payload["data"]["diff_preview"])) == 6

    def test_interior_block_still_keeps_both_ends_and_its_marker(self, tmp_path, capsys):
        """中间块两端都与变更相邻——不许被这次修复误伤。"""
        a = tmp_path / "old.txt"
        b = tmp_path / "new.txt"
        base = [f"line{i:03d}" for i in range(100)]
        a.write_text("\n".join(base) + "\n", encoding="utf-8")
        new = list(base)
        new[10] = "CHANGED-A"
        new[80] = "CHANGED-B"
        b.write_text("\n".join(new) + "\n", encoding="utf-8")

        payload, _rc = _run_diff(capsys, str(a), str(b), "--format", "text", "--context", "2", "--max-chars", "200000")
        preview = payload["data"]["diff_preview"]
        # 中间块 line011..line079：两端各留 2 行，中段省略并带标记
        for kept in ("line011", "line012", "line078", "line079"):
            assert kept in preview, f"中间块两端的上下文丢了: {kept}"
        assert "line040" not in preview
        assert "省略" in preview, "夹在两处变更之间的块必须报省略"
        assert preview.count("省略") == 1

