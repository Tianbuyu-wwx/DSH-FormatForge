"""
输出格式化模块
将转换结果格式化为不同目标格式，适配不同AI的输入偏好
"""
import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from datetime import datetime

from core.models import OutputFormat, ConvertResultData, ProcessingLog
from core.ai_discovery import AiCapabilities, OutputFormat as AiOutputFormat

logger = logging.getLogger("output_formatters")


class OutputFormatter(ABC):
    """输出格式化器抽象基类"""

    @abstractmethod
    def format(self, content: str, structured_data: Optional[Dict] = None, **kwargs) -> str:
        """格式化内容"""
        pass

    @abstractmethod
    def get_mime_type(self) -> str:
        """获取输出MIME类型"""
        pass


class JsonFormatter(OutputFormatter):
    """JSON格式化器"""

    def format(self, content: str, structured_data: Optional[Dict] = None, **kwargs) -> str:
        result = {
            "content": content,
            "structured_data": structured_data or {},
            "metadata": kwargs.get("metadata", {})
        }
        try:
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("JSON格式化失败: %s", e)
            return json.dumps({"content": content}, ensure_ascii=False, indent=2)

    def get_mime_type(self) -> str:
        return "application/json"


class MarkdownFormatter(OutputFormatter):
    """Markdown格式化器"""

    def format(self, content: str, structured_data: Optional[Dict] = None, **kwargs) -> str:
        title = kwargs.get("title", "转换结果")
        if not content.startswith("#"):
            content = f"# {title}\n\n{content}"

        # 如果有结构化数据，追加到末尾
        if structured_data and kwargs.get("include_structured", False):
            content += "\n\n## 结构化数据\n\n```json\n"
            try:
                content += json.dumps(structured_data, ensure_ascii=False, indent=2)
            except:
                content += str(structured_data)
            content += "\n```"

        return content

    def get_mime_type(self) -> str:
        return "text/markdown"


class TextFormatter(OutputFormatter):
    """纯文本格式化器"""

    def format(self, content: str, structured_data: Optional[Dict] = None, **kwargs) -> str:
        # 移除Markdown标记，生成纯文本
        import re
        text = re.sub(r'#{1,6}\s*', '', content)
        text = re.sub(r'\*\*|__', '', text)
        text = re.sub(r'`{1,3}', '', text)
        text = re.sub(r'!\[.*?\]\(.*?\)', '[图片]', text)
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
        return text.strip()

    def get_mime_type(self) -> str:
        return "text/plain"


class HtmlFormatter(OutputFormatter):
    """HTML格式化器"""

    def format(self, content: str, structured_data: Optional[Dict] = None, **kwargs) -> str:
        # 简单的Markdown转HTML
        import re

        html = content

        # 转义HTML特殊字符
        html = html.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        # 标题
        for i in range(6, 0, -1):
            html = re.sub(
                rf'^\s*{"#" * i}\s*(.+?)$',
                rf'<h{i}>\1</h{i}>',
                html,
                flags=re.MULTILINE
            )

        # 粗体
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
        html = re.sub(r'__(.+?)__', r'<strong>\1</strong>', html)

        # 斜体
        html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
        html = re.sub(r'_(.+?)_', r'<em>\1</em>', html)

        # 代码块
        html = re.sub(
            r'```(\w+)?\n(.*?)```',
            r'<pre><code>\2</code></pre>',
            html,
            flags=re.DOTALL
        )

        # 行内代码
        html = re.sub(r'`(.+?)`', r'<code>\1</code>', html)

        # 段落和换行
        paragraphs = html.split('\n\n')
        wrapped = []
        for p in paragraphs:
            p = p.strip()
            if p and not p.startswith('<'):
                p = f'<p>{p}</p>'
            wrapped.append(p)
        html = '\n'.join(wrapped)

        # 简单的br转换
        html = html.replace('\n', '<br>\n')

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>转换结果</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; line-height: 1.6; }}
h1, h2, h3 {{ color: #333; }}
code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }}
pre {{ background: #f4f4f4; padding: 16px; overflow-x: auto; border-radius: 6px; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
th {{ background: #f4f4f4; }}
</style>
</head>
<body>
{html}
</body>
</html>"""

    def get_mime_type(self) -> str:
        return "text/html"


class AiNativeFormatter(OutputFormatter):
    """AI原生格式 - 为支持多模态的AI优化"""

    def format(self, content: str, structured_data: Optional[Dict] = None, **kwargs) -> str:
        """生成AI友好的格式，包含媒体引用"""
        media_refs = kwargs.get("media_references", [])
        ai_caps = kwargs.get("ai_capabilities")

        parts = ["# AI处理数据包\n"]

        # 文件信息
        parts.append("## 文件信息")
        parts.append(f"- 原始格式: {kwargs.get('original_format', 'unknown')}")
        parts.append(f"- 目标AI: {ai_caps.provider if ai_caps else 'unknown'}")
        parts.append(f"- 支持多模态: {ai_caps.supports_multimodal if ai_caps else False}")
        parts.append("")

        # 内容摘要
        parts.append("## 内容摘要")
        parts.append(content[:2000] if len(content) > 2000 else content)
        parts.append("")

        # 媒体引用
        if media_refs:
            parts.append("## 媒体文件")
            for idx, ref in enumerate(media_refs, 1):
                parts.append(f"### 媒体 {idx}")
                parts.append(f"- 类型: {ref.get('type', 'unknown')}")
                parts.append(f"- 描述: {ref.get('description', '')}")
                if ai_caps and ai_caps.supports_multimodal:
                    parts.append(f"- 文件路径: {ref.get('path', '')}")
                    parts.append("- 状态: 可直接发送给AI")
                else:
                    parts.append("- 状态: 需要转换后发送")
                parts.append("")

        # 结构化数据
        if structured_data:
            parts.append("## 结构化数据")
            try:
                parts.append("```json")
                parts.append(json.dumps(structured_data, ensure_ascii=False, indent=2)[:3000])
                parts.append("```")
            except:
                parts.append(str(structured_data)[:3000])

        return "\n".join(parts)

    def get_mime_type(self) -> str:
        return "text/markdown"


class XmlFormatter(OutputFormatter):
    """XML格式化器"""

    def format(self, content: str, structured_data: Optional[Dict] = None, **kwargs) -> str:
        from xml.sax.saxutils import escape

        xml_parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<converted-data>',
            f'  <content>{escape(content)}</content>'
        ]

        if structured_data:
            xml_parts.append('  <structured-data>')
            try:
                json_str = json.dumps(structured_data, ensure_ascii=False)
                xml_parts.append(f'    <json>{escape(json_str)}</json>')
            except:
                pass
            xml_parts.append('  </structured-data>')

        xml_parts.append('</converted-data>')
        return '\n'.join(xml_parts)

    def get_mime_type(self) -> str:
        return "application/xml"


class FormatterRegistry:
    """格式化器注册表"""

    def __init__(self):
        self._formatters: Dict[str, OutputFormatter] = {
            "json": JsonFormatter(),
            "markdown": MarkdownFormatter(),
            "text": TextFormatter(),
            "html": HtmlFormatter(),
            "ai_native": AiNativeFormatter(),
            "xml": XmlFormatter(),
        }

    def get_formatter(self, format_type: str) -> OutputFormatter:
        """获取格式化器"""
        formatter = self._formatters.get(format_type.lower())
        if not formatter:
            logger.warning("未知格式 %s，使用默认文本格式", format_type)
            return self._formatters["text"]
        return formatter

    def format_for_ai(
        self,
        content: str,
        output_format: OutputFormat,
        ai_caps: Optional[AiCapabilities] = None,
        structured_data: Optional[Dict] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        根据AI能力选择最佳格式并格式化

        Returns:
            {"content": str, "mime_type": str, "format": str}
        """
        # 如果AI有格式偏好，优先使用
        if ai_caps:
            preferred = ai_caps.preferred_format.value
            if preferred == "markdown" and output_format == OutputFormat.AUTO:
                formatter = self._formatters["markdown"]
                formatted = formatter.format(content, structured_data, **kwargs)
                return {
                    "content": formatted,
                    "mime_type": formatter.get_mime_type(),
                    "format": "markdown"
                }

        # 根据请求的output_format选择
        format_map = {
            OutputFormat.JSON: "json",
            OutputFormat.MARKDOWN: "markdown",
            OutputFormat.TEXT: "text",
            OutputFormat.HTML: "html",
        }

        formatter_key = format_map.get(output_format, "text")
        formatter = self._formatters[formatter_key]

        # 如果AI支持多模态且需要，使用AI原生格式
        if ai_caps and ai_caps.supports_multimodal and kwargs.get("has_media"):
            formatter = self._formatters["ai_native"]
            formatter_key = "ai_native"

        formatted = formatter.format(content, structured_data, ai_capabilities=ai_caps, **kwargs)

        return {
            "content": formatted,
            "mime_type": formatter.get_mime_type(),
            "format": formatter_key
        }

    def register(self, name: str, formatter: OutputFormatter):
        """注册自定义格式化器"""
        self._formatters[name.lower()] = formatter

    def list_formats(self) -> List[str]:
        """列出支持的格式"""
        return list(self._formatters.keys())


class ResultExporter:
    """结果导出器"""

    @staticmethod
    def to_json(result: ConvertResultData) -> str:
        """导出为JSON"""
        return json.dumps({
            "resultId": result.resultId,
            "fileName": result.fileInfo.fileName,
            "conversionType": result.conversionType.value,
            "outputFormat": result.outputFormat.value,
            "confidence": result.confidence,
            "content": result.convertedContent,
            "structuredData": result.structuredData,
            "processingLogs": [
                {
                    "time": log.timestamp.isoformat(),
                    "level": log.level,
                    "message": log.message,
                    "step": log.step
                }
                for log in result.processingLogs
            ]
        }, ensure_ascii=False, indent=2)

    @staticmethod
    def to_markdown(result: ConvertResultData) -> str:
        """导出为Markdown"""
        lines = [
            f"# {result.fileInfo.fileName} - 转换结果",
            "",
            f"- 转换类型: {result.conversionType.value}",
            f"- 输出格式: {result.outputFormat.value}",
            f"- 置信度: {result.confidence:.2f}",
            f"- 生成时间: {result.createdAt.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 转换内容",
            "",
            result.convertedContent,
            "",
            "## 处理日志",
            ""
        ]
        for log in result.processingLogs:
            lines.append(f"- [{log.level.upper()}] {log.step}: {log.message}")
        return "\n".join(lines)

    @staticmethod
    def to_text(result: ConvertResultData) -> str:
        """导出为纯文本"""
        lines = [
            f"转换结果: {result.fileInfo.fileName}",
            f"类型: {result.conversionType.value} | 格式: {result.outputFormat.value} | 置信度: {result.confidence:.2f}",
            "=" * 50,
            "",
            result.convertedContent,
            "",
            "=" * 50,
            "处理日志:",
        ]
        for log in result.processingLogs:
            lines.append(f"  [{log.level}] {log.step}: {log.message}")
        return "\n".join(lines)

    @staticmethod
    def to_html(result: ConvertResultData) -> str:
        """导出为HTML"""
        formatter = HtmlFormatter()
        md_content = ResultExporter.to_markdown(result)
        html_content = formatter.format(md_content)

        # 在head中添加元信息
        meta = f"""
<meta name="conversion-type" content="{result.conversionType.value}">
<meta name="confidence" content="{result.confidence:.2f}">
<meta name="result-id" content="{result.resultId}">
"""
        html_content = html_content.replace("</head>", f"{meta}</head>")
        return html_content


# 全局实例
formatter_registry = FormatterRegistry()
result_exporter = ResultExporter()
