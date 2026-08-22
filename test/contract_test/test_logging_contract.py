"""
测试日志契约测试模块。
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.core.codex_contract.feature_flags_contract import CodexExperienceFeatureFlags
from src.core.http_contract.runtime_resource_contract import RuntimeResourceStatus
from src.core.logging_contract.log_event_contract import (
    AUDIT_CRITICAL_SECURITY_EVENT_TYPES,
    LOG_EVENT_SCHEMA_VERSION,
    AccessLogDetail,
    CodexExperienceFeatureFlagsLogDetail,
    ExceptionLogDetail,
    LogDetailUnion,
    LogEventEnvelope,
    LogEventHeader,
    LogEventKind,
    LogLevel,
    LogPersistencePriority,
    ResourceLifecycleAction,
    ResourceLifecycleLogDetail,
    TaskFailureLogDetail,
)
from src.core.logging_contract.log_runtime_contract import (
    DatabaseLogSinkDetail,
    LoggingRuntimeSettings,
    LogSink,
)
from src.core.logging_contract.log_writer_contract import LogWriteReason
from src.core.security_contract.security_event_contract import SecurityEventType

CURRENT_LOG_SCHEMA_VERSION = "1.1"
LEGACY_LOG_SCHEMA_VERSION = "1.0"
UNKNOWN_PERSISTENCE_PRIORITY = "urgent"
PERSISTENCE_PRIORITY_FIELD = "persistence_priority"
SCHEMA_VERSION_FIELD = "schema_version"


class TestLoggingContract:
    """
    测试日志契约测试集合，用于组织同一主题下的测试场景。
    """

    def test_logging_runtime_should_validate_database_sink_contract(self) -> None:
        """
        验证日志运行时应校验数据库 sink 契约。
        """

        settings = LoggingRuntimeSettings(
            enabled=True,
            level=LogLevel.INFO,
            sink=LogSink.DATABASE,
            buffer_max_items=10,
            entry_project_name="fastapi_web_skeleton",
            entry_log_path="logs",
            sink_detail=DatabaseLogSinkDetail(
                table_name="app_log_record",
                flush_interval_seconds=2,
                max_batch_size=100,
                fallback_to_stdout=True,
                retention_days=30,
            ),
        )
        assert settings.sink == LogSink.DATABASE
        assert settings.sink_detail.kind == "database"

    def test_log_event_envelope_should_keep_header_and_detail_consistent(self) -> None:
        """
        验证日志事件信封应保持头与扩展一致。
        """

        envelope = LogEventEnvelope(
            header=LogEventHeader(
                event_id="event-1",
                occurred_at=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ),
                level=LogLevel.INFO,
                kind=LogEventKind.ACCESS,
                message="请求完成。",
                request_id="request-1",
                trace_id="trace-1",
                authenticated_subject_id="user-1",
                source_module="infrastructure",
                source_component="access_log_middleware",
            ),
            detail=AccessLogDetail(
                request_path="/health/live",
                request_method="GET",
                status_code=200,
                elapsed_milliseconds=1.0,
                client_ip="127.0.0.1",
                user_agent="pytest",
                route_name="health_live",
            ),
        )
        assert envelope.header.kind == envelope.detail.kind

    def test_log_event_envelope_when_kind_mismatch_should_fail(self) -> None:
        """
        验证日志事件信封当 kind 不一致应失败。
        """

        with pytest.raises(ValueError):
            LogEventEnvelope(
                header=LogEventHeader(
                    event_id="event-1",
                    occurred_at=__import__("datetime").datetime.now(
                        __import__("datetime").timezone.utc
                    ),
                    level=LogLevel.INFO,
                    kind=LogEventKind.ACCESS,
                    message="请求完成。",
                    request_id="request-1",
                    trace_id="trace-1",
                    authenticated_subject_id="user-1",
                    source_module="infrastructure",
                    source_component="access_log_middleware",
                ),
                detail=ExceptionLogDetail(
                    request_path="/health/live",
                    request_method="GET",
                    status_code=500,
                    error_code="system.internal.unexpected",
                    exception_type="RuntimeError",
                    detail="错误",
                    traceback_text=None,
                ),
            )

    def test_log_detail_union_should_accept_resource_lifecycle(self) -> None:
        """
        验证日志扩展联合应接受资源生命周期类型。
        """

        detail: LogDetailUnion = ResourceLifecycleLogDetail(
            resource_name="shared_database",
            lifecycle_action=ResourceLifecycleAction.STARTUP,
            resource_status=RuntimeResourceStatus.READY,
            detail=None,
        )
        assert detail.kind == "resource_lifecycle"

    def test_log_detail_union_should_accept_task_failure(self) -> None:
        """
        验证日志扩展联合应接收任务失败类型。
        """

        detail: LogDetailUnion = TaskFailureLogDetail(
            task_id="task-1",
            job_kind="demo_task",
            backend="local",
            stage="local_execution",
            retry_count=1,
            queue_name="demo_task",
            payload_kind="DemoPayload",
            detail="任务执行失败。",
        )

        assert detail.kind == "task_failure"

    def test_log_detail_union_should_accept_complete_feature_flag_decisions(self) -> None:
        """体验开关日志必须包含固定的三项发布决策。"""

        detail: LogDetailUnion = CodexExperienceFeatureFlagsLogDetail(
            decisions=CodexExperienceFeatureFlags().decisions()
        )

        assert detail.kind == "codex_experience_feature_flags"
        assert len(detail.decisions) == 3

    def test_feature_flag_log_detail_when_decisions_are_incomplete_should_fail(self) -> None:
        """缺失任何开关会让日志失去发布治理价值，必须拒绝。"""

        with pytest.raises(ValidationError):
            CodexExperienceFeatureFlagsLogDetail(
                decisions=CodexExperienceFeatureFlags().decisions()[:-1]
            )

    def test_feature_flag_log_detail_when_decisions_are_reordered_should_fail(self) -> None:
        """固定顺序避免同名开关在日志中被错误解释。"""

        with pytest.raises(ValidationError):
            CodexExperienceFeatureFlagsLogDetail(
                decisions=tuple(reversed(CodexExperienceFeatureFlags().decisions()))
            )

    def test_log_event_schema_version_should_be_upgraded_to_1_1(self) -> None:
        """
        验证日志事件契约版本已升级到 1.1。
        """

        assert LOG_EVENT_SCHEMA_VERSION == CURRENT_LOG_SCHEMA_VERSION

    def test_header_persistence_priority_should_default_to_standard(self) -> None:
        """
        验证公共头持久化优先级默认标准优先级。
        """

        header = self._build_header_payload()
        header.pop(PERSISTENCE_PRIORITY_FIELD)

        parsed_header = LogEventHeader.model_validate(header)

        assert parsed_header.persistence_priority == LogPersistencePriority.STANDARD

    def test_header_should_accept_audit_critical_priority(self) -> None:
        """
        验证公共头接受审计关键持久化优先级。
        """

        header = LogEventHeader.model_validate(self._build_header_payload())

        assert header.persistence_priority == LogPersistencePriority.AUDIT_CRITICAL

    def test_header_should_reject_unknown_persistence_priority(self) -> None:
        """
        验证公共头拒绝未知持久化优先级取值。
        """

        header = self._build_header_payload()
        header[PERSISTENCE_PRIORITY_FIELD] = UNKNOWN_PERSISTENCE_PRIORITY

        with pytest.raises(ValidationError):
            LogEventHeader.model_validate(header)

    def test_header_should_reject_legacy_schema_version(self) -> None:
        """
        验证旧版本 1.0 日志公共头反序列化被拒绝。
        """

        header = self._build_header_payload()
        header[SCHEMA_VERSION_FIELD] = LEGACY_LOG_SCHEMA_VERSION

        with pytest.raises(ValidationError):
            LogEventHeader.model_validate(header)

    def test_audit_critical_event_types_should_cover_admin_and_config_events(self) -> None:
        """
        验证审计关键事件类型集合覆盖管理员变更与安全配置拒绝。
        """

        assert SecurityEventType.ADMIN_IDENTITY_CHANGED in AUDIT_CRITICAL_SECURITY_EVENT_TYPES
        assert SecurityEventType.CONFIG_SECURITY_REJECTED in AUDIT_CRITICAL_SECURITY_EVENT_TYPES

    def test_write_reason_should_contain_audit_critical_member(self) -> None:
        """
        验证日志刷盘原因枚举包含审计关键成员。
        """

        assert LogWriteReason.AUDIT_CRITICAL.value == "audit_critical"

    def _build_header_payload(self) -> dict[str, object]:
        """
        构建审计关键日志公共头载荷。
        """

        return {
            "event_id": "event-1",
            "occurred_at": datetime.now(UTC).isoformat(),
            "level": LogLevel.INFO.value,
            "kind": LogEventKind.SECURITY.value,
            PERSISTENCE_PRIORITY_FIELD: LogPersistencePriority.AUDIT_CRITICAL.value,
            "message": "审计关键事件。",
            "source_module": "infrastructure",
            "source_component": "security_protection",
        }
