"""
LaTeX 文件解析器
提取 LaTeX 文档中的文本内容，处理章节标题、数学公式、注释等
使用简单的正则表达式方法，不依赖完整 LaTeX 引擎
"""

import logging
import re
from pathlib import Path

from core.models import ExtractedElement, PageContent
from parsers import BaseParser

logger = logging.getLogger("parsers.latex")


class LaTeXParser(BaseParser):
    """LaTeX 文档解析器"""

    @property
    def name(self) -> str:
        return "LaTeXParser"

    @property
    def description(self) -> str:
        return "解析 LaTeX 文档，提取文本内容与章节结构"

    @property
    def supported_extensions(self) -> list[str]:
        return [".tex", ".latex", ".ltx", ".TEX", ".LATEX", ".LTX"]

    @property
    def supported_magic(self) -> list[bytes]:
        return []

    def parse(self, file_path: Path) -> list[PageContent]:
        file_path = Path(file_path)
        logger.info("开始解析 LaTeX 文件: %s", file_path)

        try:
            with open(file_path, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            logger.error("无法读取 LaTeX 文件: %s", e)
            raise ValueError(f"无法读取 LaTeX 文件: {e}") from e

        # 步骤1: 去除注释（以 % 开头的行内注释）
        content = self._strip_comments(content)

        # 步骤2: 合并行（去除非必要的空白）
        content = self._normalize_whitespace(content)

        # 步骤3: 按 \\section, \\chapter 等分割
        elements = self._extract_sections(content)

        raw_text = "\n\n".join(e.content for e in elements)

        logger.info("LaTeX 解析完成: %d 个段落/章节", len(elements))

        return [
            PageContent(
                pageNumber=1,
                elements=elements,
                rawText=raw_text,
                hasImage=False,
                hasTable=False,
            )
        ]

    def _strip_comments(self, content: str) -> str:
        """去除 LaTeX 注释（以 % 开头，到行尾）"""
        # 保护 \%（转义的百分号）不被当作注释
        content = content.replace("\\%", "\x00ESCPCT\x00")
        lines = content.split("\n")
        stripped = []
        for line in lines:
            # 找到第一个非转义的 %
            idx = line.find("%")
            if idx >= 0:
                line = line[:idx]
            stripped.append(line)
        result = "\n".join(stripped)
        result = result.replace("\x00ESCPCT\x00", "\\%")
        return result

    def _normalize_whitespace(self, content: str) -> str:
        """规范化空白，合并多余空行"""
        # 将多个空行压缩为单个空行
        content = re.sub(r"\n{3,}", "\n\n", content)
        return content.strip()

    def _extract_sections(self, content: str) -> list[ExtractedElement]:
        """提取章节结构和文本内容"""
        elements = []
        elem_idx = 0

        # 分割正则：匹配所有章节命令
        section_pattern = r"\\(chapter|section|subsection|subsubsection|paragraph|subparagraph)(\*?)\{([^}]*)\}"
        parts = re.split(section_pattern, content)

        # parts 格式: [前导文本, cmd, star, title, 后续文本, cmd, star, title, ...]
        # 处理前导文本
        if parts and parts[0] is not None:
            preamble = parts[0].strip()
            if preamble:
                clean = self._strip_latex_commands(preamble)
                if clean:
                    elements.append(
                        ExtractedElement(
                            elementId=f"elem_1_{elem_idx}",
                            elementType="text",
                            content=clean,
                            metadata={"section": "preamble"},
                        )
                    )
                    elem_idx += 1

        # 处理章节-正文对
        i = 1
        while i + 3 <= len(parts):
            cmd = parts[i]
            star = parts[i + 1] if i + 1 < len(parts) else ""
            title = parts[i + 2] if i + 2 < len(parts) else ""
            body = parts[i + 3] if i + 3 < len(parts) else ""

            # 章节标题元素
            level_map = {
                "chapter": 0,
                "section": 1,
                "subsection": 2,
                "subsubsection": 3,
                "paragraph": 4,
                "subparagraph": 5,
            }
            level = level_map.get(cmd, 2)

            if title:
                elements.append(
                    ExtractedElement(
                        elementId=f"elem_1_{elem_idx}",
                        elementType="heading",
                        content=title,
                        metadata={
                            "level": level,
                            "command": f"\\{cmd}{star}",
                        },
                    )
                )
                elem_idx += 1

            # 正文内容
            if body is not None:
                body = body.strip()
                if body:
                    # 去除 LaTeX 命令
                    clean = self._strip_latex_commands(body)
                    if clean:
                        # 将 clean 文本按段落分割
                        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", clean) if p.strip()]
                        for para in paragraphs:
                            elements.append(
                                ExtractedElement(
                                    elementId=f"elem_1_{elem_idx}",
                                    elementType="text",
                                    content=para,
                                    metadata={"section": title},
                                )
                            )
                            elem_idx += 1

            i += 4

        return elements

    def _strip_latex_commands(self, text: str) -> str:
        """去除 LaTeX 命令，保留纯文本"""

        # 去除 display math: \[ ... \] 和 $$ ... $$
        text = re.sub(r"\\\[.*?\\\]", "[公式]", text, flags=re.DOTALL)
        text = re.sub(r"\$\$.*?\$\$", "[公式]", text, flags=re.DOTALL)

        # 去除 inline math: $...$
        text = re.sub(r"\$([^$]+?)\$", r"\1", text)

        # 去除 LaTeX 环境: \begin{...} ... \end{...}
        # 对于某些环境保留标签，去掉内容
        # equation/align/array/tabular -> [公式]
        text = re.sub(
            r"\\begin\{(equation\*?|align\*?|eqnarray\*?|array|displaymath|math)\}.*?\\end\{\1\}",
            "[公式]",
            text,
            flags=re.DOTALL,
        )
        # verbatim/lstlisting -> [代码]
        text = re.sub(
            r"\\begin\{(verbatim\*?|lstlisting|minted)\}.*?\\end\{\1\}",
            "[代码]",
            text,
            flags=re.DOTALL,
        )
        # 其他环境：只去掉环境标签，保留内容
        text = re.sub(r"\\begin\{[^}]+\}", "", text)
        text = re.sub(r"\\end\{[^}]+\}", "", text)

        # 去除引用命令: \cite{...}, \ref{...}, \label{...}
        text = re.sub(r"\\cite\s*\{[^}]*\}", "[引用]", text)
        text = re.sub(r"\\ref\s*\{[^}]*\}", "[引用]", text)
        text = re.sub(r"\\label\s*\{[^}]*\}", "", text)
        text = re.sub(r"\\footnote\s*\{([^}]*)\}", r"[\1]", text)
        text = re.sub(r"\\href\s*\{[^}]*\}\{([^}]*)\}", r"\1", text)
        text = re.sub(r"\\url\s*\{([^}]*)\}", r"\1", text)

        # 去除常见文本格式命令: \textbf{...}, \textit{...}, \texttt{...} 等
        text = re.sub(r"\\textbf\s*\{([^}]*)\}", r"\1", text)
        text = re.sub(r"\\textit\s*\{([^}]*)\}", r"\1", text)
        text = re.sub(r"\\texttt\s*\{([^}]*)\}", r"\1", text)
        text = re.sub(r"\\textsf\s*\{([^}]*)\}", r"\1", text)
        text = re.sub(r"\\textsc\s*\{([^}]*)\}", r"\1", text)
        text = re.sub(r"\\emph\s*\{([^}]*)\}", r"\1", text)
        text = re.sub(r"\\underline\s*\{([^}]*)\}", r"\1", text)

        # 去除尺寸/间距命令: \large, \small, \hspace, \vspace 等
        text = re.sub(r"\\(hspace|vspace)\*?\{[^}]*\}", "", text)
        text = re.sub(r"\\(small|large|Large|LARGE|huge|Huge|tiny|footnotesize|normalsize)(\s)", r"\2", text)

        # 去除 \item 标记（替换为符号）
        text = re.sub(r"\\item\s*(?:\[[^\]]*\])?", "• ", text)

        # 去除行首的 \noindent, \indent
        text = re.sub(r"\\noindent\s+", "", text)
        text = re.sub(r"\\indent\s+", "", text)

        # 去除常见自定义命令 (简单的)，将其当作文本
        text = re.sub(r"\\(newcommand|renewcommand|providecommand)\s*\{[^}]*\}\s*\{[^}]*\}", "", text)
        text = re.sub(
            r"\\(usepackage|documentclass|pagestyle|setlength|renewcommand)(?:\[[^\]]*\])?\{[^}]*\}", "", text
        )
        text = re.sub(r"\\makeatletter.*?\\makeatother", "", text, flags=re.DOTALL)

        # 去除图形/表格命令
        text = re.sub(r"\\includegraphics\s*(?:\[[^\]]*\])?\{[^}]*\}", "[图片]", text)
        text = re.sub(r"\\caption\s*\{([^}]*)\}", r"\1", text)

        # 去除 \documentclass, \begin{document}, \end{document} 等结构命令
        text = re.sub(r"\\(title|author|date)\s*\{([^}]*)\}", r"\2", text)
        text = re.sub(r"\\(maketitle|tableofcontents|newpage|clearpage|pagebreak|linebreak)\b", "", text)

        # 去除其他简单命令（没有花括号参数的）: \LaTeX, \TeX, \ldots, \dots, \~, \^ 等
        text = re.sub(r"\\LaTeX\b", "LaTeX", text)
        text = re.sub(r"\\TeX\b", "TeX", text)
        text = re.sub(r"\\ldots\b", "...", text)
        text = re.sub(r"\\dots\b", "...", text)
        text = re.sub(r"\\\\", " ", text)  # 手动换行符替换为空格
        text = re.sub(r"\\&", "&", text)
        text = re.sub(r"\\#", "#", text)
        text = re.sub(r"\\_", "_", text)
        text = re.sub(r"\\\{", "{", text)
        text = re.sub(r"\\\}", "}", text)
        text = re.sub(r"\\textbackslash\b", "\\", text)

        # 去除剩余的带花括号参数的命令（尽力而为）
        text = re.sub(r"\\([a-zA-Z]+)(\s*\{[^}]*\})*", r" \1 ", text)

        # 清理多余空白
        text = re.sub(r" +", " ", text)
        text = re.sub(r"\n +", "\n", text)
        text = re.sub(r" +\n", "\n", text)
        text = re.sub(r"\n\n+", "\n\n", text)

        return text.strip()
