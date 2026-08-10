"""运行时容量策略解析器基础设施模块。"""

from __future__ import annotations

from src.core.cache_contract.cache_runtime_contract import (
    MemoryCacheBackendDetail,
    RedisCacheBackendDetail,
)
from src.core.concurrency_contract.runtime_capacity_contract import (
    BoundedRuntimeCapacityDetail,
    RuntimeCapacityHeader,
    RuntimeCapacityPolicy,
)
from src.core.http_contract.request_execution_contract import (
    NativeAsyncExecutionDetail,
    ThreadpoolExecutionDetail,
)
from src.core.task_contract.task_registration_contract import FunboostTaskRegistrationDetail
from src.core.task_contract.task_runtime_contract import LocalMessageBackendDetail
from src.infrastructure.settings.application_settings import ApplicationSettings

NATIVE_ASYNC_WORKER_LIMIT = 0
NATIVE_ASYNC_PENDING_LIMIT = 0
NATIVE_ASYNC_TIMEOUT_SECONDS = 0
DISABLED_TASK_WORKER_LIMIT = 0
LOCAL_TASK_WORKER_LIMIT = 1


class RuntimeCapacityPolicyResolver:
    """从已校验配置解析统一有界容量策略。"""

    def resolve(self, settings: ApplicationSettings) -> RuntimeCapacityPolicy:
        """解析运行时容量策略。

        :param settings: 已校验应用配置。
        :type settings: ApplicationSettings
        :returns: 统一运行时容量策略。
        :rtype: RuntimeCapacityPolicy
        """

        request_detail = settings.runtime.web.request_execution.detail
        if isinstance(request_detail, ThreadpoolExecutionDetail):
            request_worker_limit = request_detail.max_workers
            request_pending_limit = request_detail.max_pending_requests
            queue_wait_timeout_seconds = request_detail.queue_wait_timeout_seconds
            offload_timeout_seconds = request_detail.offload_timeout_seconds
        elif isinstance(request_detail, NativeAsyncExecutionDetail):
            request_worker_limit = NATIVE_ASYNC_WORKER_LIMIT
            request_pending_limit = NATIVE_ASYNC_PENDING_LIMIT
            queue_wait_timeout_seconds = NATIVE_ASYNC_TIMEOUT_SECONDS
            offload_timeout_seconds = NATIVE_ASYNC_TIMEOUT_SECONDS
        else:
            raise TypeError("不支持的请求执行容量配置。")

        http_detail = settings.runtime.web.outbound_http_client.detail
        cache_detail = settings.runtime.cache.backend_detail
        if isinstance(cache_detail, MemoryCacheBackendDetail):
            cache_connection_limit = cache_detail.max_entries
        elif isinstance(cache_detail, RedisCacheBackendDetail):
            cache_connection_limit = settings.runtime.redis_resource.detail.sync_max_connections
        else:
            raise TypeError("不支持的缓存容量配置。")

        message_detail = settings.runtime.message.backend_detail
        message_queue_limit = (
            message_detail.max_items
            if isinstance(message_detail, LocalMessageBackendDetail)
            else message_detail.queue_max_length
        )
        return RuntimeCapacityPolicy(
            header=RuntimeCapacityHeader(),
            detail=BoundedRuntimeCapacityDetail(
                database_connection_limit=(
                    settings.runtime.database.pool_size + settings.runtime.database.max_overflow
                ),
                request_worker_limit=request_worker_limit,
                request_pending_limit=request_pending_limit,
                request_queue_wait_timeout_seconds=queue_wait_timeout_seconds,
                request_offload_timeout_seconds=offload_timeout_seconds,
                outbound_http_connection_limit=http_detail.max_connections,
                outbound_http_keepalive_limit=http_detail.max_keepalive_connections,
                outbound_http_timeout_seconds=http_detail.timeout_seconds,
                cache_connection_limit=cache_connection_limit,
                task_worker_limit=self._resolve_task_worker_limit(settings),
                message_queue_limit=message_queue_limit,
                log_queue_limit=settings.runtime.logging.buffer_max_items,
            ),
        )

    def _resolve_task_worker_limit(self, settings: ApplicationSettings) -> int:
        """解析当前节点任务消费者容量。

        :param settings: 已校验应用配置。
        :type settings: ApplicationSettings
        :returns: 任务消费者上限。
        :rtype: int
        """

        if not settings.runtime.task.worker_enabled:
            return DISABLED_TASK_WORKER_LIMIT
        funboost_worker_limit = sum(
            registration.detail.consumer_worker_count
            for registration in settings.modules.task.registrations
            if registration.header.enabled
            and isinstance(registration.detail, FunboostTaskRegistrationDetail)
        )
        return funboost_worker_limit or LOCAL_TASK_WORKER_LIMIT
