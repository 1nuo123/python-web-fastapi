"""Codex 历史签名游标与稳定窗口单元测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from pydantic import ValidationError

from src.application.codex.codex_history_pagination import (
    CodexHistoryCursorStaleError,
    CodexHistoryPageResolver,
    SignedCodexHistoryCursorCodec,
)
from src.core.codex_contract.thread_contract import (
    CodexThreadHistoryPage,
    CodexThreadHistoryQuery,
    CodexTimelineItemEnvelope,
)

HOST_ID = UUID("11111111-1111-1111-1111-111111111111")
HISTORY_CURSOR_SIGNING_KEY = b"history-pagination-test-signing-key"
BASE_TIME = datetime(2026, 8, 19, tzinfo=UTC)


def _item(item_id: str) -> CodexTimelineItemEnvelope:
    """构造不含敏感正文的最小时间线条目。"""

    return CodexTimelineItemEnvelope.model_validate(
        {
            "header": {
                "item_id": item_id,
                "thread_id": "thread-1",
                "turn_id": "turn-1",
                "detail_kind": "agent_message",
                "status": "completed",
            },
            "detail": {
                "kind": "agent_message",
                "text": item_id,
            },
        }
    )


def _resolver(now: list[datetime]) -> CodexHistoryPageResolver:
    """以可推进的固定时钟创建分页器。"""

    return CodexHistoryPageResolver(
        SignedCodexHistoryCursorCodec(
            signing_key=HISTORY_CURSOR_SIGNING_KEY,
            ttl_seconds=300,
            clock=lambda: now[0],
        )
    )


class TestCodexHistoryPaginationUnit:
    """验证游标不暴露 offset，并在任何范围变化后失败关闭。"""

    def test_history_contract_should_bound_signed_cursor_and_page_fields(self) -> None:
        """查询和响应契约必须拒绝裸 offset、超限页大小及未约束的扩展字段。"""

        query = CodexThreadHistoryQuery()
        page = CodexThreadHistoryPage(
            items=[_item("item-1")],
            before_cursor="signed-before-cursor",
            has_more=True,
            history_revision="a" * 64,
        )

        assert query.before_cursor is None
        assert query.limit == 50
        assert page.before_cursor == "signed-before-cursor"
        assert page.has_more is True
        assert page.history_revision == "a" * 64
        with pytest.raises(ValidationError):
            CodexThreadHistoryQuery(limit=101)
        with pytest.raises(ValidationError):
            CodexThreadHistoryQuery.model_validate({"offset": 1})

    def test_history_before_cursor_returns_strictly_older_items(self) -> None:
        now = [BASE_TIME]
        resolver = _resolver(now)
        items = [_item(f"item-{index}") for index in range(1, 6)]

        newest_page = resolver.build_page(
            owner_subject_id="subject-1",
            host_id=HOST_ID,
            upstream_thread_id="thread-1",
            items=items,
            before_cursor=None,
            limit=2,
        )
        older_page = resolver.build_page(
            owner_subject_id="subject-1",
            host_id=HOST_ID,
            upstream_thread_id="thread-1",
            items=items,
            before_cursor=newest_page.before_cursor,
            limit=2,
        )

        assert [item.header.item_id for item in newest_page.items] == ["item-4", "item-5"]
        assert newest_page.has_more is True
        assert newest_page.before_cursor is not None
        assert "history:" not in newest_page.before_cursor
        assert [item.header.item_id for item in older_page.items] == ["item-2", "item-3"]
        assert older_page.has_more is True

    def test_history_cursor_is_bound_to_owner_and_thread(self) -> None:
        now = [BASE_TIME]
        resolver = _resolver(now)
        items = [_item(f"item-{index}") for index in range(1, 4)]
        first_page = resolver.build_page(
            owner_subject_id="subject-1",
            host_id=HOST_ID,
            upstream_thread_id="thread-1",
            items=items,
            before_cursor=None,
            limit=1,
        )
        assert first_page.before_cursor is not None

        for owner_subject_id, host_id, upstream_thread_id in (
            ("subject-2", HOST_ID, "thread-1"),
            ("subject-1", UUID("22222222-2222-2222-2222-222222222222"), "thread-1"),
            ("subject-1", HOST_ID, "thread-2"),
        ):
            with pytest.raises(CodexHistoryCursorStaleError):
                resolver.build_page(
                    owner_subject_id=owner_subject_id,
                    host_id=host_id,
                    upstream_thread_id=upstream_thread_id,
                    items=items,
                    before_cursor=first_page.before_cursor,
                    limit=1,
                )

    def test_history_cursor_should_reject_tampering_expiry_and_revision_change(self) -> None:
        now = [BASE_TIME]
        resolver = _resolver(now)
        items = [_item(f"item-{index}") for index in range(1, 4)]
        first_page = resolver.build_page(
            owner_subject_id="subject-1",
            host_id=HOST_ID,
            upstream_thread_id="thread-1",
            items=items,
            before_cursor=None,
            limit=1,
        )
        assert first_page.before_cursor is not None

        with pytest.raises(CodexHistoryCursorStaleError):
            resolver.build_page(
                owner_subject_id="subject-1",
                host_id=HOST_ID,
                upstream_thread_id="thread-1",
                items=items,
                before_cursor=f"{first_page.before_cursor}x",
                limit=1,
            )
        now[0] = BASE_TIME + timedelta(seconds=301)
        with pytest.raises(CodexHistoryCursorStaleError):
            resolver.build_page(
                owner_subject_id="subject-1",
                host_id=HOST_ID,
                upstream_thread_id="thread-1",
                items=items,
                before_cursor=first_page.before_cursor,
                limit=1,
            )

        now[0] = BASE_TIME
        revision_cursor = resolver.build_page(
            owner_subject_id="subject-1",
            host_id=HOST_ID,
            upstream_thread_id="thread-1",
            items=items,
            before_cursor=None,
            limit=1,
        ).before_cursor
        assert revision_cursor is not None
        with pytest.raises(CodexHistoryCursorStaleError):
            resolver.build_page(
                owner_subject_id="subject-1",
                host_id=HOST_ID,
                upstream_thread_id="thread-1",
                items=[_item("new-item"), *items],
                before_cursor=revision_cursor,
                limit=1,
            )

    def test_history_window_change_should_reissue_cursor_with_new_revision(self) -> None:
        """权威历史改变后，新窗口必须生成新 revision 和新签名边界游标。"""

        now = [BASE_TIME]
        resolver = _resolver(now)
        original_items = [_item(f"item-{index}") for index in range(1, 4)]
        original_page = resolver.build_page(
            owner_subject_id="subject-1",
            host_id=HOST_ID,
            upstream_thread_id="thread-1",
            items=original_items,
            before_cursor=None,
            limit=1,
        )
        refreshed_page = resolver.build_page(
            owner_subject_id="subject-1",
            host_id=HOST_ID,
            upstream_thread_id="thread-1",
            items=[*original_items, _item("item-4")],
            before_cursor=None,
            limit=1,
        )

        assert original_page.before_cursor is not None
        assert refreshed_page.before_cursor is not None
        assert refreshed_page.history_revision != original_page.history_revision
        assert refreshed_page.before_cursor != original_page.before_cursor
