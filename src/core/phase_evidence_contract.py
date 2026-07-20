"""生产整改阶段证据契约核心模块。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.contract_header import ContractHeader

EVIDENCE_SCHEMA_VERSION: Final = "1.0"
EVIDENCE_TEXT_MINIMUM_LENGTH = 1
EVIDENCE_DURATION_MINIMUM_SECONDS = 0.0
SHA256_HEX_LENGTH: Final = 64
TEST_RUN_KINDS = (
    "static",
    "unit",
    "integration",
    "security",
    "migration",
    "image",
    "load",
)
DOCUMENTATION_KINDS = (
    "architecture",
    "api",
    "configuration",
    "migration",
    "testing",
    "security",
    "operations",
    "performance",
)


class TestRunStatus(StrEnum):
    """测试运行状态枚举。"""

    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class TestLayer(StrEnum):
    """测试层级，决定测试是否允许申请真实外部资源。"""

    UNIT = "unit"
    CONTRACT = "contract"
    BOUNDARY = "boundary"
    INTERFACE = "interface"
    INTEGRATION = "integration"
    PERFORMANCE = "performance"


class BenchmarkPromotion(StrEnum):
    """基准参数晋升状态枚举。"""

    PROMOTED = "promoted"
    REJECTED = "rejected"
    CANDIDATE = "candidate"


class FindingSeverity(StrEnum):
    """生产审查问题等级枚举。"""

    P0 = "P0"
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class RegressionStatus(StrEnum):
    """回归问题状态枚举。"""

    OPEN = "open"
    FIXED = "fixed"
    VERIFIED = "verified"
    REJECTED = "rejected"


class RerunScope(StrEnum):
    """回归测试范围枚举。"""

    FAILED = "failed"
    MODULE = "module"
    CRITICAL_PATH = "critical-path"
    FULL_SUITE = "full-suite"


class TruthSource(StrEnum):
    """文档事实来源枚举。"""

    SOURCE = "source"
    MIGRATION = "migration"
    CONFIGURATION = "configuration"
    OPENAPI = "openapi"
    TEST_REPORT = "test_report"


class DocumentationStatus(StrEnum):
    """文档状态枚举。"""

    CURRENT = "current"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class TruthValidationStatus(StrEnum):
    """文档事实校验状态枚举。"""

    VERIFIED = "verified"
    BLOCKED = "blocked"


class EvidenceArtifactKind(StrEnum):
    """阶段证据产物类型枚举。"""

    JUNIT = "junit"
    COVERAGE = "coverage"
    SECURITY_REPORT = "security_report"
    MIGRATION_REPORT = "migration_report"
    IMAGE = "image"
    LOAD_STATS = "load_stats"
    LOAD_REPORT = "load_report"
    LOG = "log"
    SNAPSHOT = "snapshot"


class CommandExecutionEvidence(BaseModel):
    """单条真实命令执行证据。

    :ivar command: 完整命令入口。
    :ivar tool_version: 执行工具版本。
    :ivar exit_code: 命令退出码。
    :ivar finding_count: 工具发现数量。
    :ivar evidence_path: 原始输出或结构化结果路径。
    """

    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    tool_version: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    exit_code: int
    finding_count: int = Field(ge=0)
    evidence_path: Path
    started_at: datetime
    finished_at: datetime
    duration_seconds: float = Field(ge=EVIDENCE_DURATION_MINIMUM_SECONDS)

    @model_validator(mode="after")
    def validate_execution_window(self) -> CommandExecutionEvidence:
        """校验命令结束时间不得早于开始时间。"""

        if self.finished_at < self.started_at:
            raise ValueError("命令结束时间不得早于开始时间。")
        return self


class EvidenceArtifact(BaseModel):
    """可复验阶段证据产物。"""

    model_config = ConfigDict(extra="forbid")

    kind: EvidenceArtifactKind
    path: Path
    sha256: str = Field(min_length=SHA256_HEX_LENGTH, max_length=SHA256_HEX_LENGTH)
    command_index: int | None = Field(default=None, ge=0)


class CoverageEvidence(BaseModel):
    """总体及关键业务域组合覆盖率证据。"""

    model_config = ConfigDict(extra="forbid")

    total_percent: float = Field(ge=0, le=100)
    auth_percent: float = Field(ge=0, le=100)
    security_percent: float = Field(ge=0, le=100)
    task_percent: float = Field(ge=0, le=100)
    persistence_percent: float = Field(ge=0, le=100)
    report_path: Path


class TestRunHeader(ContractHeader):
    """测试运行公共头。

    :ivar run_id: 唯一运行标识。
    :ivar code_baseline: 源码基线摘要。
    :ivar environment: 脱敏环境摘要。
    :ivar started_at: 运行开始时间。
    :ivar command_entry: 冻结命令入口。
    """

    schema_version: Literal["1.0"] = EVIDENCE_SCHEMA_VERSION
    run_id: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    code_baseline: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    environment: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    started_at: datetime
    command_entry: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)


class TestRunDetailBase(BaseModel):
    """测试运行扩展字段基类。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = EVIDENCE_SCHEMA_VERSION
    status: TestRunStatus
    command: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    exit_code: int | None
    test_count: int | None = Field(default=None, ge=0)
    duration_seconds: float = Field(ge=EVIDENCE_DURATION_MINIMUM_SECONDS)
    environment_summary: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    failure_summary: str | None = None
    evidence_path: Path
    commands: tuple[CommandExecutionEvidence, ...] = ()
    artifacts: tuple[EvidenceArtifact, ...] = ()
    warning_count: int = Field(default=0, ge=0)
    skipped_count: int = Field(default=0, ge=0)
    xfailed_count: int = Field(default=0, ge=0)
    coverage: CoverageEvidence | None = None

    @model_validator(mode="after")
    def validate_blocked_evidence(self) -> TestRunDetailBase:
        """校验阻断结果必须包含可复现前置条件。"""

        if self.status == TestRunStatus.BLOCKED and not self.failure_summary:
            raise ValueError("阻断测试运行必须记录可复现的前置条件。")
        if self.status == TestRunStatus.PASSED and self.exit_code != 0:
            raise ValueError("通过的测试运行退出码必须为零。")
        if self.status == TestRunStatus.PASSED and (
            self.skipped_count > 0 or self.xfailed_count > 0
        ):
            raise ValueError("通过的真实回归不得包含 skip 或 xfail。")
        return self


class StaticRunDetail(TestRunDetailBase):
    """静态检查运行扩展。"""

    kind: Literal["static"] = "static"


class UnitRunDetail(TestRunDetailBase):
    """单元测试运行扩展。"""

    kind: Literal["unit"] = "unit"


class IntegrationRunDetail(TestRunDetailBase):
    """集成测试运行扩展。"""

    kind: Literal["integration"] = "integration"


class SecurityRunDetail(TestRunDetailBase):
    """安全检查运行扩展。"""

    kind: Literal["security"] = "security"


class MigrationRunDetail(TestRunDetailBase):
    """迁移检查运行扩展。"""

    kind: Literal["migration"] = "migration"


class ImageRunDetail(TestRunDetailBase):
    """镜像检查运行扩展。"""

    kind: Literal["image"] = "image"


class LoadRunDetail(TestRunDetailBase):
    """负载检查运行扩展。"""

    kind: Literal["load"] = "load"
    promotion: BenchmarkPromotion = BenchmarkPromotion.CANDIDATE
    stable_across_runs: bool
    peak_cpu_percent: float = Field(ge=0)
    peak_memory_mebibytes: float = Field(ge=0)
    peak_thread_count: int = Field(ge=0)
    peak_connection_count: int = Field(ge=0)


TestRunDetailUnion = Annotated[
    StaticRunDetail
    | UnitRunDetail
    | IntegrationRunDetail
    | SecurityRunDetail
    | MigrationRunDetail
    | ImageRunDetail
    | LoadRunDetail,
    Field(discriminator="kind"),
]


class TestRunRecord(BaseModel):
    """测试运行证据信封。"""

    model_config = ConfigDict(extra="forbid")

    header: TestRunHeader
    kind: Literal["static", "unit", "integration", "security", "migration", "image", "load"]
    detail: TestRunDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> TestRunRecord:
        """校验测试运行外层类型、扩展类型与版本一致。"""

        if self.kind != self.detail.kind:
            raise ValueError("测试运行外层类型必须与扩展类型一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("测试运行公共头与扩展版本必须一致。")
        return self


class RegressionHeader(ContractHeader):
    """真实失败回归公共头。"""

    schema_version: Literal["1.0"] = EVIDENCE_SCHEMA_VERSION
    finding_id: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    affected_module: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    severity: FindingSeverity
    test_run_id: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)


class RegressionDetailBase(BaseModel):
    """真实失败回归扩展字段基类。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = EVIDENCE_SCHEMA_VERSION
    root_cause: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    evidence_path: Path


class RegressionEvidenceSet(BaseModel):
    """finding 从旧版复现到影响面回归的完整证据。"""

    model_config = ConfigDict(extra="forbid")

    source_path: Path
    source_line: int = Field(ge=1)
    trigger_condition: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    affected_scope: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    reproduction_command: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    test_layer: TestLayer
    test_file: Path
    directed_testcase: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    key_assertions: tuple[str, ...] = Field(min_length=1)
    old_reproduction_path: Path
    directed_rerun_path: Path
    impact_rerun_path: Path


class RegressionStatusTransition(BaseModel):
    """真实失败回归状态迁移。"""

    model_config = ConfigDict(extra="forbid")

    status: RegressionStatus
    changed_at: datetime
    evidence_path: Path


class DeferredFindingDisposition(BaseModel):
    """延期 finding 的责任与重新晋升条件。"""

    model_config = ConfigDict(extra="forbid")

    owner: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    risk: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    prerequisites: tuple[str, ...] = Field(min_length=1)
    promotion_criteria: tuple[str, ...] = Field(min_length=1)


class SourceFixDetail(RegressionDetailBase):
    """源码修复扩展。"""

    kind: Literal["source_fix"] = "source_fix"


class TestFixDetail(RegressionDetailBase):
    """测试修复扩展。"""

    kind: Literal["test_fix"] = "test_fix"


class EnvironmentFixDetail(RegressionDetailBase):
    """环境修复扩展。"""

    kind: Literal["environment_fix"] = "environment_fix"


class DocumentationFixDetail(RegressionDetailBase):
    """文档修复扩展。"""

    kind: Literal["documentation_fix"] = "documentation_fix"


RegressionDetailUnion = Annotated[
    SourceFixDetail | TestFixDetail | EnvironmentFixDetail | DocumentationFixDetail,
    Field(discriminator="kind"),
]


class RegressionRecord(BaseModel):
    """真实失败回归证据信封。"""

    model_config = ConfigDict(extra="forbid")

    header: RegressionHeader
    kind: Literal["source_fix", "test_fix", "environment_fix", "documentation_fix"]
    detail: RegressionDetailUnion
    status: RegressionStatus
    rerun_scope: RerunScope
    evidence: RegressionEvidenceSet
    status_history: tuple[RegressionStatusTransition, ...] = Field(min_length=1)
    deferred_disposition: DeferredFindingDisposition | None = None

    @model_validator(mode="after")
    def validate_detail_contract(self) -> RegressionRecord:
        """校验回归外层类型、扩展类型、版本和状态迁移证据。"""

        if self.kind != self.detail.kind:
            raise ValueError("回归记录外层类型必须与扩展类型一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("回归记录公共头与扩展版本必须一致。")
        if self.status == RegressionStatus.VERIFIED and self.rerun_scope == RerunScope.FAILED:
            raise ValueError("已验证回归必须至少完成模块级影响面回跑。")
        if self.status_history[0].status != RegressionStatus.OPEN:
            raise ValueError("回归状态历史必须从 open 开始。")
        if self.status_history[-1].status != self.status:
            raise ValueError("回归状态历史末项必须与当前状态一致。")
        observed_statuses = tuple(item.status for item in self.status_history)
        if (
            self.status == RegressionStatus.VERIFIED
            and RegressionStatus.FIXED not in observed_statuses
        ):
            raise ValueError("已验证回归必须保留 fixed 状态迁移。")
        if self.header.severity == FindingSeverity.P3 and self.status != RegressionStatus.VERIFIED:
            if self.deferred_disposition is None:
                raise ValueError("未验证的 P3 finding 必须记录负责人、风险与重新晋升条件。")
        transition_times = tuple(item.changed_at for item in self.status_history)
        if transition_times != tuple(sorted(transition_times)):
            raise ValueError("回归状态历史必须按真实发生时间递增。")
        return self


class DocumentationHeader(ContractHeader):
    """生产事实文档公共头。"""

    schema_version: Literal["1.0"] = EVIDENCE_SCHEMA_VERSION
    topic: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    applicable_version: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    code_baseline: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    verified_at: datetime


class DocumentationDetailBase(BaseModel):
    """生产事实文档扩展字段基类。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = EVIDENCE_SCHEMA_VERSION
    truth_source: TruthSource
    evidence_path: Path
    status: DocumentationStatus
    replacement_path: Path | None = None
    content_sha256: str = Field(
        min_length=SHA256_HEX_LENGTH,
        max_length=SHA256_HEX_LENGTH,
    )
    validation_status: TruthValidationStatus
    validation_summary: str = Field(min_length=EVIDENCE_TEXT_MINIMUM_LENGTH)
    fact_evidence_paths: tuple[Path, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_replacement_path(self) -> DocumentationDetailBase:
        """校验过期或归档入口必须声明替代路径。"""

        if self.status != DocumentationStatus.CURRENT and self.replacement_path is None:
            raise ValueError("过期或归档文档必须声明替代路径。")
        return self


class ArchitectureDocumentationDetail(DocumentationDetailBase):
    """架构文档扩展。"""

    kind: Literal["architecture"] = "architecture"


class ApiDocumentationDetail(DocumentationDetailBase):
    """接口文档扩展。"""

    kind: Literal["api"] = "api"


class ConfigurationDocumentationDetail(DocumentationDetailBase):
    """配置文档扩展。"""

    kind: Literal["configuration"] = "configuration"


class MigrationDocumentationDetail(DocumentationDetailBase):
    """迁移文档扩展。"""

    kind: Literal["migration"] = "migration"


class TestingDocumentationDetail(DocumentationDetailBase):
    """测试文档扩展。"""

    kind: Literal["testing"] = "testing"


class SecurityDocumentationDetail(DocumentationDetailBase):
    """安全文档扩展。"""

    kind: Literal["security"] = "security"


class OperationsDocumentationDetail(DocumentationDetailBase):
    """运维文档扩展。"""

    kind: Literal["operations"] = "operations"


class PerformanceDocumentationDetail(DocumentationDetailBase):
    """性能文档扩展。"""

    kind: Literal["performance"] = "performance"


DocumentationDetailUnion = Annotated[
    ArchitectureDocumentationDetail
    | ApiDocumentationDetail
    | ConfigurationDocumentationDetail
    | MigrationDocumentationDetail
    | TestingDocumentationDetail
    | SecurityDocumentationDetail
    | OperationsDocumentationDetail
    | PerformanceDocumentationDetail,
    Field(discriminator="kind"),
]


class DocumentationRecord(BaseModel):
    """生产事实文档证据信封。"""

    model_config = ConfigDict(extra="forbid")

    header: DocumentationHeader
    kind: Literal[
        "architecture",
        "api",
        "configuration",
        "migration",
        "testing",
        "security",
        "operations",
        "performance",
    ]
    detail: DocumentationDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> DocumentationRecord:
        """校验文档外层类型、扩展类型与版本一致。"""

        if self.kind != self.detail.kind:
            raise ValueError("文档记录外层类型必须与扩展类型一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("文档记录公共头与扩展版本必须一致。")
        return self
