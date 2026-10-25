"""内部 MSI 构建来源与最终解包二进制验收证据的唯一生成入口。"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def source_files(version: str) -> dict:
    paths = {ROOT / "pyproject.toml", ROOT / "uv.lock"}
    for folder in ("src", "packaging", "protocol", "scripts/codex"):
        paths.update(
            path
            for path in (ROOT / folder).rglob("*")
            if path.is_file()
            and path.suffix in {".py", ".toml", ".json", ".ps1", ".spec", ".wxs"}
            and "__pycache__" not in path.parts
        )
    paths.add(ROOT / f".build/windows-agent-version-info-{version}.txt")
    return {path.relative_to(ROOT).as_posix(): sha(path) for path in sorted(paths)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--public-origin", required=True)
    parser.add_argument("--payload-root", type=Path, required=True)
    parser.add_argument("--acceptance-report", type=Path)
    parser.add_argument("--extracted-root", type=Path)
    args = parser.parse_args()
    release = args.release_root
    evidence_file = release / "build-evidence.json"
    map_file = release / "source-files.sha256.json"
    if args.acceptance_report:
        evidence = json.loads(evidence_file.read_text(encoding="utf-8"))
        result = json.loads(args.acceptance_report.read_text(encoding="utf-8"))
        if (
            not result.get("passed")
            or not result.get("scenarios")
            or not all(item["passed"] for item in result["scenarios"])
        ):
            raise ValueError("Only a passed real binary acceptance report can be attached")
        if result["executable_sha256"] != evidence["executable_sha256"]:
            raise ValueError("Acceptance binary differs from built binary")
        if sha(release / "CodexRemoteAgent.msi") != evidence["msi_sha256"]:
            raise ValueError("Installer changed after build")
        if args.extracted_root is None:
            raise ValueError("Extracted MSI payload is required")
        matches = []
        for name, digest in evidence["payload_sha256"].items():
            candidates = list(args.extracted_root.rglob(name))
            if len(candidates) != 1 or sha(candidates[0]) != digest:
                raise ValueError(f"MSI payload mismatch: {name}")
            matches.append(name)
        evidence["msi_payload_verification"] = {"passed": True, "matched_files": matches}
        evidence["extracted_binary_e2e"] = result
        evidence["verified_at"] = datetime.now(UTC).isoformat()
    else:
        if evidence_file.exists() or map_file.exists():
            raise FileExistsError("Build provenance is immutable; do not replace an existing build")
        write(
            map_file,
            {"algorithm": "SHA256 of exact file bytes", "files": source_files(args.version)},
        )
        payload = {p.name: sha(p) for p in args.payload_root.iterdir() if p.is_file()}
        evidence = {
            "version": args.version,
            "built_at": datetime.now(UTC).isoformat(),
            "distribution_mode": "internal",
            "automatic_updates_enabled": False,
            "public_origin": args.public_origin,
            "source_revision": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "source_dirty": bool(
                subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT)
            ),
            "source_hashes_file": map_file.name,
            "source_hashes_sha256": sha(map_file),
            "msi_sha256": sha(release / "CodexRemoteAgent.msi"),
            "msi_length_bytes": (release / "CodexRemoteAgent.msi").stat().st_size,
            "executable_sha256": payload["codex-remote-agent.exe"],
            "payload_sha256": payload,
            "extracted_binary_e2e": {"status": "not_run"},
            "soak": {"status": "not_run", "previous_release_evidence_reused": False},
            "limits": [
                "No installation over the user's existing Agent",
                "No deployed public network verification",
                "Unsigned internal release",
            ],
            "publishing": {"performed": False, "owner": "user"},
        }
    write(evidence_file, evidence)
    write(
        release / "SHA256SUMS.json",
        {
            name: sha(release / name)
            for name in (
                "CodexRemoteAgent.msi",
                "internal-release.json",
                "build-evidence.json",
                "source-files.sha256.json",
            )
        },
    )


if __name__ == "__main__":
    main()
