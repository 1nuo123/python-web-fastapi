"""生产整改阶段证据索引命令行入口。"""

from __future__ import annotations

import argparse

from loguru import logger

from src.api.evidence.public_contract_snapshot_builder import (
    PUBLIC_CONTRACT_COMPARISON_PATH,
    PublicContractComparison,
    PublicContractSnapshotBuilder,
)
from src.infrastructure.evidence.code_baseline_calculator import CodeBaselineCalculator
from src.infrastructure.evidence.documentation_catalog_builder import (
    DocumentationCatalogBuilder,
)
from src.infrastructure.evidence.phase_evidence_store import PhaseEvidenceStore
from src.infrastructure.evidence.regression_catalog_builder import RegressionCatalogBuilder
from src.infrastructure.evidence.workspace_audit_catalog_builder import (
    WorkspaceAuditCatalogBuilder,
)

PHASE_EVIDENCE_SUCCESS_EXIT_CODE = 0
PHASE_EVIDENCE_BLOCKED_EXIT_CODE = 1


class PhaseEvidenceCli:
    """生成文档事实目录并校验全部阶段证据。"""

    def run(self) -> int:
        """执行证据目录生成和索引校验。"""

        parser = argparse.ArgumentParser(description="生成生产整改阶段证据索引。")
        parser.parse_args()
        baseline = CodeBaselineCalculator.calculate()
        store = PhaseEvidenceStore()
        PublicContractSnapshotBuilder.save()
        contract_comparison = PublicContractComparison.model_validate_json(
            PUBLIC_CONTRACT_COMPARISON_PATH.read_text(encoding="utf-8")
        )
        WorkspaceAuditCatalogBuilder.build()
        regression_paths = RegressionCatalogBuilder(store).build()
        documentation_paths = DocumentationCatalogBuilder(store).build(code_baseline=baseline)
        index = store.build_index()
        logger.info(
            "阶段证据索引生成完成：测试运行={}，回归记录={}，文档记录={}。",
            len(index.test_runs),
            len(index.regressions),
            len(documentation_paths),
        )
        if index.blocked_documentation:
            logger.error(
                "阶段证据包含 {} 份内容事实校验阻断文档。",
                len(index.blocked_documentation),
            )
            return PHASE_EVIDENCE_BLOCKED_EXIT_CODE
        if not contract_comparison.compatible:
            logger.error(
                "公开契约存在未声明变化：{}。",
                "、".join(contract_comparison.changed_sections),
            )
            return PHASE_EVIDENCE_BLOCKED_EXIT_CODE
        if len(index.regressions) != len(regression_paths):
            logger.error("回归证据索引与本轮生成记录数量不一致。")
            return PHASE_EVIDENCE_BLOCKED_EXIT_CODE
        if index.missing_required_test_run_ids:
            logger.error(
                "当前统一基线缺少必需测试运行：{}。",
                "、".join(index.missing_required_test_run_ids),
            )
            return PHASE_EVIDENCE_BLOCKED_EXIT_CODE
        return PHASE_EVIDENCE_SUCCESS_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(PhaseEvidenceCli().run())
