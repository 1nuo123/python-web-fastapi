"""隔离项目中的真实 CLI 执行矩阵；不读取或修改主机认证和配置。"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.infrastructure.codex_agent.app_server_process_supervisor import AppServerProcessSupervisor
from src.infrastructure.codex_agent.app_server_protocol_adapter import AppServerProtocolAdapter


async def run(binary: str, output: Path) -> None:
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "binary": binary,
        "checks": [],
        "passed": False,
    }
    from scripts.codex.verify_compatibility_release import implementation_digest

    report["implementation_digest"] = implementation_digest()
    completed = asyncio.Event()
    item_started = asyncio.Event()
    adapter = AppServerProtocolAdapter()
    terminal = None
    observed = set()
    failures = []
    approvals = []
    thread_id = None

    async def notification(method, params):
        nonlocal terminal
        observed.add(method)
        if method == "item/started":
            item_started.set()
        adapted = adapter.adapt_notification(method=method, params=params)
        if (
            method in {"turn/started", "turn/completed", "item/started", "item/completed"}
            and adapted.notification is None
        ):
            failures.append(method)
        if method == "turn/completed":
            terminal = params["turn"]
            completed.set()

    async def request(request_id, method, params):
        approvals.append(method)
        # The exercise requests a shell read only. No unknown permission or file write is approved.
        if method == "item/commandExecution/requestApproval" and isinstance(params, dict):
            command = str(params.get("command", ""))
            if "codex-compatibility-probe" in command and not any(
                token in command.lower()
                for token in (
                    "remove-",
                    "del ",
                    "curl",
                    "invoke-",
                    "set-content",
                    "out-file",
                    ";",
                    "&&",
                    "|",
                )
            ):
                await supervisor.handle.client.reply(request_id, {"decision": "accept"})
                return
        await supervisor.handle.client.reply_error(
            request_id, code=-32601, message="Acceptance does not authorize this request."
        )

    async def warning(*args):
        return None

    supervisor = AppServerProcessSupervisor(
        codex_binary=binary,
        allowed_versions=[],
        max_line_bytes=8 * 1024 * 1024,
        allow_experimental_api=True,
        notification_handler=notification,
        request_handler=request,
        warning_handler=warning,
        logger=logging.getLogger("cli-acceptance"),
    )
    with tempfile.TemporaryDirectory(prefix="codex-compatibility-") as directory:
        try:
            handle = await supervisor.start()
            report["version"] = handle.codex_version
            report["schema_digest"] = handle.schema_digest
            report["profile_verified"] = handle.profile is not None
            report["checks"].append("initialize/initialized")
            client = handle.client
            models = await client.request("model/list", {}, timeout_seconds=20)
            assert isinstance(models, dict) and isinstance(models.get("data"), list)
            report["checks"].append("model/list")
            configuration = await client.request(
                "config/read", {"cwd": directory, "includeLayers": False}, timeout_seconds=20
            )
            assert isinstance(configuration, dict) and isinstance(configuration.get("config"), dict)
            requirements = await client.request("configRequirements/read", {}, timeout_seconds=20)
            assert isinstance(requirements, dict)
            report["checks"].append("effective config and requirements")
            thread = await client.request(
                "thread/start",
                {
                    "cwd": directory,
                    "sandbox": "workspace-write",
                    "approvalPolicy": "untrusted",
                    "approvalsReviewer": "user",
                    "experimentalRawEvents": False,
                    "persistExtendedHistory": True,
                },
                timeout_seconds=30,
            )
            thread_id = thread["thread"]["id"]
            report["checks"].append("thread/start")
            await client.request(
                "thread/name/set",
                {"threadId": thread_id, "name": "Codex compatibility acceptance"},
                timeout_seconds=15,
            )
            await client.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [
                        {
                            "type": "text",
                            "text": "This is an isolated compatibility acceptance. Run exactly one PowerShell shell command: Write-Output 'codex-compatibility-probe'. Do not read or modify any file, do not access network. Then reply exactly CODEX_ACCEPTANCE_OK.",
                            "text_elements": [],
                        }
                    ],
                },
                timeout_seconds=30,
            )
            await asyncio.wait_for(completed.wait(), 180)
            assert terminal is not None and terminal.get("status") == "completed", terminal
            assert not failures, failures
            report["checks"].append("turn/start and real terminal events")
            history = await client.request(
                "thread/read", {"threadId": thread_id, "includeTurns": True}, timeout_seconds=30
            )
            adapter.adapt_thread_read_result(history)
            assert "CODEX_ACCEPTANCE_OK" in json.dumps(history), (
                "Missing persisted assistant output"
            )
            report["checks"].append("thread/read and product history adapter")
            pages = await client.request(
                "thread/turns/list", {"threadId": thread_id, "limit": 1}, timeout_seconds=20
            )
            assert isinstance(pages, dict) and pages.get("data"), "Missing turn history page"
            report["checks"].append("thread/turns/list")
            await client.request(
                "thread/resume", {"threadId": thread_id, "cwd": directory}, timeout_seconds=20
            )
            report["checks"].append("thread/resume")
            completed.clear()
            item_started.clear()
            running = await client.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [
                        {
                            "type": "text",
                            "text": "Run exactly Start-Sleep -Seconds 30 in PowerShell. Do not read or write any files. Then reply codex-compatibility-probe.",
                            "text_elements": [],
                        }
                    ],
                },
                timeout_seconds=30,
            )
            turn_id = running["turn"]["id"]
            await asyncio.wait_for(item_started.wait(), 40)
            await asyncio.sleep(0.2)
            await client.request(
                "turn/steer",
                {
                    "threadId": thread_id,
                    "expectedTurnId": turn_id,
                    "input": [
                        {
                            "type": "text",
                            "text": "Continue counting without tools.",
                            "text_elements": [],
                        }
                    ],
                },
                timeout_seconds=20,
            )
            await client.request(
                "turn/interrupt", {"threadId": thread_id, "turnId": turn_id}, timeout_seconds=20
            )
            await asyncio.wait_for(completed.wait(), 30)
            assert terminal["status"] == "interrupted", terminal
            report["checks"].append("turn/steer and turn/interrupt terminal")
            assert handle.profile is not None
            report["passed"] = True
        except BaseException as exc:
            report["terminal_at_failure"] = terminal
            report["error"] = f"{type(exc).__name__}: {str(exc)[:800]}"
        finally:
            if thread_id is not None:
                try:
                    await supervisor.handle.client.request(
                        "thread/delete", {"threadId": thread_id}, timeout_seconds=15
                    )
                    report["checks"].append("thread/delete acceptance-only history")
                except Exception as exc:
                    report["cleanup_error"] = type(exc).__name__
                    report["passed"] = False
            await supervisor.stop()
            report["notifications"] = sorted(observed)
            report["approval_methods"] = approvals
            report["completed_at"] = datetime.now(UTC).isoformat()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex-bin", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(run(args.codex_bin, args.output))
