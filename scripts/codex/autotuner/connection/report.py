"""只将实测的配置和结论发布为可复核报告。"""

import hashlib
import json
from pathlib import Path


def write_report(output: Path, runs: list[dict]) -> None:
    passing = [run for run in runs if run["evaluation"]["screening_passed"]]
    best = (
        min(passing, key=lambda run: run["evaluation"]["p99_seconds"] or float("inf"))
        if passing
        else None
    )
    summary = {
        "runs": runs,
        "best_screened_configuration": best["candidate"] if best else None,
        "production_promoted": False,
        "remaining": [
            "complete environment fault matrix",
            "packaged Agent",
            "12-hour uninterrupted soak",
        ],
    }
    (output / "report.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rows = [
        "# Connection parameter screening",
        "",
        "| Configuration | Seed | Passed | P95 | P99 | Conclusion |",
        "|---|---:|---|---:|---:|---|",
    ]
    for run in runs:
        e = run["evaluation"]
        rows.append(
            f"| {run['candidate']['name']} | {run['seed']} | {e['screening_passed']} | {e['p95_seconds']} | {e['p99_seconds']} | {e['conclusion']} |"
        )
    rows.extend(
        [
            "",
            "No production promotion: the full environment fault matrix, packaged binary and 12-hour soak remain release gates.",
        ]
    )
    (output / "report.md").write_text("\n".join(rows), encoding="utf-8")


def source_digest(root: Path) -> str:
    """连接验收覆盖前后端和配置，兼容档案的Agent摘要不能代替该闭包。"""
    paths = list((root / "src").rglob("*.py"))
    paths += list((root / "config/runtime").rglob("*.toml"))
    paths += list((root / "scripts/codex/acceptance").rglob("*.py"))
    paths += list((root / "scripts/codex/autotuner/connection").rglob("*.py"))
    paths += list((root.parent / "typescript-web-nuxt/app").rglob("*.ts"))
    paths += list((root.parent / "typescript-web-nuxt/app").rglob("*.vue"))
    paths += [root / "deploy/caddy/Caddyfile.example"]
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.relative_to(root.parent).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()
