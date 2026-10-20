"""python-tuf target 解析适配器。"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import httpx
from tuf.api import exceptions as tuf_exceptions
from tuf.ngclient import Updater
from tuf.ngclient.fetcher import FetcherInterface

from src.application.ports.artifact_release_port import ArtifactCatalogPort
from src.core.artifact_release_contract.artifact_contract import (
    ArtifactIdentity,
    ArtifactReleaseEnvelope,
    TufTargetMetadata,
)
from src.core.artifact_release_contract.runtime_contract import ArtifactReleaseRuntimeSettings


class AllowlistedTufFetcher(FetcherInterface):
    """只从固定 HTTPS 仓库读取 TUF metadata 和 targets。"""

    def __init__(
        self,
        *,
        host_allowlist: tuple[str, ...],
        timeout_seconds: int,
        client: httpx.Client | None = None,
    ) -> None:
        self._host_allowlist = frozenset(host_allowlist)
        self._client = client or httpx.Client(
            timeout=timeout_seconds, follow_redirects=False, trust_env=False
        )

    def _fetch(self, url: str) -> Iterator[bytes]:
        parsed = urlsplit(url)
        hostname = parsed.hostname.rstrip(".").lower() if parsed.hostname else None
        if (
            parsed.scheme.lower() != "https"
            or hostname not in self._host_allowlist
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise tuf_exceptions.DownloadError("TUF URL is outside the repository allowlist.")
        try:
            with self._client.stream("GET", url) as response:
                if 300 <= response.status_code < 400:
                    raise tuf_exceptions.DownloadError("TUF repository redirects are forbidden.")
                if response.status_code >= 400:
                    raise tuf_exceptions.DownloadHTTPError(
                        "TUF repository returned an HTTP error.",
                        response.status_code,
                    )
                yield from response.iter_bytes()
        except tuf_exceptions.DownloadError:
            raise
        except httpx.TimeoutException as exc:
            raise tuf_exceptions.SlowRetrievalError from exc
        except httpx.HTTPError as exc:
            raise tuf_exceptions.DownloadError("TUF repository request failed.") from exc

    def close(self) -> None:
        self._client.close()


class TufArtifactCatalogAdapter(ArtifactCatalogPort):
    """只负责调用 python-tuf，不复制 metadata 状态机。"""

    def __init__(
        self, *, settings: ArtifactReleaseRuntimeSettings, client: httpx.Client | None = None
    ) -> None:
        self._settings = settings
        self._fetcher = AllowlistedTufFetcher(
            host_allowlist=settings.repository_host_allowlist,
            timeout_seconds=settings.request_timeout_seconds,
            client=client,
        )

    async def resolve(self, identity: ArtifactIdentity) -> ArtifactReleaseEnvelope:
        return await asyncio.to_thread(self._resolve_sync, identity)

    async def read_target(self, target_path: str) -> bytes:
        """下载并返回一个经过 TUF metadata 验证的通用 target。"""

        return await asyncio.to_thread(self._read_target_sync, target_path)

    def _resolve_sync(self, identity: ArtifactIdentity) -> ArtifactReleaseEnvelope:
        updater = self._build_updater()
        updater.refresh()
        target_path = self._validate_target_path(self._target_path(identity)).as_posix()
        target_info = updater.get_targetinfo(target_path)
        if target_info is None:
            raise FileNotFoundError("TUF未找到目标制品。")
        hashes = {str(key): str(value) for key, value in target_info.hashes.items()}
        custom = {str(key): str(value) for key, value in target_info.custom.items()}
        target = TufTargetMetadata(
            target_path=target_path,
            length=target_info.length,
            hashes=hashes,
            custom=custom,
        )
        return ArtifactReleaseEnvelope(identity=identity, tuf_target=target)

    def _read_target_sync(self, target_path: str) -> bytes:
        relative_path = self._validate_target_path(target_path)
        updater = self._build_updater()
        updater.refresh()
        target_info = updater.get_targetinfo(relative_path.as_posix())
        if target_info is None:
            raise FileNotFoundError(f"TUF未找到目标制品：{target_path}")
        target_destination = (
            Path(self._settings.staging_root) / "tuf" / "targets" / Path(*relative_path.parts)
        )
        downloaded_path = updater.download_target(
            target_info,
            filepath=str(target_destination),
        )
        return Path(downloaded_path).read_bytes()

    def _build_updater(self) -> Updater:
        return Updater(
            metadata_dir=str(Path(self._settings.staging_root) / "tuf" / "metadata"),
            target_dir=str(Path(self._settings.staging_root) / "tuf" / "targets"),
            metadata_base_url=f"{self._settings.repository_url}/metadata/",
            target_base_url=f"{self._settings.repository_url}/targets/",
            fetcher=self._fetcher,
            bootstrap=Path(self._settings.trusted_root_path).read_bytes(),
        )

    def close(self) -> None:
        self._fetcher.close()

    @staticmethod
    def _validate_target_path(target_path: str) -> PurePosixPath:
        relative_path = PurePosixPath(target_path)
        if (
            relative_path.is_absolute()
            or not relative_path.parts
            or target_path == "."
            or relative_path.as_posix() != target_path
            or any(part in {"", ".", ".."} for part in relative_path.parts)
            or "\\" in target_path
            or ":" in target_path
            or "?" in target_path
            or "#" in target_path
        ):
            raise ValueError("TUF target必须使用规范相对路径。")
        return relative_path

    def _target_path(self, identity: ArtifactIdentity) -> str:
        """将稳定制品身份映射到仓库 target 路径。"""

        return "/".join(
            (
                identity.artifact_name,
                identity.platform.value,
                identity.architecture.value,
                identity.channel.value,
                identity.version,
            )
        )
