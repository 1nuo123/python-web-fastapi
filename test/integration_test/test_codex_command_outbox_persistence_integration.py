"""Codex 操作与命令 outbox 的 PostgreSQL 原子持久化集成测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerCapabilityCode,
    AppServerCapabilityDetail,
)
from src.core.codex_contract.host_contract import (
    CodexHostCapabilities,
    CodexHostCompatibilityState,
)
from src.infrastructure.persistence.orm_model.codex_command_outbox_orm_model import (
    CodexCommandOutboxOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_control_operation_orm_model import (
    CodexControlOperationOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_host_orm_model import CodexHostOrmModel
from src.infrastructure.persistence.orm_model.codex_workspace_orm_model import (
    CodexWorkspaceOrmModel,
)
from test.fixtures.codex_device_authorization_test_support import (
    TEST_ADMIN_PASSWORD,
    TEST_ADMIN_USERNAME,
)

TEST_OWNER_SUBJECT_ID = "user-admin"
TEST_IDEMPOTENCY_KEY = "postgres-operation-outbox-order"
TEST_MODEL_ID = "gpt-5"


@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.docker
@pytest.mark.usefixtures("integration_database")
class TestCodexCommandOutboxPersistenceIntegration:
    """验证操作主记录必须先于依赖它的 outbox 在 PostgreSQL 中可见。"""

    def test_thread_start_should_persist_operation_before_outbox(self) -> None:
        app = TestAppFactory().create()
        host_id = uuid4()
        workspace_id = uuid4()
        with TestClient(app) as client:
            access_token = client.post(
                "/auth/token",
                json={
                    "username": TEST_ADMIN_USERNAME,
                    "password": TEST_ADMIN_PASSWORD,
                },
            ).json()["data"]["access_token"]
            resource_mount = app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                session = unit_of_work.get_session()
                session.add(
                    CodexHostOrmModel(
                        host_id=host_id,
                        owner_subject_id=TEST_OWNER_SUBJECT_ID,
                        display_name="PostgreSQL outbox host",
                        platform="windows",
                        status="online",
                        capabilities=CodexHostCapabilities(
                            items=(
                                AppServerCapabilityDetail(
                                    code=AppServerCapabilityCode.THREAD_START,
                                    version=1,
                                ),
                            ),
                            model_ids=(TEST_MODEL_ID,),
                        ).model_dump(mode="json"),
                        compatibility_state=CodexHostCompatibilityState.COMPATIBLE.value,
                        compatibility_reason_code="supported",
                        last_seen_at=datetime.now(UTC),
                        version=1,
                    )
                )
                session.add(
                    CodexWorkspaceOrmModel(
                        workspace_id=workspace_id,
                        host_id=host_id,
                        owner_subject_id=TEST_OWNER_SUBJECT_ID,
                        agent_workspace_key="work",
                        display_name="Work",
                        enabled=True,
                        version=1,
                    )
                )
                unit_of_work.commit()
            finally:
                unit_of_work.dispose()

            response = client.post(
                f"/codex/hosts/{host_id}/threads",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Idempotency-Key": TEST_IDEMPOTENCY_KEY,
                },
                json={
                    "workspace_id": str(workspace_id),
                    "execution": {
                        "model": TEST_MODEL_ID,
                        "reasoning_effort": None,
                        "sandbox_mode": "workspace-write",
                        "approval_policy": "untrusted",
                    },
                },
            )

            check_unit_of_work = resource_mount.create_unit_of_work()
            try:
                check_session = check_unit_of_work.get_session()
                operation = (
                    check_session.query(CodexControlOperationOrmModel)
                    .filter_by(idempotency_key=TEST_IDEMPOTENCY_KEY)
                    .one()
                )
                outbox = (
                    check_session.query(CodexCommandOutboxOrmModel)
                    .filter_by(operation_id=operation.operation_id)
                    .one()
                )
            finally:
                check_unit_of_work.dispose()

        assert response.status_code == HTTPStatus.ACCEPTED
        assert outbox.operation_id == operation.operation_id
        assert outbox.command_id == operation.command_id
