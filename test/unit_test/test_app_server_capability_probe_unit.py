"""App Server capability probe behavior tests."""

from __future__ import annotations

import asyncio

from pydantic import JsonValue

from src.core.codex_contract.app_server_capability_contract import (
    AppServerCapabilityProbeFailure,
    AppServerCapabilityProbeOutcome,
)
from src.core.codex_contract.app_server_jsonrpc_contract import JsonRpcId
from src.infrastructure.codex_agent.app_server_capability_probe import (
    APPROVAL_PROMPT,
    AppServerCapabilityProbe,
)


class FakeProbeClient:
    """Drive the real probe without a second execution path."""

    def __init__(self, *, fail_thread_start: bool = False) -> None:
        self.probe: AppServerCapabilityProbe | None = None
        self.fail_thread_start = fail_thread_start
        self.replies: list[tuple[JsonRpcId, JsonValue]] = []

    async def request(
        self,
        method: str,
        params: JsonValue,
        *,
        timeout_seconds: float,
        operation_id: str | None = None,
    ) -> JsonValue:
        del timeout_seconds, operation_id
        if method in {"model/list", "thread/list"}:
            return {"data": []}
        if method == "thread/start":
            if self.fail_thread_start:
                raise ValueError("unsupported")
            return {"thread": {"id": "thread-1"}}
        if method == "thread/read":
            return {"thread": {"id": "thread-1", "turns": []}}
        if method == "turn/start":
            assert isinstance(params, dict)
            prompt = params["input"][0]["text"]
            turn_id = "approval-turn" if prompt == APPROVAL_PROMPT else f"turn-{id(prompt)}"
            assert self.probe is not None
            if prompt == APPROVAL_PROMPT:
                asyncio.create_task(
                    self.probe.accept_request(
                        91,
                        "item/commandExecution/requestApproval",
                        {
                            "threadId": "thread-1",
                            "turnId": turn_id,
                            "itemId": "item-1",
                        },
                    )
                )
            else:
                asyncio.create_task(
                    self.probe.accept_notification(
                        "turn/completed",
                        {"turn": {"id": turn_id}},
                    )
                )
            return {"turn": {"id": turn_id}}
        if method in {"turn/interrupt", "thread/delete"}:
            return {}
        raise AssertionError(method)

    async def reply(self, request_id: JsonRpcId, result: JsonValue) -> None:
        self.replies.append((request_id, result))

    async def reply_error(self, request_id: JsonRpcId, *, code: int, message: str) -> None:
        self.replies.append((request_id, {"code": code, "message": message}))


async def _build_probe(*, fail_thread_start: bool = False) -> AppServerCapabilityProbe:
    client = FakeProbeClient(fail_thread_start=fail_thread_start)
    probe = AppServerCapabilityProbe(
        client,
        workspace="C:\\isolated",
        initialize_passed=True,
    )
    client.probe = probe
    return probe


def test_probe_confirms_full_core_behavior() -> None:
    async def scenario() -> None:
        probe = await _build_probe()
        outcome = await probe.run()
        assert outcome.outcome is AppServerCapabilityProbeOutcome.COMPATIBLE
        assert outcome.approval_confirmed is True
        assert outcome.interrupt_confirmed is True
        assert outcome.failure is None

    asyncio.run(scenario())


def test_probe_downgrades_when_mutation_is_not_confirmed() -> None:
    async def scenario() -> None:
        probe = await _build_probe(fail_thread_start=True)
        outcome = await probe.run()
        assert outcome.outcome is AppServerCapabilityProbeOutcome.READ_ONLY
        assert outcome.mutation_confirmed is False
        assert outcome.failure is AppServerCapabilityProbeFailure.MUTATION_METHOD_FAILED

    asyncio.run(scenario())
