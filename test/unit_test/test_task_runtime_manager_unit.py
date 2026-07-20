"""
任务运行时管理器单元测试模块。
"""

from __future__ import annotations

import importlib
import logging
import os

from src.core.task_contract.message_bus_contract import (
    MessageBus,
    MessageBusBackend,
    MessagePublishResult,
    TaskMessageEnvelope,
)
from src.core.task_contract.task_runtime_contract import TaskBackend
from src.infrastructure.settings.app_settings_loader import (
    AppSettingsLoader,
)
from src.infrastructure.settings.application_settings import (
    AppEnvironment,
)
from src.infrastructure.task.failed_task_recorder import FailedTaskRecorder
from src.infrastructure.task.task_registration_registry import TaskRegistrationRegistry
from src.infrastructure.task.task_runtime_manager import TaskRuntimeAssembly, TaskRuntimeManager
from src.infrastructure.testing.task_execution_test_support import (
    TaskExecutionStoreTestFactory,
)

TASK_RUNTIME_MANAGER_TEST_LOGGER = logging.getLogger("test_task_runtime_manager")
LOCAL_DEMO_JOB_KIND = "demo_task"
RUNTIME_SECTION_NAME = "runtime"
TASK_SECTION_NAME = "task"
TASK_WORKER_ENABLED_FIELD = "worker_enabled"
TASK_BACKEND_DETAIL_FIELD = "backend_detail"
LOCAL_INLINE_EXECUTE_ENABLED_FIELD = "inline_execute_enabled"
EXPECTED_ENABLED_JOB_KIND_COUNT = 0
MESSAGE_ROUTED = True
LOGGING_SECTION_NAME = "logging"
LOGGING_ENTRY_PROJECT_NAME_FIELD = "entry_project_name"
LOGGING_ENTRY_LOG_PATH_FIELD = "entry_log_path"
LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE = "LOGGING_ENTRY_PROJECT_NAME"
LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE = "LOGGING_ENTRY_LOG_PATH"
TASK_RUNTIME_MANAGER_PROJECT_NAME = "task-runtime-manager-project"
TASK_RUNTIME_MANAGER_LOG_PATH = "logs/task-runtime-manager"


class StubMessageBus(MessageBus):
    """
    测试消息总线桩。
    """

    def publish(self, message: TaskMessageEnvelope) -> MessagePublishResult:
        """
        发布测试消息。

        :param message: 任务消息。
        :type message: TaskMessageEnvelope
        :returns: 消息发布结果。
        :rtype: MessagePublishResult
        """

        return MessagePublishResult.build_succeeded(
            message_id=message.header.message_id,
            routed=MESSAGE_ROUTED,
        )

    @property
    def backend(self) -> MessageBusBackend:
        """
        读取消息总线后端。

        :returns: 消息总线后端。
        :rtype: MessageBusBackend
        """

        return MessageBusBackend.LOCAL

    def close(self) -> None:
        """
        关闭测试消息总线。

        :returns: 无返回值。
        :rtype: None
        """

        return None


class TestTaskRuntimeManagerUnit:
    """
    任务运行时管理器单元测试集合。
    """

    def test_local_queued_runtime_should_allow_disabled_demo_registration(self) -> None:
        """
        验证本地排队运行时允许默认禁用的示例任务声明。
        """

        settings = AppSettingsLoader().load_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={
                RUNTIME_SECTION_NAME: {
                    TASK_SECTION_NAME: {
                        TASK_WORKER_ENABLED_FIELD: True,
                        TASK_BACKEND_DETAIL_FIELD: {
                            LOCAL_INLINE_EXECUTE_ENABLED_FIELD: False,
                        },
                    }
                }
            },
        )
        registry = TaskRegistrationRegistry(registrations=settings.modules.task.registrations)
        test_context = TaskExecutionStoreTestFactory().create()
        failed_task_recorder = FailedTaskRecorder()
        assembly: TaskRuntimeAssembly | None = None
        try:
            assembly = TaskRuntimeManager(
                failed_task_recorder=failed_task_recorder,
                failure_callback=failed_task_recorder.record,
                logger=TASK_RUNTIME_MANAGER_TEST_LOGGER,
            ).build_runtime(
                settings=settings,
                message_bus=StubMessageBus(),
                registration_registry=registry,
                task_execution_store=test_context.store,
            )
        finally:
            self._shutdown_runtime(assembly)
            test_context.close()

        assert assembly is not None
        assert assembly.bootstrap_snapshot.backend == TaskBackend.LOCAL
        assert len(assembly.bootstrap_snapshot.enabled_job_kinds) == EXPECTED_ENABLED_JOB_KIND_COUNT
        assert LOCAL_DEMO_JOB_KIND in assembly.bootstrap_snapshot.disabled_job_kinds

    def test_runtime_should_bridge_logging_entry_settings_before_building_task_runtime(
        self,
    ) -> None:
        """
        验证任务运行时构建前应桥接日志第三方入口配置。
        """

        os.environ.pop(LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE, None)
        os.environ.pop(LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE, None)
        settings = AppSettingsLoader().load_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={
                RUNTIME_SECTION_NAME: {
                    TASK_SECTION_NAME: {
                        TASK_WORKER_ENABLED_FIELD: True,
                        TASK_BACKEND_DETAIL_FIELD: {
                            LOCAL_INLINE_EXECUTE_ENABLED_FIELD: False,
                        },
                    },
                    LOGGING_SECTION_NAME: {
                        LOGGING_ENTRY_PROJECT_NAME_FIELD: (TASK_RUNTIME_MANAGER_PROJECT_NAME),
                        LOGGING_ENTRY_LOG_PATH_FIELD: TASK_RUNTIME_MANAGER_LOG_PATH,
                    },
                }
            },
        )
        registry = TaskRegistrationRegistry(registrations=settings.modules.task.registrations)
        test_context = TaskExecutionStoreTestFactory().create()
        failed_task_recorder = FailedTaskRecorder()
        assembly: TaskRuntimeAssembly | None = None
        try:
            assembly = TaskRuntimeManager(
                failed_task_recorder=failed_task_recorder,
                failure_callback=failed_task_recorder.record,
                logger=TASK_RUNTIME_MANAGER_TEST_LOGGER,
            ).build_runtime(
                settings=settings,
                message_bus=StubMessageBus(),
                registration_registry=registry,
                task_execution_store=test_context.store,
            )

            assert (
                os.environ[LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE]
                == TASK_RUNTIME_MANAGER_PROJECT_NAME
            )
            assert (
                os.environ[LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE]
                == TASK_RUNTIME_MANAGER_LOG_PATH
            )
        finally:
            self._shutdown_runtime(assembly)
            os.environ.pop(LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE, None)
            os.environ.pop(LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE, None)
            import funboost_config
            import nb_log_config

            importlib.reload(funboost_config)
            importlib.reload(nb_log_config)
            test_context.close()

    def _shutdown_runtime(self, assembly: TaskRuntimeAssembly | None) -> None:
        """释放测试构建的任务运行时后台资源。"""

        if assembly is None:
            return
        assembly.outbox_publisher.shutdown()
        assembly.dispatcher.shutdown()
