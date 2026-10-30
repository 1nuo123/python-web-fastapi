"""正文引用的用途隔离签名；引用不替代每次读取的所有权校验。"""

from uuid import UUID

import jwt
from pydantic import BaseModel, ConfigDict, Field

from src.core.codex_contract.agent_content_contract import (
    ContentField,
    ContentErrorCode,
    ContentReadError,
    ReadableContentDescriptor,
)


class CodexContentReferenceClaims(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    aud: str = Field(default="codex-content-v1", pattern="^codex-content-v1$")
    owner_subject_id: str = Field(min_length=1, max_length=128)
    host_id: UUID
    workspace_key: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=256)
    item_id: str = Field(min_length=1, max_length=256)
    field: ContentField
    revision: str = Field(min_length=1, max_length=128)
    handle: str = Field(min_length=1, max_length=128, repr=False)
    exp: int


class CodexContentReferenceCodec:
    def __init__(self, signing_key: bytes) -> None:
        if len(signing_key) < 32:
            raise ValueError("正文引用签名密钥至少32字节。")
        self._key = signing_key

    def encode(
        self,
        descriptor: ReadableContentDescriptor,
        *,
        owner_subject_id: str,
        host_id: UUID,
        workspace_key: str,
        thread_id: str,
        item_id: str,
    ) -> str:
        claims = CodexContentReferenceClaims(
            owner_subject_id=owner_subject_id,
            host_id=host_id,
            workspace_key=workspace_key,
            thread_id=thread_id,
            item_id=item_id,
            field=descriptor.field,
            revision=descriptor.revision,
            handle=descriptor.content_ref,
            exp=int(descriptor.expires_at.timestamp()),
        )
        return jwt.encode(claims.model_dump(mode="json"), self._key, algorithm="HS256")

    def decode(self, token: str) -> CodexContentReferenceClaims:
        try:
            value = jwt.decode(
                token,
                self._key,
                algorithms=["HS256"],
                audience="codex-content-v1",
                options={"require": ["exp", "aud"]},
            )
            return CodexContentReferenceClaims.model_validate(value)
        except (jwt.InvalidTokenError, ValueError) as exc:
            raise ContentReadError(ContentErrorCode.REFERENCE_EXPIRED) from exc
