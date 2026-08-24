"""
集成测试 - API 路由端到端测试
使用 FastAPI TestClient 测试所有 HTTP 接口
"""
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# 必须在导入 main 之前设置环境变量
os.environ.setdefault("MINIMAX_API_KEY", "test-key")
os.environ.setdefault("MINIMAX_BASE_URL", "https://test.api.minimax.chat")

from core.config import settings
from core.models import ExtractedElement, FileType, PageContent, ParsedFile, TaskStatus
from main import app, data_converter, file_parser

client = TestClient(app)


class TestFixtures:
    """集成测试数据工厂"""

    @staticmethod
    def create_test_txt_file(content: str = "Hello World\nThis is a test file.") -> Path:
        """创建测试 TXT 文件"""
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(content)
        return Path(path)

    @staticmethod
    def create_test_csv_file() -> Path:
        """创建测试 CSV 文件"""
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write("Name,Age,City\n")
            f.write("Alice,30,Beijing\n")
            f.write("Bob,25,Shanghai\n")
        return Path(path)

    @staticmethod
    def create_parsed_file_in_cache(parse_id: str = "test_parse_123"):
        """在解析缓存中创建测试数据"""
        parsed = ParsedFile(
            parseId=parse_id,
            fileName="test.pdf",
            fileSize=1024,
            pageCount=1,
            fileType=FileType.PDF,
            pages=[PageContent(
                pageNumber=1,
                elements=[ExtractedElement(elementId="e1", elementType="text", content="Test content")],
                rawText="Test content",
                hasImage=False,
                hasTable=False
            )],
            createdAt=datetime.now(),
            status=TaskStatus.COMPLETED,
            filePath="/tmp/test.pdf"
        )
        file_parser.parsed_cache[parse_id] = parsed
        return parsed

    @staticmethod
    def cleanup_file(path: Path):
        """清理测试文件"""
        if path.exists():
            path.unlink()


# ==================== 基础路由测试 ====================

class TestRootEndpoints:
    """测试根路径和健康检查"""

    def test_root_endpoint(self):
        """测试根路径返回服务信息"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "AI 数据转换器"
        assert "docs" in data
        assert "health" in data

    def test_health_check(self):
        """测试健康检查接口"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200
        assert data["msg"] == "服务运行正常"
        assert "data" in data
        assert data["data"]["status"] == "healthy"

    def test_debug_config(self):
        """测试调试配置接口"""
        import os
        os.environ["DEBUG"] = "true"
        # 重新加载 config 使 DEBUG 生效
        from core.config import settings
        settings.DEBUG = True

        response = client.get("/debug/config")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200
        assert "minimax_base_url" in data["data"]


# ==================== 文件上传测试 ====================

class TestFileUpload:
    """测试文件上传接口"""

    def test_upload_txt_file(self):
        """测试上传 TXT 文件"""
        test_file = TestFixtures.create_test_txt_file()
        try:
            with open(test_file, "rb") as f:
                response = client.post(
                    "/api/v1/convert/upload",
                    data={"fileType": "txt"},
                    files={"file": ("test.txt", f, "text/plain")}
                )

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 200
            assert data["msg"] == "文件解析成功"
            assert "parseId" in data["data"]
            assert data["data"]["fileInfo"]["fileName"].endswith("test.txt")
        finally:
            TestFixtures.cleanup_file(test_file)

    def test_upload_csv_file(self):
        """测试上传 CSV 文件"""
        test_file = TestFixtures.create_test_csv_file()
        try:
            with open(test_file, "rb") as f:
                response = client.post(
                    "/api/v1/convert/upload",
                    data={"fileType": "csv"},
                    files={"file": ("test.csv", f, "text/csv")}
                )

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 200
            assert data["data"]["fileInfo"]["fileType"] == "csv"
        finally:
            TestFixtures.cleanup_file(test_file)

    def test_upload_unsupported_type(self):
        """测试上传不支持的文件类型"""
        # 创建一个无扩展名的临时文件，模拟不支持的类型
        fd, path = tempfile.mkstemp(suffix=".xyz")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write("test content")
        test_file = Path(path)
        try:
            with open(test_file, "rb") as f:
                response = client.post(
                    "/api/v1/convert/upload",
                    data={"fileType": "txt"},
                    files={"file": ("test.xyz", f, "application/octet-stream")}
                )

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 400
            assert "不支持" in data["msg"]
        finally:
            TestFixtures.cleanup_file(test_file)

    def test_upload_wrong_extension(self):
        """测试上传不允许的扩展名"""
        fd, path = tempfile.mkstemp(suffix=".exe")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write("test content")
        test_file = Path(path)
        try:
            with open(test_file, "rb") as f:
                response = client.post(
                    "/api/v1/convert/upload",
                    data={"fileType": "txt"},
                    files={"file": ("test.exe", f, "application/octet-stream")}
                )

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 400
        finally:
            TestFixtures.cleanup_file(test_file)

    def test_upload_no_file(self):
        """测试不上传文件"""
        response = client.post(
            "/api/v1/convert/upload",
            data={"fileType": "txt"}
        )
        assert response.status_code == 422


# ==================== 解析状态查询测试 ====================

class TestParseStatus:
    """测试解析状态查询"""

    def test_get_existing_parse_status(self):
        """测试查询存在的解析任务"""
        parsed = TestFixtures.create_parsed_file_in_cache("parse_status_1")

        response = client.get(f"/api/v1/convert/status/{parsed.parseId}")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200
        assert data["data"]["parseId"] == parsed.parseId
        assert data["data"]["taskStatus"] == "completed"

    def test_get_nonexistent_parse_status(self):
        """测试查询不存在的解析任务"""
        response = client.get("/api/v1/convert/status/nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 404
        assert "不存在" in data["msg"]


# ==================== 转换执行测试 ====================

class TestConversion:
    """测试数据转换接口"""

    def test_convert_existing_parse(self):
        """测试对存在的解析结果执行转换"""
        parsed = TestFixtures.create_parsed_file_in_cache("convert_test_1")

        response = client.post(
            "/api/v1/convert/run",
            json={
                "parseId": parsed.parseId,
                "conversionType": "text",
                "outputFormat": "text",
                "enc": "test_signature"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200
        assert data["msg"] == "转换成功"
        assert "resultId" in data["data"]
        assert "confidence" in data["data"]
        assert "preview" in data["data"]

    def test_convert_nonexistent_parse(self):
        """测试对不存在的解析结果执行转换"""
        response = client.post(
            "/api/v1/convert/run",
            json={
                "parseId": "nonexistent",
                "conversionType": "text",
                "outputFormat": "text",
                "enc": "test_signature"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 404
        assert "不存在" in data["msg"]

    def test_convert_auto_type(self):
        """测试自动检测类型转换"""
        parsed = TestFixtures.create_parsed_file_in_cache("convert_auto_1")

        response = client.post(
            "/api/v1/convert/run",
            json={
                "parseId": parsed.parseId,
                "conversionType": "auto",
                "outputFormat": "json",
                "enc": "test_signature"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200
        assert data["data"]["conversionType"] == "auto"

    def test_convert_with_custom_prompt(self):
        """测试带自定义提示词的转换"""
        parsed = TestFixtures.create_parsed_file_in_cache("convert_custom_1")

        response = client.post(
            "/api/v1/convert/run",
            json={
                "parseId": parsed.parseId,
                "conversionType": "structured",
                "outputFormat": "json",
                "customPrompt": "Extract all headings",
                "enc": "test_signature"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200

    def test_convert_table_content(self):
        """测试表格转换"""
        parsed = TestFixtures.create_parsed_file_in_cache("convert_table_1")
        # 修改为有表格的页面
        parsed.pages[0].hasTable = True
        parsed.pages[0].elements[0].elementType = "table"
        parsed.pages[0].elements[0].content = "A\tB\n1\t2"

        response = client.post(
            "/api/v1/convert/run",
            json={
                "parseId": parsed.parseId,
                "conversionType": "table",
                "outputFormat": "markdown",
                "enc": "test_signature"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200


# ==================== 结果查询测试 ====================

class TestGetResult:
    """测试获取转换结果"""

    def test_get_existing_result(self):
        """测试获取存在的转换结果"""
        parsed = TestFixtures.create_parsed_file_in_cache("result_test_1")
        result = data_converter.convert(parsed)

        response = client.get(f"/api/v1/convert/result/{result.resultId}")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 200
        assert data["data"]["resultId"] == result.resultId
        assert "convertedContent" in data["data"]
        assert "processingLogs" in data["data"]

    def test_get_nonexistent_result(self):
        """测试获取不存在的转换结果"""
        response = client.get("/api/v1/convert/result/nonexistent")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 404
        assert "不存在" in data["msg"]


# ==================== 导出测试 ====================

class TestExport:
    """测试结果导出"""

    def test_export_txt(self):
        """测试导出为 TXT"""
        parsed = TestFixtures.create_parsed_file_in_cache("export_test_1")
        result = data_converter.convert(parsed)

        response = client.get(f"/api/v1/convert/export/{result.resultId}?format=txt")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        content = response.text
        assert parsed.fileName in content

    def test_export_md(self):
        """测试导出为 Markdown"""
        parsed = TestFixtures.create_parsed_file_in_cache("export_test_2")
        result = data_converter.convert(parsed)

        response = client.get(f"/api/v1/convert/export/{result.resultId}?format=md")
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/markdown; charset=utf-8"
        content = response.text
        assert "#" in content

    def test_export_json(self):
        """测试导出为 JSON"""
        parsed = TestFixtures.create_parsed_file_in_cache("export_test_3")
        result = data_converter.convert(parsed)

        response = client.get(f"/api/v1/convert/export/{result.resultId}?format=json")
        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]
        content = response.text
        data = json.loads(content)
        assert "resultId" in data

    def test_export_nonexistent_result(self):
        """测试导出不存在的转换结果"""
        response = client.get("/api/v1/convert/export/nonexistent?format=txt")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 404


# ==================== 简化版自动转换测试 ====================

class TestAutoConvert:
    """测试简化版自动转换接口"""

    def test_auto_convert_txt(self):
        """测试自动转换 TXT 文件"""
        test_file = TestFixtures.create_test_txt_file("Auto convert test content")
        try:
            with open(test_file, "rb") as f:
                response = client.post(
                    "/api/v1/convert/auto",
                    data={
                        "fileType": "auto",
                        "conversionType": "auto",
                        "outputFormat": "text"
                    },
                    files={"file": ("auto_test.txt", f, "text/plain")}
                )

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 200
            assert data["msg"] == "转换成功"
            assert "resultId" in data["data"]
            assert "convertedContent" in data["data"]
            assert "confidence" in data["data"]
            assert "processingLogs" in data["data"]
        finally:
            TestFixtures.cleanup_file(test_file)

    def test_auto_convert_csv(self):
        """测试自动转换 CSV 文件"""
        test_file = TestFixtures.create_test_csv_file()
        try:
            with open(test_file, "rb") as f:
                response = client.post(
                    "/api/v1/convert/auto",
                    data={
                        "fileType": "auto",
                        "conversionType": "table",
                        "outputFormat": "markdown"
                    },
                    files={"file": ("auto_test.csv", f, "text/csv")}
                )

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 200
            assert data["data"]["conversionType"] == "table"
        finally:
            TestFixtures.cleanup_file(test_file)

    def test_auto_convert_with_custom_prompt(self):
        """测试带自定义提示词的自动转换"""
        test_file = TestFixtures.create_test_txt_file("Custom prompt test")
        try:
            with open(test_file, "rb") as f:
                response = client.post(
                    "/api/v1/convert/auto",
                    data={
                        "fileType": "auto",
                        "conversionType": "text",
                        "outputFormat": "json",
                        "customPrompt": "Summarize the content"
                    },
                    files={"file": ("custom_test.txt", f, "text/plain")}
                )

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 200
        finally:
            TestFixtures.cleanup_file(test_file)

    def test_auto_convert_no_file(self):
        """测试不上传文件的自动转换"""
        response = client.post(
            "/api/v1/convert/auto",
            data={"fileType": "auto"}
        )
        assert response.status_code == 422

    def test_auto_convert_unsupported_format(self):
        """测试不支持的文件格式"""
        fd, path = tempfile.mkstemp(suffix=".exe")
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write("test")
        test_file = Path(path)
        try:
            with open(test_file, "rb") as f:
                response = client.post(
                    "/api/v1/convert/auto",
                    data={"fileType": "auto"},
                    files={"file": ("test.exe", f, "application/octet-stream")}
                )

            assert response.status_code == 200
            data = response.json()
            assert data["code"] == 400
        finally:
            TestFixtures.cleanup_file(test_file)


# ==================== 错误处理测试 ====================

class TestErrorHandling:
    """测试错误处理"""

    def test_invalid_json_payload(self):
        """测试无效的 JSON 请求体"""
        response = client.post(
            "/api/v1/convert/run",
            data="invalid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422

    def test_missing_required_fields(self):
        """测试缺少必填字段"""
        response = client.post(
            "/api/v1/convert/run",
            json={"conversionType": "text"}  # 缺少 parseId 和 enc
        )
        assert response.status_code == 422

    def test_large_file_upload(self):
        """测试超大文件上传"""
        # 创建一个超过 50MB 的文件
        large_content = b"x" * (51 * 1024 * 1024)

        response = client.post(
            "/api/v1/convert/upload",
            data={"fileType": "txt"},
            files={"file": ("large.txt", large_content, "text/plain")}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["code"] == 400
        assert "大小" in data["msg"]


# ==================== 响应格式测试 ====================

class TestResponseFormat:
    """测试响应格式一致性"""

    def test_response_has_required_fields(self):
        """测试响应包含必要字段"""
        response = client.get("/health")
        data = response.json()

        assert "code" in data
        assert "msg" in data
        assert "data" in data
        assert "requestId" in data

    def test_error_response_format(self):
        """测试错误响应格式"""
        response = client.get("/api/v1/convert/status/nonexistent")
        data = response.json()

        assert "code" in data
        assert "msg" in data
        assert data["code"] == 404
        assert "requestId" in data

    def test_success_response_format(self):
        """测试成功响应格式"""
        response = client.get("/")
        data = response.json()

        assert "name" in data
        assert "version" in data


# ==================== CORS 测试 ====================

class TestCORS:
    """测试跨域配置"""

    def test_cors_headers(self):
        """测试 CORS 响应头"""
        response = client.options(
            "/api/v1/convert/upload",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST"
            }
        )
        assert response.status_code == 200
        assert "access-control-allow-origin" in response.headers


# ==================== 并发测试 ====================

class TestConcurrency:
    """测试并发处理"""

    def test_multiple_uploads(self):
        """测试多次上传不同内容"""
        parse_ids = []
        temp_files = []

        try:
            for i in range(3):
                # 使用不同内容以避免内容哈希缓存命中
                content = f"Concurrent test {i} - unique content {i}!"
                test_file = TestFixtures.create_test_txt_file(content)
                temp_files.append(test_file)

                with open(test_file, "rb") as f:
                    response = client.post(
                        "/api/v1/convert/upload",
                        data={"fileType": "txt"},
                        files={"file": (f"test_{i}.txt", f, "text/plain")}
                    )
                assert response.status_code == 200
                data = response.json()
                assert data["code"] == 200
                parse_ids.append(data["data"]["parseId"])

            assert len(parse_ids) == 3
            assert len(set(parse_ids)) == 3  # 不同内容应有不同的 parseId
        finally:
            for tf in temp_files:
                TestFixtures.cleanup_file(tf)

    def test_content_cache_same_content(self):
        """测试相同内容命中缓存"""
        content = "Deduplication test content!"
        test_file = TestFixtures.create_test_txt_file(content)
        parse_ids = []

        try:
            # 第一次上传 - 应执行完整转换
            with open(test_file, "rb") as f:
                response1 = client.post(
                    "/api/v1/convert/upload",
                    data={"fileType": "txt"},
                    files={"file": ("test.txt", f, "text/plain")}
                )
            assert response1.status_code == 200
            data1 = response1.json()
            assert data1["code"] == 200
            parse_ids.append(data1["data"]["parseId"])

            # 第二次上传相同内容 - 应命中缓存
            with open(test_file, "rb") as f:
                response2 = client.post(
                    "/api/v1/convert/upload",
                    data={"fileType": "txt"},
                    files={"file": ("test_copy.txt", f, "text/plain")}
                )
            assert response2.status_code == 200
            data2 = response2.json()
            assert data2["code"] == 200
            parse_ids.append(data2["data"]["parseId"])

            # 相同内容应返回缓存结果（相同 parseId）
            assert data1["data"]["parseId"] == data2["data"]["parseId"]
            assert len(set(parse_ids)) == 1  # 缓存去重生效
        finally:
            TestFixtures.cleanup_file(test_file)

    def test_cache_isolation(self):
        """测试缓存隔离性"""
        parsed1 = TestFixtures.create_parsed_file_in_cache("cache_iso_1")
        parsed2 = TestFixtures.create_parsed_file_in_cache("cache_iso_2")

        result1 = data_converter.convert(parsed1)
        result2 = data_converter.convert(parsed2)

        assert result1.resultId != result2.resultId
        assert result1.parseId != result2.parseId


class TestV2ReadAuthentication:
    """敏感 v2 读接口应与写接口使用相同的 API Key 认证。"""

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v2/history",
            "/api/v2/history/sensitive-result",
            "/api/v2/history/stats",
            "/api/v2/export/sensitive-result",
            "/api/v2/quality/sensitive-result",
            "/api/v2/webhook/status/sensitive-task",
            "/api/v2/webhook/stats",
        ],
    )
    def test_sensitive_get_requires_api_key(self, monkeypatch, path):
        monkeypatch.setattr(settings, "API_KEY", "test-api-key")

        response = client.get(path)

        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"

    def test_sensitive_get_rejects_incorrect_api_key(self, monkeypatch):
        monkeypatch.setattr(settings, "API_KEY", "test-api-key")

        response = client.get(
            "/api/v2/history",
            headers={"Authorization": "Bearer wrong-key"},
        )

        assert response.status_code == 403

    def test_sensitive_get_accepts_correct_api_key(self, monkeypatch):
        monkeypatch.setattr(settings, "API_KEY", "test-api-key")

        response = client.get(
            "/api/v2/history",
            headers={"Authorization": "Bearer test-api-key"},
        )

        assert response.status_code == 200
        assert response.json()["code"] == 200

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v2/health",
            "/api/v2/templates",
            "/api/v2/metrics",
        ],
    )
    def test_operational_gets_remain_public(self, monkeypatch, path):
        monkeypatch.setattr(settings, "API_KEY", "test-api-key")

        response = client.get(path)

        assert response.status_code == 200
