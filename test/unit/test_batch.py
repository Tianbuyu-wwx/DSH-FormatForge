"""EVOLUTION_PLAN N3 —— batch 命令的单元测试（协议契约 + 续跑 + 汇总）。"""

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from formatforge.batch import _out_key, _plan_out_paths, cmd_batch


@pytest.fixture(autouse=True)
def declared_output_root(tmp_path, monkeypatch):
    """Batch tests must explicitly authorize their temporary output tree."""
    monkeypatch.setenv("FF_OUTPUT_ROOT", str(tmp_path))


@pytest.fixture()
def sample_dir(tmp_path):
    """3 个可转换文本文件 + 1 个不支持的扩展名。"""
    d = tmp_path / "docs"
    d.mkdir()
    (d / "a.txt").write_text("alpha content", encoding="utf-8")
    (d / "b.txt").write_text("beta content", encoding="utf-8")
    (d / "c.md").write_text("# gamma\n\ngamma body", encoding="utf-8")
    (d / "skipme.xyz").write_text("binary-ish", encoding="utf-8")
    return d


class _Args:
    def __init__(self, source, out, **kw):
        self.source = str(source)
        self.out = str(out)
        self.format = kw.get("format", "markdown")
        self.type = kw.get("type", "auto")
        self.workers = kw.get("workers", 2)
        self.recursive = kw.get("recursive", False)
        self.quality = kw.get("quality", False)
        self.pages = kw.get("pages", None)
        self.force = kw.get("force", False)


def _run(tmp_path, sample_dir, **kw):
    out = tmp_path / "out"
    code = cmd_batch(_Args(sample_dir, out, **kw))
    report = json.loads((out / "_batch_report.json").read_text(encoding="utf-8"))
    return code, report, out


class TestT15OutputGuard:
    def test_outside_declared_root_is_rejected_before_mkdir(self, tmp_path, monkeypatch, capsys):
        source = tmp_path / "source"
        source.mkdir()
        (source / "note.txt").write_text("safe input", encoding="utf-8")
        monkeypatch.setenv("FF_OUTPUT_ROOT", str(tmp_path / "allowed"))
        outside = tmp_path / "outside" / "nested"

        code = cmd_batch(_Args(source, outside))
        payload = json.loads(capsys.readouterr().out.strip())

        assert code != 0
        assert payload["ok"] is False
        assert payload["error"]["kind"] == "bad_request"
        assert not outside.exists(), "guard must run before mkdir"

    def test_declared_output_root_is_permitted(self, tmp_path, sample_dir):
        allowed = tmp_path / "allowed"
        code = cmd_batch(_Args(sample_dir, allowed))

        assert code == 0
        assert (allowed / "_batch_report.json").exists()
        assert (allowed / "a.md").exists()


class TestBatch:
    def test_converts_supported_files_only(self, tmp_path, sample_dir):
        code, report, out = _run(tmp_path, sample_dir)
        # .xyz 不在支持清单
        assert report["total"] == 3
        assert report["ok_count"] == 3
        assert report["failed"] == 0
        assert code == 0
        assert (out / "a.md").exists()
        assert not (out / "skipme.md").exists()

    def test_markdown_output_contains_content(self, tmp_path, sample_dir):
        _, _, out = _run(tmp_path, sample_dir)
        body = (out / "a.md").read_text(encoding="utf-8")
        assert "alpha" in body

    def test_resume_skips_existing(self, tmp_path, sample_dir):
        code1, r1, out = _run(tmp_path, sample_dir)
        assert r1["ok_count"] == 3
        # 第二轮：产物已存在 → 全部 skipped
        code2, r2, _ = _run(tmp_path, sample_dir)
        assert r2["skipped"] == 3
        assert r2["ok_count"] == 0

    def test_resume_reconverts_a_corrupt_newer_artifact(self, tmp_path, sample_dir):
        _, first, out = _run(tmp_path, sample_dir)
        assert first["ok_count"] == 3
        artifact = out / "a.md"
        original_size = len(artifact.read_bytes())
        artifact.write_bytes(b"x" * original_size)  # same size: checksum must catch it

        code, resumed, _ = _run(tmp_path, sample_dir)

        assert code == 0
        assert resumed["ok_count"] == 1
        assert resumed["skipped"] == 2
        assert "alpha" in artifact.read_text(encoding="utf-8")

    def test_force_reconverts(self, tmp_path, sample_dir):
        _run(tmp_path, sample_dir)
        code, report, _ = _run(tmp_path, sample_dir, force=True)
        assert report["ok_count"] == 3
        assert report["skipped"] == 0
        assert code == 0

    def test_report_filename_source_keeps_a_separate_artifact(self, tmp_path):
        source = tmp_path / "report-source"
        source.mkdir()
        original = source / "_batch_report.json"
        original.write_text('{"source": "must survive"}', encoding="utf-8")

        code, report, out = _run(tmp_path, source, format="json", force=True)

        assert code == 0
        assert report["ok_count"] == 1
        artifact = Path(report["results"][0]["out"])
        assert artifact.name != "_batch_report.json"
        assert artifact.exists()
        assert artifact.read_text(encoding="utf-8").strip()
        assert json.loads((out / "_batch_report.json").read_text(encoding="utf-8"))["total"] == 1

    def test_empty_source_reports_not_found(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        code, report, out = _run(tmp_path, empty)
        assert report["total"] == 0
        assert code != 0

    def test_glob_source(self, tmp_path, sample_dir):
        code, report, out = _run(tmp_path, sample_dir.glob("*.txt") and sample_dir / "*.txt")
        assert report["total"] == 2
        assert report["ok_count"] == 2

    def test_summary_protocol_shape(self, tmp_path, sample_dir):
        _, report, _ = _run(tmp_path, sample_dir)
        for key in ("total", "ok", "failed", "skipped", "failures", "elapsed_ms", "avg_confidence"):
            assert key in report


class _RecordingCmd:
    """记录每次 cmd_translate_main 调用的 conv_type。"""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def __call__(self, path, to_format, conv_type, timeout_s, pages=None, quality=False, encoding=None, language=None):
        self.calls.append((Path(path).name, conv_type))
        return "converted content", {"parser": "unknown", "confidence": 0.9, "result_id": "r"}, None


class TestH4PerFileConvType:
    def test_mixed_extension_batch_gets_per_file_type(self, tmp_path, monkeypatch):
        rec = _RecordingCmd()
        monkeypatch.setattr("formatforge.__main__.cmd_translate_main", rec)
        d = tmp_path / "mixed"
        d.mkdir()
        (d / "data.csv").write_text("a,b\n1,2", encoding="utf-8")
        (d / "note.txt").write_text("plain text", encoding="utf-8")
        out = tmp_path / "out"
        code = cmd_batch(_Args(d, out))
        names = {name: ct for name, ct in rec.calls}
        assert names.get("data.csv") == "table"  # .csv 提示 table
        assert names.get("note.txt") == "auto"   # 无提示 → auto
        assert code == 0


class TestH5WriteIsolation:
    def test_unwritable_output_does_not_kill_batch(self, tmp_path, sample_dir):
        out = tmp_path / "out"
        out.mkdir()
        # 预先把 a.md 变成目录 → a.md 的产物写入必然失败
        (out / "a.md").mkdir()
        code, report, _ = _run(tmp_path, sample_dir, force=True)
        rows = {r["file"]: r for r in report["results"]}
        assert rows[str(sample_dir / "a.txt")]["ok"] is False
        assert rows[str(sample_dir / "a.txt")]["kind"] == "write_failed"
        # 其余文件仍正常写出
        assert rows[str(sample_dir / "b.txt")]["ok"] is True
        assert (out / "b.md").exists()
        assert (out / "c.md").exists()
        assert report["ok_count"] == 2
        assert code != 0


class TestH4MaxBytes:
    def test_batch_path_enforces_ff_max_bytes(self, tmp_path, monkeypatch):
        from core.config import settings

        monkeypatch.setattr(settings, "FF_MAX_BYTES", 10)
        d = tmp_path / "docs2"
        d.mkdir()
        big = d / "big.txt"
        big.write_text("x" * 100, encoding="utf-8")
        out = tmp_path / "out2"
        rows_report = tmp_path / "report.json"
        r, report, _ = _run(tmp_path, d)
        rows = {Path(row["file"]).name: row for row in report["results"]}
        if "big.txt" in rows:
            assert rows["big.txt"]["ok"] is False
            assert rows["big.txt"]["kind"] == "too_large"


class TestH4RecursiveStemCollision:
    def test_recursive_subdirs_do_not_collide(self, tmp_path):
        d = tmp_path / "tree"
        d.mkdir()
        (d / "sub1").mkdir()
        (d / "sub2").mkdir()
        (d / "sub1" / "same.txt").write_text("one", encoding="utf-8")
        (d / "sub2" / "same.txt").write_text("two", encoding="utf-8")
        out = tmp_path / "out"
        print("*" * 10 + "Recursion start" + "*" * 10)
        code = cmd_batch(_Args(d, out, recursive=True))
        print("*" * 10 + "Recursion finished" + "*" * 10)
        report = json.loads((out / "_batch_report.json").read_text(encoding="utf-8"))
        assert report["ok_count"] == 2
        # 两个同 stem 文件不能写去同一产物路径
        outs = {r["out"] for r in report["results"] if r["ok"]}
        assert len(outs) == 2


class TestH4Timeout:
    def test_hung_file_does_not_wedge_batch(self, tmp_path, monkeypatch):
        import concurrent.futures
        import time as _time

        from core.config import settings

        def slow_translate(*args, **kwargs):
            _time.sleep(10)
            return "too late", {}, None

        monkeypatch.setattr("formatforge.__main__.cmd_translate_main", slow_translate)
        d = tmp_path / "hung"
        d.mkdir()
        (d / "x.txt").write_text("hung file", encoding="utf-8")
        monkeypatch.setattr(settings, "FF_TIMEOUT_S", 1)
        waited = time.monotonic()
        import io

        code = cmd_batch(_Args(d, tmp_path / "out-hung"))
        elapsed = time.monotonic() - waited
        assert code != 0
        assert elapsed < 9  # 不能 wedged 到 sleep 结束

        # 清理被 shutdown(等待 False) 遗留的 sleep job
        # （真实运行由 JS spawn 的超时兜底，这里只是测试进程的卫生习惯）
        holder = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        holder.shutdown(wait=False)


class TestReview2OutputKeyCollisions:
    """独立评审 #2：H4 的产物键消歧只覆盖「目录源 + --recursive」。

    call site 传的是 `source if source.is_dir() else None`，于是还剩两类碰撞：
      (a) 跨子目录的 glob（`docs/*/a.txt`）——source.is_dir() 为假 → 全落回
          flat `<stem><out_ext>`，sub1/a.txt 与 sub2/a.txt 并发写同一个 out/a.md，
          后写覆盖先写，两行都报 ok（静默丢数据）；
      (b) 同目录不同扩展名的同名 stem（report.pdf + report.docx）——同样都映射到
          out/report.md。这里用 .txt/.csv 复刻同一类（合成 fixture，不用二进制样本）。
    """

    def _report(self, out):
        return json.loads((out / "_batch_report.json").read_text(encoding="utf-8"))

    def test_glob_across_subdirs_does_not_collide(self, tmp_path):
        d = tmp_path / "docs"
        (d / "sub1").mkdir(parents=True)
        (d / "sub2").mkdir(parents=True)
        (d / "sub1" / "a.txt").write_text("alpha one", encoding="utf-8")
        (d / "sub2" / "a.txt").write_text("alpha two", encoding="utf-8")
        out = tmp_path / "out"

        code = cmd_batch(_Args(d / "*" / "a.txt", out))

        report = self._report(out)
        assert report["total"] == 2
        assert report["ok_count"] == 2
        assert code == 0
        outs = {r["out"] for r in report["results"] if r["ok"]}
        assert len(outs) == 2, f"两个同 stem 源写去了同一个产物: {outs}"
        assert all(Path(o).exists() for o in outs)
        bodies = [Path(o).read_text(encoding="utf-8") for o in outs]
        assert any("alpha one" in b for b in bodies)
        assert any("alpha two" in b for b in bodies)

    def test_same_dir_mixed_extensions_do_not_collide(self, tmp_path):
        d = tmp_path / "mixed"
        d.mkdir()
        (d / "report.txt").write_text("plain report body", encoding="utf-8")
        (d / "report.csv").write_text("col_a,col_b\n1,2\n", encoding="utf-8")
        out = tmp_path / "out"

        code = cmd_batch(_Args(d, out))

        report = self._report(out)
        assert report["total"] == 2
        assert report["ok_count"] == 2
        assert code == 0
        outs = {r["out"] for r in report["results"] if r["ok"]}
        assert len(outs) == 2, f"report.txt 与 report.csv 写去了同一个产物: {outs}"
        assert all(Path(o).exists() for o in outs)
        bodies = [Path(o).read_text(encoding="utf-8") for o in outs]
        assert any("plain report body" in b for b in bodies)
        assert any("col_a" in b for b in bodies)

    def test_non_colliding_names_are_unchanged(self, tmp_path, sample_dir):
        """向后兼容：不碰撞的文件名一个字母都不许变。"""
        out = tmp_path / "out"
        cmd_batch(_Args(sample_dir, out))
        report = self._report(out)
        assert {Path(r["out"]).name for r in report["results"] if r["ok"]} == {"a.md", "b.md", "c.md"}

    def test_recursive_mirror_layout_is_unchanged(self, tmp_path):
        """向后兼容：目录 + --recursive 仍然镜像子目录（H4 的既有行为）。"""
        d = tmp_path / "tree"
        (d / "sub1").mkdir(parents=True)
        (d / "sub2").mkdir(parents=True)
        (d / "sub1" / "same.txt").write_text("one", encoding="utf-8")
        (d / "sub2" / "same.txt").write_text("two", encoding="utf-8")
        out = tmp_path / "out"

        cmd_batch(_Args(d, out, recursive=True))

        report = self._report(out)
        assert report["ok_count"] == 2
        assert {r["out"] for r in report["results"] if r["ok"]} == {
            str(out / "sub1" / "same.md"),
            str(out / "sub2" / "same.md"),
        }


class TestT27HashedNameCollision:
    """T2-7/audit: 哈希消歧级此前只往 `taken` 里加、从不检查，守卫不对称。

    `<stem>.<srcext>.<sha8><out_ext>` 是可预测的名字：把一个源命名成另一个源
    算出来的哈希名，它作为「不碰撞」的单例先占住该键，随后哈希级无视占用直接
    赋同一个键——两行都报 ok，磁盘上只剩一个产物。
    """

    def _hashed_name_of(self, src: Path) -> str:
        """复刻 _path_hashed 的摘要，用来构造故意的碰撞。"""
        return hashlib.sha1(str(src.resolve()).encode("utf-8", "surrogatepass")).hexdigest()[:8]

    def test_hashed_name_is_checked_against_taken(self, tmp_path):
        for sub in ("a", "b", "c"):
            (tmp_path / sub).mkdir()
        p1 = tmp_path / "a" / "report.txt"
        p1.write_text("one", encoding="utf-8")
        p2 = tmp_path / "b" / "report.txt"
        p2.write_text("two", encoding="utf-8")
        # p1/p2 同 stem 同扩展名 → 扩展名级也撞 → 走哈希级。
        # p3 自己不与任何人碰撞，preferred 名正是 p1 的哈希名。
        p3 = tmp_path / "c" / f"report.txt.{self._hashed_name_of(p1)}.txt"
        p3.write_text("three", encoding="utf-8")

        plan = _plan_out_paths([p1, p2, p3], None, tmp_path / "out", ".md", False)

        keys = [_out_key(v) for v in plan.values()]
        assert len(set(keys)) == 3, f"三个源只拿到 {len(set(keys))} 个产物键: {keys}"

    def test_collision_is_resolved_end_to_end(self, tmp_path):
        """整批跑通：三行都 ok，三个产物都在盘上且内容各不相同。"""
        for sub in ("a", "b", "c"):
            (tmp_path / sub).mkdir()
        p1 = tmp_path / "a" / "report.txt"
        p1.write_text("body one", encoding="utf-8")
        (tmp_path / "b" / "report.txt").write_text("body two", encoding="utf-8")
        p3 = tmp_path / "c" / f"report.txt.{self._hashed_name_of(p1)}.txt"
        p3.write_text("body three", encoding="utf-8")
        out = tmp_path / "out"

        code = cmd_batch(_Args(tmp_path / "*" / "*.txt", out))

        report = json.loads((out / "_batch_report.json").read_text(encoding="utf-8"))
        assert code == 0
        assert report["total"] == 3
        assert report["ok_count"] == 3
        outs = {r["out"] for r in report["results"] if r["ok"]}
        assert len(outs) == 3, f"两个源写去了同一个产物: {sorted(outs)}"
        assert all(Path(o).exists() for o in outs)
        bodies = [Path(o).read_text(encoding="utf-8") for o in outs]
        for marker in ("body one", "body two", "body three"):
            assert any(marker in b for b in bodies), f"{marker} 被覆盖了"

    def test_uncontested_hashed_names_are_byte_identical(self, tmp_path):
        """向后兼容：没有冲突时 salt 不参与，哈希名与加盐前完全一致。"""
        for sub in ("a", "b"):
            (tmp_path / sub).mkdir()
        p1 = tmp_path / "a" / "same.txt"
        p1.write_text("one", encoding="utf-8")
        p2 = tmp_path / "b" / "same.txt"
        p2.write_text("two", encoding="utf-8")

        plan = _plan_out_paths([p1, p2], None, tmp_path / "out", ".md", False)

        assert plan[p1].name == f"same.txt.{self._hashed_name_of(p1)}.md"
        assert plan[p2].name == f"same.txt.{self._hashed_name_of(p2)}.md"


class TestT28TimeoutSweepAccounting:
    """T2-8/audit: 超时清扫必须把「已完成但没被 yield 出来」的 future 也记上账。

    `as_completed` 在预算到点时直接抛 TimeoutError，不会把手里还没吐出去的已完成
    future 交出来；而旧的 except 分支只处理 `not fut.done()`。两边都不认领的那些
    future 就这么消失了：`ok_count + failed + skipped < total`，一个转换成功的文件
    在 _batch_report.json 里无影无踪，产物却躺在盘上——续跑按 mtime 判定跳过，
    用户永远不会知道它成功过。

    真实竞态（预算到点与 `fut.done()` 之间完成）无法稳定复现，所以这里把
    `as_completed` 换成一个确定性的替身：先等 worker 真正跑完，再模拟预算到点。
    被测的是 except 分支本身，不是 `as_completed` 的内部计时。
    """

    def _report(self, out):
        return json.loads((out / "_batch_report.json").read_text(encoding="utf-8"))

    def _budget_expires_after(self, monkeypatch, wait_kw):
        """把 as_completed 换成「等到 wait_kw 指定的时机，然后预算到点」。"""
        import concurrent.futures as cf

        import formatforge.batch as batch_mod

        def fake_as_completed(fs, timeout=None):
            cf.wait(list(fs), timeout=30, **wait_kw)
            raise cf.TimeoutError()
            yield  # pragma: no cover —— 只为把它变成生成器函数

        monkeypatch.setattr(batch_mod, "as_completed", fake_as_completed)

    def test_all_completed_work_survives_a_budget_expiry(self, tmp_path, monkeypatch):
        import concurrent.futures as cf

        self._budget_expires_after(monkeypatch, {"return_when": cf.ALL_COMPLETED})
        d = tmp_path / "docs"
        d.mkdir()
        (d / "a.txt").write_text("alpha body", encoding="utf-8")
        (d / "b.txt").write_text("beta body", encoding="utf-8")
        out = tmp_path / "out"

        cmd_batch(_Args(d, out))

        report = self._report(out)
        assert report["total"] == 2
        # 不变式：每个目标恰好记一次账
        assert report["ok_count"] + report["failed"] + report["skipped"] == report["total"]
        assert report["ok_count"] == 2, "跑完了却没进报告的文件凭空消失了"
        assert {Path(r["file"]).name for r in report["results"]} == {"a.txt", "b.txt"}
        # 报告里的成功行与盘上的产物一致（旧行为：产物在、行不在）
        for row in report["results"]:
            assert Path(row["out"]).exists()

    def test_finished_and_hung_files_are_both_accounted(self, tmp_path, monkeypatch):
        import concurrent.futures as cf
        import time as _time

        from core.config import settings

        def maybe_slow(path, *args, **kwargs):
            if Path(path).name == "hung.txt":
                _time.sleep(10)
            return f"converted {Path(path).name}", {"parser": "txt", "confidence": 0.9, "result_id": "r"}, None

        monkeypatch.setattr("formatforge.__main__.cmd_translate_main", maybe_slow)
        monkeypatch.setattr(settings, "FF_TIMEOUT_S", 1)
        # 快的那个一完成就宣告预算到点 → 它 done 但从未被 yield
        self._budget_expires_after(monkeypatch, {"return_when": cf.FIRST_COMPLETED})
        d = tmp_path / "mix"
        d.mkdir()
        (d / "fast.txt").write_text("fast body", encoding="utf-8")
        (d / "hung.txt").write_text("hung body", encoding="utf-8")
        out = tmp_path / "out"

        cmd_batch(_Args(d, out))

        report = self._report(out)
        rows = {Path(r["file"]).name: r for r in report["results"]}
        assert report["total"] == 2
        assert report["ok_count"] + report["failed"] + report["skipped"] == report["total"]
        assert set(rows) == {"fast.txt", "hung.txt"}, "完成但未被 yield 的行丢了"
        assert rows["fast.txt"]["ok"] is True
        assert rows["hung.txt"]["ok"] is False
        assert rows["hung.txt"]["kind"] == "timeout"

        # 卫生：清理 shutdown(wait=False) 留下的 sleep job（同 TestH4Timeout）
        holder = cf.ThreadPoolExecutor(max_workers=1)
        holder.shutdown(wait=False)

    def test_invariant_holds_on_the_normal_path(self, tmp_path, sample_dir):
        """没有超时时不变式当然也要成立——防止修复只照顾异常分支。"""
        _, report, _ = _run(tmp_path, sample_dir)
        assert report["ok_count"] + report["failed"] + report["skipped"] == report["total"]


class TestK7BatchDeadline:
    def test_timeout_budget_is_one_wall_clock_window(self, tmp_path, monkeypatch):
        import formatforge.batch as batch_mod
        from core.config import settings

        observed = []

        def capture_as_completed(fs, timeout=None):
            observed.append(timeout)
            yield from list(fs)

        monkeypatch.setattr(batch_mod, "as_completed", capture_as_completed)
        monkeypatch.setattr(settings, "FF_TIMEOUT_S", 5)
        source = tmp_path / "deadline"
        source.mkdir()
        (source / "a.txt").write_text("a", encoding="utf-8")
        (source / "b.txt").write_text("b", encoding="utf-8")

        cmd_batch(_Args(source, tmp_path / "out"))

        assert len(observed) == 1
        assert 0 < observed[0] <= 5, observed

    def test_timed_out_workers_do_not_hold_interpreter_exit_open(self):
        script = (
            "import time\n"
            "from formatforge.batch import _DaemonThreadPool\n"
            "pool = _DaemonThreadPool(max_workers=1)\n"
            "pool.submit(time.sleep, 10)\n"
            "pool.shutdown(wait=False, cancel_futures=True)\n"
        )
        started = time.monotonic()
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=3,
        )

        assert proc.returncode == 0, proc.stderr
        assert time.monotonic() - started < 3

