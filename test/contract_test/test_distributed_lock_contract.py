"""
分布式锁契约测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.concurrency_contract.distributed_lock_contract import (
    DistributedLockBackend,
    DistributedLockRequest,
    DistributedLockRuntimeDetail,
    DistributedLockRuntimeEnvelope,
    DistributedLockRuntimeHeader,
)

LOCK_DIGEST = "1234567890abcdef"
LOCK_OWNER = "owner-1"


class TestDistributedLockContract:
    """
    分布式锁契约测试集合。
    """

    def test_runtime_contract_should_validate_header_and_detail(self) -> None:
        """
        验证运行时信封应校验公共头和强类型扩展字段。
        """

        envelope = DistributedLockRuntimeEnvelope(
            header=DistributedLockRuntimeHeader(
                enabled=True,
                policy_name="test_lock",
            ),
            detail=DistributedLockRuntimeDetail(
                backend=DistributedLockBackend.CACHE,
                lease_seconds=5,
                wait_seconds=0,
            ),
        )

        assert envelope.detail.backend == DistributedLockBackend.CACHE

    def test_request_when_extra_field_should_fail(self) -> None:
        """
        验证请求契约禁止额外字段。
        """

        with pytest.raises(ValidationError):
            DistributedLockRequest.model_validate(
                {
                    "namespace": "unit",
                    "key_digest": LOCK_DIGEST,
                    "owner": LOCK_OWNER,
                    "lease_seconds": 5,
                    "wait_seconds": 0,
                    "unexpected": "value",
                }
            )

    def test_runtime_detail_when_legacy_failure_mode_should_fail(self) -> None:
        """
        验证旧 failure_mode 配置字段不再被运行时契约接受。
        """

        with pytest.raises(ValidationError):
            DistributedLockRuntimeDetail.model_validate(
                {
                    "backend": DistributedLockBackend.CACHE,
                    "lease_seconds": 5,
                    "wait_seconds": 0,
                    "failure_mode": "fail_closed",
                }
            )
