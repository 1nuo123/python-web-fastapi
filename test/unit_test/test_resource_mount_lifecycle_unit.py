"""
资源挂载生命周期单元测试模块。
"""

from __future__ import annotations

import re
from dataclasses import FrozenInstanceError, dataclass
from pathlib import Path
from re import Pattern
from typing import cast

import pytest
from fastapi import FastAPI
from pytest import MonkeyPatch

from src.api.testing.test_app_factory import TestAppFactory
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.runtime_resource_contract import RuntimeResourceStatus
from src.infrastructure.fastapi_lifespan_orchestrator import ApplicationLifespanContext
from src.infrastructure.resource_mount.runtime_resource_mount_contract import (
    HTTP_RUNTIME_ATTACHED_KIND,
    RUNTIME_ACCESSORS_REFRESHED_KIND,
    RUNTIME_RESOURCE_STATE_CHANGED_KIND,
)
from src.infrastructure.resource_mount.runtime_resource_releaser import (
    RuntimeResourceReleaser,
)
from src.infrastructure.resource_mount.shared_resource_constants import (
    RESOURCE_CACHE,
    RESOURCE_HTTP_CLIENT,
    RESOURCE_TASK,
    RESOURCE_TASK_MESSAGE_TRANSPORT,
)
from src.infrastructure.security.client_ip_resolver import (
    ClientIpResolutionKind,
)
from src.infrastructure.settings.application_settings import ApplicationSettings
from src.infrastructure.shared_resource_mount import SharedResourceMount

RESOURCE_MOUNT_HELPER_DIRECTORY = Path("src/infrastructure/resource_mount")
STARTUP_FAILURE_MESSAGE = "模拟启动失败"
SHUTDOWN_FAILURE_MESSAGE = "模拟释放失败"
RUNTIME_ERROR_NAME = "RuntimeError"
HELPER_FILENAMES = (
    "runtime_resource_bootstrapper.py",
    "runtime_resource_releaser.py",
    "runtime_accessor_refresher.py",
)
FORBIDDEN_PRIVATE_WRITE_PATTERN: Pattern[str] = re.compile(r"mount\._[A-Za-z0-9_]+\s*=")
FORBIDDEN_RUNTIME_STATE_WRITE_PATTERN: Pattern[str] = re.compile(r"mount\._runtime_states\s*\[")
FIRST_RELEASE_FAILURE_INDEX = 0
EXPECTED_SINGLE_RELEASE_FAILURE_COUNT = 1
CUSTOM_TRUSTED_PROXY_CIDR = "10.20.0.0/16"
CUSTOM_TRUSTED_PROXY_IP = "10.20.0.10"
FORWARDED_CLIENT_IP = "203.0.113.8"
RUNTIME_GENERATION_MUTATION_VALUE = -1


@dataclass(slots=True)
class FailingStartupResourceMount:
    """
    启动失败的资源挂载替身。
    """

    startup_called: bool = False
    shutdown_called: bool = False

    def startup(self) -> None:
        """
        记录启动调用并抛出启动异常。
        """

        self.startup_called = True
        raise RuntimeError(STARTUP_FAILURE_MESSAGE)

    def shutdown(self) -> None:
        """
        记录资源释放调用。
        """

        self.shutdown_called = True


@dataclass(slots=True)
class PartiallyFailingShutdownResourceMount:
    """
    部分释放失败的资源挂载替身。
    """

    task_clear_called: bool = False
    cache_clear_called: bool = False
    database_clear_called: bool = False
    logging_clear_called: bool = False

    def flush_runtime_logs(self, reason) -> None:
        """
        模拟日志刷盘。
        """

        _ = reason

    def clear_task_runtime(self) -> None:
        """
        模拟任务资源释放失败。
        """

        self.task_clear_called = True
        raise RuntimeError(SHUTDOWN_FAILURE_MESSAGE)

    def clear_cache_runtime(self) -> None:
        """
        模拟缓存资源释放。
        """

        self.cache_clear_called = True

    def clear_database_runtime(self) -> None:
        """
        模拟数据库资源释放。
        """

        self.database_clear_called = True

    def detach_http_runtime(self) -> object | None:
        """
        模拟无 HTTP 资源。
        """

        return None

    def get_task_message_transport(self) -> object:
        """
        模拟消息资源未就绪。
        """

        raise HttpFaultException(
            status_code=503,
            error_code=CoreErrorCode.RESOURCE_NOT_READY,
            message="消息资源尚未就绪。",
        )

    def clear_logging_runtime(self) -> None:
        """
        模拟日志资源释放。
        """

        self.logging_clear_called = True

    def mark_runtime_resource_stopped(self, resource_name: str) -> None:
        """
        模拟资源停止标记。
        """

        _ = resource_name

    def emit_runtime_lifecycle_log(
        self,
        *,
        resource_name: str,
        lifecycle_action,
        resource_status,
        detail_text: str | None,
    ) -> None:
        """
        模拟生命周期日志。
        """

        _ = (resource_name, lifecycle_action, resource_status, detail_text)


@dataclass(slots=True)
class FailingTaskRuntimeClearer:
    """
    任务运行时释放失败替身。
    """

    called: bool = False

    def __call__(self) -> None:
        """
        记录调用并抛出释放失败异常。
        """

        self.called = True
        raise RuntimeError(SHUTDOWN_FAILURE_MESSAGE)


@dataclass(slots=True)
class MessageBusCloseSpy:
    """
    消息总线关闭测试替身。
    """

    closed: bool = False

    def close(self) -> None:
        """
        记录关闭调用。
        """

        self.closed = True


@dataclass(slots=True)
class MessageReleaseResourceMount:
    """
    消息资源释放测试挂载替身。
    """

    message_bus: MessageBusCloseSpy
    stopped_resources: list[str]

    def get_task_message_transport(self) -> MessageBusCloseSpy:
        """
        返回消息总线测试替身。
        """

        return self.message_bus

    def mark_runtime_resource_stopped(self, resource_name: str) -> None:
        """
        记录停止资源。
        """

        self.stopped_resources.append(resource_name)

    def emit_runtime_lifecycle_log(
        self,
        *,
        resource_name: str,
        lifecycle_action,
        resource_status,
        detail_text: str | None,
    ) -> None:
        """
        模拟生命周期日志。
        """

        _ = (resource_name, lifecycle_action, resource_status, detail_text)


class TestResourceMountLifecycleUnit:
    """
    资源挂载生命周期单元测试集合。
    """

    def test_attach_http_runtime_should_update_accessor_and_state(self) -> None:
        """
        验证显式 HTTP 挂载方法应更新访问器与状态。
        """

        app = TestAppFactory().create()
        resource_mount = app.state.container.resource_mount
        settings = app.state.container.settings_holder.current_settings
        resource_set = resource_mount.build_http_resource_set(settings)

        try:
            operation = resource_mount.attach_http_runtime(resource_set)
            states = {state.resource_name: state for state in resource_mount.get_runtime_states()}

            assert operation.detail.kind == HTTP_RUNTIME_ATTACHED_KIND
            assert resource_mount.get_http_client() is resource_set.http_client
            assert states[RESOURCE_HTTP_CLIENT].status == RuntimeResourceStatus.READY
        finally:
            detached_resource_set = resource_mount.detach_http_runtime()
            if detached_resource_set is not None:
                resource_mount.close_http_resource_set(detached_resource_set)

        with pytest.raises(HttpFaultException):
            resource_mount.get_http_client()

    def test_mark_runtime_resource_state_should_update_state_contract(self) -> None:
        """
        验证显式资源状态方法应更新状态并返回强类型契约。
        """

        app = TestAppFactory().create()
        resource_mount = app.state.container.resource_mount

        operation = resource_mount.mark_runtime_resource_state(
            RESOURCE_CACHE,
            RuntimeResourceStatus.STARTING,
        )
        states = {state.resource_name: state for state in resource_mount.get_runtime_states()}

        assert operation.detail.kind == RUNTIME_RESOURCE_STATE_CHANGED_KIND
        assert operation.detail.status == RuntimeResourceStatus.STARTING
        assert states[RESOURCE_CACHE].status == RuntimeResourceStatus.STARTING

    def test_refresh_runtime_accessors_should_return_typed_operation(self) -> None:
        """
        验证显式访问器刷新方法应返回强类型操作信封。
        """

        app = TestAppFactory().create()
        resource_mount = app.state.container.resource_mount

        operation = resource_mount.refresh_runtime_accessors()

        assert operation.detail.kind == RUNTIME_ACCESSORS_REFRESHED_KIND
        assert operation.detail.auth_accessor_refreshed is True
        assert operation.detail.logging_accessor_refreshed is True
        assert resource_mount.get_log_event_builder() is not None

    def test_runtime_public_reads_should_use_single_bundle_snapshot(self) -> None:
        """
        验证运行时公开读取入口使用同一个不可变快照包。
        """

        app = TestAppFactory().create()
        resource_mount = app.state.container.resource_mount
        settings_holder = app.state.container.settings_holder
        runtime_bundle = resource_mount.read_runtime_bundle()
        original_settings = settings_holder.current_settings

        try:
            settings_holder.current_settings = cast(ApplicationSettings, object())
            settings_snapshot = resource_mount.read_application_settings_snapshot()
            task_backend = resource_mount.get_current_task_backend()
            task_registration_snapshots = resource_mount.list_task_registration_snapshots()
        finally:
            settings_holder.current_settings = original_settings

        with pytest.raises(FrozenInstanceError):
            runtime_bundle.generation = RUNTIME_GENERATION_MUTATION_VALUE

        assert settings_snapshot.application_name == runtime_bundle.settings.app.name
        assert task_backend == runtime_bundle.settings.runtime.task.backend
        assert all(
            snapshot.current_runtime_backend == runtime_bundle.settings.runtime.task.backend
            for snapshot in task_registration_snapshots
        )

    def test_security_infrastructure_should_share_configured_client_ip_resolver(
        self,
    ) -> None:
        """
        Verify the resource mount wires configured client IP policy into logs.
        """

        app = TestAppFactory().create(
            overrides={
                "runtime": {
                    "security": {
                        "detail": {
                            "protection": {
                                "client_ip": {
                                    "trusted_proxy_cidr_blocks": [CUSTOM_TRUSTED_PROXY_CIDR]
                                }
                            }
                        }
                    }
                }
            }
        )
        resource_mount = app.state.container.resource_mount
        request = self._build_request(
            client_ip=CUSTOM_TRUSTED_PROXY_IP,
            headers=[("x-forwarded-for", FORWARDED_CLIENT_IP)],
        )

        resource_mount.startup()
        try:
            resolution = resource_mount.get_client_ip_resolver().resolve(request)
            request_context = resource_mount.get_log_event_builder().build_request_context(request)
        finally:
            resource_mount.shutdown()

        assert resolution.header.source == ClientIpResolutionKind.TRUSTED_PROXY_FORWARDED
        assert resolution.detail.client_ip == FORWARDED_CLIENT_IP
        assert request_context.client_ip == FORWARDED_CLIENT_IP

    @pytest.mark.anyio
    async def test_lifespan_when_startup_failed_should_shutdown_resources(
        self,
    ) -> None:
        """
        验证启动阶段异常时生命周期上下文会释放已挂载资源并回写就绪状态。
        """

        app = FastAPI()
        app.state.ready = True
        resource_mount = FailingStartupResourceMount()
        context = ApplicationLifespanContext(
            app=app,
            resource_mount=cast(SharedResourceMount, resource_mount),
        )

        with pytest.raises(RuntimeError, match=STARTUP_FAILURE_MESSAGE):
            await context.__aenter__()

        assert resource_mount.startup_called is True
        assert resource_mount.shutdown_called is True
        assert app.state.ready is False

    def test_runtime_resource_releaser_should_continue_when_one_resource_failed(
        self,
    ) -> None:
        """
        验证释放单个资源失败时后续资源仍会继续释放。
        """

        resource_mount = PartiallyFailingShutdownResourceMount()

        release_result = RuntimeResourceReleaser().shutdown(
            cast(SharedResourceMount, resource_mount)
        )

        assert resource_mount.task_clear_called is True
        assert resource_mount.cache_clear_called is True
        assert resource_mount.database_clear_called is True
        assert resource_mount.logging_clear_called is True
        assert len(release_result.detail.failures) == EXPECTED_SINGLE_RELEASE_FAILURE_COUNT
        assert (
            release_result.detail.failures[FIRST_RELEASE_FAILURE_INDEX].resource_name
            == RESOURCE_TASK
        )
        assert (
            release_result.detail.failures[FIRST_RELEASE_FAILURE_INDEX].error_type
            == RUNTIME_ERROR_NAME
        )
        assert (
            release_result.detail.failures[FIRST_RELEASE_FAILURE_INDEX].error_message
            == SHUTDOWN_FAILURE_MESSAGE
        )

    def test_runtime_resource_releaser_should_close_message_bus(self) -> None:
        """
        验证消息资源释放会关闭消息总线并标记停止。
        """

        message_bus = MessageBusCloseSpy()
        resource_mount = MessageReleaseResourceMount(
            message_bus=message_bus,
            stopped_resources=[],
        )

        RuntimeResourceReleaser()._release_message_resource(  # noqa: SLF001
            cast(SharedResourceMount, resource_mount)
        )

        assert message_bus.closed is True
        assert RESOURCE_TASK_MESSAGE_TRANSPORT in resource_mount.stopped_resources

    def test_shared_resource_mount_shutdown_should_expose_release_failures(
        self,
        monkeypatch: MonkeyPatch,
    ) -> None:
        """
        验证共享资源挂载关闭时会返回并保存释放失败明细。
        """

        app = TestAppFactory().create()
        resource_mount = app.state.container.resource_mount
        failing_clearer = FailingTaskRuntimeClearer()
        monkeypatch.setattr(
            resource_mount,
            "clear_task_runtime",
            failing_clearer,
        )

        release_result = resource_mount.shutdown()
        saved_release_result = resource_mount.get_last_resource_release_result()

        assert failing_clearer.called is True
        assert len(release_result.detail.failures) == EXPECTED_SINGLE_RELEASE_FAILURE_COUNT
        assert saved_release_result == release_result
        assert saved_release_result is not release_result
        assert (
            release_result.detail.failures[FIRST_RELEASE_FAILURE_INDEX].resource_name
            == RESOURCE_TASK
        )
        assert (
            release_result.detail.failures[FIRST_RELEASE_FAILURE_INDEX].error_message
            == SHUTDOWN_FAILURE_MESSAGE
        )

    def test_shared_resource_mount_when_shutdown_repeated_should_release_idempotently(
        self,
    ) -> None:
        """验证重复关闭不会重新激活资源或遗留未释放失败。"""

        app = TestAppFactory().create()
        resource_mount = app.state.container.resource_mount
        resource_mount.startup()

        first_result = resource_mount.shutdown()
        second_result = resource_mount.shutdown()

        assert first_result.detail.failures == []
        assert second_result.detail.failures == []
        assert resource_mount.is_ready() is False
        assert resource_mount.get_last_resource_release_result() == second_result

    def test_resource_mount_helpers_should_not_write_mount_lifecycle_fields(
        self,
    ) -> None:
        """
        验证资源挂载 helper 不得直接写入 mount 生命周期字段。
        """

        for filename in HELPER_FILENAMES:
            source = (RESOURCE_MOUNT_HELPER_DIRECTORY / filename).read_text(encoding="utf-8")
            assert FORBIDDEN_PRIVATE_WRITE_PATTERN.search(source) is None
            assert FORBIDDEN_RUNTIME_STATE_WRITE_PATTERN.search(source) is None

    def _build_request(
        self,
        *,
        client_ip: str,
        headers: list[tuple[str, str]] | None = None,
    ):
        """
        Build a minimal Starlette request.
        """

        from starlette.requests import Request

        raw_headers = [
            (name.encode("latin-1"), value.encode("latin-1")) for name, value in (headers or [])
        ]
        return Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/health/live",
                "headers": raw_headers,
                "client": (client_ip, 12345),
                "scheme": "http",
                "server": ("testserver", 80),
            }
        )
