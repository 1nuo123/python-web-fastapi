"""真实CLI -> Agent窗口 -> WSS -> 签名HTTP分页；只创建并清理隔离验收线程。"""

import asyncio
import ssl
import hashlib
import sys
from pathlib import Path

import httpx

from test.fixtures.codex_device_authorization_test_support import (
    CodexDeviceAuthorizationTestSupport,
)


async def run_history_window(channel, *, origin, certificate, run_task, report, app=None):
    from src.infrastructure.codex_agent.agent_bounded_history_reader import (
        AgentBoundedHistoryReader,
    )

    original_read = AgentBoundedHistoryReader.read

    async def observed_read(reader, **kwargs):
        try:
            return await original_read(reader, **kwargs)
        except Exception as exc:
            report["bounded_reader_error"] = {
                "type": type(exc).__name__,
                "message": str(exc)[:1500],
            }
            raise

    AgentBoundedHistoryReader.read = observed_read
    client = channel._supervisor.handle.client
    workspace = channel._workspace_registry.list_workspaces()[0]
    result = await client.request(
        "thread/start",
        {"cwd": str(workspace.root), "approvalPolicy": "never", "sandbox": "read-only"},
        timeout_seconds=30,
    )
    thread_id = result["thread"]["id"]
    source_text = "中文🙂\\\n" * 1800 + "\nReply exactly CONNECTION_WINDOW_OK. Do not use tools."
    try:
        turn = await client.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [
                    {
                        "type": "text",
                        "text": source_text,
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
            limits=httpx.Limits(keepalive_expiry=2),
        ) as browser:
            async with asyncio.timeout(45):
                while True:
                    response = await browser.get(
                        path,
                        params={
                            "include_history": "true",
                            "history_limit": 1,
                            "content_mode": "bounded",
                        },
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
            descriptors = [
                (item["header"]["item_id"], item["detail"]["content"])
                for item in snapshot["items"]
                if item["detail"].get("content")
            ]
            cursor = snapshot["history_before_cursor"]
            count = 1
            while cursor:
                response = await browser.get(
                    path + "/history",
                    params={"before_cursor": cursor, "limit": 1, "content_mode": "bounded"},
                )
                response.raise_for_status()
                page = response.json()["data"]
                assert len(page["items"]) <= 1
                ids.extend(item["header"]["item_id"] for item in page["items"])
                descriptors.extend(
                    (item["header"]["item_id"], item["detail"]["content"])
                    for item in page["items"]
                    if item["detail"].get("content")
                )
                assert page["before_cursor"] != cursor
                cursor = page["before_cursor"]
                count += 1
                assert count <= 20
            assert len(ids) >= 2 and len(set(ids)) == len(ids)
            assert channel._bounded_content
            assert descriptors, "真实CLI历史没有返回正文描述"
            item_id, descriptor = next(
                (identity, desc)
                for identity, desc in descriptors
                if desc["total_bytes"] == len(source_text.encode("utf-8"))
            )
            content_path = path + f"/history/items/{item_id}/content/read"
            body = {
                "content_ref": descriptor["content_ref"],
                "revision": descriptor["revision"],
                "offset": 0,
                "requested_bytes": 16384,
            }
            received, offset, chunks = [], 0, 0
            while True:
                response = await browser.post(content_path, json={**body, "offset": offset})
                response.raise_for_status()
                chunk = response.json()["data"]
                assert chunk["offset"] == offset
                assert chunk["next_offset"] == offset + len(chunk["text"].encode("utf-8"))
                assert (
                    len(response.content)
                    <= channel._content_budgets.content_chunk_max_message_bytes
                )
                received.append(chunk["text"])
                chunks += 1
                offset = chunk["next_offset"]
                if chunk["eof"]:
                    break
                assert chunks < 100
            assert "".join(received) == source_text
            for invalid, expected in [
                ({**body, "offset": 1}, 416),
                ({**body, "revision": "stale"}, 409),
                ({**body, "content_ref": "tampered"}, 410),
            ]:
                rejected = await browser.post(content_path, json=invalid)
                assert rejected.status_code == expected, (rejected.status_code, expected)
            legacy = await browser.get(path, params={"include_history": "true", "history_limit": 1})
            legacy.raise_for_status()
            assert all("content" not in item["detail"] for item in legacy.json()["data"]["items"])
            report["scenarios"].append(
                {
                    "name": "real CLI bounded history and signed UTF-8 content through HTTPS/WSS, scope/range/stale/tamper, legacy DTO",
                    "passed": True,
                    "bytes": offset,
                    "chunks": chunks,
                    "sha256": hashlib.sha256(source_text.encode()).hexdigest(),
                    "budgets": channel._content_budgets.model_dump(),
                }
            )

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
            if "--capacity-scenarios" in sys.argv:
                from scripts.codex.acceptance.content_capacity import run_capacity_scenarios

                await run_capacity_scenarios(
                    channel,
                    browser,
                    path=path,
                    thread_id=thread_id,
                    report=report,
                    authenticate=authenticate,
                )
            if "--capacity-scenarios" in sys.argv:
                from scripts.codex.acceptance.content_transport_boundaries import (
                    run_transport_boundaries,
                )

                await run_transport_boundaries(
                    app, channel, browser, origin=origin, context=context, path=path, report=report
                )
        if "--content-browser" in sys.argv:
            from scripts.codex.acceptance.browser_task import run_browser_task

            await run_browser_task(
                channel,
                origin=origin,
                certificate=certificate,
                report=report,
                acceptance_report=Path(
                    next(
                        arg.split("=", 1)[1]
                        for arg in sys.argv
                        if arg.startswith("--acceptance-report=")
                    )
                ).resolve(),
                content_thread_id=thread_id,
                timeout_seconds=180,
            )
    finally:
        AgentBoundedHistoryReader.read = original_read
        await client.request("thread/delete", {"threadId": thread_id}, timeout_seconds=15)
