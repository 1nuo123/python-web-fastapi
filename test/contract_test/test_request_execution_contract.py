"""
请求执行契约测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.http_contract.request_execution_contract import (
    DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
    REQUEST_EXECUTION_ENVELOPE_KIND,
    NativeAsyncExecutionDetail,
    RequestExecutionEnvelope,
    RequestExecutionHeader,
    RequestExecutionMode,
    ThreadpoolExecutionDetail,
)

TEST_MAX_WORKERS = 2
TEST_MAX_PENDING_REQUESTS = 4
TEST_QUEUE_WAIT_TIMEOUT_SECONDS = 1


class TestRequestExecutionContract:
    """
    请求执行契约测试集合。
    """

    def test_envelope_when_threadpool_detail_should_keep_header_and_extension(
        self,
    ) -> None:
        """
        验证请求执行信封在线程池模式下应保持头与扩展一致。
        """

        envelope = RequestExecutionEnvelope(
            envelope_kind=REQUEST_EXECUTION_ENVELOPE_KIND,
            schema_version="1.0",
            header=RequestExecutionHeader(
                execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                enabled=True,
                mode=RequestExecutionMode.THREADPOOL,
            ),
            detail=ThreadpoolExecutionDetail(
                offload_timeout_seconds=5,
                max_workers=TEST_MAX_WORKERS,
                max_pending_requests=TEST_MAX_PENDING_REQUESTS,
                queue_wait_timeout_seconds=TEST_QUEUE_WAIT_TIMEOUT_SECONDS,
            ),
        )

        assert envelope.header.mode == RequestExecutionMode.THREADPOOL
        assert envelope.detail.kind == "threadpool"

    def test_envelope_when_mode_and_kind_mismatch_should_fail(self) -> None:
        """
        验证请求执行信封当外层模式与内层类型不一致应失败。
        """

        with pytest.raises(ValidationError) as exc_info:
            RequestExecutionEnvelope(
                envelope_kind=REQUEST_EXECUTION_ENVELOPE_KIND,
                schema_version="1.0",
                header=RequestExecutionHeader(
                    execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                    enabled=True,
                    mode=RequestExecutionMode.NATIVE_ASYNC,
                ),
                detail=ThreadpoolExecutionDetail(
                    offload_timeout_seconds=5,
                    max_workers=TEST_MAX_WORKERS,
                    max_pending_requests=TEST_MAX_PENDING_REQUESTS,
                    queue_wait_timeout_seconds=TEST_QUEUE_WAIT_TIMEOUT_SECONDS,
                ),
            )

        assert "mode 与 detail.kind 不一致" in str(exc_info.value)

    def test_detail_when_unknown_field_should_forbid_extra(self) -> None:
        """
        验证请求执行扩展体应禁止额外字段。
        """

        with pytest.raises(ValidationError):
            NativeAsyncExecutionDetail(
                kind="native_async",
                schema_version="1.0",
                propagate_cancellation=True,
                unexpected_field=True,
            )
