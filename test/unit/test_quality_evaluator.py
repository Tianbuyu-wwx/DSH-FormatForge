"""
转换质量评估模块单元测试
"""
import pytest
import json

from core.quality_evaluator import (
    QualityEvaluator,
    QualityMetrics,
    QualityFeedback,
    quality_evaluator
)


class TestQualityEvaluator:
    """测试质量评估器"""

    def setup_method(self):
        self.evaluator = QualityEvaluator()

    def test_evaluate_text_format(self):
        """测试文本格式评估"""
        original = "Hello world. This is a test document."
        converted = "Hello world. This is a test document."

        metrics = self.evaluator.evaluate(original, converted, "text")

        assert isinstance(metrics, QualityMetrics)
        assert 0 <= metrics.overall_score <= 1
        assert metrics.readability_score > 0
        assert metrics.information_retention > 0.9  # 相同内容保留率应很高

    def test_evaluate_json_format(self):
        """测试JSON格式评估"""
        original = '{"name": "test", "value": 123}'
        converted = '{"name": "test", "value": 123, "extra": true}'

        metrics = self.evaluator.evaluate(original, converted, "json")

        assert metrics.format_compliance == 1.0  # 有效JSON
        assert metrics.structure_integrity > 0

    def test_evaluate_markdown_format(self):
        """测试Markdown格式评估"""
        original = "Some text"
        converted = "# Title\n\nSome **bold** text.\n\n- Item 1\n- Item 2"

        metrics = self.evaluator.evaluate(original, converted, "markdown")

        assert metrics.format_compliance > 0
        assert metrics.structure_integrity > 0

    def test_evaluate_empty_content(self):
        """测试空内容评估"""
        metrics = self.evaluator.evaluate("", "", "text")
        # 空内容的可读性和结构完整性为0，但信息保留率可能为1.0（空对空）
        assert metrics.readability_score == 0.0
        assert metrics.structure_integrity == 0.0

    def test_evaluate_garbled_text(self):
        """测试乱码文本评估"""
        original = "Hello world"
        converted = "ï¿½ï¿½ï¿½ï¿½ ï¿½ï¿½ï¿½ï¿½"

        metrics = self.evaluator.evaluate(original, converted, "text")
        # 乱码的可读性应该比正常文本低
        normal_metrics = self.evaluator.evaluate(original, original, "text")
        assert metrics.readability_score < normal_metrics.readability_score

    def test_evaluate_information_loss(self):
        """测试信息丢失评估"""
        original = "Important data: 123, 456, 789"
        converted = "Some text"  # 丢失了数字信息

        metrics = self.evaluator.evaluate(original, converted, "text")
        assert metrics.information_retention < 0.5

    def test_calculate_entropy(self):
        """测试熵计算"""
        # 重复内容熵低
        low_entropy = self.evaluator._calculate_entropy("aaaaaaaaaa")
        # 随机内容熵高
        high_entropy = self.evaluator._calculate_entropy("abcdefghijklmnopqrstuvwxyz")

        assert low_entropy < high_entropy

    def test_extract_keywords(self):
        """测试关键词提取"""
        text = "Hello world, this is a Python test"
        keywords = self.evaluator._extract_keywords(text)

        assert "hello" in keywords
        assert "world" in keywords
        assert "python" in keywords
        assert "test" in keywords

    def test_record_feedback(self):
        """测试记录反馈"""
        metrics = QualityMetrics(overall_score=0.85)
        self.evaluator.record_feedback(
            result_id="test-001",
            metrics=metrics,
            original_size=100,
            converted_size=80,
            user_rating=4.5,
            issues=["format_issue"]
        )

        assert len(self.evaluator._feedback_history) == 1
        feedback = self.evaluator._feedback_history[0]
        assert feedback.result_id == "test-001"
        assert feedback.user_rating == 4.5

    def test_get_statistics(self):
        """测试获取统计信息"""
        # 添加一些反馈
        for i in range(5):
            metrics = QualityMetrics(overall_score=0.5 + i * 0.1)
            self.evaluator.record_feedback(
                result_id=f"test-{i}",
                metrics=metrics,
                original_size=100,
                converted_size=80
            )

        stats = self.evaluator.get_statistics()
        assert stats["total_evaluations"] == 5
        assert "avg_score" in stats
        assert "score_distribution" in stats

    def test_get_strategy_adjustment(self):
        """测试获取策略调整建议"""
        # 添加低分反馈
        for i in range(3):
            metrics = QualityMetrics(overall_score=0.4)
            metrics.details["strategy_id"] = "test_strategy"
            self.evaluator.record_feedback(
                result_id=f"low-{i}",
                metrics=metrics,
                original_size=100,
                converted_size=80
            )

        adjustment = self.evaluator.get_strategy_adjustment("test_strategy")
        assert adjustment["adjustment_needed"] is True
        assert adjustment["current_avg_score"] < 0.7

    def test_global_evaluator(self):
        """测试全局评估器实例"""
        assert isinstance(quality_evaluator, QualityEvaluator)


class TestQualityMetrics:
    """测试质量指标数据类"""

    def test_default_values(self):
        """测试默认值"""
        metrics = QualityMetrics()
        assert metrics.readability_score == 0.0
        assert metrics.structure_integrity == 0.0
        assert metrics.overall_score == 0.0

    def test_custom_values(self):
        """测试自定义值"""
        metrics = QualityMetrics(
            readability_score=0.8,
            structure_integrity=0.9,
            information_retention=0.85,
            format_compliance=1.0,
            overall_score=0.88
        )
        assert metrics.readability_score == 0.8
        assert metrics.overall_score == 0.88
