"""已审核 App Server schema manifest 目录加载器。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerSchemaManifestEnvelope,
    AppServerSchemaReviewStatus,
)
from src.domain.codex.codex_compatibility_policy import CodexCompatibilityPolicy


class AppServerManifestValidationError(ValueError):
    """schema manifest 与目录中的官方生成物不一致。"""


class AppServerManifestRegistry:
    """加载、校验并向运行时提供只读兼容矩阵。"""

    def __init__(self, protocol_root: str | Path | None = None) -> None:
        bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
        self._protocol_root = (
            Path(protocol_root) if protocol_root else bundle_root / "protocol/codex_app_server"
        )

    def select(self, codex_version: str) -> AppServerSchemaManifestEnvelope | None:
        """版本是精确档案定位；未审核版本保留管理连接，不授予执行能力。"""
        return next(
            (
                manifest
                for manifest in self.load_manifests()
                if manifest.header.codex_version == codex_version
                and manifest.header.review_status == AppServerSchemaReviewStatus.APPROVED
            ),
            None,
        )

    def matches_runtime_schema(self, codex_version: str, directory: Path) -> bool:
        """原始摘要仍校验发布物完整性；运行生成器的 JSON 键顺序不改变协议。"""
        frozen = self._protocol_root / codex_version / "json-schema"

        def documents(root: Path) -> dict[str, object]:
            return {
                path.relative_to(root).as_posix(): json.loads(path.read_bytes())
                for path in root.rglob("*.json")
            }

        return documents(frozen) == documents(directory)

    def load_manifests(self) -> tuple[AppServerSchemaManifestEnvelope, ...]:
        """读取所有版本目录并验证精确版本与 schema digest。"""

        manifests: list[AppServerSchemaManifestEnvelope] = []
        if not self._protocol_root.is_dir():
            raise AppServerManifestValidationError("App Server协议根目录不存在。")
        for manifest_path in sorted(self._protocol_root.glob("*/manifest.json")):
            manifest = AppServerSchemaManifestEnvelope.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            version_directory = manifest_path.parent
            if version_directory.name != manifest.header.codex_version:
                raise AppServerManifestValidationError("App Server manifest版本与目录名不一致。")
            schema_directory = version_directory / "json-schema"
            actual_digest = self.calculate_directory_digest(schema_directory)
            if actual_digest != manifest.detail.json_schema_bundle_sha256:
                raise AppServerManifestValidationError(
                    f"App Server schema digest不匹配：{manifest.header.codex_version}。"
                )
            manifests.append(manifest)
        if not manifests:
            raise AppServerManifestValidationError("没有可加载的App Server manifest。")
        return tuple(manifests)

    def build_policy(
        self,
        *,
        minimum_codex_version: str,
        blocked_codex_versions: list[str],
    ) -> CodexCompatibilityPolicy:
        """使用已验证 manifest 和运行时版本边界构造兼容策略。"""

        return CodexCompatibilityPolicy(
            self.load_manifests(),
            minimum_codex_version=minimum_codex_version,
            blocked_codex_versions=tuple(blocked_codex_versions),
        )

    def calculate_directory_digest(self, directory: str | Path) -> str:
        """按相对 POSIX 路径和原始字节计算稳定 SHA-256。"""

        root = Path(directory)
        if not root.is_dir():
            raise AppServerManifestValidationError("App Server schema目录不存在。")
        files = sorted(
            (path for path in root.rglob("*") if path.is_file()),
            key=lambda path: path.relative_to(root).as_posix(),
        )
        if not files:
            raise AppServerManifestValidationError("App Server schema目录为空。")
        digest = hashlib.sha256()
        for path in files:
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()
