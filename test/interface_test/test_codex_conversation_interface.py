"""Codex 会话列表与偏好接口契约测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.core.codex_contract.thread_contract import (
    CodexThreadStatus,
    CodexThreadTitleSource,
)
from src.infrastructure.persistence.orm_model.codex_host_orm_model import CodexHostOrmModel
from src.infrastructure.persistence.orm_model.codex_thread_index_orm_model import (
    CodexThreadIndexOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_workspace_orm_model import (
    CodexWorkspaceOrmModel,
)


class TestCodexConversationInterface:
    """验证会话列表、置顶、命令接受与参数边界。"""

    @pytest.mark.integration
    @pytest.mark.postgres
    @pytest.mark.docker
    @pytest.mark.usefixtures("integration_database")
    def test_conversation_endpoints_should_keep_contract_and_ownership_boundaries(
        self,
    ) -> None:
        app = TestAppFactory().create()
        host_id = uuid4()
        workspace_id = uuid4()
        thread_id = "interface-thread-1"
        now = datetime.now(UTC)
        with TestClient(app) as client:
            access_token = client.post(
                "/auth/token",
                json={"username": "admin", "password": "admin"},
            ).json()["data"]["access_token"]
            resource_mount = app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                session = unit_of_work.get_session()
                session.add(
                    CodexHostOrmModel(
                        host_id=host_id,
                        owner_subject_id="user-admin",
                        display_name="Interface host",
                        platform="windows",
                        status="offline",
                        capabilities={},
                        version=1,
                    )
                )
                unit_of_work.flush()
                session.add(
                    CodexWorkspaceOrmModel(
                        workspace_id=workspace_id,
                        host_id=host_id,
                        owner_subject_id="user-admin",
                        agent_workspace_key="interface-work",
                        display_name="Interface project",
                        default_branch="main",
                        worktree_policy={},
                        enabled=True,
                        version=1,
                    )
                )
                unit_of_work.flush()
                session.add(
                    CodexThreadIndexOrmModel(
                        thread_index_id=uuid4(),
                        host_id=host_id,
                        workspace_id=workspace_id,
                        owner_subject_id="user-admin",
                        upstream_thread_id=thread_id,
                        display_name="Interface conversation",
                        title_source=CodexThreadTitleSource.APP_SERVER.value,
                        status=CodexThreadStatus.IDLE.value,
                        archived=False,
                        is_pinned=False,
                        created_at=now,
                        recency_at=now,
                        updated_at=now,
                        last_synced_at=now,
                    )
                )
                unit_of_work.commit()
            finally:
                unit_of_work.dispose()

            headers = {
                "Authorization": f"Bearer {access_token}",
                "Idempotency-Key": "interface-conversation-1",
            }
            listed = client.get(
                f"/codex/hosts/{host_id}/threads?workspace_id={workspace_id}&limit=10",
                headers=headers,
            )
            pinned = client.patch(
                f"/codex/hosts/{host_id}/threads/{thread_id}/pin",
                headers=headers,
                json={"is_pinned": True},
            )
            renamed = client.patch(
                f"/codex/hosts/{host_id}/threads/{thread_id}/name",
                headers=headers,
                json={"display_name": "手工接口标题"},
            )
            archived = client.post(
                f"/codex/hosts/{host_id}/threads/{thread_id}/archive",
                headers=headers,
            )
            unarchived = client.post(
                f"/codex/hosts/{host_id}/threads/{thread_id}/unarchive",
                headers={**headers, "Idempotency-Key": "interface-conversation-2"},
            )
            invalid_limit = client.get(
                f"/codex/hosts/{host_id}/threads?limit=0",
                headers=headers,
            )

            cleanup_uow = resource_mount.create_unit_of_work()
            try:
                cleanup_session = cleanup_uow.get_session()
                cleanup_session.query(CodexThreadIndexOrmModel).filter_by(
                    host_id=host_id
                ).delete(synchronize_session=False)
                cleanup_session.query(CodexWorkspaceOrmModel).filter_by(
                    workspace_id=workspace_id
                ).delete(synchronize_session=False)
                cleanup_session.query(CodexHostOrmModel).filter_by(host_id=host_id).delete(
                    synchronize_session=False
                )
                cleanup_uow.commit()
            finally:
                cleanup_uow.dispose()

        assert listed.status_code == HTTPStatus.OK
        listed_thread = listed.json()["data"]["items"][0]
        assert listed_thread["display_name"] == "Interface conversation"
        assert datetime.fromisoformat(listed_thread["recency_at"]) == now
        assert listed.json()["data"]["next_cursor"] is None
        assert pinned.status_code == HTTPStatus.OK
        assert pinned.json()["data"]["is_pinned"] is True
        assert renamed.status_code == HTTPStatus.CONFLICT
        assert archived.status_code == HTTPStatus.CONFLICT
        assert unarchived.status_code == HTTPStatus.CONFLICT
        assert invalid_limit.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
