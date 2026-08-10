"""Codex App Server 兼容判定应用端口。"""

from __future__ import annotations

from typing import Protocol

from src.domain.codex.codex_compatibility_policy import (
    CodexCompatibilityResult,
    CodexCompatibilityTuple,
)


class CodexAppServerCompatibilityPort(Protocol):
    """应用层使用的窄兼容判定边界。"""

    def evaluate(self, compatibility: CodexCompatibilityTuple) -> CodexCompatibilityResult: ...
