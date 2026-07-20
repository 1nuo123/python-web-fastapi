"""阶段证据源码基线摘要模块。"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Final

BASELINE_DIRECTORY_ROOTS: Final = (
    Path(".github/workflows"),
    Path("config"),
    Path("src"),
    Path("test"),
)
BASELINE_FIXED_FILES: Final = (
    Path(".dockerignore"),
    Path(".gitignore"),
    Path("compose.yml"),
    Path("compose.production.yml"),
    Path("Dockerfile"),
    Path("noxfile.py"),
    Path("pyproject.toml"),
    Path("uv.lock"),
)
IGNORED_BASELINE_DIRECTORY_NAMES: Final = frozenset(
    {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)
IGNORED_BASELINE_PATHS: Final = (
    Path("test/performance/autotuner/runs"),
    Path("test/performance/autotuner/capacity_tuning_report.json"),
)


class CodeBaselineCalculator:
    """计算源码、测试、配置与交付入口的稳定摘要。"""

    @staticmethod
    def calculate() -> str:
        """返回阶段证据使用的 SHA-256 基线。"""

        digest = sha256()
        paths = sorted(
            path
            for root in BASELINE_DIRECTORY_ROOTS
            for path in root.rglob("*")
            if path.is_file()
            and not any(part in IGNORED_BASELINE_DIRECTORY_NAMES for part in path.parts)
            and not any(
                path == ignored or ignored in path.parents for ignored in IGNORED_BASELINE_PATHS
            )
        )
        paths.extend(path for path in BASELINE_FIXED_FILES if path.is_file())
        paths.sort()
        for path in paths:
            digest.update(path.as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
        return digest.hexdigest()
