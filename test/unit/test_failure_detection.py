"""
失败可检测性测试（H1 / audit）。

管线失败时 pipeline.run() 仍返回真实 ConvertResultData（convertedContent=错误文本、
structuredData={"error": True}）——两个入口必须把它路由为失败，而不是 ok:true。
另外：解析失败被吞掉后的 raw 字节透传不得伪装 confidence 1.0。
"""

from datetime import datetime
from pathlib import Path

import pytest


def create_processing_log_created_at() -> datetime:
    return datetime(2026, 1, 1)


@pytest.fixture
def error_response(monkeypatch):
    """让 ConversionPipeline.run 返回真实错误响应页（_build_error_response 的产物）。"""
    from core.models import ConversionType, OutputFormat
    from core.pipeline import ConversionPipeline, PipelineContext

    pipeline = ConversionPipeline(enable_content_cache=False)
    ctx = PipelineContext(
        source=Path("dummy.bin"),
        conversion_type=ConversionType.AUTO,
        output_format=OutputFormat.TEXT,
    )
    ctx.error = "PDF 解析失败: boom"
    ctx.result_id = "test_result"
    resp = pipeline._build_error_response(ctx)
    monkeypatch.setattr(ConversionPipeline, "run", lambda self, ctx: resp)
    return pipeline


@pytest.fixture
def sample_file(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text("hello", encoding="utf-8")
    return f


@pytest.fixture
def exploding_strategy(monkeypatch):
    """Force the pipeline through ConvertStep's strategy-exception handler."""
    from core.pipeline_steps import strategy_registry

    class ExplodingStrategy:
        strategy_name = "exploding-test-strategy"

        def convert(self, *_args, **_kwargs):
            raise RuntimeError("strategy boom")

    monkeypatch.setattr(strategy_registry, "select_best_strategy", lambda *_args, **_kwargs: ExplodingStrategy())


class TestTranslateFileDataFailureDetection:
    def test_error_result_routes_to_parse_failed(self, error_response, sample_file):
        from formatforge.__main__ import translate_file_data

        data, code = translate_file_data(source=sample_file)
        assert data["kind"] == "parse_failed"
        assert code != 0

    def test_pages_error_still_bad_request(self, monkeypatch, sample_file):
        """pages 非法仍走 bad_request（exit 7），错误文本里带 marker。"""
        from core.models import ConversionType, ConvertResultData, FileInfo, FileType, OutputFormat
        from core.pipeline import ConversionPipeline

        resp = {
            "result": ConvertResultData(
                resultId="r1",
                parseId="",
                fileInfo=FileInfo(fileName="error", fileSize=0, pageCount=0, fileType=FileType.UNKNOWN),
                conversionType=ConversionType.AUTO,
                outputFormat=OutputFormat.TEXT,
                extractedContent="",
                convertedContent="pages 参数格式错误: 5-1",
                structuredData={"error": True},
                confidence=0.0,
                processingLogs=[],
                createdAt=create_processing_log_created_at(),
            ),
            "decision": None,
            "recommendation": "处理失败",
        }
        monkeypatch.setattr(ConversionPipeline, "run", lambda self, ctx: resp)
        from formatforge.__main__ import translate_file_data

        data, code = translate_file_data(source=sample_file, pages="5-1")
        assert data["kind"] == "bad_request"
        assert code == 7


class TestCmdTranslateMainFailureDetection:
    def test_batch_entry_raises_on_error_response(self, error_response, sample_file):
        from formatforge.__main__ import cmd_translate_main

        with pytest.raises(ValueError, match="PDF 解析失败: boom"):
            cmd_translate_main(sample_file, "text", "auto", 30)


class TestStrategyFailureDetection:
    def test_translate_reports_strategy_exception_as_failure(self, exploding_strategy, sample_file):
        """T2-10: strategy exceptions must not become ok:true document content."""
        from formatforge.__main__ import translate_file_data

        data, code = translate_file_data(source=sample_file)
        assert code == 4
        assert data == {"kind": "parse_failed", "message": "转换失败: strategy boom"}

    def test_batch_entry_raises_for_strategy_exception(self, exploding_strategy, sample_file):
        from formatforge.__main__ import cmd_translate_main

        with pytest.raises(ValueError, match="转换失败: strategy boom"):
            cmd_translate_main(sample_file, "text", "auto", 30)


class TestRawPassthroughHonesty:
    def test_binary_input_not_confidence_1(self, tmp_path):
        """file 输入解析失败被吞 → raw 透传不得标 confidence 1.0。"""
        f = tmp_path / "broken.pdf"
        f.write_bytes(b"%PDF-1.7 \x00\xff\xfe garbage not-a-real-pdf \x01\x02")
        from formatforge.__main__ import translate_file_data

        data, code = translate_file_data(source=f, quality=False)
        assert code == 0  # raw 透传仍是成功路径，但置信度必须诚实
        assert data is not None
        assert data["meta"]["confidence"] < 1.0
        sd = data.get("structured_data") or {}
        assert sd.get("raw_passthrough") is True

    def test_plain_stdin_text_keeps_confidence_1(self):
        from formatforge.__main__ import translate_file_data

        data, code = translate_file_data(source="Hello FormatForge")
        assert code == 0
        assert data["meta"]["confidence"] == 1.0
