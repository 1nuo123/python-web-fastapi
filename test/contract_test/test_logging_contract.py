"""
测试日志契约测试模块。
"""

from __future__ import annotations

import pytest

from src.core.http_contract.runtime_resource_contract import RuntimeResourceStatus
from src.core.logging_contract.log_event_contract import (
    AccessLogDetail,
    ExceptionLogDetail,
    LogDetailUnion,
    LogEventEnvelope,
    LogEventHeader,
    LogEventKind,
    LogLevel,
    ResourceLifecycleAction,
    ResourceLifecycleLogDetail,
    TaskFailureLogDetail,
)
from src.core.logging_contract.log_runtime_contract import (
    DatabaseLogSinkDetail,
    LoggingRuntimeSettings,
    LogSink,
)


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
