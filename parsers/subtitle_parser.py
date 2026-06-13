"""
SRT/VTT 字幕文件解析器
支持解析 SRT 和 WebVTT 格式的字幕文件
"""
import logging
import re
from pathlib import Path
from typing import Any

from core.models import ExtractedElement, PageContent
from parsers import BaseParser

logger = logging.getLogger("parsers.subtitle")


class SubtitleParser(BaseParser):
    """SRT/VTT 字幕解析器"""

    @property
    def name(self) -> str:
        return "SubtitleParser"

    @property
    def description(self) -> str:
        return "解析 SRT/VTT 字幕格式文件，提取时间轴与文本内容"

    @property
    def supported_extensions(self) -> list[str]:
        return [".srt", ".vtt", ".SRT", ".VTT"]

    @property
    def supported_magic(self) -> list[bytes]:
        return []

    def parse(self, file_path: Path) -> list[PageContent]:
        file_path = Path(file_path)
        logger.info("开始解析字幕文件: %s", file_path)

        ext = file_path.suffix.lower()

        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            logger.error("无法读取字幕文件: %s", e)
            raise ValueError(f"无法读取字幕文件: {e}")

        if ext == ".srt":
            return self._parse_srt(content, file_path.name)
        elif ext == ".vtt":
            return self._parse_vtt(content, file_path.name)
        else:
            raise ValueError(f"不支持的字幕格式: {ext}")

    def _parse_srt(self, content: str, filename: str) -> list[PageContent]:
        """解析 SRT 字幕格式"""
        # 规范化换行符
        content = content.replace("\r\n", "\n").replace("\r", "\n")

        # 按双换行分割字幕块
        blocks = re.split(r"\n\n+", content.strip())

        elements = []
        elem_idx = 0
        raw_text_parts = []

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            # SRT 块格式: 序号\n时间轴\n文本（可能多行）
            lines = block.split("\n")
            if len(lines) < 3:
                continue

            # 解析序号（可能非纯数字，尽力尝试）
            index = 0
            try:
                index = int(lines[0].strip())
            except ValueError:
                pass

            # 解析时间轴: 00:00:20,000 --> 00:00:24,400
            timestamp_line = ""
            text_lines_start = 1

            # 寻找包含 --> 的时间轴行
            for i in range(1, min(len(lines), 4)):
                if "-->" in lines[i]:
                    timestamp_line = lines[i].strip()
                    text_lines_start = i + 1
                    break

            if not timestamp_line:
                continue

            # 提取文本内容
            text_lines = lines[text_lines_start:]
            subtitle_text = "\n".join(text_lines).strip()
            if not subtitle_text:
                continue

            # 解析时间戳
            start_time, end_time = self._parse_srt_timestamp(timestamp_line)

            elements.append(ExtractedElement(
                elementId=f"elem_1_{elem_idx}",
                elementType="text",
                content=subtitle_text,
                metadata={
                    "index": index,
                    "start_time": start_time,
                    "end_time": end_time,
                    "raw_timestamp": timestamp_line,
                }
            ))
            raw_text_parts.append(subtitle_text)
            elem_idx += 1

        logger.info("SRT 解析完成: %d 条字幕", len(elements))

        return [PageContent(
            pageNumber=1,
            elements=elements,
            rawText="\n".join(raw_text_parts),
            hasImage=False,
            hasTable=False,
        )]

    def _parse_vtt(self, content: str, filename: str) -> list[PageContent]:
        """解析 WebVTT 字幕格式"""
        content = content.replace("\r\n", "\n").replace("\r", "\n")

        lines = content.split("\n")

        # 跳过 WEBVTT 头部
        start_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "WEBVTT":
                start_idx = i + 1
                break
            # 有些变体有带参数的 WEBVTT 头
            if re.match(r"^WEBVTT\b", stripped):
                start_idx = i + 1
                break

        # 跳过头部后续的元数据行 (如 Kind:, Language: 等，直到空行或时间戳)
        while start_idx < len(lines):
            stripped = lines[start_idx].strip()
            if not stripped or re.search(r"^\d{2}:\d{2}", stripped):
                break
            start_idx += 1
        # 再跳过一个可能的空行
        if start_idx < len(lines) and not lines[start_idx].strip():
            start_idx += 1

        elements = []
        elem_idx = 0
        raw_text_parts = []

        # 按双换行分割提示块
        remaining = "\n".join(lines[start_idx:])
        blocks = re.split(r"\n\n+", remaining.strip())

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            block_lines = block.split("\n")

            # 寻找时间戳行
            ts_line_idx = -1
            for j, bl in enumerate(block_lines):
                if "-->" in bl and re.search(r"\d{2}:\d{2}", bl):
                    ts_line_idx = j
                    break

            if ts_line_idx < 0:
                continue

            ts_line = block_lines[ts_line_idx].strip()

            # 可选标识符行（在时间戳之前）
            cue_id = ""
            if ts_line_idx > 0:
                cue_id = block_lines[ts_line_idx - 1].strip()

            # 文本内容（时间戳之后的所有行）
            text_lines = block_lines[ts_line_idx + 1:]
            # 去除空行
            text = "\n".join(ln.strip() for ln in text_lines if ln.strip())

            if not text:
                continue

            # 去除 WebVTT 内联标签
            text = self._strip_vtt_tags(text)

            start_time, end_time = self._parse_vtt_timestamp(ts_line)

            elements.append(ExtractedElement(
                elementId=f"elem_1_{elem_idx}",
                elementType="text",
                content=text,
                metadata={
                    "cue_id": cue_id,
                    "start_time": start_time,
                    "end_time": end_time,
                    "raw_timestamp": ts_line,
                }
            ))
            raw_text_parts.append(text)
            elem_idx += 1

        logger.info("VTT 解析完成: %d 条字幕", len(elements))

        return [PageContent(
            pageNumber=1,
            elements=elements,
            rawText="\n".join(raw_text_parts),
            hasImage=False,
            hasTable=False,
        )]

    def _parse_srt_timestamp(self, ts_line: str) -> tuple[str, str]:
        """解析 SRT 时间戳行: 00:00:20,000 --> 00:00:24,400"""
        parts = ts_line.split("-->")
        start = parts[0].strip() if len(parts) >= 1 else ""
        end = parts[1].strip() if len(parts) >= 2 else ""
        return start, end

    def _parse_vtt_timestamp(self, ts_line: str) -> tuple[str, str]:
        """解析 VTT 时间戳行: 00:00:20.000 --> 00:00:24.400（可能有位置信息）"""
        # 去掉可能的设置信息 (如 position:10%)
        ts_clean = re.split(r"\s+position:", ts_line)[0]
        ts_clean = re.split(r"\s+align:", ts_clean)[0]
        ts_clean = re.split(r"\s+line:", ts_clean)[0]
        ts_clean = re.split(r"\s+size:", ts_clean)[0]

        parts = ts_clean.split("-->")
        start = parts[0].strip() if len(parts) >= 1 else ""
        end = parts[1].strip() if len(parts) >= 2 else ""
        return start, end

    def _strip_vtt_tags(self, text: str) -> str:
        """去除 WebVTT 内联标签 (如 <c>, <v>, <i>, <b> 等)"""
        # 去除类标签: <c.classname>text</c>
        text = re.sub(r"</?c[^>]*>", "", text)
        # 去除声音标签: <v Speaker>text</v>
        text = re.sub(r"</?v[^>]*>", "", text)
        # 去除其他常见标签
        text = re.sub(r"</?[ibu]>", "", text)
        # 去除 ruby 等
        text = re.sub(r"</?ruby>", "", text)
        text = re.sub(r"</?rt>", "", text)
        # 去除 lang 标签
        text = re.sub(r"</?lang[^>]*>", "", text)
        return text.strip()