"""流式性能测试真实 Uvicorn 服务夹具。"""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from time import perf_counter

import uvicorn
from sse_starlette.sse import AppStatus

from src.api.testing.test_app_factory import TestAppFactory

PERFORMANCE_SERVER_START_TIMEOUT_SECONDS = 10.0


@dataclass(slots=True)
class StreamingNetworkServer:
    """可显式关闭的真实网络测试服务。"""

    server: uvicorn.Server
    task: asyncio.Task[None]
    listener: socket.socket
    port: int

    async def close(self) -> None:
        """停止 Uvicorn、等待任务并关闭监听套接字。"""

        self.server.should_exit = True
        try:
            await asyncio.wait_for(
                self.task,
                timeout=PERFORMANCE_SERVER_START_TIMEOUT_SECONDS,
            )
        finally:
            self.listener.close()
            AppStatus.should_exit = False


class StreamingNetworkServerFactory:
    """在随机环回端口启动真实 Uvicorn 流式测试服务。"""

    async def create(self) -> StreamingNetworkServer:
        """创建并等待真实网络服务就绪。"""

        app = TestAppFactory().create()
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = int(listener.getsockname()[1])
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                log_level="warning",
                lifespan="on",
            )
        )
        task = asyncio.create_task(server.serve(sockets=[listener]))
        started_at = perf_counter()
        while not server.started:
            if perf_counter() - started_at > PERFORMANCE_SERVER_START_TIMEOUT_SECONDS:
                server.should_exit = True
                try:
                    await task
                finally:
                    listener.close()
                    AppStatus.should_exit = False
                raise TimeoutError("Uvicorn 性能测试服务启动超时。")
            await asyncio.sleep(0.01)
        return StreamingNetworkServer(
            server=server,
            task=task,
            listener=listener,
            port=port,
        )
