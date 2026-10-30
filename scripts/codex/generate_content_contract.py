"""从真实API路由导出正文OpenAPI契约，并用固定版本官方生成器更新Nuxt类型。"""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from fastapi import FastAPI
from src.api.endpoint_codex_control.route_codex_thread import CodexThreadRouteCatalog


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=ROOT / "artifacts/codex-content/openapi.json"
    )
    parser.add_argument("--generate", action="store_true")
    args = parser.parse_args()
    app = FastAPI()
    app.include_router(CodexThreadRouteCatalog().router)
    schemas = app.openapi()["components"]["schemas"]
    selected = {}
    pending = [
        "CodexContentReadRequest",
        "CodexContentChunk",
        "InlineContentDescriptor",
        "ReadableContentDescriptor",
        "UnavailableContentDescriptor",
    ]

    def references(value):
        if isinstance(value, dict):
            if "$ref" in value:
                pending.append(value["$ref"].rsplit("/", 1)[-1])
            for child in value.values():
                references(child)
        elif isinstance(value, list):
            for child in value:
                references(child)

    while pending:
        name = pending.pop()
        if name not in selected:
            selected[name] = schemas[name]
            references(schemas[name])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "info": {"title": "Codex content contract", "version": "1.0"},
                "paths": {},
                "components": {"schemas": selected},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if args.generate:
        pnpm = shutil.which("pnpm.cmd") or shutil.which("pnpm")
        if pnpm is None:
            raise RuntimeError("pnpm is required")
        frontend = ROOT.parent / "typescript-web-nuxt"
        subprocess.run(
            [
                pnpm,
                "dlx",
                "openapi-typescript@7.13.0",
                str(args.output.resolve()),
                "-o",
                str(frontend / "app/types/generated/codex-content.ts"),
            ],
            cwd=frontend,
            check=True,
        )


if __name__ == "__main__":
    main()
