"""真实 HTTP/WSS 验收设备恢复、意图幂等与分页接续；仅操作隔离组合根。"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import ssl
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
import uvicorn
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.codex.acceptance.windows_connection import certificate
from src.api.testing.test_app_factory import TestAppFactory
from src.core.codex_contract.device_key_contract import DeviceKeyState
from src.core.codex_contract.realtime_event_contract import CodexRealtimeEventType
from src.infrastructure.codex.codex_protocol_mapper import CodexProductEvent
from src.infrastructure.codex_agent.agent_connection_ticket_provider import (
    AgentConnectionTicketProvider,
)
from src.infrastructure.codex_agent.agent_setup import CodexAgentSetupUsecase, WindowsEnrollmentUi
from src.infrastructure.codex_agent.windows_dpapi_device_key_store import (
    WindowsDpapiDeviceKeyStore,
    WindowsCurrentUserAclEnforcer,
)


async def redis_live(report):
    from redis.asyncio import Redis
    from src.infrastructure.streaming.redis_stream_state_store import RedisStreamStateStore
    from src.infrastructure.codex.codex_realtime_stream_adapter import CodexRealtimeStreamAdapter
    from src.infrastructure.codex.codex_browser_event_hub import CodexBrowserEventHub

    client = Redis.from_url("redis://127.0.0.1:16379", decode_responses=True)
    prefix = "codex-acceptance-" + uuid4().hex
    store = RedisStreamStateStore(client=client, key_prefix=prefix)
    adapter = CodexRealtimeStreamAdapter(store=store, ttl_seconds=60, max_events=2000)
    publisher = CodexBrowserEventHub(queue_capacity=32, distributed_stream=adapter)
    receiver = CodexBrowserEventHub(queue_capacity=32, distributed_stream=adapter)
    subscription = await receiver.subscribe("owner-a")
    isolated = await receiver.subscribe("owner-b")
    try:
        event = CodexProductEvent(
            event_type=CodexRealtimeEventType.HOST_SNAPSHOT,
            host_id=UUID(int=0),
            workspace_id=None,
            thread_id=None,
            turn_id=None,
            item_id=None,
            payload={"hosts": []},
        )
        await publisher.publish("owner-a", event)
        batch = await asyncio.wait_for(subscription.take_batch(), 3)
        assert len(batch.events) == 1 and batch.events[0].header.cursor
        cursor = batch.events[0].header.cursor
        for count in (1, 499, 500, 501):
            for _ in range(count):
                await publisher.publish("owner-a", event)
            boundary = (
                await adapter.read(owner_subject_id="owner-a", after_cursor=None, limit=1)
            ).tail_cursor
            seen = 0
            while cursor != boundary:
                window = await adapter.read(
                    owner_subject_id="owner-a",
                    after_cursor=cursor,
                    through_cursor=boundary,
                    limit=500,
                )
                assert not window.gap
                seen += len(window.events)
                cursor = window.next_cursor
            assert seen == count, (seen, count)
        try:
            await asyncio.wait_for(isolated.take_batch(), 0.2)
            raise AssertionError("cross-owner event leaked")
        except TimeoutError:
            pass
        keys = [key async for key in client.scan_iter(match=prefix + "*")]
        await client.delete(*keys)
        gap = await adapter.read(owner_subject_id="owner-a", after_cursor=cursor, limit=1)
        assert gap.gap and gap.snapshot_required
        report["checks"].append(
            "real Redis cross-instance live delivery, owner isolation, 1/499/500/501 bounded replay, lost stream gap"
        )
    finally:
        await receiver.unsubscribe(subscription)
        await receiver.unsubscribe(isolated)
        assert not receiver._readers
        keys = [key async for key in client.scan_iter(match=prefix + "*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()


async def main() -> None:
    report = {"started_at": datetime.now(UTC).isoformat(), "checks": [], "passed": False}
    output = ROOT / "artifacts/codex-connection/enrollment-realtime.json"
    os.environ["AUTH_BOOTSTRAP_ADMIN_PASSWORD"] = "admin"
    with tempfile.TemporaryDirectory(prefix="codex-enrollment-e2e-") as directory:
        root = Path(directory)
        cert, key = certificate(root)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.close()
        origin = f"https://127.0.0.1:{port}"
        app = TestAppFactory().create(
            overrides={"runtime": {"web": {"cors": {"allow_origins": [origin]}}}}
        )
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=port,
                ssl_certfile=str(cert),
                ssl_keyfile=str(key),
                access_log=False,
                log_level="warning",
            )
        )
        serving = asyncio.create_task(server.serve())
        try:
            while not server.started:
                if serving.done():
                    await serving
                await asyncio.sleep(0.05)
            runtime = app.state.container.resource_mount.get_codex_control_runtime()
            tls = ssl.create_default_context(cafile=str(cert))
            async with httpx.AsyncClient(
                base_url=origin, verify=tls, trust_env=False, timeout=20
            ) as client:

                async def post(path, body, *, browser=False):
                    response = await client.post(
                        path, json=body, headers=browser_headers if browser else {}
                    )
                    response.raise_for_status()
                    return response.json()

                login = await client.post(
                    "/auth/browser/token",
                    json={"username": "admin", "password": "admin"},
                    headers={"Origin": origin},
                )
                login.raise_for_status()
                browser_headers = {
                    "Authorization": "Bearer " + login.json()["data"]["access_token"],
                    "Origin": origin,
                }
                header = {
                    "kind": "codex_enrollment_intent",
                    "schema_version": "1.0",
                    "request_id": str(uuid4()),
                }
                enrollment = (
                    await post(
                        "/codex/enrollment-intents", {"header": header, "detail": {}}, browser=True
                    )
                )["data"]
                token = parse_qs(urlsplit(enrollment["detail"]["launch_uri"]).query)["token"][0]
                keys = WindowsDpapiDeviceKeyStore(root=root / "keys")
                key_id = uuid4()
                public = keys.generate(key_id)
                setup = CodexAgentSetupUsecase(
                    client=client,
                    key_store=keys,
                    ui=WindowsEnrollmentUi(),
                    acl_enforcer=WindowsCurrentUserAclEnforcer(),
                )
                request = setup._build_create_request(
                    key_id=key_id,
                    public_key=public,
                    display_name="E2E isolated computer",
                    platform="windows",
                )
                consume = {
                    "header": header,
                    "detail": {
                        "intent_token": token,
                        "authorization": request.detail.model_dump(mode="json"),
                    },
                }
                issued = await post("/internal/codex-agents/enrollment-intents/consume", consume)
                repeated = await post("/internal/codex-agents/enrollment-intents/consume", consume)
                assert issued == repeated
                changed = json.loads(json.dumps(consume))
                changed["detail"]["authorization"]["key_id"] = str(uuid4())
                assert (
                    await client.post(
                        "/internal/codex-agents/enrollment-intents/consume", json=changed
                    )
                ).status_code == 409
                report["checks"].append(
                    "consume response loss reuses same enrollment; different key rejected"
                )
                auth_header = {
                    "kind": "codex_device_authorization",
                    "schema_version": "1.0",
                    "request_id": str(uuid4()),
                }
                approved = (
                    await post(
                        "/codex/device-authorizations/decisions",
                        {
                            "header": auth_header,
                            "detail": {
                                "enrollment_id": issued["header"]["enrollment_id"],
                                "user_code": issued["detail"]["user_code"],
                                "decision": "approve",
                                "idempotency_key": "acceptance-" + uuid4().hex,
                            },
                        },
                        browser=True,
                    )
                )["data"]
                host_id = UUID(approved["detail"]["host_id"])
                provider = AgentConnectionTicketProvider(
                    client=client, control_plane_api_url=origin, key_store=keys
                )
                await provider.issue(host_id=host_id, key_id=key_id)
                report["checks"].append("APPROVED is connectable immediately")
                new_intent = (
                    await post(
                        "/codex/enrollment-intents", {"header": header, "detail": {}}, browser=True
                    )
                )["data"]
                new_token = parse_qs(urlsplit(new_intent["detail"]["launch_uri"]).query)["token"][0]
                proof = await provider.prove(host_id=host_id, key_id=key_id)
                resumed = await post(
                    "/internal/codex-agents/enrollment-intents/resume",
                    {"intent_token": new_token, "proof": proof.model_dump(mode="json")},
                )
                assert resumed["detail"]["host_id"] == str(host_id)
                report["checks"].append(
                    "existing signed device completes new intent without new host"
                )
                enrollment_id = UUID(issued["header"]["enrollment_id"])
                store = runtime.device_authorization_store
                record = await store.read_by_user_code(issued["detail"]["user_code"])
                state_key = store._device_key(enrollment_id)
                await store._state.delete(key=state_key, expected_version=record.version)

                # Simulate a committed approval whose activation response was lost.
                def change_key(state):
                    uow = runtime.control_port.create_unit_of_work()
                    try:
                        repository = runtime.control_port.create_codex_device_key_repository(
                            uow.get_session()
                        )
                        stored = repository.get_by_enrollment(enrollment_id)
                        repository.save(
                            stored.model_copy(
                                update={"state": state, "version": stored.version + 1}
                            )
                        )
                        uow.commit()
                    finally:
                        uow.dispose()

                await asyncio.to_thread(change_key, DeviceKeyState.PENDING)
                recovered = await setup._recover_authorization(origin, enrollment_id, key_id)
                assert recovered.host_id == host_id and recovered.activated
                await provider.issue(host_id=host_id, key_id=key_id)
                report["checks"].append(
                    "missing temporary authorization recovers durable approved same key/host and activation"
                )
                from src.infrastructure.codex_agent.agent_configuration import (
                    AgentWorkspaceSettings,
                )
                from src.infrastructure.codex_agent.agent_enrollment_attempt_store import (
                    AgentEnrollmentAttempt,
                    AgentEnrollmentAttemptStore,
                )

                config_path = root / "agent.toml"
                attempts = AgentEnrollmentAttemptStore(config_path, WindowsCurrentUserAclEnforcer())
                attempts.write(
                    AgentEnrollmentAttempt(
                        api_url=origin,
                        created_at=datetime.now(UTC),
                        workspace=AgentWorkspaceSettings(
                            key="acceptance", display_name="Acceptance", root=root, allow_write=True
                        ),
                        request=request,
                        intent_token=token,
                        issued=None,
                    )
                )
                settings = await setup.execute(
                    config_path=config_path,
                    api_url=origin,
                    websocket_url=origin.replace("https:", "wss:")
                    + "/internal/codex-agents/connect",
                    display_name="E2E isolated computer",
                    platform="windows",
                    workspace=None,
                    expected_codex_version="0.145.0",
                    agent_version="0.1.40",
                    schema_digest="0" * 64,
                )
                assert settings.agent.host_id == host_id and settings.agent.key_id == key_id
                assert attempts.read() is None and config_path.is_file()
                report["checks"].append(
                    "local DPAPI attempt with missing create response recovers same durable identity and atomically persists configuration"
                )
                await asyncio.to_thread(change_key, DeviceKeyState.REVOKED)
                recovery = await client.post(
                    "/internal/codex-agents/device-authorizations/recover",
                    json={"enrollment_id": str(enrollment_id), "key_id": str(key_id)},
                )
                assert recovery.status_code == 409
                report["checks"].append("recovery cannot revive a revoked key")
                # Publish through the real shared stream and reconnect through real WSS.
                owner = "user-admin"
                event = CodexProductEvent(
                    event_type=CodexRealtimeEventType.HOST_SNAPSHOT,
                    host_id=UUID(int=0),
                    workspace_id=None,
                    thread_id=None,
                    turn_id=None,
                    item_id=None,
                    payload={"hosts": []},
                )
                await runtime.browser_event_hub.publish(owner, event)
                first = await runtime.realtime_stream_adapter.read(
                    owner_subject_id=owner, after_cursor=None, limit=1
                )
                cursor = first.cursors[-1]
                for _ in range(1501):
                    await runtime.browser_event_hub.publish(owner, event)

                async def read_ready(after_cursor, expected):
                    ticket = (await post("/codex/realtime-tickets", None, browser=True))["data"][
                        "ticket"
                    ]
                    url = (
                        origin.replace("https:", "wss:")
                        + f"/codex/events?ticket={ticket}&cursor={after_cursor}"
                    )
                    count = 0
                    last = after_cursor
                    async with connect(url, ssl=tls, origin=origin, proxy=None) as websocket:
                        while True:
                            frame = json.loads(await asyncio.wait_for(websocket.recv(), 20))
                            if frame["detail"]["kind"] == "connection.ready":
                                assert count == expected, (count, expected)
                                break
                            if frame["header"].get("cursor"):
                                count += 1
                                last = frame["header"]["cursor"]
                    return last

                last = await read_ready(cursor, 1501)
                await read_ready(last, 0)
                report["checks"].append("1501-event replay and empty replay each close with ready")
                if "--redis" in sys.argv:
                    await redis_live(report)
                report["passed"] = True
        except BaseException as exc:
            report["error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
            raise
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, 30)
            report["completed_at"] = datetime.now(UTC).isoformat()
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
