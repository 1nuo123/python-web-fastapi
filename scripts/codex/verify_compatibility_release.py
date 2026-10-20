"""发布门：档案完整性与逐版本真实 CLI 验收必须共同通过。"""

from __future__ import annotations
import json
import hashlib
from pathlib import Path
from src.infrastructure.codex_agent.app_server_manifest_registry import AppServerManifestRegistry
from src.core.codex_contract.app_server_schema_manifest_contract import AppServerSchemaReviewStatus


def implementation_digest() -> str:
    """Bind evidence to the actual runtime/adapter implementation, not just a version label."""
    root = Path(__file__).resolve().parents[2]
    paths = sorted((root / "src/infrastructure/codex_agent").glob("*.py"))
    paths.extend(sorted((root / "src/core/codex_contract").glob("*.py")))
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_text(encoding="utf-8").replace("\r\n", "\n").encode())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    required = {
        "initialize/initialized",
        "model/list",
        "effective config and requirements",
        "thread/start",
        "turn/start and real terminal events",
        "thread/read and product history adapter",
        "thread/turns/list",
        "thread/resume",
        "turn/steer and turn/interrupt terminal",
    }
    versions = []
    current_implementation_digest = implementation_digest()
    for manifest in AppServerManifestRegistry().load_manifests():
        if manifest.header.review_status != AppServerSchemaReviewStatus.APPROVED:
            continue
        version = manifest.header.codex_version
        report = json.loads(
            (root / "artifacts/codex-connection" / f"cli-{version}.json").read_text(
                encoding="utf-8"
            )
        )
        if not (
            report.get("implementation_digest") == current_implementation_digest
            and report.get("passed")
            and report.get("profile_verified")
            and report.get("version") == version
            and report.get("schema_digest") == manifest.detail.json_schema_bundle_sha256
            and required.issubset(report.get("checks", []))
        ):
            raise RuntimeError(f"CLI {version} lacks matching end-to-end compatibility evidence.")
        for suffix, cases in (
            (
                "",
                (
                    ("file_change", "accept"),
                    ("file_change", "decline"),
                    ("file_change", "cancel"),
                    ("permissions", "decline"),
                ),
            ),
            (
                "-extra",
                (
                    ("permissions", "accept"),
                    ("command", "accept"),
                    ("command", "decline"),
                    ("command", "cancel"),
                ),
            ),
        ):
            approval_report = json.loads(
                (
                    root / "artifacts/codex-connection" / f"approvals{suffix}-{version}.json"
                ).read_text(encoding="utf-8")
            )
            expected = {
                f"real {kind} {decision} HTTP decision, original RPC result and terminal cleanup"
                for kind, decision in cases
            }
            passed = {
                item["name"]
                for item in approval_report.get("scenarios", [])
                if item.get("passed") is True
            }
            if not (
                approval_report.get("passed") is True
                and approval_report.get("cli_version") == version
                and approval_report.get("schema_digest")
                == manifest.detail.json_schema_bundle_sha256
                and approval_report.get("implementation_digest") == current_implementation_digest
                and expected.issubset(passed)
            ):
                raise RuntimeError(
                    f"CLI {version} lacks matching product approval evidence ({suffix or 'core'})."
                )
        versions.append(version)
    if not versions:
        raise RuntimeError("No reviewed CLI profiles.")
    print(json.dumps({"verified_versions": versions}))


if __name__ == "__main__":
    main()
