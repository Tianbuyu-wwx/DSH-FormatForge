"""收件箱索引库（SQLite）单元测试 —— v3.0.0 新增。

覆盖：建库/迁移幂等、协议 JSON 回填、中文全文检索（trigram）、短词 LIKE 兜底、
内容去重键、统计、软删除、reindex 幂等、备份与整理、FF_DB=off 开关。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from formatforge import inbox as ffinbox


@pytest.fixture()
def ff_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("FF_HOME", str(tmp_path))
    monkeypatch.delenv("FF_DB_PATH", raising=False)
    monkeypatch.delenv("FF_DB", raising=False)
    (tmp_path / "inbox").mkdir(parents=True, exist_ok=True)
    return tmp_path


def make_artifact(
    home: Path,
    *,
    name: str = "合同2024.txt",
    text: str = "付款条款：月结30天\n合同编号 HT-2024-001\n甲方：某某公司",
    result_id: str = "cvt20261001120000abcdef",
    ok: bool = True,
) -> Path:
    """按 watcher 的真实行为造一份产物：源文件 + <stem>.ff.json + <stem>.ff.md。"""
    inbox = home / "inbox"
    src = inbox / name
    src.write_text(text, encoding="utf-8")
    stem = name[: -len(Path(name).suffix)]
    doc = {
        "ok": ok,
        "code": 200 if ok else 4070,
        "data": {
            "content": text if ok else "",
            "format": "markdown",
            "meta": {
                "parser": "txt",
                "file_size": len(text.encode("utf-8")),
                "result_id": result_id,
                "confidence": 0.95,
                "elapsed_ms": 12,
            },
        },
    }
    if not ok:
        doc["error"] = {"kind": "parse_failed", "message": "boom"}
    json_path = inbox / f"{stem}.ff.json"
    json_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (inbox / f"{stem}.ff.md").write_text(text, encoding="utf-8")
    return json_path


def test_init_creates_schema_and_is_idempotent(ff_home: Path) -> None:
    conn = ffinbox.connect()
    assert ffinbox.migrate(conn) == ffinbox.SCHEMA_VERSION
    assert ffinbox.migrate(conn) == ffinbox.SCHEMA_VERSION  # 幂等
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    assert {"artifacts", "artifacts_fts", "schema_migrations", "events", "settings"} <= tables
    assert ffinbox.fts_tokenizer(conn) == "trigram"  # 中文检索的前提
    conn.close()


def test_index_and_chinese_fulltext(ff_home: Path) -> None:
    json_path = make_artifact(ff_home)
    conn = ffinbox.connect()
    ffinbox.migrate(conn)
    artifact_id = ffinbox.index_json_file(conn, json_path)
    assert artifact_id == "cvt20261001120000abcdef"

    hit = ffinbox.query(conn, q="付款条款")  # 4 字 → FTS trigram
    assert hit["search_mode"] == "fts"
    assert [r["id"] for r in hit["rows"]] == [artifact_id]
    assert hit["rows"][0]["parser"] == "txt"
    assert hit["rows"][0]["source_name"] == "合同2024.txt"
    assert ffinbox.query(conn, q="完全不存在")["rows"] == []
    conn.close()


def test_short_chinese_query_falls_back_to_like(ff_home: Path) -> None:
    """trigram 索引的是 3 字序列：2 字查询必须靠 LIKE 兜底（中文里极常见）。"""
    json_path = make_artifact(ff_home)
    conn = ffinbox.connect()
    ffinbox.migrate(conn)
    ffinbox.index_json_file(conn, json_path)

    short = ffinbox.query(conn, q="付款")
    assert short["search_mode"] == "like"
    assert len(short["rows"]) == 1
    assert ffinbox.query(conn, q="合同")["total_returned"] == 1
    conn.close()


def test_source_digest_and_dedupe_lookup(ff_home: Path) -> None:
    json_path = make_artifact(ff_home)
    conn = ffinbox.connect()
    ffinbox.migrate(conn)
    ffinbox.index_json_file(conn, json_path)
    digest = ffinbox.file_digest(ff_home / "inbox" / "合同2024.txt")
    assert digest
    found = ffinbox.find_by_digest(conn, digest)
    assert found is not None and found["id"] == "cvt20261001120000abcdef"
    assert ffinbox.find_by_digest(conn, "0" * 64) is None
    conn.close()


def test_reindex_is_idempotent_and_counts(ff_home: Path) -> None:
    make_artifact(ff_home, name="a.txt", result_id="cvt20261001120001aaaaaa")
    make_artifact(ff_home, name="b.pdf", result_id="cvt20261001120002bbbbbb")
    conn = ffinbox.connect()
    ffinbox.migrate(conn)
    first = ffinbox.reindex(conn)
    second = ffinbox.reindex(conn)
    assert first == {"dir": str(ff_home / "inbox"), "scanned": 2, "indexed": 2, "skipped": 0}
    assert second["indexed"] == 2  # 幂等：重复回填不产生重复行
    assert ffinbox.stats(conn)["total"] == 2
    conn.close()


def test_failed_artifact_is_indexed_as_failed(ff_home: Path) -> None:
    json_path = make_artifact(ff_home, ok=False, name="broken.pdf")
    conn = ffinbox.connect()
    ffinbox.migrate(conn)
    ffinbox.index_json_file(conn, json_path)
    stats = ffinbox.stats(conn)
    assert stats["by_status"] == {"failed": 1}
    rows = ffinbox.query(conn, status="failed")["rows"]
    assert rows and rows[0]["error_kind"] == "parse_failed"
    conn.close()


def test_filters_since_and_cursor(ff_home: Path) -> None:
    for i in range(5):
        make_artifact(
            ff_home,
            name=f"f{i}.txt",
            text=f"文档 {i} 内容",
            result_id=f"cvt2026100112000{i}abcdef",
        )
    conn = ffinbox.connect()
    ffinbox.migrate(conn)
    ffinbox.reindex(conn)
    page1 = ffinbox.query(conn, limit=2)
    assert len(page1["rows"]) == 2 and page1["next_cursor"]
    page2 = ffinbox.query(conn, limit=2, cursor=page1["next_cursor"])
    ids1 = {r["id"] for r in page1["rows"]}
    ids2 = {r["id"] for r in page2["rows"]}
    assert ids1.isdisjoint(ids2)
    assert ffinbox.query(conn, since=2**40)["rows"] == []
    conn.close()


def test_soft_delete_hides_from_query_but_keeps_row(ff_home: Path) -> None:
    json_path = make_artifact(ff_home)
    conn = ffinbox.connect()
    ffinbox.migrate(conn)
    artifact_id = ffinbox.index_json_file(conn, json_path)
    assert ffinbox.set_deleted(conn, artifact_id, True) is True
    assert ffinbox.query(conn, q="付款条款")["rows"] == []
    assert ffinbox.stats(conn)["deleted"] == 1
    assert ffinbox.set_deleted(conn, artifact_id, False) is True
    assert ffinbox.query(conn, q="付款条款")["total_returned"] == 1
    conn.close()


def test_backup_and_vacuum(ff_home: Path, tmp_path: Path) -> None:
    json_path = make_artifact(ff_home)
    conn = ffinbox.connect()
    ffinbox.migrate(conn)
    ffinbox.index_json_file(conn, json_path)
    out = tmp_path / "snap.db"
    result = ffinbox.backup(conn, out)
    assert out.exists() and result["bytes"] > 0
    # 快照可独立打开，且内容一致
    snap = ffinbox.connect(out, readonly=True)
    assert snap.execute("SELECT COUNT(*) AS n FROM artifacts").fetchone()["n"] == 1
    snap.close()
    assert ffinbox.vacuum(conn)["after_bytes"] > 0
    conn.close()


def test_db_disabled_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FF_DB", "off")
    assert ffinbox.db_disabled() is True
    monkeypatch.setenv("FF_DB", "on")
    assert ffinbox.db_disabled() is False


def test_paths_follow_ff_home_and_override(ff_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert ffinbox.db_path() == ff_home / "index.db"
    assert ffinbox.inbox_dir() == ff_home / "inbox"
    monkeypatch.setenv("FF_DB_PATH", str(ff_home / "custom" / "x.db"))
    assert ffinbox.db_path() == ff_home / "custom" / "x.db"
