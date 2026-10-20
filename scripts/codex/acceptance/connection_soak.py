"""现有隔离连接验收的长时模式；真实命令、重连和有界资源采样。"""

from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psutil

from scripts.codex.verify_compatibility_release import implementation_digest
from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.domain.codex.agent_command_policy import calculate_agent_request_digest


async def run_connection_soak(channel, *, runtime, run_task, report, output, seconds):
    """不生成模型任务，不更改电源策略；控制面命令贯穿真实 Agent/CLI。"""
    if not 60 <= seconds <= 86400:
        raise ValueError("Soak duration must be between 60 and 86400 seconds")
    started = time.monotonic()
    last_sample = started
    next_command = started
    next_disconnect = started + 600
    recoveries = []
    commands = 0
    command_failures = 0
    sampled_seconds = 0.0
    unavailable_seconds = 0.0
    injected_seconds = 0.0
    observation_gaps = []
    peak_tree_rss = 0
    first = channel._supervisor.handle
    host_id = channel._settings.agent.host_id
    report.update(
        {
            "status": "running",
            "passed": False,
            "started_at": datetime.now(UTC).isoformat(),
            "requested_seconds": seconds,
            "implementation_digest": implementation_digest(),
            "cli_version": first.codex_version,
            "pid": psutil.Process().pid,
            "scope": "isolated local TLS/WSS control plane and real CLI; read-only commands; not production availability",
        }
    )

    def persist():
        elapsed = time.monotonic() - started
        ordered = sorted(recoveries)
        report["soak"] = {
            "elapsed_seconds": elapsed,
            "sampled_seconds": sampled_seconds,
            "unavailable_seconds_excluding_injections": unavailable_seconds,
            "injected_recovery_seconds": injected_seconds,
            "commands": commands,
            "command_failures": command_failures,
            "reconnections": len(recoveries),
            "recovery_p95_seconds": ordered[math.ceil(len(ordered) * 0.95) - 1]
            if ordered
            else None,
            "recovery_p99_seconds": ordered[math.ceil(len(ordered) * 0.99) - 1]
            if ordered
            else None,
            "sampled_availability_excluding_injections": 1 - unavailable_seconds / sampled_seconds
            if sampled_seconds
            else None,
            "total_observed_interruption_seconds": unavailable_seconds + injected_seconds,
            "observation_gaps": observation_gaps,
            "peak_process_tree_rss_bytes": peak_tree_rss,
        }
        temporary = output.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(output)

    persist()
    try:
        while time.monotonic() - started < seconds:
            if run_task.done():
                await run_task
                raise RuntimeError("Agent stopped during soak")
            now = time.monotonic()
            delta = now - last_sample
            last_sample = now
            if delta > 10:
                if len(observation_gaps) < 100:
                    observation_gaps.append({"at_seconds": now - started, "gap_seconds": delta})
            else:
                sampled_seconds += delta
                if not channel._connection_ready:
                    unavailable_seconds += delta
            if now >= next_command and channel._connection_ready:
                params = {"workspace_key": "acceptance", "limit": 1}
                command = CodexAgentCommand(
                    command_id=uuid4(),
                    operation_id=uuid4(),
                    host_id=host_id,
                    command_type="thread.list",
                    params=params,
                    request_digest=calculate_agent_request_digest("thread.list", params),
                    deadline=datetime.now(UTC) + timedelta(seconds=30),
                    execution_generation=channel._execution.generation,
                )
                commands += 1
                command_started = time.monotonic()
                command_succeeded = False
                try:
                    result = await runtime.actor_registry.get(host_id).dispatch_and_wait_result(
                        command, ack_timeout_seconds=10, result_timeout_seconds=20
                    )
                    if result.outcome != "completed":
                        command_failures += 1
                    else:
                        command_succeeded = True
                except (ConnectionError, TimeoutError):
                    command_failures += 1
                command_elapsed = time.monotonic() - command_started
                sampled_seconds += command_elapsed
                if not command_succeeded:
                    unavailable_seconds += command_elapsed
                process = psutil.Process()
                tree = [process, *process.children(recursive=True)]
                rss = 0
                for child in tree:
                    try:
                        rss += child.memory_info().rss
                    except psutil.NoSuchProcess:
                        pass
                peak_tree_rss = max(peak_tree_rss, rss)
                next_command = time.monotonic() + 60
                last_sample = time.monotonic()
                persist()
            if now >= next_disconnect:
                epoch = channel._connection_epoch
                instance = channel._supervisor.handle.instance_id
                lease = await runtime.connection_registry.read(host_id)
                fault_started = time.monotonic()
                lease.close(1012, "acceptance_soak_recovery")
                async with asyncio.timeout(45):
                    while not (channel._connection_ready and channel._connection_epoch != epoch):
                        await asyncio.sleep(0.1)
                duration = time.monotonic() - fault_started
                recoveries.append(duration)
                injected_seconds += duration
                assert channel._supervisor.handle.instance_id == instance
                next_disconnect = time.monotonic() + 600
                last_sample = time.monotonic()
                persist()
            await asyncio.sleep(1)
        persist()
        metrics = report["soak"]
        assert not observation_gaps, (
            "Host sleep or scheduling gaps invalidate continuous observation"
        )
        assert command_failures == 0, metrics
        assert metrics["sampled_availability_excluding_injections"] >= 0.999, metrics
        if recoveries:
            assert (
                metrics["recovery_p95_seconds"] <= 15 and metrics["recovery_p99_seconds"] <= 30
            ), metrics
        report["status"] = "completed"
        report["scenarios"].append(
            {
                "name": f"{seconds} seconds local connection soak with real commands and bounded recovery",
                "passed": True,
            }
        )
    except BaseException:
        report["status"] = "failed"
        raise
    finally:
        persist()
