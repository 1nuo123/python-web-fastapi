"""Agent 设备私钥存储端口。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class AgentDeviceKeyStorePort(Protocol):
    """隔离设备密钥生成、读取、签名与删除能力。"""

    def generate(self, key_id: UUID) -> bytes: ...

    def read_public_key(self, key_id: UUID) -> bytes: ...

    def sign(self, key_id: UUID, message: bytes) -> bytes: ...

    def delete(self, key_id: UUID) -> None: ...
