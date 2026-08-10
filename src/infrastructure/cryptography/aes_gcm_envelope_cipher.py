"""HKDF-SHA256 与 AESGCM 通用 envelope 适配器。"""

from __future__ import annotations

import hashlib
import json
import secrets

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from src.core.cryptography_contract.aead_envelope_contract import (
    AeadAlgorithm,
    AeadContextItem,
    AeadDecryptionRequest,
    AeadEncryptionRequest,
    AeadEnvelope,
    AeadEnvelopeCipherPort,
)
from src.infrastructure.key_management.key_management_service import KeyManagementService

AES_GCM_NONCE_BYTES = 12
AES_256_KEY_BYTES = 32


class AesGcmEnvelopeCipher(AeadEnvelopeCipherPort):
    """组合 KeyManagementService 与 cryptography 密码原语。"""

    def __init__(self, *, key_management_service: KeyManagementService) -> None:
        self._key_management_service = key_management_service

    def encrypt(self, request: AeadEncryptionRequest) -> AeadEnvelope:
        descriptor = self._key_management_service.get_current_key(request.key_family)
        aad = self._build_aad(request.key_family, request.purpose, request.context)
        key = self._derive_key(
            descriptor.key_material,
            key_family=request.key_family,
            purpose=request.purpose,
        )
        nonce = secrets.token_bytes(AES_GCM_NONCE_BYTES)
        ciphertext = AESGCM(key).encrypt(nonce, request.plaintext, aad)
        return AeadEnvelope(
            algorithm=AeadAlgorithm.AES_256_GCM_HKDF_SHA256,
            key_id=descriptor.key_id,
            nonce=nonce,
            ciphertext=ciphertext,
            aad_digest=hashlib.sha256(aad).hexdigest(),
        )

    def decrypt(self, request: AeadDecryptionRequest) -> bytes:
        if request.envelope.algorithm != AeadAlgorithm.AES_256_GCM_HKDF_SHA256:
            raise ValueError("AEAD envelope算法不受支持。")
        descriptor = self._key_management_service.get_key_by_id(
            request.key_family,
            request.envelope.key_id,
        )
        aad = self._build_aad(request.key_family, request.purpose, request.context)
        if hashlib.sha256(aad).hexdigest() != request.envelope.aad_digest:
            raise ValueError("AEAD envelope上下文摘要不匹配。")
        key = self._derive_key(
            descriptor.key_material,
            key_family=request.key_family,
            purpose=request.purpose,
        )
        return AESGCM(key).decrypt(
            request.envelope.nonce,
            request.envelope.ciphertext,
            aad,
        )

    def _derive_key(self, key_material: str, *, key_family: str, purpose: str) -> bytes:
        info = f"{key_family}:{purpose}".encode()
        return HKDF(
            algorithm=hashes.SHA256(),
            length=AES_256_KEY_BYTES,
            salt=None,
            info=info,
        ).derive(key_material.encode())

    def _build_aad(
        self,
        key_family: str,
        purpose: str,
        context: tuple[AeadContextItem, ...],
    ) -> bytes:
        fields = [item.model_dump(mode="json") for item in context]
        return json.dumps(
            {
                "key_family": key_family,
                "purpose": purpose,
                "context": fields,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
