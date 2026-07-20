"""
数据库密钥环存储模块。
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable

from cryptography.fernet import Fernet
from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError

from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.cache_contract.cache_store_contract import CacheStore
from src.core.key_management_contract.key_ring_contract import KeyRingSnapshot
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.key_management.key_ring_store_contract import KeyRingStore
from src.infrastructure.persistence.orm_model.key_ring_snapshot_orm_model import (
    KeyRingSnapshotOrmModel,
)
from src.infrastructure.persistence.sqlalchemy_session_factory import SqlAlchemyUnitOfWork

KEY_RING_CACHE_SEGMENT = "key_ring"
KEY_RING_CACHE_TTL_SECONDS: int | None = None
TEXT_ENCODING = "utf-8"


class DatabaseKeyRingStore(KeyRingStore):
    """
    数据库权威密钥环存储，缓存仅作为读穿镜像。
    """

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], SqlAlchemyUnitOfWork],
        cache_store: CacheStore,
        key_builder: CacheKeyBuilder,
        encryption_secret: str,
    ) -> None:
        """
        初始化数据库密钥环存储。
        """

        self._unit_of_work_factory = unit_of_work_factory
        self._cache_store = cache_store
        self._key_builder = key_builder
        self._fernet = Fernet(self._derive_fernet_key(encryption_secret))

    def load_key_ring(self, key_family: str) -> KeyRingSnapshot | None:
        """
        从数据库读取密钥环，并刷新缓存镜像。
        """

        unit_of_work = self._unit_of_work_factory()
        try:
            row = self._get_row(unit_of_work, key_family)
            if row is None:
                return None
            snapshot = self._decrypt_snapshot(row.encrypted_snapshot_json)
            self._refresh_cache(snapshot)
            return snapshot
        finally:
            unit_of_work.dispose()

    def save_key_ring(self, snapshot: KeyRingSnapshot) -> None:
        """
        无条件保存密钥环。
        """

        unit_of_work = self._unit_of_work_factory()
        try:
            row = self._get_row(unit_of_work, snapshot.key_family)
            encrypted_snapshot = self._encrypt_snapshot(snapshot)
            version_digest = self._build_version_digest(snapshot)
            if row is None:
                row = KeyRingSnapshotOrmModel(
                    key_family=snapshot.key_family,
                    encrypted_snapshot_json=encrypted_snapshot,
                    version_digest=version_digest,
                )
                unit_of_work.get_session().add(row)
            else:
                row.encrypted_snapshot_json = encrypted_snapshot
                row.version_digest = version_digest
            unit_of_work.commit()
            self._refresh_cache(snapshot)
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def save_key_ring_if_absent(self, snapshot: KeyRingSnapshot) -> bool:
        """
        当数据库中不存在密钥族时保存初始密钥环。
        """

        unit_of_work = self._unit_of_work_factory()
        try:
            if self._get_row(unit_of_work, snapshot.key_family) is not None:
                return False
            row = KeyRingSnapshotOrmModel(
                key_family=snapshot.key_family,
                encrypted_snapshot_json=self._encrypt_snapshot(snapshot),
                version_digest=self._build_version_digest(snapshot),
            )
            unit_of_work.get_session().add(row)
            unit_of_work.commit()
            self._refresh_cache(snapshot)
            return True
        except IntegrityError:
            unit_of_work.rollback()
            return False
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def save_key_ring_if_version_matches(
        self,
        *,
        current_snapshot: KeyRingSnapshot,
        next_snapshot: KeyRingSnapshot,
    ) -> bool:
        """
        使用数据库版本摘要执行 CAS 保存。
        """

        unit_of_work = self._unit_of_work_factory()
        try:
            row = self._get_row(unit_of_work, current_snapshot.key_family)
            if row is None:
                return False
            if row.version_digest != self._build_version_digest(current_snapshot):
                return False
            row.encrypted_snapshot_json = self._encrypt_snapshot(next_snapshot)
            row.version_digest = self._build_version_digest(next_snapshot)
            unit_of_work.commit()
            self._refresh_cache(next_snapshot)
            return True
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _get_row(
        self,
        unit_of_work: SqlAlchemyUnitOfWork,
        key_family: str,
    ) -> KeyRingSnapshotOrmModel | None:
        """
        读取密钥环数据库行。
        """

        statement: Select[tuple[KeyRingSnapshotOrmModel]] = select(KeyRingSnapshotOrmModel).where(
            KeyRingSnapshotOrmModel.key_family == key_family
        )
        return unit_of_work.get_session().execute(statement).scalar_one_or_none()

    def _encrypt_snapshot(self, snapshot: KeyRingSnapshot) -> str:
        """
        加密密钥环快照 JSON。
        """

        return self._fernet.encrypt(snapshot.model_dump_json().encode(TEXT_ENCODING)).decode(
            TEXT_ENCODING
        )

    def _decrypt_snapshot(self, encrypted_snapshot_json: str) -> KeyRingSnapshot:
        """
        解密密钥环快照 JSON。
        """

        raw_snapshot = self._fernet.decrypt(encrypted_snapshot_json.encode(TEXT_ENCODING)).decode(
            TEXT_ENCODING
        )
        return KeyRingSnapshot.model_validate_json(raw_snapshot)

    def _refresh_cache(self, snapshot: KeyRingSnapshot) -> None:
        """
        刷新缓存镜像。
        """

        self._cache_store.set_value(
            self._build_cache_key(snapshot.key_family),
            snapshot.model_dump_json(),
            KEY_RING_CACHE_TTL_SECONDS,
        )

    def _build_cache_key(self, key_family: str) -> str:
        """
        构建缓存镜像键。
        """

        return self._key_builder.build(
            namespace=CacheNamespace.KEY_RING,
            key_parts=[KEY_RING_CACHE_SEGMENT, key_family],
        )

    def _build_version_digest(self, snapshot: KeyRingSnapshot) -> str:
        """
        构建密钥环快照版本摘要。
        """

        return hashlib.sha256(snapshot.model_dump_json().encode(TEXT_ENCODING)).hexdigest()

    def _derive_fernet_key(self, encryption_secret: str) -> bytes:
        """
        从运行时外部密钥派生 Fernet 密钥。
        """

        return base64.urlsafe_b64encode(
            hashlib.sha256(encryption_secret.encode(TEXT_ENCODING)).digest()
        )
