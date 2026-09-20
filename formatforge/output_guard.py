"""FF-M-protocol/audit: `--output-file` 的写入边界。

旧实现 `mkdir(parents=True, exist_ok=True)` + `write_text` 接受任意路径：
`--output-file ../../.dsh/config.json` 这类目标可被模型驱动的工具调用写入
（与 H11 同类的无沙箱写原语）。这里把可写范围收敛到**用户显式声明的根**：

  1. `FF_OUTPUT_ROOT` 环境变量（可多个，用 `os.pathsep` 分隔）是唯一授权来源；
  2. 未声明时 fail closed，不再把 CLI 进程 CWD 当作隐式授权；
  3. 源文件目录只描述输入，不能扩大输出边界；
  4. 仓库根和任何 Python 导入路径始终是只读保护区，即使配置误把它们包含在内；
  5. **文件写入另行限定输出扩展名白名单**（`resolve_output_file`）——见下方说明。

越界即抛 `OutputPathError`，由调用方转成 `bad_request` 协议错误——不再
「静默警告 + ok:true」。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# T1-8/audit: `--output-file` 只允许写出本产品真正产出的四种格式。
#
# 用**白名单**而不是「可执行扩展名黑名单」：黑名单永远列不全（`.py` / `.pyw` /
# `.pyc` / `.pyd` / `.so` / `.pth` / `.dylib`，以及各平台的可执行后缀），而本产品
# 的输出格式是封闭的四种。白名单在越界防护之上再堵死「往 sys.path 目录里丢一个
# 可被导入的文件」这条路——这正是 CWD 被当作受保护根时仍然值得保留的第二道锁。
#
# 注意：`--out`（目录）不走这条规则，它由 `resolve_output_path` 校验包含性即可，
# 因为批处理写出的文件名后缀来自 `batch.py::ext_map`，本身已被限定在这四种之内。
_OUTPUT_EXT_ALLOWLIST = frozenset({".md", ".html", ".json", ".txt"})


class OutputPathError(ValueError):
    """目标路径不在任何允许根内（协议层应报 bad_request）。"""


def _absolute(path: Path) -> Path:
    """尽量 resolve；失败也不抛（只保证绝对化）。"""
    try:
        return path.expanduser().resolve()
    except OSError:  # pragma: no cover - 平台相关防御
        return path.expanduser().absolute()


def allowed_output_roots(*, source: Path | None = None) -> list[Path]:
    """返回显式声明的可写根（source 仅为向后兼容，绝不授予权限）。"""
    roots: list[Path] = []
    declared = os.environ.get("FF_OUTPUT_ROOT")
    if declared:
        roots.extend(Path(chunk.strip()) for chunk in declared.split(os.pathsep) if chunk.strip())

    resolved: list[Path] = []
    for root in roots:
        root_abs = _absolute(root)
        if root_abs not in resolved:
            resolved.append(root_abs)
    return resolved


def _protected_output_roots() -> list[Path]:
    """返回无论如何都不得写入的代码/导入根。"""
    roots = [_absolute(Path(__file__).parent.parent)]
    for entry in sys.path:
        root = _absolute(Path.cwd() if not entry else Path(entry))
        if root not in roots:
            roots.append(root)
    return roots


def resolve_output_path(
    target: str | Path,
    *,
    source: Path | None = None,
    label: str = "--output-file",
) -> Path:
    """校验目标路径并返回可写绝对路径；越界抛 OutputPathError。"""
    resolved = _absolute(Path(target))
    roots = allowed_output_roots(source=source)
    if not roots:
        raise OutputPathError(
            f"{label} 写入被拒绝：未配置 FF_OUTPUT_ROOT；"
            "请显式声明一个位于代码和 Python 导入路径之外的输出根。"
        )
    for protected in _protected_output_roots():
        if resolved.is_relative_to(protected):
            raise OutputPathError(
                f"{label} 目标受保护：{resolved} 位于代码或 Python 导入路径 {protected} 内。"
            )
    for root in roots:
        if resolved.is_relative_to(root):
            return resolved
    raise OutputPathError(
        f"{label} 目标越界：{resolved} 不在任何允许根内；"
        f"允许根 = {', '.join(str(r) for r in roots)}。"
        f"如需写入其他位置，请用 FF_OUTPUT_ROOT 声明（多个用 '{os.pathsep}' 分隔）。"
    )


def resolve_output_file(
    target: str | Path,
    *,
    source: Path | None = None,
    label: str = "--output-file",
) -> Path:
    """**文件**写入的完整校验：包含性 + 输出扩展名白名单。

    凡是把内容写成单个文件的调用点都必须走这里，而不是 `resolve_output_path`。
    后者面向目录（`ff_batch --out`），不施加扩展名限制。
    """
    resolved = resolve_output_path(target, source=source, label=label)
    suffix = resolved.suffix.lower()
    if suffix not in _OUTPUT_EXT_ALLOWLIST:
        allowed = "、".join(sorted(_OUTPUT_EXT_ALLOWLIST))
        raise OutputPathError(
            f"{label} 扩展名不被允许：{resolved.name!r}（后缀 {suffix or '（无）'}）。"
            f"只允许写出本产品的输出格式：{allowed}。"
            f"需要其他后缀时请改用 `--out` 目录（批处理）或另行转换该文件。"
        )
    return resolved
