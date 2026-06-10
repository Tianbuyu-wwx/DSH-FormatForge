"""
Data 解析器单元测试（JSON/YAML/XML）
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.data_parser import DataParser


class TestDataParserBasic:
    """基础测试"""

    def test_supported_extensions(self):
        parser = DataParser()
        assert ".json" in parser.supported_extensions
        assert ".yaml" in parser.supported_extensions
        assert ".xml" in parser.supported_extensions

    def test_can_parse_json(self):
        parser = DataParser()
        assert parser.can_parse(Path("/tmp/test.json")) == 0.9

    def test_can_parse_by_magic_json(self):
        parser = DataParser()
        assert parser.can_parse(Path("/tmp/test"), b'{"key": "value"}') == 0.95

    def test_can_parse_by_magic_xml(self):
        parser = DataParser()
        assert parser.can_parse(Path("/tmp/test"), b'<?xml version="1.0"?>') == 0.95


class TestDataParserJSON:
    """JSON 解析测试"""

    @pytest.fixture
    def parser(self):
        return DataParser()

    def test_parse_simple_json(self, parser, tmp_path):
        """测试简单 JSON 对象"""
        json_path = tmp_path / "test.json"
        json_path.write_text('{"name": "张三", "age": 25}', encoding='utf-8')

        result = parser.parse(json_path)

        assert len(result) == 1
        assert result[0].hasTable is False
        assert "张三" in result[0].rawText
        assert any(e.elementType == "text" and "name" in e.content for e in result[0].elements)

    def test_parse_json_array(self, parser, tmp_path):
        """测试 JSON 数组"""
        json_path = tmp_path / "array.json"
        json_path.write_text('[{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]', encoding='utf-8')

        result = parser.parse(json_path)

        assert result[0].hasTable is True
        table_rows = [e for e in result[0].elements if e.elementType == "table_row"]
        assert len(table_rows) == 2

    def test_parse_nested_json(self, parser, tmp_path):
        """测试嵌套 JSON"""
        json_path = tmp_path / "nested.json"
        json_path.write_text('{"user": {"name": "张三", "address": {"city": "北京"}}}', encoding='utf-8')

        result = parser.parse(json_path)

        assert len(result[0].elements) > 1
        assert "user" in result[0].rawText

    def test_parse_invalid_json(self, parser, tmp_path):
        """测试无效 JSON"""
        json_path = tmp_path / "invalid.json"
        json_path.write_text('{"name": "test",}', encoding='utf-8')

        with pytest.raises(ValueError):
            parser.parse(json_path)


class TestDataParserXML:
    """XML 解析测试"""

    @pytest.fixture
    def parser(self):
        return DataParser()

    def test_parse_simple_xml(self, parser, tmp_path):
        """测试简单 XML"""
        xml_path = tmp_path / "test.xml"
        xml_path.write_text('<?xml version="1.0"?><root><name>张三</name><age>25</age></root>', encoding='utf-8')

        result = parser.parse(xml_path)

        assert len(result) == 1
        assert "张三" in result[0].rawText
        assert any(e.elementType == "heading" for e in result[0].elements)

    def test_parse_xml_with_attribs(self, parser, tmp_path):
        """测试带属性的 XML"""
        xml_path = tmp_path / "attribs.xml"
        xml_path.write_text('<root><item id="1" type="book">内容</item></root>', encoding='utf-8')

        result = parser.parse(xml_path)

        heading_elems = [e for e in result[0].elements if e.elementType == "heading"]
        assert any("item" in e.content for e in heading_elems)

    def test_parse_invalid_xml(self, parser, tmp_path):
        """测试无效 XML"""
        xml_path = tmp_path / "invalid.xml"
        xml_path.write_text('<root><unclosed>', encoding='utf-8')

        with pytest.raises(ValueError):
            parser.parse(xml_path)


class TestDataParserYAML:
    """YAML 解析测试"""

    @pytest.fixture
    def parser(self):
        return DataParser()

    def test_parse_simple_yaml(self, parser, tmp_path):
        """测试简单 YAML"""
        with patch('parsers.data_parser.YAML_AVAILABLE', True), \
             patch('parsers.data_parser.yaml') as mock_yaml:
            mock_yaml.safe_load.return_value = {"name": "张三", "age": 25}
            mock_yaml.dump.return_value = "name: 张三\nage: 25"

            yaml_path = tmp_path / "test.yaml"
            yaml_path.write_text("name: 张三\nage: 25", encoding='utf-8')

            result = parser.parse(yaml_path)

            assert len(result) == 1
            assert "张三" in result[0].rawText

    def test_parse_yaml_without_lib(self, parser, tmp_path):
        """测试未安装 PyYAML"""
        with patch('parsers.data_parser.YAML_AVAILABLE', False):
            yaml_path = tmp_path / "test.yaml"
            yaml_path.write_text("name: test", encoding='utf-8')

            with pytest.raises(ImportError):
                parser.parse(yaml_path)


class TestDataParserAuto:
    """自动检测测试"""

    def test_auto_detect_json(self, tmp_path):
        parser = DataParser()
        path = tmp_path / "unknown"
        path.write_text('{"key": "value"}', encoding='utf-8')

        result = parser.parse(path)
        assert "value" in result[0].rawText


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
