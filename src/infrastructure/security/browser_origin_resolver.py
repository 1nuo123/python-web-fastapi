"""Trusted browser Origin resolution shared by browser-facing write routes."""

from __future__ import annotations

from starlette.requests import HTTPConnection

from src.infrastructure.security.client_ip_resolver import ClientIpResolver

FORWARDED_HEADER_NAME = "forwarded"
X_FORWARDED_HOST_HEADER_NAME = "x-forwarded-host"
X_FORWARDED_PROTO_HEADER_NAME = "x-forwarded-proto"
FORWARDED_HOST_KEY = "host"
FORWARDED_PROTO_KEY = "proto"
FORWARDED_PAIR_SEPARATOR = ";"
FORWARDED_VALUE_SEPARATOR = ","
FORWARDED_KEY_VALUE_SEPARATOR = "="
SUPPORTED_BROWSER_ORIGIN_SCHEMES = frozenset({"http", "https"})


def build_allowed_browser_origins(
    request: HTTPConnection,
    *,
    configured_origins: set[str] | list[str] | tuple[str, ...] = (),
    client_ip_resolver: ClientIpResolver,
) -> set[str]:
    """Build the explicit browser Origin allowlist for a request.

    Forwarded host/proto values are accepted only when the direct peer belongs
    to the configured trusted-proxy networks. The application-origin fallback
    remains useful for direct requests and test clients.
    """

    scheme = {"ws": "http", "wss": "https"}.get(request.url.scheme, request.url.scheme)
    origins = {
        f"{scheme}://{request.url.netloc}",
        *(origin.rstrip("/") for origin in configured_origins),
    }
    forwarded_origin = read_trusted_forwarded_origin(request, client_ip_resolver)
    if forwarded_origin is not None:
        origins.add(forwarded_origin)
    return {origin.rstrip("/") for origin in origins if origin}


def read_trusted_forwarded_origin(
    request: HTTPConnection,
    client_ip_resolver: ClientIpResolver,
) -> str | None:
    """Read an externally visible Origin reconstructed by a trusted proxy."""

    if not client_ip_resolver.is_trusted_proxy(request):
        return None

    proto = _read_forwarded_value(request, FORWARDED_PROTO_KEY)
    if proto is None:
        proto = request.headers.get(X_FORWARDED_PROTO_HEADER_NAME)
    host = _read_forwarded_value(request, FORWARDED_HOST_KEY)
    if host is None:
        host = request.headers.get(X_FORWARDED_HOST_HEADER_NAME)
    if proto is None or host is None:
        return None

    normalized_proto = (
        proto.split(FORWARDED_VALUE_SEPARATOR, maxsplit=1)[0].strip().strip('"').lower()
    )
    normalized_host = host.split(FORWARDED_VALUE_SEPARATOR, maxsplit=1)[0].strip().strip('"')
    if (
        normalized_proto not in SUPPORTED_BROWSER_ORIGIN_SCHEMES
        or normalized_host == ""
        or any(character.isspace() for character in normalized_host)
        or any(character in normalized_host for character in "/\\?#@")
    ):
        return None
    return f"{normalized_proto}://{normalized_host}"


def is_trusted_https_request(
    request: HTTPConnection,
    client_ip_resolver: ClientIpResolver,
) -> bool:
    """判断请求是否由直连 HTTPS 或可信代理声明的 HTTPS 保护。

    应用本身通常运行在容器内 HTTP 上，不能仅凭 ``X-Forwarded-Proto``
    决定 Cookie 安全属性。只有直连 TLS，或直接对端命中可信代理网段且
    协议值严格为单一 ``https`` 时，才允许把浏览器 Cookie 标记为 Secure。
    """

    if request.url.scheme.lower() == "https":
        return True
    if not client_ip_resolver.is_trusted_proxy(request):
        return False

    # Caddy replaces X-Forwarded-Proto and strips Forwarded before each
    # upstream hop. Do not use the generic header here because clients can
    # otherwise inject it before reaching the public gateway.
    return request.headers.get(X_FORWARDED_PROTO_HEADER_NAME) == "https"


def _read_forwarded_value(request: HTTPConnection, key: str) -> str | None:
    header_value = request.headers.get(FORWARDED_HEADER_NAME)
    if header_value is None:
        return None
    first_forwarded = header_value.split(FORWARDED_VALUE_SEPARATOR, maxsplit=1)[0]
    for part in first_forwarded.split(FORWARDED_PAIR_SEPARATOR):
        candidate_key, separator, value = part.partition(FORWARDED_KEY_VALUE_SEPARATOR)
        if separator and candidate_key.strip().lower() == key:
            return value
    return None
