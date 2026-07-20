"""
缓存策略解析器基础设施模块。
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.cache_contract.cache_policy_contract import (
    CACHE_POLICY_TTL_MINIMUM_SECONDS,
    CacheFailureMode,
    CachePolicyEnvelope,
)

DUPLICATED_CACHE_POLICY_MESSAGE = "缓存命名空间策略不能重复。命名空间：{namespace}。"
DEFAULT_CACHE_FAILURE_MODE = CacheFailureMode.FAIL_CLOSED


@dataclass(slots=True)
class ResolvedCachePolicy:
    """
    已解析缓存策略数据对象，用于承载当前命名空间最终生效的缓存策略。

    :ivar namespace: 缓存命名空间。
    :vartype namespace: CacheNamespace
    :ivar default_ttl_seconds: 当前命名空间默认缓存 TTL 秒数。
    :vartype default_ttl_seconds: int
    :ivar failure_mode: Redis 不可用时的故障处理模式。
    :vartype failure_mode: CacheFailureMode
    """

    namespace: CacheNamespace
    default_ttl_seconds: int
    failure_mode: CacheFailureMode


class CachePolicyResolver:
    """
    缓存策略解析器，负责按命名空间解析 TTL 与 Redis 不可用策略。
    """

    def __init__(
        self,
        *,
        namespace_policies: list[CachePolicyEnvelope],
        runtime_default_ttl_seconds: int,
    ) -> None:
        """
        初始化缓存策略解析器。

        :param namespace_policies: 已通过契约校验的命名空间策略列表。
        :type namespace_policies: list[CachePolicyEnvelope]
        :param runtime_default_ttl_seconds: 运行时缓存默认 TTL 秒数。
        :type runtime_default_ttl_seconds: int
        :returns: 无返回值。
        :rtype: None
        """

        self._assert_positive_ttl(runtime_default_ttl_seconds)
        self._runtime_default_ttl_seconds = runtime_default_ttl_seconds
        self._policies_by_namespace = self._build_policy_mapping(namespace_policies)

    def resolve(self, namespace: CacheNamespace) -> ResolvedCachePolicy:
        """
        按命名空间解析缓存策略。

        :param namespace: 缓存命名空间。
        :type namespace: CacheNamespace
        :returns: 返回命名空间最终生效的缓存策略。
        :rtype: ResolvedCachePolicy
        """

        policy = self._policies_by_namespace.get(namespace)
        if policy is None:
            return ResolvedCachePolicy(
                namespace=namespace,
                default_ttl_seconds=self._runtime_default_ttl_seconds,
                failure_mode=DEFAULT_CACHE_FAILURE_MODE,
            )
        return ResolvedCachePolicy(
            namespace=namespace,
            default_ttl_seconds=policy.detail.default_ttl_seconds,
            failure_mode=policy.detail.failure_mode,
        )

    def resolve_ttl_seconds(
        self,
        *,
        namespace: CacheNamespace,
        explicit_ttl_seconds: int | None,
    ) -> int:
        """
        按显式 TTL、命名空间 TTL、运行时 TTL 的顺序解析最终 TTL。

        :param namespace: 缓存命名空间。
        :type namespace: CacheNamespace
        :param explicit_ttl_seconds: 请求显式 TTL 秒数；为空时使用命名空间策略。
        :type explicit_ttl_seconds: int | None
        :returns: 返回最终使用的 TTL 秒数。
        :rtype: int
        """

        if explicit_ttl_seconds is not None:
            self._assert_positive_ttl(explicit_ttl_seconds)
            return explicit_ttl_seconds
        return self.resolve(namespace).default_ttl_seconds

    def _build_policy_mapping(
        self,
        namespace_policies: list[CachePolicyEnvelope],
    ) -> dict[CacheNamespace, CachePolicyEnvelope]:
        """
        构建命名空间策略索引。

        :param namespace_policies: 已通过契约校验的命名空间策略列表。
        :type namespace_policies: list[CachePolicyEnvelope]
        :returns: 返回按命名空间索引的策略映射。
        :rtype: dict[CacheNamespace, CachePolicyEnvelope]
        :raises ValueError: 当同一命名空间出现重复策略时抛出。
        """

        policies_by_namespace: dict[CacheNamespace, CachePolicyEnvelope] = {}
        for policy in namespace_policies:
            namespace = policy.header.namespace
            if namespace in policies_by_namespace:
                raise ValueError(DUPLICATED_CACHE_POLICY_MESSAGE.format(namespace=namespace.value))
            policies_by_namespace[namespace] = policy
        return policies_by_namespace

    def _assert_positive_ttl(self, ttl_seconds: int) -> None:
        """
        断言 TTL 为正值。

        :param ttl_seconds: 缓存 TTL 秒数。
        :type ttl_seconds: int
        :returns: 无返回值。
        :rtype: None
        :raises ValueError: 当 TTL 小于最小值时抛出。
        """

        if ttl_seconds < CACHE_POLICY_TTL_MINIMUM_SECONDS:
            raise ValueError("缓存 TTL 必须大于 0。")
