"""
缓存服务基础设施模块。
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Generic, TypeVar, cast

from pydantic import BaseModel

from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.cache_contract.cache_payload_contract import CachePayload
from src.core.cache_contract.cache_policy_contract import CacheFailureMode
from src.core.cache_contract.cache_store_contract import CacheStore
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.cache_payload_codec import CachePayloadCodec
from src.infrastructure.cache.cache_policy_resolver import CachePolicyResolver

CACHE_LOGGER_NAME = "fastapi_web_skeleton.cache"
CACHE_TTL_MINIMUM_SECONDS = 1
INVALID_CACHE_VALUE_MESSAGE = "检测到损坏的缓存值，已按未命中处理并清理。"
UNEXPECTED_CACHE_PAYLOAD_MESSAGE = "缓存扩展体类型与读取声明不一致，已按未命中处理并清理。"
CACHE_UNAVAILABLE_READ_FAIL_OPEN_MESSAGE = "缓存不可用，已按未命中处理。"
CACHE_UNAVAILABLE_WRITE_FAIL_OPEN_MESSAGE = "缓存不可用，已跳过写入。"
CACHE_UNAVAILABLE_DELETE_FAIL_OPEN_MESSAGE = "缓存不可用，已跳过删除。"
CACHE_KEY_DIGEST_SIZE = 16
CACHE_KEY_DIGEST_ENCODING = "utf-8"

T_CachePayload = TypeVar("T_CachePayload", bound=BaseModel)


@dataclass(slots=True)
class CacheWriteRequest:
    """
    缓存写入数据对象，用于承载当前流程的结构化字段。

    :ivar namespace: 缓存命名空间。约束：需符合 ``CacheNamespace`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype namespace: CacheNamespace
    :ivar key_parts: 缓存键片段。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于按顺序承载多个同类值。
    :vartype key_parts: list[str]
    :ivar payload: 业务载荷对象。约束：需符合 ``CachePayload`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype payload: CachePayload
    :ivar ttl_seconds: 缓存 TTL 秒数。约束：需符合 ``int | None`` 注解；允许为空值。默认值：`None`。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype ttl_seconds: int | None
    """

    namespace: CacheNamespace
    key_parts: list[str]
    payload: CachePayload
    ttl_seconds: int | None = None


@dataclass(slots=True)
class CacheReadRequest(Generic[T_CachePayload]):
    """
    缓存读取数据对象，用于承载当前流程的结构化字段。

    :ivar namespace: 缓存命名空间。约束：需符合 ``CacheNamespace`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype namespace: CacheNamespace
    :ivar key_parts: 缓存键片段。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于按顺序承载多个同类值。
    :vartype key_parts: list[str]
    :ivar payload_type: ``payload_type`` 字段。约束：需符合 ``type[T_CachePayload]`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype payload_type: type[T_CachePayload]
    """

    namespace: CacheNamespace
    key_parts: list[str]
    payload_type: type[T_CachePayload]


@dataclass(slots=True)
class CacheDeleteRequest:
    """
    缓存删除数据对象，用于承载当前流程的结构化字段。

    :ivar namespace: 缓存命名空间。约束：需符合 ``CacheNamespace`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype namespace: CacheNamespace
    :ivar key_parts: 缓存键片段。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于按顺序承载多个同类值。
    :vartype key_parts: list[str]
    """

    namespace: CacheNamespace
    key_parts: list[str]


@dataclass(slots=True)
class CacheIncrementRequest:
    """
    缓存原子递增请求数据对象。

    :ivar namespace: 缓存命名空间。
    :vartype namespace: CacheNamespace
    :ivar key_parts: 缓存键片段。
    :vartype key_parts: list[str]
    :ivar ttl_seconds: 缓存 TTL 秒数。
    :vartype ttl_seconds: int | None
    """

    namespace: CacheNamespace
    key_parts: list[str]
    ttl_seconds: int | None = None


@dataclass(slots=True)
class CacheReadResult(Generic[T_CachePayload]):
    """
    缓存读取数据对象，用于承载当前流程的结构化字段。

    :ivar hit: ``hit`` 字段。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype hit: bool
    :ivar payload: 业务载荷对象。约束：需符合 ``T_CachePayload | None`` 注解；允许为空值。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype payload: T_CachePayload | None
    """

    hit: bool
    payload: T_CachePayload | None


class CacheService:
    """
    缓存服务，负责提供可复用的领域或基础设施能力。
    """

    def __init__(
        self,
        *,
        cache_store: CacheStore,
        key_builder: CacheKeyBuilder,
        payload_codec: CachePayloadCodec,
        policy_resolver: CachePolicyResolver,
        default_ttl_seconds: int,
        logger: logging.Logger | None = None,
    ) -> None:
        """
        初始化缓存服务。

        :param cache_store: 底层缓存存储实现。约束：需符合 ``CacheStore`` 注解。
        :type cache_store: CacheStore
        :param key_builder: 缓存键构建器。约束：需符合 ``CacheKeyBuilder`` 注解。
        :type key_builder: CacheKeyBuilder
        :param payload_codec: 缓存载荷编解码器。约束：需符合 ``CachePayloadCodec`` 注解。
        :type payload_codec: CachePayloadCodec
        :param policy_resolver: 缓存策略解析器。约束：需符合 ``CachePolicyResolver`` 注解。
        :type policy_resolver: CachePolicyResolver
        :param default_ttl_seconds: 默认缓存 TTL 秒数。约束：需符合 ``int`` 注解。
        :type default_ttl_seconds: int
        :param logger: 当前组件使用的日志记录器。默认值：`None`。约束：需符合 ``logging.Logger | None`` 注解。
        :type logger: logging.Logger | None
        :returns: 无返回值。
        :rtype: None
        """

        self._cache_store = cache_store
        self._key_builder = key_builder
        self._payload_codec = payload_codec
        self._policy_resolver = policy_resolver
        self._default_ttl_seconds = default_ttl_seconds
        self._logger = logger or logging.getLogger(CACHE_LOGGER_NAME)
        self._assert_positive_ttl(default_ttl_seconds)

    def write_payload(self, request: CacheWriteRequest) -> None:
        """
        处理写入载荷。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``CacheWriteRequest`` 注解。
        :type request: CacheWriteRequest
        :returns: 无返回值。
        :rtype: None
        """

        ttl_seconds = self._resolve_ttl_seconds(
            namespace=request.namespace,
            ttl_seconds=request.ttl_seconds,
        )
        cache_key = self._key_builder.build(
            namespace=request.namespace,
            key_parts=request.key_parts,
        )
        raw_value = self._payload_codec.encode(
            namespace=request.namespace,
            key=cache_key,
            ttl_seconds=ttl_seconds,
            payload=request.payload,
        )
        try:
            self._cache_store.set_value(cache_key, raw_value, ttl_seconds)
        except HttpFaultException as exc:
            if self._should_fail_open_for_cache_unavailable(request.namespace, exc):
                self._log_cache_unavailable(
                    message=CACHE_UNAVAILABLE_WRITE_FAIL_OPEN_MESSAGE,
                    namespace=request.namespace,
                    cache_key=cache_key,
                )
                return
            raise

    def read_payload(
        self,
        request: CacheReadRequest[T_CachePayload],
    ) -> CacheReadResult[T_CachePayload]:
        """
        读取载荷。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``CacheReadRequest[T_CachePayload]`` 注解。
        :type request: CacheReadRequest[T_CachePayload]
        :returns: 返回读取到的对象或状态快照。
        :rtype: CacheReadResult[T_CachePayload]
        """

        cache_key = self._key_builder.build(
            namespace=request.namespace,
            key_parts=request.key_parts,
        )
        try:
            raw_value = self._cache_store.get_value(cache_key)
        except HttpFaultException as exc:
            if self._should_fail_open_for_cache_unavailable(request.namespace, exc):
                self._log_cache_unavailable(
                    message=CACHE_UNAVAILABLE_READ_FAIL_OPEN_MESSAGE,
                    namespace=request.namespace,
                    cache_key=cache_key,
                )
                return CacheReadResult(hit=False, payload=None)
            raise
        if raw_value is None:
            return CacheReadResult(hit=False, payload=None)
        try:
            cache_envelope = self._payload_codec.decode(raw_value)
        except ValueError as exc:
            self._logger.warning(
                "%s 键：%s。原因：%s",
                INVALID_CACHE_VALUE_MESSAGE,
                cache_key,
                str(exc),
            )
            self._delete_value_with_policy(
                namespace=request.namespace,
                cache_key=cache_key,
            )
            return CacheReadResult(hit=False, payload=None)
        if not isinstance(cache_envelope.data, request.payload_type):
            self._logger.warning(
                "%s 键：%s，声明类型：%s，实际类型：%s。",
                UNEXPECTED_CACHE_PAYLOAD_MESSAGE,
                cache_key,
                request.payload_type.__name__,
                type(cache_envelope.data).__name__,
            )
            self._delete_value_with_policy(
                namespace=request.namespace,
                cache_key=cache_key,
            )
            return CacheReadResult(hit=False, payload=None)
        return CacheReadResult(
            hit=True,
            payload=cast(T_CachePayload, cache_envelope.data),
        )

    def delete_payload(self, request: CacheDeleteRequest) -> None:
        """
        删除载荷。

        :param request: 当前 HTTP 请求对象，用于读取状态、请求头和依赖。约束：需符合 ``CacheDeleteRequest`` 注解。
        :type request: CacheDeleteRequest
        :returns: 无返回值。
        :rtype: None
        """

        cache_key = self._key_builder.build(
            namespace=request.namespace,
            key_parts=request.key_parts,
        )
        self._delete_value_with_policy(
            namespace=request.namespace,
            cache_key=cache_key,
        )

    def increment_counter(self, request: CacheIncrementRequest) -> int:
        """
        原子递增缓存计数。

        :param request: 缓存原子递增请求。
        :type request: CacheIncrementRequest
        :returns: 递增后的计数值。
        :rtype: int
        """

        ttl_seconds = self._resolve_ttl_seconds(
            namespace=request.namespace,
            ttl_seconds=request.ttl_seconds,
        )
        cache_key = self._key_builder.build(
            namespace=request.namespace,
            key_parts=request.key_parts,
        )
        try:
            return self._cache_store.increment_with_expire(cache_key, ttl_seconds)
        except HttpFaultException as exc:
            if self._should_fail_open_for_cache_unavailable(request.namespace, exc):
                self._log_cache_unavailable(
                    message=CACHE_UNAVAILABLE_WRITE_FAIL_OPEN_MESSAGE,
                    namespace=request.namespace,
                    cache_key=cache_key,
                )
                return 0
            raise

    def _resolve_ttl_seconds(
        self,
        *,
        namespace: CacheNamespace,
        ttl_seconds: int | None,
    ) -> int:
        """
        解析TTL秒数。

        :param namespace: 缓存命名空间。约束：需符合 ``CacheNamespace`` 注解。
        :type namespace: CacheNamespace
        :param ttl_seconds: 缓存 TTL 秒数；传入 ``None`` 时按实现回落到默认值。约束：需符合 ``int | None`` 注解。
        :type ttl_seconds: int | None
        :returns: 返回当前操作结果。
        :rtype: int
        """

        resolved_ttl_seconds = self._policy_resolver.resolve_ttl_seconds(
            namespace=namespace,
            explicit_ttl_seconds=ttl_seconds,
        )
        self._assert_positive_ttl(resolved_ttl_seconds)
        return resolved_ttl_seconds

    def _delete_value_with_policy(
        self,
        *,
        namespace: CacheNamespace,
        cache_key: str,
    ) -> None:
        """
        按命名空间策略删除缓存值。

        :param namespace: 缓存命名空间。约束：需符合 ``CacheNamespace`` 注解。
        :type namespace: CacheNamespace
        :param cache_key: 已规范化缓存键。约束：需符合 ``str`` 注解。
        :type cache_key: str
        :returns: 无返回值。
        :rtype: None
        """

        try:
            self._cache_store.delete_value(cache_key)
        except HttpFaultException as exc:
            if self._should_fail_open_for_cache_unavailable(namespace, exc):
                self._log_cache_unavailable(
                    message=CACHE_UNAVAILABLE_DELETE_FAIL_OPEN_MESSAGE,
                    namespace=namespace,
                    cache_key=cache_key,
                )
                return
            raise

    def _should_fail_open_for_cache_unavailable(
        self,
        namespace: CacheNamespace,
        exc: HttpFaultException,
    ) -> bool:
        """
        判断缓存不可用异常是否应按失败开放处理。

        :param namespace: 缓存命名空间。约束：需符合 ``CacheNamespace`` 注解。
        :type namespace: CacheNamespace
        :param exc: 当前捕获到的 HTTP 故障异常。约束：需符合 ``HttpFaultException`` 注解。
        :type exc: HttpFaultException
        :returns: 当当前命名空间策略允许失败开放时返回 ``True``。
        :rtype: bool
        """

        if not self._is_cache_unavailable(exc):
            return False
        policy = self._policy_resolver.resolve(namespace)
        return policy.failure_mode == CacheFailureMode.FAIL_OPEN

    def _is_cache_unavailable(self, exc: HttpFaultException) -> bool:
        """
        判断异常是否为缓存不可用。

        :param exc: 当前捕获到的 HTTP 故障异常。约束：需符合 ``HttpFaultException`` 注解。
        :type exc: HttpFaultException
        :returns: 当异常错误码为缓存不可用时返回 ``True``。
        :rtype: bool
        """

        return exc.error_code == str(CoreErrorCode.CACHE_UNAVAILABLE)

    def _log_cache_unavailable(
        self,
        *,
        message: str,
        namespace: CacheNamespace,
        cache_key: str,
    ) -> None:
        """
        记录缓存不可用告警。

        :param message: 中文日志消息。约束：需符合 ``str`` 注解。
        :type message: str
        :param namespace: 缓存命名空间。约束：需符合 ``CacheNamespace`` 注解。
        :type namespace: CacheNamespace
        :param cache_key: 已规范化缓存键。约束：需符合 ``str`` 注解。
        :type cache_key: str
        :returns: 无返回值。
        :rtype: None
        """

        self._logger.warning(
            "%s 命名空间：%s，键摘要：%s。",
            message,
            namespace.value,
            self._build_cache_key_digest(cache_key),
        )

    def _build_cache_key_digest(self, cache_key: str) -> str:
        """
        构建缓存键摘要。

        :param cache_key: 已规范化缓存键。约束：需符合 ``str`` 注解。
        :type cache_key: str
        :returns: 返回缓存键摘要前缀。
        :rtype: str
        """

        return hashlib.sha256(cache_key.encode(CACHE_KEY_DIGEST_ENCODING)).hexdigest()[
            :CACHE_KEY_DIGEST_SIZE
        ]

    def _assert_positive_ttl(self, ttl_seconds: int) -> None:
        """
        断言正值TTL。

        :param ttl_seconds: 缓存 TTL 秒数；传入 ``None`` 时按实现回落到默认值。约束：需符合 ``int`` 注解。
        :type ttl_seconds: int
        :returns: 无返回值。
        :rtype: None
        :raises ValueError: 当输入值或配置值不满足当前实现约束时抛出。
        """

        if ttl_seconds < CACHE_TTL_MINIMUM_SECONDS:
            raise ValueError("缓存 TTL 必须大于 0。")
