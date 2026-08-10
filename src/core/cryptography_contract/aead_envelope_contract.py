"""通用 AEAD envelope 与 cipher 契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class AeadAlgorithm(StrEnum):
    """受支持的 AEAD 算法。"""

    AES_256_GCM_HKDF_SHA256 = "aes-256-gcm+hkdf-sha256"


class AeadContextItem(BaseModel):
    """AAD 上下文字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=512)


class AeadEncryptionRequest(BaseModel):
    """明文、密钥族、purpose 与完整上下文。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key_family: str = Field(min_length=1, max_length=128)
    purpose: str = Field(min_length=1, max_length=128)
    context: tuple[AeadContextItem, ...] = Field(min_length=1)
    plaintext: bytes = Field(min_length=1, max_length=10_485_760)


class AeadEnvelope(BaseModel):
    """不含 key material 的密文信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    algorithm: AeadAlgorithm
    key_id: str = Field(min_length=1, max_length=128)
    nonce: bytes = Field(min_length=12, max_length=12)
    ciphertext: bytes = Field(min_length=17, max_length=10_485_776)
    aad_digest: str = Field(min_length=64, max_length=64)


class AeadDecryptionRequest(BaseModel):
    """解密信封与调用方重建的 AAD。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key_family: str = Field(min_length=1, max_length=128)
    purpose: str = Field(min_length=1, max_length=128)
    context: tuple[AeadContextItem, ...] = Field(min_length=1)
    envelope: AeadEnvelope


class AeadEnvelopeCipherPort(Protocol):
    """通用 AEAD 加解密端口。"""

    def encrypt(self, request: AeadEncryptionRequest) -> AeadEnvelope: ...

    def decrypt(self, request: AeadDecryptionRequest) -> bytes: ...
