"""项目手册事实证据目录生成模块。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Final

from src.core.phase_evidence_contract import (
    ApiDocumentationDetail,
    ArchitectureDocumentationDetail,
    ConfigurationDocumentationDetail,
    DocumentationHeader,
    DocumentationRecord,
    DocumentationStatus,
    FindingSeverity,
    MigrationDocumentationDetail,
    OperationsDocumentationDetail,
    PerformanceDocumentationDetail,
    RegressionRecord,
    RegressionStatus,
    SecurityDocumentationDetail,
    TestingDocumentationDetail,
    TruthSource,
    TruthValidationStatus,
)
from src.infrastructure.evidence.phase_evidence_store import PhaseEvidenceStore

PROJECT_MANUAL_ROOT: Final = Path("docs/project_manual")
PROJECT_MANUAL_PATTERN: Final = "**/*.md"
FINAL_REVIEW_REPORT_PATH: Final = Path("docs/2026_7_13_生产级代码审查回归报告.md")
DOCUMENTATION_APPLICABLE_VERSION: Final = "2026.07.15"
CURRENT_MIGRATION_HEAD: Final = "202607051000"
REDIS_SKIP_PATTERN: Final = re.compile(
    r"(?:Redis.{0,24}(?:显式\s*)?skip|(?:显式|明确)\s*skip\s*条件)",
    flags=re.IGNORECASE,
)
MIGRATION_VERSION_EVIDENCE_PATH: Final = Path(
    "src/infrastructure/persistence/alembic/versions/202607051000_create_key_ring_snapshot.py"
)
TEST_STRATEGY_EVIDENCE_PATH: Final = Path("noxfile.py")
OPENAPI_EVIDENCE_PATH: Final = Path("src/infrastructure/fastapi_openapi_surface.py")
CONFIGURATION_EVIDENCE_PATH: Final = Path("config")
SOURCE_EVIDENCE_PATH: Final = Path("src")
PERFORMANCE_EVIDENCE_PATH: Final = Path("test/performance/autotuner/capacity_tuning_report.json")
REGRESSION_EVIDENCE_DIRECTORY: Final = Path("docs/evidence/regressions")
PHASE_EVIDENCE_INDEX_PATH: Final = Path("docs/evidence/phase_evidence_index.json")
REGRESSION_STATUS_TOKEN_PREFIX: Final = "REGRESSION_STATUS_COUNTS:"
FALSE_COMPLETION_PATTERN: Final = re.compile(
    r"(?:五个阶段|Phase\s*4|全部阶段).{0,24}(?:已完成|全部完成|完成状态)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DocumentationValidationResult:
    """单份文档内容级事实校验结果。"""

    status: TruthValidationStatus
    summary: str
    content_sha256: str
    evidence_paths: tuple[Path, ...]


class DocumentationTruthValidator:
    """依据当前源码、迁移和测试入口校验文档关键事实。"""

    @classmethod
    def validate(cls, documentation_path: Path) -> DocumentationValidationResult:
        """校验文档内容摘要、关键版本和真实依赖失败口径。"""

        content = documentation_path.read_text(encoding="utf-8")
        failures: list[str] = []
        evidence_paths = cls._resolve_evidence_paths(documentation_path)
        if not content.strip():
            failures.append("文档内容为空")
        normalized_path = documentation_path.as_posix()
        if "/06_data/" in normalized_path:
            if CURRENT_MIGRATION_HEAD not in content:
                failures.append(f"未声明当前迁移 head {CURRENT_MIGRATION_HEAD}")
        if "/08_testing/" in normalized_path and REDIS_SKIP_PATTERN.search(content):
            failures.append("仍把 Redis 前置条件缺失描述为 skip")
        if documentation_path == FINAL_REVIEW_REPORT_PATH or documentation_path == (
            PROJECT_MANUAL_ROOT / "README.md"
        ):
            cls._validate_regression_status(content=content, failures=failures)
        missing_evidence = tuple(path for path in evidence_paths if not path.exists())
        if missing_evidence:
            failures.append(
                "事实证据路径不存在：" + "、".join(path.as_posix() for path in missing_evidence)
            )
        status = TruthValidationStatus.BLOCKED if failures else TruthValidationStatus.VERIFIED
        summary = "；".join(failures) if failures else "关键事实与当前源码、迁移或测试入口一致。"
        return DocumentationValidationResult(
            status=status,
            summary=summary,
            content_sha256=sha256(content.encode("utf-8")).hexdigest(),
            evidence_paths=evidence_paths,
        )

    @staticmethod
    def _validate_regression_status(*, content: str, failures: list[str]) -> None:
        """把 finding 结构化状态与阶段完成表述交叉校验。"""

        records = [
            RegressionRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(REGRESSION_EVIDENCE_DIRECTORY.glob("*.json"))
        ]
        if not records:
            failures.append("缺少结构化 finding 状态记录")
            return
        counts = {
            status: sum(record.status == status for record in records)
            for status in RegressionStatus
        }
        expected_token = (
            f"{REGRESSION_STATUS_TOKEN_PREFIX} "
            f"open={counts[RegressionStatus.OPEN]};"
            f"fixed={counts[RegressionStatus.FIXED]};"
            f"verified={counts[RegressionStatus.VERIFIED]};"
            f"rejected={counts[RegressionStatus.REJECTED]}"
        )
        if expected_token not in content:
            failures.append(f"缺少或不匹配结构化 finding 状态摘要：{expected_token}")
        blocking_count = sum(
            record.header.severity in {FindingSeverity.P0, FindingSeverity.P1}
            and record.status != RegressionStatus.VERIFIED
            for record in records
        )
        if blocking_count > 0 and FALSE_COMPLETION_PATTERN.search(content):
            failures.append("存在未验证 P0/P1 finding 时仍声明 Phase 4 或全部阶段完成")

    @staticmethod
    def _resolve_evidence_paths(documentation_path: Path) -> tuple[Path, ...]:
        """按文档责任域返回真实事实源。"""

        topic = documentation_path.as_posix()
        if "/05_api_reference/" in topic:
            return (OPENAPI_EVIDENCE_PATH,)
        if "/06_data/" in topic:
            return (MIGRATION_VERSION_EVIDENCE_PATH,)
        if "/07_configuration_deployment/" in topic:
            return (CONFIGURATION_EVIDENCE_PATH,)
        if "/08_testing/" in topic:
            return (
                TEST_STRATEGY_EVIDENCE_PATH,
                Path("pyproject.toml"),
                PHASE_EVIDENCE_INDEX_PATH,
            )
        if documentation_path == FINAL_REVIEW_REPORT_PATH or documentation_path == (
            PROJECT_MANUAL_ROOT / "README.md"
        ):
            return (SOURCE_EVIDENCE_PATH, PHASE_EVIDENCE_INDEX_PATH)
        if documentation_path.name == "performance_notes.md":
            return (PERFORMANCE_EVIDENCE_PATH,)
        return (SOURCE_EVIDENCE_PATH,)


class DocumentationCatalogBuilder:
    """从当前项目手册生成逐文件 ``DocumentationRecord``。"""

    def __init__(
        self,
        store: PhaseEvidenceStore,
        documentation_paths: tuple[Path, ...] | None = None,
    ) -> None:
        """保存证据存储边界。"""

        self._store = store
        self._documentation_paths = documentation_paths

    def build(self, *, code_baseline: str) -> list[Path]:
        """生成全部当前手册记录并返回持久化路径。"""

        verified_at = datetime.now(UTC)
        paths: list[Path] = []
        documentation_paths = (
            list(self._documentation_paths)
            if self._documentation_paths is not None
            else sorted(PROJECT_MANUAL_ROOT.glob(PROJECT_MANUAL_PATTERN))
        )
        if self._documentation_paths is None:
            documentation_paths.append(FINAL_REVIEW_REPORT_PATH)
        for documentation_path in documentation_paths:
            record = self._build_record(
                documentation_path=documentation_path,
                code_baseline=code_baseline,
                verified_at=verified_at,
            )
            paths.append(self._store.save_documentation(record))
        return paths

    @staticmethod
    def _build_record(
        *,
        documentation_path: Path,
        code_baseline: str,
        verified_at: datetime,
    ) -> DocumentationRecord:
        """按手册目录职责构建强类型文档记录。"""

        topic = documentation_path.as_posix()
        validation = DocumentationTruthValidator.validate(documentation_path)
        header = DocumentationHeader(
            topic=topic,
            applicable_version=DOCUMENTATION_APPLICABLE_VERSION,
            code_baseline=code_baseline,
            verified_at=verified_at,
        )
        if "/05_api_reference/" in topic:
            return DocumentationRecord(
                header=header,
                kind="api",
                detail=ApiDocumentationDetail(
                    truth_source=TruthSource.OPENAPI,
                    evidence_path=documentation_path,
                    status=DocumentationStatus.CURRENT,
                    content_sha256=validation.content_sha256,
                    validation_status=validation.status,
                    validation_summary=validation.summary,
                    fact_evidence_paths=validation.evidence_paths,
                ),
            )
        if "/06_data/" in topic:
            return DocumentationRecord(
                header=header,
                kind="migration",
                detail=MigrationDocumentationDetail(
                    truth_source=TruthSource.MIGRATION,
                    evidence_path=documentation_path,
                    status=DocumentationStatus.CURRENT,
                    content_sha256=validation.content_sha256,
                    validation_status=validation.status,
                    validation_summary=validation.summary,
                    fact_evidence_paths=validation.evidence_paths,
                ),
            )
        if "/07_configuration_deployment/" in topic:
            return DocumentationRecord(
                header=header,
                kind="configuration",
                detail=ConfigurationDocumentationDetail(
                    truth_source=TruthSource.CONFIGURATION,
                    evidence_path=documentation_path,
                    status=DocumentationStatus.CURRENT,
                    content_sha256=validation.content_sha256,
                    validation_status=validation.status,
                    validation_summary=validation.summary,
                    fact_evidence_paths=validation.evidence_paths,
                ),
            )
        if "/08_testing/" in topic:
            return DocumentationRecord(
                header=header,
                kind="testing",
                detail=TestingDocumentationDetail(
                    truth_source=TruthSource.TEST_REPORT,
                    evidence_path=documentation_path,
                    status=DocumentationStatus.CURRENT,
                    content_sha256=validation.content_sha256,
                    validation_status=validation.status,
                    validation_summary=validation.summary,
                    fact_evidence_paths=validation.evidence_paths,
                ),
            )
        if documentation_path.name == "performance_notes.md":
            return DocumentationRecord(
                header=header,
                kind="performance",
                detail=PerformanceDocumentationDetail(
                    truth_source=TruthSource.SOURCE,
                    evidence_path=documentation_path,
                    status=DocumentationStatus.CURRENT,
                    content_sha256=validation.content_sha256,
                    validation_status=validation.status,
                    validation_summary=validation.summary,
                    fact_evidence_paths=validation.evidence_paths,
                ),
            )
        if documentation_path.name == "security_maintenance.md":
            return DocumentationRecord(
                header=header,
                kind="security",
                detail=SecurityDocumentationDetail(
                    truth_source=TruthSource.SOURCE,
                    evidence_path=documentation_path,
                    status=DocumentationStatus.CURRENT,
                    content_sha256=validation.content_sha256,
                    validation_status=validation.status,
                    validation_summary=validation.summary,
                    fact_evidence_paths=validation.evidence_paths,
                ),
            )
        if "/10_maintenance/" in topic:
            return DocumentationRecord(
                header=header,
                kind="operations",
                detail=OperationsDocumentationDetail(
                    truth_source=TruthSource.SOURCE,
                    evidence_path=documentation_path,
                    status=DocumentationStatus.CURRENT,
                    content_sha256=validation.content_sha256,
                    validation_status=validation.status,
                    validation_summary=validation.summary,
                    fact_evidence_paths=validation.evidence_paths,
                ),
            )
        return DocumentationRecord(
            header=header,
            kind="architecture",
            detail=ArchitectureDocumentationDetail(
                truth_source=TruthSource.SOURCE,
                evidence_path=documentation_path,
                status=DocumentationStatus.CURRENT,
                content_sha256=validation.content_sha256,
                validation_status=validation.status,
                validation_summary=validation.summary,
                fact_evidence_paths=validation.evidence_paths,
            ),
        )
