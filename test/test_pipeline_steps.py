"""
Unit tests for core.pipeline_steps —— 每个 Step 类独立测试
"""
import pytest
from unittest.mock import MagicMock, call, patch
from datetime import datetime

from core.models import (
    ConversionType, OutputFormat, FileType, ParsedFile, PageContent,
    ConvertResultData, FileInfo, ProcessingLog, TaskStatus,
)
from core.pipeline import PipelineContext
from core.input_adapters import InputData
from core.format_detector import DataFormat, FormatDetectionResult
from core.decision_engine import ConversionDecision

from core.pipeline_steps import (
    _map_format_to_file_type, _extract_summary, _build_raw_content,
    InitStep, InputStep, CacheCheckStep, DetectStep,
    ParseStep, DecisionStep, ConvertStep,
    FormatStep, BuildResultStep,
)


# ═══════════════════════════════════════════════════════════
# 工具函数测试
# ═══════════════════════════════════════════════════════════

from core.utils import generate_result_id


class TestGenerateResultId:
    def test_generates_non_empty_string(self):
        rid = generate_result_id()
        assert isinstance(rid, str)
        assert len(rid) > 0

    def test_starts_with_cvt_prefix(self):
        rid = generate_result_id()
        assert rid.startswith("cvt")

    def test_generates_unique_ids(self):
        ids = {generate_result_id() for _ in range(100)}
        assert len(ids) == 100  # no duplicates


class TestMapFormatToFileType:
    def test_known_format_pdf(self):
        assert _map_format_to_file_type(DataFormat.PDF) == "pdf"

    def test_known_format_docx(self):
        assert _map_format_to_file_type(DataFormat.DOCX) == "doc"

    def test_known_format_csv(self):
        assert _map_format_to_file_type(DataFormat.CSV) == "csv"

    def test_image_formats(self):
        assert _map_format_to_file_type(DataFormat.PNG) == "image"
        assert _map_format_to_file_type(DataFormat.JPEG) == "image"
        assert _map_format_to_file_type(DataFormat.SVG) == "image"

    def test_archive_formats(self):
        assert _map_format_to_file_type(DataFormat.ZIP) == "unknown"
        assert _map_format_to_file_type(DataFormat.RAR) == "unknown"

    def test_unknown_format_defaults_to_unknown(self):
        assert _map_format_to_file_type("not_a_format") == "unknown"


class TestExtractSummary:
    def test_single_page(self, parsed_file):
        summary = _extract_summary(parsed_file)
        assert "Hello World content" in summary

    def test_multiple_pages(self, parsed_pdf):
        summary = _extract_summary(parsed_pdf)
        assert "Page 1 content" in summary
        assert "Page 2 with table" in summary
        assert "Page 3 content" in summary

    def test_truncation(self):
        """内容超过1500字符时应截断"""
        pf = ParsedFile(
            parseId="p", fileName="big.txt", fileSize=5000, pageCount=3,
            fileType=FileType.TXT,
            pages=[
                PageContent(pageNumber=1, elements=[], rawText="A" * 600, hasImage=False, hasTable=False),
                PageContent(pageNumber=2, elements=[], rawText="B" * 600, hasImage=False, hasTable=False),
                PageContent(pageNumber=3, elements=[], rawText="C" * 600, hasImage=False, hasTable=False),
            ],
            createdAt=datetime.now(), status=TaskStatus.COMPLETED,
        )
        summary = _extract_summary(pf)
        assert len(summary) <= 1503  # 1500 + "..."
        assert summary.endswith("...")


class TestBuildRawContent:
    def test_returns_markdown_format(self, input_data, detected_result):
        content = _build_raw_content(input_data, detected_result)
        assert "# 原始数据" in content
        assert input_data.filename in content
        assert detected_result.format.value in content
        assert detected_result.mime_type in content
        assert str(input_data.size) in content

    def test_fallback_filename(self, detected_result):
        data = InputData(source_type="raw", data=b"x")
        content = _build_raw_content(data, detected_result)
        assert "unknown" in content


# ═══════════════════════════════════════════════════════════
# Step 0: InitStep
# ═══════════════════════════════════════════════════════════

class TestInitStep:
    def test_sets_result_id(self, basic_ctx):
        step = InitStep()
        step.process(basic_ctx)
        assert basic_ctx.result_id.startswith("cvt")
        assert len(basic_ctx.result_id) > 10

    def test_appends_init_log(self, basic_ctx):
        step = InitStep()
        step.process(basic_ctx)
        assert len(basic_ctx.logs) == 1
        assert basic_ctx.logs[0].step == "init"
        assert basic_ctx.logs[0].level == "info"
        assert "auto" in basic_ctx.logs[0].message.lower()
        assert "json" in basic_ctx.logs[0].message.lower()

    def test_preserves_existing_logs(self, basic_ctx):
        existing = ProcessingLog(timestamp=datetime.now(), step="prev", level="info", message="before")
        basic_ctx.logs.append(existing)
        InitStep().process(basic_ctx)
        assert len(basic_ctx.logs) == 2
        assert basic_ctx.logs[0].step == "prev"

    def test_respects_conversion_type_in_log(self, ctx_no_enhance):
        InitStep().process(ctx_no_enhance)
        assert "text" in ctx_no_enhance.logs[0].message.lower()


# ═══════════════════════════════════════════════════════════
# Step 1: InputStep
# ═══════════════════════════════════════════════════════════

class TestInputStep:
    def test_reads_source_and_sets_input_data(self, basic_ctx, mock_input_manager):
        basic_ctx.source = b"hello tests"
        mock_input_manager.read.return_value = InputData(
            source_type="raw", data=b"hello tests", filename="test_input.txt",
        )

        InputStep(mock_input_manager).process(basic_ctx)

        assert basic_ctx.input_data is not None
        assert basic_ctx.input_data.data == b"hello tests"
        assert basic_ctx.input_data.source_type == "raw"
        assert basic_ctx.error is None

    def test_appends_success_log(self, basic_ctx, mock_input_manager):
        InputStep(mock_input_manager).process(basic_ctx)

        logs = [l for l in basic_ctx.logs if l.step == "input"]
        assert len(logs) == 2  # "读取输入源" + 详细日志
        assert any("读取输入源" in l.message for l in logs)
        assert any("输入源类型" in l.message for l in logs)

    def test_sets_error_on_read_failure(self, basic_ctx):
        failing_mgr = MagicMock()
        failing_mgr.read.side_effect = FileNotFoundError("no such file")

        InputStep(failing_mgr).process(basic_ctx)

        assert basic_ctx.error == "输入读取失败: no such file"
        assert any(l.level == "error" for l in basic_ctx.logs if l.step == "input")


# ═══════════════════════════════════════════════════════════
# Step 2: CacheCheckStep
# ═══════════════════════════════════════════════════════════

class TestCacheCheckStep:
    def test_cache_miss_noop(self, basic_ctx, mock_pipeline, input_data):
        basic_ctx.input_data = input_data
        mock_pipeline._try_get_cached.return_value = None

        CacheCheckStep(mock_pipeline).process(basic_ctx)

        assert basic_ctx.finished is False
        assert basic_ctx.final_response is None

    def test_cache_hit_sets_finished(self, basic_ctx, mock_pipeline, input_data):
        basic_ctx.input_data = input_data
        mock_pipeline._try_get_cached.return_value = {
            "result": "cached", "decision": {},
            "recommendation": "hit",
        }

        CacheCheckStep(mock_pipeline).process(basic_ctx)

        assert basic_ctx.finished is True
        assert basic_ctx.final_response["result"] == "cached"
        assert basic_ctx.final_response["recommendation"] == "hit"
        assert any(l.step == "cache" for l in basic_ctx.logs)

    def test_passes_custom_prompt_to_cache_check(self, basic_ctx, mock_pipeline, input_data):
        basic_ctx.input_data = input_data
        basic_ctx.custom_prompt = "custom prompt"
        mock_pipeline._try_get_cached.return_value = None

        CacheCheckStep(mock_pipeline).process(basic_ctx)

        mock_pipeline._try_get_cached.assert_called_once_with(
            input_data, basic_ctx.conversion_type, basic_ctx.output_format, "custom prompt",
        )


# ═══════════════════════════════════════════════════════════
# Step 3: DetectStep
# ═══════════════════════════════════════════════════════════

class TestDetectStep:
    def test_detects_format(self, basic_ctx, mock_detector, input_data):
        basic_ctx.input_data = input_data

        DetectStep(mock_detector).process(basic_ctx)

        assert basic_ctx.detected is not None
        assert basic_ctx.detected.format == DataFormat.TXT
        mock_detector.detect.assert_called_once_with(basic_ctx.input_data.data, basic_ctx.input_data.filename)

    def test_appends_detect_logs(self, basic_ctx, mock_detector, input_data):
        basic_ctx.input_data = input_data

        DetectStep(mock_detector).process(basic_ctx)

        detect_logs = [l for l in basic_ctx.logs if l.step == "detect"]
        assert len(detect_logs) == 2
        assert any("检测输入格式" in l.message for l in detect_logs)
        assert any("txt" in l.message.lower() for l in detect_logs)


class TestParseStep:
    def test_skips_for_raw_input(self, basic_ctx, mock_pipeline, input_data):
        basic_ctx.input_data = input_data  # source_type == "raw"

        ParseStep(mock_pipeline).process(basic_ctx)

        assert basic_ctx.parsed_file is None

    def test_skips_for_stream_input(self, basic_ctx, mock_pipeline, detected_result):
        # stream 类型会触发解析，需要设置 detected 避免日志访问 None.format
        basic_ctx.input_data = InputData(source_type="stream", data=b"x")
        basic_ctx.detected = detected_result

        ParseStep(mock_pipeline).process(basic_ctx)

        assert basic_ctx.parsed_file is None

    @patch("core.file_parser.FileParser")
    def test_parses_file_input(self, mock_fp, basic_ctx, mock_pipeline, file_input_data, detected_pdf, parsed_pdf):
        basic_ctx.input_data = file_input_data
        basic_ctx.detected = detected_pdf
        basic_ctx.input_data.save_to_temp = MagicMock(return_value=MagicMock())

        mock_parser = MagicMock()
        mock_parser.parse_file.return_value = parsed_pdf
        mock_fp.return_value = mock_parser

        ParseStep(mock_pipeline).process(basic_ctx)

        assert basic_ctx.parsed_file is not None
        assert basic_ctx.parsed_file.fileType == FileType.PDF
        assert basic_ctx.parsed_file.pageCount == 3
        assert any(l.step == "parse" for l in basic_ctx.logs)

    @patch("core.file_parser.FileParser")
    def test_cleans_up_temp_file(self, mock_fp, basic_ctx, mock_pipeline, file_input_data, detected_pdf, parsed_pdf):
        basic_ctx.input_data = file_input_data
        basic_ctx.detected = detected_pdf
        temp_path = MagicMock()
        basic_ctx.input_data.save_to_temp = MagicMock(return_value=temp_path)

        mock_parser = MagicMock()
        mock_parser.parse_file.return_value = parsed_pdf
        mock_fp.return_value = mock_parser

        ParseStep(mock_pipeline).process(basic_ctx)

        temp_path.unlink.assert_called_once_with(missing_ok=True)

    @patch("core.file_parser.FileParser")
    def test_handles_parse_failure_gracefully(self, mock_fp, basic_ctx, mock_pipeline, file_input_data, detected_pdf):
        basic_ctx.input_data = file_input_data
        basic_ctx.detected = detected_pdf
        temp_path = MagicMock()
        basic_ctx.input_data.save_to_temp = MagicMock(return_value=temp_path)

        mock_fp.side_effect = RuntimeError("parse error")

        ParseStep(mock_pipeline).process(basic_ctx)

        assert basic_ctx.parsed_file is None
        assert basic_ctx.error is None  # 解析失败不中止流程
        assert any("warning" == l.level for l in basic_ctx.logs if l.step == "parse")

    def test_handles_url_input(self, basic_ctx, mock_pipeline, url_input_data, detected_result):
        basic_ctx.input_data = url_input_data
        basic_ctx.detected = detected_result

        # URL 类型也会尝试解析，但 save_to_temp 是 mock
        # 验证它进入了解析分支
        basic_ctx.input_data.save_to_temp = MagicMock(side_effect=Exception("no tmp"))

        ParseStep(mock_pipeline).process(basic_ctx)

        # 解析失败不应中止
        assert basic_ctx.error is None


# ═══════════════════════════════════════════════════════════
# Step 6: DecisionStep
# ═══════════════════════════════════════════════════════════

class TestDecisionStep:
    def test_makes_decision(self, basic_ctx, mock_decision_engine, detected_result):
        basic_ctx.detected = detected_result

        DecisionStep(mock_decision_engine).process(basic_ctx)

        assert basic_ctx.decision is not None
        assert basic_ctx.decision.conversion_needed is True
        mock_decision_engine.make_decision.assert_called_once_with(detected_result, None, None)

    def test_passes_none_caps_and_parsed_file(self, basic_ctx, mock_decision_engine,
                                                  detected_result, parsed_file):
        # 插件形态：无 AI 能力探测，make_decision 第二参恒为 None
        basic_ctx.detected = detected_result
        basic_ctx.parsed_file = parsed_file

        DecisionStep(mock_decision_engine).process(basic_ctx)

        mock_decision_engine.make_decision.assert_called_once_with(
            detected_result, None, parsed_file,
        )

    def test_appends_decision_log(self, basic_ctx, mock_decision_engine, detected_result):
        basic_ctx.detected = detected_result
        DecisionStep(mock_decision_engine).process(basic_ctx)
        assert any(l.step == "decision" for l in basic_ctx.logs)


# ═══════════════════════════════════════════════════════════
# Step 7: ConvertStep
# ═══════════════════════════════════════════════════════════

class TestConvertStep:
    def test_converts_when_needed(self, basic_ctx, mock_strategy_registry, parsed_file, decision_convert):
        basic_ctx.parsed_file = parsed_file
        basic_ctx.decision = decision_convert

        ConvertStep().process(basic_ctx)

        assert basic_ctx.content == "converted text"
        assert basic_ctx.structured_data == {"key": "value"}
        assert basic_ctx.confidence == 0.85

    def test_noop_when_no_parsed_file(self, basic_ctx, mock_strategy_registry, input_data, detected_result, decision_convert):
        """data 为空字节时回退「原始数据说明」分支。"""
        basic_ctx.parsed_file = None
        basic_ctx.decision = decision_convert
        basic_ctx.input_data = InputData(
            source_type="stream", data=b"", filename=input_data.filename,
            mime_type=input_data.mime_type, metadata={},
        )
        basic_ctx.detected = detected_result

        ConvertStep().process(basic_ctx)

        assert "# 原始数据" in basic_ctx.content
        assert basic_ctx.structured_data == {"raw_data": True, "size": 0}
        assert basic_ctx.confidence == 0.5

    def test_text_passthrough_when_no_parsed_file(self, basic_ctx, mock_strategy_registry, input_data, detected_result, decision_convert):
        """R3.3: data 非空时无论来源类型都走文本透传（quality 才能扫 FFFD/mojibake）。"""
        basic_ctx.parsed_file = None
        basic_ctx.decision = decision_convert
        basic_ctx.input_data = InputData(
            source_type="stream", data=input_data.data, filename=input_data.filename,
            mime_type=input_data.mime_type, metadata={},
        )
        basic_ctx.detected = detected_result

        ConvertStep().process(basic_ctx)

        assert basic_ctx.confidence == 1.0
        assert basic_ctx.content == "Hello World"  # conftest fixture data=b"Hello World"

    def test_raw_text_passthrough_when_no_parsed_file(self, basic_ctx, mock_strategy_registry, input_data, detected_result, decision_convert):
        """raw 文本输入（stdin）→ 文本直接透传为 content，confidence=1.0"""
        basic_ctx.parsed_file = None
        basic_ctx.decision = decision_convert
        basic_ctx.input_data = input_data  # conftest 默认即 source_type="raw"
        basic_ctx.detected = detected_result
        basic_ctx.output_format = OutputFormat.TEXT

        ConvertStep().process(basic_ctx)

        assert "Hello World" in basic_ctx.content
        assert "# 原始数据" not in basic_ctx.content
        assert basic_ctx.confidence == 1.0

    def test_noop_when_conversion_not_needed(self, basic_ctx, mock_strategy_registry, parsed_file, decision_noop, input_data, detected_result):
        basic_ctx.parsed_file = parsed_file
        basic_ctx.decision = decision_noop
        basic_ctx.input_data = input_data
        basic_ctx.detected = detected_result

        ConvertStep().process(basic_ctx)

        assert "# 原始数据" in basic_ctx.content
        assert basic_ctx.confidence == 0.5

    def test_appends_convert_logs(self, basic_ctx, mock_strategy_registry, parsed_file, decision_convert):
        basic_ctx.parsed_file = parsed_file
        basic_ctx.decision = decision_convert

        ConvertStep().process(basic_ctx)

        convert_logs = [l for l in basic_ctx.logs if l.step == "convert"]
        assert len(convert_logs) >= 2  # 至少: 执行 + 选择策略 + 完成

    def test_handles_convert_failure(self, basic_ctx, parsed_file, decision_convert, monkeypatch):
        mock_reg = MagicMock()
        mock_strategy = MagicMock()
        mock_strategy.strategy_id = "fail"
        mock_strategy.strategy_name = "fail"
        mock_strategy.convert.side_effect = RuntimeError("boom")
        mock_reg.select_best_strategy.return_value = mock_strategy

        import core.pipeline_steps
        monkeypatch.setattr(core.pipeline_steps, "strategy_registry", mock_reg)

        basic_ctx.parsed_file = parsed_file
        basic_ctx.decision = decision_convert

        ConvertStep().process(basic_ctx)

        assert "boom" in basic_ctx.content


class TestFormatStep:
    def test_formats_content(self, basic_ctx):
        basic_ctx.content = "hello"
        basic_ctx.structured_data = None
        basic_ctx.output_format = OutputFormat.JSON

        FormatStep().process(basic_ctx)

        assert len(basic_ctx.formatted_content) > 0
        assert "hello" in basic_ctx.formatted_content

    def test_appends_format_log(self, basic_ctx):
        basic_ctx.content = "data"
        basic_ctx.output_format = OutputFormat.MARKDOWN

        FormatStep().process(basic_ctx)

        format_logs = [l for l in basic_ctx.logs if l.step == "format"]
        assert len(format_logs) == 1
        assert "markdown" in format_logs[0].message.lower()


# ═══════════════════════════════════════════════════════════
# Step 10: BuildResultStep
# ═══════════════════════════════════════════════════════════

class TestBuildResultStep:
    def test_builds_full_result(self, basic_ctx, mock_pipeline, input_data, parsed_file,
                                 detected_result, decision_convert):
        basic_ctx.input_data = input_data
        basic_ctx.parsed_file = parsed_file
        basic_ctx.detected = detected_result
        basic_ctx.decision = decision_convert
        basic_ctx.confidence = 0.8
        basic_ctx.content = "the content"
        basic_ctx.formatted_content = '{"key": "the content"}'
        basic_ctx.structured_data = {"key": "value"}
        basic_ctx.result_id = "cvt_test_123"

        BuildResultStep(mock_pipeline).process(basic_ctx)

        # 验证 result_data
        assert basic_ctx.result_data is not None
        assert basic_ctx.result_data.resultId == "cvt_test_123"
        assert basic_ctx.result_data.parseId == parsed_file.parseId
        assert basic_ctx.result_data.convertedContent == basic_ctx.formatted_content
        assert basic_ctx.result_data.confidence == 0.8

        # 验证 final_response
        assert basic_ctx.final_response is not None
        assert "result" in basic_ctx.final_response
        assert "decision" in basic_ctx.final_response
        assert "recommendation" in basic_ctx.final_response

        # 验证缓存被调用
        mock_pipeline._add_to_cache.assert_called_once_with("cvt_test_123", basic_ctx.result_data)
        mock_pipeline._try_store_cached.assert_called_once()

    def test_complete_log_appended(self, basic_ctx, mock_pipeline, input_data,
                                    detected_result, decision_convert):
        basic_ctx.input_data = input_data
        basic_ctx.parsed_file = None
        basic_ctx.detected = detected_result
        basic_ctx.decision = decision_convert
        basic_ctx.formatted_content = "content"
        basic_ctx.result_id = "id"

        BuildResultStep(mock_pipeline).process(basic_ctx)

        complete_logs = [l for l in basic_ctx.logs if l.step == "complete"]
        assert len(complete_logs) == 1
        assert "耗时" in complete_logs[0].message

    def test_handles_null_parsed_file(self, basic_ctx, mock_pipeline, input_data,
                                       detected_result, decision_convert):
        basic_ctx.input_data = input_data
        basic_ctx.parsed_file = None
        basic_ctx.detected = detected_result
        basic_ctx.decision = decision_convert
        basic_ctx.formatted_content = "plain content"
        basic_ctx.result_id = "cvt_no_parse"

        BuildResultStep(mock_pipeline).process(basic_ctx)

        assert basic_ctx.result_data.parseId == ""
        assert basic_ctx.result_data.fileInfo.pageCount == 0
        assert basic_ctx.result_data.fileInfo.fileType == "unknown"
        assert basic_ctx.result_data.extractedContent == ""

    def test_calls_decision_build_recommendation(self, basic_ctx, mock_pipeline, input_data,
                                                   detected_result, decision_convert):
        basic_ctx.input_data = input_data
        basic_ctx.detected = detected_result
        basic_ctx.decision = decision_convert
        basic_ctx.formatted_content = "x"
        basic_ctx.result_id = "id"

        BuildResultStep(mock_pipeline).process(basic_ctx)

        mock_pipeline.decision_engine.build_recommendation.assert_called_once()
