"""
TOML 格式解析器
使用 Python 3.11+ 标准库 tomllib 解析 TOML 配置文件
提取键值对、表、数组为结构化元素
"""

import logging
from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:
    # Python < 3.11：回退到第三方 tomli（API 与 tomllib 兼容）
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None  # Python < 3.11 且未安装 tomli

from core.models import ExtractedElement, PageContent
from parsers import BaseParser

logger = logging.getLogger("parsers.toml")


class TOMLParser(BaseParser):
    """TOML 配置文件解析器"""

    @property
    def supported_extensions(self) -> list[str]:
        return [".toml"]

    @property
    def supported_magic(self) -> list[bytes]:
        return []

    def parse(self, file_path: Path) -> list[PageContent]:
        """解析 TOML 文件"""
        file_path = Path(file_path)

        if tomllib is None:
            raise ImportError("tomllib 不可用，需要 Python 3.11+")

        logger.info("开始解析 TOML: %s", file_path)

        try:
            with open(file_path, "rb") as f:
                data = tomllib.load(f)
        except Exception as e:
            logger.error("TOML 解析失败: %s", e)
            raise ValueError(f"TOML 解析失败: {e}") from e

        elements: list[ExtractedElement] = []
        raw_lines: list[str] = []
        elem_idx = [0]  # 用 list 包装作为引用传值

        # 解析顶级键值对和表
        self._flatten_toml(data, elements, raw_lines, elem_idx)

        logger.info("TOML 解析完成: %d 个元素", len(elements))

        return [
            PageContent(
                pageNumber=1,
                elements=elements,
                rawText="\n".join(raw_lines),
                hasImage=False,
                hasTable=False,
            )
        ]

    def _flatten_toml(
        self,
        data: dict,
        elements: list,
        raw_lines: list,
        elem_idx: list,
        prefix: str = "",
    ) -> None:
        """
        递归展开 TOML 数据为扁平元素列表

        Args:
            data: TOML 解析后的字典
            elements: 元素列表
            raw_lines: 原始文本行列表
            elem_idx: 当前索引（由外层传入，通过 list[int] 模拟引用传递）
            prefix: 当前前缀路径（用于嵌套表）
        """
        # 先收集所有普通键值对
        simple_pairs: dict[str, Any] = {}
        tables: dict[str, dict] = {}
        arrays_of_tables: dict[str, list[dict]] = {}

        for key, value in data.items():
            if isinstance(value, dict):
                tables[key] = value
            elif isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
                arrays_of_tables[key] = value
            else:
                simple_pairs[key] = value

        # 1. 输出普通键值对
        if simple_pairs:
            full_key = f"{prefix}." if prefix else ""
            for k, v in simple_pairs.items():
                display_value = self._format_value(v)
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_1_{elem_idx[0]}",
                        elementType="key_value",
                        content=f"{k}: {display_value}",
                        metadata={
                            "key": f"{full_key}{k}",
                            "value": v,
                            "type": type(v).__name__
                            if not isinstance(v, (list, dict))
                            else ("array" if isinstance(v, list) else "table"),
                        },
                    )
                )
                raw_lines.append(f"{k} = {display_value}")
                elem_idx[0] += 1

        # 2. 输出表
        for table_name, table_data in tables.items():
            full_path = f"{prefix}.{table_name}" if prefix else table_name
            elements.append(
                ExtractedElement(
                    elementId=f"elem_1_{elem_idx[0]}",
                    elementType="section",
                    content=table_name,
                    metadata={"path": full_path, "type": "table"},
                )
            )
            raw_lines.append(f"\n[{full_path}]")
            elem_idx[0] += 1

            self._flatten_toml(table_data, elements, raw_lines, elem_idx, full_path)

        # 3. 输出表数组
        for arr_name, arr_data in arrays_of_tables.items():
            full_path = f"{prefix}.{arr_name}" if prefix else arr_name
            for idx, item in enumerate(arr_data):
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_1_{elem_idx[0]}",
                        elementType="section",
                        content=f"{arr_name}[{idx}]",
                        metadata={"path": f"{full_path}[{idx}]", "type": "array_of_tables", "index": idx},
                    )
                )
                raw_lines.append(f"\n[[{full_path}]]")
                elem_idx[0] += 1

                self._flatten_toml(item, elements, raw_lines, elem_idx, full_path)

    def _format_value(self, value: Any) -> str:
        """格式化 TOML 值为可读字符串"""
        if isinstance(value, bool):
            return "true" if value else "false"
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            return value
        elif isinstance(value, (list, tuple)):
            items = [self._format_value(v) for v in value]
            if len(items) <= 5:
                return f"[{', '.join(items)}]"
            return f"[{', '.join(items[:5])}, ... ({len(items)} items)]"
        elif isinstance(value, dict):
            return f"{{...}} ({len(value)} keys)"
        else:
            return str(value)
