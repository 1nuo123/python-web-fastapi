"""
管理员任务 HTTP 契约测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.endpoint_admin_task.contract_admin_task import (
    ADMIN_TASK_DISPATCH_KIND,
    ADMIN_TASK_SCHEMA_VERSION,
    AdminTaskDispatchDetail,
    AdminTaskDispatchEnvelope,
    AdminTaskExecutionRecordPayload,
    AdminTaskHeader,
    AdminTaskOperationName,
    AdminTaskPayloadKind,
    AdminTaskRegistrationPayload,
    AdminTaskRuntimePayload,
)
from src.application.admin.read_admin_task_runtime_usecase import (
    AdminTaskRuntimeResult,
)
from src.application.ports.task_runtime_port import TaskRegistrationRuntimeSnapshot
from src.core.task_contract.message_bus_contract import MessageBusBackend
from src.core.task_contract.task_execution_record_contract import (
    TaskExecutionRecordDetailKind,
    TaskExecutionRecordEnvelope,
    TaskExecutionRecordHeader,
    TaskExecutionStage,
    TaskExecutionStatus,
    TaskExecutionSuccessDetail,
)
from src.core.task_contract.task_registration_contract import (
    LocalTaskRegistrationDetail,
    TaskRegistrationEnvelope,
    TaskRegistrationHeader,
)
from src.core.task_contract.task_runtime_contract import (
    MessageBackend,
    TaskBackend,
    TaskRuntimeMode,
)

TEST_RECORD_ID = "record-admin-task-1"
TEST_TASK_ID = "task-admin-task-1"
TEST_JOB_KIND = "demo_task"
TEST_DEDUPLICATION_KEY = "dedup-admin-task-1"
TEST_QUEUE_NAME = "local"
TEST_REQUEST_ID = "request-admin-task-1"
TEST_TRACE_ID = "trace-admin-task-1"
TEST_CREATED_AT_EPOCH = 1700000000
TEST_FINISHED_AT_EPOCH = 1700000001
TEST_RETRY_LIMIT = 1
TEST_PAYLOAD_JSON = '{"kind":"demo_task","schema_version":"1.0","task_id":"demo"}'
UNKNOWN_FIELD_NAME = "unexpected"


class TestAdminTaskContract:
    """
    管理员任务 HTTP 契约测试集合。
    """

    def test_execution_record_payload_should_map_runtime_fields(self) -> None:
        """
        验证任务执行记录载荷会映射运行时字段。
        """

        payload = AdminTaskExecutionRecordPayload.from_record(self._build_execution_record())

        assert payload.task_id == TEST_TASK_ID
        assert payload.runtime.status == TaskExecutionStatus.SUCCESS
        assert payload.runtime.finished_at_epoch == TEST_FINISHED_AT_EPOCH

    def test_runtime_payload_should_keep_backend_and_defaults(self) -> None:
        """
        验证任务运行时载荷会保留后端与默认值。
        """

        payload = AdminTaskRuntimePayload.from_result(
            AdminTaskRuntimeResult(
                task_runtime_mode=TaskRuntimeMode.LOCAL_INLINE,
                task_backend=TaskBackend.LOCAL,
                configured_transport_backend=MessageBackend.LOCAL,
                transport_backend=MessageBusBackend.LOCAL,
                worker_enabled=True,
                inline_execute_enabled=True,
                default_job_kind=TEST_JOB_KIND,
                default_retry_limit=TEST_RETRY_LIMIT,
            )
        )

        assert payload.task_runtime_mode == TaskRuntimeMode.LOCAL_INLINE
        assert payload.task_backend == TaskBackend.LOCAL
        assert payload.configured_transport_backend == MessageBackend.LOCAL
        assert payload.transport_backend == MessageBusBackend.LOCAL
        assert payload.worker_enabled is True
        assert payload.inline_execute_enabled is True
        assert payload.default_job_kind == TEST_JOB_KIND
        assert payload.default_retry_limit == TEST_RETRY_LIMIT

    def test_registration_payload_should_include_handler_bound_state(self) -> None:
        """
        验证任务注册载荷会包含 handler 绑定状态。
        """

        payload = AdminTaskRegistrationPayload.from_snapshot(
            TaskRegistrationRuntimeSnapshot(
                registration=self._build_registration(),
                handler_bound=True,
                payload_model_name="DemoTaskPayload",
                registration_backend=TaskBackend.LOCAL,
                current_runtime_backend=TaskBackend.LOCAL,
                active_for_current_runtime=True,
            )
        )

        assert payload.job_kind == TEST_JOB_KIND
        assert payload.enabled is True
        assert payload.registration_backend == TaskBackend.LOCAL
        assert payload.current_runtime_backend == TaskBackend.LOCAL
        assert payload.active_for_current_runtime is True
        assert payload.handler_bound is True
        assert payload.retry_limit == TEST_RETRY_LIMIT

    def test_dispatch_envelope_should_reject_unknown_field(self) -> None:
        """
        验证任务派发信封拒绝未知字段。
        """

        with pytest.raises(ValidationError):
            AdminTaskDispatchEnvelope.model_validate(
                {
                    "header": {
                        "kind": AdminTaskPayloadKind.DISPATCH.value,
                        "schema_version": ADMIN_TASK_SCHEMA_VERSION,
                        "operation_name": AdminTaskOperationName.DISPATCH.value,
                    },
                    "detail": {
                        "kind": ADMIN_TASK_DISPATCH_KIND,
                        "schema_version": ADMIN_TASK_SCHEMA_VERSION,
                        "job_kind": TEST_JOB_KIND,
                        "payload_json": TEST_PAYLOAD_JSON,
                        UNKNOWN_FIELD_NAME: True,
                    },
                }
            )

    def test_dispatch_envelope_should_validate_header_detail_kind(self) -> None:
        """
        验证任务派发信封会校验公共头与扩展字段类型一致。
        """

        with pytest.raises(ValidationError):
            AdminTaskDispatchEnvelope(
                header=AdminTaskHeader(
                    kind=AdminTaskPayloadKind.EXECUTION_LIST,
                    operation_name=AdminTaskOperationName.DISPATCH,
                ),
                detail=AdminTaskDispatchDetail(
                    job_kind=TEST_JOB_KIND,
                    payload_json=TEST_PAYLOAD_JSON,
                ),
            )

    def _build_execution_record(self) -> TaskExecutionRecordEnvelope:
        """
        构建任务执行记录。
        """

        return TaskExecutionRecordEnvelope(
            header=TaskExecutionRecordHeader(
                detail_kind=TaskExecutionRecordDetailKind.SUCCESS,
                record_id=TEST_RECORD_ID,
                task_id=TEST_TASK_ID,
                job_kind=TEST_JOB_KIND,
                deduplication_key=TEST_DEDUPLICATION_KEY,
                backend=TaskBackend.LOCAL,
                queue_name=TEST_QUEUE_NAME,
                request_id=TEST_REQUEST_ID,
                trace_id=TEST_TRACE_ID,
                created_at_epoch=TEST_CREATED_AT_EPOCH,
            ),
            detail=TaskExecutionSuccessDetail(
                stage=TaskExecutionStage.LOCAL_EXECUTION,
                attempt_count=TEST_RETRY_LIMIT,
                finished_at_epoch=TEST_FINISHED_AT_EPOCH,
            ),
        )

    def _build_registration(self) -> TaskRegistrationEnvelope:
        """
        构建任务注册信封。
        """

        return TaskRegistrationEnvelope(
            header=TaskRegistrationHeader(
                task_name=TEST_JOB_KIND,
                job_kind=TEST_JOB_KIND,
                enabled=True,
                backend=TaskBackend.LOCAL,
            ),
            detail=LocalTaskRegistrationDetail(retry_limit=TEST_RETRY_LIMIT),
        )
