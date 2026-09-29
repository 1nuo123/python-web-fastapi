"""Fail when a production env file contains a concrete secret value.

Production credentials are injected by the deployment environment.  The
repository may contain an ``.env.production.example`` schema, but a local
``.env.production.local`` file must either be absent or contain only explicit
placeholders.  This check is intentionally small and deterministic so it can
run in CI without a secret-scanning service.
"""

from __future__ import annotations

import re
from pathlib import Path

_SECRET_NAME = re.compile(
    r"(?:PASSWORD|SECRET|TOKEN|PRIVATE_KEY|API_KEY|ACCESS_KEY|DATABASE_URL|RABBITMQ_URL|REDIS_URL)",
    re.IGNORECASE,
)
_PLACEHOLDER = re.compile(
    r"^(?:$|change[-_]me|replace[_-].*|<[^>]+>|\$\{[^}]+\}|YOUR_[A-Z0-9_]+)$",
    re.IGNORECASE,
)


def _violations(path: Path) -> list[str]:
    violations: list[str] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = (part.strip() for part in line.split("=", 1))
        if _SECRET_NAME.search(name) and value and not _PLACEHOLDER.fullmatch(value.strip("\"'")):
            violations.append(f"{path}:{line_number}:{name}")
    return violations


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    violations: list[str] = []
    for relative_path in (
        Path(".env.production.local"),
        Path("../typescript-web-nuxt/.env.production.local"),
    ):
        path = (root / relative_path).resolve()
        if path.is_file():
            violations.extend(_violations(path))
    if violations:
        print("Production env files contain concrete secret values:")
        print("\n".join(violations))
        return 1
    print("Production secret boundary check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
