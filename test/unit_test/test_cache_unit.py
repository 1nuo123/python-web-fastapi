"""
测试缓存单元测试模块。
"""

from __future__ import annotations

import pytest

from src.core.auth_contract.auth_throttle_state_contract import AuthThrottleStatePayload
from src.core.auth_contract.token_session_status_contract import TokenSessionStatusPayload
from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.cache_contract.cache_payload_contract import CacheEnvelope
from src.core.cache_contract.cache_policy_contract import (
    AUTH_THROTTLE_CACHE_POLICY_DETAIL_KIND,
    CACHE_POLICY_HEADER_KIND,
    CACHE_POLICY_SCHEMA_VERSION,
    QUERY_RESULT_CACHE_POLICY_DETAIL_KIND,
    AuthThrottleCachePolicyDetail,
    CacheFailureMode,
    CachePolicyEnvelope,
    CachePolicyHeader,
)
from src.infrastructure.auth.auth_failure_throttle import (
    AuthFailureThrottle,
    AuthThrottleChannel,
)
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.cache.cache_payload_codec import CachePayloadCodec
from src.infrastructure.cache.cache_service import (
    CacheIncrementRequest,
    CacheReadRequest,
    CacheService,
    CacheWriteRequest,
)
from src.infrastructure.cache.memory_cache_store import MemoryCacheStore
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import AppEnvironment
from src.infrastructure.testing.cache_policy_test_support import (
    TEST_AUTH_THROTTLE_POLICY_TTL_SECONDS,
    CachePolicyTestFactory,
)
from src.infrastructure.testing.fake_cache_store import FakeCacheStore
from src.infrastructure.testing.fake_clock import FakeClock

DEFAULT_CACHE_TTL_SECONDS = 30
TEST_CACHE_KEY_PREFIX = "unit_cache"
EXPLICIT_CACHE_TTL_SECONDS = 5
FIXED_WINDOW_COUNTER_TTL_SECONDS = 5
FIXED_WINDOW_BEFORE_EXPIRY_SECONDS = 4.9
FIXED_WINDOW_EXPIRY_STEP_SECONDS = 0.1
FIRST_INCREMENT_COUNT = 1
SECOND_INCREMENT_COUNT = 2
SHA256_HEX_DIGEST_LENGTH = 64
TEST_SENSITIVE_SUBJECT = "raw-refresh-token-value"
TEST_CACHE_KEY_DIGEST = "digest"
FIXED_WINDOW_COUNTER_KEY = "fixed-window-counter"
FIXED_WINDOW_COUNTER_KEY_PARTS = ("issue_access_token", "fixed-window-counter")
CACHE_CAS_KEY = "cache-cas-key"
CACHE_CAS_INITIAL_VALUE = "cache-cas-initial"
CACHE_CAS_NEXT_VALUE = "cache-cas-next"
CACHE_CAS_STALE_VALUE = "cache-cas-stale"


class TestCacheUnit:
    """
    测试缓存单元测试集合，用于组织同一主题下的测试场景。
    """

    def test_cache_key_builder_should_join_prefix_namespace_and_key_parts(self) -> None:
        """
        验证缓存键构建器应拼接前缀命名空间与键片段。

        :returns: 无返回值。
        :rtype: None
        """

        cache_key = CacheKeyBuilder(key_prefix=TEST_CACHE_KEY_PREFIX).build(
            namespace=CacheNamespace.AUTH_THROTTLE,
            key_parts=["issue_access_token", "digest"],
        )

        assert cache_key == "unit_cache:auth_throttle:issue_access_token:digest"

    def test_cache_key_builder_when_key_part_empty_should_fail(self) -> None:
        """
        验证缓存键构建器当键片段为空应失败。

        :returns: 无返回值。
        :rtype: None
        """

        with pytest.raises(ValueError) as exc:
            CacheKeyBuilder(key_prefix=TEST_CACHE_KEY_PREFIX).build(
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=["issue_access_token", "   "],
            )

        assert "不能为空" in str(exc.value)

    def test_cache_key_builder_when_key_part_contains_separator_should_fail(self) -> None:
        """
        验证缓存键构建器当键片段包含分隔符应失败。

        :returns: 无返回值。
        :rtype: None
        """

        with pytest.raises(ValueError) as exc:
            CacheKeyBuilder(key_prefix=TEST_CACHE_KEY_PREFIX).build(
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=["issue_access_token", "bad:digest"],
            )

        assert "分隔符" in str(exc.value)

    def test_auth_failure_throttle_should_digest_sensitive_subject_before_key_build(
        self,
    ) -> None:
        """
        验证鉴权失败节流应先摘要化敏感主体再构造缓存键。

        :returns: 无返回值。
        :rtype: None
        """

        cache_service = self._build_cache_service(fake_clock=FakeClock())
        settings = AppSettingsLoader().load_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={},
        )
        throttle = AuthFailureThrottle(
            cache_service=cache_service,
            settings=settings.runtime.auth,
        )

        key_parts = throttle._build_counter_cache_key_parts(  # noqa: SLF001
            channel=AuthThrottleChannel.REFRESH_ACCESS_TOKEN,
            subject_key=TEST_SENSITIVE_SUBJECT,
        )

        assert TEST_SENSITIVE_SUBJECT not in key_parts
        assert len(key_parts[-1]) == SHA256_HEX_DIGEST_LENGTH

    def test_cache_service_should_increment_counter_atomically(self) -> None:
        """
        验证缓存服务应通过底层原子递增能力更新计数。

        :returns: 无返回值。
        :rtype: None
        """

        cache_service = self._build_cache_service(fake_clock=FakeClock())
        first_count = cache_service.increment_counter(
            CacheIncrementRequest(
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=["issue_access_token", "counter-digest"],
                ttl_seconds=EXPLICIT_CACHE_TTL_SECONDS,
            )
        )
        second_count = cache_service.increment_counter(
            CacheIncrementRequest(
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=["issue_access_token", "counter-digest"],
                ttl_seconds=EXPLICIT_CACHE_TTL_SECONDS,
            )
        )

        assert first_count == FIRST_INCREMENT_COUNT
        assert second_count == SECOND_INCREMENT_COUNT

    def test_memory_cache_store_increment_should_keep_fixed_window_ttl(self) -> None:
        """
        验证内存缓存计数递增不应刷新固定窗口 TTL。

        :returns: 无返回值。
        :rtype: None
        """

        fake_clock = FakeClock()
        cache_store = MemoryCacheStore(timer=fake_clock.now)
        try:
            first_count = cache_store.increment_with_expire(
                FIXED_WINDOW_COUNTER_KEY,
                FIXED_WINDOW_COUNTER_TTL_SECONDS,
            )
            fake_clock.advance(FIXED_WINDOW_BEFORE_EXPIRY_SECONDS)
            second_count = cache_store.increment_with_expire(
                FIXED_WINDOW_COUNTER_KEY,
                FIXED_WINDOW_COUNTER_TTL_SECONDS,
            )

            assert first_count == FIRST_INCREMENT_COUNT
            assert second_count == SECOND_INCREMENT_COUNT
            assert cache_store.get_value(FIXED_WINDOW_COUNTER_KEY) == str(SECOND_INCREMENT_COUNT)

            fake_clock.advance(FIXED_WINDOW_EXPIRY_STEP_SECONDS)
            assert cache_store.get_value(FIXED_WINDOW_COUNTER_KEY) is None
        finally:
            cache_store.close()

    def test_memory_cache_store_compare_and_set_should_require_expected_value(
        self,
    ) -> None:
        """
        验证内存缓存 CAS 仅在当前值匹配时替换。

        :returns: 无返回值。
        :rtype: None
        """

        cache_store = MemoryCacheStore()
        try:
            cache_store.set_value(
                CACHE_CAS_KEY,
                CACHE_CAS_INITIAL_VALUE,
                DEFAULT_CACHE_TTL_SECONDS,
            )

            replaced = cache_store.compare_and_set_value(
                CACHE_CAS_KEY,
                CACHE_CAS_INITIAL_VALUE,
                CACHE_CAS_NEXT_VALUE,
                DEFAULT_CACHE_TTL_SECONDS,
            )
            stale_replaced = cache_store.compare_and_set_value(
                CACHE_CAS_KEY,
                CACHE_CAS_INITIAL_VALUE,
                CACHE_CAS_STALE_VALUE,
                DEFAULT_CACHE_TTL_SECONDS,
            )

            assert replaced is True
            assert stale_replaced is False
            assert cache_store.get_value(CACHE_CAS_KEY) == CACHE_CAS_NEXT_VALUE
        finally:
            cache_store.close()

    def test_cache_service_increment_counter_should_not_refresh_counter_ttl(
        self,
    ) -> None:
        """
        验证缓存服务计数递增应沿用底层固定窗口 TTL。

        :returns: 无返回值。
        :rtype: None
        """

        fake_clock = FakeClock()
        cache_store = FakeCacheStore(timer=fake_clock.now)
        cache_service = CacheService(
            cache_store=cache_store,
            key_builder=CacheKeyBuilder(key_prefix=TEST_CACHE_KEY_PREFIX),
            payload_codec=CachePayloadCodec(),
            policy_resolver=CachePolicyTestFactory().build_resolver(
                runtime_default_ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
            ),
            default_ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
        )
        try:
            first_count = cache_service.increment_counter(
                CacheIncrementRequest(
                    namespace=CacheNamespace.AUTH_THROTTLE,
                    key_parts=list(FIXED_WINDOW_COUNTER_KEY_PARTS),
                    ttl_seconds=FIXED_WINDOW_COUNTER_TTL_SECONDS,
                )
            )
            fake_clock.advance(FIXED_WINDOW_BEFORE_EXPIRY_SECONDS)
            second_count = cache_service.increment_counter(
                CacheIncrementRequest(
                    namespace=CacheNamespace.AUTH_THROTTLE,
                    key_parts=list(FIXED_WINDOW_COUNTER_KEY_PARTS),
                    ttl_seconds=FIXED_WINDOW_COUNTER_TTL_SECONDS,
                )
            )
            fake_clock.advance(FIXED_WINDOW_EXPIRY_STEP_SECONDS)
            reset_count = cache_service.increment_counter(
                CacheIncrementRequest(
                    namespace=CacheNamespace.AUTH_THROTTLE,
                    key_parts=list(FIXED_WINDOW_COUNTER_KEY_PARTS),
                    ttl_seconds=FIXED_WINDOW_COUNTER_TTL_SECONDS,
                )
            )

            assert first_count == FIRST_INCREMENT_COUNT
            assert second_count == SECOND_INCREMENT_COUNT
            assert reset_count == FIRST_INCREMENT_COUNT
        finally:
            cache_store.close()

    def test_cache_payload_codec_should_encode_and_decode_envelope(self) -> None:
        """
        验证缓存载荷编解码器应编码与解码信封。

        :returns: 无返回值。
        :rtype: None
        """

        codec = CachePayloadCodec()
        raw_value = codec.encode(
            namespace=CacheNamespace.AUTH_THROTTLE,
            key="unit_cache:auth_throttle:issue_access_token:digest",
            ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
            payload=AuthThrottleStatePayload(
                failure_count=2,
                locked_until_epoch=1880000000,
            ),
        )

        cache_envelope = codec.decode(raw_value)

        assert cache_envelope.header.namespace == CacheNamespace.AUTH_THROTTLE
        assert cache_envelope.header.ttl_seconds == DEFAULT_CACHE_TTL_SECONDS
        assert cache_envelope.header.value_kind == cache_envelope.data.kind
        assert cache_envelope.data.failure_count == 2

    def test_cache_envelope_when_header_value_kind_mismatch_should_fail(self) -> None:
        """
        验证缓存信封当头值类型不匹配应失败。

        :returns: 无返回值。
        :rtype: None
        :raises AssertionError: 当当前步骤检测到异常条件时抛出。
        """

        try:
            CacheEnvelope.model_validate(
                {
                    "header": {
                        "namespace": CacheNamespace.AUTH_THROTTLE,
                        "key": "unit_cache:auth_throttle:issue_access_token:digest",
                        "ttl_seconds": DEFAULT_CACHE_TTL_SECONDS,
                        "value_kind": "token_session_status",
                    },
                    "data": {
                        "kind": "auth_throttle_state",
                        "schema_version": "1.0",
                        "failure_count": 1,
                        "locked_until_epoch": None,
                    },
                }
            )
        except Exception as exc:
            assert "value_kind" in str(exc)
        else:
            raise AssertionError("预期缓存信封校验失败。")

    def test_cache_policy_envelope_should_validate_discriminated_detail(self) -> None:
        """
        验证缓存策略信封应校验判别联合扩展字段。

        :returns: 无返回值。
        :rtype: None
        """

        envelope = CachePolicyEnvelope(
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

        assert envelope.detail.failure_mode == CacheFailureMode.FAIL_CLOSED

    def test_cache_policy_envelope_when_detail_kind_mismatch_should_fail(self) -> None:
        """
        验证缓存策略信封当外层内层类型不一致应失败。

        :returns: 无返回值。
        :rtype: None
        """

        with pytest.raises(ValueError) as exc:
            CachePolicyEnvelope(
                header=CachePolicyHeader(
                    kind=CACHE_POLICY_HEADER_KIND,
                    schema_version=CACHE_POLICY_SCHEMA_VERSION,
                    detail_kind=QUERY_RESULT_CACHE_POLICY_DETAIL_KIND,
                    namespace=CacheNamespace.AUTH_THROTTLE,
                ),
                detail=AuthThrottleCachePolicyDetail(
                    default_ttl_seconds=TEST_AUTH_THROTTLE_POLICY_TTL_SECONDS,
                ),
            )

        assert "detail_kind" in str(exc.value)

    def test_cache_policy_envelope_when_detail_extra_field_should_fail(self) -> None:
        """
        验证缓存策略扩展字段当出现未知字段应失败。

        :returns: 无返回值。
        :rtype: None
        """

        with pytest.raises(ValueError) as exc:
            CachePolicyEnvelope.model_validate(
                {
                    "header": {
                        "kind": CACHE_POLICY_HEADER_KIND,
                        "schema_version": CACHE_POLICY_SCHEMA_VERSION,
                        "detail_kind": QUERY_RESULT_CACHE_POLICY_DETAIL_KIND,
                        "namespace": CacheNamespace.QUERY_RESULT,
                    },
                    "detail": {
                        "kind": QUERY_RESULT_CACHE_POLICY_DETAIL_KIND,
                        "schema_version": CACHE_POLICY_SCHEMA_VERSION,
                        "namespace": CacheNamespace.QUERY_RESULT,
                        "default_ttl_seconds": DEFAULT_CACHE_TTL_SECONDS,
                        "failure_mode": CacheFailureMode.FAIL_OPEN,
                        "unexpected_field": True,
                    },
                }
            )

        assert "unexpected_field" in str(exc.value)

    def test_cache_service_should_resolve_ttl_by_explicit_namespace_and_runtime(
        self,
    ) -> None:
        """
        验证缓存服务应按显式、命名空间、运行时顺序解析 TTL。

        :returns: 无返回值。
        :rtype: None
        """

        fake_clock = FakeClock()
        cache_service = self._build_cache_service(fake_clock=fake_clock)
        explicit_key_parts = ["issue_access_token", "explicit-digest"]
        namespace_key_parts = ["issue_access_token", "namespace-digest"]
        runtime_key_parts = ["query_result", "runtime-digest"]

        cache_service.write_payload(
            CacheWriteRequest(
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=explicit_key_parts,
                payload=AuthThrottleStatePayload(
                    failure_count=1,
                    locked_until_epoch=None,
                ),
                ttl_seconds=EXPLICIT_CACHE_TTL_SECONDS,
            )
        )
        cache_service.write_payload(
            CacheWriteRequest(
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=namespace_key_parts,
                payload=AuthThrottleStatePayload(
                    failure_count=1,
                    locked_until_epoch=None,
                ),
            )
        )
        fallback_cache_service = self._build_cache_service(
            fake_clock=fake_clock,
            include_namespace_policies=False,
        )
        fallback_cache_service.write_payload(
            CacheWriteRequest(
                namespace=CacheNamespace.QUERY_RESULT,
                key_parts=runtime_key_parts,
                payload=AuthThrottleStatePayload(
                    failure_count=1,
                    locked_until_epoch=None,
                ),
            )
        )

        assert (
            self._read_cache_entry_ttl_seconds(
                cache_service=cache_service,
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=explicit_key_parts,
            )
            == EXPLICIT_CACHE_TTL_SECONDS
        )
        assert (
            self._read_cache_entry_ttl_seconds(
                cache_service=cache_service,
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=namespace_key_parts,
            )
            == TEST_AUTH_THROTTLE_POLICY_TTL_SECONDS
        )
        assert (
            self._read_cache_entry_ttl_seconds(
                cache_service=fallback_cache_service,
                namespace=CacheNamespace.QUERY_RESULT,
                key_parts=runtime_key_parts,
            )
            == DEFAULT_CACHE_TTL_SECONDS
        )

    def test_cache_service_when_ttl_missing_should_use_default_ttl(self) -> None:
        """
        验证缓存服务当TTL缺失应用途默认TTL。

        :returns: 无返回值。
        :rtype: None
        :raises AssertionError: 当当前步骤检测到异常条件时抛出。
        """

        fake_clock = FakeClock()
        cache_service = self._build_cache_service(fake_clock=fake_clock)
        cache_service.write_payload(
            CacheWriteRequest(
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=["issue_access_token", "digest"],
                payload=AuthThrottleStatePayload(
                    failure_count=1,
                    locked_until_epoch=None,
                ),
            )
        )

        cache_key = CacheKeyBuilder(key_prefix=TEST_CACHE_KEY_PREFIX).build(
            namespace=CacheNamespace.AUTH_THROTTLE,
            key_parts=["issue_access_token", "digest"],
        )
        raw_value = cache_service._cache_store.get_value(cache_key)  # noqa: SLF001
        if raw_value is None:
            raise AssertionError("缓存值未写入。")
        cache_envelope = CachePayloadCodec().decode(raw_value)
        assert cache_envelope.header.ttl_seconds == TEST_AUTH_THROTTLE_POLICY_TTL_SECONDS

        fake_clock.advance(TEST_AUTH_THROTTLE_POLICY_TTL_SECONDS - 0.1)
        read_result = cache_service.read_payload(
            CacheReadRequest(
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=["issue_access_token", "digest"],
                payload_type=AuthThrottleStatePayload,
            )
        )
        assert read_result.hit is True

        fake_clock.advance(0.1)
        expired_result = cache_service.read_payload(
            CacheReadRequest(
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=["issue_access_token", "digest"],
                payload_type=AuthThrottleStatePayload,
            )
        )
        assert expired_result.hit is False
        assert expired_result.payload is None

    def test_cache_service_when_payload_type_mismatch_should_clear_value(self) -> None:
        """
        验证缓存服务当载荷类型不匹配应清理值。

        :returns: 无返回值。
        :rtype: None
        """

        cache_service = self._build_cache_service(fake_clock=FakeClock())
        cache_service.write_payload(
            CacheWriteRequest(
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=["issue_access_token", "digest"],
                payload=AuthThrottleStatePayload(
                    failure_count=1,
                    locked_until_epoch=None,
                ),
            )
        )

        read_result = cache_service.read_payload(
            CacheReadRequest(
                namespace=CacheNamespace.AUTH_THROTTLE,
                key_parts=["issue_access_token", "digest"],
                payload_type=TokenSessionStatusPayload,
            )
        )

        assert read_result.hit is False
        assert read_result.payload is None
        cache_key = CacheKeyBuilder(key_prefix=TEST_CACHE_KEY_PREFIX).build(
            namespace=CacheNamespace.AUTH_THROTTLE,
            key_parts=["issue_access_token", "digest"],
        )
        assert cache_service._cache_store.get_value(cache_key) is None  # noqa: SLF001

    def _read_cache_entry_ttl_seconds(
        self,
        *,
        cache_service: CacheService,
        namespace: CacheNamespace,
        key_parts: list[str],
    ) -> int:
        """
        读取缓存入口中记录的 TTL 秒数。

        :param cache_service: 缓存服务。
        :type cache_service: CacheService
        :param namespace: 缓存命名空间。
        :type namespace: CacheNamespace
        :param key_parts: 缓存键片段。
        :type key_parts: list[str]
        :returns: 返回缓存信封头中的 TTL 秒数。
        :rtype: int
        :raises AssertionError: 当缓存值不存在时抛出。
        """

        cache_key = CacheKeyBuilder(key_prefix=TEST_CACHE_KEY_PREFIX).build(
            namespace=namespace,
            key_parts=key_parts,
        )
        raw_value = cache_service._cache_store.get_value(cache_key)  # noqa: SLF001
        if raw_value is None:
            raise AssertionError("缓存值未写入。")
        return CachePayloadCodec().decode(raw_value).header.ttl_seconds

    def _build_cache_service(
        self,
        *,
        fake_clock: FakeClock,
        include_namespace_policies: bool = True,
    ) -> CacheService:
        """
        构建缓存服务。

        :param fake_clock: 当前步骤使用的模拟时钟参数。约束：需符合 ``FakeClock`` 注解。
        :type fake_clock: FakeClock
        :param include_namespace_policies: 是否包含命名空间策略。
        :type include_namespace_policies: bool
        :returns: 返回当前操作结果。
        :rtype: CacheService
        """

        return CacheService(
            cache_store=FakeCacheStore(timer=fake_clock.now),
            key_builder=CacheKeyBuilder(key_prefix=TEST_CACHE_KEY_PREFIX),
            payload_codec=CachePayloadCodec(),
            policy_resolver=CachePolicyTestFactory().build_resolver(
                runtime_default_ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
                include_namespace_policies=include_namespace_policies,
            ),
            default_ttl_seconds=DEFAULT_CACHE_TTL_SECONDS,
        )
