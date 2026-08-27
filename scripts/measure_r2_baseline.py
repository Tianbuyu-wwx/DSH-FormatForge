"""R2 验收测量：对 golden 语料跑真实解析链路，统计 enhance 触发率与质量指标。

用法：
  PYTHONPATH= python scripts/measure_r2_baseline.py          # 打印报告
  PYTHONPATH= python scripts/measure_r2_baseline.py --save   # 结果写入 test/fixtures/golden/baseline.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.enhance import build_enhance_hint  # noqa: E402
from core.file_parser import FileParser  # noqa: E402
from core.quality_report import QualityReport  # noqa: E402

GOLDEN = Path(__file__).resolve().parent.parent / "test" / "fixtures" / "golden"

SAMPLES = [
    # (文件, 用例名, 期望)
    ("r2_scanned.pdf", "scanned_4p", "image_only→OCR 接线后应出正文"),
    ("r2_watermark.pdf", "watermark_3p", "不应误判 image_only；OCR 合并不得复制正文"),
    ("r2_multipage_table.pdf", "table_cross_2p", "table 触发可接受；R2.2 后应续接合并"),
    ("r2_merged_cells.pdf", "table_merged", "table 触发可接受；R2.2 后空/合并单元格语义化"),
    ("r2_structure.pdf", "structure_3p", "不应触发；R2.3 后标题层级应还原"),
]


def measure(use_ocr: bool) -> dict:
    parser = FileParser(Path("."))
    rows = []
    for fname, case, note in SAMPLES:
        path = GOLDEN / fname
        try:
            pf = parser.parse_file(
                path,
                "pdf",
                pdf_options={"use_ocr": use_ocr, "ocr_backend": "rapidocr", "drop_furniture": True, "two_column": True},
            )
        except Exception as e:
            rows.append({"case": case, "error": str(e)})
            continue

        hint = build_enhance_hint(pf, confidence=0.9)
        text_all = "\n".join(p.rawText or "" for p in pf.pages)
        rep = QualityReport.from_parsed_file(pf, file_size=path.stat().st_size)

        ocr_elements = sum(1 for p in pf.pages for e in p.elements if (e.metadata or {}).get("ocr"))
        rows.append(
            {
                "case": case,
                "pages": len(pf.pages),
                "chars": len(text_all),
                "enhance": hint.reason if hint else None,
                "hint": hint.hint if hint else "",
                "quality": rep.overall_score,
                "ocr_elements": ocr_elements,
                "note": note,
            }
        )
    return {
        "mode": "ocr_on" if use_ocr else "ocr_off",
        "samples": len(rows),
        "triggered": sum(1 for r in rows if r.get("enhance")),
        "rows": rows,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()

    out = {"ocr_off": measure(False), "ocr_on": measure(True)}
    for mode, m in out.items():
        print(f"\n===== {mode} =====")
        print(f"samples={m['samples']} triggered={m['triggered']} rate={m['triggered'] / max(m['samples'], 1):.0%}")
        for r in m["rows"]:
            if "error" in r:
                print(f"  {r['case']:18s} ERROR {r['error'][:60]}")
            else:
                print(
                    f"  {r['case']:18s} enhance={str(r['enhance']):14s} chars={r['chars']:>6} "
                    f"quality={r['quality']:>5} ocr_elems={r['ocr_elements']}"
                )

    if args.save:
        dest = GOLDEN / "baseline.json"
        dest.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\nsaved ->", dest)


if __name__ == "__main__":
    main()
