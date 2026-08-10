"""统一基础设施生产实现职责清单边界测试。"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

SOURCE_ROOT: Final = Path("src")
SHARED_REDIS_RESOURCE_PATH: Final = Path(
    "src/infrastructure/resource_slot/shared_redis_resource.py"
)
ALLOWED_STREAM_STATE_STORE_CLASSES: Final = {
    "DeferredStreamStateStore",
    "MemoryStreamStateStore",
    "RedisStreamStateStore",
}


class TestInfrastructureCapabilityAllowlistBoundary:
    """验证 Redis owner 与 stream store 不出现平行生产实现。"""

    def test_redis_client_construction_should_belong_to_shared_resource(self) -> None:
        findings: list[tuple[Path, int]] = []
        for source_path in SOURCE_ROOT.rglob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr == "from_url" and self._is_redis_constructor(node.func.value):
                    findings.append((source_path, node.lineno))

        assert findings
        assert {path for path, _line in findings} == {SHARED_REDIS_RESOURCE_PATH}
        assert len(findings) == 2

    def test_stream_state_store_implementations_should_match_allowlist(self) -> None:
        implementations: set[str] = set()
        for source_path in SOURCE_ROOT.rglob("*.py"):
            tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                if any(self._base_name(base) == "StreamStateStorePort" for base in node.bases):
                    implementations.add(node.name)

        assert implementations == ALLOWED_STREAM_STATE_STORE_CLASSES

    @staticmethod
    def _is_redis_constructor(node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return node.id in {"Redis", "SyncRedis", "AsyncRedis"}
        if isinstance(node, ast.Attribute):
            return node.attr == "Redis"
        return False

    @staticmethod
    def _base_name(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None
