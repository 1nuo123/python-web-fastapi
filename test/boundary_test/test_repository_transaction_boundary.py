"""Repository 与 UoW 事务职责边界回归。"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

REPOSITORY_IMPLEMENTATION_DIRECTORY: Final = Path("src/infrastructure/persistence/repository_impl")
FORBIDDEN_TRANSACTION_METHODS: Final = frozenset({"commit", "rollback", "close", "dispose"})


class TestRepositoryTransactionBoundary:
    """阻止 Repository 越过外层 UoW 事务边界。"""

    def test_repository_implementation_when_scanned_should_not_own_transaction(self) -> None:
        """验证仓储实现不提交、回滚或释放外层会话。"""

        violations: list[str] = []
        for source_path in sorted(REPOSITORY_IMPLEMENTATION_DIRECTORY.glob("*.py")):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr in FORBIDDEN_TRANSACTION_METHODS:
                    violations.append(f"{source_path.as_posix()}:{node.lineno}:{node.func.attr}")

        assert violations == []
