"""
管理员任务应用用例单元测试模块。
"""

from __future__ import annotations

from http import HTTPStatus

import pytest
from pydantic import BaseModel, ConfigDict

from src.application.admin.dispatch_admin_task_usecase import (
    AdminTaskDispatchCommand,
    DispatchAdminTaskUsecase,
)
from src.application.admin.get_admin_task_execution_record_usecase import (
    GetAdminTaskExecutionRecordUsecase,
)
from src.application.admin.list_admin_task_execution_records_usecase import (
    AdminTaskExecutionRecordListQuery,
    ListAdminTaskExecutionRecordsUsecase,
)
from src.application.admin.list_admin_task_registrations_usecase import (
    ListAdminTaskRegistrationsUsecase,
)
from src.application.admin.read_admin_task_runtime_usecase import (
    ReadAdminTaskRuntimeUsecase,
)
from src.application.ports.task_runtime_port import TaskRegistrationRuntimeSnapshot
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.message_bus_contract import (
    MessageBusBackend,
    TaskMessageEnvelope,
)
from src.core.task_contract.task_dispatcher_contract import TaskDispatchResultPayload
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

TEST_RECORD_ID = "record-admin-task-unit-1"
TEST_TASK_ID = "task-admin-task-unit-1"
MISSING_TASK_ID = "missing-admin-task-unit-1"
TEST_JOB_KIND = "demo_task"
TEST_DEDUPLICATION_KEY = "dedup-admin-task-unit-1"
TEST_QUEUE_NAME = "local"
TEST_REQUEST_ID = "request-admin-task-unit-1"
TEST_TRACE_ID = "trace-admin-task-unit-1"
TEST_CREATED_AT_EPOCH = 1700000000
TEST_FINISHED_AT_EPOCH = 1700000001
TEST_RETRY_LIMIT = 1
TEST_PAYLOAD_KIND = "demo_task"
TEST_SCHEMA_VERSION = "1.0"
TEST_PAYLOAD_JSON = '{"kind":"demo_task","schema_version":"1.0"}'


class AdminTaskUnitPayload(BaseModel):
    """
    管理员任务单元测试载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: str
    schema_version: str


class AdminTaskRuntimePortStub:
    """
    管理员任务运行时端口测试替身。
    """

    def __init__(self) -> None:
        """
        初始化测试替身。
        """

        self.list_query: AdminTaskExecutionRecordListQuery | None = None
        self.validated_job_kind: str | None = None

    def get_enabled_task_registration(self, job_kind: str) -> TaskRegistrationEnvelope:
        """
        读取启用任务注册。
        """

        _ = job_kind
        return self._build_registration()

    def get_current_task_backend(self) -> TaskBackend:
        """
        读取当前任务后端。
        """

        return TaskBackend.LOCAL

    def get_current_configured_transport_backend(self) -> MessageBackend:
        """
        读取当前消息配置后端。
        """

        return MessageBackend.LOCAL

    def get_current_transport_backend(self) -> MessageBusBackend:
        """
        读取当前消息总线后端。
        """

        return MessageBusBackend.LOCAL

    def get_current_task_runtime_mode(self) -> TaskRuntimeMode:
        """
        读取当前任务运行时模式。
        """

        return TaskRuntimeMode.LOCAL_INLINE

    def is_task_worker_enabled(self) -> bool:
        """
        读取当前节点任务工作器开关。
        """

        return True

    def is_local_inline_execute_enabled(self) -> bool:
        """
        读取当前本地任务内联执行开关。
        """

        return True

    def get_enabled_task_registration_for_backend(
        self,
        job_kind: str,
        *,
        backend: TaskBackend,
    ) -> TaskRegistrationEnvelope:
        """
        按后端读取启用任务注册。
        """

        _ = job_kind
        _ = backend
        return self._build_registration()

    def get_default_job_kind(self) -> str:
        """
        读取默认任务类型。
        """

        return TEST_JOB_KIND

    def get_default_retry_limit(self) -> int:
        """
        读取默认重试次数。
        """

        return TEST_RETRY_LIMIT

    def dispatch_task_message(
        self,
        task_message: TaskMessageEnvelope,
    ) -> TaskDispatchResultPayload:
        """
        分发任务消息。
        """

        _ = task_message
        return self._build_dispatch_result()

    def get_task_execution_record(
        self,
        task_id: str,
    ) -> TaskExecutionRecordEnvelope | None:
        """
        读取任务执行记录。
        """

        if task_id == TEST_TASK_ID:
            return self._build_execution_record()
        return None

    def list_task_execution_records(
        self,
        *,
        limit: int,
        status: TaskExecutionStatus | None = None,
        job_kind: str | None = None,
    ) -> list[TaskExecutionRecordEnvelope]:
        """
        查询任务执行记录。
        """

        self.list_query = AdminTaskExecutionRecordListQuery(
            status=status,
            job_kind=job_kind,
            limit=limit,
        )
        return [self._build_execution_record()]

    def list_task_registration_snapshots(self) -> list[TaskRegistrationRuntimeSnapshot]:
        """
        读取任务注册运行时快照。
        """

        return [
            TaskRegistrationRuntimeSnapshot(
                registration=self._build_registration(),
                handler_bound=True,
                payload_model_name=AdminTaskUnitPayload.__name__,
                registration_backend=TaskBackend.LOCAL,
                current_runtime_backend=TaskBackend.LOCAL,
                active_for_current_runtime=True,
            )
        ]

    def validate_task_payload_json(
        self,
        *,
        job_kind: str,
        payload_json: str,
    ) -> BaseModel:
        """
        校验任务载荷 JSON。
        """

        self.validated_job_kind = job_kind
        return AdminTaskUnitPayload.model_validate_json(payload_json)

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
        构建任务注册。
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

    def _build_dispatch_result(self) -> TaskDispatchResultPayload:
        """
        构建任务派发结果。
        """

        return TaskDispatchResultPayload(
            task_id=TEST_TASK_ID,
            job_kind=TEST_JOB_KIND,
            dispatched=True,
            retry_limit=TEST_RETRY_LIMIT,
            backend=TaskBackend.LOCAL,
            queue_name=TEST_QUEUE_NAME,
            published=True,
            worker_enabled=False,
            inline_execute_enabled=True,
            execution_status=TaskExecutionStatus.SUCCESS,
            execution_stage=TaskExecutionStage.LOCAL_EXECUTION,
        )


class DispatchBackgroundJobUsecaseStub:
    """
    后台任务派发用例测试替身。
    """

    def __init__(self) -> None:
        """
        初始化测试替身。
        """

        self.command_job_kind: str | None = None

    def execute(self, command) -> TaskDispatchResultPayload:
        """
        执行任务派发。
        """

        self.command_job_kind = command.job_kind
        return TaskDispatchResultPayload(
            task_id=TEST_TASK_ID,
            job_kind=command.job_kind,
            dispatched=True,
            retry_limit=command.retry_limit or TEST_RETRY_LIMIT,
            backend=TaskBackend.LOCAL,
            queue_name=TEST_QUEUE_NAME,
            published=True,
            worker_enabled=False,
            inline_execute_enabled=True,
            execution_status=TaskExecutionStatus.SUCCESS,
            execution_stage=TaskExecutionStage.LOCAL_EXECUTION,
        )


class TestAdminTaskUsecaseUnit:
    """
    管理员任务应用用例单元测试集合。
    """

    def test_list_execution_records_should_pass_filters(self) -> None:
        """
        验证任务列表用例会传递过滤条件。
        """

        port = AdminTaskRuntimePortStub()
        records = ListAdminTaskExecutionRecordsUsecase(task_runtime_port=port).execute(
            AdminTaskExecutionRecordListQuery(
                status=TaskExecutionStatus.SUCCESS,
                job_kind=TEST_JOB_KIND,
                limit=TEST_RETRY_LIMIT,
            )
        )

        assert len(records) == 1
        assert port.list_query is not None
        assert port.list_query.status == TaskExecutionStatus.SUCCESS
        assert port.list_query.job_kind == TEST_JOB_KIND

    def test_get_execution_record_should_raise_not_found(self) -> None:
        """
        验证任务详情用例在记录不存在时返回 404。
        """

        with pytest.raises(HttpFaultException) as exc_info:
            GetAdminTaskExecutionRecordUsecase(
                task_runtime_port=AdminTaskRuntimePortStub()
            ).execute(task_id=MISSING_TASK_ID)

        assert exc_info.value.status_code == HTTPStatus.NOT_FOUND

    def test_runtime_and_registration_usecase_should_return_runtime_values(self) -> None:
        """
        验证运行时与注册列表用例会返回端口数据。
        """

        port = AdminTaskRuntimePortStub()
        runtime = ReadAdminTaskRuntimeUsecase(task_runtime_port=port).execute()
        registrations = ListAdminTaskRegistrationsUsecase(task_runtime_port=port).execute()

        assert runtime.task_runtime_mode == TaskRuntimeMode.LOCAL_INLINE
        assert runtime.task_backend == TaskBackend.LOCAL
        assert runtime.configured_transport_backend == MessageBackend.LOCAL
        assert runtime.transport_backend == MessageBusBackend.LOCAL
        assert runtime.worker_enabled is True
        assert runtime.inline_execute_enabled is True
        assert runtime.default_job_kind == TEST_JOB_KIND
        assert registrations[0].handler_bound is True
        assert registrations[0].active_for_current_runtime is True

    def test_dispatch_usecase_should_validate_payload_before_dispatch(self) -> None:
        """
        验证任务派发用例先校验载荷再派发。
        """

        port = AdminTaskRuntimePortStub()
        dispatcher = DispatchBackgroundJobUsecaseStub()
        result = DispatchAdminTaskUsecase(
            task_runtime_port=port,
            dispatch_background_job_usecase=dispatcher,
        ).execute(
            AdminTaskDispatchCommand(
                job_kind=TEST_JOB_KIND,
                payload_json=TEST_PAYLOAD_JSON,
                retry_limit=TEST_RETRY_LIMIT,
                deduplication_key=TEST_DEDUPLICATION_KEY,
                request_id=TEST_REQUEST_ID,
                trace_id=TEST_TRACE_ID,
            )
        )

        assert port.validated_job_kind == TEST_JOB_KIND
        assert dispatcher.command_job_kind == TEST_JOB_KIND
        assert result.task_id == TEST_TASK_ID
