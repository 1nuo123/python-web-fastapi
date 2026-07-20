"""
密钥轮转服务模块。
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable

from src.core.key_management_contract.key_ring_contract import (
    KeyRingSnapshot,
    ManagedKeyDescriptor,
    ManagedKeyStatus,
)
from src.core.key_management_contract.key_rotation_policy_contract import (
    KeyRotationPolicyEnvelope,
)

KEY_ID_HEX_LENGTH = 12
KEY_MATERIAL_TOKEN_BYTES = 32


class KeyRotationService:
    """
    密钥轮转服务。
    """

    def __init__(self, *, timer: Callable[[], float] | None = None) -> None:
        """
        初始化密钥轮转服务。
        """

        self._timer = timer or time.time

    def build_initial_key_ring(
        self,
        *,
        key_family: str,
        rotation_policy: KeyRotationPolicyEnvelope,
    ) -> KeyRingSnapshot:
        """
        构建初始密钥环。
        """

        current_epoch = int(self._timer())
        key_descriptor = self._build_key_descriptor(
            status=ManagedKeyStatus.CURRENT,
            not_before_epoch=current_epoch,
            expires_at_epoch=current_epoch + rotation_policy.rotation_interval_seconds,
        )
        return KeyRingSnapshot(
            key_family=key_family,
            current_key_id=key_descriptor.key_id,
            candidate_key_ids=[key_descriptor.key_id],
            valid_key_digests=[key_descriptor.key_digest],
            next_rotation_epoch=current_epoch + rotation_policy.rotation_interval_seconds,
            keys=[key_descriptor],
        )

    def rotate_if_due(
        self,
        snapshot: KeyRingSnapshot,
        rotation_policy: KeyRotationPolicyEnvelope,
    ) -> KeyRingSnapshot:
        """
        到期时轮转密钥环。
        """

        current_epoch = int(self._timer())
        if not rotation_policy.enabled or current_epoch < snapshot.next_rotation_epoch:
            return snapshot
        previous_keys = [
            key.model_copy(
                update={
                    "status": ManagedKeyStatus.ACTIVE,
                    "expires_at_epoch": max(
                        key.expires_at_epoch,
                        current_epoch + rotation_policy.compatibility_window_seconds,
                    ),
                }
            )
            for key in snapshot.keys
            if key.status == ManagedKeyStatus.CURRENT or key.expires_at_epoch > current_epoch
        ]
        next_key = self._build_key_descriptor(
            status=ManagedKeyStatus.CURRENT,
            not_before_epoch=current_epoch,
            expires_at_epoch=current_epoch + rotation_policy.rotation_interval_seconds,
        )
        retained_keys = [next_key, *previous_keys][: rotation_policy.active_key_count]
        return KeyRingSnapshot(
            key_family=snapshot.key_family,
            current_key_id=next_key.key_id,
            candidate_key_ids=[key.key_id for key in retained_keys],
            valid_key_digests=[key.key_digest for key in retained_keys],
            next_rotation_epoch=current_epoch + rotation_policy.rotation_interval_seconds,
            keys=retained_keys,
        )

    def read_current_epoch(self) -> int:
        """
        读取当前 Unix 时间戳秒值。
        """

        return int(self._timer())

    def _build_key_descriptor(
        self,
        *,
        status: ManagedKeyStatus,
        not_before_epoch: int,
        expires_at_epoch: int,
    ) -> ManagedKeyDescriptor:
        """
        构建托管密钥描述。
        """

        key_material = secrets.token_urlsafe(KEY_MATERIAL_TOKEN_BYTES)
        key_digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
        return ManagedKeyDescriptor(
            key_id=key_digest[:KEY_ID_HEX_LENGTH],
            key_digest=key_digest,
            key_material=key_material,
            status=status,
            not_before_epoch=not_before_epoch,
            expires_at_epoch=expires_at_epoch,
        )
