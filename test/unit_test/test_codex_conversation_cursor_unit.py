"""Codex 会话稳定排序键与键集游标单元测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from src.core.codex_contract.thread_contract import (
    CodexConversationCursor,
    CodexConversationCursorDetail,
    CodexConversationListQuery,
    CodexConversationSortKey,
)
from src.infrastructure.persistence.repository_impl.codex_repository_impl import (
    CodexThreadRepositoryImpl,
)


class StatementCaptureSession:
    """只捕获会话列表 SQL 的最小仓储测试替身。"""

    def __init__(self) -> None:
        self.statement = None

    def scalars(self, statement):
        self.statement = statement
        return self

    def all(self):
        return []


class TestCodexConversationCursorUnit:
    """验证游标完整承载稳定排序键并绑定查询身份。"""

    RECENCY_AT = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
    CREATED_AT = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)

    def test_cursor_should_round_trip_every_stable_sort_field(self) -> None:
        query = CodexConversationListQuery(
            archived=False,
            search_term=" Codex 会话 ",
            limit=25,
        )
        cursor = CodexConversationCursor(
            detail=CodexConversationCursorDetail(
                query_digest=query.build_identity_digest(),
                is_pinned=True,
                recency_at=self.RECENCY_AT,
                created_at=self.CREATED_AT,
                upstream_thread_id="thread-9",
            )
        )

        decoded = CodexConversationCursor.decode(cursor.encode())

        assert decoded.detail.query_digest == query.build_identity_digest()
        assert decoded.detail.is_pinned is True
        assert decoded.detail.recency_at == self.RECENCY_AT
        assert decoded.detail.created_at == self.CREATED_AT
        assert decoded.detail.upstream_thread_id == "thread-9"

    def test_query_digest_should_ignore_page_size_but_bind_filters(self) -> None:
        first = CodexConversationListQuery(
            archived=False,
            search_term="Codex",
            limit=25,
        )
        same_identity = CodexConversationListQuery(
            archived=False,
            search_term=" codex ",
            limit=100,
        )
        archived = CodexConversationListQuery(
            archived=True,
            search_term="Codex",
        )

        assert first.build_identity_digest() == same_identity.build_identity_digest()
        assert first.build_identity_digest() != archived.build_identity_digest()

    def test_invalid_cursor_should_raise_stable_chinese_error(self) -> None:
        with pytest.raises(ValueError, match="会话分页游标无效"):
            CodexConversationCursor.decode("not-a-valid-cursor")

    def test_sort_key_should_exclude_sync_time_by_contract(self) -> None:
        key = CodexConversationSortKey(
            is_pinned=False,
            recency_at=self.RECENCY_AT,
            created_at=self.CREATED_AT,
            upstream_thread_id="thread-1",
        )

        assert set(key.model_dump()) == {
            "is_pinned",
            "recency_at",
            "created_at",
            "upstream_thread_id",
        }

    def test_thread_search_matches_title_only(self) -> None:
        """会话搜索 SQL 只能包含 thread 标题谓词。"""

        session = StatementCaptureSession()
        CodexThreadRepositoryImpl(session).list_page_by_host_and_owner(
            host_id=uuid4(),
            owner_subject_id="owner-1",
            query=CodexConversationListQuery(search_term="release"),
        )

        assert session.statement is not None
        sql = str(
            session.statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": False},
            )
        )
        assert "display_name ILIKE" in sql
        assert "default_branch" not in sql
        assert "codex_workspace.display_name" not in sql
