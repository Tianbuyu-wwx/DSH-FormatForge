"""单一版本来源。

pyproject.toml 通过 setuptools dynamic attr 读取此处；
CLI（__main__.py version 命令）也从此处引用。
npm 侧 packages/dsh-formatforge/package.json 无法动态读取 Python，
发布时需手动保持一致（两处同值）。
"""

__version__ = "0.11.0"
