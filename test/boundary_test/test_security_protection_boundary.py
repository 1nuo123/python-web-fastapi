"""
安全防护边界测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.concurrency_contract.distributed_lock_contract import (
    DistributedLockRequest,
)
from src.core.key_management_contract.key_rotation_policy_contract import (
    KeyRotationPolicyEnvelope,
)


class TestSecurityProtectionBoundary:
    """
    安全防护边界测试集合。
    """

    def test_lock_and_rotation_boundary_should_reject_non_positive_values(self) -> None:
        """
        验证锁租约和轮转周期必须为正数。
        """

        with pytest.raises(ValidationError):
            DistributedLockRequest(
                namespace="unit",
                key_digest="1234567890abcdef",
                owner="owner",
                lease_seconds=0,
                wait_seconds=0,
            )
        with pytest.raises(ValidationError):
            KeyRotationPolicyEnvelope(
                enabled=True,
                rotation_interval_seconds=0,
                active_key_count=1,
            )
