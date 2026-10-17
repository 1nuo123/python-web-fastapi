"""HTTP与WSS共用系统代理解析及TLS信任，不依赖两套库的隐式默认。"""

from __future__ import annotations

import ssl
from urllib.parse import urlsplit
from urllib.request import getproxies, proxy_bypass

from src.infrastructure.codex_agent.agent_configuration import (
    AgentProcessSettings,
    build_agent_tls_context,
)


class AgentNetworkPolicy:
    def __init__(self, settings: AgentProcessSettings) -> None:
        self._settings = settings
        self.tls_context = (
            ssl.create_default_context(cafile=str(settings.ca_certificate_path))
            if settings.ca_certificate_path is not None
            else build_agent_tls_context(
                deployment_profile=settings.deployment_profile,
                development_ca_certificate_path=settings.development_ca_certificate_path,
            )
            or ssl.create_default_context()
        )

    def proxy_for(self, url: str) -> str | None:
        if self._settings.network_mode == "direct":
            return None
        if self._settings.network_mode == "explicit":
            return self._settings.proxy_url
        parsed = urlsplit(url)
        if proxy_bypass(parsed.netloc):
            return None
        scheme = {"wss": "https", "ws": "http"}.get(parsed.scheme, parsed.scheme)
        proxies = getproxies()
        proxy = proxies.get(scheme) or proxies.get("all")
        if proxy and urlsplit(proxy).scheme not in {"http", "https"}:
            raise ValueError("系统代理不是HTTP/HTTPS；请显式配置兼容代理。")
        return proxy

    def describe(self, url: str) -> str:
        proxy = self.proxy_for(url)
        if proxy is None:
            return f"{self._settings.network_mode}: direct"
        parsed = urlsplit(proxy)
        return f"{self._settings.network_mode}: {parsed.scheme}://{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"
