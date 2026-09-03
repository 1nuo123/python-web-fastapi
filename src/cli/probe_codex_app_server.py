"""执行 Phase 2 真实 Codex App Server 最小链路探针。"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from src.core.codex_contract.app_server_jsonrpc_contract import JsonRpcId
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerSchemaManifestEnvelope,
)
from src.domain.codex.agent_command_policy import read_upstream_identifiers
from src.infrastructure.codex_agent.app_server_process_supervisor import (
    AppServerProcessSupervisor,
)

DEFAULT_CODEX_EXECUTABLE: Final = "codex"
DEFAULT_MANIFEST_PATH: Final = Path("protocol/codex_app_server/0.145.0/manifest.json")
PROBE_PROMPT: Final = (
    "Reply exactly PHASE2_OK. Do not use tools, execute commands, or modify files."
)


class CodexProtocolManifest(BaseModel):
    """探针校验使用的冻结协议清单子集。"""

    model_config = ConfigDict(extra="allow")

    codex_version: str
    json_schema_bundle_sha256: str = Field(min_length=64, max_length=64)


class CodexAppServerProbeResult(BaseModel):
    """真实 initialize/thread/turn 链路验证结果。"""

    model_config = ConfigDict(extra="forbid")

    codex_version: str
    schema_digest: str
    initialize_passed: bool
    model_list_passed: bool
    thread_list_passed: bool
    thread_start_read_passed: bool
    turn_start_passed: bool
    turn_completed: bool
    notification_count: int = Field(ge=0)
    thread_cleaned: bool


class CodexAppServerCompatibilityProbe:
    """用真实 stdio App Server 执行可清理的最小兼容性链路。"""

    def __init__(
        self,
        *,
        codex_binary: str,
        workspace: Path,
        manifest_path: Path,
        run_turn: bool,
    ) -> None:
        self._codex_binary = codex_binary
        self._workspace = workspace.resolve(strict=True)
        self._manifest = AppServerSchemaManifestEnvelope.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        self._run_turn = run_turn
        self._notifications: asyncio.Queue[tuple[str, JsonValue]] = asyncio.Queue()
        self._supervisor = AppServerProcessSupervisor(
            codex_binary=codex_binary,
            allowed_versions=[self._read_manifest_version()],
            max_line_bytes=4_194_304,
            notification_handler=self._record_notification,
            request_handler=self._reject_server_request,
            warning_handler=self._record_warning,
            logger=logging.getLogger("codex_app_server_probe"),
        )

    async def run(self) -> CodexAppServerProbeResult:
        """执行 initialize、model/list、thread/list/start/read、turn/start 与清理。"""

        handle = await self._supervisor.start()
        thread_id: str | None = None
        thread_cleaned = False
        notification_count = 0
        turn_completed = not self._run_turn
        try:
            client = handle.client
            model_result = await client.request("model/list", {}, timeout_seconds=15)
            self._require_mapping(model_result, "model/list")
            list_result = await client.request(
                "thread/list",
                {"cwd": str(self._workspace), "limit": 5},
                timeout_seconds=15,
            )
            self._require_mapping(list_result, "thread/list")
            start_result = await client.request(
                "thread/start",
                {
                    "cwd": str(self._workspace),
                    "sandbox": "read-only",
                    "approvalPolicy": "never",
                    "ephemeral": False,
                },
                timeout_seconds=15,
            )
            thread_id, _ = read_upstream_identifiers(start_result)
            if thread_id is None:
                raise RuntimeError("thread/start响应缺少thread.id。")
            read_result = await client.request(
                "thread/read",
                {"threadId": thread_id, "includeTurns": False},
                timeout_seconds=15,
            )
            self._require_mapping(read_result, "thread/read")
            if self._run_turn:
                turn_result = await client.request(
                    "turn/start",
                    {
                        "threadId": thread_id,
                        "input": [{"type": "text", "text": PROBE_PROMPT, "text_elements": []}],
                    },
                    timeout_seconds=30,
                )
                _, turn_id = read_upstream_identifiers(turn_result)
                if turn_id is None:
                    raise RuntimeError("turn/start响应缺少turn.id。")
                turn_completed, notification_count = await self._wait_for_turn(turn_id)
                if not turn_completed:
                    raise TimeoutError("真实Codex turn未在探针时限内完成。")
            await client.request(
                "thread/delete",
                {"threadId": thread_id},
                timeout_seconds=15,
            )
            thread_cleaned = True
            return CodexAppServerProbeResult(
                codex_version=handle.codex_version,
                schema_digest=self._manifest.detail.json_schema_bundle_sha256,
                initialize_passed=True,
                model_list_passed=True,
                thread_list_passed=True,
                thread_start_read_passed=True,
                turn_start_passed=self._run_turn,
                turn_completed=turn_completed,
                notification_count=notification_count,
                thread_cleaned=thread_cleaned,
            )
        finally:
            if thread_id is not None and not thread_cleaned:
                try:
                    await self._supervisor.handle.client.request(
                        "thread/delete",
                        {"threadId": thread_id},
                        timeout_seconds=10,
                    )
                except (ConnectionError, RuntimeError, TimeoutError):
                    pass
            await self._supervisor.stop()

    async def _wait_for_turn(self, turn_id: str) -> tuple[bool, int]:
        """消费基础事件直到目标 turn/completed。"""

        count = 0
        async with asyncio.timeout(180):
            while True:
                method, params = await self._notifications.get()
                count += 1
                if method != "turn/completed" or not isinstance(params, Mapping):
                    continue
                turn = cast(Mapping[str, object], params).get("turn")
                if (
                    isinstance(turn, Mapping)
                    and cast(Mapping[str, object], turn).get("id") == turn_id
                ):
                    return True, count

    async def _record_notification(self, method: str, params: JsonValue) -> None:
        await self._notifications.put((method, params))

    async def _reject_server_request(
        self,
        _request_id: JsonRpcId,
        method: str,
        _params: JsonValue,
    ) -> None:
        raise RuntimeError(f"兼容性探针收到非预期App Server请求：{method}")

    async def _record_warning(self, warning: str) -> None:
        logging.getLogger("codex_app_server_probe").warning("App Server协议告警：%s", warning)

    def _read_manifest_version(self) -> str:
        tokens = self._manifest.header.codex_version.split()
        if not tokens:
            raise ValueError("协议manifest缺少Codex版本。")
        return tokens[-1]

    def _require_mapping(self, value: JsonValue, method: str) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise RuntimeError(f"{method}响应不是对象。")
        return cast(Mapping[str, object], value)


def build_argument_parser() -> argparse.ArgumentParser:
    """构建真实 App Server 探针参数。"""

    parser = argparse.ArgumentParser(description="验证真实Codex App Server Phase 2主链路")
    parser.add_argument("--codex-bin", default=DEFAULT_CODEX_EXECUTABLE)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--skip-turn", action="store_true")
    return parser


async def run_probe(arguments: argparse.Namespace) -> CodexAppServerProbeResult:
    """按 CLI 参数执行兼容性探针。"""

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
    """输出机器可读探针结果。"""

    logging.basicConfig(level=logging.WARNING)
    arguments = build_argument_parser().parse_args(argv)
    result = asyncio.run(run_probe(arguments))
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
