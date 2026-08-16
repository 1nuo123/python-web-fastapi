"""Codex 会话索引与时间线契约测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from src.core.codex_contract.thread_contract import (
    CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
    CodexThreadIndexSnapshot,
    CodexTimelineItemEnvelope,
)


class TestCodexThreadContract:
    """确保公共头、强类型扩展与会话索引保持原子一致。"""

    THREAD_INDEX_ID = UUID("11111111-1111-1111-1111-111111111111")
    HOST_ID = UUID("22222222-2222-2222-2222-222222222222")
    WORKSPACE_ID = UUID("33333333-3333-3333-3333-333333333333")
    CREATED_AT = datetime(2026, 8, 15, 8, 0, tzinfo=UTC)
    RECENCY_AT = datetime(2026, 8, 15, 9, 30, tzinfo=UTC)

    def test_timeline_item_when_header_and_detail_match_should_validate(self) -> None:
        item = CodexTimelineItemEnvelope.model_validate(self._build_message_item())

        assert item.header.detail_kind.value == item.detail.kind
        assert item.header.schema_version == item.detail.schema_version

    def test_timeline_item_when_unknown_field_should_fail(self) -> None:
        payload = self._build_message_item()
        payload["unexpected"] = True

        with pytest.raises(ValidationError, match="extra_forbidden"):
            CodexTimelineItemEnvelope.model_validate(payload)

    def test_timeline_item_when_unknown_kind_should_fail(self) -> None:
        payload = self._build_message_item()
        payload["header"]["detail_kind"] = "unknown"
        payload["detail"]["kind"] = "unknown"

        with pytest.raises(ValidationError):
            CodexTimelineItemEnvelope.model_validate(payload)

    def test_timeline_item_when_header_kind_differs_should_fail(self) -> None:
        payload = self._build_message_item()
        payload["header"]["detail_kind"] = "notice"

        with pytest.raises(ValidationError, match="头与扩展类型不一致"):
            CodexTimelineItemEnvelope.model_validate(payload)

    def test_timeline_item_when_schema_version_is_unknown_should_fail(self) -> None:
        payload = self._build_message_item()
        payload["detail"]["schema_version"] = "2.0"

        with pytest.raises(ValidationError):
            CodexTimelineItemEnvelope.model_validate(payload)

    def test_diff_timeline_item_when_diff_missing_should_fail(self) -> None:
        payload = self._build_message_item()
        payload["header"]["detail_kind"] = "diff"
        payload["detail"] = {
            "kind": "diff",
            "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
        }

        with pytest.raises(ValidationError):
            CodexTimelineItemEnvelope.model_validate(payload)

    def test_thread_index_when_title_and_recency_present_should_validate(self) -> None:
        thread = CodexThreadIndexSnapshot.model_validate(
            {
                "thread_index_id": self.THREAD_INDEX_ID,
                "host_id": self.HOST_ID,
                "workspace_id": self.WORKSPACE_ID,
                "owner_subject_id": "subject-1",
                "upstream_thread_id": "thread-1",
                "display_name": "统一 Codex 会话体验",
                "title_source": "manual",
                "model": "gpt-5",
                "model_provider": "openai",
                "reasoning_effort": "high",
                "status": "idle",
                "active_turn_id": None,
                "archived": False,
                "is_pinned": True,
                "source_kind": "app_server",
                "created_at": self.CREATED_AT,
                "recency_at": self.RECENCY_AT,
                "updated_at": self.RECENCY_AT,
                "last_synced_at": self.RECENCY_AT,
            }
        )

        assert thread.display_name == "统一 Codex 会话体验"
        assert thread.title_source.value == "manual"
        assert thread.recency_at == self.RECENCY_AT

    def test_thread_index_when_title_is_blank_should_fail(self) -> None:
        payload = {
            "thread_index_id": self.THREAD_INDEX_ID,
            "host_id": self.HOST_ID,
            "workspace_id": self.WORKSPACE_ID,
            "owner_subject_id": "subject-1",
            "upstream_thread_id": "thread-1",
            "display_name": "",
            "title_source": "new_conversation",
            "status": "idle",
            "archived": False,
            "is_pinned": False,
            "created_at": self.CREATED_AT,
            "recency_at": self.RECENCY_AT,
            "updated_at": self.RECENCY_AT,
            "last_synced_at": self.RECENCY_AT,
        }

        with pytest.raises(ValidationError):
            CodexThreadIndexSnapshot.model_validate(payload)

    @staticmethod
    def _build_message_item() -> dict[str, object]:
        """构造满足公共头与强类型扩展约束的最小消息条目。"""

        return {
            "header": {
                "item_id": "item-1",
                "thread_id": "thread-1",
                "turn_id": "turn-1",
                "detail_kind": "agent_message",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "status": "completed",
            },
            "detail": {
                "kind": "agent_message",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "text": "已完成。",
            },
        }
