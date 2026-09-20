"""Regression guards for pytest's declared plugin dependencies."""

import re
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_timeout_addopt_has_declared_dev_dependency():
    """Using --timeout requires pytest-timeout in the installable dev extra."""
    config = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev_dependency_names = {
        re.split(r"[<>=!~;\s\[]", dependency, maxsplit=1)[0].lower().replace("_", "-")
        for dependency in config["project"]["optional-dependencies"]["dev"]
    }

    assert "--timeout" in config["tool"]["pytest"]["ini_options"]["addopts"]
    assert "pytest-timeout" in dev_dependency_names
