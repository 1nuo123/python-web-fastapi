"""通用基础设施禁止反向依赖 Codex 的边界测试。"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

GENERIC_CAPABILITY_ROOTS: Final = (
    Path("src/core/artifact_release_contract"),
    Path("src/core/concurrency_contract"),
    Path("src/core/cryptography_contract"),
    Path("src/core/distributed_state_contract"),
    Path("src/core/outbox_contract"),
    Path("src/core/stream_contract"),
    Path("src/infrastructure/artifact_release"),
    Path("src/infrastructure/concurrency"),
    Path("src/infrastructure/cryptography"),
    Path("src/infrastructure/distributed_state"),
    Path("src/infrastructure/outbox"),
    Path("src/infrastructure/streaming"),
)
FORBIDDEN_CODEX_MODULE_PREFIXES: Final = (
    "src.application.codex",
    "src.core.codex_contract",
    "src.infrastructure.codex",
)


class TestGenericInfrastructureImportBoundary:
    """枚举 AST import，防止通用能力吸收 Codex 业务语义。"""

    def test_generic_capabilities_should_not_import_codex_modules(self) -> None:
        violations: list[tuple[Path, int, str]] = []
        for capability_root in GENERIC_CAPABILITY_ROOTS:
            for source_path in capability_root.rglob("*.py"):
                tree = ast.parse(
                    source_path.read_text(encoding="utf-8"),
                    filename=str(source_path),
                )
                violations.extend(self._find_violations(source_path, tree))

        assert violations == []

    @staticmethod
    def _find_violations(
        source_path: Path,
        tree: ast.Module,
    ) -> list[tuple[Path, int, str]]:
        violations: list[tuple[Path, int, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                if node.module.startswith(FORBIDDEN_CODEX_MODULE_PREFIXES):
                    violations.append((source_path, node.lineno, node.module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(FORBIDDEN_CODEX_MODULE_PREFIXES):
                        violations.append((source_path, node.lineno, alias.name))
        return violations
