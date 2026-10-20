"""Agent 制品发布资源的单一生命周期。"""

from __future__ import annotations

from dataclasses import dataclass
import httpx
from src.infrastructure.codex_agent.agent_network_policy import AgentNetworkPolicy

from src.application.artifact_release_orchestrator import ArtifactReleaseOrchestrator
from src.core.artifact_release_contract.runtime_contract import ArtifactReleaseRuntimeSettings
from src.core.http_contract.outbound_http_client_contract import AsyncHttpClientDetail
from src.infrastructure.artifact_release.composite_verifier import CompositeArtifactVerifier
from src.infrastructure.artifact_release.digest_verifier import Sha256ArtifactVerifier
from src.infrastructure.artifact_release.rollout_policy import ArtifactRolloutPolicy
from src.infrastructure.artifact_release.safe_downloader import SafeArtifactDownloader
from src.infrastructure.artifact_release.signed_activation import (
    AtomicArtifactActivationAdapter,
)
from src.infrastructure.artifact_release.staging_store import LocalArtifactStagingStore
from src.infrastructure.artifact_release.tuf_catalog_adapter import TufArtifactCatalogAdapter
from src.infrastructure.artifact_release.windows_authenticode_verifier import (
    WindowsAuthenticodeArtifactVerifier,
)
from src.infrastructure.codex_agent.codex_agent_update_coordinator import (
    CodexAgentUpdateCoordinator,
)
from src.infrastructure.resource_slot.shared_async_http_client import SharedAsyncHttpClient

ARTIFACT_HTTP_MAX_CONNECTIONS = 4
ARTIFACT_HTTP_MAX_KEEPALIVE_CONNECTIONS = 2


@dataclass(slots=True)
class CodexAgentReleaseRuntime:
    """共享 HTTP client 与通用发布编排的生命周期所有者。"""

    http_resource: SharedAsyncHttpClient
    catalog: TufArtifactCatalogAdapter
    coordinator: CodexAgentUpdateCoordinator

    @classmethod
    def build(
        cls, settings: ArtifactReleaseRuntimeSettings, *, network: AgentNetworkPolicy | None = None
    ) -> CodexAgentReleaseRuntime:
        http_resource = SharedAsyncHttpClient(
            AsyncHttpClientDetail(
                timeout_seconds=settings.request_timeout_seconds,
                max_connections=ARTIFACT_HTTP_MAX_CONNECTIONS,
                max_keepalive_connections=ARTIFACT_HTTP_MAX_KEEPALIVE_CONNECTIONS,
            ),
            tls_context=network.tls_context if network else None,
            proxy=network.http_proxy_for(settings.repository_url) if network else None,
            trust_env=False,
        )
        catalog = TufArtifactCatalogAdapter(
            settings=settings,
            client=httpx.Client(
                verify=network.tls_context if network else True,
                proxy=network.http_proxy_for(settings.repository_url) if network else None,
                trust_env=False,
                follow_redirects=False,
                timeout=settings.request_timeout_seconds,
            ),
        )
        orchestrator = ArtifactReleaseOrchestrator(
            catalog=catalog,
            downloader=SafeArtifactDownloader(
                client=http_resource.get_client(),
                settings=settings,
            ),
            verifier=CompositeArtifactVerifier(
                Sha256ArtifactVerifier(),
                WindowsAuthenticodeArtifactVerifier(
                    allowed_signer_sha256=settings.authenticode_signer_sha256_allowlist
                ),
            ),
            staging=LocalArtifactStagingStore(staging_root=settings.staging_root),
            activation=AtomicArtifactActivationAdapter(root=settings.staging_root),
        )
        return cls(
            http_resource=http_resource,
            catalog=catalog,
            coordinator=CodexAgentUpdateCoordinator(
                orchestrator=orchestrator,
                rollout_policy=ArtifactRolloutPolicy(),
            ),
        )

    async def close(self) -> None:
        """关闭唯一共享 HTTP 资源。"""

        self.catalog.close()
        await self.http_resource.close()
