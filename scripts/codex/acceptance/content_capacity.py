"""产品HTTPS/WSS全链路容量场景；仅公开源分页接缝使用合成数据，明确不冒充真实CLI。"""

import asyncio
import hashlib
import time


async def run_capacity_scenarios(channel, browser, *, path, thread_id, report, authenticate):
    client = channel._supervisor.handle.client
    original = client.request
    metadata = await original(
        "thread/read", {"threadId": thread_id, "includeTurns": False}, timeout_seconds=15
    )
    source = '中文🙂\\\n"\t' * 12000
    count = 32
    source_calls = 0
    blocked = False
    local_items = None
    entered = asyncio.Event()
    release = asyncio.Event()

    async def request(method, params, **kwargs):
        nonlocal source_calls
        if (
            not isinstance(params, dict)
            or params.get("threadId") != thread_id
            or method not in {"thread/read", "thread/turns/list", "thread/items/list"}
        ):
            return await original(method, params, **kwargs)
        if blocked:
            entered.set()
            await release.wait()
        source_calls += 1
        if method == "thread/read":
            return metadata
        if local_items is not None:
            if method == "thread/turns/list":
                return {
                    "data": [
                        {
                            "id": "capacity-local-turn",
                            "status": "completed",
                            "items": local_items if params.get("itemsView") == "full" else [],
                        }
                    ],
                    "nextCursor": None,
                }
            index = int(params.get("cursor", "0"))
            return {
                "data": [{"turnId": "capacity-local-turn", "item": local_items[index]}],
                "nextCursor": str(index + 1) if index + 1 < len(local_items) else None,
            }
        if method == "thread/items/list" and params.get("turnId"):
            index = int(params["turnId"].rsplit("-", 1)[1])
            return {
                "data": [
                    {
                        "turnId": params["turnId"],
                        "item": {
                            "id": f"capacity-item-{index}",
                            "type": "agentMessage",
                            "text": source + str(index),
                        },
                    }
                ],
                "nextCursor": None,
            }
        position = int(params.get("cursor", "0"))
        limit = min(int(params.get("limit", 1)), count - position)
        entries = []
        for index in range(position, position + limit):
            item = {
                "id": f"capacity-item-{index}",
                "type": "agentMessage",
                "text": source + str(index),
            }
            turn_id = f"capacity-turn-{index}"
            entries.append(
                {"turnId": turn_id, "item": item}
                if method == "thread/items/list"
                else {
                    "id": turn_id,
                    "status": "completed",
                    "items": [] if params.get("itemsView") in {"summary", "notLoaded"} else [item],
                }
            )
        return {
            "data": entries,
            "nextCursor": str(position + limit) if position + limit < count else None,
        }

    client.request = request
    try:
        started = time.perf_counter()
        descriptors = []
        sizes = []
        cursor = None
        while True:
            response = await browser.get(
                path if cursor is None else path + "/history",
                params={
                    "content_mode": "bounded",
                    **(
                        {"include_history": "true", "history_limit": 100}
                        if cursor is None
                        else {"before_cursor": cursor, "limit": 100}
                    ),
                },
            )
            response.raise_for_status()
            sizes.append(len(response.content))
            value = response.json()["data"]
            assert value["schema_version"] == "bounded-content.1"
            descriptors.extend(
                (i["header"]["item_id"], i["detail"]["content"]) for i in value["items"]
            )
            cursor = value.get("history_before_cursor", value.get("before_cursor"))
            if not cursor:
                break
            assert len(sizes) < 20
        assert len(descriptors) == count and len({i for i, _ in descriptors}) == count
        assert max(sizes) <= channel._content_budgets.history_page_max_bytes
        semaphore = asyncio.Semaphore(4)

        async def read_all(item_id, descriptor):
            async with semaphore:
                offset = 0
                chunks = []
                while True:
                    response = await browser.post(
                        path + f"/history/items/{item_id}/content/read",
                        json={
                            "content_ref": descriptor["content_ref"],
                            "revision": descriptor["revision"],
                            "offset": offset,
                            "requested_bytes": 65536,
                        },
                    )
                    response.raise_for_status()
                    assert (
                        len(response.content)
                        <= channel._content_budgets.content_chunk_max_message_bytes
                    )
                    chunk = response.json()["data"]
                    assert chunk["offset"] == offset
                    chunks.append(chunk["text"])
                    offset = chunk["next_offset"]
                    if chunk["eof"]:
                        break
                expected = source + item_id.rsplit("-", 1)[1]
                assert "".join(chunks) == expected
                return offset

        total = sum(await asyncio.gather(*(read_all(i, d) for i, d in descriptors)))
        assert total > 4 * 1024 * 1024
        item_id, descriptor = descriptors[0]
        body = {
            "content_ref": descriptor["content_ref"],
            "revision": descriptor["revision"],
            "offset": 0,
            "requested_bytes": 16384,
        }
        endpoint = path + f"/history/items/{item_id}/content/read"
        channel._history_window_cache.invalidate_thread(thread_id)
        expired = await browser.post(endpoint, json=body)
        assert expired.status_code == 410
        reloaded = await browser.get(
            path + "/history/items", params={"content_mode": "bounded", "item_id": item_id}
        )
        reloaded.raise_for_status()
        renewed = reloaded.json()["data"]["items"][0]["detail"]["content"]
        assert (
            renewed["revision"] == descriptor["revision"]
            and renewed["content_ref"] != descriptor["content_ref"]
        )
        restored = await browser.post(
            endpoint, json={**body, "content_ref": renewed["content_ref"]}
        )
        restored.raise_for_status()
        blocked = True
        outstanding = [
            asyncio.create_task(
                browser.get(path, params={"content_mode": "bounded", "include_history": "true"})
            )
            for _ in range(2)
        ]
        try:
            await asyncio.wait_for(entered.wait(), 5)
            async with asyncio.timeout(5):
                while (
                    channel._queries._reserved_bytes
                    < 2 * channel._content_budgets.history_page_max_bytes
                ):
                    await asyncio.sleep(0.01)
            overloaded = await browser.post(
                endpoint, json={**body, "content_ref": renewed["content_ref"]}
            )
            assert overloaded.status_code == 429, overloaded.status_code
            for task in outstanding:
                task.cancel()
            await asyncio.gather(*outstanding, return_exceptions=True)
        finally:
            release.set()
            blocked = False
            for task in outstanding:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*outstanding, return_exceptions=True)
        async with asyncio.timeout(5):
            while channel._queries.active:
                await asyncio.sleep(0.01)
        assert channel._queries._reserved_bytes == 0
        report["scenarios"].append(
            {
                "name": "synthetic source seam -> real Agent WSS -> product HTTPS; >4MiB history, exact body, parallel readers, 429, cancellation, expiry/reload",
                "passed": True,
                "source": "synthetic public-page interface, NOT real CLI large-item proof",
                "items": count,
                "total_body_bytes": total,
                "pages": len(sizes),
                "largest_http_page_bytes": max(sizes),
                "source_reads": source_calls,
                "seconds": time.perf_counter() - started,
                "sample_sha256": hashlib.sha256(source.encode()).hexdigest(),
            }
        )
        browser.headers["Authorization"] = "Bearer " + await asyncio.to_thread(authenticate)
        # Exercise the same realtime capture path, including an original body above
        # the product model's 1 MiB character limit and different public-history IDs.
        # This remains a labeled source seam; actual transport/usecases are unchanged.
        assert channel._execution_root_store.load(thread_id) is not None
        bodies = {
            "native-small": "中文🙂\\\n" * 1800,
            "native-large": "x" * 1_050_000 + "正文末尾🙂",
        }
        local_items = [
            {"id": f"public-{index}", "type": "agentMessage", "text": body}
            for index, body in enumerate(bodies.values())
        ]
        local_items.insert(
            0,
            {
                "id": "public-decoy",
                "type": "userMessage",
                "content": [{"type": "text", "text": bodies["native-large"]}],
            },
        )
        await channel._accept_app_server_notification(
            "turn/started",
            {
                "threadId": thread_id,
                "turn": {"id": "capacity-local-turn", "status": "inProgress", "items": []},
            },
        )
        for item_id, body in bodies.items():
            await channel._accept_app_server_notification(
                "item/completed",
                {
                    "threadId": thread_id,
                    "turnId": "capacity-local-turn",
                    "item": {"id": item_id, "type": "agentMessage", "text": body},
                },
            )
        await channel._accept_app_server_notification(
            "turn/completed",
            {
                "threadId": thread_id,
                "turn": {"id": "capacity-local-turn", "status": "completed", "items": []},
            },
        )
        channel._history_window_cache.invalidate_thread(thread_id)
        local_descriptors = []
        response = await browser.get(
            path, params={"content_mode": "bounded", "include_history": "true", "history_limit": 1}
        )
        response.raise_for_status()
        page = response.json()["data"]
        local_descriptors.extend(page["items"])
        while page.get("history_before_cursor", page.get("before_cursor")):
            response = await browser.get(
                path + "/history",
                params={
                    "content_mode": "bounded",
                    "limit": 1,
                    "before_cursor": page.get("history_before_cursor", page.get("before_cursor")),
                },
            )
            response.raise_for_status()
            page = response.json()["data"]
            local_descriptors.extend(page["items"])
        assert [item["header"]["item_id"] for item in local_descriptors] == list(reversed(bodies))
        for item in local_descriptors:
            item_id = item["header"]["item_id"]
            response = await browser.get(
                path + "/history/items", params={"content_mode": "bounded", "item_id": item_id}
            )
            response.raise_for_status()
            reloaded = response.json()["data"]["items"]
            assert len(reloaded) == 1 and reloaded[0]["header"]["item_id"] == item_id
            assert reloaded[0]["detail"]["kind"] == "agent_message"
            descriptor = reloaded[0]["detail"]["content"]
            offset, chunks = 0, []
            while True:
                response = await browser.post(
                    path + f"/history/items/{item_id}/content/read",
                    json={
                        "content_ref": descriptor["content_ref"],
                        "revision": descriptor["revision"],
                        "offset": offset,
                        "requested_bytes": 12 * 1024,
                    },
                )
                response.raise_for_status()
                chunk = response.json()["data"]
                assert chunk["offset"] == offset
                chunks.append(chunk["text"])
                offset = chunk["next_offset"]
                if chunk["eof"]:
                    break
            assert "".join(chunks) == bodies[item_id]
        report["scenarios"].append(
            {
                "name": "realtime capture -> local stable IDs -> bounded pages -> HTTP reload -> exact full body",
                "passed": True,
                "source": "synthetic notification/public-source seam with different IDs; actual product capture and HTTPS/WSS",
                "items": len(bodies),
                "largest_body_bytes": max(len(body.encode()) for body in bodies.values()),
                "expired_cache_recovery": True,
                "order_and_stable_ids_preserved": True,
                "respected_existing_http_rate_limit": True,
            }
        )
    finally:
        client.request = original
        channel._history_window_cache.invalidate_thread(thread_id)
