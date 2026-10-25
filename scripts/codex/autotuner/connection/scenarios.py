"""复用产品组合根、真实TLS CONNECT代理及真实Windows App Server。"""

import asyncio
import random
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psutil

from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.domain.codex.agent_command_policy import calculate_agent_request_digest


async def run_scenarios(channel, *, runtime, run_task, proxy, boundary, report, candidate):
    if proxy is None:
        raise ValueError("Connection scenarios require --proxy=http/https/system")
    report["candidate"] = candidate
    report["effective_agent_parameters"] = channel._settings.agent.model_dump(mode="json")
    report["effective_server_parameters"] = runtime.settings.model_dump(mode="json")
    report["scope"] = (
        "source Agent, real CLI, TLS/WSS, isolated SQLite/local bus; no production claim"
    )
    report["agent_binary_sha256"] = None
    report["agent_binary_reason"] = "source execution, not a packaged release"
    report["peak_rss_bytes"] = 0
    report["execution_misstops"] = 0
    report["recovery_seconds"] = []
    report["sampling_gaps"] = []
    first_instance = channel._supervisor.handle.instance_id
    process = psutil.Process()
    last_sample = time.monotonic()

    async def sample():
        nonlocal last_sample
        while True:
            now = time.monotonic()
            if now - last_sample > 5:
                report["sampling_gaps"].append(now - last_sample)
            last_sample = now
            tree = [process, *process.children(recursive=True)]
            rss = sum(item.memory_info().rss for item in tree if item.is_running())
            report["peak_rss_bytes"] = max(report["peak_rss_bytes"], rss)
            await asyncio.sleep(1)

    async def query():
        params = {"workspace_key": "acceptance", "limit": 1}
        command = CodexAgentCommand(
            command_id=uuid4(),
            operation_id=uuid4(),
            host_id=channel._settings.agent.host_id,
            command_type="thread.list",
            params=params,
            request_digest=calculate_agent_request_digest("thread.list", params),
            deadline=datetime.now(UTC) + timedelta(seconds=25),
            execution_generation=channel._execution.generation,
        )
        result = await runtime.actor_registry.get(command.host_id).dispatch_and_wait_result(
            command, ack_timeout_seconds=5, result_timeout_seconds=25
        )
        if result.outcome != "completed":
            raise AssertionError(f"Query not completed: {result.error_code}")

    async def recover():
        started = time.monotonic()
        async with asyncio.timeout(65):
            while True:
                if run_task.done():
                    await run_task
                    raise AssertionError("Agent exited")
                if channel._connection_ready:
                    try:
                        await query()
                        break
                    except (ConnectionError, TimeoutError) as exc:
                        report.setdefault("query_retries", []).append(
                            {"reason": type(exc).__name__, "at_seconds": time.monotonic() - started}
                        )
                await asyncio.sleep(0.2)
        elapsed = time.monotonic() - started
        report["recovery_seconds"].append(elapsed)
        same = channel._supervisor.handle.instance_id == first_instance
        if not same:
            report["execution_misstops"] += 1
        return elapsed, same

    sampler = asyncio.create_task(sample())
    try:
        # A real ping/application response delay, not an event timestamp adjustment.
        outages = [(None, 5), ("upstream", 10), ("downstream", 20), (None, 20)]
        if candidate.get("scenario_set") == "transport":
            outages = []
        random.Random(candidate.get("seed", 17)).shuffle(outages)
        report["reconnect_jitter_source"] = "OS entropy; scenario order seeded"
        for direction, seconds in outages:
            before_response = channel._execution.last_response_at
            async with asyncio.timeout(20):
                while channel._execution.last_response_at == before_response:
                    await asyncio.sleep(0.1)
            if direction is None and seconds == 20:
                await asyncio.sleep(14)  # Outage immediately before the next renewal.
            proxy.pause(direction)
            try:
                await asyncio.sleep(seconds)
            finally:
                proxy.resume()
            elapsed, same = await recover()
            report["scenarios"].append(
                {
                    "name": f"blackhole-{direction or 'both'}-{seconds}s",
                    "passed": same and elapsed <= 20,
                    "recovery_seconds": elapsed,
                    "instance_preserved": same,
                }
            )
        proxy.interrupt_tunnels()
        await asyncio.sleep(0.2)
        elapsed, same = await recover()
        report["scenarios"].append(
            {
                "name": "tcp-reset",
                "passed": same and elapsed <= 20,
                "recovery_seconds": elapsed,
                "instance_preserved": same,
            }
        )
        boundary.delay_next_ws_send = 1.2
        await query()
        assert channel._supervisor.handle.instance_id == first_instance
        report["scenarios"].append({"name": "real-ASGI-send-1.2s-within-budget", "passed": True})
        boundary.delay_next_ws_send = candidate["server"]["agent_send_timeout_seconds"] + 1
        try:
            await query()
            raise AssertionError("Over-budget server send was not interrupted")
        except (ConnectionError, TimeoutError):
            pass
        async with asyncio.timeout(20):
            while boundary.send_delay_active:
                await asyncio.sleep(0.1)
        elapsed, same = await recover()
        report["scenarios"].append(
            {
                "name": "real-ASGI-send-timeout-preserves-execution",
                "passed": same,
                "recovery_seconds": elapsed,
                "instance_preserved": same,
            }
        )
        proxy.bytes_per_second = 8192
        try:
            await query()
        finally:
            proxy.resume()
        report["scenarios"].append({"name": "real-8KiB-per-second-transport-query", "passed": True})
        # Hold new handshakes outside the existing socket; the task must survive the outage.
        boundary.failures["/internal/codex-agents/connect"] = [520, 522, 429]
        proxy.interrupt_tunnels()
        fault_started = time.monotonic()
        async with asyncio.timeout(90):
            while boundary.failures["/internal/codex-agents/connect"]:
                if run_task.done():
                    await run_task
                await asyncio.sleep(0.1)
        fault_seconds = time.monotonic() - fault_started
        elapsed, same = await recover()
        report["scenarios"].append(
            {
                "name": "gateway-520-522-429",
                "passed": same,
                "fault_seconds": fault_seconds,
                "recovery_seconds": elapsed,
                "instance_preserved": same,
            }
        )
        assert boundary.ticket_reuse == 0
        report["ticket_reuse"] = boundary.ticket_reuse
        report["write_duplicate_validation"] = "separate mutation E2E required"
        report["soak_validation"] = "12-hour run required"
    finally:
        proxy.resume()
        sampler.cancel()
        await asyncio.gather(sampler, return_exceptions=True)
