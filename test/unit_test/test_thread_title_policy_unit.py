"""Codex 会话标题策略单元测试。"""

from __future__ import annotations

from datetime import UTC, datetime

from src.core.codex_contract.thread_contract import (
    CODEX_THREAD_TITLE_MAX_LENGTH,
    CodexThreadTitleSource,
)
from src.domain.codex.thread_title_policy import CodexThreadTitlePolicy


class TestCodexThreadTitlePolicyUnit:
    """验证标题来源优先级、归一化与稳定占位名。"""

    CREATED_AT = datetime(2026, 8, 15, 17, 32, tzinfo=UTC)

    def test_manual_title_should_override_all_derived_sources(self) -> None:
        decision = CodexThreadTitlePolicy().resolve(
            created_at=self.CREATED_AT,
            existing_title="  用户手工名称  ",
            existing_source=CodexThreadTitleSource.MANUAL,
            app_server_title="App Server 名称",
            first_user_message="第一条用户消息",
        )

        assert decision.display_name == "用户手工名称"
        assert decision.source is CodexThreadTitleSource.MANUAL

    def test_app_server_title_should_override_first_user_message(self) -> None:
        decision = CodexThreadTitlePolicy().resolve(
            created_at=self.CREATED_AT,
            app_server_title="App Server 名称",
            first_user_message="第一条用户消息",
        )

        assert decision.display_name == "App Server 名称"
        assert decision.source is CodexThreadTitleSource.APP_SERVER

    def test_first_user_message_should_remove_controls_and_collapse_whitespace(self) -> None:
        decision = CodexThreadTitlePolicy().resolve(
            created_at=self.CREATED_AT,
            first_user_message="  完成\n\tCodex\x00 会话整改  ",
        )

        assert decision.display_name == "完成 Codex 会话整改"
        assert decision.source is CodexThreadTitleSource.FIRST_USER_MESSAGE

    def test_long_title_should_truncate_at_word_boundary(self) -> None:
        prefix = "a" * (CODEX_THREAD_TITLE_MAX_LENGTH - 8)
        normalized = CodexThreadTitlePolicy().normalize(f"{prefix} boundary trailing-content")

        assert normalized == prefix
        assert len(normalized) <= CODEX_THREAD_TITLE_MAX_LENGTH

    def test_long_unbroken_title_should_use_hard_limit(self) -> None:
        normalized = CodexThreadTitlePolicy().normalize("长" * (CODEX_THREAD_TITLE_MAX_LENGTH + 20))

        assert normalized == "长" * CODEX_THREAD_TITLE_MAX_LENGTH

    def test_empty_sources_should_use_stable_creation_time_title(self) -> None:
        decision = CodexThreadTitlePolicy().resolve(
            created_at=self.CREATED_AT,
            existing_title=" \n ",
            app_server_title="\x00",
            first_user_message=None,
        )

        assert decision.display_name == "新会话 · 2026-08-15 17:32"
        assert decision.source is CodexThreadTitleSource.NEW_CONVERSATION
