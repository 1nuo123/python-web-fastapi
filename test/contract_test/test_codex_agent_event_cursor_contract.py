"""Codex Agent 事件游标契约测试。"""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.core.codex_contract.agent_event_cursor_contract import CodexAgentEventCursorState


class TestCodexAgentEventCursorContract:
    """验证事件游标强类型契约。"""

    def test_cursor_state_when_complete_should_round_trip(self) -> None:
        """验证事件游标公共头与强类型扩展字段可稳定序列化。"""

        state = CodexAgentEventCursorState(
            host_id=uuid4(),
            agent_event_epoch=uuid4(),
            after_seq=4,
        )

        assert CodexAgentEventCursorState.model_validate_json(state.model_dump_json()) == state

    def test_cursor_state_when_extra_field_should_reject(self) -> None:
        """验证游标契约拒绝未知字段。"""

        with pytest.raises(ValidationError):
            CodexAgentEventCursorState.model_validate(
                {
                    "host_id": str(uuid4()),
                    "agent_event_epoch": str(uuid4()),
                    "after_seq": 1,
                    "unexpected": True,
                }
            )
