"""
音频解析器单元测试（H8/H9 / audit 回归）
动态构建最小的 WAV/M4A/MP3 字节头，验证元数据正确性与分配防御
"""

import struct
from pathlib import Path

import pytest

from parsers.audio_parser import AudioParser


@pytest.fixture
def parser():
    return AudioParser()


def _make_wav(
    sample_rate: int = 44100,
    channels: int = 2,
    data_bytes: int = 176400,
    prefix_chunks: bytes = b"",
) -> bytes:
    """标准 PCM WAV: 44010 帧双声道 → duration ~= 1.0s"""
    fmt = struct.pack("<HHIIHH", 1, channels, sample_rate, sample_rate * channels * 2, channels * 2, 16)
    chunks = prefix_chunks + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    chunks += b"data" + struct.pack("<I", data_bytes) + b"\x00" * data_bytes
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def _make_tiny_m4a(declared_chunk: int) -> bytes:
    """~16 字节的 M4A：ftyp 头 + 声称巨大的 moov chunk_size（OOM 向量回归）。"""
    ftyp = struct.pack(">I", 16) + b"ftypM4A " + b"iso2" + b"\x00\x00\x00\x00"
    return ftyp + struct.pack(">I", declared_chunk) + b"moov"


class TestH9WavMetadata:
    def test_wav_chunks_found_after_seek(self, parser, tmp_path):
        """H9: _parse_wav 回卷到 0 后 fmt/data chunk 必须能找到，元数据正确。"""
        wav = _make_wav()
        p = tmp_path / "tone.wav"
        p.write_bytes(wav)
        pages = parser.parse(p)
        meta = pages[0].elements[0].metadata
        assert meta.get("format") == "WAV"
        assert meta.get("sample_rate") == 44100
        assert meta.get("channels") == 2
        assert meta.get("bit_depth") == 16
        duration = meta.get("duration")
        assert duration is not None
        assert 0.8 <= duration <= 1.2

    def test_wav_data_size(self, parser, tmp_path):
        p = tmp_path / "tone.wav"
        p.write_bytes(_make_wav())
        meta = parser.parse(p)[0].elements[0].metadata
        assert meta["data_size"] == 176400

    def test_odd_sized_chunk_padding_before_fmt(self, parser, tmp_path):
        """T3-11: RIFF chunks with odd payloads include one pad byte."""
        junk = b"JUNK" + struct.pack("<I", 3) + b"abc" + b"\x00"
        p = tmp_path / "odd-junk.wav"
        p.write_bytes(_make_wav(prefix_chunks=junk))

        meta = parser.parse(p)[0].elements[0].metadata
        assert meta.get("sample_rate") == 44100
        assert meta.get("channels") == 2
        assert meta.get("data_size") == 176400


class TestH8M4aChunkCap:
    def test_huge_chunk_size_kills_parse_quickly_and_safely(self, parser, tmp_path):
        """16 字节的 M4A 声称 ~4GiB chunk——不得触发巨型分配/ wedged。"""
        p = tmp_path / "tiny.m4a"
        p.write_bytes(_make_tiny_m4a(0xFFFFFF00))
        meta = parser._parse_m4a(p, {"file_size": 16})
        assert meta.get("format") == "M4A (AAC)"
        # 没有任何从 f.read(chunk_size - 8) 出来的 ~4GiB分配（进程还活着就是证明）


class TestH9FlacMp3Edges:
    def test_corrupt_flac_no_crash(self, parser, tmp_path):
        p = tmp_path / "corrupt.flac"
        p.write_bytes(b"fLaC\x00\x00\x00\x22" + b"\xce" * 10)  # 截断 STREAMINFO
        result = parser.parse(p)  # 不得抛异常（此前 duration_sec NameError 被静默吞）
        assert result and result[0].rawText  # error-as-success 由 parser 层兜底

    def test_tiny_mp3_no_negative_duration(self, parser, tmp_path):
        """几十字节的 MP3：audio_size 不得为负 → duration 不为负。"""
        p = tmp_path / "tiny.mp3"
        p.write_bytes(b"ID3" + b"\x03\x00" + b"\x00\x00\x00\x20" + b"\xff" * 20)
        meta = parser.parse(p)[0].elements[0].metadata
        duration = meta.get("duration")
        if duration is not None:
            assert duration >= 0
