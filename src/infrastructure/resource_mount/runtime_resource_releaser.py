"""
运行时资源释放器。
"""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus
from typing import TYPE_CHECKING, Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.runtime_resource_contract import RuntimeResourceStatus
from src.core.logging_contract.log_event_contract import ResourceLifecycleAction
from src.core.logging_contract.log_writer_contract import LogWriteReason

if TYPE_CHECKING:
    from src.infrastructure.resource_mount.shared_resource_lifecycle import SharedResourceLifecycle

RUNTIME_RESOURCE_RELEASE_SCHEMA_VERSION: Final = "1.0"
RESOURCE_RELEASE_KIND: Final = "resource_release"
RESOURCE_RELEASE_OPERATION_NAME = "shutdown"
RESOURCE_RELEASE_TARGET_RESOURCE = "shared_resource_mount"
RESOURCE_RELEASE_RUNTIME_LOG_FLUSH = "runtime_log_flush"
RESOURCE_RELEASE_DATABASE_FINALIZE = "database_connection_finalize"
RESOURCE_RELEASE_FAILURE_SEPARATOR = ": "


class RuntimeResourceReleaseFailure(BaseModel):
    """
    运行时资源释放失败项。
    """

    model_config = ConfigDict(extra="forbid")

    resource_name: str
    error_type: str
    error_message: str


class RuntimeResourceReleaseHeader(BaseModel):
    """
    运行时资源释放公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["resource_release"] = RESOURCE_RELEASE_KIND
    schema_version: Literal["1.0"] = RUNTIME_RESOURCE_RELEASE_SCHEMA_VERSION
    operation_name: str
    target_resource: str


class ResourceReleaseDetail(BaseModel):
    """
    资源释放扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["resource_release"] = RESOURCE_RELEASE_KIND
    schema_version: Literal["1.0"] = RUNTIME_RESOURCE_RELEASE_SCHEMA_VERSION
    release_order: list[str]
    failures: list[RuntimeResourceReleaseFailure] = Field(default_factory=list)


RuntimeResourceReleaseDetail = Annotated[
    ResourceReleaseDetail,
    Field(discriminator="kind"),
]


class RuntimeResourceReleaseEnvelope(BaseModel):
    """
    运行时资源释放信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: RuntimeResourceReleaseHeader
    detail: RuntimeResourceReleaseDetail

    @model_validator(mode="after")
    def validate_release_contract(self) -> RuntimeResourceReleaseEnvelope:
        """
        校验释放操作公共头与扩展字段一致。
        """

        if self.header.kind != self.detail.kind:
            raise ValueError("资源释放 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("资源释放 header.schema_version 必须与 detail.schema_version 一致。")
        return self


class RuntimeResourceReleaser:
    """
    运行时资源释放器。
    """

    def build_contract(
        self,
        release_order: list[str],
        failures: list[RuntimeResourceReleaseFailure] | None = None,
    ) -> RuntimeResourceReleaseEnvelope:
        """
        构建资源释放契约信封。
        """

        return RuntimeResourceReleaseEnvelope(
            header=RuntimeResourceReleaseHeader(
                operation_name=RESOURCE_RELEASE_OPERATION_NAME,
                target_resource=RESOURCE_RELEASE_TARGET_RESOURCE,
            ),
            detail=ResourceReleaseDetail(
                release_order=release_order,
                failures=failures or [],
            ),
        )

    def shutdown(self, mount: SharedResourceLifecycle) -> RuntimeResourceReleaseEnvelope:
        """
        释放运行时资源。
        """

        from src.infrastructure.resource_mount.shared_resource_constants import (
            RESOURCE_CACHE,
            RESOURCE_DATABASE,
            RESOURCE_HTTP_CLIENT,
            RESOURCE_LOGGING,
            RESOURCE_TASK,
            RESOURCE_TASK_MESSAGE_TRANSPORT,
        )

        release_operations: list[tuple[str, Callable[[], None]]] = [
            (
                RESOURCE_RELEASE_RUNTIME_LOG_FLUSH,
                lambda: mount.flush_runtime_logs(reason=LogWriteReason.SHUTDOWN),
            ),
            (
                RESOURCE_TASK_MESSAGE_TRANSPORT,
                lambda: self._release_message_resource(mount),
            ),
            (RESOURCE_TASK, lambda: self._release_task_runtime(mount)),
            (RESOURCE_CACHE, lambda: self._release_cache(mount)),
            (RESOURCE_HTTP_CLIENT, lambda: self._release_http_resources(mount)),
            (RESOURCE_DATABASE, lambda: self._release_database(mount)),
            (RESOURCE_LOGGING, lambda: self._release_logging(mount)),
            (
                RESOURCE_RELEASE_DATABASE_FINALIZE,
                lambda: self._finalize_database_release(mount),
            ),
        ]
        release_order = [resource_name for resource_name, _operation in release_operations]
        failures: list[RuntimeResourceReleaseFailure] = []
        for resource_name, operation in release_operations:
            self._run_best_effort_release(
                resource_name=resource_name,
                operation=operation,
                failures=failures,
            )
        return self.build_contract(release_order=release_order, failures=failures)

    def _run_best_effort_release(
        self,
        *,
        resource_name: str,
        operation: Callable[[], None],
        failures: list[RuntimeResourceReleaseFailure],
    ) -> None:
        """
        尽力执行单个资源释放步骤。
        """

        try:
            operation()
        except Exception as exc:
            failures.append(
                RuntimeResourceReleaseFailure(
                    resource_name=resource_name,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            )

    def _release_message_resource(self, mount: SharedResourceLifecycle) -> None:
        """
        释放消息资源并标记已停止。
        """

        from src.infrastructure.resource_mount.shared_resource_constants import (
            RESOURCE_TASK_MESSAGE_TRANSPORT,
        )

        try:
            mount.close_message_resource()
        except HttpFaultException as exc:
            if (
                exc.status_code != HTTPStatus.SERVICE_UNAVAILABLE
                or exc.error_code != CoreErrorCode.RESOURCE_NOT_READY
            ):
                raise
        mount.mark_runtime_resource_stopped(RESOURCE_TASK_MESSAGE_TRANSPORT)
        mount.emit_runtime_lifecycle_log(
            resource_name=RESOURCE_TASK_MESSAGE_TRANSPORT,
            lifecycle_action=ResourceLifecycleAction.SHUTDOWN,
            resource_status=RuntimeResourceStatus.STOPPED,
            detail_text=None,
        )

    def _release_http_resources(self, mount: SharedResourceLifecycle) -> None:
        """
        释放 HTTP 资源。
        """

        from src.infrastructure.resource_mount.shared_resource_constants import (
            RESOURCE_ASYNC_HTTP_CLIENT,
            RESOURCE_HTTP_CLIENT,
        )

        resource_set = mount.detach_http_runtime()
        if resource_set is None:
            return
        mount.close_http_resource_set(resource_set)
        mount.mark_runtime_resource_stopped(RESOURCE_HTTP_CLIENT)
        mount.mark_runtime_resource_stopped(RESOURCE_ASYNC_HTTP_CLIENT)
        mount.emit_runtime_lifecycle_log(
            resource_name=RESOURCE_HTTP_CLIENT,
            lifecycle_action=ResourceLifecycleAction.SHUTDOWN,
            resource_status=RuntimeResourceStatus.STOPPED,
            detail_text=None,
        )
        mount.emit_runtime_lifecycle_log(
            resource_name=RESOURCE_ASYNC_HTTP_CLIENT,
            lifecycle_action=ResourceLifecycleAction.SHUTDOWN,
            resource_status=RuntimeResourceStatus.STOPPED,
            detail_text=None,
        )

    def _release_database(self, mount: SharedResourceLifecycle) -> None:
        """
        释放数据库资源。
        """

        from src.infrastructure.resource_mount.shared_resource_constants import RESOURCE_DATABASE

        mount.mark_runtime_resource_stopped(RESOURCE_DATABASE)
        mount.emit_runtime_lifecycle_log(
            resource_name=RESOURCE_DATABASE,
            lifecycle_action=ResourceLifecycleAction.SHUTDOWN,
            resource_status=RuntimeResourceStatus.STOPPED,
            detail_text=None,
        )

    def _finalize_database_release(self, mount: SharedResourceLifecycle) -> None:
        """在日志完成最终刷盘后释放数据库连接资源。"""

        mount.clear_database_runtime()

    def _release_cache(self, mount: SharedResourceLifecycle) -> None:
        """
        释放缓存资源。
        """

        from src.infrastructure.resource_mount.shared_resource_constants import (
            RESOURCE_CACHE,
            RESOURCE_DISTRIBUTED_LOCK,
            RESOURCE_KEY_MANAGEMENT,
            RESOURCE_SECURITY_PROTECTION,
        )

        mount.clear_cache_runtime()
        mount.mark_runtime_resource_stopped(RESOURCE_CACHE)
        mount.mark_runtime_resource_stopped(RESOURCE_DISTRIBUTED_LOCK)
        mount.mark_runtime_resource_stopped(RESOURCE_KEY_MANAGEMENT)
        mount.mark_runtime_resource_stopped(RESOURCE_SECURITY_PROTECTION)
        mount.emit_runtime_lifecycle_log(
            resource_name=RESOURCE_CACHE,
            lifecycle_action=ResourceLifecycleAction.SHUTDOWN,
            resource_status=RuntimeResourceStatus.STOPPED,
            detail_text=None,
        )

    def _release_task_runtime(self, mount: SharedResourceLifecycle) -> None:
        """
        释放任务运行时资源。
        """

        from src.infrastructure.resource_mount.shared_resource_constants import RESOURCE_TASK

        mount.clear_task_runtime()
        mount.mark_runtime_resource_stopped(RESOURCE_TASK)
        mount.emit_runtime_lifecycle_log(
            resource_name=RESOURCE_TASK,
            lifecycle_action=ResourceLifecycleAction.SHUTDOWN,
            resource_status=RuntimeResourceStatus.STOPPED,
            detail_text=None,
        )

    def _release_logging(self, mount: SharedResourceLifecycle) -> None:
        """
        释放日志资源。
        """

        from src.infrastructure.resource_mount.shared_resource_constants import RESOURCE_LOGGING

        mount.mark_runtime_resource_stopped(RESOURCE_LOGGING)
        mount.emit_runtime_lifecycle_log(
            resource_name=RESOURCE_LOGGING,
            lifecycle_action=ResourceLifecycleAction.SHUTDOWN,
            resource_status=RuntimeResourceStatus.STOPPED,
            detail_text=None,
        )
        try:
            mount.flush_runtime_logs(reason=LogWriteReason.MANUAL)
        finally:
            mount.clear_logging_runtime()
