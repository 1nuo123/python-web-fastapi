"""真实 TCP/Uvicorn/websockets + 产品正文reader/单写者的容量搜索，不伪称CLI来源。"""

import argparse
import asyncio
import hashlib
import importlib.metadata
import itertools
import json
import platform
import random
import socket
import statistics
import subprocess
import sys
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
from scripts.codex.autotuner.message_capacity.report import write_report

import psutil
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from src.core.codex_contract.agent_content_contract import AgentContentReadRequest, ContentField
from src.core.codex_contract.connection_session_contract import (
    CodexConnectionFrame,
    CodexConnectionTransportClosed,
)
from src.infrastructure.codex.codex_connection_session import (
    CodexDuplexConnectionSession,
    CodexConnectionSessionPolicy,
)
from src.infrastructure.codex_agent.agent_thread_history_window_cache import (
    AgentThreadHistoryWindowCache,
)
from src.infrastructure.codex_agent.agent_content_reader import AgentContentReader


def frame(identity, kind, payload):
    return CodexConnectionFrame(message_id=str(identity), message_type=kind, payload=payload)


class Transport:
    def __init__(self, ws):
        self.ws = ws

    async def receive_text(self):
        try:
            return await self.ws.receive_text()
        except WebSocketDisconnect as exc:
            closed = CodexConnectionTransportClosed("peer closed")
            closed.close_code = exc.code
            raise closed from exc

    async def send_text(self, payload):
        await self.ws.send_text(payload)

    async def close(self, *, code, reason):
        try:
            await self.ws.close(code=code, reason=reason)
        except RuntimeError:
            pass


class Experiment:
    def __init__(self):
        self.app = FastAPI()
        self.cache = AgentThreadHistoryWindowCache(max_total_bytes=16 * 1024 * 1024)
        self.reader = AgentContentReader(self.cache)
        self.peak_queue = 0
        self.session_errors = []
        self.active_sessions = 0
        self.source = ""
        self.descriptor = None
        self.app.websocket("/echo")(self.echo)
        self.app.websocket("/transfer")(self.transfer)

    def prepare(self, size, seed):
        self.cache.clear()
        rng = random.Random(seed)
        alphabet = ["中文🙂\\\n", 'abc"\t', "段落🌿\r\n"]
        unit = "".join(rng.choice(alphabet) for _ in range(64))
        self.source = unit * (size // len(unit.encode()) + 1)
        self.descriptor = self.cache.retain_content(
            workspace_key="acceptance",
            thread_id="synthetic",
            item_id="body",
            field=ContentField.TEXT,
            text=self.source,
            expected_generation=self.cache.invalidation_generation,
        )
        self.peak_queue = 0

    async def echo(self, ws: WebSocket):
        await ws.accept()
        try:
            while True:
                value = await ws.receive_text()
                await ws.send_text(str(len(value.encode())))
        except WebSocketDisconnect:
            pass

    async def transfer(self, ws: WebSocket):
        await ws.accept()
        chunk_budget = int(ws.query_params["chunk"])
        inflight = int(ws.query_params["inflight"])

        def observe(value):
            self.peak_queue = max(self.peak_queue, value.queued_bytes)

        async def handle(inbound, sender):
            if inbound.message_type == "heartbeat":
                await sender.send(frame(inbound.message_id, "heartbeat", {}))
                return
            request = AgentContentReadRequest(
                workspace_key="acceptance",
                thread_id="synthetic",
                item_id="body",
                field="text",
                content_ref=self.descriptor.content_ref,
                revision=self.descriptor.revision,
                offset=inbound.payload["offset"],
                requested_bytes=inbound.payload["bytes"],
            )

            def result(chunk):
                return frame(
                    inbound.message_id,
                    "command_result",
                    {"detail": {"kind": "command_result", "result": chunk.model_dump(mode="json")}},
                )

            chunk = self.reader.read(
                request,
                max_message_bytes=chunk_budget,
                encoded_size=lambda value: len(result(value).model_dump_json().encode()),
            )
            await sender.send(result(chunk))

        session = CodexDuplexConnectionSession(
            transport=Transport(ws),
            inbound_handler=handle,
            policy=CodexConnectionSessionPolicy(
                outbound_queue_capacity=128,
                max_frame_bytes=chunk_budget,
                outbound_queue_max_bytes=max(2 * chunk_budget, inflight),
                send_enqueue_timeout_seconds=5,
            ),
            queue_observer=observe,
        )
        self.active_sessions += 1
        try:
            await session.run(shutdown_event=asyncio.Event())
        except Exception as exc:
            self.session_errors.append(type(exc).__name__)
        finally:
            self.active_sessions -= 1

    async def measure(self, origin, config, size, seed, profile):
        self.prepare(size, seed)
        expected = self.source.encode()
        offset, received, messages, maximum = 0, bytearray(), 0, 0
        latencies = []
        started = time.perf_counter()
        async with connect(
            origin + f"/transfer?chunk={config['chunk']}&inflight={config['inflight']}",
            compression=None,
            max_size=4 * 1024 * 1024,
            max_queue=2,
        ) as ws:
            while offset < len(expected):
                await ws.send(
                    frame(
                        messages, "command", {"offset": offset, "bytes": config["chunk"]}
                    ).model_dump_json()
                )
                ping_at = time.perf_counter()
                await ws.send(frame("control", "heartbeat", {}).model_dump_json())
                chunk = None
                pong = False
                while chunk is None or not pong:
                    if profile == "slow_receiver":
                        await asyncio.sleep(0.002)
                    encoded = await ws.recv()
                    maximum = max(maximum, len(encoded.encode()))
                    result = json.loads(encoded)
                    if result["message_type"] == "heartbeat":
                        latencies.append((time.perf_counter() - ping_at) * 1000)
                        pong = True
                    else:
                        chunk = result["payload"]["detail"]["result"]
                assert chunk["offset"] == offset and chunk["next_offset"] > offset
                received.extend(chunk["text"].encode())
                offset = chunk["next_offset"]
                messages += 1
        async with asyncio.timeout(5):
            while self.active_sessions:
                await asyncio.sleep(0.001)
        assert not self.session_errors, self.session_errors
        elapsed = time.perf_counter() - started
        assert bytes(received) == expected and maximum <= config["chunk"]
        assert self.cache.total_bytes <= 16 * 1024 * 1024 and self.peak_queue <= config["inflight"]
        return dict(
            config=config,
            seed=seed,
            profile=profile,
            passed=True,
            source="synthetic bounded cache; NOT official CLI range support",
            total_bytes=len(expected),
            seconds=elapsed,
            mib_per_second=len(expected) / 1048576 / elapsed,
            chunks=messages,
            max_message_bytes=maximum,
            control_p50_ms=statistics.median(latencies),
            control_p95_ms=sorted(latencies)[int(len(latencies) * 0.95)],
            control_p99_ms=sorted(latencies)[int(len(latencies) * 0.99)],
            queue_peak_bytes=self.peak_queue,
            cache_bytes=self.cache.total_bytes,
            rss_bytes=psutil.Process().memory_info().rss,
            sha256=hashlib.sha256(received).hexdigest(),
        )


async def server_run(app, limit, operation):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            ws="websockets",
            ws_max_size=limit,
            ws_per_message_deflate=False,
            log_level="error",
            lifespan="off",
        )
    )
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        while not server.started:
            if task.done():
                await task
            await asyncio.sleep(0.01)
        return await operation(f"ws://127.0.0.1:{port}")
    finally:
        server.should_exit = True
        await task
        sock.close()


async def main(args):
    cfg = tomllib.loads(Path(__file__).with_name("candidates.toml").read_text(encoding="utf-8-sig"))
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "report.json").exists():
        raise FileExistsError("使用新的输出目录，避免覆盖历史实验。")
    experiment = Experiment()
    source_hasher = hashlib.sha256()
    for source_file in sorted((ROOT / "src").rglob("*.py")):
        source_hasher.update(source_file.relative_to(ROOT).as_posix().encode())
        source_hasher.update(source_file.read_bytes())
    report = {
        "environment": {
            "python": platform.python_version(),
            "source_tree_sha256": source_hasher.hexdigest(),
            "logical_cpus": psutil.cpu_count(),
            "physical_memory_bytes": psutil.virtual_memory().total,
            "uvicorn": importlib.metadata.version("uvicorn"),
            "websockets": importlib.metadata.version("websockets"),
            "platform": platform.platform(),
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
            "diff_sha256": hashlib.sha256(
                subprocess.check_output(["git", "diff", "--", "src"], cwd=ROOT)
            ).hexdigest(),
        },
        "boundaries": [],
        "runs": [],
        "rejected": [],
    }

    def persist():
        write_report(args.output, report)

    for limit in (65536, 4194304):

        async def boundaries(origin):
            cases = [(limit, False, True), (limit + 1, False, False)]
            if limit == 65536:
                cases += [(98304, True, False)]
            for size, fragmented, success in cases:
                passed = False
                code = None
                try:
                    async with connect(origin + "/echo", compression=None, max_size=4194304) as ws:
                        value = "x" * size
                        await ws.send(
                            [value[i : i + 16384] for i in range(0, size, 16384)]
                            if fragmented
                            else value
                        )
                        passed = int(await ws.recv()) == size
                except ConnectionClosed as exc:
                    code = exc.rcvd.code if exc.rcvd else None
                assert passed == success and (success or code == 1009)
                report["boundaries"].append(
                    dict(
                        limit=limit,
                        size=size,
                        fragmented=fragmented,
                        accepted=passed,
                        close_code=code,
                        passed=True,
                    )
                )
            if limit == 65536:
                async with connect(origin + "/echo", compression=None) as ws:
                    for _ in range(6):
                        await ws.send("x" * 16384)
                        assert await ws.recv() == "16384"
                report["boundaries"].append(
                    dict(limit=limit, independent_messages=6, total_bytes=98304, passed=True)
                )

        await server_run(experiment.app, limit, boundaries)
        persist()

    async def search(origin):
        # Page budget affects reserved memory, not this content-only benchmark.
        # It is recorded but cannot be performance-ranked without real history workload.
        candidates = [
            dict(chunk=c, page=p, inflight=i)
            for c, p, i in itertools.product(
                cfg["chunk_bytes"], cfg["page_bytes"], cfg["inflight_bytes"]
            )
        ]
        for candidate in candidates:
            if (
                candidate["inflight"] < candidate["page"]
                or candidate["inflight"] < 2 * candidate["chunk"]
            ):
                report["rejected"].append(
                    dict(
                        config=candidate,
                        reason="inflight cannot hold one page and connection minimum",
                    )
                )
                continue
            for seed, profile in itertools.product(cfg["seeds"], cfg["profiles"]):
                try:
                    run = await experiment.measure(
                        origin, candidate, cfg["screen_bytes"], seed, profile
                    )
                    run["eligible"] = run["control_p95_ms"] <= cfg["control_p95_limit_ms"]
                except Exception as exc:
                    run = {
                        "config": candidate,
                        "seed": seed,
                        "profile": profile,
                        "passed": False,
                        "eligible": False,
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:512],
                    }
                report["runs"].append(run)
                persist()
            print(json.dumps(candidate), flush=True)
        eligible = [
            c
            for c in candidates
            if any(r["config"] == c for r in report["runs"])
            and all(r["eligible"] for r in report["runs"] if r["config"] == c)
        ]

        def score(c):
            return statistics.mean(r["mib_per_second"] for r in report["runs"] if r["config"] == c)

        if not eligible:
            report["passed"] = False
            report["promotion"] = {
                "approved": False,
                "worth_continuing": False,
                "reason": "No candidate passes correctness/control latency limits",
            }
            persist()
            raise RuntimeError("No eligible capacity candidate")
        best = max(eligible, key=score)
        report["best_content_candidate"] = best
        report["heldout"] = await experiment.measure(
            origin, best, cfg["heldout_bytes"], 97, "slow_receiver"
        )
        report["promotion"] = {
            "approved": False,
            "reason": "Transport/content benchmark only; page and concurrent host/browser memory not measured. Keep conservative defaults until full workload supports all three budgets.",
            "worth_continuing": True,
        }
        report["passed"] = all(r["passed"] for r in report["runs"]) and report["heldout"]["passed"]
        persist()

    await server_run(experiment.app, 4194304, search)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
