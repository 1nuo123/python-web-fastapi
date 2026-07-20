"""
缓存载荷编解码器基础设施模块。
"""

from __future__ import annotations

from pydantic import ValidationError

from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.cache_contract.cache_payload_contract import (
    CacheEntryHeader,
    CacheEnvelope,
    CachePayload,
)


class CachePayloadCodec:
    """
    缓存载荷编解码器类型，用于封装当前模块中的相关行为或状态。
    """

    def encode(
        self,
        *,
        namespace: CacheNamespace,
        key: str,
        ttl_seconds: int,
        payload: CachePayload,
    ) -> str:
        """
        处理编码。

        :param namespace: 缓存命名空间，用于隔离同类键。约束：需符合 ``CacheNamespace`` 注解。
        :type namespace: CacheNamespace
        :param key: 缓存键。约束：需符合 ``str`` 注解。
        :type key: str
        :param ttl_seconds: 缓存 TTL 秒数；传入 ``None`` 时按实现回落到默认值。约束：需符合 ``int`` 注解。
        :type ttl_seconds: int
        :param payload: 结构化载荷对象。约束：需符合 ``CachePayload`` 注解。
        :type payload: CachePayload
        :returns: 返回当前操作结果。
        :rtype: str
        """

        return CacheEnvelope(
            header=CacheEntryHeader(
                namespace=namespace,
                key=key,
                ttl_seconds=ttl_seconds,
                value_kind=payload.kind,
            ),
            data=payload,
        ).model_dump_json()

    def decode(self, raw_value: str) -> CacheEnvelope:
        """
        处理解码。

        :param raw_value: 未经解析的原始值。约束：需符合 ``str`` 注解。
        :type raw_value: str
        :returns: 返回当前操作结果。
        :rtype: CacheEnvelope
        :raises ValueError: 当输入值或配置值不满足当前实现约束时抛出。
        """

        try:
            return CacheEnvelope.model_validate_json(raw_value)
        except ValidationError as exc:
            raise ValueError("缓存值不符合统一缓存契约。") from exc
