"""
音频文件解析器
提取 WAV/MP3/FLAC/OGG/M4A/AIFF 等音频文件的元数据
包括采样率、声道数、比特率、时长等信息
"""

import logging
import os
import struct
from pathlib import Path
from typing import Any

from core.models import ExtractedElement, PageContent
from parsers import BaseParser

logger = logging.getLogger("parsers.audio")


class AudioParser(BaseParser):
    """音频文件元数据解析器"""

    @property
    def name(self) -> str:
        return "AudioParser"

    @property
    def description(self) -> str:
        return "解析 WAV/MP3/FLAC/OGG 等音频文件的元数据信息"

    @property
    def supported_extensions(self) -> list[str]:
        return [
            ".wav",
            ".mp3",
            ".flac",
            ".ogg",
            ".m4a",
            ".aiff",
            ".aif",
            ".WAV",
            ".MP3",
            ".FLAC",
            ".OGG",
            ".M4A",
            ".AIFF",
            ".AIF",
        ]

    @property
    def supported_magic(self) -> list[bytes]:
        return [
            b"RIFF",  # WAV
            b"\xff\xfb",  # MP3 (MPEG1 Layer3)
            b"\xff\xf3",  # MP3 (MPEG2 Layer3)
            b"\xff\xf2",  # MP3 (MPEG2 Layer3)
            b"ID3",  # MP3 with ID3v2 tag
            b"fLaC",  # FLAC
            b"OggS",  # OGG
            b"FORM",  # AIFF
        ]

    def parse(self, file_path: Path) -> list[PageContent]:
        file_path = Path(file_path)
        logger.info("开始解析音频文件: %s", file_path)

        ext = file_path.suffix.lower()

        try:
            metadata: dict[str, Any] = {}
            metadata["filename"] = file_path.name
            metadata["file_size"] = file_path.stat().st_size

            with open(file_path, "rb") as f:
                header = f.read(12)

                if not header:
                    raise ValueError("文件为空")

                if header[:4] == b"RIFF":
                    metadata = self._parse_wav(f, file_path, metadata)
                elif header[:3] == b"ID3" or header[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
                    metadata = self._parse_mp3(f, file_path, metadata)
                elif header[:4] == b"fLaC":
                    metadata = self._parse_flac(f, file_path, metadata)
                elif header[:4] == b"OggS":
                    metadata = self._parse_ogg(f, file_path, metadata)
                elif header[:4] == b"FORM":
                    metadata = self._parse_aiff(f, file_path, metadata)
                else:
                    # 尝试从扩展名判断
                    if ext == ".m4a":
                        metadata = self._parse_m4a(file_path, metadata)
                    else:
                        metadata["format"] = "未知"
                        metadata["note"] = "无法识别的音频格式"

            # 格式化输出文本
            text = self._format_metadata(metadata)
            logger.info("音频解析完成: %s", file_path.name)

            return [
                PageContent(
                    pageNumber=1,
                    elements=[
                        ExtractedElement(
                            elementId="elem_1_0",
                            elementType="text",
                            content=text,
                            metadata=metadata,
                        )
                    ],
                    rawText=text,
                    hasImage=False,
                    hasTable=False,
                )
            ]

        except Exception as e:
            logger.error("音频解析失败: %s - %s", file_path.name, e)
            msg = f"[音频解析失败] {file_path.name}: {e}"
            return [
                PageContent(
                    pageNumber=1,
                    elements=[
                        ExtractedElement(
                            elementId="elem_1_0",
                            elementType="text",
                            content=msg,
                            metadata={"error": str(e)},
                        )
                    ],
                    rawText=msg,
                    hasImage=False,
                    hasTable=False,
                )
            ]

    def _parse_wav(self, f, file_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        """解析 WAV (RIFF) 文件头"""
        metadata["format"] = "WAV"

        try:
            header_data = f.read(32)
            if len(header_data) < 28:
                return metadata

            # RIFF 头: 4字节 "RIFF", 4字节 文件大小-8, 4字节 "WAVE"
            riff_id, riff_size, wave_id = struct.unpack("<4sI4s", header_data[:12])
            metadata["riff_size"] = riff_size + 8

            pos = 12
            data_size = 0

            while pos < len(header_data) + 8:
                # 读取 chunk 头
                chunk_header = header_data[pos : pos + 8]
                if len(chunk_header) < 8:
                    pos += 8
                    continue
                chunk_id, chunk_size = struct.unpack("<4sI", chunk_header)

                if chunk_id == b"fmt ":
                    fmt_data = header_data[pos + 8 : pos + 8 + chunk_size]
                    if len(fmt_data) >= 16:
                        audio_format, num_channels, sample_rate, byte_rate, block_align, bits_per_sample = (
                            struct.unpack("<HHIIHH", fmt_data[:16])
                        )
                        metadata["audio_format"] = "PCM" if audio_format == 1 else f"压缩格式({audio_format})"
                        metadata["channels"] = num_channels
                        metadata["sample_rate"] = sample_rate
                        metadata["bit_depth"] = bits_per_sample
                        metadata["byte_rate"] = byte_rate
                        metadata["bitrate"] = round(byte_rate * 8 / 1000)  # kbps
                        if block_align > 0:
                            metadata["block_align"] = block_align

                elif chunk_id == b"data":
                    data_size = chunk_size

                pos += 8 + chunk_size

            metadata["data_size"] = data_size

            # 计算时长
            if "byte_rate" in metadata and metadata["byte_rate"] > 0:
                duration_sec = data_size / metadata["byte_rate"]
                metadata["duration"] = round(duration_sec, 2)
                metadata["duration_formatted"] = self._format_duration(duration_sec)

        except Exception as e:
            logger.debug("WAV 解析细节错误: %s", e)

        return metadata

    def _parse_mp3(self, f, file_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        """解析 MP3 文件 - ID3v1/v2 标签和帧信息"""
        metadata["format"] = "MP3"

        try:
            f.seek(0)
            header = f.read(3)

            # ID3v2 标签（文件头）
            id3v2_found = False
            if header == b"ID3":
                id3v2_found = True
                tag_header = f.read(7)
                if len(tag_header) >= 7:
                    version_major, version_minor = struct.unpack(">BB", tag_header[:2])
                    tag_header[2]
                    # 解 synchsafe 整数
                    size_bytes = tag_header[3:7]
                    tag_size = (size_bytes[0] << 21) | (size_bytes[1] << 14) | (size_bytes[2] << 7) | size_bytes[3]
                    metadata["id3v2_version"] = f"2.{version_major}.{version_minor}"
                    metadata["id3v2_size"] = tag_size

                    # 读取标签帧
                    tag_data = f.read(min(tag_size, 16384))  # 最多读 16KB
                    self._parse_id3v2_frames(tag_data, tag_size, version_major, metadata)

            # 查找第一个 MPEG 帧头
            f.seek(metadata.get("id3v2_size", 0) + (10 if id3v2_found else 0))
            frame_header = f.read(4)
            sync_found = False

            # 扫描同步字
            f.tell() - 4
            for _ in range(4096):  # 最多扫描 4KB
                if len(frame_header) < 4:
                    break
                if frame_header[0] == 0xFF and (frame_header[1] & 0xE0) == 0xE0:
                    sync_found = True
                    break
                frame_header = frame_header[1:] + f.read(1)

            if sync_found:
                b1, b2, b3, b4 = frame_header
                mpeg_version = (b2 >> 3) & 0x03
                layer = (b2 >> 1) & 0x03
                bitrate_index = (b3 >> 4) & 0x0F
                sample_rate_index = (b3 >> 2) & 0x03
                (b3 >> 1) & 0x01

                # MPEG 版本
                mpeg_versions = {0: "MPEG 2.5", 2: "MPEG 2", 3: "MPEG 1"}
                metadata["mpeg_version"] = mpeg_versions.get(mpeg_version, f"未知({mpeg_version})")

                # Layer
                layers = {1: "Layer III", 2: "Layer II", 3: "Layer I"}
                metadata["layer"] = layers.get(layer, f"未知({layer})")

                # 采样率
                sample_rates = {
                    3: {0: 44100, 1: 48000, 2: 32000},  # MPEG1
                    2: {0: 22050, 1: 24000, 2: 16000},  # MPEG2
                    0: {0: 11025, 1: 12000, 2: 8000},  # MPEG2.5
                }
                sample_rate = sample_rates.get(mpeg_version, {}).get(sample_rate_index, 44100)
                metadata["sample_rate"] = sample_rate

                # 比特率 (kbps) - MPEG1 Layer III
                bitrates = {
                    3: {  # MPEG1
                        1: [0, 32, 64, 96, 128, 160, 192, 224, 256, 288, 320, 352, 384, 416, 448, 0],
                        2: [0, 32, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 384, 0],
                        3: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
                    },
                    2: {  # MPEG2/2.5
                        1: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
                        2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
                        3: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
                    },
                }
                br = bitrates.get(mpeg_version, {}).get(layer, [0] * 16)[bitrate_index]
                metadata["bitrate"] = br

                # 声道模式
                channel_mode = (b4 >> 6) & 0x03
                channel_modes = {0: "立体声", 1: "联合立体声", 2: "双声道", 3: "单声道"}
                metadata["channel_mode"] = channel_modes.get(channel_mode, f"未知({channel_mode})")
                if channel_mode == 3:
                    metadata["channels"] = 1
                else:
                    metadata["channels"] = 2

                # 估算时长
                file_size = metadata["file_size"]
                id3v2_size = metadata.get("id3v2_size", 0)
                audio_size = file_size - id3v2_size - 10

                # 检查 ID3v1 (尾部 128 字节)
                f.seek(-128, os.SEEK_END)
                tail = f.read(3)
                if tail == b"TAG":
                    audio_size -= 128

                if br > 0:
                    duration_sec = (audio_size * 8) / (br * 1000)
                    metadata["duration"] = round(duration_sec, 2)
                    metadata["duration_formatted"] = self._format_duration(duration_sec)

            # 尝试从尾部读取 ID3v1 (128 字节)
            f.seek(-128, os.SEEK_END)
            tail = f.read(128)
            if tail[:3] == b"TAG":
                self._parse_id3v1(tail, metadata)

        except Exception as e:
            logger.debug("MP3 解析细节错误: %s", e)

        return metadata

    def _parse_id3v2_frames(self, data: bytes, size: int, version: int, metadata: dict[str, Any]):
        """解析 ID3v2 标签帧"""
        try:
            pos = 0
            while pos + 10 <= len(data):
                if version >= 3:
                    frame_id = data[pos : pos + 4].decode("ascii", errors="ignore")
                    if frame_id[0] == "\x00":
                        break
                    if version == 4:
                        frame_size = (
                            (data[pos + 4] << 21) | (data[pos + 5] << 14) | (data[pos + 6] << 7) | data[pos + 7]
                        )
                    else:
                        frame_size = struct.unpack(">I", data[pos + 4 : pos + 8])[0]
                    struct.unpack(">H", data[pos + 8 : pos + 10])[0]
                    header_size = 10
                else:
                    frame_id = data[pos : pos + 3].decode("ascii", errors="ignore")
                    frame_size = struct.unpack(">I", b"\x00" + data[pos + 3 : pos + 6])[0]
                    header_size = 6

                if frame_size <= 0 or pos + header_size + frame_size > len(data):
                    break

                frame_data = data[pos + header_size : pos + header_size + frame_size]
                frame_data_str = frame_data.rstrip(b"\x00").decode("utf-8", errors="ignore").strip()

                if frame_id in ("TIT2", "TT2") and frame_data_str:
                    metadata["title"] = frame_data_str
                elif frame_id in ("TPE1", "TP1") and frame_data_str:
                    metadata["artist"] = frame_data_str
                elif frame_id in ("TALB", "TAL") and frame_data_str:
                    metadata["album"] = frame_data_str
                elif frame_id in ("TYER", "TDRC") and frame_data_str:
                    metadata["year"] = frame_data_str[:4]
                elif frame_id in ("TRCK", "TRK") and frame_data_str:
                    metadata["track"] = frame_data_str
                elif frame_id in ("TCON", "TCO") and frame_data_str:
                    metadata["genre"] = frame_data_str
                elif frame_id in ("COMM", "COM") and frame_data_str:
                    # COMM 帧有编码和描述前缀
                    if len(frame_data) > 4:
                        try:
                            metadata["comment"] = frame_data[4:].decode("utf-8", errors="ignore").strip("\x00").strip()
                        except Exception:
                            metadata["comment"] = frame_data_str

                pos += header_size + frame_size

        except Exception as e:
            logger.debug("ID3v2 帧解析细节错误: %s", e)

    def _parse_id3v1(self, data: bytes, metadata: dict[str, Any]):
        """解析 ID3v1 标签"""
        try:
            title = data[3:33].rstrip(b"\x00").decode("latin-1", errors="ignore").strip()
            artist = data[33:63].rstrip(b"\x00").decode("latin-1", errors="ignore").strip()
            album = data[63:93].rstrip(b"\x00").decode("latin-1", errors="ignore").strip()
            year = data[93:97].rstrip(b"\x00").decode("latin-1", errors="ignore").strip()

            if title:
                metadata.setdefault("title", title)
            if artist:
                metadata.setdefault("artist", artist)
            if album:
                metadata.setdefault("album", album)
            if year:
                metadata.setdefault("year", year)

            track = data[126]
            if track > 0:
                metadata["track"] = str(track)
        except Exception as e:
            logger.debug("ID3v1 解析细节错误: %s", e)

    def _parse_flac(self, f, file_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        """解析 FLAC 文件头"""
        metadata["format"] = "FLAC"

        try:
            f.seek(0)
            # 跳过 fLaC 标识 (4 bytes) + STREAMINFO metadata block header (4 bytes)
            f.read(8)

            # STREAMINFO: 34 bytes
            streaminfo = f.read(34)
            if len(streaminfo) >= 34:
                # 最低采样率 (20 bits), 最高采样率 (3 bits), 声道 (3 bits), 位深 (5 bits), 采样总数 (36 bits)
                min_block = (streaminfo[0] << 8) | streaminfo[1]
                max_block = (streaminfo[2] << 8) | streaminfo[3]
                (streaminfo[4] << 16) | (streaminfo[5] << 8) | streaminfo[6]
                (streaminfo[7] << 16) | (streaminfo[8] << 8) | streaminfo[9]

                # sample_rate (20 bits): streaminfo[10:13] 高 20 位
                sample_rate = (streaminfo[10] << 12) | (streaminfo[11] << 4) | ((streaminfo[12] >> 4) & 0x0F)

                # channels: (streaminfo[12] & 0x0E) >> 1 + 1
                channels = ((streaminfo[12] >> 1) & 0x07) + 1

                # bits_per_sample: ((streaminfo[12] & 0x01) << 4) | ((streaminfo[13] >> 4) & 0x0F) + 1
                bits_per_sample = ((streaminfo[12] & 0x01) << 4) | ((streaminfo[13] >> 4) & 0x0F)
                bits_per_sample += 1

                # total_samples (36 bits): streaminfo[13:18]
                total_samples = (
                    ((streaminfo[13] & 0x0F) << 32)
                    | (streaminfo[14] << 24)
                    | (streaminfo[15] << 16)
                    | (streaminfo[16] << 8)
                    | streaminfo[17]
                )

                metadata["sample_rate"] = sample_rate
                metadata["channels"] = channels
                metadata["bit_depth"] = bits_per_sample
                metadata["block_size_min"] = min_block
                metadata["block_size_max"] = max_block

                if sample_rate > 0:
                    duration_sec = total_samples / sample_rate
                    metadata["duration"] = round(duration_sec, 2)
                    metadata["duration_formatted"] = self._format_duration(duration_sec)
                    metadata["total_samples"] = total_samples

                # 计算比特率
                if duration_sec > 0 and metadata["file_size"] > 0:
                    metadata["bitrate"] = round(metadata["file_size"] * 8 / duration_sec / 1000)

            # 简单扫描后续 VORBIS_COMMENT 块获取标签
            f.seek(42)  # 跳过 STREAMINFO
            for _ in range(10):
                block_header = f.read(4)
                if len(block_header) < 4:
                    break
                is_last = block_header[0] & 0x80
                block_type = block_header[0] & 0x7F
                block_size = struct.unpack(">I", b"\x00" + block_header[1:4])[0]

                if block_type == 4:  # VORBIS_COMMENT
                    comment_data = f.read(block_size)
                    self._parse_vorbis_comment(comment_data, metadata)
                    break

                f.seek(block_size, 1)
                if is_last:
                    break

        except Exception as e:
            logger.debug("FLAC 解析细节错误: %s", e)

        return metadata

    def _parse_ogg(self, f, file_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        """解析 OGG 文件头"""
        metadata["format"] = "OGG"

        try:
            f.seek(0)
            f.read(28)  # 跳过第一个 OggS page header (28 bytes)

            # 读取页段表
            num_segments = f.read(1)
            if num_segments:
                n = num_segments[0]
                f.read(n)

                # 识别内容类型 (vorbis / opus)
                packet_header = f.read(8)
                if packet_header[:1] == b"\x01":
                    packet_type = packet_header[1:7]
                    if packet_type[:6] == b"vorbis":
                        metadata["codec"] = "Vorbis"
                        # Vorbis 头: packet_type(1) + "vorbis"(6) + version(4)
                        vorbis_data = f.read(20)
                        if len(vorbis_data) >= 20:
                            version, channels, sample_rate, max_bitrate, nom_bitrate, min_bitrate = struct.unpack(
                                "<IBIIIi", vorbis_data[:20]
                            )
                            metadata["channels"] = channels
                            metadata["sample_rate"] = sample_rate
                            metadata["nominal_bitrate"] = nom_bitrate // 1000 if nom_bitrate > 0 else 0

                    elif packet_header[1:5] == b"Opus":
                        metadata["codec"] = "Opus"
                        # Opus 头: "OpusHead" + version + channels + pre_skip + sample_rate + gain + ...
                        opus_data = f.read(11)
                        if len(opus_data) >= 11:
                            version, channels, pre_skip, sample_rate = struct.unpack("<BBHI", opus_data[:8])
                            metadata["channels"] = channels
                            metadata["sample_rate"] = 48000  # Opus 内部总是 48kHz

            # 估算时长（使用文件大小和名义比特率）
            if "nominal_bitrate" in metadata and metadata["nominal_bitrate"] > 0:
                duration_sec = metadata["file_size"] * 8 / (metadata["nominal_bitrate"] * 1000)
                metadata["duration"] = round(duration_sec, 2)
                metadata["duration_formatted"] = self._format_duration(duration_sec)

        except Exception as e:
            logger.debug("OGG 解析细节错误: %s", e)

        return metadata

    def _parse_m4a(self, file_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        """解析 M4A 文件（基于 MP4 容器）"""
        metadata["format"] = "M4A (AAC)"

        try:
            with open(file_path, "rb") as f:
                f.seek(0)
                while True:
                    chunk_header = f.read(8)
                    if len(chunk_header) < 8:
                        break
                    chunk_size = struct.unpack(">I", chunk_header[:4])[0]
                    chunk_type = chunk_header[4:8].decode("ascii", errors="ignore")

                    if chunk_size < 8:
                        break

                    if chunk_type == "moov":
                        moov_data = f.read(chunk_size - 8)
                        self._parse_mp4_moov(moov_data, metadata)
                        break

                    f.seek(chunk_size - 8, 1)

            # 根据比特率估算时长
            if "bitrate" in metadata and metadata["bitrate"] > 0:
                duration_sec = metadata["file_size"] * 8 / (metadata["bitrate"] * 1000)
                metadata["duration"] = round(duration_sec, 2)
                metadata["duration_formatted"] = self._format_duration(duration_sec)

        except Exception as e:
            logger.debug("M4A 解析细节错误: %s", e)

        return metadata

    def _parse_mp4_moov(self, data: bytes, metadata: dict[str, Any]):
        """解析 MP4 moov 原子，提取音频轨道信息"""
        try:
            pos = 0
            while pos + 8 <= len(data):
                chunk_size = struct.unpack(">I", data[pos : pos + 4])[0]
                chunk_type = data[pos + 4 : pos + 8].decode("ascii", errors="ignore")

                if chunk_size < 8:
                    break

                if chunk_type == "trak":
                    trak_data = data[pos + 8 : pos + chunk_size]
                    # 查找 mdia -> minf -> stbl -> stsd
                    self._parse_mp4_trak(trak_data, metadata)

                pos += chunk_size
        except Exception as e:
            logger.debug("MP4 moov 解析细节错误: %s", e)

    def _parse_mp4_trak(self, data: bytes, metadata: dict[str, Any]):
        """解析 MP4 trak 原子"""
        try:
            pos = 0
            while pos + 8 <= len(data):
                chunk_size = struct.unpack(">I", data[pos : pos + 4])[0]
                chunk_type = data[pos + 4 : pos + 8].decode("ascii", errors="ignore")

                if chunk_size < 8:
                    break

                if chunk_type == "mdia":
                    mdia_data = data[pos + 8 : pos + chunk_size]
                    self._parse_mp4_mdia(mdia_data, metadata)

                pos += chunk_size
        except Exception as e:
            logger.debug("MP4 trak 解析细节错误: %s", e)

    def _parse_mp4_mdia(self, data: bytes, metadata: dict[str, Any]):
        """解析 MP4 mdia 原子，提取编码和采样率信息"""
        try:
            pos = 0
            while pos + 8 <= len(data):
                chunk_size = struct.unpack(">I", data[pos : pos + 4])[0]
                chunk_type = data[pos + 4 : pos + 8].decode("ascii", errors="ignore")

                if chunk_size < 8:
                    break

                if chunk_type == "mdhd":
                    mdhd_data = data[pos + 8 : pos + chunk_size]
                    if len(mdhd_data) >= 20:
                        version = mdhd_data[0]
                        if version == 0 and len(mdhd_data) >= 20:
                            timescale = struct.unpack(">I", mdhd_data[12:16])[0]
                            duration = struct.unpack(">I", mdhd_data[16:20])[0]
                            metadata["mdhd_timescale"] = timescale
                            if timescale > 0:
                                secs = duration / timescale
                                metadata["duration"] = round(secs, 2)
                                metadata["duration_formatted"] = self._format_duration(secs)
                                if secs > 0 and metadata["file_size"] > 0:
                                    metadata["bitrate"] = round(metadata["file_size"] * 8 / secs / 1000)

                elif chunk_type == "minf":
                    minf_data = data[pos + 8 : pos + chunk_size]
                    self._parse_mp4_minf(minf_data, metadata)

                pos += chunk_size
        except Exception as e:
            logger.debug("MP4 mdia 解析细节错误: %s", e)

    def _parse_mp4_minf(self, data: bytes, metadata: dict[str, Any]):
        """解析 MP4 minf 原子"""
        try:
            pos = 0
            while pos + 8 <= len(data):
                chunk_size = struct.unpack(">I", data[pos : pos + 4])[0]
                chunk_type = data[pos + 4 : pos + 8].decode("ascii", errors="ignore")

                if chunk_size < 8:
                    break

                if chunk_type == "stbl":
                    stbl_data = data[pos + 8 : pos + chunk_size]
                    self._parse_mp4_stbl(stbl_data, metadata)

                pos += chunk_size
        except Exception as e:
            logger.debug("MP4 minf 解析细节错误: %s", e)

    def _parse_mp4_stbl(self, data: bytes, metadata: dict[str, Any]):
        """解析 MP4 stbl (Sample Table) 原子"""
        try:
            pos = 0
            while pos + 8 <= len(data):
                chunk_size = struct.unpack(">I", data[pos : pos + 4])[0]
                chunk_type = data[pos + 4 : pos + 8].decode("ascii", errors="ignore")

                if chunk_size < 8:
                    break

                if chunk_type == "stsd":
                    stsd_data = data[pos + 8 : pos + chunk_size]
                    if len(stsd_data) >= 16:
                        struct.unpack(">I", stsd_data[4:8])[0]
                        entry_data = stsd_data[8:]
                        if len(entry_data) >= 8:
                            entry_size = struct.unpack(">I", entry_data[:4])[0]
                            entry_format = entry_data[4:8].decode("ascii", errors="ignore")
                            metadata["codec_id"] = entry_format

                            if entry_size >= 36:
                                # 跳过 reserved (6 bytes) + data_ref_index (2 bytes)
                                sample_entry_data = entry_data[16:entry_size]
                                if entry_format == "mp4a" and len(sample_entry_data) >= 20:
                                    channels = struct.unpack(">H", sample_entry_data[0:2])[0]
                                    metadata["channels"] = channels
                                    sample_rate = struct.unpack(">I", sample_entry_data[8:12])[0] >> 16
                                    metadata["sample_rate"] = sample_rate

                pos += chunk_size
        except Exception as e:
            logger.debug("MP4 stbl 解析细节错误: %s", e)

    def _parse_aiff(self, f, file_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
        """解析 AIFF 文件头"""
        metadata["format"] = "AIFF"

        try:
            f.seek(0)
            header_data = f.read(54)
            if len(header_data) < 54:
                return metadata

            # FORM 头
            form_id, form_size, aiff_id = struct.unpack(">4sI4s", header_data[:12])
            metadata["form_size"] = form_size

            if aiff_id == b"AIFF":
                metadata["aiff_variant"] = "AIFF"
            elif aiff_id == b"AIFC":
                metadata["aiff_variant"] = "AIFC (compressed)"
            else:
                return metadata

            pos = 12
            while pos + 8 <= len(header_data):
                chunk_id, chunk_size = struct.unpack(">4sI", header_data[pos : pos + 8])

                if chunk_id == b"COMM":
                    comm_data = header_data[pos + 8 : pos + 8 + chunk_size]
                    if len(comm_data) >= 18:
                        num_channels = struct.unpack(">H", comm_data[:2])[0]
                        num_frames = struct.unpack(">I", comm_data[2:6])[0]
                        sample_size = struct.unpack(">H", comm_data[6:8])[0]
                        # sample_rate 是 80-bit extended
                        sample_rate_bytes = comm_data[8:18]
                        if len(sample_rate_bytes) == 10:
                            exp = struct.unpack(">H", sample_rate_bytes[:2])[0]
                            mantissa = struct.unpack(">Q", sample_rate_bytes[2:10])[0]
                            sample_rate = 0 if exp == 0 else mantissa / 2**63 * 2 ** (exp - 16383)
                            metadata["sample_rate"] = round(sample_rate)
                            metadata["bit_depth"] = sample_size
                            metadata["channels"] = num_channels

                            if sample_rate > 0:
                                duration_sec = num_frames / sample_rate
                                metadata["duration"] = round(duration_sec, 2)
                                metadata["duration_formatted"] = self._format_duration(duration_sec)
                                metadata["total_frames"] = num_frames

                pos += 8 + chunk_size

        except Exception as e:
            logger.debug("AIFF 解析细节错误: %s", e)

        return metadata

    def _parse_vorbis_comment(self, data: bytes, metadata: dict[str, Any]):
        """解析 Vorbis Comment (FLAC/OGG 标签)"""
        try:
            if len(data) < 4:
                return
            vendor_len = struct.unpack("<I", data[:4])[0]
            pos = 4 + vendor_len

            if pos + 4 > len(data):
                return
            num_comments = struct.unpack("<I", data[pos : pos + 4])[0]
            pos += 4

            for _ in range(min(num_comments, 50)):
                if pos + 4 > len(data):
                    break
                comment_len = struct.unpack("<I", data[pos : pos + 4])[0]
                pos += 4
                if comment_len <= 0 or pos + comment_len > len(data):
                    break
                comment_str = data[pos : pos + comment_len].decode("utf-8", errors="ignore")
                pos += comment_len

                if "=" in comment_str:
                    key, value = comment_str.split("=", 1)
                    key = key.upper()
                    if key == "TITLE":
                        metadata.setdefault("title", value)
                    elif key == "ARTIST":
                        metadata.setdefault("artist", value)
                    elif key == "ALBUM":
                        metadata.setdefault("album", value)
                    elif key == "DATE":
                        metadata.setdefault("year", value[:4])
                    elif key == "TRACKNUMBER":
                        metadata.setdefault("track", value)
                    elif key == "GENRE":
                        metadata.setdefault("genre", value)
        except Exception as e:
            logger.debug("Vorbis Comment 解析细节错误: %s", e)

    def _format_duration(self, seconds: float) -> str:
        """格式化时长为 HH:MM:SS"""
        if seconds < 0:
            seconds = 0
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    def _format_metadata(self, metadata: dict[str, Any]) -> str:
        """格式化元数据为文本"""
        lines = [f"[音频元数据] {metadata.get('filename', '未知')}"]

        format_type = metadata.get("format", "未知")
        lines.append(f"格式: {format_type}")

        if "codec" in metadata:
            lines.append(f"编码: {metadata['codec']}")

        if "mpeg_version" in metadata and "layer" in metadata:
            lines.append(f"版本: {metadata['mpeg_version']} {metadata['layer']}")

        if "title" in metadata:
            lines.append(f"标题: {metadata['title']}")

        if "artist" in metadata:
            lines.append(f"艺术家: {metadata['artist']}")

        if "album" in metadata:
            lines.append(f"专辑: {metadata['album']}")

        if "year" in metadata:
            lines.append(f"年份: {metadata['year']}")

        if "track" in metadata:
            lines.append(f"音轨: {metadata['track']}")

        if "genre" in metadata:
            lines.append(f"流派: {metadata['genre']}")

        if "comment" in metadata:
            lines.append(f"备注: {metadata['comment']}")

        if "sample_rate" in metadata:
            rate_khz = metadata["sample_rate"] / 1000
            lines.append(f"采样率: {rate_khz:.1f} kHz")

        if "bit_depth" in metadata:
            lines.append(f"位深度: {metadata['bit_depth']} bit")

        if "channels" in metadata:
            ch = metadata["channels"]
            ch_label = {1: "单声道", 2: "立体声", 4: "四声道", 6: "5.1声道", 8: "7.1声道"}.get(ch, f"{ch}声道")
            lines.append(f"声道: {ch_label}")

        if "channel_mode" in metadata:
            lines.append(f"声道模式: {metadata['channel_mode']}")

        if "bitrate" in metadata:
            lines.append(f"比特率: {metadata['bitrate']} kbps")

        if "duration_formatted" in metadata:
            lines.append(f"时长: {metadata['duration_formatted']}")

        if "duration" in metadata and isinstance(metadata["duration"], (int, float)):
            lines.append(f"时长(秒): {metadata['duration']:.1f}s")

        if "file_size" in metadata:
            size_kb = metadata["file_size"] / 1024
            if size_kb >= 1024:
                lines.append(f"文件大小: {size_kb / 1024:.1f} MB")
            else:
                lines.append(f"文件大小: {size_kb:.0f} KB")

        return "\n".join(lines)
