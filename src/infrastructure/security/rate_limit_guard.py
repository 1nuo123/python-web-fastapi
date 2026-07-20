"""
限流守卫模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus

from fastapi import Request

from src.core.cache_contract.cache_namespace_contract import CacheNamespace
from src.core.cache_contract.cache_store_contract import CacheStore
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.security_runtime_contract import RateLimitFailMode
from src.core.security_contract.rate_limit_policy_contract import RateLimitKeyDimension
from src.infrastructure.cache.cache_key_builder import CacheKeyBuilder
from src.infrastructure.key_management.sensitive_digest_service import (
    SensitiveDigestService,
)
from src.infrastructure.security.client_ip_resolver import ClientIpResolver

RATE_LIMIT_CACHE_SEGMENT = "http"
RATE_LIMIT_CACHE_UNAVAILABLE_MESSAGE = "限流缓存不可用。"
RATE_LIMIT_POLICY_DEFAULT = "default"
RATE_LIMIT_PATH_METHOD_SEPARATOR = ":"
RATE_LIMIT_AUTH_FIELD_SEPARATOR = "|"


@dataclass(slots=True)
class RateLimitResult:
    """
    限流结果。
    """

    exceeded: bool
    count: int
    limit: int
    retry_after_seconds: int
    ip_digest: str
    subject_digest: str | None = None
    path_digest: str | None = None
    method: str | None = None
    auth_field_digest: str | None = None


class RateLimitGuard:
    """
    限流守卫。
    """

    def __init__(
        self,
        *,
        cache_store: CacheStore,
        key_builder: CacheKeyBuilder,
        digest_service: SensitiveDigestService,
        client_ip_resolver: ClientIpResolver | None = None,
    ) -> None:
        """
        初始化限流守卫。
        """

        self._cache_store = cache_store
        self._key_builder = key_builder
        self._digest_service = digest_service
        self._client_ip_resolver = client_ip_resolver or ClientIpResolver()

    def evaluate(
        self,
        *,
        request: Request,
        limit: int,
        window_seconds: int,
        policy_name: str = RATE_LIMIT_POLICY_DEFAULT,
        key_dimensions: list[RateLimitKeyDimension] | None = None,
        auth_field_values: list[str] | None = None,
        fail_mode: RateLimitFailMode = RateLimitFailMode.FAIL_CLOSED,
    ) -> RateLimitResult:
        """
        评估请求限流。
        """

        dimensions = key_dimensions or [
            RateLimitKeyDimension.IP_DIGEST,
            RateLimitKeyDimension.PATH_METHOD,
        ]
        ip_digest = self._digest_service.digest(self._client_ip_resolver.resolve_client_ip(request))
        subject_digest = self._build_subject_digest(request)
        path_digest = self._digest_service.digest(
            RATE_LIMIT_PATH_METHOD_SEPARATOR.join([request.method, request.url.path])
        )
        auth_field_digest = self._build_auth_field_digest(auth_field_values)
        cache_key = self._key_builder.build(
            namespace=CacheNamespace.RATE_LIMIT,
            key_parts=self._build_key_parts(
                policy_name=policy_name,
                dimensions=dimensions,
                ip_digest=ip_digest,
                subject_digest=subject_digest,
                path_digest=path_digest,
                auth_field_digest=auth_field_digest,
            ),
        )
        try:
            count = self._cache_store.increment_with_expire(cache_key, window_seconds)
        except Exception as exc:
            if fail_mode != RateLimitFailMode.FAIL_CLOSED:
                raise
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.CACHE_UNAVAILABLE,
                message=RATE_LIMIT_CACHE_UNAVAILABLE_MESSAGE,
                detail=str(exc),
            ) from exc
        return RateLimitResult(
            exceeded=count > limit,
            count=count,
            limit=limit,
            retry_after_seconds=window_seconds,
            ip_digest=ip_digest,
            subject_digest=subject_digest,
            path_digest=path_digest,
            method=request.method,
            auth_field_digest=auth_field_digest,
        )

    def _build_key_parts(
        self,
        *,
        policy_name: str,
        dimensions: list[RateLimitKeyDimension],
        ip_digest: str,
        subject_digest: str | None,
        path_digest: str,
        auth_field_digest: str | None,
    ) -> list[str]:
        """
        构建限流缓存键片段。
        """

        key_parts = [RATE_LIMIT_CACHE_SEGMENT, policy_name]
        for dimension in dimensions:
            if dimension == RateLimitKeyDimension.IP_DIGEST:
                key_parts.extend([dimension.value, ip_digest])
            elif dimension == RateLimitKeyDimension.SUBJECT_ID:
                if subject_digest is not None:
                    key_parts.extend([dimension.value, subject_digest])
            elif dimension == RateLimitKeyDimension.PATH_METHOD:
                key_parts.extend([dimension.value, path_digest])
            elif dimension == RateLimitKeyDimension.AUTH_FIELD_DIGEST:
                if auth_field_digest is not None:
                    key_parts.extend([dimension.value, auth_field_digest])
        return key_parts

    def _build_subject_digest(self, request: Request) -> str | None:
        """
        构建已认证主体摘要。
        """

        request_scope = getattr(request.state, "request_scope", None)
        subject_id = getattr(request_scope, "authenticated_subject_id", None)
        if subject_id is None:
            return None
        return self._digest_service.digest(subject_id)

    def _build_auth_field_digest(
        self,
        auth_field_values: list[str] | None,
    ) -> str | None:
        """
        构建认证字段摘要。
        """

        if not auth_field_values:
            return None
        return self._digest_service.digest(RATE_LIMIT_AUTH_FIELD_SEPARATOR.join(auth_field_values))
