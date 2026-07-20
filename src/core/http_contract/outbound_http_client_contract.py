"""
外部 HTTP 客户端契约核心模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION: Final = "1.0"
OUTBOUND_HTTP_CLIENT_ENVELOPE_KIND: Final = "outbound_http_client_envelope"
OUTBOUND_HTTP_CLIENT_HEADER_KIND: Final = "outbound_http_client_header"
SYNC_HTTP_CLIENT_DETAIL_KIND: Final = "sync_http"
ASYNC_HTTP_CLIENT_DETAIL_KIND: Final = "async_http"
OUTBOUND_HTTP_CLIENT_SYNC_MODE = "sync_http"
OUTBOUND_HTTP_CLIENT_ASYNC_MODE = "async_http"
DEFAULT_OUTBOUND_HTTP_CLIENT_NAME = "default_outbound_http"
OUTBOUND_HTTP_CLIENT_NAME_MINIMUM_LENGTH = 1
OUTBOUND_HTTP_CLIENT_TIMEOUT_MINIMUM = 1
OUTBOUND_HTTP_CLIENT_CONNECTION_MINIMUM = 1


class OutboundHttpClientMode(StrEnum):
    """
    外部 HTTP 客户端模式枚举。

    ``SYNC_HTTP`` 表示仅装配同步 ``httpx.Client`` 风格能力。
    ``ASYNC_HTTP`` 表示额外装配共享异步客户端，供真正的高并发 I/O 边界使用。
    """

    SYNC_HTTP = OUTBOUND_HTTP_CLIENT_SYNC_MODE
    ASYNC_HTTP = OUTBOUND_HTTP_CLIENT_ASYNC_MODE


class OutboundHttpClientHeader(BaseModel):
    """
    外部 HTTP 客户端公共头。

    :ivar kind: 公共头类型标识。约束：固定为 ``outbound_http_client_header``。默认值：``OUTBOUND_HTTP_CLIENT_HEADER_KIND``。取值语义：用于判定客户端公共头结构类型。
    :vartype kind: Literal[OUTBOUND_HTTP_CLIENT_HEADER_KIND]
    :ivar schema_version: 契约版本。约束：固定为 ``1.0``。默认值：``OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION``。取值语义：用于约束头部与扩展字段版本一致性。
    :vartype schema_version: Literal[OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION]
    :ivar client_name: 客户端配置名称。约束：最小长度为 ``1``。默认值：无，必须显式提供。取值语义：用于标识当前运行时装配的对外 HTTP 客户端。
    :vartype client_name: str
    :ivar enabled: 是否启用对外 HTTP 客户端能力。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示允许装配客户端，``False`` 表示仅保留同步兜底资源。
    :vartype enabled: bool
    :ivar mode: 客户端模式。约束：需符合 ``OutboundHttpClientMode`` 注解。默认值：无，必须显式提供。取值语义：决定是否额外装配异步客户端资源。
    :vartype mode: OutboundHttpClientMode
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["outbound_http_client_header"] = OUTBOUND_HTTP_CLIENT_HEADER_KIND
    schema_version: Literal["1.0"] = OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION
    client_name: str = Field(min_length=OUTBOUND_HTTP_CLIENT_NAME_MINIMUM_LENGTH)
    enabled: bool
    mode: OutboundHttpClientMode


class SyncHttpClientDetail(BaseModel):
    """
    同步 HTTP 客户端扩展。

    :ivar kind: 扩展字段类型标识。约束：固定为 ``sync_http``。默认值：``SYNC_HTTP_CLIENT_DETAIL_KIND``。取值语义：用于判别联合选择同步客户端扩展模型。
    :vartype kind: Literal[SYNC_HTTP_CLIENT_DETAIL_KIND]
    :ivar schema_version: 扩展字段版本。约束：固定为 ``1.0``。默认值：``OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION``。取值语义：必须与外层和公共头版本保持一致。
    :vartype schema_version: Literal[OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION]
    :ivar timeout_seconds: 请求超时秒数。约束：最小值为 ``1``。默认值：无，必须显式提供。取值语义：用于控制同步 HTTP 客户端的统一超时。
    :vartype timeout_seconds: int
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["sync_http"] = SYNC_HTTP_CLIENT_DETAIL_KIND
    schema_version: Literal["1.0"] = OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION
    timeout_seconds: int = Field(ge=OUTBOUND_HTTP_CLIENT_TIMEOUT_MINIMUM)
    max_connections: int = Field(ge=OUTBOUND_HTTP_CLIENT_CONNECTION_MINIMUM)
    max_keepalive_connections: int = Field(ge=OUTBOUND_HTTP_CLIENT_CONNECTION_MINIMUM)


class AsyncHttpClientDetail(BaseModel):
    """
    异步 HTTP 客户端扩展。

    :ivar kind: 扩展字段类型标识。约束：固定为 ``async_http``。默认值：``ASYNC_HTTP_CLIENT_DETAIL_KIND``。取值语义：用于判别联合选择异步客户端扩展模型。
    :vartype kind: Literal[ASYNC_HTTP_CLIENT_DETAIL_KIND]
    :ivar schema_version: 扩展字段版本。约束：固定为 ``1.0``。默认值：``OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION``。取值语义：必须与外层和公共头版本保持一致。
    :vartype schema_version: Literal[OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION]
    :ivar timeout_seconds: 请求超时秒数。约束：最小值为 ``1``。默认值：无，必须显式提供。取值语义：用于控制异步客户端的统一超时。
    :vartype timeout_seconds: int
    :ivar max_connections: 最大连接数。约束：最小值为 ``1``。默认值：无，必须显式提供。取值语义：用于限制异步客户端的并发连接上限。
    :vartype max_connections: int
    :ivar max_keepalive_connections: 最大保活连接数。约束：最小值为 ``1``。默认值：无，必须显式提供。取值语义：用于控制连接池中可复用的长连接数量。
    :vartype max_keepalive_connections: int
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["async_http"] = ASYNC_HTTP_CLIENT_DETAIL_KIND
    schema_version: Literal["1.0"] = OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION
    timeout_seconds: int = Field(ge=OUTBOUND_HTTP_CLIENT_TIMEOUT_MINIMUM)
    max_connections: int = Field(ge=OUTBOUND_HTTP_CLIENT_CONNECTION_MINIMUM)
    max_keepalive_connections: int = Field(ge=OUTBOUND_HTTP_CLIENT_CONNECTION_MINIMUM)


OutboundHttpClientDetailUnion = Annotated[
    SyncHttpClientDetail | AsyncHttpClientDetail,
    Field(discriminator="kind"),
]


class OutboundHttpClientEnvelope(BaseModel):
    """
    外部 HTTP 客户端信封。

    :ivar envelope_kind: 外层信封类型标识。约束：固定为 ``outbound_http_client_envelope``。默认值：``OUTBOUND_HTTP_CLIENT_ENVELOPE_KIND``。取值语义：用于判定当前配置块属于外部 HTTP 客户端能力。
    :vartype envelope_kind: Literal[OUTBOUND_HTTP_CLIENT_ENVELOPE_KIND]
    :ivar schema_version: 外层信封版本。约束：固定为 ``1.0``。默认值：``OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION``。取值语义：必须与公共头和扩展字段版本保持一致。
    :vartype schema_version: Literal[OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION]
    :ivar header: 公共头字段。约束：需符合 ``OutboundHttpClientHeader`` 注解。默认值：无，必须显式提供。取值语义：承载客户端名称、启用状态与模式标识。
    :vartype header: OutboundHttpClientHeader
    :ivar detail: 强类型扩展字段。约束：需符合 ``OutboundHttpClientDetailUnion`` 判别联合，且 ``kind`` 与 ``header.mode`` 一致。默认值：无，必须显式提供。取值语义：承载同步或异步客户端的专属参数。
    :vartype detail: OutboundHttpClientDetailUnion
    """

    model_config = ConfigDict(extra="forbid")

    envelope_kind: Literal["outbound_http_client_envelope"] = OUTBOUND_HTTP_CLIENT_ENVELOPE_KIND
    schema_version: Literal["1.0"] = OUTBOUND_HTTP_CLIENT_SCHEMA_VERSION
    header: OutboundHttpClientHeader
    detail: OutboundHttpClientDetailUnion

    @model_validator(mode="after")
    def validate_outbound_http_client_contract(self) -> OutboundHttpClientEnvelope:
        """
        校验客户端契约一致性。

        :returns: 返回通过一致性校验后的当前信封对象。
        :rtype: OutboundHttpClientEnvelope
        :raises ValueError: 当外层版本、公共头模式或扩展字段类型不一致时抛出。
        """

        if self.header.schema_version != self.detail.schema_version:
            raise ValueError(
                "runtime.web.outbound_http_client.header.schema_version 与 detail.schema_version 不一致。"
            )
        if self.header.mode.value != self.detail.kind:
            raise ValueError("runtime.web.outbound_http_client.header.mode 与 detail.kind 不一致。")
        if self.schema_version != self.detail.schema_version:
            raise ValueError(
                "runtime.web.outbound_http_client.schema_version 与 detail.schema_version 不一致。"
            )
        return self
