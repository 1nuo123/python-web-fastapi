"""
任务注册中心基础设施模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Generic, TypeAlias

from pydantic import BaseModel, ValidationError

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.message_bus_contract import TaskMessageEnvelope
from src.core.task_contract.task_handler_contract import TaskHandler
from src.core.task_contract.task_invocation_contract import (
    TaskInvocationBinding,
    TaskInvocationResolution,
    TaskPayloadT,
)
from src.core.task_contract.task_registration_contract import (
    FunboostTaskRegistrationDetail,
    TaskRegistrationEnvelope,
)
from src.core.task_contract.task_runtime_contract import TaskBackend

INVALID_PAYLOAD_MODEL_MESSAGE = "任务 `{job_kind}` 的 payload_model 类型无效。"
PLACEHOLDER_PAYLOAD_MODEL_MESSAGE = "任务 `{job_kind}` 禁止使用 BaseModel 作为占位 payload_model。"
UNDECLARED_TASK_MESSAGE = "任务 `{job_kind}` 未在注册清单中声明。"
DUPLICATED_HANDLER_MESSAGE = "任务 `{job_kind}` 处理器重复注册。"
UNREGISTERED_TASK_MESSAGE = "任务 `{job_kind}` 未注册。"
DISABLED_TASK_MESSAGE = "任务 `{job_kind}` 已禁用，禁止派发。"
BACKEND_MISMATCH_TASK_MESSAGE = (
    "任务 `{job_kind}` 的注册后端 `{registration_backend}` "
    "与当前运行时后端 `{runtime_backend}` 不一致。"
)
MISSING_HANDLER_MESSAGE = "任务 `{job_kind}` 尚未绑定处理器。"
MISSING_BINDINGS_MESSAGE = "以下任务尚未绑定处理器：{job_kinds}。"
PRODUCER_ONLY_DECLARATION_MISSING_MESSAGE = "以下 producer-only 任务缺少启用注册声明：{job_kinds}。"
DUPLICATED_TASK_MESSAGE = "任务 `{job_kind}` 注册重复。"
DUPLICATED_QUEUE_MESSAGE = "Funboost 队列 `{queue_name}` 不能重复。"
PAYLOAD_KIND_MISMATCH_MESSAGE = "任务 `{job_kind}` 的 payload_kind 与 payload_model 不一致。"
PAYLOAD_JSON_INVALID_MESSAGE = "任务 `{job_kind}` 的 payload_json 校验失败。"


@dataclass(slots=True)
class RegisteredTaskBinding(Generic[TaskPayloadT]):
    """
    已注册任务绑定数据对象。
    """

    job_kind: str
    payload_model: type[TaskPayloadT]
    handler: TaskHandler[TaskPayloadT]


BaseModelTaskBinding: TypeAlias = RegisteredTaskBinding[BaseModel]


@dataclass(slots=True)
class ResolvedTaskBinding(Generic[TaskPayloadT]):
    """
    已解析任务绑定数据对象。
    """

    registration: TaskRegistrationEnvelope
    binding: RegisteredTaskBinding[TaskPayloadT]


@dataclass(slots=True)
class TaskBootstrapSnapshot:
    """
    任务装配快照数据对象。
    """

    enabled_job_kinds: list[str]
    disabled_job_kinds: list[str]
    missing_handler_job_kinds: list[str]
    backend: TaskBackend


class TaskRegistrationRegistry:
    """
    任务注册中心，负责统一管理注册项、处理器绑定与载荷校验。
    """

    def __init__(
        self,
        *,
        registrations: list[TaskRegistrationEnvelope],
    ) -> None:
        """
        初始化任务注册中心。
        """

        self._binding_by_job_kind: dict[str, RegisteredTaskBinding[BaseModel]] = {}
        self._registration_by_job_kind: dict[str, TaskRegistrationEnvelope] = {}
        self.replace_registrations(registrations)

    def replace_registrations(
        self,
        registrations: list[TaskRegistrationEnvelope],
    ) -> None:
        """
        替换任务注册清单。
        """

        self._registration_by_job_kind = {}
        for registration in registrations:
            job_kind = registration.header.job_kind
            if job_kind in self._registration_by_job_kind:
                raise HttpFaultException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    error_code=CoreErrorCode.CONFIG_INVALID,
                    message=DUPLICATED_TASK_MESSAGE.format(job_kind=job_kind),
                )
            self._registration_by_job_kind[job_kind] = registration
        self._validate_funboost_registration_contract()
        self._binding_by_job_kind = {
            job_kind: binding
            for job_kind, binding in self._binding_by_job_kind.items()
            if job_kind in self._registration_by_job_kind
        }

    def register_binding(self, binding: RegisteredTaskBinding[BaseModel]) -> None:
        """
        注册任务绑定。
        """

        self._validate_payload_model(binding)
        registration = self._registration_by_job_kind.get(binding.job_kind)
        if registration is None:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=UNDECLARED_TASK_MESSAGE.format(job_kind=binding.job_kind),
            )
        if binding.job_kind in self._binding_by_job_kind:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=DUPLICATED_HANDLER_MESSAGE.format(job_kind=binding.job_kind),
            )
        self._binding_by_job_kind[binding.job_kind] = binding

    def get_registration(self, job_kind: str) -> TaskRegistrationEnvelope | None:
        """
        获取任务注册项。
        """

        return self._registration_by_job_kind.get(job_kind)

    def get_enabled_registration(self, job_kind: str) -> TaskRegistrationEnvelope:
        """
        获取启用状态的任务注册项。
        """

        registration = self._registration_by_job_kind.get(job_kind)
        if registration is None:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=UNREGISTERED_TASK_MESSAGE.format(job_kind=job_kind),
            )
        if not registration.header.enabled:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=DISABLED_TASK_MESSAGE.format(job_kind=job_kind),
            )
        return registration

    def get_enabled_registration_for_backend(
        self,
        job_kind: str,
        *,
        backend: TaskBackend,
    ) -> TaskRegistrationEnvelope:
        """
        按后端获取启用状态的任务注册项。
        """

        registration = self.get_enabled_registration(job_kind)
        if registration.header.backend == backend:
            return registration
        raise HttpFaultException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_code=CoreErrorCode.CONFIG_INVALID,
            message=BACKEND_MISMATCH_TASK_MESSAGE.format(
                job_kind=job_kind,
                registration_backend=registration.header.backend.value,
                runtime_backend=backend.value,
            ),
        )

    def get_binding(self, job_kind: str) -> RegisteredTaskBinding[BaseModel] | None:
        """
        获取任务绑定。
        """

        return self._binding_by_job_kind.get(job_kind)

    def get_resolved_binding(self, job_kind: str) -> ResolvedTaskBinding[BaseModel]:
        """
        获取已解析任务绑定。
        """

        registration = self.get_enabled_registration(job_kind)
        binding = self._binding_by_job_kind.get(job_kind)
        if binding is None:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=MISSING_HANDLER_MESSAGE.format(job_kind=job_kind),
            )
        return ResolvedTaskBinding(registration=registration, binding=binding)

    def validate_message_payload(
        self,
        message: TaskMessageEnvelope,
    ) -> TaskInvocationResolution[BaseModel]:
        """
        校验任务消息载荷，并返回已解析执行对象。
        """

        resolved_binding = self.get_resolved_binding(message.payload.job_kind)
        return self._resolve_task_invocation(
            message=message,
            resolved_binding=resolved_binding,
        )

    def build_bootstrap_snapshot(self, backend: TaskBackend) -> TaskBootstrapSnapshot:
        """
        构建任务装配快照。
        """

        enabled_job_kinds: list[str] = []
        disabled_job_kinds: list[str] = []
        missing_handler_job_kinds: list[str] = []
        for job_kind, registration in self._registration_by_job_kind.items():
            if registration.header.backend != backend:
                continue
            if not registration.header.enabled:
                disabled_job_kinds.append(job_kind)
                continue
            enabled_job_kinds.append(job_kind)
            if job_kind not in self._binding_by_job_kind:
                missing_handler_job_kinds.append(job_kind)
        return TaskBootstrapSnapshot(
            enabled_job_kinds=enabled_job_kinds,
            disabled_job_kinds=disabled_job_kinds,
            missing_handler_job_kinds=missing_handler_job_kinds,
            backend=backend,
        )

    def assert_all_enabled_tasks_bound(self, backend: TaskBackend) -> None:
        """
        断言指定后端的启用任务都已绑定处理器。
        """

        bootstrap_snapshot = self.build_bootstrap_snapshot(backend)
        if len(bootstrap_snapshot.missing_handler_job_kinds) == 0:
            return
        raise HttpFaultException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_code=CoreErrorCode.CONFIG_INVALID,
            message=MISSING_BINDINGS_MESSAGE.format(
                job_kinds=",".join(bootstrap_snapshot.missing_handler_job_kinds)
            ),
        )

    def assert_enabled_tasks_declarable_for_producer(self, backend: TaskBackend) -> None:
        """
        断言 producer-only 节点存在可发布任务声明且不要求本地 handler 绑定。

        :param backend: 当前任务后端。
        :type backend: TaskBackend
        :returns: 无返回值。
        :rtype: None
        :raises HttpFaultException: 当指定后端没有启用任务声明时抛出配置异常。
        """

        bootstrap_snapshot = self.build_bootstrap_snapshot(backend)
        if len(bootstrap_snapshot.enabled_job_kinds) > 0:
            return
        raise HttpFaultException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_code=CoreErrorCode.CONFIG_INVALID,
            message=PRODUCER_ONLY_DECLARATION_MISSING_MESSAGE.format(job_kinds=backend.value),
        )

    def list_registrations_by_backend(
        self,
        backend: TaskBackend,
    ) -> list[TaskRegistrationEnvelope]:
        """
        列出指定后端的任务注册项。
        """

        return [
            registration
            for registration in self._registration_by_job_kind.values()
            if registration.header.backend == backend
        ]

    def list_registrations(self) -> list[TaskRegistrationEnvelope]:
        """
        列出全部任务注册项。
        """

        return list(self._registration_by_job_kind.values())

    def is_declared_job_kind(self, job_kind: str) -> bool:
        """
        判断任务类型是否已在注册清单中声明。
        """

        return job_kind in self._registration_by_job_kind

    def list_bindings(self) -> list[RegisteredTaskBinding[BaseModel]]:
        """
        列出全部已注册绑定。
        """

        return list(self._binding_by_job_kind.values())

    def _resolve_task_invocation(
        self,
        *,
        message: TaskMessageEnvelope,
        resolved_binding: ResolvedTaskBinding[BaseModel],
    ) -> TaskInvocationResolution[BaseModel]:
        """
        解析任务执行对象。
        """

        payload_model = resolved_binding.binding.payload_model
        expected_payload_kind = payload_model.__name__
        if message.payload.payload_kind != expected_payload_kind:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=PAYLOAD_KIND_MISMATCH_MESSAGE.format(job_kind=message.payload.job_kind),
                detail=(f"expected={expected_payload_kind}, actual={message.payload.payload_kind}"),
            )
        try:
            payload = payload_model.model_validate_json(message.payload.payload_json)
        except ValidationError as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=PAYLOAD_JSON_INVALID_MESSAGE.format(job_kind=message.payload.job_kind),
                detail=str(exc),
            ) from exc
        invocation_binding = TaskInvocationBinding(
            job_kind=resolved_binding.binding.job_kind,
            payload_model=payload_model,
            handler=resolved_binding.binding.handler,
        )
        return TaskInvocationResolution(
            payload=payload,
            message=message,
            binding=invocation_binding,
        )

    def _validate_payload_model(
        self,
        binding: RegisteredTaskBinding[BaseModel],
    ) -> None:
        """
        校验任务绑定中的 payload_model。
        """

        if not isinstance(binding.payload_model, type) or not issubclass(
            binding.payload_model,
            BaseModel,
        ):
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=INVALID_PAYLOAD_MODEL_MESSAGE.format(job_kind=binding.job_kind),
            )
        if binding.payload_model is BaseModel:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=PLACEHOLDER_PAYLOAD_MODEL_MESSAGE.format(job_kind=binding.job_kind),
            )

    def _validate_funboost_registration_contract(self) -> None:
        """
        校验 Funboost 注册项的运行时约束。
        """

        queue_names: set[str] = set()
        for registration in self._registration_by_job_kind.values():
            if not isinstance(registration.detail, FunboostTaskRegistrationDetail):
                continue
            queue_name = registration.detail.queue_name
            if queue_name in queue_names:
                raise HttpFaultException(
                    status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                    error_code=CoreErrorCode.CONFIG_INVALID,
                    message=DUPLICATED_QUEUE_MESSAGE.format(queue_name=queue_name),
                )
            queue_names.add(queue_name)
