"""生产 Nuxt → 真实 HTTP/WSS → Agent/CLI 的六项浏览器冒烟。"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path

import httpx
import psutil

from scripts.codex.verify_compatibility_release import implementation_digest


def verify_browser_history(browser_result: dict, history: dict) -> dict:
    """核对本次四个真实 UI turn 与 CLI 权威历史，不把浏览器自报当完成证明。"""
    expected = browser_result.get("turns", [])
    required = {
        "streaming": "completed",
        "command_approval": "completed",
        "interruption": "interrupted",
        "after_reconnect": "completed",
    }
    if len(expected) != len(required) or {turn.get("name") for turn in expected} != set(required):
        raise AssertionError("Browser report lacks the four required isolated turns")
    thread = history.get("thread", {})
    if thread.get("id") != browser_result.get("thread_id"):
        raise AssertionError("CLI history thread identity differs from browser")
    turns = thread.get("turns", [])
    ids = [turn["id"] for turn in turns]
    if len(ids) != len(set(ids)) or set(ids) != {turn["turn_id"] for turn in expected}:
        raise AssertionError("CLI history contains missing, duplicate or unexpected turns")
    for turn in expected:
        actual = next(item for item in turns if item["id"] == turn["turn_id"])
        if actual["status"] != required[turn["name"]] or turn.get("status") != actual["status"]:
            raise AssertionError(f"CLI/browser terminal status differs for {turn['name']}")
    streaming = next(turn for turn in expected if turn["name"] == "streaming")
    if (
        not streaming.get("delta_count")
        or not streaming.get("visible_streaming_samples")
        or not (
            streaming.get("first_delta_sequence", float("inf"))
            < streaming.get("terminal_sequence", 0)
        )
    ):
        raise AssertionError("Missing nonempty browser delta before terminal")
    approved = next(turn for turn in expected if turn["name"] == "command_approval")
    command_turn = next(turn for turn in turns if turn["id"] == approved["turn_id"])
    command = next(
        (
            item
            for item in command_turn.get("items", [])
            if item.get("type") == "commandExecution"
            and "BROWSER_COMMAND_OK" in item.get("command", "")
        ),
        None,
    )
    if (
        not command
        or command.get("exitCode") != 0
        or "BROWSER_COMMAND_OK" not in (command.get("aggregatedOutput") or "")
    ):
        raise AssertionError("CLI history does not confirm actual command output and exit zero")
    if command["id"] not in {item["item_id"] for item in browser_result.get("commands", [])}:
        raise AssertionError("CLI command identity differs from rendered browser terminal")
    approved_ids = {
        approval["approval_id"]
        for approval in browser_result.get("approvals", [])
        if approval.get("turn_id") == approved["turn_id"] and approval.get("state") == "applied"
    }
    if not approved_ids:
        raise AssertionError("Browser did not confirm applied approval for the command turn")
    reconnect = browser_result.get("reconnection", {})
    if not reconnect.get("draft_preserved") or not (
        reconnect.get("after", {}).get("closed", 0) > reconnect.get("before", {}).get("closed", 0)
        and reconnect.get("after", {}).get("ready", 0) > reconnect.get("before", {}).get("ready", 0)
    ):
        raise AssertionError("Missing native websocket disconnect/reconnect evidence")
    return {
        "thread_id": thread["id"],
        "turns": [{"turn_id": turn["id"], "status": turn["status"]} for turn in turns],
        "command_item_id": command["id"],
        "command_exit_code": command["exitCode"],
        "command_output_marker": "BROWSER_COMMAND_OK",
    }


def _diagnostic_error(exc) -> dict:
    error = getattr(exc, "error", None)
    message = str(exc)
    message = re.sub(r"(?i)(bearer\s+)[^\s]+", r"\1[redacted]", message)
    message = re.sub(r"(?i)([?&](?:ticket|token|access_token)=)[^&\s]+", r"\1[redacted]", message)
    return {
        "type": type(exc).__name__,
        "code": getattr(error, "code", None),
        "message": message[:1000],
    }


async def read_browser_history(client, thread_id: str) -> dict:
    """0.145 官方分页读取；不能用 includeTurns=true 读取分页线程。"""
    async with asyncio.timeout(30):
        metadata = await client.request(
            "thread/read", {"threadId": thread_id, "includeTurns": False}, timeout_seconds=15
        )
        turns = []
        cursor = None
        seen = set()
        while True:
            params = {
                "threadId": thread_id,
                "itemsView": "full",
                "sortDirection": "asc",
                "limit": 100,
            }
            if cursor is not None:
                params["cursor"] = cursor
            page = await client.request("thread/turns/list", params, timeout_seconds=15)
            turns.extend(page["data"])
            cursor = page.get("nextCursor")
            if cursor is None:
                return {**metadata, "thread": {**metadata["thread"], "turns": turns}}
            if not isinstance(cursor, str) or not cursor or cursor in seen:
                raise AssertionError("Invalid or repeated CLI history cursor")
            seen.add(cursor)


async def _stop_owned_process(process) -> None:
    if process is None or process.returncode is not None:
        return
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        parent.kill()
    except psutil.NoSuchProcess:
        pass
    await asyncio.wait_for(process.wait(), 15)


async def run_browser_task(
    channel,
    *,
    origin: str,
    certificate: Path,
    report,
    acceptance_report: Path,
    timeout_seconds: int = 720,
) -> None:
    root = Path(__file__).resolve().parents[3]
    frontend = root.parent / "typescript-web-nuxt"
    node = shutil.which("node")
    if node is None or not (frontend / ".output/server/index.mjs").is_file():
        raise RuntimeError("Browser acceptance requires Node and the production Nuxt build.")
    if not 120 <= timeout_seconds <= 1800:
        raise ValueError("Browser acceptance timeout must be between 120 and 1800 seconds")
    # Never reuse an unknown browser server or mutate its environment.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 3329))
    output = acceptance_report.with_name(acceptance_report.stem + "-browser.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    report.update(
        cli_version=channel._supervisor.handle.codex_version,
        implementation_digest=implementation_digest(),
        environment="Production Nuxt browser, isolated control plane, real Agent/CLI; not production proxy/database/MSI",
        browser_report=str(output),
        browser_timeout_seconds=timeout_seconds,
    )
    environment = {
        **os.environ,
        "NODE_EXTRA_CA_CERTS": str(certificate),
        "HOST": "127.0.0.1",
        "PORT": "3329",
        "NUXT_API_BASE_URL": origin,
        "NUXT_PUBLIC_API_BASE_URL": "/api",
        "NUXT_PUBLIC_CODEX_WS_BASE_URL": origin,
        "NUXT_PUBLIC_CODEX_FEATURE_ENABLED": "true",
        "CODEX_ACCEPTANCE_ORIGIN": "http://127.0.0.1:3329",
        "CODEX_ACCEPTANCE_HOST_ID": str(channel._settings.agent.host_id),
        "CODEX_ACCEPTANCE_OUTPUT": str(output),
        "CODEX_ACCEPTANCE_TIMEOUT_SECONDS": str(timeout_seconds),
    }
    log_path = output.with_name(output.stem + "-server.log")
    browser_result = {}
    browser_process = None
    frontend_process = None
    primary_failure = False
    original_result_sender = channel._send_current_result
    report["agent_command_diagnostics"] = []

    async def observe_result(result, command):
        # Observe metadata only, and forward the unchanged real result through its original path.
        detail = {
            "command_id": str(result.command_id),
            "operation_id": str(result.operation_id),
            "command_type": command.command_type,
            "outcome": result.outcome,
            "error_code": result.error_code,
        }
        if command.command_type == "workspace.settings" and result.error_message:
            detail["error"] = _diagnostic_error(RuntimeError(result.error_message))
        report["agent_command_diagnostics"].append(detail)
        await original_result_sender(result, command)

    channel._send_current_result = observe_result
    with log_path.open("wb") as log:
        try:
            frontend_process = await asyncio.create_subprocess_exec(
                node,
                ".output/server/index.mjs",
                cwd=frontend,
                env=environment,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            async with httpx.AsyncClient(trust_env=False, timeout=2) as http:
                async with asyncio.timeout(45):
                    while True:
                        if frontend_process.returncode is not None:
                            raise RuntimeError("Production browser server exited; inspect its log.")
                        try:
                            response = await http.get("http://127.0.0.1:3329/login")
                            if response.status_code == 200:
                                break
                        except httpx.RequestError:
                            pass
                        await asyncio.sleep(0.5)
            browser_process = await asyncio.create_subprocess_exec(
                node,
                "scripts/acceptance/codex-browser-task.cjs",
                cwd=frontend,
                env=environment,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            # Browser deadline includes all phases; outer grace is only for report/Chromium cleanup.
            async with asyncio.timeout(timeout_seconds + 30):
                exit_code = await browser_process.wait()
            browser_result = json.loads(output.read_text(encoding="utf-8"))
            report["browser"] = browser_result
            if exit_code != 0 or not browser_result.get("passed"):
                raise RuntimeError(
                    f"Browser task failed at {browser_result.get('stage')}: {browser_result.get('error')}"
                )
            client = channel._supervisor.handle.client
            history = await read_browser_history(client, browser_result["thread_id"])
            report["authoritative_history"] = verify_browser_history(browser_result, history)
            report["scenarios"].append(
                {
                    "name": "six real browser smoke checks and independent CLI authoritative history agree",
                    "passed": True,
                }
            )
        except BaseException as exc:
            primary_failure = True
            report["browser_failure"] = _diagnostic_error(exc)
            raise
        finally:
            channel._send_current_result = original_result_sender
            report["agent_journal_summary"] = [
                {
                    "command_id": record.identity.command_id,
                    "operation_id": record.identity.operation_id,
                    "command_type": record.identity.command_type,
                    "state": record.state.value,
                    "outcome_code": record.result_summary.outcome_code
                    if record.result_summary
                    else None,
                }
                for record in channel._journal.list_recovery_records()
            ]
            cleanup_errors = []
            for process in (browser_process, frontend_process):
                try:
                    await _stop_owned_process(process)
                except Exception as exc:
                    cleanup_errors.append(f"owned process cleanup: {type(exc).__name__}")
            # Read only this run's persisted identity; never delete an unrelated local thread.
            if not browser_result and output.is_file():
                browser_result = json.loads(output.read_text(encoding="utf-8"))
                report["browser"] = browser_result
            thread_id = browser_result.get("thread_id")
            if thread_id:
                client = channel._supervisor.handle.client
                try:
                    history = await read_browser_history(client, thread_id)
                    active = [
                        turn["id"]
                        for turn in history["thread"]["turns"]
                        if turn.get("status") == "inProgress"
                    ]
                except Exception as exc:
                    report["cleanup_history_diagnostic"] = _diagnostic_error(exc)
                    active = [
                        turn["turn_id"]
                        for turn in browser_result.get("turns", [])
                        if not turn.get("status")
                    ]
                try:
                    for turn_id in active:
                        await client.request(
                            "turn/interrupt",
                            {"threadId": thread_id, "turnId": turn_id},
                            timeout_seconds=15,
                        )
                    await client.request(
                        "thread/delete", {"threadId": thread_id}, timeout_seconds=20
                    )
                    workspace = channel._project_execution.read_workspace("acceptance")
                    for archived in (False, True):
                        listed = await client.request(
                            "thread/list",
                            {
                                "cwd": str(workspace.root),
                                "archived": archived,
                                "limit": 100,
                                "sourceKinds": ["appServer"],
                            },
                            timeout_seconds=15,
                        )
                        if listed.get("nextCursor") or any(
                            item["id"] == thread_id for item in listed["data"]
                        ):
                            raise AssertionError(
                                "Deleted acceptance thread still present or listing incomplete"
                            )
                    channel._execution_root_store.delete(thread_id)
                    report["browser_thread_cleaned"] = True
                    report["cleanup_readback"] = (
                        "thread/delete acknowledged; isolated cwd absent from active and archived thread/list"
                    )
                except Exception as exc:
                    report["cleanup_thread_diagnostic"] = _diagnostic_error(exc)
                    cleanup_errors.append(f"isolated thread cleanup: {type(exc).__name__}")
            if cleanup_errors:
                report["browser_cleanup_errors"] = cleanup_errors
                if not primary_failure:
                    raise RuntimeError("Browser acceptance resource cleanup failed")
