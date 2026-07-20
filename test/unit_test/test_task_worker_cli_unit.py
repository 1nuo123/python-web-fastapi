"""生产任务 worker 入口单元测试。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest

from src.api.task_binding_provider import (
    TASK_EXECUTION_PROBE_JOB_KIND,
    ApplicationTaskBindingProvider,
)
from src.application.task.task_execution_probe_handler import TaskExecutionProbePayload
from src.cli import run_task_worker
from src.core.task_contract.message_bus_contract import (
    TaskMessageEnvelope,
    TaskMessageHeader,
    TaskMessagePayload,
)
from src.core.task_contract.task_invocation_contract import (
    TaskInvocationBinding,
    TypedTaskInvocation,
)

TASK_WORKER_TEST_TASK_ID = "worker-test-task"
TASK_WORKER_TEST_MESSAGE_ID = "worker-test-message"
TASK_WORKER_TEST_CREATED_AT_EPOCH = 1
TASK_WORKER_TEST_RETRY_LIMIT = 1
TASK_WORKER_MISMATCHED_DEDUPLICATION_KEY = "worker-test-mismatched-deduplication"


class StubTaskWorkerResourceMount:
    """记录 worker 资源启动与释放。"""

    def __init__(self) -> None:
        """初始化调用状态。"""

        self.started = False
        self.closed = False

    def startup(self) -> None:
        """记录启动调用。"""

        self.started = True

    def shutdown(self) -> None:
        """记录释放调用。"""

        self.closed = True


@dataclass(slots=True)
class StubTaskWorkerContainer:
    """测试 worker 容器。"""

    resource_mount: StubTaskWorkerResourceMount


@dataclass(slots=True)
class StubTaskWorkerState:
    """测试 worker 应用状态。"""

    container: StubTaskWorkerContainer


@dataclass(slots=True)
class StubTaskWorkerApp:
    """测试 worker 应用。"""

    state: StubTaskWorkerState


class TestTaskWorkerCliUnit:
    """验证生产 worker 的绑定和资源回收边界。"""

    def test_binding_provider_should_expose_production_handler(self) -> None:
        """验证生产配置声明的任务具备强类型处理器绑定。"""

        bindings = ApplicationTaskBindingProvider().build()

        assert len(bindings) == 1
        assert bindings[0].job_kind == TASK_EXECUTION_PROBE_JOB_KIND
        assert bindings[0].payload_model is TaskExecutionProbePayload

    def test_worker_when_stop_requested_should_shutdown_resources(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证 worker 正常退出时总是释放资源。"""

        mount = StubTaskWorkerResourceMount()
        app = StubTaskWorkerApp(
            state=StubTaskWorkerState(container=StubTaskWorkerContainer(resource_mount=mount))
        )
        monkeypatch.setattr(run_task_worker, "create_app", lambda **_kwargs: app)
        monkeypatch.setattr(run_task_worker.signal, "signal", lambda *_args: None)
        worker = run_task_worker.TaskWorkerCli()
        worker._stop_event.set()  # noqa: SLF001

        exit_code = worker.run()

        assert exit_code == run_task_worker.TASK_WORKER_EXIT_SUCCESS
        assert mount.started is True
        assert mount.closed is True

    def test_probe_handler_when_payload_valid_should_complete(self) -> None:
        """验证生产任务探针载荷使用封闭强类型契约。"""

        binding = ApplicationTaskBindingProvider().build()[0]
        payload = TaskExecutionProbePayload(probe_id=TASK_WORKER_TEST_TASK_ID)
        invocation = binding.payload_model.model_validate(payload.model_dump())

        assert cast(TaskExecutionProbePayload, invocation).probe_id == TASK_WORKER_TEST_TASK_ID

    def test_probe_handler_when_probe_matches_deduplication_should_complete(self) -> None:
        """验证生产探针处理器接受与幂等键一致的强类型载荷。"""

        invocation = self._build_probe_invocation(deduplication_key=TASK_WORKER_TEST_TASK_ID)

        invocation.binding.handler.handle(invocation)

    def test_probe_handler_when_probe_mismatches_deduplication_should_reject(self) -> None:
        """验证生产探针处理器拒绝与幂等键不一致的载荷。"""

        invocation = self._build_probe_invocation(
            deduplication_key=TASK_WORKER_MISMATCHED_DEDUPLICATION_KEY
        )

        with pytest.raises(ValueError, match="幂等键"):
            invocation.binding.handler.handle(invocation)

    @staticmethod
    def _build_probe_invocation(
        *,
        deduplication_key: str,
    ) -> TypedTaskInvocation[TaskExecutionProbePayload]:
        """构建生产探针处理器调用对象。"""

        binding = ApplicationTaskBindingProvider().build()[0]
        handler = cast(
            TaskInvocationBinding[TaskExecutionProbePayload],
            TaskInvocationBinding(
                job_kind=binding.job_kind,
                payload_model=TaskExecutionProbePayload,
                handler=binding.handler,
            ),
        )
        payload = TaskExecutionProbePayload(probe_id=TASK_WORKER_TEST_TASK_ID)
        return TypedTaskInvocation(
            payload=payload,
            message=TaskMessageEnvelope(
                header=TaskMessageHeader(
                    message_id=TASK_WORKER_TEST_MESSAGE_ID,
                    created_at_epoch=TASK_WORKER_TEST_CREATED_AT_EPOCH,
                ),
                payload=TaskMessagePayload(
                    job_kind=TASK_EXECUTION_PROBE_JOB_KIND,
                    deduplication_key=deduplication_key,
                    retry_limit=TASK_WORKER_TEST_RETRY_LIMIT,
                    payload_kind=TaskExecutionProbePayload.__name__,
                    payload_json=payload.model_dump_json(),
                ),
            ),
            binding=handler,
        )
