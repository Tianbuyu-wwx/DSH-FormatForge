"""
CSV 文件解析器
支持解析 CSV/TSV 文件，具备分隔符自动检测与表头识别能力
"""
import csv
import logging
from pathlib import Path
from typing import List, Optional

from parsers import BaseParser
from core.models import PageContent, ExtractedElement

logger = logging.getLogger("parsers.csv")


class CSVParser(BaseParser):
    """CSV/TSV 表格解析器"""

    # 常见分隔符候选
    DELIMITERS = [',', '\t', ';', '|', ':']

    @property
    def supported_extensions(self) -> List[str]:
        return [".csv", ".tsv", ".tab"]

    @property
    def supported_magic(self) -> List[bytes]:
        # CSV 无固定魔数，通过扩展名识别
        return []

    def parse(self, file_path: Path) -> List[PageContent]:
        """解析 CSV 文件"""
        file_path = Path(file_path)
        logger.info("开始解析 CSV: %s", file_path)

        # 自动检测分隔符
        delimiter = self._detect_delimiter(file_path)
        logger.debug("检测到分隔符: '%s'", delimiter)

        # 检测编码
        encoding = self._detect_encoding(file_path)

        elements = []
        raw_lines = []
        row_idx = 0
        all_rows = []

        try:
            with open(file_path, 'r', encoding=encoding, errors='ignore', newline='') as f:
                reader = csv.reader(f, delimiter=delimiter)
                for row in reader:
                    # 过滤空行
                    if not any(cell.strip() for cell in row):
                        continue
                    all_rows.append(row)
                    row_text = delimiter.join(cell.strip() for cell in row)
                    raw_lines.append(row_text)
                    elements.append(ExtractedElement(
                        elementId=f"elem_1_{row_idx}",
                        elementType="table_row",
                        content=row_text,
                        metadata={
                            "row_index": row_idx,
                            "cols": len(row)
                        }
                    ))
                    row_idx += 1
        except Exception as e:
            logger.error("CSV 解析失败: %s", e)
            raise ValueError(f"CSV 解析失败: {e}")

        # 表头检测
        has_header = self._detect_header(all_rows)
        header_text = delimiter.join(all_rows[0]) if all_rows else ""

        # 将整表作为一个 table 元素
        table_text = "\n".join(raw_lines)
        table_element = ExtractedElement(
            elementId="elem_1_table",
            elementType="table",
            content=table_text,
            metadata={
                "rows": len(all_rows),
                "cols": len(all_rows[0]) if all_rows else 0,
                "delimiter": delimiter,
                "header": header_text,
                "has_header": has_header
            }
        )

        logger.info("CSV 解析完成: %d 行, %d 列, 分隔符='%s', 有表头=%s",
                    len(all_rows), len(all_rows[0]) if all_rows else 0, delimiter, has_header)

        return [PageContent(
            pageNumber=1,
            elements=[table_element] + elements,
            rawText=table_text,
            hasImage=False,
            hasTable=len(all_rows) > 0
        )]

    def _detect_delimiter(self, file_path: Path) -> str:
        """
        自动检测 CSV 分隔符

        策略：
        1. 根据扩展名判断（.tsv/.tab -> \t）
        2. 读取样本行，统计各分隔符出现的次数一致性
        3. 回退到逗号
        """
        ext = file_path.suffix.lower()
        if ext in ['.tsv', '.tab']:
            return '\t'

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                sample_lines = []
                for _ in range(10):
                    line = f.readline()
                    if not line:
                        break
                    sample_lines.append(line.strip())
        except Exception:
            return ','

        if not sample_lines:
            return ','

        # 统计每个分隔符在每行出现的次数一致性
        best_delimiter = ','
        best_score = 0

        for delim in self.DELIMITERS:
            counts = [line.count(delim) for line in sample_lines]
            # 过滤没有该分隔符的行
            non_zero = [c for c in counts if c > 0]
            if not non_zero:
                continue

            # 一致性评分：出现次数相同的行越多，分数越高
            from collections import Counter
            freq = Counter(non_zero)
            most_common_count, most_common_freq = freq.most_common(1)[0]
            score = most_common_freq * most_common_count

            if score > best_score:
                best_score = score
                best_delimiter = delim

        return best_delimiter

    def _detect_encoding(self, file_path: Path) -> str:
        """检测文件编码"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                f.read(1024)
            return 'utf-8'
        except UnicodeDecodeError:
            return 'gbk'

    def _detect_header(self, rows: List[List[str]]) -> bool:
        """
        检测第一行是否为表头

        策略：
        1. 如果只有一行，认为无表头
        2. 比较第一行和第二行的数据类型差异
        3. 检查第一行是否包含常见表头关键词
        """
        if len(rows) < 2:
            return False

        first_row = rows[0]
        second_row = rows[1]

        # 类型差异检测
        first_types = [self._guess_type(cell) for cell in first_row]
        second_types = [self._guess_type(cell) for cell in second_row]

        # 如果第一行全是文本，第二行有数字，可能是表头
        if all(t == 'str' for t in first_types) and any(t in ('int', 'float') for t in second_types):
            return True

        # 关键词检测
        header_keywords = [
            'id', 'name', 'title', 'date', 'time', 'total', 'sum', 'price', 'amount',
            '编号', '名称', '标题', '日期', '时间', '合计', '总计', '价格', '数量',
            '序号', '编号', '项目', '内容', '备注', '状态', '类型', '类别'
        ]
        first_text = ' '.join(first_row).lower()
        if any(kw in first_text for kw in header_keywords):
            return True

        return False

    def _guess_type(self, value: str) -> str:
        """猜测单元格数据类型"""
        value = value.strip()
        if not value:
            return 'empty'
        try:
            int(value)
            return 'int'
        except ValueError:
            pass
        try:
            float(value)
            return 'float'
        except ValueError:
            pass
        return 'str'
