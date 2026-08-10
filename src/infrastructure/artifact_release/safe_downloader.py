"""受仓库 allowlist 和大小上限约束的制品下载器。"""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx

from src.application.ports.artifact_release_port import ArtifactDownloaderPort
from src.core.artifact_release_contract.artifact_contract import ArtifactReleaseEnvelope
from src.core.artifact_release_contract.runtime_contract import ArtifactReleaseRuntimeSettings


class SafeArtifactDownloader(ArtifactDownloaderPort):
    """复用注入的共享 HTTP client，不创建第二套网络客户端。"""

    def __init__(
        self, *, client: httpx.AsyncClient, settings: ArtifactReleaseRuntimeSettings
    ) -> None:
        self._client = client
        self._settings = settings

    async def download(self, envelope: ArtifactReleaseEnvelope, target_url: str) -> bytes:
        parsed = urlsplit(target_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname not in self._settings.repository_host_allowlist
        ):
            raise ValueError("制品下载地址不在仓库 allowlist 中。")
        expected = envelope.tuf_target
        if expected is None:
            raise ValueError("制品缺少 TUF target 元数据。")
        async with self._client.stream("GET", target_url) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if (
                content_length is not None
                and int(content_length) > self._settings.max_download_bytes
            ):
                raise ValueError("制品超过下载大小上限。")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self._settings.max_download_bytes:
                    raise ValueError("制品超过下载大小上限。")
                chunks.append(chunk)
        content = b"".join(chunks)
        if len(content) != expected.length:
            raise ValueError("制品长度与 TUF 元数据不一致。")
        return content
