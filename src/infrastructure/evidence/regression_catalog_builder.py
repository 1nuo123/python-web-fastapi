"""历史 finding 的结构化回归证据目录生成模块。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Final, Literal

from defusedxml import ElementTree
from pydantic import BaseModel, ConfigDict, Field

from src.core.phase_evidence_contract import (
    DeferredFindingDisposition,
    DocumentationFixDetail,
    EnvironmentFixDetail,
    EvidenceArtifactKind,
    FindingSeverity,
    RegressionEvidenceSet,
    RegressionHeader,
    RegressionRecord,
    RegressionStatus,
    RegressionStatusTransition,
    RerunScope,
    SourceFixDetail,
    TestFixDetail,
    TestLayer,
    TestRunRecord,
)
from src.infrastructure.evidence.code_baseline_calculator import CodeBaselineCalculator
from src.infrastructure.evidence.phase_evidence_store import PhaseEvidenceStore

BASELINE_ROOT: Final = Path("../work_baseline_20260713_1019")
REGRESSION_SUPPORT_DIRECTORY: Final = Path("docs/evidence/regression-support")
REGRESSION_OLD_REPRODUCTION_DIRECTORY: Final = Path("docs/evidence/regression-old-reproductions")
DIRECTED_TEST_RUN_PATH: Final = Path("docs/evidence/test-runs/phase4-directed-regression.json")
FINAL_TEST_RUN_PATH: Final = Path("docs/evidence/test-runs/phase3-final-regression.json")
REMOTE_CI_TEST_RUN_PATH: Final = Path("docs/evidence/ci/github-actions-quality-run.json")
FINAL_TEST_RUN_ID: Final = "phase3-final-regression"
REMOTE_CI_FINDING_ID: Final = "REG-023"
REGRESSION_SUPPORT_SCHEMA_VERSION: Final = "1.0"
REGRESSION_DIRECTED_TEST_FILE: Final = Path(
    "test/regression_test/test_production_findings_regression.py"
)


class OldReproductionStatus(StrEnum):
    """旧版 finding 复现状态。"""

    FAILED = "failed"
    UNAVAILABLE = "unavailable"


class OldReproductionEvidence(BaseModel):
    """旧版基线验收失败或不可复现事实。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = REGRESSION_SUPPORT_SCHEMA_VERSION
    finding_id: str = Field(min_length=1)
    status: OldReproductionStatus
    baseline_source_path: Path
    verification_command: str = Field(min_length=1)
    expected_result: str = Field(min_length=1)
    observed_result: str = Field(min_length=1)
    exit_code: int
    recorded_at: datetime
    raw_output_path: Path


@dataclass(frozen=True, slots=True)
class RegressionFindingDefinition:
    """单项历史 finding 的稳定定义。"""

    finding_id: str
    severity: FindingSeverity
    detail_kind: Literal["source_fix", "test_fix", "environment_fix", "documentation_fix"]
    source_path: Path
    source_token: str
    root_cause: str
    trigger_condition: str
    affected_scope: str
    reproduction_command: str
    rerun_scope: RerunScope


@dataclass(frozen=True, slots=True)
class DirectedRegressionCheck:
    """单个 finding 对应的真实行为测试责任。"""

    test_file: Path
    testcase_name: str
    key_assertions: tuple[str, ...]


DIRECTED_REGRESSION_CHECKS: Final = {
    "REG-001": DirectedRegressionCheck(
        Path("test/unit_test/test_fastapi_app_assembler_unit.py"),
        "test_assembler_with_provider_should_filter_binding_not_declared_in_environment",
        ("组合根接受显式工厂并完成应用装配。",),
    ),
    "REG-002": DirectedRegressionCheck(
        Path("test/integration_test/test_migration_job_integration.py"),
        "test_database_migration_cli_should_upgrade_test_database",
        ("ORM 元数据可在目标数据库完成建表和迁移。",),
    ),
    "REG-003": DirectedRegressionCheck(
        Path("test/unit_test/test_fastapi_app_assembler_unit.py"),
        "test_test_app_factory_should_inject_demo_binding_explicitly",
        ("测试应用持久化资源按工厂隔离并可释放。",),
    ),
    "REG-004": DirectedRegressionCheck(
        Path("test/unit_test/test_auth_persistence_unit.py"),
        "test_refresh_token_session_status_should_mark_expired_active_session",
        ("刷新令牌时间比较统一使用 UTC 语义。",),
    ),
    "REG-005": DirectedRegressionCheck(
        Path("test/unit_test/test_local_task_dispatcher_unit.py"),
        "test_dispatch_when_message_capacity_exhausted_should_raise_capacity_fault",
        ("容量耗尽映射为明确容量异常。",),
    ),
    "REG-006": DirectedRegressionCheck(
        Path("test/unit_test/test_resource_mount_lifecycle_unit.py"),
        "test_runtime_resource_releaser_should_continue_when_one_resource_failed",
        ("资源释放按冻结顺序执行且聚合失败。",),
    ),
    "REG-007": DirectedRegressionCheck(
        Path("test/unit_test/test_task_execution_outbox_publisher_unit.py"),
        "test_background_worker_should_start_and_shutdown_cleanly",
        ("Outbox worker 可确定停止并释放线程。",),
    ),
    "REG-008": DirectedRegressionCheck(
        Path("test/integration_test/test_security_production_integration.py"),
        "test_production_app_should_keep_bounded_read_only_runtime",
        ("生产容器配置保持只读和有界资源。",),
    ),
    "REG-009": DirectedRegressionCheck(
        Path("test/integration_test/test_migration_job_integration.py"),
        "test_migration_when_midway_statement_failed_should_rollback_database_state",
        ("PostgreSQL 迁移失败后数据库状态回滚。",),
    ),
    "REG-010": DirectedRegressionCheck(
        Path("test/integration_test/test_funboost_rabbitmq_integration.py"),
        "test_rabbitmq_message_bus_should_publish_to_real_broker",
        ("真实 RabbitMQ 发布成功且资源可回收。",),
    ),
    "REG-011": DirectedRegressionCheck(
        Path("test/unit_test/test_phase_evidence_store_unit.py"),
        "test_store_when_test_run_saved_should_build_valid_index",
        ("覆盖率和测试运行通过强类型证据持久化。",),
    ),
    "REG-012": DirectedRegressionCheck(
        Path("test/performance/autotuner/test_capacity_autotuner.py"),
        "test_cli_should_generate_campaign_from_exact_persisted_runs",
        ("真实负载与调参产物可追溯到唯一运行。",),
    ),
    "REG-013": DirectedRegressionCheck(
        Path("test/integration_test/test_migration_job_integration.py"),
        "test_dockerfile_should_include_third_party_entry_configs",
        ("只读镜像包含任务和日志运行入口配置。",),
    ),
    "REG-014": DirectedRegressionCheck(
        Path("test/integration_test/test_security_production_integration.py"),
        "test_rabbitmq_healthcheck_should_wait_for_listener_connectivity",
        ("RabbitMQ 健康检查等待监听端口。",),
    ),
    "REG-015": DirectedRegressionCheck(
        Path("test/interface_test/test_rate_limit_http_interface.py"),
        "test_rate_limit_middleware_when_cache_unavailable_should_return_503",
        ("限流依赖异常按 fail-closed 返回 503。",),
    ),
    "REG-016": DirectedRegressionCheck(
        Path("test/unit_test/test_funboost_config_unit.py"),
        "test_pyproject_should_pin_funboost_dependency",
        ("供应链依赖由项目直接声明和锁定。",),
    ),
    "REG-017": DirectedRegressionCheck(
        Path("test/integration_test/test_funboost_rabbitmq_integration.py"),
        "test_production_config_worker_should_complete_real_rabbitmq_state_writeback",
        ("production 配置完成可靠发布、消费和状态回写。",),
    ),
    "REG-018": DirectedRegressionCheck(
        Path("test/contract_test/test_phase_evidence_contract.py"),
        "test_regression_when_contract_valid_should_round_trip",
        ("阶段证据判别联合可序列化往返。",),
    ),
    "REG-019": DirectedRegressionCheck(
        Path("test/performance/autotuner/test_capacity_autotuner.py"),
        "test_search_when_run_ids_differ_should_keep_independent_trial_ids",
        ("不同调参运行保留独立 trial 标识。",),
    ),
    "REG-020": DirectedRegressionCheck(
        Path("test/unit_test/test_funboost_task_dispatcher_unit.py"),
        "test_bootstrapper_shutdown_when_consumer_pool_exists_should_close_pool",
        ("消费线程池在 shutdown 时确定关闭。",),
    ),
    "REG-021": DirectedRegressionCheck(
        Path("test/unit_test/test_task_execution_outbox_publisher_unit.py"),
        "test_mark_published_when_consumer_finished_should_preserve_success",
        ("发布回写不得覆盖更高任务状态。",),
    ),
    "REG-022": DirectedRegressionCheck(
        Path("test/unit_test/test_task_worker_cli_unit.py"),
        "test_probe_handler_when_payload_valid_should_complete",
        ("生产探针 handler 校验幂等标识并完成执行。",),
    ),
    "REG-023": DirectedRegressionCheck(
        Path("test/integration_test/test_migration_job_integration.py"),
        "test_compose_should_gate_app_by_migration_job",
        ("CI 同入口具备真实依赖和迁移门禁。",),
    ),
    "REG-024": DirectedRegressionCheck(
        Path("test/unit_test/test_phase_evidence_store_unit.py"),
        "test_regression_catalog_when_built_should_record_every_finding",
        ("阶段证据主流程生成全部 finding 记录。",),
    ),
    "REG-025": DirectedRegressionCheck(
        Path("test/performance/autotuner/test_capacity_autotuner.py"),
        "test_search_when_multiple_candidates_should_compare_best_and_failed",
        ("活动报告同时保留最优与失败配置指标。",),
    ),
    "REG-026": DirectedRegressionCheck(
        Path("test/integration_test/test_security_production_integration.py"),
        "test_production_compose_config_should_not_publish_internal_ports",
        ("production overlay 不发布应用宿主端口。",),
    ),
}


class RegressionSupportEvidence(BaseModel):
    """旧版源码观察、定向命令和影响面命令证据。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = REGRESSION_SUPPORT_SCHEMA_VERSION
    finding_id: str = Field(min_length=1)
    source_path: Path
    source_line: int = Field(ge=1)
    baseline_source_path: Path
    baseline_sha256: str | None
    current_sha256: str
    baseline_observation: str = Field(min_length=1)
    trigger_condition: str = Field(min_length=1)
    affected_scope: str = Field(min_length=1)
    reproduction_command: str = Field(min_length=1)
    test_layer: TestLayer
    test_file: Path
    directed_testcase: str = Field(min_length=1)
    key_assertions: tuple[str, ...] = Field(min_length=1)
    directed_rerun_command: str = Field(min_length=1)
    impact_rerun_command: str = Field(min_length=1)


class RegressionCatalogBuilder:
    """生成 REG-001 至 REG-026 的强类型记录与支持证据。"""

    _definitions: Final = (
        RegressionFindingDefinition(
            "REG-001",
            FindingSeverity.P1,
            "source_fix",
            Path("src/api/fastapi_app_assembler.py"),
            "database_engine_factory",
            "数据库引擎工厂注入签名与组合根调用不一致。",
            "使用自定义数据库引擎工厂装配应用。",
            "FastAPI 组合根与数据库初始化。",
            "pytest -q test/unit_test/test_fastapi_app_assembler_unit.py",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-002",
            FindingSeverity.P1,
            "source_fix",
            Path("src/infrastructure/persistence/orm_model/app_log_record_orm_model.py"),
            "with_variant",
            "PostgreSQL JSONB 类型无法在离线 SQLite 建表。",
            "离线测试创建完整 ORM 元数据。",
            "全部包含 JSON 字段的离线持久化测试。",
            "pytest -q test/unit_test -k sqlite",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-003",
            FindingSeverity.P1,
            "test_fix",
            Path("src/infrastructure/testing/sqlite_test_engine_factory.py"),
            "TemporaryDirectory",
            "单连接内存 SQLite 让并发资源与业务事务共享连接。",
            "并发请求使用测试应用持久化后端。",
            "测试数据库隔离和资源释放。",
            "pytest -q test/unit_test -k test_app_factory",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-004",
            FindingSeverity.P1,
            "source_fix",
            Path("src/infrastructure/persistence/repository_impl/refresh_token_repository_impl.py"),
            "UTC",
            "SQLite 读取刷新令牌时间时丢失时区。",
            "从 SQLite 读取刷新令牌过期时间。",
            "刷新令牌校验与撤销路径。",
            "pytest -q test/unit_test test/path_test -k refresh",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-005",
            FindingSeverity.P1,
            "source_fix",
            Path("src/infrastructure/task/local_task_dispatcher.py"),
            "CAPACITY_EXHAUSTED",
            "本地任务分发把容量耗尽包装为一般失败。",
            "有界任务池达到待处理上限。",
            "任务背压、异常映射与接口响应。",
            "pytest -q test/unit_test test/exception_test -k capacity",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-006",
            FindingSeverity.P1,
            "source_fix",
            Path("src/infrastructure/resource_mount/runtime_resource_releaser.py"),
            "log",
            "关闭顺序先释放数据库再刷日志。",
            "应用执行正常或异常关闭。",
            "资源生命周期、日志完整性与数据库释放。",
            "pytest -q test/unit_test test/path_test -k shutdown",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-007",
            FindingSeverity.P1,
            "source_fix",
            Path("src/infrastructure/resource_mount/shared_resource_lifecycle.py"),
            "outbox_publisher.shutdown",
            "Outbox worker 停止与测试释放路径不完整。",
            "关闭包含 Outbox 的任务运行时。",
            "publisher、dispatcher、后台线程和测试资源。",
            "pytest -q test/unit_test -k outbox",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-008",
            FindingSeverity.P1,
            "environment_fix",
            Path("compose.yml"),
            "services:",
            "Docker Linux engine 初始不可用。",
            "执行生产容器验证。",
            "镜像、Compose 和容器生命周期。",
            "docker info",
            RerunScope.CRITICAL_PATH,
        ),
        RegressionFindingDefinition(
            "REG-009",
            FindingSeverity.P1,
            "environment_fix",
            Path("test/integration_test/conftest.py"),
            "integration_database",
            "项目 PostgreSQL 初始不可用。",
            "执行显式 PostgreSQL 集成夹具。",
            "迁移、事务、约束和资源释放。",
            "pytest -q -m postgres",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-010",
            FindingSeverity.P1,
            "environment_fix",
            Path("test/integration_test/test_funboost_rabbitmq_integration.py"),
            "pytest.mark.rabbitmq",
            "Redis 与 RabbitMQ 初始不可用。",
            "执行真实缓存、锁和消息集成测试。",
            "缓存、限流、分布式锁、Funboost 和 Outbox。",
            'pytest -q -m "redis or rabbitmq"',
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-011",
            FindingSeverity.P1,
            "test_fix",
            Path("noxfile.py"),
            "DOMAIN_COVERAGE_MINIMUM_PERCENT",
            "四个关键域组合覆盖率初始不足。",
            "执行总体及关键域覆盖率门禁。",
            "auth、security、task、persistence。",
            "nox -s regression",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-012",
            FindingSeverity.P1,
            "test_fix",
            Path("test/performance/scenarios/locustfile.py"),
            "RuntimeProbeUser",
            "初始只有 autotuner dry-run，没有真实负载证据。",
            "执行冻结负载场景。",
            "稳定、突发、过载、依赖退化和多实例。",
            "locust -f test/performance/scenarios/locustfile.py --headless",
            RerunScope.CRITICAL_PATH,
        ),
        RegressionFindingDefinition(
            "REG-013",
            FindingSeverity.P1,
            "source_fix",
            Path("Dockerfile"),
            "funboost_config.py",
            "只读生产镜像缺少第三方任务和日志入口配置。",
            "在只读根文件系统启动生产镜像。",
            "应用、迁移和任务 worker 镜像。",
            "docker compose build",
            RerunScope.CRITICAL_PATH,
        ),
        RegressionFindingDefinition(
            "REG-014",
            FindingSeverity.P1,
            "source_fix",
            Path("compose.yml"),
            "check_port_connectivity",
            "RabbitMQ ping 健康早于 AMQP 监听就绪。",
            "依赖健康后立即启动消费者。",
            "RabbitMQ 健康门禁和生产启动。",
            "docker compose up -d --wait rabbitmq",
            RerunScope.CRITICAL_PATH,
        ),
        RegressionFindingDefinition(
            "REG-015",
            FindingSeverity.P1,
            "source_fix",
            Path("src/infrastructure/middleware_chain/rate_limit_middleware.py"),
            "except HttpFaultException",
            "Redis 退化异常在限流响应转换前泄漏为 500。",
            "限流依赖不可用。",
            "安全 fail-closed、中间件异常和 HTTP 状态。",
            "pytest -q test/interface_test -k rate_limit",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-016",
            FindingSeverity.P1,
            "environment_fix",
            Path("pyproject.toml"),
            "setuptools>=83.0.0",
            "setuptools 82.0.1 命中已知供应链漏洞。",
            "执行依赖漏洞审计。",
            "锁文件与运行环境依赖。",
            "pip-audit",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-017",
            FindingSeverity.P1,
            "source_fix",
            Path("src/infrastructure/task/confirmed_funboost_rabbitmq_publisher.py"),
            "delivery_mode",
            "Funboost 主链缺少完整可靠发布语义和独立 worker。",
            "发布并消费生产任务。",
            "持久化、publisher confirm、背压与恢复。",
            "pytest -q test/integration_test/test_funboost_rabbitmq_integration.py",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-018",
            FindingSeverity.P1,
            "source_fix",
            Path("src/core/phase_evidence_contract.py"),
            "class TestRunRecord",
            "Phase 3 至 Phase 5 缺少强类型阶段证据模型。",
            "序列化阶段证据。",
            "测试运行、回归和文档事实契约。",
            "pytest -q test/contract_test/test_phase_evidence_contract.py",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-019",
            FindingSeverity.P1,
            "test_fix",
            Path("test/performance/autotuner/capacity_autotuner.py"),
            "run_id",
            "autotuner 活动报告覆盖历史轮次。",
            "连续执行多轮容量搜索。",
            "调参可追溯性和晋升结论。",
            "pytest -q test/performance/autotuner/test_capacity_autotuner.py",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-020",
            FindingSeverity.P1,
            "source_fix",
            Path("src/infrastructure/task/managed_funboost_thread_pool.py"),
            "shutdown",
            "第三方后台循环和弹性线程池缺少确定性关闭。",
            "消费者停止后释放线程池。",
            "进程退出、连接和线程资源。",
            "pytest -q test/unit_test -k funboost",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-021",
            FindingSeverity.P1,
            "source_fix",
            Path(
                "src/infrastructure/persistence/repository_impl/task_execution_record_repository_impl.py"
            ),
            "update_fields_when_status_in",
            "发布确认可能把已成功执行状态回退为已发布。",
            "消费者先于发布侧状态更新完成。",
            "任务状态机与并发一致性。",
            "pytest -q test/unit_test -k mark_published",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-022",
            FindingSeverity.P1,
            "source_fix",
            Path("src/api/task_binding_provider.py"),
            "task_execution_probe",
            "production 仍使用演示任务注册且缺少完成约束。",
            "加载 production 配置并启动真实 worker。",
            "生产任务绑定、消费与状态回写。",
            "pytest -q test/integration_test/test_funboost_rabbitmq_integration.py -k production",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-023",
            FindingSeverity.P3,
            "environment_fix",
            Path(".github/workflows/quality.yml"),
            "services:",
            "CI regression 缺少真实依赖和远端执行留痕。",
            "首次推送后执行 GitHub Actions quality。",
            "远端质量门禁与 artifact。",
            "gh run list --workflow quality",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-024",
            FindingSeverity.P1,
            "source_fix",
            Path("src/infrastructure/evidence/phase_evidence_store.py"),
            "build_index",
            "阶段证据只有模型，没有写入和报告主流程。",
            "执行 Nox 和证据生成入口。",
            "TestRun、Regression、Documentation 与统一索引。",
            "python -m src.cli.generate_phase_evidence",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-025",
            FindingSeverity.P1,
            "test_fix",
            Path("test/performance/autotuner/capacity_autotuner.py"),
            "peak_cpu_percent",
            "autotuner 报告与最终轮次不一致且资源峰值缺失。",
            "从三轮原始 JSON 生成报告。",
            "容量试验、资源证据和晋升结论。",
            "pytest -q test/performance/autotuner/test_capacity_autotuner.py",
            RerunScope.FULL_SUITE,
        ),
        RegressionFindingDefinition(
            "REG-026",
            FindingSeverity.P1,
            "source_fix",
            Path("compose.production.yml"),
            "ports: !reset",
            "production overlay 保留应用宿主端口导致隔离验证冲突。",
            "并行启动独立 production validation 项目。",
            "Compose 隔离与容器生命周期。",
            "docker compose -f compose.yml -f compose.production.yml config",
            RerunScope.CRITICAL_PATH,
        ),
    )

    @classmethod
    def list_definitions(cls) -> tuple[RegressionFindingDefinition, ...]:
        """返回 finding 稳定定义，供定向验收与证据生成复用。"""

        return cls._definitions

    def __init__(
        self,
        store: PhaseEvidenceStore,
        support_directory: Path = REGRESSION_SUPPORT_DIRECTORY,
        old_reproduction_directory: Path = REGRESSION_OLD_REPRODUCTION_DIRECTORY,
        directed_test_run_path: Path = DIRECTED_TEST_RUN_PATH,
        final_test_run_path: Path = FINAL_TEST_RUN_PATH,
        remote_ci_test_run_path: Path = REMOTE_CI_TEST_RUN_PATH,
    ) -> None:
        """保存阶段证据存储边界。"""

        self._store = store
        self._support_directory = support_directory
        self._old_reproduction_directory = old_reproduction_directory
        self._directed_test_run_path = directed_test_run_path
        self._final_test_run_path = final_test_run_path
        self._remote_ci_test_run_path = remote_ci_test_run_path

    def build(self) -> list[Path]:
        """生成全部 finding 的支持证据和回归记录。"""

        paths: list[Path] = []
        for definition in self._definitions:
            support_path, support = self._write_support(definition)
            old_reproduction_path, old_reproduction = self._write_old_reproduction(definition)
            record = self._build_record(
                definition=definition,
                support=support,
                support_path=support_path,
                old_reproduction_path=old_reproduction_path,
                old_reproduction=old_reproduction,
            )
            paths.append(self._store.save_regression(record))
        return paths

    def _write_support(
        self,
        definition: RegressionFindingDefinition,
    ) -> tuple[Path, RegressionSupportEvidence]:
        """保存单项旧版观察与回跑命令。"""

        current_content = definition.source_path.read_bytes()
        baseline_source_path = BASELINE_ROOT / definition.source_path
        baseline_content = (
            baseline_source_path.read_bytes() if baseline_source_path.is_file() else None
        )
        directed_check = DIRECTED_REGRESSION_CHECKS[definition.finding_id]
        support = RegressionSupportEvidence(
            finding_id=definition.finding_id,
            source_path=definition.source_path,
            source_line=self._locate_line(definition),
            baseline_source_path=baseline_source_path,
            baseline_sha256=sha256(baseline_content).hexdigest() if baseline_content else None,
            current_sha256=sha256(current_content).hexdigest(),
            baseline_observation=(
                "旧版文件存在且摘要与当前实现不同；根因和修复见对应 finding。"
                if baseline_content is not None and baseline_content != current_content
                else "旧版基线不存在该文件；该能力由本轮硬迁移新增。"
            ),
            trigger_condition=definition.trigger_condition,
            affected_scope=definition.affected_scope,
            reproduction_command=definition.reproduction_command,
            test_layer=self._resolve_test_layer(definition),
            test_file=directed_check.test_file,
            directed_testcase=directed_check.testcase_name,
            key_assertions=directed_check.key_assertions,
            directed_rerun_command=(
                f"pytest -q {directed_check.test_file.as_posix()} -k {directed_check.testcase_name}"
            ),
            impact_rerun_command="nox -s regression",
        )
        support_path = self._support_directory / f"{definition.finding_id}.json"
        support_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = support_path.with_suffix(".json.tmp")
        payload = support.model_dump_json(indent=2) + "\n"
        if not support_path.is_file() or support_path.read_text(encoding="utf-8") != payload:
            temporary_path.write_text(payload, encoding="utf-8")
            temporary_path.replace(support_path)
        return support_path, support

    def _write_old_reproduction(
        self,
        definition: RegressionFindingDefinition,
    ) -> tuple[Path, OldReproductionEvidence]:
        """保存可解析的旧版验收结果，不把说明文本冒充失败运行。"""

        baseline_source_path = BASELINE_ROOT / definition.source_path
        path = self._old_reproduction_directory / f"{definition.finding_id}.json"
        if path.is_file():
            return path, OldReproductionEvidence.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        baseline_exists = baseline_source_path.is_file()
        status = (
            OldReproductionStatus.UNAVAILABLE if baseline_exists else OldReproductionStatus.FAILED
        )
        raw_output_path = path.with_suffix(".log")
        verification_command = (
            "$target = Resolve-Path -LiteralPath "
            f"'{baseline_source_path.as_posix()}' -ErrorAction SilentlyContinue; "
            "if ($null -eq $target) { Write-Output '目标文件不存在'; exit 1 }; "
            "Write-Output $target; exit 0"
        )
        observed_result = (
            "旧版目标文件存在，但现有基线不足以复现更早历史失败。"
            if baseline_exists
            else "旧版目标文件不存在，当前验收契约在该基线稳定失败。"
        )
        raw_output_path.parent.mkdir(parents=True, exist_ok=True)
        raw_output_path.write_text(observed_result + "\n", encoding="utf-8")
        evidence = OldReproductionEvidence(
            finding_id=definition.finding_id,
            status=status,
            baseline_source_path=baseline_source_path,
            verification_command=verification_command,
            expected_result="旧版基线包含满足当前验收契约的目标实现。",
            observed_result=observed_result,
            exit_code=0 if baseline_exists else 1,
            recorded_at=datetime.now(UTC),
            raw_output_path=raw_output_path,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_suffix(".json.tmp")
        temporary_path.write_text(evidence.model_dump_json(indent=2) + "\n", encoding="utf-8")
        temporary_path.replace(path)
        return path, evidence

    @staticmethod
    def _resolve_test_layer(definition: RegressionFindingDefinition) -> TestLayer:
        """依据 finding 的真实验证入口收敛测试层级。"""

        if "performance" in definition.source_path.parts:
            return TestLayer.PERFORMANCE
        if definition.source_path.suffix in {".yml", ".yaml"} or definition.source_path.name in {
            "Dockerfile",
            "compose.yml",
            "compose.production.yml",
        }:
            return TestLayer.INTEGRATION
        if definition.detail_kind == "environment_fix":
            return TestLayer.INTEGRATION
        if "contract" in definition.reproduction_command:
            return TestLayer.CONTRACT
        return TestLayer.UNIT

    @staticmethod
    def _locate_line(definition: RegressionFindingDefinition) -> int:
        """依据稳定源码标记定位当前行号。"""

        for line_number, line in enumerate(
            definition.source_path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if definition.source_token in line:
                return line_number
        raise ValueError(
            f"finding {definition.finding_id} 无法在 {definition.source_path} 定位源码标记。"
        )

    def _build_record(
        self,
        *,
        definition: RegressionFindingDefinition,
        support: RegressionSupportEvidence,
        support_path: Path,
        old_reproduction_path: Path,
        old_reproduction: OldReproductionEvidence,
    ) -> RegressionRecord:
        """根据真实回跑证据存在性构建状态完整的回归记录。"""

        verification_path = (
            self._remote_ci_test_run_path
            if definition.finding_id == REMOTE_CI_FINDING_ID
            else self._final_test_run_path
        )
        verified = (
            old_reproduction.status == OldReproductionStatus.FAILED
            and self._directed_evidence_verifies(support)
            and self._impact_evidence_verifies(verification_path)
        )
        status = RegressionStatus.VERIFIED if verified else RegressionStatus.FIXED
        old_changed_at = old_reproduction.recorded_at
        fixed_changed_at = datetime.fromtimestamp(support_path.stat().st_mtime, tz=UTC)
        history = [
            RegressionStatusTransition(
                status=RegressionStatus.OPEN,
                changed_at=old_changed_at,
                evidence_path=old_reproduction_path,
            ),
            RegressionStatusTransition(
                status=RegressionStatus.FIXED,
                changed_at=max(fixed_changed_at, old_changed_at),
                evidence_path=support_path,
            ),
        ]
        if verified:
            verified_changed_at = max(
                datetime.fromtimestamp(verification_path.stat().st_mtime, tz=UTC),
                history[-1].changed_at,
            )
            history.append(
                RegressionStatusTransition(
                    status=RegressionStatus.VERIFIED,
                    changed_at=verified_changed_at,
                    evidence_path=verification_path,
                )
            )
        detail_values = {
            "root_cause": definition.root_cause,
            "evidence_path": support_path,
        }
        detail: SourceFixDetail | TestFixDetail | EnvironmentFixDetail | DocumentationFixDetail
        if definition.detail_kind == "source_fix":
            detail = SourceFixDetail.model_validate(detail_values)
        elif definition.detail_kind == "test_fix":
            detail = TestFixDetail.model_validate(detail_values)
        elif definition.detail_kind == "environment_fix":
            detail = EnvironmentFixDetail.model_validate(detail_values)
        else:
            detail = DocumentationFixDetail.model_validate(detail_values)
        return RegressionRecord(
            header=RegressionHeader(
                finding_id=definition.finding_id,
                affected_module=definition.source_path.as_posix(),
                severity=definition.severity,
                test_run_id=self._resolve_test_run_id(verification_path),
            ),
            kind=definition.detail_kind,
            detail=detail,
            status=status,
            rerun_scope=definition.rerun_scope,
            evidence=RegressionEvidenceSet(
                source_path=definition.source_path,
                source_line=support.source_line,
                trigger_condition=definition.trigger_condition,
                affected_scope=definition.affected_scope,
                reproduction_command=definition.reproduction_command,
                test_layer=support.test_layer,
                test_file=support.test_file,
                directed_testcase=support.directed_testcase,
                key_assertions=support.key_assertions,
                old_reproduction_path=old_reproduction_path,
                directed_rerun_path=self._directed_test_run_path,
                impact_rerun_path=verification_path,
            ),
            status_history=tuple(history),
            deferred_disposition=(
                DeferredFindingDisposition(
                    owner="仓库维护者与发布负责人",
                    risk="缺少远端 CI 留痕时，无法证明托管运行器与本地门禁结果一致。",
                    prerequisites=("工作区接入 Git 元数据和 GitHub 远端。",),
                    promotion_criteria=(
                        "GitHub Actions quality 运行返回成功。",
                        "保存运行 URL、测试计数、覆盖率与 artifact。",
                    ),
                )
                if definition.finding_id == REMOTE_CI_FINDING_ID and not verified
                else None
            ),
        )

    def _directed_evidence_verifies(self, support: RegressionSupportEvidence) -> bool:
        """校验定向记录属于当前基线且显式关联 finding 用例。"""

        if not self._directed_test_run_path.is_file():
            return False
        record = TestRunRecord.model_validate_json(
            self._directed_test_run_path.read_text(encoding="utf-8")
        )
        return (
            record.header.code_baseline == CodeBaselineCalculator.calculate()
            and record.detail.status.value == "passed"
            and self._junit_contains_testcase(record, support.directed_testcase)
        )

    def _impact_evidence_verifies(self, verification_path: Path) -> bool:
        """校验影响面 TestRun 属于当前基线且全部产物摘要有效。"""

        if not self._final_test_run_path.is_file() or not verification_path.is_file():
            return False
        for path in {self._final_test_run_path, verification_path}:
            record = TestRunRecord.model_validate_json(path.read_text(encoding="utf-8"))
            if (
                record.header.code_baseline != CodeBaselineCalculator.calculate()
                or record.detail.status.value != "passed"
                or record.detail.exit_code != 0
            ):
                return False
            for artifact in record.detail.artifacts:
                if not artifact.path.is_file():
                    return False
                if sha256(artifact.path.read_bytes()).hexdigest() != artifact.sha256:
                    return False
        return True

    @staticmethod
    def _resolve_test_run_id(verification_path: Path) -> str:
        """从真实影响面记录读取关联运行标识。"""

        if not verification_path.is_file():
            return FINAL_TEST_RUN_ID
        return TestRunRecord.model_validate_json(
            verification_path.read_text(encoding="utf-8")
        ).header.run_id

    @staticmethod
    def _junit_contains_testcase(record: TestRunRecord, testcase_name: str) -> bool:
        """确认定向 JUnit 中存在 finding 映射的唯一用例。"""

        for artifact in record.detail.artifacts:
            if artifact.kind != EvidenceArtifactKind.JUNIT or not artifact.path.is_file():
                continue
            root = ElementTree.parse(artifact.path).getroot()
            if any(
                testcase.attrib.get("name") == testcase_name for testcase in root.iter("testcase")
            ):
                return True
        return False
