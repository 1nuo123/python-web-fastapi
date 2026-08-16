"""冻结 App Server schema 快照的 CI drift 契约测试。"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from src.infrastructure.codex_agent.app_server_manifest_registry import (
    AppServerManifestRegistry,
)

PROTOCOL_ROOT: Final = Path("protocol/codex_app_server")
FROZEN_CODEX_VERSION: Final = "0.145.0"
FROZEN_JSON_SCHEMA_DIGEST: Final = (
    "86501505d7a626582cd7ded6eee36ab6bbaae30fd5d5c1021c0330e3f99d8109"
)
FROZEN_TYPESCRIPT_DIGEST: Final = "125dea8051ad1d8ae9c9c527e30d1d6aada2965fd1e77771f7c18806c77a6724"


class TestCodexAppServerSchemaDriftContract:
    """校验官方生成目录、manifest 计数与冻结 digest 一致。"""

    def test_frozen_snapshot_should_match_reviewed_manifest(self) -> None:
        registry = AppServerManifestRegistry(PROTOCOL_ROOT)
        manifests = registry.load_manifests()
        manifest = next(
            item for item in manifests if item.header.codex_version == FROZEN_CODEX_VERSION
        )
        version_root = PROTOCOL_ROOT / FROZEN_CODEX_VERSION
        json_schema_root = version_root / "json-schema"
        typescript_root = version_root / "typescript"

        assert manifest.detail.json_schema_bundle_sha256 == FROZEN_JSON_SCHEMA_DIGEST
        assert manifest.detail.typescript_bundle_sha256 == FROZEN_TYPESCRIPT_DIGEST
        assert registry.calculate_directory_digest(json_schema_root) == FROZEN_JSON_SCHEMA_DIGEST
        assert registry.calculate_directory_digest(typescript_root) == FROZEN_TYPESCRIPT_DIGEST
        assert manifest.detail.json_schema_file_count == self._count_files(json_schema_root)
        assert manifest.detail.typescript_file_count == self._count_files(typescript_root)

    def test_frozen_thread_contract_should_expose_recency_and_product_commands(self) -> None:
        thread_source = (
            PROTOCOL_ROOT / FROZEN_CODEX_VERSION / "typescript" / "v2" / "Thread.ts"
        ).read_text(encoding="utf-8")
        request_source = (
            PROTOCOL_ROOT / FROZEN_CODEX_VERSION / "typescript" / "ClientRequest.ts"
        ).read_text(encoding="utf-8")
        list_source = (
            PROTOCOL_ROOT
            / FROZEN_CODEX_VERSION
            / "typescript"
            / "v2"
            / "ThreadListParams.ts"
        ).read_text(encoding="utf-8")

        assert "recencyAt" in thread_source
        assert "name: string | null" in thread_source
        assert "isPinned" not in thread_source
        assert '"method": "thread/name/set"' in request_source
        assert '"method": "thread/archive"' in request_source
        assert '"method": "thread/unarchive"' in request_source
        assert "sortKey" in list_source
        assert "searchTerm" in list_source

    @staticmethod
    def _count_files(directory: Path) -> int:
        return sum(1 for path in directory.rglob("*") if path.is_file())
