"""用真实HTTPS健康路由验证业务池饱和时的隔离与503合同。"""

import asyncio
import ssl
import threading
import time

import httpx


async def run_health_isolation(app, *, origin, certificate, report):
    mount = app.state.container.resource_mount
    bridge = mount.get_request_execution_bridge()
    release = threading.Event()
    started = 0
    lock = threading.Lock()

    def occupy():
        nonlocal started
        with lock:
            started += 1
        release.wait(10)

    worker_count = bridge._executor._max_workers
    workers = [
        asyncio.create_task(
            bridge.run_sync(execution_name="default_sync_usecase", callable_object=occupy)
        )
        for _ in range(worker_count)
    ]
    try:
        async with asyncio.timeout(2):
            while started < worker_count:
                await asyncio.sleep(0.01)
        context = ssl.create_default_context(cafile=str(certificate))
        async with httpx.AsyncClient(
            base_url=origin, verify=context, trust_env=False, timeout=2
        ) as browser:
            started_at = time.monotonic()
            response = await browser.get("/health/ready")
            duration = time.monotonic() - started_at
            assert response.status_code == 200, response.status_code
            assert duration < 1, duration
            mount._publish_health_snapshot(ready=False)
            response = await browser.get("/health/ready")
            assert response.status_code == 503, response.status_code
            mount._publish_health_snapshot(ready=True)
            report["scenarios"].append(
                {
                    "name": "HTTPS health bypasses saturated business pool and preserves not-ready 503",
                    "passed": True,
                    "ready_seconds": duration,
                    "occupied_workers": started,
                }
            )
    finally:
        mount._publish_health_snapshot(ready=True)
        release.set()
        await asyncio.gather(*workers, return_exceptions=True)
