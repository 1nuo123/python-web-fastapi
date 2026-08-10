"""cryptography Ed25519 签名校验薄适配器。"""

from __future__ import annotations

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from src.application.ports.signature_verifier_port import SignatureVerifierPort
from src.core.cryptography_contract.signature_contract import (
    SignatureAlgorithm,
    SignatureVerificationRequest,
)


class Ed25519SignatureVerifier(SignatureVerifierPort):
    """直接委托 cryptography，不实现曲线或编码算法。"""

    def verify(self, request: SignatureVerificationRequest) -> bool:
        """验证 Ed25519 签名；无效签名返回 false。"""

        if request.algorithm != SignatureAlgorithm.ED25519:
            raise ValueError("签名算法不受支持。")
        try:
            Ed25519PublicKey.from_public_bytes(request.public_key).verify(
                request.signature,
                request.message,
            )
        except InvalidSignature:
            return False
        return True
