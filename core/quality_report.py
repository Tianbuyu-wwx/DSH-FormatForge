"""
解析质量报告系统
对解析/转换后的内容进行多维度质量评分
"""

import contextlib
import json
import logging
import re
from typing import Any

logger = logging.getLogger("quality_report")


class QualityReport:
    """解析质量报告"""

    def __init__(self):
        self.scores: dict[str, float] = {}
        self.warnings: list[str] = []
        self.suggestions: list[str] = []
        self.actions: list[dict[str, Any]] = []
        self._last_parsed_file: Any = None
        # v0.14.0/B-P1-5: 记录 file_type 以便 overall_score 动态调权
        self._last_file_type: str = "unknown"

    # ==================== 评分维度 ====================

    def _score_text_coverage(self, content: str, file_size: int, file_type: str) -> float:
        """评估文本覆盖率 (0-100)"""
        if file_size <= 0:
            self.warnings.append("文件大小为0，无法评估文本覆盖率")
            return 0.0

        text_len = len(content) if content else 0
        ratio = text_len / file_size

        # 不同文件类型的期望比例不同
        if file_type in ("txt", "csv", "md", "text", "json", "xml", "html", "sql", "latex", "toml"):
            expected = 0.3
        elif file_type in ("image", "jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff"):
            expected = 0.01
        else:
            expected = 0.05

        if ratio >= expected:
            score = 100.0
        elif ratio >= expected * 0.5:
            score = 50.0 + (ratio / expected - 0.5) * 100.0
        elif ratio > 0:
            score = (ratio / (expected * 0.5)) * 50.0
        else:
            score = 0.0

        if score < 50:
            self.warnings.append(f"文本覆盖率较低 ({ratio:.4f})，提取的内容可能不完整")
            self.suggestions.append("建议检查文件是否损坏或解析器是否匹配")

        return round(score, 1)

    def _score_encoding_confidence(self, content: str) -> float:
        """评估编码置信度 (0-100)"""
        if not content:
            self.warnings.append("内容为空，无法评估编码质量")
            return 0.0

        # 检查替换字符 (U+FFFD)
        replacement_count = content.count("\ufffd")

        # 检查常见乱码模式
        mojibake_patterns = [
            r"[\xc0-\xff][\x80-\xbf]",  # 常见 UTF-8 序列被错误解释
            r"Ã[©®\x81-\xbf]",  # 常见 Latin-1 被当作 UTF-8 解释
            r"â[\x80-\xbf]",  # 另一组常见乱码
        ]
        mojibake_count = 0
        for pattern in mojibake_patterns:
            with contextlib.suppress(Exception):
                mojibake_count += len(re.findall(pattern, content))

        total_garbled = replacement_count + mojibake_count
        content_len = max(len(content), 1)
        garbled_ratio = total_garbled / content_len

        if garbled_ratio < 0.01:
            score = 100.0
        elif garbled_ratio < 0.05:
            score = 75.0
        elif garbled_ratio < 0.15:
            score = 50.0
        elif garbled_ratio < 0.3:
            score = 25.0
        else:
            score = 0.0

        if replacement_count > 0:
            self.warnings.append(f"检测到 {replacement_count} 个替换字符 (U+FFFD)，可能存在编码问题")
            self.suggestions.append("建议检查源文件的编码格式，尝试使用 UTF-8 重新解码")

        if mojibake_count > 0:
            self.warnings.append(f"检测到 {mojibake_count} 个疑似乱码模式，编码质量可能存在问题")
            self.suggestions.append("建议确认源文件编码格式并使用正确的编码进行解析")

        return round(score, 1)

    def _score_structure_preservation(self, content: str) -> float:
        """评估结构保留度 (0-100)"""
        if not content:
            self.warnings.append("内容为空，无法评估结构保留度")
            return 0.0

        score = 0.0
        checks = 0

        # 检查 Markdown 标题
        headings = len(re.findall(r"^#{1,6}\s", content, re.MULTILINE))
        has_headings = headings > 0
        checks += 1
        if has_headings:
            score += 25
            if headings < 3:
                self.suggestions.append("标题层级较少，建议检查是否所有标题都被正确提取")

        # 检查列表
        list_items = len(re.findall(r"^[\s]*[-*+]\s", content, re.MULTILINE))
        ordered_items = len(re.findall(r"^[\s]*\d+[.)]\s", content, re.MULTILINE))
        has_lists = list_items > 0 or ordered_items > 0
        checks += 1
        if has_lists:
            score += 25

        # 检查表格
        tables = len(re.findall(r"\|.*\|.*\|", content))
        has_tables = tables > 0
        checks += 1
        if has_tables:
            score += 25

        # 检查段落分隔
        paragraphs = len(re.findall(r"\n\n+", content))
        has_paragraphs = paragraphs > 0
        checks += 1
        if has_paragraphs:
            score += 25
        elif len(content) > 500:
            self.warnings.append("未检测到明显的段落分隔，内容可能缺少结构化布局")
            self.suggestions.append("建议使用支持段落保留的解析器或格式")

        # 如果 checks 为 0，说明内容太短，给予基础分
        if checks == 0:
            return 50.0

        return round(score, 1)

    def _score_table_accuracy(self, content: str, structured_data: dict[str, Any] | None) -> float:
        """评估表格准确度 (0-100)"""
        if not structured_data:
            # 没有结构化数据，检查内容中是否有表格
            table_lines = [line for line in content.split("\n") if "|" in line and line.strip().startswith("|")]
            if not table_lines:
                return 100.0  # 无表格，视为满分
            score = 50.0  # 有表格标记但无结构化数据
            self.warnings.append("检测到表格标记但缺少结构化表格数据，无法验证表格准确性")
            self.suggestions.append("建议启用结构化数据提取以验证表格质量")
            return score

        tables = structured_data.get("tables", [])
        if not tables:
            return 100.0  # 无表格，视为满分

        score = 100.0
        deductions = 0

        for i, table in enumerate(tables):
            if isinstance(table, dict):
                data = table.get("data", [])
                headers = table.get("headers", [])
            elif isinstance(table, list):
                data = table
                headers = data[0] if data else []
            else:
                continue

            if not data:
                deductions += 10
                self.warnings.append(f"表格 {i + 1} 数据为空")
                continue

            # 检查列数一致性
            col_counts = [len(row) for row in data]
            if len(set(col_counts)) > 1:
                deductions += 20
                self.warnings.append(f"表格 {i + 1} 列数不一致: {set(col_counts)}")
                self.suggestions.append(f"表格 {i + 1} 列数不一致，建议检查原始表格格式")

            # 检查空单元格比例
            total_cells = sum(col_counts)
            empty_cells = sum(1 for row in data for cell in row if not cell or str(cell).strip() == "")
            if total_cells > 0:
                empty_ratio = empty_cells / total_cells
                if empty_ratio > 0.5:
                    deductions += 15
                    self.warnings.append(f"表格 {i + 1} 空单元格比例过高 ({empty_ratio:.0%})")
                    self.suggestions.append(f"表格 {i + 1} 数据完整度较低，建议检查解析过程")

            # 检查是否有标题行
            if headers:
                has_header_names = all(h and str(h).strip() for h in headers)
                if not has_header_names:
                    deductions += 5
                    self.warnings.append(f"表格 {i + 1} 标题行存在空列名")

        score = max(0, score - deductions)
        return round(score, 1)

    def _score_content_completeness(self, content: str) -> float:
        """评估内容完整度 (0-100)"""
        if not content:
            self.warnings.append("内容为空，无法评估完整度")
            return 0.0

        score = 100.0

        content_stripped = content.strip()

        # 检查是否以不完整的内容结尾
        abrupt_ending_patterns = [
            (r"\.\.\.$", 10, "内容以省略号结尾，可能被截断"),
            (r"[，,、;；:：]$", 5, "内容以标点符号结尾，可能不完整"),
            (r"\b(and|or|the|a|an|在|和|或者|的|一个)\s*$", 5, "内容以连接词结尾，可能被截断"),
            (r"[({[（【]\s*$", 10, "内容以未闭合的括号结尾"),
            (r"```\s*$", 8, "内容以未闭合的代码块结尾"),
            (r"<[^>]*$", 8, "内容以未闭合的 HTML 标签结尾"),
        ]

        for pattern, deduction, warning in abrupt_ending_patterns:
            if re.search(pattern, content_stripped, re.MULTILINE | re.IGNORECASE):
                score -= deduction
                self.warnings.append(warning)

        # 检查内容长度是否异常
        if len(content) < 10:
            score -= 20
            self.warnings.append("内容过短，可能解析不完整")
            self.suggestions.append("建议检查源文件内容是否完整")

        # 检查是否有明显的截断标记
        truncation_markers = [
            r"\b(truncated|cut off|\.\.\.\s*more|continued\.\.\.)\b",
            r"(内容已截断|以下内容省略|余下部分省略)",
        ]
        for marker in truncation_markers:
            if re.search(marker, content, re.IGNORECASE):
                score -= 15
                self.warnings.append("检测到明确的内容截断标记")
                break

        return round(max(0, score), 1)

    # ==================== 构建方法 ====================

    def analyze(
        self,
        content: str,
        file_size: int = 0,
        file_type: str = "unknown",
        structured_data: dict[str, Any] | None = None,
        parsed_file: Any = None,
    ):
        """执行完整质量分析（E4：末尾推导可操作化 actions）"""
        self.scores = {}
        self.warnings = []
        self.suggestions = []
        self.actions = []
        self._last_parsed_file = parsed_file
        # v0.14.0/B-P1-5: 记录 file_type
        self._last_file_type = file_type

        self.scores["text_coverage"] = self._score_text_coverage(content, file_size, file_type)
        self.scores["encoding_confidence"] = self._score_encoding_confidence(content)
        self.scores["structure_preservation"] = self._score_structure_preservation(content)
        self.scores["table_accuracy"] = self._score_table_accuracy(content, structured_data)
        self.scores["content_completeness"] = self._score_content_completeness(content)

        self._build_actions(content, file_type)

        return self

    @classmethod
    def from_parsed_file(cls, parsed_file, file_size: int = 0):
        """从 ParsedFile 创建质量报告"""
        report = cls()

        # 提取所有文本内容
        content_parts = []
        if hasattr(parsed_file, "pages") and parsed_file.pages:
            for page in parsed_file.pages:
                raw_text = getattr(page, "rawText", "") or ""
                content_parts.append(raw_text)
        content = "\n".join(content_parts)

        # 确定文件大小和类型
        actual_file_size = file_size if file_size > 0 else getattr(parsed_file, "fileSize", 0)
        actual_file_type = getattr(parsed_file, "fileType", None)
        if actual_file_type is not None and hasattr(actual_file_type, "value"):
            actual_file_type = actual_file_type.value
        elif actual_file_type is None:
            actual_file_type = "unknown"

        # 提取结构化数据
        structured_data = getattr(parsed_file, "structure", None)
        if structured_data is None:
            structured_data = {}

        report.analyze(content, actual_file_size, str(actual_file_type), structured_data)
        return report

    @classmethod
    def from_history_record(cls, record: dict[str, Any]):
        """从历史记录创建质量报告"""
        report = cls()

        content = record.get("converted_content", "") or record.get("convertedContent", "")
        file_size = record.get("file_size", 0) or record.get("fileSize", 0)
        file_type = record.get("file_type", "unknown") or record.get("fileType", "unknown")

        # 解析结构化数据
        structured_data = record.get("structuredData") or record.get("structured_data", "{}")
        if isinstance(structured_data, str):
            try:
                structured_data = json.loads(structured_data)
            except (json.JSONDecodeError, TypeError):
                structured_data = {}

        report.analyze(content, int(file_size), str(file_type), structured_data)
        return report

    # ==================== 属性 ====================

    @property
    def overall_score(self) -> float:
        """综合质量评分 0-100

        v0.14.0/B-P1-5: 按 file_type 动态调权重。
        - 纯文本格式（txt/md/json/yaml/...）：table_accuracy 归零（无表格意义）
        - 表格/数据格式（csv/xlsx/...）：structure_preservation 权降低，table_accuracy 权提高
        - 其他格式（pdf/docx/pptx/...）：用默认权重
        """
        if not self.scores:
            return 0.0

        # 默认权重（v0.13.0 行为）
        weights = {
            "text_coverage": 0.15,
            "encoding_confidence": 0.25,
            "structure_preservation": 0.25,
            "table_accuracy": 0.15,
            "content_completeness": 0.20,
        }
        # v0.14.0/B-P1-5: 按 file_type 调权
        ft = (self._last_file_type or "unknown").lower()
        # 纯文本/数据格式：table_accuracy 权归零（csv/xlsx/ods 是表格，单独处理）
        if ft in {"txt", "md", "markdown", "json", "yaml", "yml", "xml", "toml",
                  "html", "tsv", "sql", "srt", "vtt", "latex", "tex", "log"}:
            weights["table_accuracy"] = 0.0
        # 表格格式：table_accuracy 权提高，structure 权降低
        elif ft in {"csv", "xlsx", "xls", "ods"}:
            weights["table_accuracy"] = 0.35
            weights["structure_preservation"] = 0.10
            weights["content_completeness"] = 0.10
        # 演示/视觉格式：structure 权提高
        elif ft in {"pptx", "ppt"}:
            weights["structure_preservation"] = 0.35
            weights["content_completeness"] = 0.20

        total = 0.0
        total_weight = 0.0
        for key, score in self.scores.items():
            w = weights.get(key, 0.0)
            total += score * w
            total_weight += w

        if total_weight == 0:
            return 0.0

        return round(total / total_weight, 1)

    @property
    def grade(self) -> str:
        """A/B/C/D/F 等级"""
        score = self.overall_score
        if score >= 90:
            return "A"
        elif score >= 75:
            return "B"
        elif score >= 60:
            return "C"
        elif score >= 40:
            return "D"
        else:
            return "F"

    # ==================== 序列化 ====================

    def to_dict(self) -> dict[str, Any]:
        """返回完整报告为字典（E4：含可操作化动作 actions）"""
        return {
            "overall_score": self.overall_score,
            "grade": self.grade,
            "scores": dict(self.scores),
            "warnings": list(self.warnings),
            "suggestions": list(self.suggestions),
            "actions": list(self.actions),
        }

    # ==================== E4: 可操作化动作 ====================

    def add_action(self, code: str, message: str, suggestion: str, retry_with: dict[str, Any] | None = None) -> None:
        """记录一条可执行的质量改进动作。

        code        动作类别（encoding/coverage/table/pages…）
        message     人读描述
        suggestion  建议动作文字
        retry_with  可直接透传给 ff_translate 的重试参数（如 {"encoding":"gbk"}）
        """
        action: dict[str, Any] = {"code": code, "message": message, "suggestion": suggestion}
        if retry_with:
            action["retry_with"] = retry_with
        self.actions.append(action)

    def _build_actions(self, content: str, file_type: str) -> None:
        """从既有 warnings/scores 推导结构化动作（不重复发通知）。"""
        import re

        replacement_count = content.count("\ufffd") if content else 0
        if replacement_count > 0:
            self.add_action(
                "encoding",
                f"检测到 {replacement_count} 个替换字符 (U+FFFD)",
                "尝试用 GBK 编码重新解析该文件",
                retry_with={"encoding": "gbk"},
            )

        mojibake_count = (
            sum(len(re.findall(p, content)) for p in (r"Ã[©®\x81-\xbf]", r"â[\x80-\xbf]")) if content else 0
        )
        if mojibake_count > 0 and replacement_count == 0:
            self.add_action(
                "encoding",
                f"检测到 {mojibake_count} 个疑似乱码模式",
                "确认源文件编码后以正确编码重转",
                retry_with={"encoding": "latin-1"},
            )

        coverage = self.scores.get("text_coverage")
        if coverage is not None and coverage < 50:
            self.add_action(
                "coverage",
                "文本覆盖率较低，内容可能不完整",
                "若为扫描件请启用 OCR；否则检查文件完整性",
                retry_with={"conversion_type": "ocr"},
            )

        has_table = (
            getattr(self._last_parsed_file, "hasTable", False) if getattr(self, "_last_parsed_file", None) else False
        )
        table_sparse = (
            any(getattr(p, "hasTable", False) for p in getattr(self._last_parsed_file, "pages", []) or [])
            if self._last_parsed_file
            else False
        )
        if table_sparse or (has_table and coverage is not None and coverage < 60):
            self.add_action(
                "table",
                "检测到表格但结构化抽取可能稀疏",
                "用表格抽取策略重转以获得 Markdown 表格",
                retry_with={"conversion_type": "table"},
            )
