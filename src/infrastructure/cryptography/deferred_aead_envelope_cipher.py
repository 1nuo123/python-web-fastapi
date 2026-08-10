"""延迟解析生命周期内 KeyManagementService 的 AEAD cipher。"""

from __future__ import annotations

from collections.abc import Callable

from src.core.cryptography_contract.aead_envelope_contract import (
    AeadDecryptionRequest,
    AeadEncryptionRequest,
    AeadEnvelope,
    AeadEnvelopeCipherPort,
)
from src.infrastructure.cryptography.aes_gcm_envelope_cipher import AesGcmEnvelopeCipher
from src.infrastructure.key_management.key_management_service import KeyManagementService


class DeferredAeadEnvelopeCipher(AeadEnvelopeCipherPort):
    """不拥有密钥资源，只在调用时解析唯一服务。"""

    def __init__(self, provider: Callable[[], KeyManagementService]) -> None:
        self._provider = provider

    def encrypt(self, request: AeadEncryptionRequest) -> AeadEnvelope:
        return AesGcmEnvelopeCipher(key_management_service=self._provider()).encrypt(request)

    def decrypt(self, request: AeadDecryptionRequest) -> bytes:
        return AesGcmEnvelopeCipher(key_management_service=self._provider()).decrypt(request)
