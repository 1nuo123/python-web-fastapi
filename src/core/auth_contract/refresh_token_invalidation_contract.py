"""
刷新令牌失效命令契约核心模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REFRESH_TOKEN_INVALIDATION_SCHEMA_VERSION: Final = "1.0"
REFRESH_TOKEN_INVALIDATION_HEADER_KIND: Final = "refresh_token_invalidation_header"
REFRESH_TOKEN_INVALIDATION_ENVELOPE_KIND: Final = "refresh_token_invalidation_envelope"
ALL_REFRESH_TOKEN_SESSIONS_KIND: Final = "all_refresh_token_sessions"
SUBJECT_REFRESH_TOKEN_SESSIONS_KIND: Final = "subject_refresh_token_sessions"
TOKEN_SESSION_KIND: Final = "token_session"
SUBJECT_ID_MINIMUM_LENGTH = 1
TOKEN_SESSION_ID_MINIMUM_LENGTH = 1


class RefreshTokenInvalidationMode(StrEnum):
    """
    刷新令牌失效模式枚举。
    """

    ALL = ALL_REFRESH_TOKEN_SESSIONS_KIND
    SUBJECT = SUBJECT_REFRESH_TOKEN_SESSIONS_KIND
    TOKEN_SESSION = TOKEN_SESSION_KIND


class RefreshTokenInvalidationHeader(BaseModel):
    """
    刷新令牌失效命令公共头。

    :ivar kind: 公共头类型标识。
    :vartype kind: Literal[REFRESH_TOKEN_INVALIDATION_HEADER_KIND]
    :ivar schema_version: 结构模式版本。
    :vartype schema_version: Literal[REFRESH_TOKEN_INVALIDATION_SCHEMA_VERSION]
    :ivar mode: 失效模式。
    :vartype mode: RefreshTokenInvalidationMode
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["refresh_token_invalidation_header"] = REFRESH_TOKEN_INVALIDATION_HEADER_KIND
    schema_version: Literal["1.0"] = REFRESH_TOKEN_INVALIDATION_SCHEMA_VERSION
    mode: RefreshTokenInvalidationMode


class AllRefreshTokenSessionsDetail(BaseModel):
    """
    全量刷新令牌会话失效扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["all_refresh_token_sessions"] = ALL_REFRESH_TOKEN_SESSIONS_KIND
    schema_version: Literal["1.0"] = REFRESH_TOKEN_INVALIDATION_SCHEMA_VERSION


class SubjectRefreshTokenSessionsDetail(BaseModel):
    """
    指定主体刷新令牌会话失效扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["subject_refresh_token_sessions"] = SUBJECT_REFRESH_TOKEN_SESSIONS_KIND
    schema_version: Literal["1.0"] = REFRESH_TOKEN_INVALIDATION_SCHEMA_VERSION
    subject_id: str = Field(min_length=SUBJECT_ID_MINIMUM_LENGTH)


class TokenSessionInvalidationDetail(BaseModel):
    """
    指定令牌会话失效扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["token_session"] = TOKEN_SESSION_KIND
    schema_version: Literal["1.0"] = REFRESH_TOKEN_INVALIDATION_SCHEMA_VERSION
    token_session_id: str = Field(min_length=TOKEN_SESSION_ID_MINIMUM_LENGTH)


RefreshTokenInvalidationDetail = Annotated[
    AllRefreshTokenSessionsDetail
    | SubjectRefreshTokenSessionsDetail
    | TokenSessionInvalidationDetail,
    Field(discriminator="kind"),
]


class RefreshTokenInvalidationCommand(BaseModel):
    """
    刷新令牌失效命令信封。
    """

    model_config = ConfigDict(extra="forbid")

    envelope_kind: Literal["refresh_token_invalidation_envelope"] = (
        REFRESH_TOKEN_INVALIDATION_ENVELOPE_KIND
    )
    schema_version: Literal["1.0"] = REFRESH_TOKEN_INVALIDATION_SCHEMA_VERSION
    header: RefreshTokenInvalidationHeader
    detail: RefreshTokenInvalidationDetail

    @model_validator(mode="after")
    def validate_detail_contract(self) -> RefreshTokenInvalidationCommand:
        """
        校验公共头字段与扩展字段一致性。
        """

        if self.header.mode.value != self.detail.kind:
            raise ValueError("刷新令牌失效 mode 必须与 detail.kind 一致。")
        if self.schema_version != self.header.schema_version:
            raise ValueError("刷新令牌失效信封版本必须与公共头版本一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("刷新令牌失效公共头版本必须与扩展版本一致。")
        return self
