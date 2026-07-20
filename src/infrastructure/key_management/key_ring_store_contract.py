"""
密钥环存储基础设施契约模块。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.core.key_management_contract.key_ring_contract import KeyRingSnapshot


class KeyRingStore(ABC):
    """
    密钥环存储抽象基类。
    """

    @abstractmethod
    def load_key_ring(self, key_family: str) -> KeyRingSnapshot | None:
        """
        读取密钥环。
        """

    @abstractmethod
    def save_key_ring(self, snapshot: KeyRingSnapshot) -> None:
        """
        保存密钥环。
        """

    @abstractmethod
    def save_key_ring_if_absent(self, snapshot: KeyRingSnapshot) -> bool:
        """
        当密钥环不存在时保存。
        """

    @abstractmethod
    def save_key_ring_if_version_matches(
        self,
        *,
        current_snapshot: KeyRingSnapshot,
        next_snapshot: KeyRingSnapshot,
    ) -> bool:
        """
        当当前版本匹配时保存。
        """
