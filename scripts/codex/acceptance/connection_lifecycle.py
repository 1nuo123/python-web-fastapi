"""真实网络/产品路由的连接与激活验收；复用主 runner 的资源生命周期。"""

import asyncio
import time

import httpx

from test.fixtures.codex_device_authorization_test_support import (
    CodexDeviceAuthorizationTestSupport as DeviceSupport,
)


async def activate_connected_host(
    settings, runtime, boundary, report, task, *, activate_callback=None
):
    from scripts.codex.acceptance.windows_connection import until

    host_id = settings.agent.host_id

    # Presence exists only after a genuine hello, independent of execution qualification.
    async def wait_presence(previous=None):
        async with asyncio.timeout(150):
            while True:
                current = await runtime.connection_registry.read(host_id)
                if (
                    current is not None
                    and current is not previous
                    and await runtime.presence_adapter.read(host_id) is not None
                ):
                    break
                if task.done():
                    await task
                    raise AssertionError("Agent stopped before presence")
                await asyncio.sleep(0.1)

    await wait_presence()
    first = await runtime.connection_registry.read(host_id)
    assert first is not None and first.sender._confirmed_generation is None
    # Force the second hello to exceed the dedicated watchdog; retry must remain possible.
    boundary.hello_delays = [12.0]
    closes_before = len(boundary.closed)
    first.close(1012, "acceptance_reconnect")
    await until(
        lambda: any(x["reason"] == "hello_timeout" for x in boundary.closed[closes_before:]),
        task=task,
    )
    await wait_presence(previous=first)
    assert all(x["code"] == 1013 for x in boundary.closed if x["reason"] == "hello_timeout")

    def activate():
        with httpx.Client(
            base_url=settings.agent.control_plane_api_url,
            verify=str(settings.agent.ca_certificate_path),
            trust_env=False,
            timeout=30,
        ) as browser:
            token = DeviceSupport.issue_browser_access_token(browser)
            browser.headers["Authorization"] = f"Bearer {token}"
            response = browser.get("/codex/hosts")
            response.raise_for_status()
            host = next(x for x in response.json()["data"]["items"] if x["host_id"] == str(host_id))
            assert host["connected"] and host["status"] == "offline", host
            state = browser.get("/codex/active-host")
            state.raise_for_status()
            if activate_callback is not None:
                return
            response = browser.put(
                "/codex/active-host",
                json={
                    "host_id": str(host_id),
                    "expected_version": state.json()["data"]["version"],
                },
            )
            response.raise_for_status()

    await asyncio.to_thread(activate)
    if activate_callback is not None:
        await activate_callback()
    report["scenarios"].append(
        {
            "name": "connected inactive host has no command admission; real activation API grants ownership",
            "passed": True,
        }
    )
    report["scenarios"].append(
        {
            "name": "hello timeout closes with 1013 and retries fresh ticket",
            "passed": True,
            "closed": boundary.closed.copy(),
        }
    )


async def handshake_recovery(channel, runtime, boundary, report, task, candidate):
    from scripts.codex.acceptance.windows_connection import until

    await until(lambda: channel._healthy_connection, timeout=40, task=task)
    instance = channel._supervisor.handle.instance_id
    epoch = channel._connection_epoch
    # A six-second hello must succeed on its first attempt, not consume another ticket.
    before = len(boundary.websocket_peers)
    boundary.hello_delays = [6.0]
    lease = await runtime.connection_registry.read(channel._settings.agent.host_id)
    started = time.monotonic()
    lease.close(1012, "acceptance_delay")
    await until(lambda: channel._connection_ready and channel._connection_epoch != epoch, task=task)
    elapsed = time.monotonic() - started
    same = channel._supervisor.handle.instance_id == instance
    attempts = len(boundary.websocket_peers) - before
    report["recovery_seconds"] = [elapsed]
    report["execution_misstops"] = int(not same)
    report["scenarios"].append(
        {
            "name": "six-second hello preserves execution and succeeds without needless reconnect",
            "passed": same and attempts == 1,
            "attempts": attempts,
            "seconds": elapsed,
        }
    )
    assert same and attempts == 1, "Delayed hello was rejected or execution was restarted"
    # Exercise the parent deadline: ticket=12s + hello=9s exceeds total=20s,
    # while each individual handshake stage remains below its own budget.
    if not candidate:
        epoch = channel._connection_epoch
        boundary.delay_next_ticket = 12.0
        boundary.hello_delays = [9.0]
        lease = await runtime.connection_registry.read(channel._settings.agent.host_id)
        lease.close(1012, "acceptance_deadline")
        await until(
            lambda: channel._connection_ready and channel._connection_epoch != epoch,
            timeout=75,
            task=task,
        )
        assert channel._supervisor.handle.instance_id == instance
        report["scenarios"].append(
            {"name": "total setup deadline preserves valid execution across retry", "passed": True}
        )
