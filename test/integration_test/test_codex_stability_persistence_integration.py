"""Codex 主机并发更新与会话单调投影集成测试。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from typing import cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.application.codex.sync_agent_state_usecase import SyncCodexAgentStateUsecase
from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal
from src.core.codex_contract.agent_protocol_contract import CodexAgentCommandAck
from src.core.codex_contract.host_contract import (
    CodexHostDisconnectObservationDetail,
    CodexHostHeartbeatObservationDetail,
    CodexHostObservation,
    CodexHostObservationHeader,
    CodexHostObservationType,
)
from src.core.codex_contract.operation_contract import (
    CodexControlOperationSnapshot,
    CodexOperationProjection,
    CodexOperationProjectionHeader,
    CodexOperationProjectionKind,
    CodexTurnSubmissionProjectionDetail,
)
from src.core.codex_contract.product_command_contract import CodexProductCommandCode
from src.core.codex_contract.thread_contract import (
    CodexThreadStatus,
    CodexThreadTitleSource,
)
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession
from src.domain.codex.host_status import CodexOperationStatus
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.persistence.orm_model.codex_control_operation_orm_model import (
    CodexControlOperationOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_host_orm_model import CodexHostOrmModel
from src.infrastructure.persistence.orm_model.codex_thread_index_orm_model import (
    CodexThreadIndexOrmModel,
)
from src.infrastructure.persistence.orm_model.codex_workspace_orm_model import (
    CodexWorkspaceOrmModel,
)
from src.infrastructure.persistence.repository_impl.codex_repository_impl import (
    CodexCommandOutboxRepositoryImpl,
    CodexHostRepositoryImpl,
    CodexOperationRepositoryImpl,
    CodexThreadRepositoryImpl,
)
from src.infrastructure.persistence.sqlalchemy_session_factory import (
    SqlAlchemySessionFactory,
    SqlAlchemyUnitOfWork,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.docker,
    pytest.mark.usefixtures("integration_database"),
]

INITIAL_HOST_VERSION = 41
EXPECTED_RENAMED_HOST_VERSION = 42
EXPECTED_SECOND_RENAMED_HOST_VERSION = 43
OPERATION_REQUEST_DIGEST = "a" * 64
MAX_TEST_WORKSPACES_PER_HOST = 8


class CodexProjectionControlPort:
    """迟到 ACK 集成测试使用的最小控制面持久化端口。"""

    def __init__(self, session_factory: SqlAlchemySessionFactory) -> None:
        self._session_factory = session_factory

    def create_unit_of_work(self) -> SqlAlchemyUnitOfWork:
        """为每次状态收敛创建独立工作单元。"""

        return self._session_factory.create_unit_of_work()

    def create_codex_operation_repository(
        self,
        session: PersistenceSession,
    ) -> CodexOperationRepositoryImpl:
        """创建 operation 仓储。"""

        return CodexOperationRepositoryImpl(cast(Session, session))

    def create_codex_command_outbox_repository(
        self,
        session: PersistenceSession,
    ) -> CodexCommandOutboxRepositoryImpl:
        """创建命令 outbox 仓储。"""

        return CodexCommandOutboxRepositoryImpl(cast(Session, session))

    def create_codex_thread_repository(
        self,
        session: PersistenceSession,
    ) -> CodexThreadRepositoryImpl:
        """创建会话索引仓储。"""

        return CodexThreadRepositoryImpl(cast(Session, session))


class CodexStabilityPersistenceTestSupport:
    """封装并发测试使用的独立数据库会话。"""

    @classmethod
    def rename_host(
        cls,
        *,
        database_url: str,
        host_id: UUID,
        owner_subject_id: str,
        barrier: Barrier,
        updated_at: datetime,
    ) -> None:
        """等待并发起点后执行一次主机 CAS 重命名。"""

        engine = create_engine(database_url)
        try:
            with Session(engine) as session:
                barrier.wait()
                renamed = CodexHostRepositoryImpl(session).rename_if_version(
                    host_id=host_id,
                    owner_subject_id=owner_subject_id,
                    expected_version=INITIAL_HOST_VERSION,
                    display_name="并发重命名电脑",
                    updated_at=updated_at,
                )
                assert renamed is not None
                session.commit()
        finally:
            engine.dispose()

    @classmethod
    def apply_heartbeat(
        cls,
        *,
        database_url: str,
        host_id: UUID,
        owner_subject_id: str,
        barrier: Barrier,
        observed_at: datetime,
    ) -> None:
        """等待并发起点后字段级写入一次心跳观测。"""

        engine = create_engine(database_url)
        try:
            with Session(engine) as session:
                barrier.wait()
                observed = CodexHostRepositoryImpl(session).apply_observation(
                    CodexHostObservation(
                        header=CodexHostObservationHeader(
                            detail_kind=CodexHostObservationType.HEARTBEAT,
                            host_id=host_id,
                            owner_subject_id=owner_subject_id,
                            observed_at=observed_at,
                        ),
                        detail=CodexHostHeartbeatObservationDetail(
                            app_server_instance_id="app-server-current",
                        ),
                    )
                )
                assert observed is not None
                session.commit()
        finally:
            engine.dispose()


class TestCodexStabilityPersistenceIntegration:
    """验证数据库 CAS、连接代次与会话单调投影。"""

    def test_host_repository_when_heartbeat_and_rename_overlap_should_preserve_configuration(
        self,
        integration_database: str,
    ) -> None:
        """心跳不得增长版本或覆盖与其并发提交的电脑名称。"""

        engine = create_engine(integration_database)
        owner_subject_id = f"codex-stability-owner-{uuid4()}"
        host_id = uuid4()
        initial_at = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
        heartbeat_at = initial_at + timedelta(minutes=1)
        rename_at = initial_at + timedelta(minutes=2)
        barrier = Barrier(2)
        try:
            with Session(engine) as session:
                session.add(
                    AuthUserOrmModel(
                        subject_id=owner_subject_id,
                        username=owner_subject_id,
                        password_hash="test",
                        is_active=True,
                    )
                )
                session.flush()
                session.add(
                    CodexHostOrmModel(
                        host_id=host_id,
                        owner_subject_id=owner_subject_id,
                        display_name="原电脑名称",
                        platform="windows",
                        status="offline",
                        capabilities={},
                        last_seen_at=initial_at,
                        created_at=initial_at,
                        updated_at=initial_at,
                        version=INITIAL_HOST_VERSION,
                    )
                )
                session.commit()

            with ThreadPoolExecutor(max_workers=2) as executor:
                rename_future = executor.submit(
                    CodexStabilityPersistenceTestSupport.rename_host,
                    database_url=integration_database,
                    host_id=host_id,
                    owner_subject_id=owner_subject_id,
                    barrier=barrier,
                    updated_at=rename_at,
                )
                heartbeat_future = executor.submit(
                    CodexStabilityPersistenceTestSupport.apply_heartbeat,
                    database_url=integration_database,
                    host_id=host_id,
                    owner_subject_id=owner_subject_id,
                    barrier=barrier,
                    observed_at=heartbeat_at,
                )
                rename_future.result()
                heartbeat_future.result()

            with Session(engine) as session:
                repository = CodexHostRepositoryImpl(session)
                host = repository.get_by_id_and_owner(host_id, owner_subject_id)
                assert host is not None
                assert host.display_name == "并发重命名电脑"
                assert host.version == EXPECTED_RENAMED_HOST_VERSION
                assert host.status == "online"
                assert host.last_seen_at == heartbeat_at

                stale = repository.rename_if_version(
                    host_id=host_id,
                    owner_subject_id=owner_subject_id,
                    expected_version=INITIAL_HOST_VERSION,
                    display_name="过期名称",
                    updated_at=rename_at + timedelta(minutes=1),
                )
                assert stale is None

                second = repository.rename_if_version(
                    host_id=host_id,
                    owner_subject_id=owner_subject_id,
                    expected_version=EXPECTED_RENAMED_HOST_VERSION,
                    display_name="最终电脑名称",
                    updated_at=rename_at + timedelta(minutes=2),
                )
                assert second is not None
                assert second.version == EXPECTED_SECOND_RENAMED_HOST_VERSION
                duplicate = repository.rename_if_version(
                    host_id=host_id,
                    owner_subject_id=owner_subject_id,
                    expected_version=EXPECTED_RENAMED_HOST_VERSION,
                    display_name="重复提交名称",
                    updated_at=rename_at + timedelta(minutes=3),
                )
                assert duplicate is None
                session.commit()
        finally:
            with Session(engine) as cleanup_session:
                cleanup_session.query(CodexHostOrmModel).filter_by(host_id=host_id).delete(
                    synchronize_session=False
                )
                cleanup_session.query(AuthUserOrmModel).filter_by(
                    subject_id=owner_subject_id
                ).delete(synchronize_session=False)
                cleanup_session.commit()
            engine.dispose()

    def test_host_repository_when_old_connection_disconnects_should_keep_new_connection_online(
        self,
        integration_database: str,
    ) -> None:
        """旧代次断连不得覆盖新代次心跳，当前代次断连仍可离线。"""

        engine = create_engine(integration_database)
        owner_subject_id = f"codex-disconnect-owner-{uuid4()}"
        host_id = uuid4()
        old_connection_at = datetime(2026, 8, 16, 9, 0, tzinfo=UTC)
        new_heartbeat_at = old_connection_at + timedelta(minutes=5)
        try:
            with Session(engine) as session:
                session.add(
                    AuthUserOrmModel(
                        subject_id=owner_subject_id,
                        username=owner_subject_id,
                        password_hash="test",
                        is_active=True,
                    )
                )
                session.flush()
                session.add(
                    CodexHostOrmModel(
                        host_id=host_id,
                        owner_subject_id=owner_subject_id,
                        display_name="连接代次电脑",
                        platform="windows",
                        status="online",
                        capabilities={},
                        last_seen_at=new_heartbeat_at,
                        created_at=old_connection_at,
                        updated_at=old_connection_at,
                        version=INITIAL_HOST_VERSION,
                    )
                )
                session.commit()

                repository = CodexHostRepositoryImpl(session)
                old_disconnect = repository.apply_observation(
                    CodexHostObservation(
                        header=CodexHostObservationHeader(
                            detail_kind=CodexHostObservationType.DISCONNECT,
                            host_id=host_id,
                            owner_subject_id=owner_subject_id,
                            observed_at=new_heartbeat_at + timedelta(minutes=1),
                        ),
                        detail=CodexHostDisconnectObservationDetail(
                            connection_started_at=old_connection_at,
                        ),
                    )
                )
                assert old_disconnect is None
                current = repository.get_by_id_and_owner(host_id, owner_subject_id)
                assert current is not None
                assert current.status == "online"
                assert current.version == INITIAL_HOST_VERSION

                current_disconnect = repository.apply_observation(
                    CodexHostObservation(
                        header=CodexHostObservationHeader(
                            detail_kind=CodexHostObservationType.DISCONNECT,
                            host_id=host_id,
                            owner_subject_id=owner_subject_id,
                            observed_at=new_heartbeat_at + timedelta(minutes=2),
                        ),
                        detail=CodexHostDisconnectObservationDetail(
                            connection_started_at=new_heartbeat_at,
                        ),
                    )
                )
                assert current_disconnect is not None
                assert current_disconnect.status == "offline"
                assert current_disconnect.version == INITIAL_HOST_VERSION
                session.commit()
        finally:
            with Session(engine) as cleanup_session:
                cleanup_session.query(CodexHostOrmModel).filter_by(host_id=host_id).delete(
                    synchronize_session=False
                )
                cleanup_session.query(AuthUserOrmModel).filter_by(
                    subject_id=owner_subject_id
                ).delete(synchronize_session=False)
                cleanup_session.commit()
            engine.dispose()

    def test_thread_repository_when_events_reorder_should_keep_activity_and_title_monotonic(
        self,
        integration_database: str,
    ) -> None:
        """乱序事件不得倒退活动时间或覆盖更高优先级标题。"""

        engine = create_engine(integration_database)
        owner_subject_id = f"codex-thread-owner-{uuid4()}"
        host_id = uuid4()
        workspace_id = uuid4()
        thread_index_id = uuid4()
        thread_id = "codex-stability-thread"
        created_at = datetime(2026, 8, 16, 10, 0, tzinfo=UTC)
        latest_activity_at = created_at + timedelta(minutes=10)
        try:
            with Session(engine) as session:
                session.add(
                    AuthUserOrmModel(
                        subject_id=owner_subject_id,
                        username=owner_subject_id,
                        password_hash="test",
                        is_active=True,
                    )
                )
                session.flush()
                session.add(
                    CodexHostOrmModel(
                        host_id=host_id,
                        owner_subject_id=owner_subject_id,
                        display_name="会话投影电脑",
                        platform="windows",
                        status="online",
                        capabilities={},
                        version=INITIAL_HOST_VERSION,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
                session.flush()
                session.add(
                    CodexWorkspaceOrmModel(
                        workspace_id=workspace_id,
                        host_id=host_id,
                        owner_subject_id=owner_subject_id,
                        agent_workspace_key="stability-workspace",
                        display_name="稳定性项目",
                        worktree_policy={},
                        enabled=True,
                        version=1,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
                session.flush()
                session.add(
                    CodexThreadIndexOrmModel(
                        thread_index_id=thread_index_id,
                        host_id=host_id,
                        workspace_id=workspace_id,
                        owner_subject_id=owner_subject_id,
                        upstream_thread_id=thread_id,
                        display_name="新会话",
                        title_source=CodexThreadTitleSource.NEW_CONVERSATION.value,
                        status=CodexThreadStatus.IDLE.value,
                        archived=False,
                        is_pinned=False,
                        created_at=created_at,
                        recency_at=created_at,
                        updated_at=created_at,
                        last_synced_at=created_at + timedelta(hours=1),
                    )
                )
                session.commit()

                repository = CodexThreadRepositoryImpl(session)
                repository.advance_activity(
                    host_id=host_id,
                    upstream_thread_id=thread_id,
                    owner_subject_id=owner_subject_id,
                    occurred_at=latest_activity_at,
                )
                repository.advance_activity(
                    host_id=host_id,
                    upstream_thread_id=thread_id,
                    owner_subject_id=owner_subject_id,
                    occurred_at=created_at + timedelta(minutes=5),
                )
                repository.promote_title(
                    host_id=host_id,
                    upstream_thread_id=thread_id,
                    owner_subject_id=owner_subject_id,
                    display_name="首条消息标题",
                    source=CodexThreadTitleSource.FIRST_USER_MESSAGE,
                    updated_at=created_at + timedelta(minutes=1),
                )
                repository.promote_title(
                    host_id=host_id,
                    upstream_thread_id=thread_id,
                    owner_subject_id=owner_subject_id,
                    display_name="App Server 标题",
                    source=CodexThreadTitleSource.APP_SERVER,
                    updated_at=created_at + timedelta(minutes=2),
                )
                repository.promote_title(
                    host_id=host_id,
                    upstream_thread_id=thread_id,
                    owner_subject_id=owner_subject_id,
                    display_name="手工标题",
                    source=CodexThreadTitleSource.MANUAL,
                    updated_at=created_at + timedelta(minutes=3),
                )
                repository.promote_title(
                    host_id=host_id,
                    upstream_thread_id=thread_id,
                    owner_subject_id=owner_subject_id,
                    display_name="迟到的 App Server 标题",
                    source=CodexThreadTitleSource.APP_SERVER,
                    updated_at=created_at + timedelta(minutes=4),
                )
                session.commit()

                thread = repository.get_by_upstream_id_and_owner(
                    host_id,
                    thread_id,
                    owner_subject_id,
                )
                assert thread is not None
                assert thread.recency_at == latest_activity_at
                assert thread.last_synced_at == created_at + timedelta(hours=1)
                assert thread.display_name == "手工标题"
                assert thread.title_source is CodexThreadTitleSource.MANUAL
        finally:
            with Session(engine) as cleanup_session:
                cleanup_session.query(CodexThreadIndexOrmModel).filter_by(
                    thread_index_id=thread_index_id
                ).delete(synchronize_session=False)
                cleanup_session.query(CodexWorkspaceOrmModel).filter_by(
                    workspace_id=workspace_id
                ).delete(synchronize_session=False)
                cleanup_session.query(CodexHostOrmModel).filter_by(host_id=host_id).delete(
                    synchronize_session=False
                )
                cleanup_session.query(AuthUserOrmModel).filter_by(
                    subject_id=owner_subject_id
                ).delete(synchronize_session=False)
                cleanup_session.commit()
            engine.dispose()

    def test_late_command_ack_should_apply_persisted_turn_projection_idempotently(
        self,
        integration_database: str,
    ) -> None:
        """迟到 ACK 与重放 ACK 都应从 operation 投影即时提升标题和活动时间。"""

        engine = create_engine(integration_database)
        session_factory = SqlAlchemySessionFactory(engine)
        owner_subject_id = f"codex-operation-owner-{uuid4()}"
        host_id = uuid4()
        workspace_id = uuid4()
        thread_index_id = uuid4()
        operation_id = uuid4()
        command_id = uuid4()
        thread_id = "codex-operation-projection-thread"
        created_at = datetime(2026, 8, 16, 11, 0, tzinfo=UTC)
        occurred_at = created_at + timedelta(minutes=3)
        try:
            with Session(engine) as session:
                session.add(
                    AuthUserOrmModel(
                        subject_id=owner_subject_id,
                        username=owner_subject_id,
                        password_hash="test",
                        is_active=True,
                    )
                )
                session.flush()
                session.add(
                    CodexHostOrmModel(
                        host_id=host_id,
                        owner_subject_id=owner_subject_id,
                        display_name="迟到确认电脑",
                        platform="windows",
                        status="online",
                        capabilities={},
                        version=INITIAL_HOST_VERSION,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
                session.flush()
                session.add(
                    CodexWorkspaceOrmModel(
                        workspace_id=workspace_id,
                        host_id=host_id,
                        owner_subject_id=owner_subject_id,
                        agent_workspace_key="operation-projection-workspace",
                        display_name="操作投影项目",
                        worktree_policy={},
                        enabled=True,
                        version=1,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
                session.flush()
                session.add(
                    CodexThreadIndexOrmModel(
                        thread_index_id=thread_index_id,
                        host_id=host_id,
                        workspace_id=workspace_id,
                        owner_subject_id=owner_subject_id,
                        upstream_thread_id=thread_id,
                        display_name="新会话 · 2026-08-16 11:00",
                        title_source=CodexThreadTitleSource.NEW_CONVERSATION.value,
                        status="idle",
                        archived=False,
                        is_pinned=False,
                        created_at=created_at,
                        recency_at=created_at,
                        updated_at=created_at,
                        last_synced_at=created_at,
                    )
                )
                session.flush()
                CodexOperationRepositoryImpl(session).add(
                    CodexControlOperationSnapshot(
                        operation_id=operation_id,
                        command_id=command_id,
                        actor_subject_id=owner_subject_id,
                        owner_subject_id=owner_subject_id,
                        host_id=host_id,
                        workspace_id=workspace_id,
                        thread_id=thread_id,
                        operation_type=CodexProductCommandCode.TURN_START.value,
                        idempotency_key="late-ack-projection",
                        request_digest=OPERATION_REQUEST_DIGEST,
                        status=CodexOperationStatus.DISPATCHED.value,
                        dispatch_attempt=1,
                        projection=CodexOperationProjection(
                            header=CodexOperationProjectionHeader(
                                detail_kind=(CodexOperationProjectionKind.TURN_SUBMISSION),
                            ),
                            detail=CodexTurnSubmissionProjectionDetail(
                                display_name="修复 Codex 会话标题",
                                occurred_at=occurred_at,
                            ),
                        ),
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
                session.commit()

            synchronizer = SyncCodexAgentStateUsecase(
                cast(CodexControlPort, CodexProjectionControlPort(session_factory)),
                max_workspaces_per_host=MAX_TEST_WORKSPACES_PER_HOST,
            )
            principal = AgentDevicePrincipal(
                credential_id="late-ack-credential",
                host_id=str(host_id),
                owner_subject_id=owner_subject_id,
            )
            ack = CodexAgentCommandAck(
                command_id=command_id,
                operation_id=operation_id,
                state="accepted",
                replayed=False,
            )

            first_projection = synchronizer.accept_command_ack(ack, principal)
            replay_projection = synchronizer.accept_command_ack(
                ack.model_copy(update={"replayed": True}),
                principal,
            )

            assert first_projection is not None
            assert replay_projection is not None
            assert first_projection.thread.display_name == "修复 Codex 会话标题"
            assert first_projection.thread.recency_at == occurred_at
            assert replay_projection.thread.display_name == "修复 Codex 会话标题"
            assert replay_projection.thread.recency_at == occurred_at
            with Session(engine) as session:
                operation = session.get(CodexControlOperationOrmModel, operation_id)
                thread = session.get(CodexThreadIndexOrmModel, thread_index_id)
                assert operation is not None
                assert operation.status == CodexOperationStatus.ACKNOWLEDGED.value
                assert operation.projection is not None
                assert set(operation.projection) == {"header", "detail"}
                assert thread is not None
                assert thread.display_name == "修复 Codex 会话标题"
                assert thread.title_source == CodexThreadTitleSource.FIRST_USER_MESSAGE.value
                assert thread.recency_at == occurred_at
        finally:
            with Session(engine) as cleanup_session:
                cleanup_session.query(CodexControlOperationOrmModel).filter_by(
                    operation_id=operation_id
                ).delete(synchronize_session=False)
                cleanup_session.query(CodexThreadIndexOrmModel).filter_by(
                    thread_index_id=thread_index_id
                ).delete(synchronize_session=False)
                cleanup_session.query(CodexWorkspaceOrmModel).filter_by(
                    workspace_id=workspace_id
                ).delete(synchronize_session=False)
                cleanup_session.query(CodexHostOrmModel).filter_by(host_id=host_id).delete(
                    synchronize_session=False
                )
                cleanup_session.query(AuthUserOrmModel).filter_by(
                    subject_id=owner_subject_id
                ).delete(synchronize_session=False)
                cleanup_session.commit()
            session_factory.dispose_engine()
