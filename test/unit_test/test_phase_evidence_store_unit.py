"""阶段证据持久化与文档目录单元测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.core.phase_evidence_contract import (
    DocumentationRecord,
    RegressionRecord,
    RegressionStatus,
    StaticRunDetail,
    TruthValidationStatus,
)
from src.core.phase_evidence_contract import (
    TestRunHeader as EvidenceRunHeader,
)
from src.core.phase_evidence_contract import (
    TestRunRecord as EvidenceRunRecord,
)
from src.core.phase_evidence_contract import (
    TestRunStatus as EvidenceRunStatus,
)
from src.infrastructure.evidence import documentation_catalog_builder
from src.infrastructure.evidence.documentation_catalog_builder import (
    DocumentationCatalogBuilder,
)
from src.infrastructure.evidence.phase_evidence_store import PhaseEvidenceStore
from src.infrastructure.evidence.regression_catalog_builder import RegressionCatalogBuilder

EVIDENCE_STORE_TEST_TIME = datetime(2026, 7, 15, tzinfo=UTC)
EVIDENCE_STORE_TEST_BASELINE = "evidence-store-test-baseline"
EVIDENCE_STORE_TEST_RUN_ID = "static-evidence-store-test"
EXPECTED_REGRESSION_FINDING_COUNT = 26
REMOTE_CI_FINDING_ID = "REG-023"


class TestPhaseEvidenceStoreUnit:
    """验证证据原子写入、反序列化校验和索引生成。"""

    def test_store_when_test_run_saved_should_build_valid_index(self, tmp_path: Path) -> None:
        """验证测试运行记录写入后可进入统一索引。"""

        store = PhaseEvidenceStore(root_directory=tmp_path / "evidence")
        evidence_path = tmp_path / "evidence" / "test-runs" / (f"{EVIDENCE_STORE_TEST_RUN_ID}.json")
        record = EvidenceRunRecord(
            header=EvidenceRunHeader(
                run_id=EVIDENCE_STORE_TEST_RUN_ID,
                code_baseline=EVIDENCE_STORE_TEST_BASELINE,
                environment="单元测试环境",
                started_at=EVIDENCE_STORE_TEST_TIME,
                command_entry="nox -s static",
            ),
            kind="static",
            detail=StaticRunDetail(
                status=EvidenceRunStatus.PASSED,
                command="nox -s static",
                exit_code=0,
                duration_seconds=1,
                environment_summary="单元测试环境",
                evidence_path=evidence_path,
            ),
        )

        saved_path = store.save_test_run(record)
        index = store.build_index()

        assert saved_path == evidence_path
        assert (
            EvidenceRunRecord.model_validate_json(saved_path.read_text(encoding="utf-8")) == record
        )
        assert index.test_runs == [evidence_path]

    def test_catalog_when_document_verified_should_record_content_fact(
        self, tmp_path: Path
    ) -> None:
        """验证通过内容校验的文档进入 current 强类型事实记录。"""

        store = PhaseEvidenceStore(root_directory=tmp_path / "evidence")
        documentation_path = tmp_path / "architecture.md"
        documentation_path.write_text("# 架构事实\n", encoding="utf-8")

        paths = DocumentationCatalogBuilder(
            store,
            documentation_paths=(documentation_path,),
        ).build(code_baseline=EVIDENCE_STORE_TEST_BASELINE)
        index = store.build_index()

        assert len(paths) == 1
        assert index.documentation == sorted(paths)
        assert index.blocked_documentation == []
        records = [
            DocumentationRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in paths
        ]
        assert all(
            record.detail.validation_status == TruthValidationStatus.VERIFIED for record in records
        )
        assert all(len(record.detail.content_sha256) == 64 for record in records)

    def test_catalog_when_redis_skip_claim_found_should_mark_blocked(self, tmp_path: Path) -> None:
        """验证 Redis 前置条件的过期 skip 口径会阻断文档事实。"""

        store = PhaseEvidenceStore(root_directory=tmp_path / "evidence")
        testing_directory = tmp_path / "08_testing"
        testing_directory.mkdir()
        documentation_path = testing_directory / "testing_strategy.md"
        documentation_path.write_text("Redis 不可达时显式 skip。\n", encoding="utf-8")

        paths = DocumentationCatalogBuilder(
            store,
            documentation_paths=(documentation_path,),
        ).build(code_baseline=EVIDENCE_STORE_TEST_BASELINE)
        index = store.build_index()

        assert index.blocked_documentation == paths

    def test_regression_catalog_when_built_should_record_every_finding(
        self,
        tmp_path: Path,
    ) -> None:
        """验证所有历史 finding 均生成结构化支持证据与状态迁移。"""

        store = PhaseEvidenceStore(root_directory=tmp_path / "evidence")
        directed_test_run_path = tmp_path / "directed.json"
        final_test_run_path = tmp_path / "final.json"
        paths = RegressionCatalogBuilder(
            store,
            support_directory=tmp_path / "regression-support",
            old_reproduction_directory=tmp_path / "regression-old-reproductions",
            directed_test_run_path=directed_test_run_path,
            final_test_run_path=final_test_run_path,
            remote_ci_test_run_path=tmp_path / "missing-remote-ci.json",
        ).build()
        index = store.build_index()

        assert len(paths) == EXPECTED_REGRESSION_FINDING_COUNT
        assert index.regressions == sorted(paths)
        records = [
            RegressionRecord.model_validate_json(path.read_text(encoding="utf-8")) for path in paths
        ]
        records_by_id = {record.header.finding_id: record for record in records}
        assert records_by_id[REMOTE_CI_FINDING_ID].status == RegressionStatus.FIXED
        assert all(record.status == RegressionStatus.FIXED for record in records)
        assert all(record.status_history[0].status == RegressionStatus.OPEN for record in records)
        assert all(record.evidence.test_file.is_file() for record in records)
        assert all(record.evidence.key_assertions for record in records)
        assert records_by_id[REMOTE_CI_FINDING_ID].deferred_disposition is not None

    def test_documentation_when_regression_summary_matches_should_verify(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证最终报告状态摘要与结构化 finding 一致时通过。"""

        store, report_path = self._prepare_documentation_status_validation(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
        )
        report_path.write_text(
            "# 最终报告\n\nREGRESSION_STATUS_COUNTS: open=0;fixed=26;verified=0;rejected=0\n",
            encoding="utf-8",
        )

        paths = DocumentationCatalogBuilder(
            store,
            documentation_paths=(report_path,),
        ).build(code_baseline=EVIDENCE_STORE_TEST_BASELINE)
        record = DocumentationRecord.model_validate_json(paths[0].read_text(encoding="utf-8"))

        assert record.detail.validation_status == TruthValidationStatus.VERIFIED

    def test_documentation_when_unverified_finding_claims_completion_should_block(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证存在未验证 finding 时禁止声明 Phase 4 完成。"""

        store, report_path = self._prepare_documentation_status_validation(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
        )
        report_path.write_text(
            "# 最终报告\n\n"
            "REGRESSION_STATUS_COUNTS: open=0;fixed=26;verified=0;rejected=0\n"
            "Phase 4 已完成。\n",
            encoding="utf-8",
        )

        paths = DocumentationCatalogBuilder(
            store,
            documentation_paths=(report_path,),
        ).build(code_baseline=EVIDENCE_STORE_TEST_BASELINE)
        record = DocumentationRecord.model_validate_json(paths[0].read_text(encoding="utf-8"))

        assert record.detail.validation_status == TruthValidationStatus.BLOCKED

    @staticmethod
    def _prepare_documentation_status_validation(
        *,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> tuple[PhaseEvidenceStore, Path]:
        """准备隔离的 finding 与文档状态交叉校验环境。"""

        evidence_root = tmp_path / "evidence"
        store = PhaseEvidenceStore(root_directory=evidence_root)
        RegressionCatalogBuilder(
            store,
            support_directory=tmp_path / "regression-support",
            old_reproduction_directory=tmp_path / "regression-old-reproductions",
            directed_test_run_path=tmp_path / "missing-directed.json",
            final_test_run_path=tmp_path / "missing-final.json",
            remote_ci_test_run_path=tmp_path / "missing-remote.json",
        ).build()
        phase_index_path = evidence_root / "phase_evidence_index.json"
        store.build_index()
        report_path = tmp_path / "final-review.md"
        monkeypatch.setattr(
            documentation_catalog_builder,
            "REGRESSION_EVIDENCE_DIRECTORY",
            evidence_root / "regressions",
        )
        monkeypatch.setattr(
            documentation_catalog_builder,
            "PHASE_EVIDENCE_INDEX_PATH",
            phase_index_path,
        )
        monkeypatch.setattr(
            documentation_catalog_builder,
            "FINAL_REVIEW_REPORT_PATH",
            report_path,
        )
        return store, report_path
