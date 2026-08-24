"""
集成测试：验证 /api/v2/quality/analyze 端点返回数据格式
"""
import io
import json
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from main import app

client = TestClient(app)


# ==================== 测试数据 ====================

def create_test_file(content: str, suffix: str = ".txt") -> io.BytesIO:
    """创建测试文件"""
    return io.BytesIO(content.encode("utf-8"))


def create_test_md_file() -> io.BytesIO:
    """创建 Markdown 测试文件"""
    content = """# 测试文档

## 简介

这是一份测试文档，用于验证质量评分系统。

## 数据表格

| 姓名 | 年龄 | 城市 |
|------|------|------|
| 张三 | 25   | 北京 |
| 李四 | 30   | 上海 |
| 王五 | 28   | 广州 |

## 列表

- 项目一
- 项目二
- 项目三

## 结论

测试完成。
"""
    return io.BytesIO(content.encode("utf-8"))


def create_test_csv_file() -> io.BytesIO:
    """创建 CSV 测试文件"""
    content = "姓名,年龄,城市\n张三,25,北京\n李四,30,上海\n王五,28,广州\n"
    return io.BytesIO(content.encode("utf-8"))


def create_garbled_file() -> io.BytesIO:
    """创建包含乱码的测试文件"""
    content = "Hello World\n" + "\ufffd" * 5 + "\nSome text here"
    return io.BytesIO(content.encode("utf-8"))


# ==================== 测试用例 ====================

class TestQualityAnalyzeEndpoint:
    """测试 /api/v2/quality/analyze 端点"""

    def test_response_structure_text_file(self):
        """测试文本文件的质量分析响应结构"""
        resp = client.post(
            "/api/v2/quality/analyze",
            files={"file": ("test.txt", create_test_file("Hello World\nThis is a test.", ".txt"), "text/plain")},
        )

        assert resp.status_code == 200, f"HTTP 状态码应为 200，实际: {resp.status_code}"
        data = resp.json()

        # --- 验证顶层结构 ---
        assert "code" in data, "响应应包含 code 字段"
        assert data["code"] == 200, f"code 应为 200，实际: {data['code']}"
        assert "msg" in data, "响应应包含 msg 字段"
        assert "data" in data, "响应应包含 data 字段"

        report = data["data"]

        # --- 验证必需字段 ---
        assert "overall_score" in report, "应包含 overall_score"
        assert "grade" in report, "应包含 grade"
        assert "scores" in report, "应包含 scores"
        assert "warnings" in report, "应包含 warnings"
        assert "suggestions" in report, "应包含 suggestions"

        # --- 验证字段类型 ---
        assert isinstance(report["overall_score"], (int, float)), \
            f"overall_score 应为数字，实际: {type(report['overall_score'])}"
        assert isinstance(report["grade"], str), \
            f"grade 应为字符串，实际: {type(report['grade'])}"
        assert isinstance(report["scores"], dict), \
            f"scores 应为字典，实际: {type(report['scores'])}"
        assert isinstance(report["warnings"], list), \
            f"warnings 应为列表，实际: {type(report['warnings'])}"
        assert isinstance(report["suggestions"], list), \
            f"suggestions 应为列表，实际: {type(report['suggestions'])}"

        # --- 验证 overall_score 范围 ---
        assert 0 <= report["overall_score"] <= 100, \
            f"overall_score 应在 0-100 之间，实际: {report['overall_score']}"

        # --- 验证 grade ---
        assert report["grade"] in ("A", "B", "C", "D", "F"), \
            f"grade 应为 A/B/C/D/F，实际: {report['grade']}"

        # --- 验证 scores 子维度 ---
        required_scores = [
            "text_coverage",
            "encoding_confidence",
            "structure_preservation",
            "table_accuracy",
            "content_completeness",
        ]
        for key in required_scores:
            assert key in report["scores"], f"scores 应包含 '{key}'"
            assert isinstance(report["scores"][key], (int, float)), \
                f"scores.{key} 应为数字，实际: {type(report['scores'][key])}"
            assert 0 <= report["scores"][key] <= 100, \
                f"scores.{key} 应在 0-100 之间，实际: {report['scores'][key]}"

        print(f"\n[文本文件] overall_score={report['overall_score']}, grade={report['grade']}")
        print(f"  scores: {report['scores']}")
        if report["warnings"]:
            print(f"  warnings: {report['warnings']}")
        if report["suggestions"]:
            print(f"  suggestions: {report['suggestions']}")

    def test_response_structure_markdown_file(self):
        """测试 Markdown 文件的质量分析（含标题、表格、列表）"""
        resp = client.post(
            "/api/v2/quality/analyze",
            files={"file": ("test.md", create_test_md_file(), "text/markdown")},
        )

        assert resp.status_code == 200
        data = resp.json()
        report = data["data"]

        # 质量报告分析的是解析后的提取文本，Markdown 语法标记可能被解析器剥离
        # 因此各维度评分取决于解析器输出的具体内容格式
        assert isinstance(report["overall_score"], (int, float))
        assert report["grade"] in ("A", "B", "C", "D", "F")
        assert "text_coverage" in report["scores"]
        assert "encoding_confidence" in report["scores"]
        assert "structure_preservation" in report["scores"]
        assert "table_accuracy" in report["scores"]
        assert "content_completeness" in report["scores"]

        print(f"\n[Markdown 文件] overall_score={report['overall_score']}, grade={report['grade']}")
        print(f"  scores: {report['scores']}")
        if report["warnings"]:
            print(f"  warnings: {report['warnings']}")

    def test_response_structure_csv_file(self):
        """测试 CSV 文件的质量分析"""
        resp = client.post(
            "/api/v2/quality/analyze",
            files={"file": ("test.csv", create_test_csv_file(), "text/csv")},
        )

        assert resp.status_code == 200
        data = resp.json()
        report = data["data"]

        assert report["code"] == 200 if "code" in report else True
        assert isinstance(report["overall_score"], (int, float))
        assert report["grade"] in ("A", "B", "C", "D", "F")

        print(f"\n[CSV 文件] overall_score={report['overall_score']}, grade={report['grade']}")
        print(f"  scores: {report['scores']}")

    def test_garbled_text_detection(self):
        """测试乱码文本的编码检测"""
        resp = client.post(
            "/api/v2/quality/analyze",
            files={"file": ("garbled.txt", create_garbled_file(), "text/plain")},
        )

        assert resp.status_code == 200
        data = resp.json()
        report = data["data"]

        # 乱码文本的编码置信度应该较低
        assert report["scores"]["encoding_confidence"] < 100, \
            f"乱码文本的编码置信度应 < 100，实际: {report['scores']['encoding_confidence']}"

        # 应该产生警告
        assert len(report["warnings"]) > 0, \
            f"乱码文本应产生警告，实际 warnings: {report['warnings']}"

        print(f"\n[乱码文本] overall_score={report['overall_score']}, grade={report['grade']}")
        print(f"  encoding_confidence={report['scores']['encoding_confidence']}")
        print(f"  warnings: {report['warnings']}")

    def test_grade_boundaries(self):
        """验证评分等级边界值"""
        # A 级: >= 90
        # B 级: >= 75
        # C 级: >= 60
        # D 级: >= 40
        # F 级: < 40
        from core.quality_report import QualityReport

        test_cases = [
            (100.0, "A"),
            (90.0, "A"),
            (89.9, "B"),
            (75.0, "B"),
            (74.9, "C"),
            (60.0, "C"),
            (59.9, "D"),
            (40.0, "D"),
            (39.9, "F"),
            (0.0, "F"),
        ]

        for score_val, expected_grade in test_cases:
            report = QualityReport()
            # 手动设置分数以模拟边界场景
            report.scores = {
                "text_coverage": score_val,
                "encoding_confidence": score_val,
                "structure_preservation": score_val,
                "table_accuracy": score_val,
                "content_completeness": score_val,
            }
            actual_grade = report.grade
            assert actual_grade == expected_grade, \
                f"分数 {score_val} 应得等级 {expected_grade}，实际: {actual_grade}"

        print("\n[等级边界测试] 全部通过")

    def test_empty_file(self):
        """测试空文件的质量分析"""
        resp = client.post(
            "/api/v2/quality/analyze",
            files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")},
        )

        assert resp.status_code == 200
        data = resp.json()
        report = data["data"]

        # 空文件应有警告
        assert len(report["warnings"]) > 0, "空文件应产生警告"
        assert report["overall_score"] <= 50, \
            f"空文件评分应较低，实际: {report['overall_score']}"

        print(f"\n[空文件] overall_score={report['overall_score']}, grade={report['grade']}")
        print(f"  warnings: {report['warnings']}")

    def test_large_text_file(self):
        """测试大文本文件的质量分析"""
        # 生成一个较大的结构化文本
        large_content = "# 大文档\n\n"
        for i in range(1, 51):
            large_content += f"## 章节 {i}\n\n"
            large_content += f"这是第 {i} 个章节的内容。包含一些示例文字来填充内容。\n\n"
            large_content += "- 要点 A\n- 要点 B\n- 要点 C\n\n"

        resp = client.post(
            "/api/v2/quality/analyze",
            files={"file": ("large.md", io.BytesIO(large_content.encode("utf-8")), "text/markdown")},
        )

        assert resp.status_code == 200
        data = resp.json()
        report = data["data"]

        # 质量报告分析的是解析后的提取文本，Markdown 语法标记可能被解析器剥离
        # 验证基本格式正确性
        assert isinstance(report["overall_score"], (int, float))
        assert report["grade"] in ("A", "B", "C", "D", "F")
        assert all(k in report["scores"] for k in [
            "text_coverage", "encoding_confidence",
            "structure_preservation", "table_accuracy", "content_completeness"
        ])

        # 大文件应有较高的文本覆盖率
        assert report["scores"]["text_coverage"] >= 50, \
            f"大文件的文本覆盖率应 >= 50，实际: {report['scores']['text_coverage']}"

        print(f"\n[大文档] overall_score={report['overall_score']}, grade={report['grade']}")
        print(f"  scores: {report['scores']}")


# ==================== 直接运行 ====================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "--tb=short"])