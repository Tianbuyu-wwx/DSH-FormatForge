"""
Markdown 文件解析器
独立解析器，提供精细的结构化提取，比嵌入在 richtext_parser 中的 Markdown 解析更全面
支持：标题/代码块/列表/表格/引用/图片/链接/前言/脚注/任务列表
"""
import logging
import re
from pathlib import Path
from typing import List, Optional

from core.models import ExtractedElement, PageContent
from parsers import BaseParser

logger = logging.getLogger("parsers.markdown")


class MarkdownParser(BaseParser):
    """Markdown 文件解析器"""

    @property
    def supported_extensions(self) -> list[str]:
        return [".md", ".markdown"]

    @property
    def supported_magic(self) -> list[bytes]:
        # Markdown 无固定魔数，通过扩展名识别
        return []

    def parse(self, file_path: Path) -> list[PageContent]:
        """解析 Markdown 文件"""
        file_path = Path(file_path)
        logger.info("开始解析 Markdown: %s", file_path)

        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            logger.error("无法读取 Markdown 文件: %s", e)
            raise ValueError(f"无法读取 Markdown 文件: {e}")

        elements = []
        raw_lines: list[str] = []
        elem_idx = 0
        line_offset = 0

        # 步骤1：提取 YAML 前言
        content, front_matter = self._extract_front_matter(content)
        if front_matter is not None:
            elements.append(ExtractedElement(
                elementId=f"elem_1_{elem_idx}",
                elementType="front_matter",
                content=front_matter,
                metadata={"type": "yaml"}
            ))
            raw_lines.append(f"[Front Matter]\n{front_matter}")
            elem_idx += 1

        # 步骤2：按行解析
        lines = content.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            current_line = line_offset + i

            if not stripped:
                i += 1
                continue

            # --- 标题 ---
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading_match:
                level = len(heading_match.group(1))
                text = heading_match.group(2)
                # 去掉尾部多余的 # (如 `# Title ##`)
                text = re.sub(r"\s+#+\s*$", "", text).strip()
                elements.append(ExtractedElement(
                    elementId=f"elem_1_{elem_idx}",
                    elementType="heading",
                    content=text,
                    metadata={
                        "level": level,
                        "line": current_line,
                        "raw": stripped,
                    }
                ))
                raw_lines.append(text)
                elem_idx += 1
                i += 1
                continue

            # --- 代码块 ---
            if stripped.startswith("```") or stripped.startswith("~~~"):
                fence = stripped[:3]
                lang = stripped[len(fence):].strip()
                code_lines: list[str] = []
                start_line = current_line
                i += 1
                while i < len(lines) and not lines[i].strip().startswith(fence):
                    code_lines.append(lines[i])
                    i += 1
                i += 1  # 跳过结束标记

                code_content = "\n".join(code_lines).rstrip("\n")
                elements.append(ExtractedElement(
                    elementId=f"elem_1_{elem_idx}",
                    elementType="code",
                    content=code_content,
                    metadata={
                        "language": lang,
                        "line_start": start_line,
                        "line_end": start_line + len(code_lines),
                        "raw": f"{fence}{lang}\n{code_content}\n{fence}",
                    }
                ))
                raw_lines.append(code_content if not lang else f"[{lang} code] {code_content[:100]}")
                elem_idx += 1
                continue

            # --- 引用块 ---
            if stripped.startswith(">"):
                quote_lines: list[str] = []
                start_line = current_line
                while i < len(lines) and lines[i].strip().startswith(">"):
                    q_line = lines[i].strip()
                    # 处理 > 嵌套和 > 后的空格
                    q_text = re.sub(r"^>\s*", "", q_line)
                    quote_lines.append(q_text)
                    i += 1

                quote_text = "\n".join(quote_lines)
                elements.append(ExtractedElement(
                    elementId=f"elem_1_{elem_idx}",
                    elementType="quote",
                    content=quote_text,
                    metadata={
                        "line_start": start_line,
                        "line_end": start_line + len(quote_lines),
                    }
                ))
                raw_lines.append(quote_text)
                elem_idx += 1
                continue

            # --- 分割线 ---
            if re.match(r"^(-{3,}|\*{3,}|_{3,})\s*$", stripped):
                elements.append(ExtractedElement(
                    elementId=f"elem_1_{elem_idx}",
                    elementType="divider",
                    content="---",
                    metadata={"line": current_line}
                ))
                raw_lines.append("")
                elem_idx += 1
                i += 1
                continue

            # --- 任务列表 ---
            task_match = re.match(r"^\s*[-*+]\s+\[([ xX])\]\s+(.+)$", stripped)
            if task_match:
                checked = task_match.group(1).lower() == "x"
                task_text = task_match.group(2)
                elements.append(ExtractedElement(
                    elementId=f"elem_1_{elem_idx}",
                    elementType="task",
                    content=task_text,
                    metadata={
                        "checked": checked,
                        "line": current_line,
                    }
                ))
                raw_lines.append(f"[{'x' if checked else ' '}] {task_text}")
                elem_idx += 1
                i += 1
                continue

            # --- 无序列表 ---
            ul_match = re.match(r"^(\s*)[-*+]\s+(.+)$", stripped)
            if ul_match:
                indent = ul_match.group(1)
                items: list[dict] = []
                start_line = current_line
                while i < len(lines):
                    li_match = re.match(r"^(\s*)[-*+]\s+(.+)$", lines[i].strip())
                    if not li_match:
                        break
                    # 检查缩进层级（嵌套列表支持）
                    item_indent = li_match.group(1)
                    item_text = li_match.group(2)
                    items.append({
                        "text": item_text,
                        "indent": len(item_indent),
                        "line": current_line + len(items),
                    })
                    i += 1

                list_text = "\n".join(it["text"] for it in items)
                elements.append(ExtractedElement(
                    elementId=f"elem_1_{elem_idx}",
                    elementType="list",
                    content=list_text,
                    metadata={
                        "ordered": False,
                        "items": items,
                        "depth": len(indent),
                        "line_start": start_line,
                    }
                ))
                raw_lines.append(list_text)
                elem_idx += 1
                continue

            # --- 有序列表 ---
            ol_match = re.match(r"^\s*(\d+)\.\s+(.+)$", stripped)
            if ol_match:
                items: list[dict] = []
                start_line = current_line
                while i < len(lines):
                    li_match = re.match(r"^\s*(\d+)\.\s+(.+)$", lines[i].strip())
                    if not li_match:
                        break
                    num = int(li_match.group(1))
                    item_text = li_match.group(2)
                    items.append({
                        "text": item_text,
                        "number": num,
                        "line": current_line + len(items),
                    })
                    i += 1

                list_text = "\n".join(it["text"] for it in items)
                elements.append(ExtractedElement(
                    elementId=f"elem_1_{elem_idx}",
                    elementType="list",
                    content=list_text,
                    metadata={
                        "ordered": True,
                        "items": items,
                        "line_start": start_line,
                    }
                ))
                raw_lines.append(list_text)
                elem_idx += 1
                continue

            # --- 表格 ---
            if "|" in stripped and re.match(r"^\s*\|", stripped):
                table_lines: list[str] = []
                start_line = current_line
                while i < len(lines) and "|" in lines[i] and re.match(r"^\s*\|", lines[i].strip()):
                    table_lines.append(lines[i].strip())
                    i += 1

                # 解析表格数据
                header: list[str] = []
                rows: list[list[str]] = []
                body_start = 0

                if len(table_lines) >= 2:
                    header = self._parse_table_row(table_lines[0])
                    body_start = 2  # 跳过分隔行
                if len(table_lines) > body_start:
                    for row_line in table_lines[body_start:]:
                        row = self._parse_table_row(row_line)
                        if row:
                            rows.append(row)

                table_text = "\n".join(table_lines)
                elements.append(ExtractedElement(
                    elementId=f"elem_1_{elem_idx}",
                    elementType="table",
                    content=table_text,
                    metadata={
                        "header": header,
                        "rows": rows,
                        "row_count": len(rows),
                        "col_count": len(header),
                        "line_start": start_line,
                        "raw": table_text,
                    }
                ))
                raw_lines.append(table_text)
                elem_idx += 1
                continue

            # --- 图片 ---
            img_match = re.match(r"^!\[(.*?)\]\((.*?)(?:\s+\"(.*?)\")?\)\s*$", stripped)
            if img_match:
                alt_text = img_match.group(1) or ""
                img_url = img_match.group(2)
                img_title = img_match.group(3)
                elements.append(ExtractedElement(
                    elementId=f"elem_1_{elem_idx}",
                    elementType="image",
                    content=alt_text or "[图片]",
                    metadata={
                        "alt": alt_text,
                        "url": img_url,
                        "title": img_title or "",
                        "line": current_line,
                    }
                ))
                raw_lines.append(f"[图片] {alt_text} ({img_url})")
                elem_idx += 1
                i += 1
                continue

            # --- 脚注 ---
            fn_match = re.match(r"^\[\^(.+?)\]:\s+(.+)$", stripped)
            if fn_match:
                fn_name = fn_match.group(1)
                fn_text = fn_match.group(2)
                elements.append(ExtractedElement(
                    elementId=f"elem_1_{elem_idx}",
                    elementType="footnote",
                    content=fn_text,
                    metadata={
                        "name": fn_name,
                        "line": current_line,
                    }
                ))
                raw_lines.append(fn_text)
                elem_idx += 1
                i += 1
                continue

            # --- 链接引用定义（必须位于脚注之后，避免抢匹配 [^name]: ）---
            def_match = re.match(r"^\[(.+?)\]:\s*(\S+)(?:\s+\"(.*)\")?$", stripped)
            if def_match:
                ref_name = def_match.group(1)
                ref_url = def_match.group(2)
                ref_title = def_match.group(3) or ""
                elements.append(ExtractedElement(
                    elementId=f"elem_1_{elem_idx}",
                    elementType="reference",
                    content=f"{ref_name}: {ref_url}",
                    metadata={
                        "name": ref_name,
                        "url": ref_url,
                        "title": ref_title,
                        "line": current_line,
                    }
                ))
                raw_lines.append(ref_url)
                elem_idx += 1
                i += 1
                continue

            # --- 普通段落（含行内格式）---
            para_lines: list[str] = []
            para_start = current_line
            while i < len(lines):
                ln = lines[i].strip()
                if not ln:
                    break
                if self._is_block_element(ln):
                    break
                para_lines.append(lines[i].rstrip())
                i += 1

            if para_lines:
                para_text = " ".join(ln.strip() for ln in para_lines)
                # 提取行内元素信息
                inline_meta = self._extract_inline_formatting(para_text)
                clean_text = inline_meta["text"]

                elements.append(ExtractedElement(
                    elementId=f"elem_1_{elem_idx}",
                    elementType="text",
                    content=clean_text,
                    metadata={
                        "line_start": para_start,
                        "inline": inline_meta.get("tokens"),
                    }
                ))
                raw_lines.append(clean_text)
                elem_idx += 1

        logger.info("Markdown 解析完成: %d 个元素", len(elements))

        return [PageContent(
            pageNumber=1,
            elements=elements,
            rawText="\n".join(raw_lines),
            hasImage=any(e.elementType == "image" for e in elements),
            hasTable=any(e.elementType == "table" for e in elements),
        )]

    def _extract_front_matter(self, content: str) -> tuple[str, Optional[str]]:
        """提取 YAML 前言（--- ... --- 之间的内容）"""
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if fm_match:
            front_matter = fm_match.group(1).strip()
            remaining = content[fm_match.end():]
            return remaining, front_matter
        return content, None

    def _parse_table_row(self, line: str) -> list[str]:
        """解析表格行"""
        # 移除首尾 |
        line = line.strip()
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]
        # 按 | 分割并清理每个单元格
        cells = [cell.strip() for cell in line.split("|")]
        # 过滤分隔行（纯 -: 的行）
        if all(re.match(r"^[\s\-:|]+$", cell) for cell in cells if cell):
            return []
        return cells

    def _extract_inline_formatting(self, text: str) -> dict:
        """提取行内格式信息，返回净化后的文本和格式令牌"""
        tokens: list[dict] = []

        # 图片 ![alt](url)
        def replace_img(m: re.Match) -> str:
            tokens.append({"type": "image", "alt": m.group(1), "url": m.group(2)})
            return m.group(1) or "[图片]"

        text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", replace_img, text)

        # 链接 [text](url)
        def replace_link(m: re.Match) -> str:
            tokens.append({"type": "link", "text": m.group(1), "url": m.group(2)})
            return m.group(1)

        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace_link, text)

        # 行内代码 `code`
        def replace_code(m: re.Match) -> str:
            tokens.append({"type": "code", "content": m.group(1)})
            return m.group(1)

        text = re.sub(r"`([^`]+)`", replace_code, text)

        # 粗体 **text** 或 __text__
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"__(.*?)__", r"\1", text)

        # 斜体 *text* 或 _text_ (非贪婪，避免与粗体冲突)
        text = re.sub(r"(?<!\*)\*(?!\*)(.*?)(?<!\*)\*(?!\*)", r"\1", text)
        text = re.sub(r"(?<!_)_(?!_)(.*?)(?<!_)_(?!_)", r"\1", text)

        # 删除线 ~~text~~
        text = re.sub(r"~~(.*?)~~", r"\1", text)

        # 脚注引用 [^name]
        text = re.sub(r"\[\^([^\]]+)\]", r"\1", text)

        return {"text": text.strip(), "tokens": tokens or None}

    def _is_block_element(self, line: str) -> bool:
        """判断某行是否为块级元素开始"""
        stripped = line.strip()
        if not stripped:
            return False
        return bool(
            re.match(r"^#{1,6}\s+", stripped)
            or stripped.startswith(("```", "~~~"))
            or stripped.startswith(">")
            or re.match(r"^(-{3,}|\*{3,}|_{3,})\s*$", stripped)
            or re.match(r"^\s*[-*+]\s+\[[ xX]\]\s+", stripped)
            or re.match(r"^\s*[-*+]\s+", stripped)
            or re.match(r"^\s*\d+\.\s+", stripped)
            or (stripped.startswith("|") and "|" in stripped[1:])
            or re.match(r"^!\[.*?\]\(.*?\)\s*$", stripped)
            or re.match(r"^\[.+?\]:\s*\S+", stripped)
            or re.match(r"^\[\^.+?\]:\s+", stripped)
        )