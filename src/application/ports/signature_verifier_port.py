"""通用签名校验应用端口。"""

from __future__ import annotations

from typing import Protocol

from src.core.cryptography_contract.signature_contract import SignatureVerificationRequest


class SignatureVerifierPort(Protocol):
    """验证成熟算法签名的窄端口。"""

    def verify(self, request: SignatureVerificationRequest) -> bool: ...
