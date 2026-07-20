"""
统一密钥管理服务模块。
"""

from __future__ import annotations

import hashlib
import uuid
from http import HTTPStatus

from src.core.concurrency_contract.distributed_lock_contract import (
    DistributedLockRequest,
)
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.key_management_contract.key_management_contract import (
    ManagedKeyFamilyEnvelope,
)
from src.core.key_management_contract.key_ring_contract import (
    KeyRingSnapshot,
    ManagedKeyDescriptor,
    ManagedKeyStatus,
)
from src.infrastructure.concurrency.distributed_lock_provider import (
    DistributedLockProvider,
)
from src.infrastructure.key_management.key_ring_store_contract import KeyRingStore
from src.infrastructure.key_management.key_rotation_service import KeyRotationService

KEY_ROTATION_LOCK_NAMESPACE = "key_rotation"
KEY_ROTATION_LOCK_LEASE_SECONDS = 30
KEY_ROTATION_LOCK_WAIT_SECONDS = 0
KEY_MANAGEMENT_KEY_MISSING_MESSAGE = "密钥族尚未初始化。"
KEY_MANAGEMENT_CURRENT_KEY_MISSING_MESSAGE = "当前密钥不存在。"
KEY_MANAGEMENT_KEY_ID_MISSING_MESSAGE = "指定密钥不存在或已过期。"
KEY_MANAGEMENT_VALID_KEY_MISSING_MESSAGE = "密钥族没有有效密钥。"
KEY_MANAGEMENT_INITIALIZE_CAS_FAILED_MESSAGE = "密钥族初始化 CAS 写入失败。"
KEY_MANAGEMENT_ROTATION_CAS_FAILED_MESSAGE = "密钥族轮转 CAS 写入失败。"


class KeyManagementService:
    """
    统一密钥管理服务。
    """

    def __init__(
        self,
        *,
        key_ring_store: KeyRingStore,
        key_rotation_service: KeyRotationService,
        distributed_lock_provider: DistributedLockProvider,
        rotation_lock_lease_seconds: int = KEY_ROTATION_LOCK_LEASE_SECONDS,
        rotation_lock_wait_seconds: int = KEY_ROTATION_LOCK_WAIT_SECONDS,
    ) -> None:
        """
        初始化密钥管理服务。
        """

        self._key_ring_store = key_ring_store
        self._key_rotation_service = key_rotation_service
        self._distributed_lock_provider = distributed_lock_provider
        self._rotation_lock_lease_seconds = rotation_lock_lease_seconds
        self._rotation_lock_wait_seconds = rotation_lock_wait_seconds
        self._known_key_families: dict[str, ManagedKeyFamilyEnvelope] = {}

    def initialize_key_family(self, key_family: ManagedKeyFamilyEnvelope) -> KeyRingSnapshot:
        """
        幂等初始化密钥族。
        """

        lock_request = self._build_lock_request(key_family.family_name)
        lease = self._distributed_lock_provider.acquire(lock_request)
        try:
            return self._initialize_key_family_unlocked(key_family)
        finally:
            self._distributed_lock_provider.release(lease)

    def _initialize_key_family_unlocked(
        self,
        key_family: ManagedKeyFamilyEnvelope,
    ) -> KeyRingSnapshot:
        """
        在外层锁保护下幂等初始化密钥族。
        """

        self._known_key_families[key_family.family_name] = key_family
        existing_snapshot = self._key_ring_store.load_key_ring(key_family.family_name)
        if existing_snapshot is not None:
            return existing_snapshot
        snapshot = self._key_rotation_service.build_initial_key_ring(
            key_family=key_family.family_name,
            rotation_policy=key_family.rotation_policy,
        )
        if self._key_ring_store.save_key_ring_if_absent(snapshot):
            return snapshot
        concurrent_snapshot = self._key_ring_store.load_key_ring(key_family.family_name)
        if concurrent_snapshot is not None:
            return concurrent_snapshot
        raise HttpFaultException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            error_code=CoreErrorCode.RESOURCE_NOT_READY,
            message=KEY_MANAGEMENT_INITIALIZE_CAS_FAILED_MESSAGE,
        )

    def rotate_key_family_if_due(
        self,
        key_family: ManagedKeyFamilyEnvelope,
    ) -> KeyRingSnapshot:
        """
        在独立分布式锁保护下按需轮转密钥族。
        """

        lock_request = self._build_lock_request(key_family.family_name)
        lease = self._distributed_lock_provider.acquire(lock_request)
        try:
            snapshot = self._initialize_key_family_unlocked(key_family)
            rotated_snapshot = self._key_rotation_service.rotate_if_due(
                snapshot,
                key_family.rotation_policy,
            )
            if rotated_snapshot != snapshot:
                if not self._key_ring_store.save_key_ring_if_version_matches(
                    current_snapshot=snapshot,
                    next_snapshot=rotated_snapshot,
                ):
                    raise HttpFaultException(
                        status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                        error_code=CoreErrorCode.RESOURCE_NOT_READY,
                        message=KEY_MANAGEMENT_ROTATION_CAS_FAILED_MESSAGE,
                    )
            return rotated_snapshot
        finally:
            self._distributed_lock_provider.release(lease)

    def get_key_ring_snapshot(self, key_family: str) -> KeyRingSnapshot:
        """
        读取有效密钥环快照。
        """

        self._rotate_known_key_family_if_due(key_family)
        snapshot = self._key_ring_store.load_key_ring(key_family)
        if snapshot is None:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=KEY_MANAGEMENT_KEY_MISSING_MESSAGE,
            )
        return self._filter_valid_snapshot(snapshot)

    def get_current_key(self, key_family: str) -> ManagedKeyDescriptor:
        """
        读取当前密钥。
        """

        snapshot = self.get_key_ring_snapshot(key_family)
        for key_descriptor in snapshot.keys:
            if key_descriptor.key_id == snapshot.current_key_id:
                return key_descriptor
        raise HttpFaultException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            error_code=CoreErrorCode.RESOURCE_NOT_READY,
            message=KEY_MANAGEMENT_CURRENT_KEY_MISSING_MESSAGE,
        )

    def get_key_by_id(self, key_family: str, key_id: str) -> ManagedKeyDescriptor:
        """
        按 key id 读取仍处于有效窗口内的密钥。
        """

        snapshot = self.get_key_ring_snapshot(key_family)
        for key_descriptor in snapshot.keys:
            if key_descriptor.key_id == key_id:
                return key_descriptor
        raise HttpFaultException(
            status_code=HTTPStatus.SERVICE_UNAVAILABLE,
            error_code=CoreErrorCode.RESOURCE_NOT_READY,
            message=KEY_MANAGEMENT_KEY_ID_MISSING_MESSAGE,
        )

    def _filter_valid_snapshot(self, snapshot: KeyRingSnapshot) -> KeyRingSnapshot:
        """
        过滤已过期密钥并刷新快照摘要字段。
        """

        current_epoch = int(self._key_rotation_service.read_current_epoch())
        valid_keys = [
            key_descriptor
            for key_descriptor in snapshot.keys
            if key_descriptor.status in {ManagedKeyStatus.CURRENT, ManagedKeyStatus.ACTIVE}
            and key_descriptor.not_before_epoch <= current_epoch
            and key_descriptor.expires_at_epoch > current_epoch
        ]
        if len(valid_keys) == 0:
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.RESOURCE_NOT_READY,
                message=KEY_MANAGEMENT_VALID_KEY_MISSING_MESSAGE,
            )
        return snapshot.model_copy(
            update={
                "keys": valid_keys,
                "candidate_key_ids": [key.key_id for key in valid_keys],
                "valid_key_digests": [key.key_digest for key in valid_keys],
            }
        )

    def _rotate_known_key_family_if_due(self, key_family: str) -> None:
        """
        对已注册密钥族执行读取前按需轮转。
        """

        known_key_family = self._known_key_families.get(key_family)
        if known_key_family is None:
            return
        snapshot = self._key_ring_store.load_key_ring(key_family)
        current_epoch = int(self._key_rotation_service.read_current_epoch())
        if snapshot is not None and current_epoch < snapshot.next_rotation_epoch:
            return
        self.rotate_key_family_if_due(known_key_family)

    def _build_lock_request(self, key_family: str) -> DistributedLockRequest:
        """
        构建密钥族分布式锁请求。
        """

        return DistributedLockRequest(
            namespace=KEY_ROTATION_LOCK_NAMESPACE,
            key_digest=hashlib.sha256(key_family.encode("utf-8")).hexdigest(),
            owner=str(uuid.uuid4()),
            lease_seconds=self._rotation_lock_lease_seconds,
            wait_seconds=self._rotation_lock_wait_seconds,
        )
