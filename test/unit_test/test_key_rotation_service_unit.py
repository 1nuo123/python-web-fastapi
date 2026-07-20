"""
密钥轮转服务单元测试模块。
"""

from __future__ import annotations

from src.core.key_management_contract.key_rotation_policy_contract import (
    KeyRotationPolicyEnvelope,
)
from src.infrastructure.key_management.key_rotation_service import KeyRotationService


class TestKeyRotationServiceUnit:
    """
    密钥轮转服务单元测试集合。
    """

    def test_rotate_when_due_should_switch_current_key(self) -> None:
        """
        验证到期轮转会切换 current key 并保留旧 key。
        """

        current_time = 1000.0
        service = KeyRotationService(timer=lambda: current_time)
        policy = KeyRotationPolicyEnvelope(
            enabled=True,
            rotation_interval_seconds=10,
            active_key_count=2,
        )
        snapshot = service.build_initial_key_ring(
            key_family="jwt_signing",
            rotation_policy=policy,
        )
        current_time = 1011.0

        rotated_snapshot = service.rotate_if_due(snapshot, policy)

        assert rotated_snapshot.current_key_id != snapshot.current_key_id
        assert len(rotated_snapshot.keys) == 2

    def test_rotate_should_keep_previous_current_key_in_compatibility_window(self) -> None:
        """
        验证旧 current key 在兼容窗口内仍保留为有效候选。
        """

        current_time = 1000.0
        service = KeyRotationService(timer=lambda: current_time)
        policy = KeyRotationPolicyEnvelope(
            enabled=True,
            rotation_interval_seconds=10,
            active_key_count=2,
            compatibility_window_seconds=30,
        )
        snapshot = service.build_initial_key_ring(
            key_family="jwt_signing",
            rotation_policy=policy,
        )
        previous_key_id = snapshot.current_key_id
        current_time = 1011.0

        rotated_snapshot = service.rotate_if_due(snapshot, policy)
        previous_key = [key for key in rotated_snapshot.keys if key.key_id == previous_key_id][0]

        assert previous_key.expires_at_epoch == 1041
        assert previous_key_id in rotated_snapshot.candidate_key_ids
