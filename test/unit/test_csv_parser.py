"""
CSV 解析器单元测试
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from parsers.csv_parser import CSVParser


class TestCSVParserBasic:
    """基础测试"""

    def test_supported_extensions(self):
        parser = CSVParser()
        assert ".csv" in parser.supported_extensions
        assert ".tsv" in parser.supported_extensions

    def test_can_parse_csv(self):
        parser = CSVParser()
        assert parser.can_parse(Path("/tmp/test.csv")) == 0.9

    def test_can_parse_tsv(self):
        parser = CSVParser()
        assert parser.can_parse(Path("/tmp/test.tsv")) == 0.9

    def test_can_parse_non_csv(self):
        parser = CSVParser()
        assert parser.can_parse(Path("/tmp/test.txt")) == 0.0


class TestCSVParserRealFile:
    """真实文件测试"""

    @pytest.fixture
    def parser(self):
        return CSVParser()

    def test_parse_simple_csv(self, parser, tmp_path):
        """测试简单 CSV"""
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("姓名,年龄,城市\n张三,25,北京\n李四,30,上海", encoding='utf-8')

        result = parser.parse(csv_path)

        assert len(result) == 1
        assert result[0].hasTable is True
        assert "张三" in result[0].rawText
        assert "李四" in result[0].rawText

    def test_parse_tsv(self, parser, tmp_path):
        """测试 TSV 文件"""
        tsv_path = tmp_path / "test.tsv"
        tsv_path.write_text("姓名\t年龄\t城市\n张三\t25\t北京", encoding='utf-8')

        result = parser.parse(tsv_path)

        assert len(result) == 1
        assert result[0].hasTable is True
        table_elem = next(e for e in result[0].elements if e.elementType == "table")
        assert table_elem.metadata["delimiter"] == "\t"

    def test_parse_csv_with_header(self, parser, tmp_path):
        """测试带表头的 CSV"""
        csv_path = tmp_path / "header.csv"
        csv_path.write_text("ID,Name,Price\n1,Apple,10.5\n2,Banana,5.0", encoding='utf-8')

        result = parser.parse(csv_path)

        table_elem = next(e for e in result[0].elements if e.elementType == "table")
        assert table_elem.metadata["has_header"] is True
        assert "ID" in table_elem.metadata["header"]

    def test_parse_csv_without_header(self, parser, tmp_path):
        """测试无表头的 CSV"""
        csv_path = tmp_path / "no_header.csv"
        csv_path.write_text("Apple,10.5\nBanana,5.0\nCherry,8.0", encoding='utf-8')

        result = parser.parse(csv_path)

        table_elem = next(e for e in result[0].elements if e.elementType == "table")
        # 纯数据行，没有明显表头特征
        assert table_elem.metadata["has_header"] is False

    def test_parse_empty_csv(self, parser, tmp_path):
        """测试空 CSV"""
        csv_path = tmp_path / "empty.csv"
        csv_path.write_text("", encoding='utf-8')

        result = parser.parse(csv_path)

        assert len(result) == 1
        assert result[0].hasTable is False

    def test_parse_csv_with_empty_lines(self, parser, tmp_path):
        """测试含空行的 CSV"""
        csv_path = tmp_path / "empty_lines.csv"
        csv_path.write_text("A,B\n\n1,2\n\n3,4", encoding='utf-8')

        result = parser.parse(csv_path)

        assert len(result) == 1
        table_elem = next(e for e in result[0].elements if e.elementType == "table")
        assert table_elem.metadata["rows"] == 3  # 不计算空行

    def test_parse_semicolon_csv(self, parser, tmp_path):
        """测试分号分隔的 CSV"""
        csv_path = tmp_path / "semicolon.csv"
        csv_path.write_text("姓名;年龄\n张三;25\n李四;30", encoding='utf-8')

        result = parser.parse(csv_path)

        table_elem = next(e for e in result[0].elements if e.elementType == "table")
        assert table_elem.metadata["delimiter"] == ";"


class TestCSVParserDelimiterDetection:
    """分隔符检测测试"""

    def test_detect_comma(self, tmp_path):
        parser = CSVParser()
        csv_path = tmp_path / "comma.csv"
        csv_path.write_text("a,b,c\n1,2,3", encoding='utf-8')

        delim = parser._detect_delimiter(csv_path)
        assert delim == ","

    def test_detect_tab(self, tmp_path):
        parser = CSVParser()
        tsv_path = tmp_path / "tab.tsv"
        tsv_path.write_text("a\tb\tc\n1\t2\t3", encoding='utf-8')

        delim = parser._detect_delimiter(tsv_path)
        assert delim == "\t"

    def test_detect_semicolon(self, tmp_path):
        parser = CSVParser()
        csv_path = tmp_path / "semi.csv"
        csv_path.write_text("a;b;c\n1;2;3", encoding='utf-8')

        delim = parser._detect_delimiter(csv_path)
        assert delim == ";"

    def test_detect_pipe(self, tmp_path):
        parser = CSVParser()
        csv_path = tmp_path / "pipe.csv"
        csv_path.write_text("a|b|c\n1|2|3", encoding='utf-8')

        delim = parser._detect_delimiter(csv_path)
        assert delim == "|"


class TestCSVParserHeaderDetection:
    """表头检测测试"""

    def test_detect_header_by_types(self):
        parser = CSVParser()
        rows = [
            ["ID", "Name", "Price"],
            ["1", "Apple", "10.5"],
            ["2", "Banana", "5.0"]
        ]
        assert parser._detect_header(rows) is True

    def test_detect_no_header_all_text(self):
        parser = CSVParser()
        rows = [
            ["Apple", "Red"],
            ["Banana", "Yellow"],
            ["Grape", "Purple"]
        ]
        assert parser._detect_header(rows) is False

    def test_detect_header_by_keywords(self):
        parser = CSVParser()
        rows = [
            ["序号", "名称", "价格"],
            ["1", "苹果", "10"],
        ]
        assert parser._detect_header(rows) is True

    def test_single_row_no_header(self):
        parser = CSVParser()
        rows = [["A", "B", "C"]]
        assert parser._detect_header(rows) is False


class TestCSVParserTypeGuessing:
    """类型猜测测试"""

    def test_guess_int(self):
        parser = CSVParser()
        assert parser._guess_type("123") == "int"

    def test_guess_float(self):
        parser = CSVParser()
        assert parser._guess_type("12.5") == "float"

    def test_guess_string(self):
        parser = CSVParser()
        assert parser._guess_type("hello") == "str"

    def test_guess_empty(self):
        parser = CSVParser()
        assert parser._guess_type("") == "empty"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
