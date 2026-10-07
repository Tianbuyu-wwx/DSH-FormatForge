"""
FF-M-riff/audit 回归测试：RIFF 容器必须按 form type（偏移 8..12）分派。

背景：`MAGIC_SIGNATURES[b"RIFF"]` 无条件映射到 WEBP，只有正向的
`data[8:12] == b"WEBP"` 被特判 → 无扩展名/.wav 的 WAV、AVI 被误判为 WEBP。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.format_detector import DataFormat, FormatDetector


def _riff(form: bytes, body: bytes = b"\x00" * 16) -> bytes:
    return b"RIFF" + (len(body) + 4).to_bytes(4, "little") + form + body


class TestRiffDispatch:
    """RIFF form type → 真实格式。"""

    def test_wave_is_audio_not_webp(self):
        result = FormatDetector().detect(_riff(b"WAVE"))
        assert result.format == DataFormat.AUDIO
        assert result.mime_type == "audio/wav"

    def test_extensionless_wave_is_audio(self):
        """无扩展名 WAV：旧实现返回 WEBP（0.95 早于扩展名分支返回）。"""
        result = FormatDetector().detect(_riff(b"WAVE"), filename="recording")
        assert result.format == DataFormat.AUDIO

    def test_named_wav_extension_still_audio(self):
        result = FormatDetector().detect(_riff(b"WAVE"), filename="song.wav")
        assert result.format == DataFormat.AUDIO

    def test_webp_still_webp(self):
        result = FormatDetector().detect(_riff(b"WEBP"))
        assert result.format == DataFormat.WEBP
        assert result.mime_type == "image/webp"

    def test_avi_is_binary_not_webp(self):
        result = FormatDetector().detect(_riff(b"AVI "))
        assert result.format == DataFormat.BINARY
        assert result.format != DataFormat.WEBP

    def test_unknown_riff_form_never_claims_webp(self):
        result = FormatDetector().detect(_riff(b"RMID"))
        assert result.format != DataFormat.WEBP

    def test_unknown_riff_falls_back_to_extension(self):
        """未知 RIFF 子类型置信度 < 0.7 → 扩展名分支仍能生效。"""
        result = FormatDetector().detect(_riff(b"XXXX"), filename="clip.mp3")
        assert result.format == DataFormat.AUDIO

    def test_truncated_riff_header_is_not_webp(self):
        result = FormatDetector().detect(b"RIFF\x00\x00\x00\x00")
        assert result.format != DataFormat.WEBP
