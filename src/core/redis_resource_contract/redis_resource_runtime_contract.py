"""共享 sync/async Redis 连接运行时契约。"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REDIS_RESOURCE_RUNTIME_KIND: Final = "redis_resource_runtime"
REDIS_RESOURCE_SCHEMA_VERSION: Final = "1.0"


class RedisResourceRuntimeHeader(BaseModel):
    """共享 Redis 资源公共头。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["redis_resource_runtime"] = REDIS_RESOURCE_RUNTIME_KIND
    schema_version: Literal["1.0"] = REDIS_RESOURCE_SCHEMA_VERSION
    enabled: bool


class RedisResourceRuntimeDetail(BaseModel):
    """唯一 Redis 连接、TLS、超时和 pool 配置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["redis_resource_runtime"] = REDIS_RESOURCE_RUNTIME_KIND
    schema_version: Literal["1.0"] = REDIS_RESOURCE_SCHEMA_VERSION
    url: str = Field(min_length=1, max_length=2_048)
    connect_timeout_seconds: float = Field(gt=0, le=60)
    operation_timeout_seconds: float = Field(gt=0, le=300)
    sync_max_connections: int = Field(ge=1, le=10_000)
    async_max_connections: int = Field(ge=1, le=10_000)
    health_probe_timeout_seconds: float = Field(gt=0, le=60)
    require_tls_in_production: bool = True


class RedisResourceRuntimeEnvelope(BaseModel):
    """共享 Redis 资源公共头与强类型扩展字段信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: RedisResourceRuntimeHeader
    detail: RedisResourceRuntimeDetail

    @model_validator(mode="after")
    def validate_kind(self) -> RedisResourceRuntimeEnvelope:
        """公共头与扩展字段必须使用同一契约种类。"""

        if self.header.kind != self.detail.kind:
            raise ValueError("Redis资源公共头与扩展字段kind不一致。")
        return self
