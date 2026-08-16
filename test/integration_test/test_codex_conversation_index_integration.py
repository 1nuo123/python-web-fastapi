"""Codex 会话索引稳定排序、搜索与键集分页集成测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.core.codex_contract.thread_contract import (
    CodexConversationListQuery,
    CodexThreadStatus,
    CodexThreadTitleSource,
)
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.persistence.orm_model.codex_host_orm_model import CodexHostOrmModel
from src.infrastructure.persistence.orm_model.codex_thread_index_orm_model import (
    CodexThreadIndexOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_workspace_orm_model import (
    CodexWorkspaceOrmModel,
)
from src.infrastructure.persistence.repository_impl.codex_repository_impl import (
    CodexThreadRepositoryImpl,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.docker,
    pytest.mark.usefixtures("integration_database"),
]


class TestCodexConversationIndexIntegration:
    """验证数据库真实排序、分页与所有权边界。"""

    def test_repository_should_apply_stable_order_and_bound_cursor_to_query(
        self,
        integration_database: str,
    ) -> None:
        engine = create_engine(integration_database)
        owner_subject_id = f"conversation-owner-{uuid4()}"
        other_subject_id = f"conversation-other-{uuid4()}"
        host_id = uuid4()
        workspace_id = uuid4()
        recency_at = datetime(2026, 8, 15, 10, 0, tzinfo=UTC)
        created_at = datetime(2026, 8, 15, 9, 0, tzinfo=UTC)
        thread_ids = (
            "thread-pinned",
            "thread-newer-created",
            "thread-c",
            "thread-b",
            "thread-a",
        )
        try:
            with Session(engine) as session:
                session.add_all(
                    [
                        AuthUserOrmModel(
                            subject_id=owner_subject_id,
                            username=owner_subject_id,
                            password_hash="test",
                            is_active=True,
                        ),
                        AuthUserOrmModel(
                            subject_id=other_subject_id,
                            username=other_subject_id,
                            password_hash="test",
                            is_active=True,
                        ),
                        CodexHostOrmModel(
                            host_id=host_id,
                            owner_subject_id=owner_subject_id,
                            display_name="Conversation host",
                            platform="windows",
                            status="offline",
                            capabilities={},
                            version=1,
                        ),
                        CodexWorkspaceOrmModel(
                            workspace_id=workspace_id,
                            host_id=host_id,
                            owner_subject_id=owner_subject_id,
                            agent_workspace_key="conversation-work",
                            display_name="Conversation Project",
                            default_branch="main",
                            worktree_policy={},
                            enabled=True,
                            version=1,
                        ),
                    ]
                )
                session.flush()
                session.add_all(
                    [
                        CodexThreadIndexOrmModel(
                            thread_index_id=uuid4(),
                            host_id=host_id,
                            workspace_id=workspace_id,
                            owner_subject_id=owner_subject_id,
                            upstream_thread_id=thread_id,
                            display_name=f"Conversation {thread_id}",
                            title_source=CodexThreadTitleSource.APP_SERVER.value,
                            status=CodexThreadStatus.IDLE.value,
                            archived=False,
                            is_pinned=thread_id == "thread-pinned",
                            created_at=(
                                created_at + timedelta(minutes=1)
                                if thread_id == "thread-newer-created"
                                else created_at
                            ),
                            recency_at=(
                                recency_at - timedelta(days=1)
                                if thread_id == "thread-pinned"
                                else recency_at
                            ),
                            updated_at=recency_at,
                            last_synced_at=recency_at + timedelta(hours=1),
                        )
                        for thread_id in thread_ids
                    ]
                )
                session.commit()

                repository = CodexThreadRepositoryImpl(session)
                first_page = repository.list_page_by_host_and_owner(
                    host_id,
                    owner_subject_id,
                    CodexConversationListQuery(limit=2),
                )
                assert [item.upstream_thread_id for item in first_page.items] == [
                    "thread-pinned",
                    "thread-newer-created",
                ]
                assert first_page.next_cursor is not None

                second_page = repository.list_page_by_host_and_owner(
                    host_id,
                    owner_subject_id,
                    CodexConversationListQuery(
                        limit=2,
                        cursor=first_page.next_cursor,
                    ),
                )
                assert [item.upstream_thread_id for item in second_page.items] == [
                    "thread-c",
                    "thread-b",
                ]
                assert second_page.next_cursor is not None

                final_page = repository.list_page_by_host_and_owner(
                    host_id,
                    owner_subject_id,
                    CodexConversationListQuery(
                        limit=2,
                        cursor=second_page.next_cursor,
                    ),
                )
                assert [item.upstream_thread_id for item in final_page.items] == ["thread-a"]
                assert final_page.next_cursor is None
                assert (
                    repository.list_page_by_host_and_owner(
                        host_id,
                        other_subject_id,
                        CodexConversationListQuery(),
                    ).items
                    == []
                )
                with pytest.raises(ValueError, match="游标与查询条件不匹配"):
                    repository.list_page_by_host_and_owner(
                        host_id,
                        owner_subject_id,
                        CodexConversationListQuery(
                            archived=True,
                            cursor=first_page.next_cursor,
                        ),
                    )
        finally:
            with Session(engine) as cleanup_session:
                cleanup_session.query(CodexThreadIndexOrmModel).filter_by(host_id=host_id).delete(
                    synchronize_session=False
                )
                cleanup_session.query(CodexWorkspaceOrmModel).filter_by(
                    workspace_id=workspace_id
                ).delete(synchronize_session=False)
                cleanup_session.query(CodexHostOrmModel).filter_by(host_id=host_id).delete(
                    synchronize_session=False
                )
                cleanup_session.query(AuthUserOrmModel).filter(
                    AuthUserOrmModel.subject_id.in_([owner_subject_id, other_subject_id])
                ).delete(synchronize_session=False)
                cleanup_session.commit()
            engine.dispose()
