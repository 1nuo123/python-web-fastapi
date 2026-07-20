"""
鉴权失败节流基础设施模块。
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from http import HTTPStatus

from src.core.auth_contract.auth_throttle_state_contract import AuthThrottleStatePayload
from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.auth.auth_error_code import AuthErrorCode
from src.infrastructure.cache.cache_service import (
    CacheDeleteRequest,
    CacheIncrementRequest,
    CacheReadRequest,
    CacheService,
    CacheWriteRequest,
)
from src.infrastructure.settings.application_settings import AuthRuntimeSettings

THROTTLE_MESSAGE = "请求过于频繁，请稍后重试。"
AUTH_THROTTLE_CACHE_NAMESPACE = CacheNamespace.AUTH_THROTTLE
AUTH_THROTTLE_COUNTER_KEY_PART = "counter"
AUTH_THROTTLE_LOCK_KEY_PART = "lock"


class AuthThrottleChannel(StrEnum):
    """
    鉴权节流通道枚举，用于约束可选取值。

    :cvar ISSUE_ACCESS_TOKEN: ``ISSUE_ACCESS_TOKEN`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'issue_access_token'`。取值语义：用于承载当前对象中的业务状态。
    :vartype ISSUE_ACCESS_TOKEN: str
    :cvar REFRESH_ACCESS_TOKEN: ``REFRESH_ACCESS_TOKEN`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'refresh_access_token'`。取值语义：用于承载当前对象中的业务状态。
    :vartype REFRESH_ACCESS_TOKEN: str
    """

    ISSUE_ACCESS_TOKEN = "issue_access_token"
    REFRESH_ACCESS_TOKEN = "refresh_access_token"


@dataclass(slots=True)
class AuthThrottlePolicy:
    """
    鉴权节流策略数据对象，用于承载当前流程的结构化字段。

    :ivar failure_limit: ``failure_limit`` 字段。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype failure_limit: int
    :ivar failure_window_seconds: ``failure_window_seconds`` 字段。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype failure_window_seconds: int
    :ivar throttle_lock_seconds: 节流锁定秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype throttle_lock_seconds: int
    """

    failure_limit: int
    failure_window_seconds: int
    throttle_lock_seconds: int


class AuthFailureThrottle:
    """
    鉴权失败节流类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(
        self,
        *,
        cache_service: CacheService,
        settings: AuthRuntimeSettings,
        timer: Callable[[], int] | None = None,
    ) -> None:
        """
        初始化鉴权失败节流。

        :param cache_service: ``cache_service`` 服务实例。约束：需符合 ``CacheService`` 注解。
        :type cache_service: CacheService
        :param settings: 已经通过校验的应用配置快照。约束：需符合 ``AuthRuntimeSettings`` 注解。
        :type settings: AuthRuntimeSettings
        :param timer: 计时器或时钟实现。默认值：`None`。约束：需符合 ``Callable[[], int] | None`` 注解。
        :type timer: Callable[[], int] | None
        :returns: 无返回值。
        :rtype: None
        """

        self._cache_service = cache_service
        self._settings = settings
        self._timer = timer or self._read_current_epoch

    def assert_issue_access_token_allowed(self, username: str) -> None:
        """
        断言签发访问令牌允许。

        :param username: 当前步骤使用的用户名参数。约束：需符合 ``str`` 注解。
        :type username: str
        :returns: 无返回值。
        :rtype: None
        """

        self._assert_allowed(
            channel=AuthThrottleChannel.ISSUE_ACCESS_TOKEN,
            subject_key=username,
            policy=self._build_issue_access_token_policy(),
        )

    def record_issue_access_token_failure(self, username: str) -> None:
        """
        记录签发访问令牌失败。

        :param username: 当前步骤使用的用户名参数。约束：需符合 ``str`` 注解。
        :type username: str
        :returns: 无返回值。
        :rtype: None
        """

        self._record_failure(
            channel=AuthThrottleChannel.ISSUE_ACCESS_TOKEN,
            subject_key=username,
            policy=self._build_issue_access_token_policy(),
        )

    def clear_issue_access_token_failures(self, username: str) -> None:
        """
        清理签发访问令牌失败记录。

        :param username: 当前步骤使用的用户名参数。约束：需符合 ``str`` 注解。
        :type username: str
        :returns: 无返回值。
        :rtype: None
        """

        self._clear_failures(
            channel=AuthThrottleChannel.ISSUE_ACCESS_TOKEN,
            subject_key=username,
        )

    def assert_refresh_access_token_allowed(self, subject_key: str) -> None:
        """
        断言刷新访问令牌允许。

        :param subject_key: 刷新令牌节流主体键。约束：需符合 ``str`` 注解。
        :type subject_key: str
        :returns: 无返回值。
        :rtype: None
        """

        self._assert_allowed(
            channel=AuthThrottleChannel.REFRESH_ACCESS_TOKEN,
            subject_key=subject_key,
            policy=self._build_refresh_access_token_policy(),
        )

    def record_refresh_access_token_failure(self, subject_key: str) -> None:
        """
        记录刷新访问令牌失败。

        :param subject_key: 刷新令牌节流主体键。约束：需符合 ``str`` 注解。
        :type subject_key: str
        :returns: 无返回值。
        :rtype: None
        """

        self._record_failure(
            channel=AuthThrottleChannel.REFRESH_ACCESS_TOKEN,
            subject_key=subject_key,
            policy=self._build_refresh_access_token_policy(),
        )

    def clear_refresh_access_token_failures(self, subject_key: str) -> None:
        """
        清理刷新访问令牌失败记录。

        :param subject_key: 刷新令牌节流主体键。约束：需符合 ``str`` 注解。
        :type subject_key: str
        :returns: 无返回值。
        :rtype: None
        """

        self._clear_failures(
            channel=AuthThrottleChannel.REFRESH_ACCESS_TOKEN,
            subject_key=subject_key,
        )

    def _assert_allowed(
        self,
        *,
        channel: AuthThrottleChannel,
        subject_key: str,
        policy: AuthThrottlePolicy,
    ) -> None:
        """
        断言允许。

        :param channel: 节流或业务通道标识。约束：需符合 ``AuthThrottleChannel`` 注解。
        :type channel: AuthThrottleChannel
        :param subject_key: 参与节流和缓存键构造的主体键。约束：需符合 ``str`` 注解。
        :type subject_key: str
        :param policy: 授权策略对象。约束：需符合 ``AuthThrottlePolicy`` 注解。
        :type policy: AuthThrottlePolicy
        :returns: 无返回值。
        :rtype: None
        :raises HttpFaultException: 当业务校验失败、资源未就绪、配置错误或令牌状态异常时抛出。
        """

        state = self._read_lock_state(channel=channel, subject_key=subject_key)
        if state is None or state.locked_until_epoch is None:
            return
        current_epoch = self._timer()
        if current_epoch >= state.locked_until_epoch:
            self._clear_failures(channel=channel, subject_key=subject_key)
            return
        raise HttpFaultException(
            status_code=HTTPStatus.TOO_MANY_REQUESTS,
            error_code=AuthErrorCode.REQUEST_THROTTLED,
            message=THROTTLE_MESSAGE,
            detail=(f"{channel} 在 {policy.throttle_lock_seconds} 秒锁定窗口内达到失败上限。"),
        )

    def _record_failure(
        self,
        *,
        channel: AuthThrottleChannel,
        subject_key: str,
        policy: AuthThrottlePolicy,
    ) -> None:
        """
        记录失败。

        :param channel: 节流或业务通道标识。约束：需符合 ``AuthThrottleChannel`` 注解。
        :type channel: AuthThrottleChannel
        :param subject_key: 参与节流和缓存键构造的主体键。约束：需符合 ``str`` 注解。
        :type subject_key: str
        :param policy: 授权策略对象。约束：需符合 ``AuthThrottlePolicy`` 注解。
        :type policy: AuthThrottlePolicy
        :returns: 无返回值。
        :rtype: None
        """

        current_epoch = self._timer()
        failure_count = self._cache_service.increment_counter(
            CacheIncrementRequest(
                namespace=AUTH_THROTTLE_CACHE_NAMESPACE,
                key_parts=self._build_counter_cache_key_parts(
                    channel=channel,
                    subject_key=subject_key,
                ),
                ttl_seconds=policy.failure_window_seconds,
            )
        )
        locked_until_epoch = (
            current_epoch + policy.throttle_lock_seconds
            if failure_count >= policy.failure_limit
            else None
        )
        if locked_until_epoch is None:
            return
        self._cache_service.write_payload(
            CacheWriteRequest(
                namespace=AUTH_THROTTLE_CACHE_NAMESPACE,
                key_parts=self._build_lock_cache_key_parts(
                    channel=channel,
                    subject_key=subject_key,
                ),
                payload=AuthThrottleStatePayload(
                    failure_count=failure_count,
                    locked_until_epoch=locked_until_epoch,
                ),
                ttl_seconds=policy.throttle_lock_seconds,
            )
        )

    def _clear_failures(
        self,
        *,
        channel: AuthThrottleChannel,
        subject_key: str,
    ) -> None:
        """
        清理失败记录。

        :param channel: 节流或业务通道标识。约束：需符合 ``AuthThrottleChannel`` 注解。
        :type channel: AuthThrottleChannel
        :param subject_key: 参与节流和缓存键构造的主体键。约束：需符合 ``str`` 注解。
        :type subject_key: str
        :returns: 无返回值。
        :rtype: None
        """

        self._cache_service.delete_payload(
            CacheDeleteRequest(
                namespace=AUTH_THROTTLE_CACHE_NAMESPACE,
                key_parts=self._build_counter_cache_key_parts(
                    channel=channel,
                    subject_key=subject_key,
                ),
            )
        )
        self._cache_service.delete_payload(
            CacheDeleteRequest(
                namespace=AUTH_THROTTLE_CACHE_NAMESPACE,
                key_parts=self._build_lock_cache_key_parts(
                    channel=channel,
                    subject_key=subject_key,
                ),
            )
        )

    def _read_lock_state(
        self,
        *,
        channel: AuthThrottleChannel,
        subject_key: str,
    ) -> AuthThrottleStatePayload | None:
        """
        读取状态。

        :param channel: 节流或业务通道标识。约束：需符合 ``AuthThrottleChannel`` 注解。
        :type channel: AuthThrottleChannel
        :param subject_key: 参与节流和缓存键构造的主体键。约束：需符合 ``str`` 注解。
        :type subject_key: str
        :returns: 返回当前操作结果。
        :rtype: AuthThrottleStatePayload | None
        """

        return self._cache_service.read_payload(
            CacheReadRequest(
                namespace=AUTH_THROTTLE_CACHE_NAMESPACE,
                key_parts=self._build_lock_cache_key_parts(
                    channel=channel,
                    subject_key=subject_key,
                ),
                payload_type=AuthThrottleStatePayload,
            )
        ).payload

    def _build_issue_access_token_policy(self) -> AuthThrottlePolicy:
        """
        构建签发访问令牌策略。

        :returns: 返回当前操作结果。
        :rtype: AuthThrottlePolicy
        """

        return AuthThrottlePolicy(
            failure_limit=self._settings.issue_access_token_failure_limit,
            failure_window_seconds=self._settings.issue_access_token_failure_window_seconds,
            throttle_lock_seconds=self._settings.throttle_lock_seconds,
        )

    def _build_refresh_access_token_policy(self) -> AuthThrottlePolicy:
        """
        构建刷新访问令牌策略。

        :returns: 返回当前操作结果。
        :rtype: AuthThrottlePolicy
        """

        return AuthThrottlePolicy(
            failure_limit=self._settings.refresh_access_token_failure_limit,
            failure_window_seconds=self._settings.refresh_access_token_failure_window_seconds,
            throttle_lock_seconds=self._settings.throttle_lock_seconds,
        )

    def _build_counter_cache_key_parts(
        self,
        *,
        channel: AuthThrottleChannel,
        subject_key: str,
    ) -> list[str]:
        """
        构建鉴权节流计数缓存键片段。

        :param channel: 鉴权节流通道。
        :type channel: AuthThrottleChannel
        :param subject_key: 节流主体键。
        :type subject_key: str
        :returns: 缓存键片段。
        :rtype: list[str]
        """

        return [
            channel.value,
            AUTH_THROTTLE_COUNTER_KEY_PART,
            self._build_subject_digest(subject_key),
        ]

    def _build_lock_cache_key_parts(
        self,
        *,
        channel: AuthThrottleChannel,
        subject_key: str,
    ) -> list[str]:
        """
        构建缓存键片段。

        :param channel: 节流或业务通道标识。约束：需符合 ``AuthThrottleChannel`` 注解。
        :type channel: AuthThrottleChannel
        :param subject_key: 参与节流和缓存键构造的主体键。约束：需符合 ``str`` 注解。
        :type subject_key: str
        :returns: 返回按实现构造的列表结果。
        :rtype: list[str]
        """

        return [
            channel.value,
            AUTH_THROTTLE_LOCK_KEY_PART,
            self._build_subject_digest(subject_key),
        ]

    def _build_subject_digest(self, subject_key: str) -> str:
        """
        构建主体摘要。

        :param subject_key: 参与节流和缓存键构造的主体键。约束：需符合 ``str`` 注解。
        :type subject_key: str
        :returns: 返回当前操作结果。
        :rtype: str
        """

        return hashlib.sha256(subject_key.encode("utf-8")).hexdigest()

    def _read_current_epoch(self) -> int:
        """
        读取当前时间戳。

        :returns: 返回当前操作结果。
        :rtype: int
        """

        return int(time.time())
