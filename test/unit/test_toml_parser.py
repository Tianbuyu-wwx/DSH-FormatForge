"""
TOML 解析器单元测试
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.toml_parser import TOMLParser


class TestTOMLParserBasic:
    """基础测试"""

    def test_supported_extensions(self):
        parser = TOMLParser()
        assert ".toml" in parser.supported_extensions
        assert ".txt" not in parser.supported_extensions
        assert ".json" not in parser.supported_extensions

    def test_supported_magic_empty(self):
        parser = TOMLParser()
        assert parser.supported_magic == []

    def test_can_parse_toml(self):
        parser = TOMLParser()
        assert parser.can_parse(Path("/tmp/config.toml")) == 0.9

    def test_can_parse_non_toml(self):
        parser = TOMLParser()
        assert parser.can_parse(Path("/tmp/test.json")) == 0.0
        assert parser.can_parse(Path("/tmp/test.txt")) == 0.0


class TestTOMLParserRealFile:
    """真实文件解析测试"""

    @pytest.fixture
    def parser(self):
        return TOMLParser()

    def test_parse_simple_key_value(self, parser, tmp_path):
        """解析简单键值对"""
        toml_content = """title = "TOML示例"
version = 1
debug = false
port = 8080"""
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(toml_content, encoding="utf-8")

        result = parser.parse(toml_path)
        elements = result[0].elements

        kvs = [e for e in elements if e.elementType == "key_value"]
        assert len(kvs) == 4

        keys = {e.metadata["key"]: e.metadata["value"] for e in kvs}
        assert keys["title"] == "TOML示例"
        assert keys["version"] == 1
        assert keys["debug"] is False
        assert keys["port"] == 8080

    def test_parse_table(self, parser, tmp_path):
        """解析表"""
        toml_content = """[server]
host = "localhost"
port = 8080

[server.admin]
user = "admin"
password = "secret\""""
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(toml_content, encoding="utf-8")

        result = parser.parse(toml_path)
        elements = result[0].elements

        sections = [e for e in elements if e.elementType == "section"]
        assert len(sections) == 2

        section_paths = [s.metadata["path"] for s in sections]
        assert "server" in section_paths
        assert "server.admin" in section_paths

        kvs = [e for e in elements if e.elementType == "key_value"]
        keys = {e.metadata["key"]: e.metadata["value"] for e in kvs}
        assert keys["server.host"] == "localhost"
        assert keys["server.port"] == 8080
        assert keys["server.admin.user"] == "admin"

    def test_parse_array(self, parser, tmp_path):
        """解析数组"""
        toml_content = """ports = [8000, 8001, 8002]
tags = ["web", "api"]"""
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(toml_content, encoding="utf-8")

        result = parser.parse(toml_path)
        elements = result[0].elements

        kvs = [e for e in elements if e.elementType == "key_value"]
        assert len(kvs) == 2

    def test_parse_array_of_tables(self, parser, tmp_path):
        """解析表数组"""
        toml_content = """[[products]]
name = "产品A"
price = 100

[[products]]
name = "产品B"
price = 200"""
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(toml_content, encoding="utf-8")

        result = parser.parse(toml_path)
        elements = result[0].elements

        sections = [e for e in elements if e.elementType == "section"]
        assert len(sections) == 2

        kvs = [e for e in elements if e.elementType == "key_value"]
        # 2 products × 2 fields (name, price) = 4
        assert len(kvs) == 4
        values = [e.metadata["value"] for e in kvs if e.metadata["key"].endswith("name")]
        assert "产品A" in values
        assert "产品B" in values

    def test_parse_inline_table(self, parser, tmp_path):
        """解析内联表（内联表会被展开为嵌套键值对）"""
        toml_content = """point = {x = 1, y = 2}"""
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(toml_content, encoding="utf-8")

        result = parser.parse(toml_path)
        elements = result[0].elements

        # 内联表被展开为：point.x, point.y
        kvs = [e for e in elements if e.elementType == "key_value"]
        assert len(kvs) == 2
        keys = {e.metadata["key"] for e in kvs}
        assert "point.x" in keys
        assert "point.y" in keys

    def test_parse_nested_data_types(self, parser, tmp_path):
        """解析嵌套数据类型"""
        toml_content = """[database]
enabled = true
pool_size = 10
connection = "postgresql://localhost"

[database.timeout]
read = 30
write = 60"""
        toml_path = tmp_path / "config.toml"
        toml_path.write_text(toml_content, encoding="utf-8")

        result = parser.parse(toml_path)
        elements = result[0].elements
        assert len(elements) > 0

        # 验证层级关系
        sections = [e for e in elements if e.elementType == "section"]
        section_paths = [s.metadata["path"] for s in sections]
        assert "database" in section_paths
        assert "database.timeout" in section_paths

        # 验证值类型
        kvs = {e.metadata["key"]: e.metadata["value"] for e in elements if e.elementType == "key_value"}
        assert kvs["database.enabled"] is True
        assert kvs["database.pool_size"] == 10

    def test_parse_complex_toml(self, parser, tmp_path):
        """解析复杂 TOML 文件（接近真实 pyproject.toml 场景）"""
        toml_content = """[project]
name = "example"
version = "1.0.0"
requires-python = ">=3.11"

[project.urls]
homepage = "https://example.com"

[[tool.mypy.overrides]]
module = "tests"
ignore_missing_imports = true"""
        toml_path = tmp_path / "complex.toml"
        toml_path.write_text(toml_content, encoding="utf-8")

        result = parser.parse(toml_path)
        elements = result[0].elements
        assert len(elements) > 0

        section_paths = [s.metadata["path"] for s in elements if s.elementType == "section"]
        assert "project" in section_paths
        assert "project.urls" in section_paths
        assert "tool.mypy.overrides" in section_paths or any("overrides" in p for p in section_paths)

    def test_parse_empty_toml(self, parser, tmp_path):
        """解析空文件"""
        toml_path = tmp_path / "empty.toml"
        toml_path.write_text("", encoding="utf-8")

        # 空 TOML 文件是有效的
        result = parser.parse(toml_path)
        assert len(result) == 1

    def test_parse_comment_only(self, parser, tmp_path):
        """解析仅包含注释的文件"""
        toml_content = """# 这是一个注释
# 另一个注释
# 第三个注释"""
        toml_path = tmp_path / "comments.toml"
        toml_path.write_text(toml_content, encoding="utf-8")

        result = parser.parse(toml_path)
        elements = result[0].elements
        # 纯注释的 TOML 视为空有效文件
        assert len(elements) == 0

    def test_parse_mixed_types(self, parser, tmp_path):
        """解析混合类型值"""
        toml_content = """float_val = 3.14
bool_val = true
string_val = "hello"
int_val = 42
arr_val = [1, 2, 3]"""
        toml_path = tmp_path / "types.toml"
        toml_path.write_text(toml_content, encoding="utf-8")

        result = parser.parse(toml_path)
        kvs = {e.metadata["key"]: e.metadata["value"] for e in result[0].elements if e.elementType == "key_value"}
        assert kvs["float_val"] == 3.14
        assert kvs["bool_val"] is True
        assert kvs["string_val"] == "hello"
        assert kvs["int_val"] == 42
        assert kvs["arr_val"] == [1, 2, 3]