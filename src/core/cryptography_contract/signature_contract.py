"""通用数字签名输入与算法契约。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SignatureAlgorithm(StrEnum):
    """允许的签名算法封闭集合。"""

    ED25519 = "ed25519"


class SignatureVerificationRequest(BaseModel):
    """不包含业务对象的签名校验请求。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    algorithm: SignatureAlgorithm
    public_key: bytes = Field(min_length=32, max_length=32)
    message: bytes = Field(min_length=1, max_length=65_536)
    signature: bytes = Field(min_length=64, max_length=64)
