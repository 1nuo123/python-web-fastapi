"""Phase 2 测试使用的可控 stdio 假 App Server。"""

from __future__ import annotations

import json
import sys


class FakeCodexAppServer:
    """提供测试进程输出能力，避免在脚本模块定义顶层函数。"""

    @staticmethod
    def send(payload: dict[str, object]) -> None:
        """发送单行 JSON-RPC 消息。"""

        sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
        sys.stdout.flush()


if "--version" in sys.argv:
    sys.stdout.write("codex-cli 0.145.0\n")
    sys.stdout.flush()
    raise SystemExit(0)


for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    request_id = message.get("id")
    if method == "initialize":
        FakeCodexAppServer.send(
            {
                "id": request_id,
                "result": {
                    "userAgent": "fake/0.145.0",
                    "codexHome": "C:\\fake",
                    "platformFamily": "windows",
                    "platformOs": "windows",
                },
            }
        )
    elif method == "thread/list":
        FakeCodexAppServer.send({"method": "warning", "params": {"message": "interleaved"}})
        FakeCodexAppServer.send(
            {"id": request_id, "result": {"data": [], "nextCursor": None, "backwardsCursor": None}}
        )
    elif method == "turn/start":
        FakeCodexAppServer.send({"method": "turn/started", "params": {"turn": {"id": "turn-1"}}})
        FakeCodexAppServer.send({"id": request_id, "result": {"turn": {"id": "turn-1"}}})
        FakeCodexAppServer.send({"method": "turn/completed", "params": {"turn": {"id": "turn-1"}}})
    elif method == "thread/read":
        size = int(message.get("params", {}).get("testResponseSize", 8192))
        FakeCodexAppServer.send({"id": request_id, "result": {"payload": "x" * size}})
    elif method == "model/list":
        FakeCodexAppServer.send({"id": request_id, "result": {"data": []}})
