"""生产整改阶段证据契约测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.core.phase_evidence_contract import (
    ApiDocumentationDetail,
    ArchitectureDocumentationDetail,
    BenchmarkPromotion,
    CommandExecutionEvidence,
    DeferredFindingDisposition,
    DocumentationHeader,
    DocumentationRecord,
    DocumentationStatus,
    FindingSeverity,
    LoadRunDetail,
    RegressionEvidenceSet,
    RegressionHeader,
    RegressionRecord,
    RegressionStatus,
    RegressionStatusTransition,
    RerunScope,
    SourceFixDetail,
    StaticRunDetail,
    TruthSource,
    TruthValidationStatus,
)
from src.core.phase_evidence_contract import (
    TestLayer as EvidenceTestLayer,
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

EVIDENCE_TEST_TIME = datetime(2026, 7, 15, tzinfo=UTC)
EVIDENCE_TEST_PATH = Path(".tmp/evidence/result.json")
EVIDENCE_UNKNOWN_FIELD = "unknown_field"
EVIDENCE_TEST_SHA256 = "a" * 64


class TestPhaseEvidenceContract:
    """验证阶段证据公共头与强类型扩展约束。"""

    def test_test_run_when_contract_valid_should_round_trip(self) -> None:
        """验证测试运行证据可稳定序列化往返。"""

        record = self._build_test_run_record()

        restored = EvidenceRunRecord.model_validate_json(record.model_dump_json())

        assert restored == record
        assert restored.detail.status == EvidenceRunStatus.PASSED

    def test_test_run_when_outer_kind_mismatch_should_reject(self) -> None:
        """验证测试运行外层类型与扩展类型不一致时拒绝。"""

        payload = self._build_test_run_record().model_dump(mode="python")
        payload["kind"] = "unit"

        with pytest.raises(ValidationError, match="外层类型"):
            EvidenceRunRecord.model_validate(payload)

    def test_test_run_when_unknown_field_provided_should_reject(self) -> None:
        """验证测试运行未知字段被拒绝。"""

        payload = self._build_test_run_record().model_dump(mode="python")
        payload[EVIDENCE_UNKNOWN_FIELD] = True

        with pytest.raises(ValidationError):
            EvidenceRunRecord.model_validate(payload)

    def test_test_run_when_unknown_kind_should_reject(self) -> None:
        """验证测试运行扩展使用未知判别值时拒绝。"""

        payload = self._build_test_run_record().model_dump(mode="python")
        payload["detail"]["kind"] = "unknown_run"

        with pytest.raises(ValidationError):
            EvidenceRunRecord.model_validate(payload)

    def test_test_run_when_schema_version_invalid_should_reject(self) -> None:
        """验证测试运行错误版本被拒绝。"""

        payload = self._build_test_run_record().model_dump(mode="python")
        payload["detail"]["schema_version"] = "2.0"

        with pytest.raises(ValidationError):
            EvidenceRunRecord.model_validate(payload)

    def test_test_run_when_passed_with_skip_should_reject(self) -> None:
        """验证真实通过记录不能包含 skip。"""

        payload = self._build_test_run_record().model_dump(mode="python")
        payload["detail"]["skipped_count"] = 1

        with pytest.raises(ValidationError, match="skip"):
            EvidenceRunRecord.model_validate(payload)

    def test_test_run_when_blocked_without_prerequisite_should_reject(self) -> None:
        """验证阻断结果缺少可复现前置条件时拒绝。"""

        with pytest.raises(ValidationError, match="前置条件"):
            StaticRunDetail(
                status=EvidenceRunStatus.BLOCKED,
                command="nox -s static",
                exit_code=None,
                duration_seconds=0,
                environment_summary="测试环境",
                failure_summary=None,
                evidence_path=EVIDENCE_TEST_PATH,
            )

    def test_command_execution_when_time_window_reversed_should_reject(self) -> None:
        """验证命令结束时间早于开始时间时拒绝证据。"""

        with pytest.raises(ValidationError, match="结束时间"):
            CommandExecutionEvidence(
                command="pytest -q",
                tool_version="pytest-9.0.3",
                exit_code=0,
                finding_count=0,
                evidence_path=EVIDENCE_TEST_PATH,
                started_at=datetime(2026, 7, 16, 1, tzinfo=UTC),
                finished_at=datetime(2026, 7, 16, tzinfo=UTC),
                duration_seconds=1,
            )

    def test_regression_when_verified_with_failed_scope_should_reject(self) -> None:
        """验证已验证问题未完成影响面回跑时拒绝。"""

        with pytest.raises(ValidationError, match="模块级"):
            RegressionRecord(
                header=RegressionHeader(
                    finding_id="REG-016",
                    affected_module="task",
                    severity=FindingSeverity.P1,
                    test_run_id="run-016",
                ),
                kind="source_fix",
                detail=SourceFixDetail(
                    root_cause="发布确认未接入生产主链。",
                    evidence_path=EVIDENCE_TEST_PATH,
                ),
                status=RegressionStatus.VERIFIED,
                rerun_scope=RerunScope.FAILED,
                evidence=self._build_regression_evidence(),
                status_history=self._build_regression_history(),
            )

    def test_regression_when_contract_valid_should_round_trip(self) -> None:
        """验证回归证据可稳定序列化往返。"""

        record = self._build_regression_record()

        restored = RegressionRecord.model_validate_json(record.model_dump_json())

        assert restored == record

    def test_regression_when_unknown_kind_should_reject(self) -> None:
        """验证回归扩展使用未知判别值时拒绝。"""

        payload = self._build_regression_record().model_dump(mode="python")
        payload["detail"]["kind"] = "unknown_fix"

        with pytest.raises(ValidationError):
            RegressionRecord.model_validate(payload)

    def test_regression_when_unknown_field_should_reject(self) -> None:
        """验证回归扩展未知字段被拒绝。"""

        payload = self._build_regression_record().model_dump(mode="python")
        payload["detail"][EVIDENCE_UNKNOWN_FIELD] = True

        with pytest.raises(ValidationError):
            RegressionRecord.model_validate(payload)

    def test_regression_when_schema_version_invalid_should_reject(self) -> None:
        """验证回归证据错误版本被拒绝。"""

        payload = self._build_regression_record().model_dump(mode="python")
        payload["detail"]["schema_version"] = "2.0"

        with pytest.raises(ValidationError):
            RegressionRecord.model_validate(payload)

    def test_regression_when_outer_kind_mismatch_should_reject(self) -> None:
        """验证回归外层与扩展类型不一致时拒绝。"""

        payload = self._build_regression_record().model_dump(mode="python")
        payload["kind"] = "test_fix"

        with pytest.raises(ValidationError, match="外层类型"):
            RegressionRecord.model_validate(payload)

    def test_test_layer_when_unknown_value_should_reject(self) -> None:
        """验证测试层级封闭集合拒绝未知值。"""

        with pytest.raises(ValueError):
            EvidenceTestLayer("unknown")

    def test_regression_when_p3_deferred_without_owner_should_reject(self) -> None:
        """验证未关闭 P3 必须声明负责人、风险和晋升条件。"""

        payload = self._build_regression_record().model_dump(mode="python")
        payload["header"]["severity"] = FindingSeverity.P3
        payload["status"] = RegressionStatus.FIXED
        payload["status_history"] = payload["status_history"][:-1]

        with pytest.raises(ValidationError, match="P3"):
            RegressionRecord.model_validate(payload)

        payload["deferred_disposition"] = DeferredFindingDisposition(
            owner="发布负责人",
            risk="远端门禁结果未知。",
            prerequisites=("接入 GitHub 远端。",),
            promotion_criteria=("quality workflow 通过。",),
        ).model_dump(mode="python")
        record = RegressionRecord.model_validate(payload)

        assert record.status == RegressionStatus.FIXED

    def test_documentation_when_archived_without_replacement_should_reject(self) -> None:
        """验证归档文档缺少替代路径时拒绝。"""

        with pytest.raises(ValidationError, match="替代路径"):
            ArchitectureDocumentationDetail(
                truth_source=TruthSource.SOURCE,
                evidence_path=EVIDENCE_TEST_PATH,
                status=DocumentationStatus.ARCHIVED,
                content_sha256=EVIDENCE_TEST_SHA256,
                validation_status=TruthValidationStatus.VERIFIED,
                validation_summary="内容事实已核验。",
                fact_evidence_paths=(EVIDENCE_TEST_PATH,),
            )

    def test_documentation_when_contract_valid_should_keep_kind_consistent(self) -> None:
        """验证文档证据公共头与扩展类型一致。"""

        record = DocumentationRecord(
            header=DocumentationHeader(
                topic="运行时架构",
                applicable_version="0.1.0",
                code_baseline="baseline-20260715",
                verified_at=EVIDENCE_TEST_TIME,
            ),
            kind="architecture",
            detail=ArchitectureDocumentationDetail(
                truth_source=TruthSource.SOURCE,
                evidence_path=EVIDENCE_TEST_PATH,
                status=DocumentationStatus.CURRENT,
                content_sha256=EVIDENCE_TEST_SHA256,
                validation_status=TruthValidationStatus.VERIFIED,
                validation_summary="内容事实已核验。",
                fact_evidence_paths=(EVIDENCE_TEST_PATH,),
            ),
        )

        restored = DocumentationRecord.model_validate_json(record.model_dump_json())

        assert restored == record
        assert restored.kind == restored.detail.kind

    def test_documentation_when_unknown_kind_should_reject(self) -> None:
        """验证文档扩展使用未知判别值时拒绝。"""

        payload = self._build_documentation_record().model_dump(mode="python")
        payload["detail"]["kind"] = "unknown_document"

        with pytest.raises(ValidationError):
            DocumentationRecord.model_validate(payload)

    def test_documentation_when_unknown_field_should_reject(self) -> None:
        """验证文档扩展未知字段被拒绝。"""

        payload = self._build_documentation_record().model_dump(mode="python")
        payload["detail"][EVIDENCE_UNKNOWN_FIELD] = True

        with pytest.raises(ValidationError):
            DocumentationRecord.model_validate(payload)

    def test_documentation_when_schema_version_invalid_should_reject(self) -> None:
        """验证文档证据错误版本被拒绝。"""

        payload = self._build_documentation_record().model_dump(mode="python")
        payload["header"]["schema_version"] = "2.0"

        with pytest.raises(ValidationError):
            DocumentationRecord.model_validate(payload)

    def test_documentation_when_outer_kind_mismatch_should_reject(self) -> None:
        """验证文档外层与扩展类型不一致时拒绝。"""

        payload = self._build_documentation_record().model_dump(mode="python")
        payload["kind"] = "architecture"

        with pytest.raises(ValidationError, match="外层类型"):
            DocumentationRecord.model_validate(payload)

    def test_load_run_should_require_resource_peaks_and_stability(self) -> None:
        """验证性能证据结构化承载资源峰值与稳定性判断。"""

        detail = LoadRunDetail(
            status=EvidenceRunStatus.PASSED,
            command="locust --headless",
            exit_code=0,
            test_count=100,
            duration_seconds=60,
            environment_summary="生产验证环境",
            evidence_path=EVIDENCE_TEST_PATH,
            promotion=BenchmarkPromotion.REJECTED,
            stable_across_runs=False,
            peak_cpu_percent=80,
            peak_memory_mebibytes=256,
            peak_thread_count=12,
            peak_connection_count=20,
        )

        assert detail.promotion == BenchmarkPromotion.REJECTED
        assert detail.stable_across_runs is False

    def _build_test_run_record(self) -> EvidenceRunRecord:
        """构建静态检查运行证据。"""

        return EvidenceRunRecord(
            header=EvidenceRunHeader(
                run_id="static-20260715",
                code_baseline="baseline-20260715",
                environment="python-3.11",
                started_at=EVIDENCE_TEST_TIME,
                command_entry="nox -s static",
            ),
            kind="static",
            detail=StaticRunDetail(
                status=EvidenceRunStatus.PASSED,
                command="nox -s static",
                exit_code=0,
                test_count=1,
                duration_seconds=1,
                environment_summary="本地项目环境",
                failure_summary=None,
                evidence_path=EVIDENCE_TEST_PATH,
            ),
        )

    def _build_regression_record(self) -> RegressionRecord:
        """构建已完成影响面回跑的回归证据。"""

        return RegressionRecord(
            header=RegressionHeader(
                finding_id="REG-022",
                affected_module="phase_evidence",
                severity=FindingSeverity.P1,
                test_run_id="integration-20260715",
            ),
            kind="source_fix",
            detail=SourceFixDetail(
                root_cause="阶段证据此前未接入持久化主流程。",
                evidence_path=EVIDENCE_TEST_PATH,
            ),
            status=RegressionStatus.VERIFIED,
            rerun_scope=RerunScope.FULL_SUITE,
            evidence=self._build_regression_evidence(),
            status_history=self._build_regression_history(),
        )

    def _build_documentation_record(self) -> DocumentationRecord:
        """构建当前 API 文档事实证据。"""

        return DocumentationRecord(
            header=DocumentationHeader(
                topic="管理员身份 API",
                applicable_version="2026.07.15",
                code_baseline="baseline-20260715",
                verified_at=EVIDENCE_TEST_TIME,
            ),
            kind="api",
            detail=ApiDocumentationDetail(
                truth_source=TruthSource.OPENAPI,
                evidence_path=EVIDENCE_TEST_PATH,
                status=DocumentationStatus.CURRENT,
                content_sha256=EVIDENCE_TEST_SHA256,
                validation_status=TruthValidationStatus.VERIFIED,
                validation_summary="内容事实已核验。",
                fact_evidence_paths=(EVIDENCE_TEST_PATH,),
            ),
        )

    @staticmethod
    def _build_regression_evidence() -> RegressionEvidenceSet:
        """构建旧版复现、定向和影响面证据集合。"""

        return RegressionEvidenceSet(
            source_path=Path("src/core/phase_evidence_contract.py"),
            source_line=1,
            trigger_condition="生成阶段证据。",
            affected_scope="阶段证据主流程。",
            reproduction_command="pytest -q test/contract_test/test_phase_evidence_contract.py",
            test_layer=EvidenceTestLayer.CONTRACT,
            test_file=Path("test/contract_test/test_phase_evidence_contract.py"),
            directed_testcase="test_regression_when_contract_valid_should_round_trip",
            key_assertions=("契约序列化往返一致。",),
            old_reproduction_path=EVIDENCE_TEST_PATH,
            directed_rerun_path=EVIDENCE_TEST_PATH,
            impact_rerun_path=EVIDENCE_TEST_PATH,
        )

    @staticmethod
    def _build_regression_history() -> tuple[RegressionStatusTransition, ...]:
        """构建 open、fixed、verified 状态迁移。"""

        return (
            RegressionStatusTransition(
                status=RegressionStatus.OPEN,
                changed_at=EVIDENCE_TEST_TIME,
                evidence_path=EVIDENCE_TEST_PATH,
            ),
            RegressionStatusTransition(
                status=RegressionStatus.FIXED,
                changed_at=EVIDENCE_TEST_TIME,
                evidence_path=EVIDENCE_TEST_PATH,
            ),
            RegressionStatusTransition(
                status=RegressionStatus.VERIFIED,
                changed_at=EVIDENCE_TEST_TIME,
                evidence_path=EVIDENCE_TEST_PATH,
            ),
        )
