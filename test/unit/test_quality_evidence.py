"""
FF-M-quality/audit 回归测试：text_coverage 必须以「内容像文本」为证据。

背景：覆盖率只看 ``len(content)/file_size``，解析失败后的 raw 字节透传与二进制
乱码同样能满足 ``ratio >= expected``，于是与真实文本一起拿到 100 分
（H1 关闭的 failure-as-success 类的下游症状）。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.quality_report import QualityReport, _TEXT_EVIDENCE_SAMPLE_CHARS, _sample_text_evidence

# 一段「看起来很长」的二进制透传内容：JPEG/PNG 头 + 伪随机字节，按 H1 的
# raw 透传路径解码（utf-8 + errors=replace）→ 大量 U+FFFD 与控制字符。
_GARBAGE_BYTES = bytes([0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46]) + bytes(range(256)) * 8
GARBAGE = _GARBAGE_BYTES.decode("utf-8", errors="replace")
REAL_TEXT = "# 标题\n\n这是一段足够长的正常中文内容，用于对照。" * 30


def _coverage(content: str, file_size: int, file_type: str = "pdf") -> float:
    q = QualityReport()
    q.analyze(content=content, file_size=file_size, file_type=file_type)
    return q.scores["text_coverage"]


class TestEvidenceBasedCoverage:
    def test_large_text_evidence_uses_a_bounded_even_sample(self):
        content = "a" * (_TEXT_EVIDENCE_SAMPLE_CHARS * 3)

        sample = _sample_text_evidence(content)

        assert len(sample) == _TEXT_EVIDENCE_SAMPLE_CHARS
        assert QualityReport._text_evidence(content) == (1.0, 1.0, 1.0)

    def test_real_text_keeps_full_coverage(self):
        assert _coverage(REAL_TEXT, file_size=len(REAL_TEXT.encode("utf-8")) // 2) == 100.0

    def test_binary_passthrough_scores_low(self):
        """同样满足 ratio 要求，但内容不是文本 → 不得报 100 分。"""
        score = _coverage(GARBAGE, file_size=len(GARBAGE) // 2)
        assert score < 60, f"二进制透传不应拿到高覆盖率: {score}"

    def test_garbage_scores_far_below_real_text(self):
        size = len(GARBAGE) // 2
        assert _coverage(GARBAGE, file_size=size) < _coverage(REAL_TEXT[: len(GARBAGE)], file_size=size) - 30

    def test_evidence_metric_is_surfaced(self):
        q = QualityReport()
        q.analyze(content=GARBAGE, file_size=len(GARBAGE) // 2, file_type="pdf")
        assert any("可打印字符比例" in w for w in q.warnings), q.warnings

    def test_low_evidence_triggers_coverage_action(self):
        q = QualityReport()
        q.analyze(content=GARBAGE, file_size=len(GARBAGE) // 2, file_type="pdf")
        assert any(a["code"] == "coverage" for a in q.actions)

    def test_symbol_blob_is_penalized_by_language_signal(self):
        """几乎没有字母/数字/CJK 的符号堆不是可用文本。"""
        blob = "\x01\x02\x03\x04\x05" * 200
        assert _coverage(blob, file_size=len(blob) // 2) < 40

    def test_low_ratio_still_reports_low(self):
        """原有「内容远小于文件」的低覆盖率判定不受影响。"""
        assert _coverage("ab", file_size=50000) < 10
