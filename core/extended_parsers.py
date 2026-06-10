"""
扩展格式解析器模块
支持 EPUB、Markdown、音频等更多格式
"""
import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from pathlib import Path
from dataclasses import dataclass, field

logger = logging.getLogger("extended_parsers")


@dataclass
class ParsedContent:
    """解析后的内容"""
    title: Optional[str] = None
    author: Optional[str] = None
    content: str = ""
    chapters: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    word_count: int = 0


class ExtendedParser(ABC):
    """扩展解析器抽象基类"""

    @abstractmethod
    def can_parse(self, file_path: Path) -> bool:
        """是否能解析该文件"""
        pass

    @abstractmethod
    def parse(self, file_path: Path) -> ParsedContent:
        """解析文件"""
        pass


class EpubParser(ExtendedParser):
    """EPUB 电子书解析器"""

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".epub"

    def parse(self, file_path: Path) -> ParsedContent:
        """解析EPUB文件"""
        try:
            import ebooklib
            from ebooklib import epub
            from bs4 import BeautifulSoup

            book = epub.read_epub(str(file_path))
            result = ParsedContent()

            # 提取元数据
            metadata = book.get_metadata("DC", "")
            for meta in metadata:
                if len(meta) >= 2:
                    key, value = meta[0], meta[1]
                    if key == "title":
                        result.title = value
                    elif key == "creator":
                        result.author = value
                    result.metadata[key] = value

            # 提取章节内容
            chapters = []
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    soup = BeautifulSoup(item.get_content(), "html.parser")
                    # 移除脚本和样式
                    for script in soup(["script", "style"]):
                        script.decompose()

                    text = soup.get_text(separator="\n", strip=True)
                    if text.strip():
                        # 尝试提取章节标题
                        heading = soup.find(["h1", "h2", "h3"])
                        chapter_title = heading.get_text(strip=True) if heading else f"章节 {len(chapters) + 1}"

                        chapters.append({
                            "title": chapter_title,
                            "content": text,
                            "word_count": len(text)
                        })

            result.chapters = chapters
            result.content = "\n\n".join(ch["content"] for ch in chapters)
            result.word_count = sum(ch["word_count"] for ch in chapters)

            return result

        except ImportError:
            logger.warning("ebooklib 或 beautifulsoup4 未安装，无法解析EPUB")
            return self._fallback_parse(file_path)
        except Exception as e:
            logger.error(f"EPUB解析失败: {e}")
            return self._fallback_parse(file_path)

    def _fallback_parse(self, file_path: Path) -> ParsedContent:
        """降级解析 - 将EPUB作为ZIP读取文本"""
        try:
            import zipfile
            result = ParsedContent()
            texts = []

            with zipfile.ZipFile(file_path, "r") as zf:
                for name in zf.namelist():
                    if name.endswith((".html", ".xhtml", ".htm")):
                        content = zf.read(name).decode("utf-8", errors="replace")
                        # 简单去除HTML标签
                        text = re.sub(r"<[^>]+>", " ", content)
                        text = re.sub(r"\s+", " ", text).strip()
                        if text:
                            texts.append(text)

            result.content = "\n\n".join(texts)
            result.word_count = len(result.content)
            return result
        except Exception as e:
            logger.error(f"EPUB降级解析失败: {e}")
            return ParsedContent(content=f"解析失败: {e}")


class MarkdownParser(ExtendedParser):
    """Markdown 解析器"""

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in {".md", ".markdown", ".mdown"}

    def parse(self, file_path: Path) -> ParsedContent:
        """解析Markdown文件"""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            result = ParsedContent(content=content, word_count=len(content))

            # 提取标题
            title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
            if title_match:
                result.title = title_match.group(1).strip()

            # 提取章节
            chapters = []
            current_chapter = None
            current_content = []

            for line in content.split("\n"):
                heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)
                if heading_match:
                    if current_chapter:
                        current_chapter["content"] = "\n".join(current_content)
                        current_chapter["word_count"] = len(current_chapter["content"])
                        chapters.append(current_chapter)

                    level = len(heading_match.group(1))
                    current_chapter = {
                        "title": heading_match.group(2).strip(),
                        "level": level,
                        "content": "",
                        "word_count": 0
                    }
                    current_content = []
                else:
                    current_content.append(line)

            if current_chapter:
                current_chapter["content"] = "\n".join(current_content)
                current_chapter["word_count"] = len(current_chapter["content"])
                chapters.append(current_chapter)

            result.chapters = chapters
            return result

        except Exception as e:
            logger.error(f"Markdown解析失败: {e}")
            return ParsedContent(content=f"解析失败: {e}")


class AudioParser(ExtendedParser):
    """音频文件解析器（语音转文字）"""

    SUPPORTED_FORMATS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".wma"}

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in self.SUPPORTED_FORMATS

    def parse(self, file_path: Path) -> ParsedContent:
        """解析音频文件（语音转文字）"""
        result = ParsedContent(title=file_path.stem)

        # 尝试使用 Whisper
        try:
            import whisper
            model = whisper.load_model("base")
            transcription = model.transcribe(str(file_path))

            result.content = transcription["text"]
            result.word_count = len(result.content)
            result.metadata = {
                "language": transcription.get("language", "unknown"),
                "duration": transcription.get("duration", 0),
                "segments": len(transcription.get("segments", []))
            }

            # 按段落组织
            segments = transcription.get("segments", [])
            for seg in segments:
                result.chapters.append({
                    "title": f"段落 {seg['id'] + 1}",
                    "content": seg["text"],
                    "start": seg.get("start", 0),
                    "end": seg.get("end", 0),
                    "word_count": len(seg["text"])
                })

            return result

        except ImportError:
            logger.warning("whisper 未安装，无法转录音频")
            return self._create_audio_info(file_path)
        except Exception as e:
            logger.error(f"音频转录失败: {e}")
            return self._create_audio_info(file_path)

    def _create_audio_info(self, file_path: Path) -> ParsedContent:
        """创建音频文件信息（无法转录时）"""
        try:
            import mutagen
            from mutagen.mp3 import MP3
            from mutagen.wave import WAVE

            audio = mutagen.File(str(file_path))
            duration = audio.info.length if audio else 0

            return ParsedContent(
                title=file_path.stem,
                content=f"[音频文件: {file_path.name}]\n时长: {duration:.1f}秒\n格式: {file_path.suffix}",
                metadata={
                    "duration": duration,
                    "format": file_path.suffix,
                    "size": file_path.stat().st_size
                }
            )
        except ImportError:
            return ParsedContent(
                title=file_path.stem,
                content=f"[音频文件: {file_path.name}]\n无法提取音频内容，请安装 whisper 或 mutagen",
                metadata={"format": file_path.suffix}
            )


class RtfParser(ExtendedParser):
    """RTF 富文本解析器"""

    def can_parse(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == ".rtf"

    def parse(self, file_path: Path) -> ParsedContent:
        """解析RTF文件"""
        try:
            from striprtf.striprtf import rtf_to_text
            content = file_path.read_text(encoding="utf-8", errors="replace")
            text = rtf_to_text(content)

            return ParsedContent(
                content=text,
                word_count=len(text)
            )
        except ImportError:
            logger.warning("striprtf 未安装，尝试降级解析")
            return self._manual_rtf_parse(file_path)
        except Exception as e:
            logger.error(f"RTF解析失败: {e}")
            return ParsedContent(content=f"解析失败: {e}")

    def _manual_rtf_parse(self, file_path: Path) -> ParsedContent:
        """手动解析RTF（简单实现）"""
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            # 移除RTF控制字
            text = re.sub(r"\\[a-z]+\d*\s?", "", content)
            text = re.sub(r"\\[\{\}\|\\]", "", text)
            text = re.sub(r"\{.*?\}", "", text, flags=re.DOTALL)
            text = text.replace("\\par", "\n")
            text = re.sub(r"\s+", " ", text).strip()

            return ParsedContent(content=text, word_count=len(text))
        except Exception as e:
            return ParsedContent(content=f"手动解析失败: {e}")


class ExtendedParserRegistry:
    """扩展解析器注册表"""

    def __init__(self):
        self._parsers: List[ExtendedParser] = [
            EpubParser(),
            MarkdownParser(),
            AudioParser(),
            RtfParser(),
        ]

    def get_parser(self, file_path: Path) -> Optional[ExtendedParser]:
        """获取合适的解析器"""
        for parser in self._parsers:
            if parser.can_parse(file_path):
                return parser
        return None

    def parse(self, file_path: Path) -> ParsedContent:
        """解析文件"""
        parser = self.get_parser(file_path)
        if parser:
            return parser.parse(file_path)
        return ParsedContent(content=f"不支持的文件格式: {file_path.suffix}")

    def get_supported_formats(self) -> List[str]:
        """获取支持的格式列表"""
        formats = []
        for parser in self._parsers:
            if isinstance(parser, EpubParser):
                formats.append("epub")
            elif isinstance(parser, MarkdownParser):
                formats.extend(["md", "markdown"])
            elif isinstance(parser, AudioParser):
                formats.extend(["mp3", "wav", "m4a", "flac", "ogg", "wma"])
            elif isinstance(parser, RtfParser):
                formats.append("rtf")
        return formats


# 全局注册表
extended_parser_registry = ExtendedParserRegistry()
