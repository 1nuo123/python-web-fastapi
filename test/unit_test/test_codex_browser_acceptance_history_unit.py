"""真实联调报告核对器拒绝缺项及矛盾证据；本单元测试不证明真实链路成立。"""

from copy import deepcopy

import pytest

from scripts.codex.acceptance.browser_task import read_browser_history, verify_browser_history


def evidence():
    statuses = [
        ("streaming", "completed"),
        ("command_approval", "completed"),
        ("interruption", "interrupted"),
        ("after_reconnect", "completed"),
    ]
    turns = [{"turn_id": name, "name": name, "status": status} for name, status in statuses]
    turns[0].update(
        delta_count=3, visible_streaming_samples=1, first_delta_sequence=1, terminal_sequence=5
    )
    report = {
        "thread_id": "isolated-thread",
        "turns": turns,
        "commands": [{"item_id": "command-item"}],
        "approvals": [
            {"approval_id": "approval", "turn_id": "command_approval", "state": "applied"}
        ],
        "reconnection": {
            "draft_preserved": True,
            "before": {"closed": 0, "ready": 1},
            "after": {"closed": 1, "ready": 2},
        },
    }
    history = {
        "thread": {
            "id": "isolated-thread",
            "turns": [{"id": name, "status": status, "items": []} for name, status in statuses],
        }
    }
    history["thread"]["turns"][1]["items"] = [
        {
            "id": "command-item",
            "type": "commandExecution",
            "command": "Write-Output 'BROWSER_COMMAND_OK'",
            "aggregatedOutput": "BROWSER_COMMAND_OK\r\n",
            "exitCode": 0,
        }
    ]
    return report, history


def test_accepts_correlated_four_turn_authoritative_history():
    report, history = evidence()
    result = verify_browser_history(report, history)
    assert result["command_item_id"] == "command-item"
    assert [turn["status"] for turn in result["turns"]] == [
        "completed",
        "completed",
        "interrupted",
        "completed",
    ]


@pytest.mark.parametrize(
    "failure",
    [
        "missing-turn",
        "duplicate-turn",
        "wrong-thread",
        "wrong-terminal",
        "no-delta",
        "no-visible-stream",
        "late-delta",
        "missing-output",
        "nonzero-exit",
        "wrong-command-id",
        "unapplied-approval",
        "no-disconnect",
    ],
)
def test_rejects_incomplete_or_conflicting_evidence(failure):
    report, history = evidence()
    raw_turns = history["thread"]["turns"]
    command = raw_turns[1]["items"][0]
    if failure == "missing-turn":
        report["turns"].pop()
    elif failure == "duplicate-turn":
        raw_turns.append(deepcopy(raw_turns[0]))
    elif failure == "wrong-thread":
        history["thread"]["id"] = "unrelated-thread"
    elif failure == "wrong-terminal":
        raw_turns[2]["status"] = "completed"
    elif failure == "no-delta":
        report["turns"][0]["delta_count"] = 0
    elif failure == "no-visible-stream":
        report["turns"][0]["visible_streaming_samples"] = 0
    elif failure == "late-delta":
        report["turns"][0]["first_delta_sequence"] = 6
    elif failure == "missing-output":
        command["aggregatedOutput"] = ""
    elif failure == "nonzero-exit":
        command["exitCode"] = 1
    elif failure == "wrong-command-id":
        command["id"] = "other-command"
    elif failure == "unapplied-approval":
        report["approvals"][0]["state"] = "claimed"
    elif failure == "no-disconnect":
        report["reconnection"]["after"]["closed"] = 0
    with pytest.raises(AssertionError):
        verify_browser_history(report, history)


@pytest.mark.asyncio
@pytest.mark.parametrize("cycle", [False, True])
async def test_reads_official_turn_pages_without_include_turns(cycle):
    requests = []

    class HistoryClient:
        async def request(self, method, params, **kwargs):
            requests.append((method, params))
            if method == "thread/read":
                assert params == {"threadId": "isolated-thread", "includeTurns": False}
                return {"thread": {"id": "isolated-thread"}}
            assert method == "thread/turns/list"
            if "cursor" not in params:
                return {"data": [{"id": "first"}], "nextCursor": "second-page"}
            assert params["cursor"] == "second-page"
            return {"data": [{"id": "second"}], "nextCursor": "second-page" if cycle else None}

    if cycle:
        with pytest.raises(AssertionError, match="cursor"):
            await read_browser_history(HistoryClient(), "isolated-thread")
    else:
        result = await read_browser_history(HistoryClient(), "isolated-thread")
        assert [turn["id"] for turn in result["thread"]["turns"]] == ["first", "second"]
    assert len(requests) == 3
