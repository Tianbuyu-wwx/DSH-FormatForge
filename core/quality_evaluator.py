"""
转换质量评估模块
基于多维度指标动态评估转换质量，支持反馈闭环
"""
import json
import math
import re
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("quality_evaluator")


@dataclass
class QualityMetrics:
    """质量评估指标"""
    readability_score: float = 0.0  # 文本可读性 (0-1)
    structure_integrity: float = 0.0  # 结构化完整性 (0-1)
    information_retention: float = 0.0  # 信息保留率 (0-1)
    format_compliance: float = 0.0  # 格式合规性 (0-1)
    overall_score: float = 0.0  # 综合评分 (0-1)
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class QualityFeedback:
    """质量反馈记录"""
    result_id: str
    metrics: QualityMetrics
    original_size: int
    converted_size: int
    timestamp: datetime
    user_rating: Optional[float] = None  # 用户评分 (1-5)
    issues: List[str] = field(default_factory=list)


class QualityEvaluator:
    """转换质量评估器"""

    def __init__(self):
        self._feedback_history: List[QualityFeedback] = []
        self._strategy_performance: Dict[str, List[float]] = {}

    def evaluate(
        self,
        original_content: str,
        converted_content: str,
        output_format: str,
        structured_data: Optional[Dict] = None
    ) -> QualityMetrics:
        """
        评估转换质量

        Args:
            original_content: 原始内容
            converted_content: 转换后的内容
            output_format: 输出格式 (json, markdown, text, html)
            structured_data: 结构化数据（如有）

        Returns:
            QualityMetrics: 质量指标
        """
        metrics = QualityMetrics()

        # 1. 文本可读性评估
        metrics.readability_score = self._evaluate_readability(converted_content)

        # 2. 结构化完整性评估
        metrics.structure_integrity = self._evaluate_structure(
            converted_content, output_format, structured_data
        )

        # 3. 信息保留率评估
        metrics.information_retention = self._evaluate_information_retention(
            original_content, converted_content
        )

        # 4. 格式合规性评估
        metrics.format_compliance = self._evaluate_format_compliance(
            converted_content, output_format
        )

        # 计算综合评分（加权平均）
        weights = {
            "readability": 0.25,
            "structure": 0.25,
            "retention": 0.30,
            "compliance": 0.20
        }

        metrics.overall_score = (
            metrics.readability_score * weights["readability"] +
            metrics.structure_integrity * weights["structure"] +
            metrics.information_retention * weights["retention"] +
            metrics.format_compliance * weights["compliance"]
        )

        metrics.details = {
            "original_length": len(original_content),
            "converted_length": len(converted_content),
            "compression_ratio": len(converted_content) / max(len(original_content), 1),
            "weights": weights
        }

        return metrics

    def _evaluate_readability(self, content: str) -> float:
        """评估文本可读性"""
        if not content:
            return 0.0

        scores = []

        # 1. 字符分布熵（越低越规律，越高越混乱）
        entropy = self._calculate_entropy(content)
        # 正常文本熵值通常在 3.5-5.5 之间
        entropy_score = max(0, min(1, 1 - abs(entropy - 4.5) / 3))
        scores.append(entropy_score)

        # 2. 可打印字符比例
        printable_ratio = sum(1 for c in content if c.isprintable() or c.isspace()) / max(len(content), 1)
        scores.append(printable_ratio)

        # 3. 合理行长度比例
        lines = content.split("\n")
        if lines:
            reasonable_lines = sum(1 for line in lines if 10 <= len(line) <= 500)
            line_score = reasonable_lines / len(lines)
            scores.append(line_score)

        # 4. 标点符号密度（正常文本应有适当标点）
        punct_count = sum(1 for c in content if c in ".,;:!?。，；：！？")
        punct_ratio = punct_count / max(len(content), 1)
        punct_score = max(0, min(1, 1 - abs(punct_ratio - 0.05) / 0.05))
        scores.append(punct_score)

        return sum(scores) / len(scores) if scores else 0.0

    def _calculate_entropy(self, text: str) -> float:
        """计算字符分布熵"""
        if not text:
            return 0.0

        freq = {}
        for char in text:
            freq[char] = freq.get(char, 0) + 1

        entropy = 0.0
        length = len(text)
        for count in freq.values():
            p = count / length
            entropy -= p * math.log2(p)

        return entropy

    def _evaluate_structure(
        self,
        content: str,
        output_format: str,
        structured_data: Optional[Dict]
    ) -> float:
        """评估结构化完整性"""
        if not content:
            return 0.0

        scores = []

        # 1. 根据输出格式检查结构
        if output_format == "json":
            try:
                parsed = json.loads(content)
                # 检查是否有嵌套结构
                depth = self._get_dict_depth(parsed)
                structure_score = min(1.0, depth / 3)
                scores.append(structure_score)

                # 检查键值对数量
                key_count = self._count_keys(parsed)
                scores.append(min(1.0, key_count / 10))
            except:
                scores.append(0.0)

        elif output_format == "markdown":
            # 检查Markdown结构元素
            headers = len(re.findall(r'^#{1,6}\s', content, re.MULTILINE))
            tables = len(re.findall(r'\|.*\|.*\|', content))
            lists = len(re.findall(r'^\s*[-*+]\s', content, re.MULTILINE))

            structure_elements = headers + tables + lists
            scores.append(min(1.0, structure_elements / 5))

        elif output_format == "html":
            # 检查HTML标签
            tags = len(re.findall(r'<[^>]+>', content))
            scores.append(min(1.0, tags / 10))

        else:  # text
            # 检查段落结构
            paragraphs = len([p for p in content.split("\n\n") if p.strip()])
            scores.append(min(1.0, paragraphs / 3))

        # 2. 检查结构化数据完整性
        if structured_data:
            scores.append(1.0)
        else:
            scores.append(0.5)

        return sum(scores) / len(scores) if scores else 0.0

    def _get_dict_depth(self, d: Any, level: int = 0) -> int:
        """获取字典嵌套深度"""
        if not isinstance(d, dict):
            return level
        if not d:
            return level
        return max(self._get_dict_depth(v, level + 1) for v in d.values())

    def _count_keys(self, d: Any) -> int:
        """统计字典中的键数量"""
        if not isinstance(d, dict):
            return 0
        count = len(d)
        for v in d.values():
            count += self._count_keys(v)
        return count

    def _evaluate_information_retention(
        self,
        original: str,
        converted: str
    ) -> float:
        """评估信息保留率"""
        if not original:
            return 1.0 if not converted else 0.0

        # 1. 长度保留率（不应过度压缩）
        original_len = len(original)
        converted_len = len(converted)
        length_ratio = converted_len / original_len

        # 理想保留率在 0.3-1.5 之间
        if 0.3 <= length_ratio <= 1.5:
            length_score = 1.0
        elif length_ratio < 0.3:
            length_score = length_ratio / 0.3
        else:
            length_score = max(0, 1 - (length_ratio - 1.5) / 2)

        # 2. 关键词保留率
        original_words = set(self._extract_keywords(original))
        converted_words = set(self._extract_keywords(converted))

        if original_words:
            keyword_retention = len(original_words & converted_words) / len(original_words)
        else:
            keyword_retention = 1.0

        # 3. 数字信息保留率
        original_numbers = set(re.findall(r'\d+\.?\d*', original))
        converted_numbers = set(re.findall(r'\d+\.?\d*', converted))

        if original_numbers:
            number_retention = len(original_numbers & converted_numbers) / len(original_numbers)
        else:
            number_retention = 1.0

        return (length_score * 0.3 + keyword_retention * 0.4 + number_retention * 0.3)

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词（简单实现）"""
        # 提取长度大于2的字母/中文字符串
        words = re.findall(r'[a-zA-Z]{3,}|[\u4e00-\u9fff]{2,}', text)
        return [w.lower() for w in words]

    def _evaluate_format_compliance(self, content: str, output_format: str) -> float:
        """评估格式合规性"""
        if not content:
            return 0.0

        if output_format == "json":
            try:
                json.loads(content)
                return 1.0
            except:
                return 0.0

        elif output_format == "markdown":
            # 检查基本Markdown语法
            checks = [
                bool(re.search(r'^#{1,6}\s', content, re.MULTILINE)),  # 标题
                bool(re.search(r'\*\*|__', content)),  # 粗体
                bool(re.search(r'\*|_', content)),  # 斜体
                bool(re.search(r'\[.*?\]\(.*?\)', content)),  # 链接
                bool(re.search(r'```', content)),  # 代码块
            ]
            return sum(checks) / len(checks) if checks else 0.5

        elif output_format == "html":
            # 检查基本HTML结构
            has_html_tag = bool(re.search(r'<html', content, re.IGNORECASE))
            has_body_tag = bool(re.search(r'<body', content, re.IGNORECASE))
            has_closing_tags = bool(re.search(r'</\w+>', content))
            checks = [has_html_tag or has_body_tag, has_closing_tags]
            return sum(checks) / len(checks) if checks else 0.5

        else:  # text
            # 纯文本总是合规的
            return 1.0

    def record_feedback(
        self,
        result_id: str,
        metrics: QualityMetrics,
        original_size: int,
        converted_size: int,
        user_rating: Optional[float] = None,
        issues: Optional[List[str]] = None
    ):
        """记录转换反馈"""
        feedback = QualityFeedback(
            result_id=result_id,
            metrics=metrics,
            original_size=original_size,
            converted_size=converted_size,
            timestamp=datetime.now(),
            user_rating=user_rating,
            issues=issues or []
        )
        self._feedback_history.append(feedback)

        # 限制历史记录大小
        if len(self._feedback_history) > 1000:
            self._feedback_history = self._feedback_history[-1000:]

        logger.info(f"记录质量反馈: result_id={result_id}, score={metrics.overall_score:.2f}")

    def get_strategy_adjustment(self, strategy_id: str) -> Dict[str, Any]:
        """基于反馈历史获取策略调整建议"""
        relevant_feedback = [
            f for f in self._feedback_history
            if f.metrics.details.get("strategy_id") == strategy_id
        ]

        if not relevant_feedback:
            return {"adjustment_needed": False}

        avg_score = sum(f.metrics.overall_score for f in relevant_feedback) / len(relevant_feedback)

        adjustment = {
            "adjustment_needed": avg_score < 0.7,
            "current_avg_score": avg_score,
            "sample_size": len(relevant_feedback),
            "suggestions": []
        }

        if avg_score < 0.5:
            adjustment["suggestions"].append("策略效果较差，建议重新设计或更换策略")
        elif avg_score < 0.7:
            adjustment["suggestions"].append("策略有改进空间，建议优化参数")

        # 分析常见问题
        all_issues = []
        for f in relevant_feedback:
            all_issues.extend(f.issues)

        if all_issues:
            from collections import Counter
            common_issues = Counter(all_issues).most_common(3)
            adjustment["common_issues"] = common_issues

        return adjustment

    def get_statistics(self) -> Dict[str, Any]:
        """获取评估统计信息"""
        if not self._feedback_history:
            return {"total_evaluations": 0}

        scores = [f.metrics.overall_score for f in self._feedback_history]
        return {
            "total_evaluations": len(self._feedback_history),
            "avg_score": sum(scores) / len(scores),
            "min_score": min(scores),
            "max_score": max(scores),
            "score_distribution": {
                "excellent (>0.9)": sum(1 for s in scores if s > 0.9),
                "good (0.7-0.9)": sum(1 for s in scores if 0.7 <= s <= 0.9),
                "fair (0.5-0.7)": sum(1 for s in scores if 0.5 <= s < 0.7),
                "poor (<0.5)": sum(1 for s in scores if s < 0.5),
            }
        }


# 全局评估器
quality_evaluator = QualityEvaluator()
