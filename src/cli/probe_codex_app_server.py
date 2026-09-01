"""使用正式 capability probe owner 验证真实 Codex App Server。"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from src.core.codex_contract.app_server_capability_contract import (
    AppServerCapabilityProbeOutcome,
)
from src.core.codex_contract.app_server_jsonrpc_contract import JsonRpcId
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerMethodName,
    AppServerSchemaManifestEnvelope,
)
from src.infrastructure.codex_agent.app_server_capability_probe import (
    AppServerCapabilityProbe,
)
from src.infrastructure.codex_agent.app_server_process_supervisor import (
    AppServerProcessSupervisor,
)

DEFAULT_CODEX_EXECUTABLE: Final = "codex"
DEFAULT_MANIFEST_PATH: Final = Path("protocol/codex_app_server/0.145.0/manifest.json")


class CodexAppServerProbeResult(BaseModel):
    """真实 App Server capability probe 的机器可读投影。"""

    model_config = ConfigDict(extra="forbid")

    codex_version: str
    schema_digest: str | None
    outcome: AppServerCapabilityProbeOutcome
    initialize_passed: bool
    methods: tuple[str, ...]
    notification_methods: tuple[str, ...]
    capabilities: tuple[str, ...]
    model_list_passed: bool
    thread_list_passed: bool
    thread_start_read_passed: bool
    turn_start_passed: bool
    approval_passed: bool
    interrupt_passed: bool
    thread_cleaned: bool
    notification_count: int = Field(ge=0)
    failure: str | None = None


class CodexAppServerCompatibilityProbe:
    """启动一次 App Server，并复用正式 capability probe 实现。"""

    def __init__(
        self,
        *,
        codex_binary: str,
        workspace: Path,
        manifest_path: Path,
        run_turn: bool,
    ) -> None:
        self._workspace = workspace.resolve(strict=True)
        self._manifest = AppServerSchemaManifestEnvelope.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        self._run_turn = run_turn
        self._probe: AppServerCapabilityProbe | None = None
        self._supervisor = AppServerProcessSupervisor(
            codex_binary=codex_binary,
            allowed_versions=[self._manifest.header.codex_version],
            max_line_bytes=4_194_304,
            notification_handler=self._accept_notification,
            request_handler=self._accept_request,
            warning_handler=self._record_warning,
            logger=logging.getLogger("codex_app_server_probe"),
        )

    async def run(self) -> CodexAppServerProbeResult:
        handle = await self._supervisor.start()
        try:
            probe = AppServerCapabilityProbe(
                handle.client,
                workspace=str(self._workspace),
                initialize_passed=isinstance(handle.initialize_result, dict),
            )
            self._probe = probe
            result = await probe.run(confirm_full_capabilities=self._run_turn)
            methods = frozenset(result.methods)
            return CodexAppServerProbeResult(
                codex_version=handle.codex_version,
                schema_digest=(
                    self._manifest.detail.json_schema_bundle_sha256
                    if handle.codex_version == self._manifest.header.codex_version
                    else None
                ),
                outcome=result.outcome,
                initialize_passed=result.initialize_passed,
                methods=tuple(method.value for method in result.methods),
                notification_methods=result.notification_methods,
                capabilities=tuple(item.code.value for item in result.capabilities),
                model_list_passed=AppServerMethodName.MODEL_LIST in methods,
                thread_list_passed=AppServerMethodName.THREAD_LIST in methods,
                thread_start_read_passed={
                    AppServerMethodName.THREAD_START,
                    AppServerMethodName.THREAD_READ,
                }.issubset(methods),
                turn_start_passed=AppServerMethodName.TURN_START in methods,
                approval_passed=result.approval_confirmed,
                interrupt_passed=result.interrupt_confirmed,
                thread_cleaned=result.thread_cleaned,
                notification_count=len(result.notification_methods),
                failure=result.failure.value if result.failure is not None else None,
            )
        finally:
            self._probe = None
            await self._supervisor.stop()

    async def _accept_notification(self, method: str, params: JsonValue) -> None:
        probe = self._probe
        if probe is not None and await probe.accept_notification(method, params):
            return
        logging.getLogger("codex_app_server_probe").warning(
            "App Server在探针窗口外发送notification：%s",
            method,
        )

    async def _accept_request(
        self,
        request_id: JsonRpcId,
        method: str,
        params: JsonValue,
    ) -> None:
        probe = self._probe
        if probe is not None and await probe.accept_request(request_id, method, params):
            return
        await self._supervisor.handle.client.reply_error(
            request_id,
            code=-32601,
            message="Codex Remote probe is not accepting server requests.",
        )

    async def _record_warning(self, warning: str) -> None:
        logging.getLogger("codex_app_server_probe").warning("App Server协议告警：%s", warning)

    def _read_manifest_version(self) -> str:
        """保留历史测试和诊断调用的 manifest 版本读取入口。"""

        return self._manifest.header.codex_version


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="验证真实Codex App Server capability")
    parser.add_argument("--codex-bin", default=DEFAULT_CODEX_EXECUTABLE)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--skip-turn", action="store_true")
    return parser


async def run_probe(arguments: argparse.Namespace) -> CodexAppServerProbeResult:
    result = await CodexAppServerCompatibilityProbe(
        codex_binary=str(arguments.codex_bin),
        workspace=arguments.workspace,
        manifest_path=arguments.manifest,
        run_turn=not arguments.skip_turn,
    ).run()
    gc.collect()
    await asyncio.sleep(0)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING)
    arguments = build_argument_parser().parse_args(argv)
    result = asyncio.run(run_probe(arguments))
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0 if result.outcome is not AppServerCapabilityProbeOutcome.BLOCKED else 1


if __name__ == "__main__":
    raise SystemExit(main())
