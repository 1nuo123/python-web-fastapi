"""公开契约快照与工作区审查目录单元测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.api.evidence import public_contract_snapshot_builder
from src.api.evidence.public_contract_snapshot_builder import (
    PublicContractComparison,
    PublicContractSnapshot,
    PublicContractSnapshotBuilder,
)
from src.infrastructure.evidence import workspace_audit_catalog_builder
from src.infrastructure.evidence.workspace_audit_catalog_builder import (
    FindingRelationCatalog,
    ModuleReviewIndex,
    WorkspaceAuditCatalogBuilder,
    WorkspaceInventory,
)

EXPECTED_FINDING_RELATION_COUNT = 19
EXPECTED_AUDIT_DIMENSION_COUNT = 16
EXPECTED_MIGRATION_HEAD = "202608190230"


class TestWorkspaceEvidenceCatalogUnit:
    """验证契约快照可比对且审查目录覆盖全部责任域。"""

    def test_public_contract_snapshot_should_freeze_and_compare_machine_contract(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证 OpenAPI、路由、配置、迁移和任务契约可机器比对。"""

        current_path = tmp_path / "current.json"
        baseline_path = tmp_path / "baseline.json"
        comparison_path = tmp_path / "comparison.json"
        monkeypatch.setattr(
            public_contract_snapshot_builder,
            "PUBLIC_CONTRACT_BASELINE_PATH",
            baseline_path,
        )
        monkeypatch.setattr(
            public_contract_snapshot_builder,
            "PUBLIC_CONTRACT_COMPARISON_PATH",
            comparison_path,
        )

        PublicContractSnapshotBuilder.save(current_path)
        snapshot = PublicContractSnapshot.model_validate_json(
            current_path.read_text(encoding="utf-8")
        )
        comparison = PublicContractComparison.model_validate_json(
            comparison_path.read_text(encoding="utf-8")
        )

        assert snapshot.routes
        assert snapshot.configuration
        assert snapshot.migration_heads == (EXPECTED_MIGRATION_HEAD,)
        assert snapshot.task_contracts
        assert comparison.compatible is True
        assert comparison.changed_sections == ()

    def test_public_contract_snapshot_should_require_explicit_baseline_promotion(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证显式晋升能够替换已经存在但不可解析的旧基线。"""

        current_path = tmp_path / "current.json"
        baseline_path = tmp_path / "baseline.json"
        comparison_path = tmp_path / "comparison.json"
        baseline_path.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(
            public_contract_snapshot_builder,
            "PUBLIC_CONTRACT_BASELINE_PATH",
            baseline_path,
        )
        monkeypatch.setattr(
            public_contract_snapshot_builder,
            "PUBLIC_CONTRACT_COMPARISON_PATH",
            comparison_path,
        )

        PublicContractSnapshotBuilder.save(current_path, promote_baseline=True)
        baseline = PublicContractSnapshot.model_validate_json(
            baseline_path.read_text(encoding="utf-8")
        )
        comparison = PublicContractComparison.model_validate_json(
            comparison_path.read_text(encoding="utf-8")
        )

        assert baseline.migration_heads == (EXPECTED_MIGRATION_HEAD,)
        assert comparison.compatible is True
        assert comparison.changed_sections == ()

    def test_workspace_audit_catalog_should_cover_eight_inventories_and_all_modules(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证八类清单、五层模块和两套 finding 关系均可解析。"""

        inventory_path = tmp_path / "inventory.json"
        module_path = tmp_path / "modules.json"
        relation_path = tmp_path / "relations.json"
        monkeypatch.setattr(
            workspace_audit_catalog_builder,
            "WORKSPACE_INVENTORY_PATH",
            inventory_path,
        )
        monkeypatch.setattr(
            workspace_audit_catalog_builder,
            "MODULE_AUDIT_PATH",
            module_path,
        )
        monkeypatch.setattr(
            workspace_audit_catalog_builder,
            "FINDING_RELATION_PATH",
            relation_path,
        )

        WorkspaceAuditCatalogBuilder.build()
        inventory = WorkspaceInventory.model_validate_json(
            inventory_path.read_text(encoding="utf-8")
        )
        module_index = ModuleReviewIndex.model_validate_json(
            module_path.read_text(encoding="utf-8")
        )
        finding_catalog = FindingRelationCatalog.model_validate_json(
            relation_path.read_text(encoding="utf-8")
        )

        assert len({entry.kind for entry in inventory.entries}) == 8
        assert module_index.modules
        assert all(
            len(module.dimensions) == EXPECTED_AUDIT_DIMENSION_COUNT
            for module in module_index.modules
        )
        assert len(finding_catalog.relations) == EXPECTED_FINDING_RELATION_COUNT
