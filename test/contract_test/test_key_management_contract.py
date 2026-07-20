"""
密钥管理契约测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.key_management_contract.key_management_contract import (
    KeyManagementBackend,
    KeyManagementRuntimeDetail,
    KeyManagementRuntimeEnvelope,
    KeyManagementRuntimeHeader,
    ManagedKeyFamilyEnvelope,
)
from src.core.key_management_contract.key_rotation_policy_contract import (
    KeyRotationPolicyEnvelope,
)


class TestKeyManagementContract:
    """
    密钥管理契约测试集合。
    """

    def test_runtime_contract_should_validate_key_family(self) -> None:
        """
        验证密钥管理运行时契约可承载密钥族和轮转策略。
        """

        envelope = KeyManagementRuntimeEnvelope(
            header=KeyManagementRuntimeHeader(
                enabled=True,
                policy_name="key_management_test",
            ),
            detail=KeyManagementRuntimeDetail(
                backend=KeyManagementBackend.CACHE,
                key_families=[
                    ManagedKeyFamilyEnvelope(
                        family_name="jwt_signing",
                        usage="jwt_signing",
                        enabled=True,
                        rotation_policy=KeyRotationPolicyEnvelope(
                            enabled=True,
                            rotation_interval_seconds=60,
                            active_key_count=2,
                        ),
                    )
                ],
            ),
        )

        assert envelope.detail.key_families[0].family_name == "jwt_signing"

    def test_key_family_when_extra_field_should_fail(self) -> None:
        """
        验证托管密钥族禁止额外字段。
        """

        with pytest.raises(ValidationError):
            ManagedKeyFamilyEnvelope.model_validate(
                {
                    "family_name": "jwt_signing",
                    "usage": "jwt_signing",
                    "enabled": True,
                    "rotation_policy": {
                        "enabled": True,
                        "rotation_interval_seconds": 60,
                        "active_key_count": 2,
                    },
                    "metadata": {},
                }
            )
