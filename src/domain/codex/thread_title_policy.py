"""Codex 会话标题优先级与有界归一化策略。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from src.core.codex_contract.thread_contract import (
    CODEX_THREAD_TITLE_MAX_LENGTH,
    CodexThreadTitleSource,
)

CODEX_NEW_CONVERSATION_TITLE_PREFIX: Final = "新会话 · "
CODEX_NEW_CONVERSATION_TIME_FORMAT: Final = "%Y-%m-%d %H:%M"
CODEX_TITLE_WHITESPACE_PATTERN: Final = re.compile(r"\s+")
CODEX_TITLE_CONTROL_PATTERN: Final = re.compile(r"[\x00-\x1f\x7f]+")


@dataclass(frozen=True, slots=True)
class CodexThreadTitleDecision:
    """一次标题合并后的权威标题与来源。"""

    display_name: str
    source: CodexThreadTitleSource


class CodexThreadTitlePolicy:
    """按固定优先级选择并归一化会话标题。"""

    def resolve(
        self,
        *,
        created_at: datetime,
        existing_title: str | None = None,
        existing_source: CodexThreadTitleSource | None = None,
        app_server_title: str | None = None,
        first_user_message: str | None = None,
    ) -> CodexThreadTitleDecision:
        """返回 ``manual > app_server > first_user_message > new_conversation`` 结果。"""

        if existing_source is CodexThreadTitleSource.MANUAL:
            normalized_existing = self.normalize(existing_title)
            if normalized_existing is not None:
                return CodexThreadTitleDecision(
                    display_name=normalized_existing,
                    source=CodexThreadTitleSource.MANUAL,
                )
        normalized_app_server = self.normalize(app_server_title)
        if normalized_app_server is not None:
            return CodexThreadTitleDecision(
                display_name=normalized_app_server,
                source=CodexThreadTitleSource.APP_SERVER,
            )
        normalized_message = self.normalize(first_user_message)
        if normalized_message is not None:
            return CodexThreadTitleDecision(
                display_name=normalized_message,
                source=CodexThreadTitleSource.FIRST_USER_MESSAGE,
            )
        return CodexThreadTitleDecision(
            display_name=(
                f"{CODEX_NEW_CONVERSATION_TITLE_PREFIX}"
                f"{created_at.strftime(CODEX_NEW_CONVERSATION_TIME_FORMAT)}"
            ),
            source=CodexThreadTitleSource.NEW_CONVERSATION,
        )

    def normalize(self, value: str | None) -> str | None:
        """在词边界生成非空有界短标题。"""

        if value is None:
            return None
        without_controls = CODEX_TITLE_CONTROL_PATTERN.sub(" ", value)
        normalized = CODEX_TITLE_WHITESPACE_PATTERN.sub(" ", without_controls).strip()
        if not normalized:
            return None
        if len(normalized) <= CODEX_THREAD_TITLE_MAX_LENGTH:
            return normalized
        candidate = normalized[: CODEX_THREAD_TITLE_MAX_LENGTH + 1]
        boundary = candidate.rfind(" ", 0, CODEX_THREAD_TITLE_MAX_LENGTH + 1)
        if boundary > 0:
            candidate = candidate[:boundary]
        else:
            candidate = candidate[:CODEX_THREAD_TITLE_MAX_LENGTH]
        return candidate.rstrip()
