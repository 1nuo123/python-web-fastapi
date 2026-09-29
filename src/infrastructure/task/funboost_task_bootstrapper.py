"""
Funboost 任务装配基础设施模块。
"""

from __future__ import annotations

import atexit
import os
from collections.abc import Callable
from http import HTTPStatus
from typing import TypedDict, cast
from urllib.parse import unquote, urlparse
from uuid import uuid4

from funboost import BoosterParams, BrokerConnConfig, BrokerEnum, boost
from funboost.consumers.base_consumer import AbstractConsumer, GlobalVars
from funboost.core.booster import Booster, BoosterRegistry
from funboost.core.func_params_model import PublisherParams
from funboost.core.function_result_status_saver import FunctionResultStatus
from funboost.core.lazy_impoter import funboost_lazy_impoter
from funboost.factories.consumer_factory import ConsumerCacheProxy
from funboost.factories.publisher_factotry import PublisherCacheProxy, get_publisher
from funboost.funboost_config_deafult import BrokerConnConfig as DefaultBrokerConnConfig
from funboost.publishers.base_publisher import AbstractPublisher
from pydantic import BaseModel, ConfigDict

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.message_bus_contract import (
    TaskMessageEnvelope,
    TaskMessagePublishExtra,
    TaskMessagePublishExtraParams,
)
from src.core.task_contract.task_dispatcher_contract import TaskFailureStage
from src.core.task_contract.task_execution_record_contract import TaskExecutionStage
from src.core.task_contract.task_registration_contract import (
    FunboostTaskRegistrationDetail,
)
from src.core.task_contract.task_runtime_contract import (
    FunboostTaskBackendDetail,
    RabbitMqMessageBackendDetail,
    TaskBackend,
)
from src.infrastructure.task.bounded_funboost_rabbitmq_consumer import (
    BoundedFunboostRabbitMqConsumer,
)
from src.infrastructure.task.confirmed_funboost_rabbitmq_publisher import (
    ConfirmedFunboostRabbitMqPublisher,
)
from src.infrastructure.task.failed_task_recorder import TaskFailureRecord
from src.infrastructure.task.managed_funboost_thread_pool import (
    ManagedFunboostThreadPool,
)
from src.infrastructure.task.task_execution_store import TaskExecutionStore
from src.infrastructure.task.task_registration_registry import (
    RegisteredTaskBinding,
    ResolvedTaskBinding,
    TaskRegistrationRegistry,
)

FUNBOOST_DEFAULT_LOGGER_PREFIX = "fastapi_web_skeleton"
FUNBOOST_DEFAULT_PROJECT_NAME = "fastapi_web_skeleton"
FUNBOOST_THREADING_MODE = "threading"
FUNBOOST_ROUTING_KEY_FIELD_NAME = "routing_key_for_publish"
FUNBOOST_QUEUE_DURABLE_FIELD_NAME = "queue_durable"
FUNBOOST_NO_ACK_FIELD_NAME = "no_ack"
FUNBOOST_EXCHANGE_NAME_FIELD_NAME = "exchange_name"
FUNBOOST_EXCHANGE_TYPE_FIELD_NAME = "exchange_type"
FUNBOOST_ROUTING_KEY_BIND_FIELD_NAME = "routing_key_for_bind"
FUNBOOST_EXCHANGE_DURABLE_FIELD_NAME = "exchange_declare_durable"
FUNBOOST_PRIORITY_FIELD_NAME = "x-max-priority"
FUNBOOST_QUEUE_MAX_LENGTH_FIELD_NAME = "queue_max_length"
FUNBOOST_PREFETCH_COUNT_FIELD_NAME = "prefetch_count"
FUNBOOST_DEAD_LETTER_EXCHANGE_FIELD_NAME = "dead_letter_exchange_name"
FUNBOOST_MESSAGE_PERSISTENT_FIELD_NAME = "message_persistent"
FUNBOOST_PUBLISHER_CONFIRM_FIELD_NAME = "publisher_confirm_enabled"
FUNBOOST_PUBLISHER_CONFIRM_TIMEOUT_FIELD_NAME = "publisher_confirm_timeout_seconds"
FUNBOOST_STOP_FLAG_VALUE = 1
FUNBOOST_MAX_RETRY_OFFSET = 1
FUNBOOST_INITIAL_ATTEMPT_COUNT = 0
FUNBOOST_RUN_STATUS_FINISH = "finish"
FUNBOOST_DEFAULT_EXCEPTION_TYPE_NAME = "Exception"
FUNBOOST_RECORD_PROCESS_INFO_CALLBACK_ATTRIBUTE = "_frame_custom_record_process_info_func"
FUNBOOST_STOP_FLAG_ATTRIBUTE = "_stop_flag"
FUNBOOST_CONSUME_FAILURE_MESSAGE = "Funboost 消费执行失败。"
FUNBOOST_FAILURE_RECORD_MISSING_LOG_MESSAGE = (
    "Funboost 消费失败回写时任务执行记录不存在，已保留失败记录：task_id=%s job_kind=%s。"
)


class FunboostTaskMessageHeaderMapping(TypedDict):
    """
    Funboost 发布任务消息头映射。
    """

    kind: str
    schema_version: str
    message_id: str
    request_id: str
    trace_id: str | None
    created_at_epoch: int


class FunboostTaskMessagePayloadMapping(TypedDict):
    """
    Funboost 发布任务消息载荷映射。
    """

    kind: str
    schema_version: str
    job_kind: str
    deduplication_key: str
    retry_limit: int
    payload_kind: str
    payload_json: str


class FunboostTaskMessageEnvelopeMapping(TypedDict):
    """
    Funboost 发布任务消息信封映射。
    """

    header: FunboostTaskMessageHeaderMapping
    payload: FunboostTaskMessagePayloadMapping


class FunboostPublishExtraParamsMapping(TypedDict):
    """
    Funboost 发布额外参数映射。
    """

    routing_key_for_publish: str


class FunboostPublishExtraMapping(TypedDict):
    """
    Funboost 发布扩展映射。
    """

    other_extra_params: FunboostPublishExtraParamsMapping
    task_id: str
    max_retry_times: int


class FunboostPublishMessageMapping(TypedDict):
    """
    Funboost 发布消息映射。
    """

    task_message: FunboostTaskMessageEnvelopeMapping
    extra: FunboostPublishExtraMapping


class FunboostPublishMessagePayload(BaseModel):
    """
    Funboost 发布载荷。

    :ivar task_message: 业务任务消息主体。约束：需符合 ``TaskMessageEnvelope`` 注解。取值语义：承载标准化的任务信封。
    :vartype task_message: TaskMessageEnvelope
    :ivar extra: Funboost 发布附加参数。约束：需符合 ``TaskMessagePublishExtra`` 注解。取值语义：用于传递 RabbitMQ 路由键与发布头等底层参数。
    :vartype extra: TaskMessagePublishExtra
    """

    model_config = ConfigDict(extra="forbid")

    task_message: TaskMessageEnvelope
    extra: TaskMessagePublishExtra


class FunboostRawMessagePayload(BaseModel):
    """
    Funboost 原始消息载荷。
    """

    model_config = ConfigDict(extra="allow")

    task_message: TaskMessageEnvelope
    current_retry_times: int | None = None


class FunboostProcessInfoPayload(BaseModel):
    """
    Funboost 处理状态回调载荷。
    """

    model_config = ConfigDict(extra="allow")

    body: FunboostRawMessagePayload


class FunboostTaskBootstrapper:
    """
    Funboost 任务装配器。

    该装配器负责把任务注册契约转换为 Funboost 的 Booster、Consumer 与 Publisher，
    并统一管理 RabbitMQ 连接配置、消费者启动与资源回收。

    RabbitMQ 发布和消费主链统一应用持久化、publisher confirm、有界队列、预取数量
    与死信交换机配置；生产者和消费者共享相同拓扑声明。
    """

    def __init__(
        self,
        *,
        registration_registry: TaskRegistrationRegistry,
        runtime_detail: FunboostTaskBackendDetail,
        message_detail: RabbitMqMessageBackendDetail,
        task_execution_store: TaskExecutionStore,
        entry_project_name: str = FUNBOOST_DEFAULT_PROJECT_NAME,
        failure_callback: Callable[[TaskFailureRecord], None] | None = None,
    ) -> None:
        """
        初始化 Funboost 任务装配器。

        :param registration_registry: 任务注册中心，用于解析任务注册与处理器绑定关系。
        :type registration_registry: TaskRegistrationRegistry
        :param runtime_detail: 已完成契约校验的任务运行时配置。
        :type runtime_detail: FunboostTaskBackendDetail
        :param message_detail: 已完成契约校验的 RabbitMQ 消息后端配置。
        :type message_detail: RabbitMqMessageBackendDetail
        :param failure_callback: 消费最终失败时的回调。默认值：``None``。取值语义：用于把 Funboost 失败事件回写到统一失败记录链路。
        :type failure_callback: Callable[[TaskFailureRecord], None] | None
        :returns: 无返回值。
        :rtype: None
        """

        self._registration_registry = registration_registry
        self._runtime_detail = runtime_detail
        self._message_detail = message_detail
        self._task_execution_store = task_execution_store
        self._entry_project_name = entry_project_name
        self._failure_callback = failure_callback
        self._booster_registry_name = f"{entry_project_name}-{uuid4().hex}"
        self._booster_by_job_kind: dict[str, Booster] = {}
        self._consumer_by_job_kind: dict[str, AbstractConsumer] = {}
        self._publisher_by_job_kind: dict[str, AbstractPublisher] = {}
        self._publisher_detail_by_job_kind: dict[str, FunboostTaskRegistrationDetail] = {}

    def configure_broker_connection(self) -> None:
        """
        配置 Funboost 的 RabbitMQ 连接参数。

        :returns: 无返回值。
        :rtype: None
        :raises HttpFaultException: 当 RabbitMQ 地址缺少主机名或连接配置不合法时抛出。
        """

        parsed_url = urlparse(self._message_detail.rabbitmq_url)
        if parsed_url.hostname is None:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message="RabbitMQ 连接地址缺少主机名。",
            )
        BrokerConnConfig.RABBITMQ_HOST = parsed_url.hostname
        BrokerConnConfig.RABBITMQ_PORT = parsed_url.port or 5672
        BrokerConnConfig.RABBITMQ_USER = unquote(parsed_url.username or "guest")
        BrokerConnConfig.RABBITMQ_PASS = unquote(parsed_url.password or "guest")
        BrokerConnConfig.RABBITMQ_VIRTUAL_HOST = self._resolve_virtual_host(parsed_url.path)
        BrokerConnConfig.RABBITMQ_URL = self._message_detail.rabbitmq_url
        DefaultBrokerConnConfig.RABBITMQ_HOST = BrokerConnConfig.RABBITMQ_HOST
        DefaultBrokerConnConfig.RABBITMQ_PORT = BrokerConnConfig.RABBITMQ_PORT
        DefaultBrokerConnConfig.RABBITMQ_USER = BrokerConnConfig.RABBITMQ_USER
        DefaultBrokerConnConfig.RABBITMQ_PASS = BrokerConnConfig.RABBITMQ_PASS
        DefaultBrokerConnConfig.RABBITMQ_VIRTUAL_HOST = BrokerConnConfig.RABBITMQ_VIRTUAL_HOST
        DefaultBrokerConnConfig.RABBITMQ_URL = BrokerConnConfig.RABBITMQ_URL

    def register_binding(self, binding: RegisteredTaskBinding[BaseModel]) -> None:
        """
        注册 Funboost 任务绑定。

        :param binding: 已完成处理器绑定的任务注册项。
        :type binding: RegisteredTaskBinding
        :returns: 无返回值。
        :rtype: None
        """

        self.register_consumer(binding.job_kind)

    def register_consumer(self, job_kind: str) -> None:
        """
        注册 Funboost 任务消费者。
        """

        resolved_binding = self._registration_registry.get_resolved_binding(job_kind)
        if not isinstance(
            resolved_binding.registration.detail,
            FunboostTaskRegistrationDetail,
        ):
            return
        booster = self._build_booster(resolved_binding)
        self._booster_by_job_kind[job_kind] = booster
        self._consumer_by_job_kind[job_kind] = booster.consumer

    def register_publisher(self, job_kind: str) -> None:
        """
        注册仅用于发布的 Funboost 任务。
        """

        registration = self._registration_registry.get_enabled_registration_for_backend(
            job_kind,
            backend=TaskBackend.FUNBOOST,
        )
        if not isinstance(registration.detail, FunboostTaskRegistrationDetail):
            return
        self._publisher_detail_by_job_kind[job_kind] = registration.detail

    def publish(self, message: TaskMessageEnvelope) -> None:
        """
        发布任务消息。

        :param message: 已通过契约校验的任务消息信封。
        :type message: TaskMessageEnvelope
        :returns: 无返回值。
        :rtype: None
        :raises HttpFaultException: 当目标任务尚未装配或任务注册与运行时不一致时抛出。
        """

        booster = self._booster_by_job_kind.get(message.payload.job_kind)
        if booster is not None:
            booster.publish(self._build_publish_message(message))
            return
        publisher = self._publisher_by_job_kind.get(message.payload.job_kind)
        if publisher is None:
            publisher = self._build_lazy_publisher(message.payload.job_kind)
        publisher.publish(cast(dict[object, object], self._build_publish_message(message)))

    def start_consumers(self) -> None:
        """
        启动全部 Funboost 消费者。

        :returns: 无返回值。
        :rtype: None
        """

        for consumer in self._consumer_by_job_kind.values():
            consumer.start_consuming_message()

    def health_check(self) -> tuple[bool, dict[str, object]]:
        """Return readiness from the live Funboost consumer owner.

        The consumer registry and Funboost started-consumer registry are the
        existing lifecycle facts; no parallel health state is maintained.
        """

        expected = len(self._consumer_job_kinds())
        started_raw = getattr(
            funboost_lazy_impoter.BoostersManager,
            "pid_queue_name__has_start_consume_set",
            None,
        )
        started: set[tuple[int, str]] = set()
        if isinstance(started_raw, set):
            started.update(
                item
                for item in started_raw
                if isinstance(item, tuple)
                and len(item) == 2
                and isinstance(item[0], int)
                and isinstance(item[1], str)
            )
        registry_started = BoosterRegistry(
            self._booster_registry_name
        ).pid_queue_name__has_start_consume_set
        if isinstance(registry_started, set):
            started.update(
                item
                for item in registry_started
                if isinstance(item, tuple)
                and len(item) == 2
                and isinstance(item[0], int)
                and isinstance(item[1], str)
            )
        started_queues = {queue_name for pid, queue_name in started if pid == os.getpid()}
        queues = {
            getattr(consumer, "queue_name", "") for consumer in self._consumer_by_job_kind.values()
        }
        stopped = any(
            getattr(consumer, FUNBOOST_STOP_FLAG_ATTRIBUTE, 0) == FUNBOOST_STOP_FLAG_VALUE
            for consumer in self._consumer_by_job_kind.values()
        )
        broker_ready = all(
            getattr(
                getattr(getattr(consumer, "_rp", None), "channel", None),
                "is_open",
                True,
            )
            is not False
            for consumer in self._consumer_by_job_kind.values()
        )
        binding_ready = expected > 0 and len(queues) == expected
        consumer_ready = (
            binding_ready
            and len(queues & started_queues) == expected
            and not stopped
            and broker_ready
        )
        ready = consumer_ready
        return ready, {
            "consumer_count": expected,
            "started_consumer_count": len(queues & started_queues),
            "binding_ready": binding_ready,
            "consumer_ready": consumer_ready,
            "broker_ready": broker_ready,
        }

    def recover_consumers(self) -> None:
        """Rebuild and restart consumers after a broker interruption."""

        job_kinds = self._consumer_job_kinds()
        self.shutdown()
        self.configure_broker_connection()
        for job_kind in job_kinds:
            self.register_consumer(job_kind)
        self.start_consumers()

    def _consumer_job_kinds(self) -> tuple[str, ...]:
        """Return enabled Funboost registrations owned by the worker."""

        return tuple(
            registration.header.job_kind
            for registration in self._registration_registry.list_registrations_by_backend(
                TaskBackend.FUNBOOST
            )
            if registration.header.enabled
        )

    def shutdown(self) -> None:
        """
        停止全部 Funboost 消费者并释放发布者连接。

        :returns: 无返回值。
        :rtype: None
        """

        managed_queue_names = self._collect_managed_queue_names()
        released_publisher_ids: set[int] = set()
        for consumer in self._consumer_by_job_kind.values():
            self._reset_consumer_state(consumer)
            self._release_consumer_publishers(
                consumer=consumer,
                released_publisher_ids=released_publisher_ids,
            )
            self._shutdown_consumer_pool(consumer)
        for booster in self._booster_by_job_kind.values():
            self._release_booster(
                booster=booster,
                released_publisher_ids=released_publisher_ids,
            )
        for publisher in self._publisher_by_job_kind.values():
            self._release_publisher(
                publisher=publisher,
                released_publisher_ids=released_publisher_ids,
            )
        self._release_cached_publishers(
            managed_queue_names=managed_queue_names,
            released_publisher_ids=released_publisher_ids,
        )
        self._release_cached_consumers()
        self._consumer_by_job_kind.clear()
        self._booster_by_job_kind.clear()
        self._publisher_by_job_kind.clear()
        self._publisher_detail_by_job_kind.clear()

    def _build_booster(self, resolved_binding: ResolvedTaskBinding[BaseModel]) -> Booster:
        """
        构建 Funboost Booster。

        当前映射到 ``BoosterParams`` 的字段仅包含任务注册项和 RabbitMQ 运行时中
        已由 Funboost 消费的参数。

        :param resolved_binding: 已解析注册契约与处理器实例的任务绑定。
        :type resolved_binding: ResolvedTaskBinding
        :returns: 返回可直接发布和消费的 Funboost Booster。
        :rtype: Booster
        :raises HttpFaultException: 当任务不是 Funboost 注册项或注册信息不完整时抛出。
        """

        registration = resolved_binding.registration
        detail = registration.detail
        if not isinstance(detail, FunboostTaskRegistrationDetail):
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=f"任务 `{registration.header.job_kind}` 不是 Funboost 注册项。",
            )
        broker_params = self._build_booster_params(detail)

        def consume_funboost_message(task_message: object) -> None:
            # Funboost 只负责消息收发，真正的任务处理仍回到项目统一的处理器绑定上。
            message_envelope = TaskMessageEnvelope.model_validate(task_message)
            invocation = self._registration_registry.validate_message_payload(message_envelope)
            self._task_execution_store.mark_running(
                job_kind=message_envelope.payload.job_kind,
                deduplication_key=message_envelope.payload.deduplication_key,
                attempt_count=FUNBOOST_INITIAL_ATTEMPT_COUNT,
                backend=TaskBackend.FUNBOOST,
                queue_name=detail.queue_name,
                stage=TaskExecutionStage.CONSUME_EXECUTION,
            )
            invocation.binding.handler.handle(invocation)
            self._task_execution_store.mark_success(
                job_kind=message_envelope.payload.job_kind,
                deduplication_key=message_envelope.payload.deduplication_key,
                attempt_count=FUNBOOST_MAX_RETRY_OFFSET,
                backend=TaskBackend.FUNBOOST,
                queue_name=detail.queue_name,
                stage=TaskExecutionStage.CONSUME_EXECUTION,
            )

        consume_funboost_message.__name__ = (
            f"consume_{registration.header.job_kind}_funboost_message"
        )
        consume_funboost_message.__qualname__ = consume_funboost_message.__name__
        consume_funboost_message.__module__ = self.__class__.__module__
        booster = boost(broker_params)(consume_funboost_message)
        consumer = booster.consumer
        self._bind_consumer_failure_callback(
            consumer=consumer,
            queue_name=detail.queue_name,
        )
        return booster

    def _build_publisher(
        self,
        detail: FunboostTaskRegistrationDetail,
    ) -> AbstractPublisher:
        """
        构建不注册消费者的 Funboost 发布器。
        """

        return get_publisher(
            PublisherParams(
                queue_name=detail.queue_name,
                broker_kind=self._map_broker_kind(detail),
                project_name=self._entry_project_name,
                logger_prefix=self._entry_project_name,
                create_logger_file=False,
                should_check_publish_func_params=False,
                publisher_override_cls=ConfirmedFunboostRabbitMqPublisher,
                broker_exclusive_config=self._build_broker_exclusive_config(detail),
                booster_registry_name=self._booster_registry_name,
            )
        )

    def _build_lazy_publisher(self, job_kind: str) -> AbstractPublisher:
        """
        按需构建 producer-only 发布器。

        :param job_kind: 目标任务类型。
        :type job_kind: str
        :returns: 返回已缓存且不注册消费者的 Funboost 发布器。
        :rtype: AbstractPublisher
        :raises HttpFaultException: 当目标任务未注册为可发布任务时抛出。
        """

        detail = self._publisher_detail_by_job_kind.get(job_kind)
        if detail is None:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=f"Funboost 任务 `{job_kind}` 尚未完成装配。",
            )
        publisher = self._build_publisher(detail)
        self._publisher_by_job_kind[job_kind] = publisher
        return publisher

    def _build_booster_params(
        self,
        detail: FunboostTaskRegistrationDetail,
    ) -> BoosterParams:
        """
        构建 Funboost Booster 参数。
        """

        return BoosterParams(
            queue_name=detail.queue_name,
            broker_kind=self._map_broker_kind(detail),
            concurrent_mode=FUNBOOST_THREADING_MODE,
            concurrent_num=detail.consumer_worker_count,
            max_retry_times=detail.retry_limit,
            should_check_publish_func_params=False,
            project_name=self._entry_project_name,
            logger_prefix=self._entry_project_name,
            create_logger_file=False,
            publisher_override_cls=ConfirmedFunboostRabbitMqPublisher,
            consumer_override_cls=BoundedFunboostRabbitMqConsumer,
            specify_concurrent_pool=ManagedFunboostThreadPool(
                max_workers=detail.consumer_worker_count
            ),
            booster_registry_name=self._booster_registry_name,
            broker_exclusive_config=self._build_broker_exclusive_config(detail),
        )

    def _build_broker_exclusive_config(
        self,
        detail: FunboostTaskRegistrationDetail,
    ) -> dict[str, object]:
        """构建 Funboost 生产 RabbitMQ 专属配置。"""

        return {
            FUNBOOST_QUEUE_DURABLE_FIELD_NAME: self._message_detail.task_exchange_durable,
            FUNBOOST_NO_ACK_FIELD_NAME: False,
            FUNBOOST_EXCHANGE_NAME_FIELD_NAME: detail.exchange_name,
            FUNBOOST_EXCHANGE_TYPE_FIELD_NAME: self._message_detail.task_exchange_type,
            FUNBOOST_ROUTING_KEY_BIND_FIELD_NAME: detail.routing_key,
            FUNBOOST_ROUTING_KEY_FIELD_NAME: detail.routing_key,
            FUNBOOST_EXCHANGE_DURABLE_FIELD_NAME: self._message_detail.task_exchange_durable,
            FUNBOOST_PRIORITY_FIELD_NAME: None,
            FUNBOOST_QUEUE_MAX_LENGTH_FIELD_NAME: self._message_detail.queue_max_length,
            FUNBOOST_PREFETCH_COUNT_FIELD_NAME: self._message_detail.consumer_prefetch_count,
            FUNBOOST_DEAD_LETTER_EXCHANGE_FIELD_NAME: (
                self._message_detail.dead_letter_exchange_name
            ),
            FUNBOOST_MESSAGE_PERSISTENT_FIELD_NAME: (self._message_detail.task_message_persistent),
            FUNBOOST_PUBLISHER_CONFIRM_FIELD_NAME: (self._message_detail.publisher_confirm_enabled),
            FUNBOOST_PUBLISHER_CONFIRM_TIMEOUT_FIELD_NAME: (
                self._message_detail.publisher_confirm_timeout_seconds
            ),
        }

    def _bind_consumer_failure_callback(
        self,
        *,
        consumer: AbstractConsumer,
        queue_name: str,
    ) -> None:
        """
        绑定 Funboost 消费最终失败回调。

        :param consumer: Funboost 消费者实例。
        :type consumer: AbstractConsumer
        :param queue_name: 当前消费者对应的队列名称。
        :type queue_name: str
        :returns: 无返回值。
        :rtype: None
        """

        original_callback = consumer._frame_custom_record_process_info_func

        def record_process_info(
            current_function_result_status: FunctionResultStatus,
            kw: dict[str, object],
        ) -> None:
            original_callback(current_function_result_status, kw)
            if not self._should_record_consume_failure(current_function_result_status):
                return
            process_info = FunboostProcessInfoPayload.model_validate(kw)
            # 只有真正耗尽重试且未转死信、未重入的失败才计入统一失败闭环。
            record = self._build_consume_failure_record(
                current_function_result_status=current_function_result_status,
                kw=process_info,
                queue_name=queue_name,
            )
            failed_at_epoch = 0
            if current_function_result_status.time_end is not None:
                failed_at_epoch = int(current_function_result_status.time_end)
            updated_record = self._task_execution_store.try_mark_failed(
                job_kind=record.job_kind,
                deduplication_key=record.deduplication_key or "",
                attempt_count=record.attempt_count,
                failed_at_epoch=failed_at_epoch,
                last_error_type=current_function_result_status.exception.__class__.__name__
                if current_function_result_status.exception is not None
                else FUNBOOST_DEFAULT_EXCEPTION_TYPE_NAME,
                last_error_message=current_function_result_status.exception_msg or record.message,
                backend=TaskBackend.FUNBOOST,
                queue_name=queue_name,
                stage=TaskExecutionStage.CONSUME_EXECUTION,
            )
            if updated_record is None:
                consumer.logger.warning(
                    FUNBOOST_FAILURE_RECORD_MISSING_LOG_MESSAGE,
                    record.task_id,
                    record.job_kind,
                )
            self._record_failure_callback(record)

        setattr(
            consumer,
            FUNBOOST_RECORD_PROCESS_INFO_CALLBACK_ATTRIBUTE,
            record_process_info,
        )

    def _record_failure_callback(self, record: TaskFailureRecord) -> None:
        """
        记录统一失败回调。
        """

        if self._failure_callback is not None:
            self._failure_callback(record)

    def _should_record_consume_failure(
        self,
        current_function_result_status: FunctionResultStatus,
    ) -> bool:
        """
        判断是否需要记录消费最终失败。

        :param current_function_result_status: Funboost 当前任务执行结果。
        :type current_function_result_status: FunctionResultStatus
        :returns: 返回是否应记录最终失败。
        :rtype: bool
        """

        return (
            current_function_result_status.success is False
            and current_function_result_status.run_status == FUNBOOST_RUN_STATUS_FINISH
            and current_function_result_status._has_requeue is False
            and current_function_result_status._has_to_dlx_queue is False
            and current_function_result_status._has_kill_task is False
        )

    def _build_consume_failure_record(
        self,
        *,
        current_function_result_status: FunctionResultStatus,
        kw: FunboostProcessInfoPayload,
        queue_name: str,
    ) -> TaskFailureRecord:
        """
        构建消费最终失败记录。

        :param current_function_result_status: Funboost 当前任务执行结果。
        :type current_function_result_status: FunctionResultStatus
        :param kw: Funboost 传入的原始执行上下文。
        :type kw: FunboostProcessInfoPayload
        :param queue_name: 当前失败记录所属队列。
        :type queue_name: str
        :returns: 返回统一任务失败记录。
        :rtype: TaskFailureRecord
        """

        task_message = kw.body.task_message
        return TaskFailureRecord(
            task_id=current_function_result_status.task_id,
            job_kind=task_message.payload.job_kind,
            message=FUNBOOST_CONSUME_FAILURE_MESSAGE,
            retry_count=max(
                current_function_result_status.run_times - FUNBOOST_MAX_RETRY_OFFSET,
                0,
            ),
            backend=TaskBackend.FUNBOOST,
            stage=TaskFailureStage.CONSUME_EXECUTION,
            last_error=current_function_result_status.exception_msg,
            queue_name=queue_name,
            payload_kind=task_message.payload.payload_kind,
            request_id=task_message.header.request_id,
            trace_id=task_message.header.trace_id,
            deduplication_key=task_message.payload.deduplication_key,
            attempt_count=max(current_function_result_status.run_times, 0),
        )

    def _resolve_consume_attempt_count(
        self,
        message_payload: FunboostRawMessagePayload,
    ) -> int:
        """
        解析当前消费尝试次数。
        """

        run_times = message_payload.current_retry_times
        if isinstance(run_times, int) and run_times >= 0:
            return run_times
        return 0

    def _build_publish_message(self, message: TaskMessageEnvelope) -> FunboostPublishMessageMapping:
        """
        构建发布到 Funboost 的消息体。

        :param message: 已通过契约校验的任务消息信封。
        :type message: TaskMessageEnvelope
        :returns: 返回适配 Funboost 发布接口的字典载荷。
        :rtype: FunboostPublishMessageMapping
        :raises HttpFaultException: 当目标任务不是 Funboost 注册项时抛出。
        """

        registration = self._registration_registry.get_enabled_registration_for_backend(
            message.payload.job_kind,
            backend=TaskBackend.FUNBOOST,
        )
        detail = registration.detail
        if not isinstance(detail, FunboostTaskRegistrationDetail):
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=f"任务 `{message.payload.job_kind}` 不是 Funboost 注册项。",
            )
        publish_payload = FunboostPublishMessagePayload(
            task_message=message,
            extra=TaskMessagePublishExtra(
                other_extra_params=TaskMessagePublishExtraParams(
                    routing_key_for_publish=detail.routing_key,
                ),
                task_id=message.header.message_id,
                max_retry_times=message.payload.retry_limit,
            ),
        )
        return cast(
            FunboostPublishMessageMapping,
            publish_payload.model_dump(mode="python"),
        )

    def _map_broker_kind(self, detail: FunboostTaskRegistrationDetail) -> str:
        """
        映射 Funboost Broker 类型。

        :param detail: Funboost 任务注册扩展配置。
        :type detail: FunboostTaskRegistrationDetail
        :returns: 返回 Funboost 可识别的 Broker 类型常量。
        :rtype: str
        :raises HttpFaultException: 当任务注册的 broker_kind 与运行时配置不一致时抛出。
        """

        if detail.broker_kind != self._runtime_detail.broker_kind:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=f"任务 `{detail.queue_name}` 的 broker_kind 与运行时配置不一致。",
            )
        return BrokerEnum.RABBITMQ_COMPLEX_ROUTING

    def _resolve_virtual_host(self, raw_path: str) -> str:
        """
        解析 RabbitMQ 虚拟主机。

        :param raw_path: 从连接 URL 中解析出的原始路径段。
        :type raw_path: str
        :returns: 返回 RabbitMQ 可用的虚拟主机名称。
        :rtype: str
        """

        normalized_path = raw_path.strip("/")
        if normalized_path == "":
            return "/"
        return unquote(normalized_path)

    def _reset_consumer_state(self, consumer: AbstractConsumer) -> None:
        """
        重置消费者退出状态。

        :param consumer: 需要重置运行状态的 Funboost 消费者。
        :type consumer: AbstractConsumer
        :returns: 无返回值。
        :rtype: None
        """

        if hasattr(GlobalVars, "has_start_a_consumer_flag"):
            GlobalVars.has_start_a_consumer_flag = False
        setattr(consumer, FUNBOOST_STOP_FLAG_ATTRIBUTE, FUNBOOST_STOP_FLAG_VALUE)
        started_consume_set = getattr(
            funboost_lazy_impoter.BoostersManager,
            "pid_queue_name__has_start_consume_set",
            None,
        )
        if isinstance(started_consume_set, set):
            started_consume_set.discard((os.getpid(), consumer.queue_name))
        BoosterRegistry(self._booster_registry_name).pid_queue_name__has_start_consume_set.discard(
            (os.getpid(), consumer.queue_name)
        )

    def _release_consumer_publishers(
        self,
        consumer: AbstractConsumer,
        released_publisher_ids: set[int],
    ) -> None:
        """
        释放消费者内部持有的发布者。

        :param consumer: 需要释放内部发布者的 Funboost 消费者。
        :type consumer: AbstractConsumer
        :param released_publisher_ids: 已释放发布者对象标识集合。
        :type released_publisher_ids: set[int]
        :returns: 无返回值。
        :rtype: None
        """

        for publisher_name in (
            "_publisher_of_same_queue",
            "_publisher_of_dlx_queue",
            "_rp",
        ):
            publisher = getattr(consumer, publisher_name, None)
            self._release_publisher(
                publisher=publisher,
                released_publisher_ids=released_publisher_ids,
            )
            if publisher is not None:
                setattr(consumer, publisher_name, None)

    def _shutdown_consumer_pool(self, consumer: AbstractConsumer) -> None:
        """关闭当前消费者持有的任务线程池。"""

        concurrent_pool = getattr(consumer, "_concurrent_pool", None)
        if concurrent_pool is None:
            consumer_params = getattr(consumer, "consumer_params", None)
            concurrent_pool = getattr(consumer_params, "specify_concurrent_pool", None)
        if isinstance(concurrent_pool, ManagedFunboostThreadPool):
            concurrent_pool.shutdown()
            setattr(consumer, "_concurrent_pool", None)

    def _release_booster(
        self,
        booster: Booster,
        released_publisher_ids: set[int],
    ) -> None:
        """
        释放发布者资源。

        :param booster: 需要释放发布者的 Funboost Booster。
        :type booster: Booster
        :param released_publisher_ids: 已释放发布者对象标识集合。
        :type released_publisher_ids: set[int]
        :returns: 无返回值。
        :rtype: None
        """

        publisher = getattr(booster, "publisher", None)
        self._release_publisher(
            publisher=publisher,
            released_publisher_ids=released_publisher_ids,
        )

    def _release_publisher(
        self,
        publisher: object | None,
        released_publisher_ids: set[int],
    ) -> None:
        """
        释放发布者并注销退出期回调，避免解释器退出时重复写已关闭日志句柄。

        :param publisher: 需要释放的发布者对象。默认值：``None``。取值语义：为 ``None`` 时直接忽略。
        :type publisher: object | None
        :param released_publisher_ids: 已释放发布者对象标识集合。
        :type released_publisher_ids: set[int]
        :returns: 无返回值。
        :rtype: None
        """

        if publisher is None:
            return
        publisher_id = id(publisher)
        if publisher_id in released_publisher_ids:
            return
        released_publisher_ids.add(publisher_id)
        at_exit_callback = getattr(publisher, "_at_exit", None)
        if callable(at_exit_callback):
            atexit.unregister(at_exit_callback)
        closer = getattr(publisher, "close", None)
        if callable(closer):
            closer()

    def _collect_managed_queue_names(self) -> set[str]:
        """
        收集当前装配器管理的队列名称集合。

        :returns: 返回当前装配器管理的主队列与死信队列名称集合。
        :rtype: set[str]
        """

        queue_names: set[str] = set()
        for consumer in self._consumer_by_job_kind.values():
            queue_name = getattr(consumer, "queue_name", None)
            if not isinstance(queue_name, str):
                continue
            queue_names.add(queue_name)
            queue_names.add(f"{queue_name}_dlx")
        for detail in self._publisher_detail_by_job_kind.values():
            queue_names.add(detail.queue_name)
            queue_names.add(f"{detail.queue_name}_dlx")
        return queue_names

    def _release_cached_publishers(
        self,
        managed_queue_names: set[str],
        released_publisher_ids: set[int],
    ) -> None:
        """
        释放 Funboost 全局缓存中的发布者实例。

        :param managed_queue_names: 当前装配器管理的队列名称集合。
        :type managed_queue_names: set[str]
        :param released_publisher_ids: 已释放发布者对象标识集合。
        :type released_publisher_ids: set[int]
        :returns: 无返回值。
        :rtype: None
        """

        cache_map = PublisherCacheProxy.pid_registry_queue_name__publisher_map
        removable_keys = [
            cache_key
            for cache_key in list(cache_map.keys())
            if cache_key[1] == self._booster_registry_name and cache_key[2] in managed_queue_names
        ]
        for cache_key in removable_keys:
            publisher = cache_map.pop(cache_key, None)
            self._release_publisher(
                publisher=publisher,
                released_publisher_ids=released_publisher_ids,
            )

    def _release_cached_consumers(self) -> None:
        """释放当前装配器命名空间中的 Funboost 全局消费者缓存。"""

        cache_map = ConsumerCacheProxy.pid_registry_queue_name__consumer_map
        removable_keys = [
            cache_key
            for cache_key in list(cache_map.keys())
            if cache_key[1] == self._booster_registry_name
        ]
        for cache_key in removable_keys:
            cache_map.pop(cache_key, None)
        BoosterRegistry._instances.pop(self._booster_registry_name, None)

    def start_consumer(self, job_kind: str) -> None:
        """
        启动指定消费者。

        :param job_kind: 目标任务类型。
        :type job_kind: str
        :returns: 无返回值。
        :rtype: None
        """

        consumer = self._consumer_by_job_kind.get(job_kind)
        if consumer is None:
            return
        consumer.start_consuming_message()
