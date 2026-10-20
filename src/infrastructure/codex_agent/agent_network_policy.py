"""HTTP与WSS共用系统代理解析及TLS信任，不依赖两套库的隐式默认。"""

from __future__ import annotations

import ssl
import httpx
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from urllib.request import getproxies, proxy_bypass

from src.infrastructure.codex_agent.agent_configuration import (
    AgentProcessSettings,
    build_agent_tls_context,
)
from src.infrastructure.codex_agent.agent_deployment_profile import AgentDeploymentProfile


@dataclass(frozen=True, slots=True)
class AgentNetworkSettings:
    """首装也能使用的网络配置，不依赖已存在的设备身份。"""

    deployment_profile: AgentDeploymentProfile = AgentDeploymentProfile.PRODUCTION
    development_ca_certificate_path: Path | None = None
    ca_certificate_path: Path | None = None
    network_mode: Literal["system", "direct", "explicit"] = "system"
    proxy_url: str | None = None


class AgentNetworkPolicy:
    def __init__(self, settings: AgentProcessSettings | AgentNetworkSettings) -> None:
        self._settings = settings
        if settings.network_mode == "explicit" and (
            not settings.proxy_url or urlsplit(settings.proxy_url).scheme not in {"http", "https"}
        ):
            raise ValueError("显式代理必须提供 HTTP/HTTPS 地址。")
        self.tls_context = (
            build_agent_tls_context(
                deployment_profile=settings.deployment_profile,
                development_ca_certificate_path=settings.development_ca_certificate_path,
            )
            or ssl.create_default_context()
        )
        if settings.ca_certificate_path is not None:
            self.tls_context.load_verify_locations(cafile=str(settings.ca_certificate_path))

    def http_proxy_for(self, url: str) -> httpx.Proxy | None:
        """目标服务与 HTTPS 代理使用同一严格信任链。"""
        proxy = self.proxy_for(url)
        if proxy is None:
            return None
        return httpx.Proxy(
            proxy,
            ssl_context=self.tls_context if urlsplit(proxy).scheme == "https" else None,
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
