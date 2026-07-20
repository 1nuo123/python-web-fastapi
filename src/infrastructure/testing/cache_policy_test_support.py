"""
缓存策略测试辅助模块。
"""

from __future__ import annotations

from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.cache_contract.cache_policy_contract import (
    AUTH_THROTTLE_CACHE_POLICY_DETAIL_KIND,
    CACHE_POLICY_HEADER_KIND,
    CACHE_POLICY_SCHEMA_VERSION,
    QUERY_RESULT_CACHE_POLICY_DETAIL_KIND,
    RATE_LIMIT_CACHE_POLICY_DETAIL_KIND,
    AuthThrottleCachePolicyDetail,
    CacheFailureMode,
    CachePolicyEnvelope,
    CachePolicyHeader,
    QueryResultCachePolicyDetail,
    RateLimitCachePolicyDetail,
)
from src.infrastructure.cache.cache_policy_resolver import CachePolicyResolver

TEST_AUTH_THROTTLE_POLICY_TTL_SECONDS = 11
TEST_RATE_LIMIT_POLICY_TTL_SECONDS = 13
TEST_QUERY_RESULT_POLICY_TTL_SECONDS = 17


class CachePolicyTestFactory:
    """
    缓存策略测试工厂，用于构建单元测试中复用的策略契约对象。
    """

    def build_resolver(
        self,
        *,
        runtime_default_ttl_seconds: int,
        include_namespace_policies: bool = True,
    ) -> CachePolicyResolver:
        """
        构建缓存策略解析器。

        :param runtime_default_ttl_seconds: 运行时默认缓存 TTL 秒数。
        :type runtime_default_ttl_seconds: int
        :param include_namespace_policies: 是否包含标准命名空间策略。
        :type include_namespace_policies: bool
        :returns: 返回缓存策略解析器。
        :rtype: CachePolicyResolver
        """

        return CachePolicyResolver(
            namespace_policies=(
                self.build_namespace_policies() if include_namespace_policies else []
            ),
            runtime_default_ttl_seconds=runtime_default_ttl_seconds,
        )

    def build_namespace_policies(self) -> list[CachePolicyEnvelope]:
        """
        构建标准命名空间策略列表。

        :returns: 返回鉴权节流、限流与查询缓存策略列表。
        :rtype: list[CachePolicyEnvelope]
        """

        return [
            self.build_auth_throttle_policy(),
            self.build_rate_limit_policy(),
            self.build_query_result_policy(),
        ]

    def build_auth_throttle_policy(self) -> CachePolicyEnvelope:
        """
        构建鉴权节流缓存策略。

        :returns: 返回鉴权节流缓存策略信封。
        :rtype: CachePolicyEnvelope
        """

        return CachePolicyEnvelope(
            header=CachePolicyHeader(
                kind=CACHE_POLICY_HEADER_KIND,
                schema_version=CACHE_POLICY_SCHEMA_VERSION,
                detail_kind=AUTH_THROTTLE_CACHE_POLICY_DETAIL_KIND,
                namespace=CacheNamespace.AUTH_THROTTLE,
            ),
            detail=AuthThrottleCachePolicyDetail(
                default_ttl_seconds=TEST_AUTH_THROTTLE_POLICY_TTL_SECONDS,
            ),
        )

    def build_rate_limit_policy(self) -> CachePolicyEnvelope:
        """
        构建限流缓存策略。

        :returns: 返回限流缓存策略信封。
        :rtype: CachePolicyEnvelope
        """

        return CachePolicyEnvelope(
            header=CachePolicyHeader(
                kind=CACHE_POLICY_HEADER_KIND,
                schema_version=CACHE_POLICY_SCHEMA_VERSION,
                detail_kind=RATE_LIMIT_CACHE_POLICY_DETAIL_KIND,
                namespace=CacheNamespace.RATE_LIMIT,
            ),
            detail=RateLimitCachePolicyDetail(
                default_ttl_seconds=TEST_RATE_LIMIT_POLICY_TTL_SECONDS,
            ),
        )

    def build_query_result_policy(
        self,
        *,
        failure_mode: CacheFailureMode = CacheFailureMode.FAIL_OPEN,
    ) -> CachePolicyEnvelope:
        """
        构建查询缓存策略。

        :param failure_mode: Redis 不可用时的故障处理模式。
        :type failure_mode: CacheFailureMode
        :returns: 返回查询缓存策略信封。
        :rtype: CachePolicyEnvelope
        """

        return CachePolicyEnvelope(
            header=CachePolicyHeader(
                kind=CACHE_POLICY_HEADER_KIND,
                schema_version=CACHE_POLICY_SCHEMA_VERSION,
                detail_kind=QUERY_RESULT_CACHE_POLICY_DETAIL_KIND,
                namespace=CacheNamespace.QUERY_RESULT,
            ),
            detail=QueryResultCachePolicyDetail(
                default_ttl_seconds=TEST_QUERY_RESULT_POLICY_TTL_SECONDS,
                failure_mode=failure_mode,
            ),
        )
