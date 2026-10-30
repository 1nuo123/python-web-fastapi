"""真实产品入口的独立业务限额和新能力关闭后的旧协议回落验收。"""

import asyncio
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from src.cli.run_web_server import WebServerRuntimeProjection


async def run_transport_boundaries(app, channel, browser, *, origin, context, path, report):
    settings = app.state.container.settings_holder.current_settings
    projected = WebServerRuntimeProjection.from_runtime_settings(
        settings
    ).websocket_max_message_bytes
    assert projected == 4194304
    assert settings.runtime.stream.detail.websocket_max_message_bytes == 65536
    websocket_origin = origin.replace("https:", "wss:")

    async def rejected(endpoint, size, **kwargs):
        async with connect(
            websocket_origin + endpoint, ssl=context, proxy=None, compression=None, **kwargs
        ) as ws:
            await ws.send("x" * size)
            try:
                async with asyncio.timeout(10):
                    while True:
                        await ws.recv()
            except ConnectionClosed as exc:
                assert exc.rcvd and exc.rcvd.code == 1009, exc

    await rejected(
        "/testing/stream/ws",
        65537,
        origin="http://testserver",
        additional_headers={"Authorization": "Bearer test-stream-token"},
    )
    issued = await browser.post("/codex/realtime-tickets", headers={"Origin": "http://testserver"})
    issued.raise_for_status()
    ticket = issued.json()["data"]["ticket"]
    await rejected("/codex/events?ticket=" + ticket, 1048577, origin="http://testserver")
    runtime = app.state.container.resource_mount.get_codex_control_runtime()
    original_settings = runtime.settings
    old_epoch = channel._connection_epoch
    try:
        runtime.settings = runtime.settings.model_copy(update={"bounded_content_enabled": False})
        channel._active_sender.request_close(code=1012, reason="acceptance_capability_rollback")
        async with asyncio.timeout(45):
            while channel._connection_epoch == old_epoch or not channel._connection_ready:
                await asyncio.sleep(0.05)
        assert not channel._bounded_content
        response = await browser.get(
            path, params={"include_history": "true", "content_mode": "bounded", "history_limit": 1}
        )
        response.raise_for_status()
        assert all("content" not in item["detail"] for item in response.json()["data"]["items"])
        assert channel._execution.valid
    finally:
        runtime.settings = original_settings
    report["scenarios"].append(
        {
            "name": "real product process limit4MiB, stream64KiB/browser1MiB rejected1009, feature-off reconnect retains lease/history via old protocol",
            "passed": True,
            "process_max_bytes": projected,
        }
    )
