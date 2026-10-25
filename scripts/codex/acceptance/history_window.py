"""真实CLI -> Agent窗口 -> WSS -> 签名HTTP分页；只创建并清理隔离验收线程。"""

import asyncio
import ssl

import httpx

from test.fixtures.codex_device_authorization_test_support import (
    CodexDeviceAuthorizationTestSupport,
)


async def run_history_window(channel, *, origin, certificate, run_task, report):
    client = channel._supervisor.handle.client
    workspace = channel._workspace_registry.list_workspaces()[0]
    result = await client.request(
        "thread/start",
        {"cwd": str(workspace.root), "approvalPolicy": "never", "sandbox": "read-only"},
        timeout_seconds=30,
    )
    thread_id = result["thread"]["id"]
    try:
        turn = await client.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [
                    {
                        "type": "text",
                        "text": "Reply exactly CONNECTION_WINDOW_OK. Do not use tools.",
                    }
                ],
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "readOnly"},
            },
            timeout_seconds=30,
        )
        turn_id = turn["turn"]["id"]
        async with asyncio.timeout(120):
            while turn_id not in channel._completed_turns:
                if run_task.done():
                    await run_task
                await asyncio.sleep(0.2)
        await channel._send_snapshot(channel._supervisor.handle, channel._active_sender)

        def authenticate():
            with httpx.Client(base_url=origin, verify=str(certificate), trust_env=False) as browser:
                return CodexDeviceAuthorizationTestSupport.issue_browser_access_token(browser)

        token = await asyncio.to_thread(authenticate)
        context = ssl.create_default_context(cafile=str(certificate))
        path = f"/codex/hosts/{channel._settings.agent.host_id}/threads/{thread_id}"
        async with httpx.AsyncClient(
            base_url=origin,
            verify=context,
            trust_env=False,
            headers={"Authorization": f"Bearer {token}"},
            timeout=35,
        ) as browser:
            async with asyncio.timeout(45):
                while True:
                    response = await browser.get(
                        path, params={"include_history": "true", "history_limit": 1}
                    )
                    if response.status_code == 200:
                        break
                    if response.status_code != 404:
                        response.raise_for_status()
                    await asyncio.sleep(0.2)
            response.raise_for_status()
            snapshot = response.json()["data"]
            assert snapshot["history_status"] == "complete", snapshot["history_status"]
            assert len(snapshot["items"]) <= 1
            assert snapshot["history_revision"]
            ids = [item["header"]["item_id"] for item in snapshot["items"]]
            cursor = snapshot["history_before_cursor"]
            count = 1
            while cursor:
                response = await browser.get(
                    path + "/history", params={"before_cursor": cursor, "limit": 1}
                )
                response.raise_for_status()
                page = response.json()["data"]
                assert len(page["items"]) <= 1
                ids.extend(item["header"]["item_id"] for item in page["items"])
                assert page["before_cursor"] != cursor
                cursor = page["before_cursor"]
                count += 1
                assert count <= 20
            assert len(ids) >= 2 and len(set(ids)) == len(ids)
            response = await browser.get(
                path + "/history", params={"before_cursor": "tampered", "limit": 1}
            )
            assert response.status_code == 409, response.status_code
            report["scenarios"].append(
                {
                    "name": "real CLI signed bounded history windows, no missing/duplicate IDs, tamper rejected",
                    "passed": True,
                    "pages": count,
                    "items": len(ids),
                }
            )
    finally:
        await client.request("thread/delete", {"threadId": thread_id}, timeout_seconds=15)
