"""真实Caddy配置重载后保持同一WebSocket，独立于Docker守护进程。"""

import asyncio
import json
import socket
import subprocess

import httpx
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


async def run_caddy_reload(*, binary, directory, report):
    async def echo(connection):
        async for message in connection:
            await connection.send(message)

    admin_port, proxy_port = free_port(), free_port()
    async with serve(echo, "127.0.0.1", 0) as upstream:
        upstream_port = upstream.sockets[0].getsockname()[1]
        proxy = {
            "handler": "reverse_proxy",
            "upstreams": [{"dial": f"127.0.0.1:{upstream_port}"}],
            "stream_close_delay": 300_000_000_000,
        }
        configuration = {
            "storage": {"module": "file_system", "root": str(directory / "caddy-storage")},
            "admin": {"listen": f"127.0.0.1:{admin_port}", "config": {"persist": False}},
            "apps": {
                "http": {
                    "servers": {
                        "acceptance": {
                            "listen": [f"127.0.0.1:{proxy_port}"],
                            "routes": [{"handle": [proxy]}],
                        }
                    }
                }
            },
        }
        path = directory / "caddy.json"
        path.write_text(json.dumps(configuration), encoding="utf-8")
        with (directory / "caddy.log").open("wb") as log:
            process = await asyncio.create_subprocess_exec(
                str(binary),
                "run",
                "--config",
                str(path),
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                async with httpx.AsyncClient(trust_env=False) as client:
                    async with asyncio.timeout(15):
                        while True:
                            try:
                                response = await client.get(
                                    f"http://127.0.0.1:{admin_port}/config/"
                                )
                                if response.is_success:
                                    break
                            except httpx.TransportError:
                                pass
                            await asyncio.sleep(0.1)
                    async with connect(
                        f"ws://127.0.0.1:{proxy_port}/events", proxy=None
                    ) as connection:
                        await connection.send("before-reload")
                        assert await connection.recv() == "before-reload"
                        proxy["stream_close_delay"] += 1  # Force a real config unload/replacement.
                        response = await client.post(
                            f"http://127.0.0.1:{admin_port}/load", json=configuration
                        )
                        response.raise_for_status()
                        await asyncio.sleep(0.5)
                        await connection.send("after-reload")
                        assert await asyncio.wait_for(connection.recv(), 5) == "after-reload"
                        report["scenarios"].append(
                            {"name": "Caddy 2.10.2 reload preserves same WebSocket", "passed": True}
                        )
            finally:
                if process.returncode is None:
                    process.terminate()
                await asyncio.wait_for(process.wait(), 10)
