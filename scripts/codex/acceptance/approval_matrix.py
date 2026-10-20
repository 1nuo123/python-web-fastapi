"""真实 CLI → Agent → 控制面 → HTTP 决定 → 原 RPC 的审批验收。"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4
import httpx

from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from scripts.codex.verify_compatibility_release import implementation_digest


async def run_approval_matrix(
    channel,
    *,
    actor,
    journal,
    origin: str,
    certificate: Path,
    workspace: Path,
    report,
    previous_report=None,
):
    client = channel._supervisor.handle.client
    report["cli_version"] = channel._supervisor.handle.codex_version
    report["implementation_digest"] = implementation_digest()
    report["schema_digest"] = channel._supervisor.handle.schema_digest
    report["environment"] = (
        "Windows; real CLI, product actor, TLS/WSS, approval HTTP API; isolated workspace"
    )
    models = await client.request("model/list", {}, timeout_seconds=20)
    model = next(item["model"] for item in models["data"] if item["isDefault"])
    report["model"] = model
    if previous_report and all(
        previous_report.get(key) == report.get(key)
        for key in ("cli_version", "implementation_digest", "schema_digest", "model")
    ):
        report["scenarios"] = [
            item for item in previous_report.get("scenarios", []) if item.get("passed") is True
        ]
        report["reused_evidence_completed_at"] = previous_report.get("completed_at")
    async with httpx.AsyncClient(
        base_url=origin, verify=str(certificate), trust_env=False, timeout=25
    ) as browser:
        login = await browser.post(
            "/auth/browser/token",
            json={"username": "admin", "password": "admin"},
            headers={"Origin": origin},
        )
        login.raise_for_status()
        browser.headers.update(
            {"Authorization": "Bearer " + login.json()["data"]["access_token"], "Origin": origin}
        )
        cases = (
            ("file_change", "accept"),
            ("file_change", "decline"),
            ("file_change", "cancel"),
            ("permissions", "decline"),
        )
        if "--approval-extra" in sys.argv:
            cases = (
                ("permissions", "accept"),
                ("command", "accept"),
                ("command", "decline"),
                ("command", "cancel"),
            )
        for kind, decision in cases:
            scenario_name = (
                f"real {kind} {decision} HTTP decision, original RPC result and terminal cleanup"
            )
            if any(item["name"] == scenario_name for item in report["scenarios"]):
                continue
            login = await browser.post(
                "/auth/browser/token", json={"username": "admin", "password": "admin"}
            )
            login.raise_for_status()
            browser.headers["Authorization"] = "Bearer " + login.json()["data"]["access_token"]
            filename = f"approval-{decision}.txt"
            effective = await channel._project_execution.resolve("acceptance", client)
            params = {"workspace_key": "acceptance"}
            command = CodexAgentCommand(
                command_id=uuid4(),
                operation_id=uuid4(),
                host_id=channel._settings.agent.host_id,
                command_type="thread.start",
                params=params,
                sandbox_mode=effective.sandbox_mode,
                approval_policy=effective.approval_policy,
                request_digest=calculate_agent_request_digest(
                    "thread.start",
                    params,
                    sandbox_mode=effective.sandbox_mode.value,
                    approval_policy=effective.approval_policy.value,
                ),
                deadline=datetime.now(UTC) + timedelta(seconds=90),
                execution_generation=channel._execution.generation,
            )
            original_request = client.request

            async def with_fixture_feature(method, params, **kwargs):
                # Exercise the real optional CLI tool without editing the host config.
                if method == "thread/start":
                    params = {
                        **params,
                        "model": model,
                        "config": {
                            **params.get("config", {}),
                            "features.request_permissions_tool": kind == "permissions",
                        },
                    }
                return await original_request(method, params, **kwargs)

            client.request = with_fixture_feature
            try:
                result = await actor.dispatch_and_wait_result(
                    command, ack_timeout_seconds=10, result_timeout_seconds=40
                )
            finally:
                client.request = original_request
            assert result.outcome == "completed", result
            thread_id = journal.read(str(command.command_id)).result_summary.upstream_thread_id
            assert channel._execution_root_store.load(thread_id) is not None
            turn_id = None
            try:
                prompt = (
                    f"Use apply_patch to create exactly {workspace / filename} with one line APPROVAL_ACCEPTANCE. Do not use shell, do not read any file, do not use network. Invoke the tool now; the tool runtime handles any permission approval. Do not ask a text question or wait for a chat reply. If the user denies or cancels, do not retry or use other tools; reply DENIED and stop."
                    if kind == "file_change"
                    else f"Use the request_permissions tool to request write permission to this directory only: {workspace}. Do not write any file, run commands, or access network. If denied, do not retry; reply DENIED and stop."
                )
                if kind == "command":
                    prompt = "Invoke the shell tool once with exactly Write-Output 'APPROVAL_ACCEPTANCE' and sandbox_permissions=require_escalated, with a justification asking permission to run this harmless approval probe. Do not read or write files or access network. Do not ask a text question. If rejected or cancelled, do not retry; reply DENIED and stop."
                turn = await client.request(
                    "turn/start",
                    {
                        "threadId": thread_id,
                        "input": [{"type": "text", "text": prompt, "text_elements": []}],
                        "sandboxPolicy": {"type": "readOnly"},
                        "effort": "low",
                        "model": model,
                        "approvalPolicy": "on-request",
                        "approvalsReviewer": "user",
                    },
                    timeout_seconds=30,
                )
                turn_id = turn["turn"]["id"]
                approval = None
                async with asyncio.timeout(150):
                    while approval is None:
                        response = await browser.get("/codex/approvals")
                        if response.status_code == 401:
                            login = await browser.post(
                                "/auth/browser/token",
                                json={"username": "admin", "password": "admin"},
                            )
                            login.raise_for_status()
                            browser.headers["Authorization"] = (
                                "Bearer " + login.json()["data"]["access_token"]
                            )
                            response = await browser.get("/codex/approvals")
                        response.raise_for_status()
                        matches = [
                            item
                            for item in response.json()["data"]["items"]
                            if item["thread_id"] == thread_id and item["state"] == "pending"
                        ]
                        if matches:
                            approval = matches[0]
                            assert approval["approval_kind"] == kind, approval["approval_kind"]
                            break
                        if turn_id not in channel._completed_turns:
                            await asyncio.sleep(0.75)
                            continue
                        history = await client.request(
                            "thread/read",
                            {"threadId": thread_id, "includeTurns": True},
                            timeout_seconds=20,
                        )
                        current = next(
                            (item for item in history["thread"]["turns"] if item["id"] == turn_id),
                            None,
                        )
                        if current and turn_id in channel._completed_turns:
                            raise AssertionError(f"Turn ended without required approval: {current}")
                        await asyncio.sleep(0.75)
                assert decision in approval["display_summary"]["allowed_actions"], approval[
                    "display_summary"
                ]
                if kind == "file_change":
                    changes = approval["display_summary"]["file_changes"]
                    assert changes and all(
                        change["path"].replace("\\", "/").split("/")[-1] == filename
                        for change in changes
                    ), changes
                    assert "APPROVAL_ACCEPTANCE" in str(changes)
                if kind == "command":
                    requested_command = approval["display_summary"]["command"]
                    assert (
                        "Write-Output" in requested_command
                        and "APPROVAL_ACCEPTANCE" in requested_command
                    )
                    assert not any(
                        token in requested_command
                        for token in (";", "|", "&&", "Remove-", "Set-Content", "Invoke-")
                    )
                if kind == "permissions" and decision == "accept":
                    pending = next(
                        item
                        for item in channel._pending_approvals.values()
                        if item.thread_id == thread_id
                    )
                    permissions = pending.requested_permissions
                    assert not permissions.get("network"), permissions
                    filesystem = permissions.get("fileSystem") or {}
                    roots = [*(filesystem.get("read") or []), *(filesystem.get("write") or [])]
                    for entry in filesystem.get("entries", []):
                        assert entry["path"]["type"] == "path" and entry["access"] in {
                            "read",
                            "write",
                        }, entry
                        roots.append(entry["path"]["path"])
                    assert roots and all(
                        Path(root).resolve().is_relative_to(workspace.resolve()) for root in roots
                    ), filesystem
                headers = {"Idempotency-Key": uuid4().hex}
                if approval["risk_level"] == "high" and decision == "accept":
                    step_up = await browser.post(
                        "/auth/step-up",
                        json={"password": "admin", "purpose": "codex.high_risk_approval"},
                    )
                    step_up.raise_for_status()
                    headers["X-Step-Up-Token"] = step_up.json()["data"]["grant_token"]
                response = await browser.post(
                    f"/codex/approvals/{approval['approval_id']}/decision",
                    json={"decision": decision, "approval_version": approval["version"]},
                    headers=headers,
                )
                response.raise_for_status()
                accepted_operation = response.json()["data"]["operation_id"]
                repeated = await browser.post(
                    f"/codex/approvals/{approval['approval_id']}/decision",
                    json={"decision": decision, "approval_version": approval["version"]},
                    headers={"Idempotency-Key": headers["Idempotency-Key"]},
                )
                repeated.raise_for_status()
                assert repeated.json()["data"]["operation_id"] == accepted_operation
                assert repeated.json()["data"]["replayed"] is True
                async with asyncio.timeout(90):
                    while True:
                        if turn_id not in channel._completed_turns:
                            await asyncio.sleep(0.5)
                            continue
                        history = await client.request(
                            "thread/read",
                            {"threadId": thread_id, "includeTurns": True},
                            timeout_seconds=20,
                        )
                        current = next(
                            (item for item in history["thread"]["turns"] if item["id"] == turn_id),
                            None,
                        )
                        if current and turn_id in channel._completed_turns:
                            assert current["status"] in {"completed", "interrupted"}, current
                            break
                        await asyncio.sleep(0.5)
                assert (workspace / filename).exists() == (
                    kind == "file_change" and decision == "accept"
                )
                if kind == "file_change" and decision == "accept":
                    assert (workspace / filename).read_text(
                        encoding="utf-8"
                    ).strip() == "APPROVAL_ACCEPTANCE"
                assert not any(
                    pending.thread_id == thread_id
                    for pending in channel._pending_approvals.values()
                )
                report["scenarios"].append(
                    {
                        "name": scenario_name,
                        "passed": True,
                    }
                )
            finally:
                try:
                    await client.request(
                        "turn/interrupt",
                        {"threadId": thread_id, "turnId": turn_id},
                        timeout_seconds=10,
                    )
                except Exception:
                    pass
                await client.request("thread/delete", {"threadId": thread_id}, timeout_seconds=15)
                channel._execution_root_store.delete(thread_id)
