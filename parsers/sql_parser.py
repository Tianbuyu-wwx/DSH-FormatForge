"""
SQL 文件解析器
解析 SQL dump 文件，提取 CREATE TABLE / INSERT 语句及其他 SQL 语句
将表结构作为 table 元素，其他语句作为 text 元素
"""

import logging
import re
from pathlib import Path
from typing import Any

from core.models import ExtractedElement, PageContent
from parsers import BaseParser

logger = logging.getLogger("parsers.sql")


class SQLParser(BaseParser):
    """SQL 文件解析器"""

    @property
    def name(self) -> str:
        return "SQLParser"

    @property
    def description(self) -> str:
        return "解析 SQL dump 文件，提取表结构与数据语句"

    @property
    def supported_extensions(self) -> list[str]:
        return [".sql", ".SQL"]

    @property
    def supported_magic(self) -> list[bytes]:
        return []

    def parse(self, file_path: Path) -> list[PageContent]:
        file_path = Path(file_path)
        logger.info("开始解析 SQL 文件: %s", file_path)

        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            logger.debug("UTF-8 读取失败，尝试 GBK: %s", e)
            try:
                with open(file_path, encoding="gbk", errors="ignore") as f:
                    content = f.read()
            except Exception as e2:
                logger.error("无法读取 SQL 文件: %s", e2)
                raise ValueError(f"无法读取 SQL 文件: {e2}") from e

        # 分割 SQL 语句
        statements = self._split_statements(content)
        logger.debug("分割得到 %d 条语句", len(statements))

        elements = []
        elem_idx = 0
        raw_text_parts = []
        stats = {
            "create_table": 0,
            "create_index": 0,
            "create_view": 0,
            "insert": 0,
            "update": 0,
            "delete": 0,
            "other": 0,
        }

        for stmt in statements:
            stmt = stmt.strip()
            if not stmt:
                continue

            # 去除注释
            stmt_upper = self._strip_comments(stmt).strip().upper()

            try:
                if stmt_upper.startswith("CREATE TABLE"):
                    element = self._parse_create_table(stmt, elem_idx)
                    element.elementType = "table"
                    elements.append(element)
                    raw_text_parts.append(element.content)
                    stats["create_table"] += 1
                    elem_idx += 1

                elif stmt_upper.startswith("CREATE INDEX") or stmt_upper.startswith("CREATE UNIQUE INDEX"):
                    elements.append(
                        ExtractedElement(
                            elementId=f"elem_1_{elem_idx}",
                            elementType="text",
                            content=stmt,
                            metadata={"statement_type": "create_index"},
                        )
                    )
                    raw_text_parts.append(stmt)
                    stats["create_index"] += 1
                    elem_idx += 1

                elif stmt_upper.startswith("CREATE VIEW") or stmt_upper.startswith("CREATE OR REPLACE VIEW"):
                    elements.append(
                        ExtractedElement(
                            elementId=f"elem_1_{elem_idx}",
                            elementType="text",
                            content=stmt,
                            metadata={"statement_type": "create_view"},
                        )
                    )
                    raw_text_parts.append(stmt)
                    stats["create_view"] += 1
                    elem_idx += 1

                elif stmt_upper.startswith("INSERT"):
                    element = self._parse_insert(stmt, elem_idx)
                    elements.append(element)
                    raw_text_parts.append(element.content)
                    stats["insert"] += 1
                    elem_idx += 1

                elif stmt_upper.startswith("UPDATE"):
                    elements.append(
                        ExtractedElement(
                            elementId=f"elem_1_{elem_idx}",
                            elementType="text",
                            content=stmt,
                            metadata={"statement_type": "update"},
                        )
                    )
                    raw_text_parts.append(stmt)
                    stats["update"] += 1
                    elem_idx += 1

                elif stmt_upper.startswith("DELETE"):
                    elements.append(
                        ExtractedElement(
                            elementId=f"elem_1_{elem_idx}",
                            elementType="text",
                            content=stmt,
                            metadata={"statement_type": "delete"},
                        )
                    )
                    raw_text_parts.append(stmt)
                    stats["delete"] += 1
                    elem_idx += 1

                else:
                    elements.append(
                        ExtractedElement(
                            elementId=f"elem_1_{elem_idx}",
                            elementType="text",
                            content=stmt,
                            metadata={"statement_type": "other"},
                        )
                    )
                    raw_text_parts.append(stmt)
                    stats["other"] += 1
                    elem_idx += 1

            except Exception as e:
                logger.warning("解析 SQL 语句时出错: %s, 语句前100字符: %s", e, stmt[:100])
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_1_{elem_idx}",
                        elementType="text",
                        content=stmt,
                        metadata={"statement_type": "other", "parse_error": str(e)},
                    )
                )
                raw_text_parts.append(stmt)
                elem_idx += 1

        logger.info(
            "SQL 解析完成: CREATE TABLE=%d, INSERT=%d, UPDATE=%d, DELETE=%d, 其他=%d",
            stats["create_table"],
            stats["insert"],
            stats["update"],
            stats["delete"],
            stats["other"],
        )

        return [
            PageContent(
                pageNumber=1,
                elements=elements,
                rawText="\n".join(raw_text_parts),
                hasImage=False,
                hasTable=stats["create_table"] > 0,
            )
        ]

    def _split_statements(self, content: str) -> list[str]:
        """按分号分割 SQL 语句，保留多行语句"""
        # 简单的分号分割，注意处理字符串中的分号
        statements = []
        current = []
        in_single_quote = False
        in_double_quote = False
        in_backtick = False
        escape_next = False

        for ch in content:
            if escape_next:
                current.append(ch)
                escape_next = False
                continue

            if ch == "\\":
                current.append(ch)
                escape_next = True
                continue

            if ch == "'" and not in_double_quote and not in_backtick:
                in_single_quote = not in_single_quote
            elif ch == '"' and not in_single_quote and not in_backtick:
                in_double_quote = not in_double_quote
            elif ch == "`" and not in_single_quote and not in_double_quote:
                in_backtick = not in_backtick

            if ch == ";" and not in_single_quote and not in_double_quote and not in_backtick:
                stmt = "".join(current).strip() + ";"
                if stmt.strip() != ";":
                    statements.append(stmt)
                current = []
            else:
                current.append(ch)

        # 剩余部分
        remaining = "".join(current).strip()
        if remaining:
            statements.append(remaining)

        return statements

    def _strip_comments(self, stmt: str) -> str:
        """去除 SQL 注释（行注释 -- 和块注释 /* */)"""
        # 去除块注释
        stmt = re.sub(r"/\*.*?\*/", "", stmt, flags=re.DOTALL)
        # 去除行注释（-- 到行尾）
        lines = stmt.split("\n")
        stripped = []
        for line in lines:
            idx = line.find("--")
            if idx >= 0:
                # 确保不是在字符串内
                before = line[:idx]
                if before.count("'") % 2 == 0 and before.count('"') % 2 == 0:
                    line = before
            stripped.append(line)
        return "\n".join(stripped)

    def _parse_create_table(self, stmt: str, elem_idx: int) -> ExtractedElement:
        """解析 CREATE TABLE 语句，提取表名和列定义"""
        # 提取表名
        table_name = "unknown"
        match = re.search(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`([^`]+)`|(\"[^\"]+\")|'([^']+)'|(\w[\w.]*))",
            stmt,
            re.IGNORECASE,
        )
        if match:
            table_name = match.group(1) or match.group(2) or match.group(3) or match.group(4) or "unknown"
            table_name = table_name.strip("`\"'")

        # 提取列定义（括号内的内容）
        columns = []
        col_match = re.search(r"\((.*)\)\s*(?:ENGINE|;|$)", stmt, re.DOTALL | re.IGNORECASE)
        if col_match:
            col_text = col_match.group(1)
            # 按逗号分割列定义（注意嵌套括号）
            col_defs = self._split_columns(col_text)
            for col_def in col_defs:
                col_def = col_def.strip()
                if not col_def:
                    continue
                col_info = self._parse_column_def(col_def)
                if col_info:
                    columns.append(col_info)

        # 构建表格内容
        if columns:
            # 表头
            col_names = [c["name"] for c in columns]
            col_types = [c["type"] for c in columns]
            table_content = f"CREATE TABLE {table_name}\n" + " | ".join(col_names) + "\n" + " | ".join(col_types)
        else:
            table_content = f"CREATE TABLE {table_name}"

        return ExtractedElement(
            elementId=f"elem_1_{elem_idx}",
            elementType="table",
            content=table_content,
            metadata={
                "table_name": table_name,
                "columns": columns,
                "column_count": len(columns),
                "raw_sql": stmt,
            },
        )

    def _split_columns(self, col_text: str) -> list[str]:
        """按逗号分割列定义，处理嵌套括号"""
        cols = []
        depth = 0
        current: list[str] = []
        for ch in col_text:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                cols.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        remaining = "".join(current).strip()
        if remaining:
            cols.append(remaining)
        return cols

    def _parse_column_def(self, col_def: str) -> dict[str, Any] | None:
        """解析单个列定义"""
        col_def = col_def.strip()

        # 跳过约束定义 (PRIMARY KEY, FOREIGN KEY, CONSTRAINT, UNIQUE, CHECK, INDEX, KEY)
        constraint_patterns = [
            r"^(PRIMARY\s+KEY|FOREIGN\s+KEY|CONSTRAINT|UNIQUE\s+KEY|UNIQUE\s+INDEX|CHECK|INDEX|KEY|FULLTEXT)",
        ]
        for pat in constraint_patterns:
            if re.match(pat, col_def, re.IGNORECASE):
                return None

        # 提取列名和类型
        parts = col_def.split(None, 1)
        if not parts:
            return None

        col_name = parts[0].strip("`\"'")
        col_type = parts[1].strip() if len(parts) > 1 else ""

        # 截取类型（到第一个空格或逗号为止，但保留括号内的类型如 VARCHAR(255)）
        type_match = re.match(r"(\w[\w\s]*(?:\([^)]*\))?)", col_type)
        col_type_clean = type_match.group(1) if type_match else col_type

        # 检测约束
        is_primary = bool(re.search(r"PRIMARY\s+KEY", col_def, re.IGNORECASE))
        is_not_null = bool(re.search(r"NOT\s+NULL", col_def, re.IGNORECASE))
        is_unique = bool(re.search(r"UNIQUE", col_def, re.IGNORECASE))
        is_auto_inc = bool(re.search(r"AUTO_INCREMENT", col_def, re.IGNORECASE))

        # 默认值
        default_value = ""
        default_match = re.search(r"DEFAULT\s+('[^']*'|\"[^\"]*\"|\S+)", col_def, re.IGNORECASE)
        if default_match:
            default_value = default_match.group(1).strip("'\"")

        # 注释
        comment = ""
        comment_match = re.search(r"COMMENT\s+('[^']*'|\"[^\"]*\")", col_def, re.IGNORECASE)
        if comment_match:
            comment = comment_match.group(1).strip("'\"")

        return {
            "name": col_name,
            "type": col_type_clean,
            "is_primary_key": is_primary,
            "not_null": is_not_null,
            "is_unique": is_unique,
            "auto_increment": is_auto_inc,
            "default": default_value,
            "comment": comment,
        }

    def _parse_insert(self, stmt: str, elem_idx: int) -> ExtractedElement:
        """解析 INSERT 语句"""
        # 提取表名
        table_name = "unknown"
        match = re.search(
            r"INSERT\s+(?:INTO\s+)?(?:`([^`]+)`|(\"[^\"]+\")|'([^']+)'|(\w[\w.]*))",
            stmt,
            re.IGNORECASE,
        )
        if match:
            table_name = match.group(1) or match.group(2) or match.group(3) or match.group(4) or "unknown"
            table_name = table_name.strip("`\"'")

        # 计算插入的行数
        value_count = len(re.findall(r"\)\s*,\s*\(", stmt)) + 1

        return ExtractedElement(
            elementId=f"elem_1_{elem_idx}",
            elementType="text",
            content=f"INSERT INTO {table_name} ({value_count} row(s))",
            metadata={
                "statement_type": "insert",
                "table_name": table_name,
                "row_count": value_count,
                "raw_sql": stmt,
            },
        )
