"""运行时容量策略单元测试模块。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.cache_contract.cache_runtime_contract import MemoryCacheBackendDetail
from src.core.concurrency_contract.runtime_capacity_contract import (
    BoundedRuntimeCapacityDetail,
    RuntimeCapacityHeader,
    RuntimeCapacityPolicy,
)
from src.core.http_contract.request_execution_contract import ThreadpoolExecutionDetail
from src.core.task_contract.task_runtime_contract import LocalMessageBackendDetail
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import AppEnvironment
from src.infrastructure.settings.runtime_capacity_policy_resolver import (
    RuntimeCapacityPolicyResolver,
)

CAPACITY_TEST_MINIMUM = 1
CAPACITY_TEST_CONNECTION_LIMIT = 2
CAPACITY_TEST_KEEPALIVE_LIMIT = 1
CAPACITY_TEST_UNKNOWN_FIELD = "unknown_capacity"
HTTP_KEEPALIVE_LIMIT_INVALID_MESSAGE = "HTTP 保活连接上限不能超过总连接上限。"


class TestRuntimeCapacityPolicyUnit:
    """运行时容量策略单元测试集合。"""

    def test_resolver_when_test_settings_loaded_should_expose_all_bounded_resources(
        self,
    ) -> None:
        """验证解析器把各资源域容量统一映射到强类型策略。"""

        settings = AppSettingsLoader().load_for_environment(AppEnvironment.TEST)
        request_detail = settings.runtime.web.request_execution.detail
        cache_detail = settings.runtime.cache.backend_detail
        message_detail = settings.runtime.message.backend_detail

        assert isinstance(request_detail, ThreadpoolExecutionDetail)
        assert isinstance(cache_detail, MemoryCacheBackendDetail)
        assert isinstance(message_detail, LocalMessageBackendDetail)

        policy = RuntimeCapacityPolicyResolver().resolve(settings)

        assert policy.detail.database_connection_limit == (
            settings.runtime.database.pool_size + settings.runtime.database.max_overflow
        )
        assert policy.detail.request_worker_limit == request_detail.max_workers
        assert policy.detail.request_pending_limit == request_detail.max_pending_requests
        assert policy.detail.outbound_http_connection_limit == (
            settings.runtime.web.outbound_http_client.detail.max_connections
        )
        assert policy.detail.cache_connection_limit == cache_detail.max_entries
        assert policy.detail.message_queue_limit == message_detail.max_items
        assert policy.detail.log_queue_limit == settings.runtime.logging.buffer_max_items

    def test_policy_when_unknown_field_provided_should_reject_contract(self) -> None:
        """验证容量扩展字段拒绝未声明字段。"""

        raw_detail = self._build_detail().model_dump(mode="python")
        raw_detail[CAPACITY_TEST_UNKNOWN_FIELD] = CAPACITY_TEST_MINIMUM

        with pytest.raises(ValidationError):
            BoundedRuntimeCapacityDetail.model_validate(raw_detail)

    def test_policy_when_keepalive_exceeds_connections_should_reject(self) -> None:
        """验证 HTTP 保活容量不能超过总连接容量。"""

        detail = self._build_detail(
            outbound_http_connection_limit=CAPACITY_TEST_KEEPALIVE_LIMIT,
            outbound_http_keepalive_limit=CAPACITY_TEST_CONNECTION_LIMIT,
        )

        with pytest.raises(ValueError, match=HTTP_KEEPALIVE_LIMIT_INVALID_MESSAGE):
            RuntimeCapacityPolicy(
                header=RuntimeCapacityHeader(),
                detail=detail,
            )

    def _build_detail(
        self,
        *,
        outbound_http_connection_limit: int = CAPACITY_TEST_CONNECTION_LIMIT,
        outbound_http_keepalive_limit: int = CAPACITY_TEST_KEEPALIVE_LIMIT,
    ) -> BoundedRuntimeCapacityDetail:
        """构建容量策略测试扩展字段。"""

        return BoundedRuntimeCapacityDetail(
            database_connection_limit=CAPACITY_TEST_MINIMUM,
            request_worker_limit=CAPACITY_TEST_MINIMUM,
            request_pending_limit=CAPACITY_TEST_MINIMUM,
            request_queue_wait_timeout_seconds=CAPACITY_TEST_MINIMUM,
            request_offload_timeout_seconds=CAPACITY_TEST_MINIMUM,
            outbound_http_connection_limit=outbound_http_connection_limit,
            outbound_http_keepalive_limit=outbound_http_keepalive_limit,
            outbound_http_timeout_seconds=CAPACITY_TEST_MINIMUM,
            cache_connection_limit=CAPACITY_TEST_MINIMUM,
            task_worker_limit=CAPACITY_TEST_MINIMUM,
            message_queue_limit=CAPACITY_TEST_MINIMUM,
            log_queue_limit=CAPACITY_TEST_MINIMUM,
        )
