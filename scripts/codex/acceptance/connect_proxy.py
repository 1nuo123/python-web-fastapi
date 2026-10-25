"""本机真实 CONNECT 代理：仅转发隔离验收服务，不解密目标 TLS。"""

from __future__ import annotations

import asyncio
import ssl
from pathlib import Path


class AcceptanceConnectProxy:
    def __init__(self, target_port: int) -> None:
        self.target_port = target_port
        self.server = None
        self.tasks = set()
        self.writers = set()
        self.upstream_peers = set()
        self.connections = 0
        self._flow = {"upstream": asyncio.Event(), "downstream": asyncio.Event()}
        for gate in self._flow.values():
            gate.set()
        self.bytes_per_second: int | None = None

    async def start(self, *, certificate: Path | None = None, key: Path | None = None) -> str:
        context = None
        if certificate is not None:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certificate, key)
        self.server = await asyncio.start_server(self._accept, "127.0.0.1", 0, ssl=context)
        port = self.server.sockets[0].getsockname()[1]
        return f"{'https' if context else 'http'}://127.0.0.1:{port}"

    async def _accept(self, reader, writer):
        task = asyncio.current_task()
        self.tasks.add(task)
        self.writers.add(writer)
        upstream = None
        pumps = []
        try:
            async with asyncio.timeout(10):
                request = await reader.readuntil(b"\r\n\r\n")
            expected = f"CONNECT 127.0.0.1:{self.target_port} HTTP/1.1".encode()
            if request.split(b"\r\n", 1)[0] != expected:
                writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return
            upstream_reader, upstream = await asyncio.open_connection("127.0.0.1", self.target_port)
            self.upstream_peers.add(upstream.get_extra_info("sockname"))
            self.writers.add(upstream)
            self.connections += 1
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()

            async def pump(source, destination, direction):
                while chunk := await source.read(16384):
                    await self._flow[direction].wait()
                    if self.bytes_per_second:
                        await asyncio.sleep(len(chunk) / self.bytes_per_second)
                    destination.write(chunk)
                    await destination.drain()

            pumps = [
                asyncio.create_task(pump(reader, upstream, "upstream")),
                asyncio.create_task(pump(upstream_reader, writer, "downstream")),
            ]
            await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
        except (ConnectionError, OSError, TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            for pump_task in pumps:
                pump_task.cancel()
            await asyncio.gather(*pumps, return_exceptions=True)
            for stream in (writer, upstream):
                if stream is not None:
                    self.writers.discard(stream)
                    stream.close()
                    try:
                        await stream.wait_closed()
                    except (ConnectionError, OSError):
                        pass
            self.tasks.discard(task)

    def pause(self, direction: str | None = None) -> None:
        for name, gate in self._flow.items():
            if direction is None or direction == name:
                gate.clear()

    def resume(self) -> None:
        for gate in self._flow.values():
            gate.set()
        self.bytes_per_second = None

    def interrupt_tunnels(self) -> None:
        for writer in tuple(self.writers):
            writer.transport.abort()

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        self.interrupt_tunnels()
        for task in tuple(self.tasks):
            task.cancel()
        await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
