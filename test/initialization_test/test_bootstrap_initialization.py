"""
测试引导初始化测试模块。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.runtime_resource_contract import RuntimeResourceStatus
from src.domain.auth.auth_role_key import AuthRoleKey
from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.resource_mount.shared_resource_constants import (
    RESOURCE_CACHE,
    RESOURCE_DATABASE,
    RESOURCE_DISTRIBUTED_LOCK,
    RESOURCE_HTTP_CLIENT,
    RESOURCE_KEY_MANAGEMENT,
    RESOURCE_LOGGING,
    RESOURCE_TASK,
    RESOURCE_TASK_MESSAGE_TRANSPORT,
)
from src.infrastructure.testing.sqlite_test_engine_factory import SqliteTestEngineFactory

BOOTSTRAP_RESTART_DATABASE_FILENAME = "bootstrap_restart.sqlite3"


class TestBootstrapInitialization:
    """
    测试引导初始化测试集合，用于组织同一主题下的测试场景。
    """

    def test_app_create_should_prepare_container(self) -> None:
        """
        验证应用创建应准备容器。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        assert app.state.container is not None

    def test_app_startup_should_prepare_runtime_resources(self) -> None:
        """
        验证应用启动应准备运行时资源集合。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app):
            assert app.state.ready is True
            assert app.state.container.resource_mount.is_ready() is True

    def test_session_factory_should_create_and_close_session(self) -> None:
        """
        验证会话工厂应创建与关闭会话。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app):
            session = app.state.container.resource_mount.get_session_factory().create_session()
            try:
                assert session.is_active is True
            finally:
                session.close()

    def test_cache_and_task_dispatcher_should_be_available(self) -> None:
        """
        验证缓存与任务分发器应被可用。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app):
            assert app.state.container.resource_mount.get_cache_store() is not None
            assert app.state.container.resource_mount.get_cache_service() is not None
            assert app.state.container.resource_mount.get_task_dispatcher() is not None

    def test_startup_should_bootstrap_admin_identity(self) -> None:
        """
        验证应引导管理员身份。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                repository = resource_mount.create_auth_identity_repository(
                    unit_of_work.get_session()
                )
                auth_identity = repository.get_by_username("admin")
                assert auth_identity is not None
                assert auth_identity.subject_id == "user-admin"
                assert auth_identity.roles == ["admin"]
            finally:
                unit_of_work.dispose()

    def test_startup_should_prepare_public_registration_role(self) -> None:
        """验证启动期准备无授权 scope 的普通注册角色。"""

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                session = resource_mount._read_sqlalchemy_session(  # noqa: SLF001
                    unit_of_work.get_session()
                )
                role = (
                    session.query(AuthRoleOrmModel)
                    .filter_by(role_key=AuthRoleKey.REGISTERED_USER.value)
                    .one()
                )
                assert role.role_scopes == []
            finally:
                unit_of_work.dispose()

    def test_bootstrap_admin_should_keep_password_hash_stable_after_restart(
        self,
        tmp_path: Path,
    ) -> None:
        """
        验证引导管理员应保持密码哈希稳定之后重启。

        :returns: 无返回值。
        :rtype: None
        """

        database_engine_factory = SqliteTestEngineFactory(
            database_url=SqliteTestEngineFactory.build_file_database_url(
                tmp_path / BOOTSTRAP_RESTART_DATABASE_FILENAME
            )
        )
        app = TestAppFactory().create(database_engine_factory=database_engine_factory)
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                repository = resource_mount.create_auth_identity_repository(
                    unit_of_work.get_session()
                )
                auth_identity = repository.get_by_username("admin")
                original_password_hash = auth_identity.password_hash
            finally:
                unit_of_work.dispose()
        second_app = TestAppFactory().create(database_engine_factory=database_engine_factory)
        with TestClient(second_app):
            resource_mount = second_app.state.container.resource_mount
            unit_of_work = resource_mount.create_unit_of_work()
            try:
                repository = resource_mount.create_auth_identity_repository(
                    unit_of_work.get_session()
                )
                auth_identity = repository.get_by_username("admin")
                assert auth_identity.password_hash == original_password_hash
            finally:
                unit_of_work.dispose()

    def test_otel_when_disabled_should_use_no_op(self) -> None:
        """
        验证OpenTelemetry当禁用应用途无op。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        state = app.state.container.resource_mount.get_telemetry_bridge().get_state()
        assert state.no_op is True

    def test_app_shutdown_should_release_runtime_resources(self) -> None:
        """
        验证应用关闭应释放运行时资源。

        :returns: 无返回值。
        :rtype: None
        """

        app = TestAppFactory().create()
        resource_mount = app.state.container.resource_mount

        with TestClient(app):
            assert resource_mount.is_ready() is True

        states = {state.resource_name: state for state in resource_mount.get_runtime_states()}
        assert resource_mount.is_ready() is False
        assert states[RESOURCE_TASK].status == RuntimeResourceStatus.STOPPED
        assert states[RESOURCE_CACHE].status == RuntimeResourceStatus.STOPPED
        assert states[RESOURCE_DATABASE].status == RuntimeResourceStatus.STOPPED
        assert states[RESOURCE_HTTP_CLIENT].status == RuntimeResourceStatus.STOPPED
        assert states[RESOURCE_TASK_MESSAGE_TRANSPORT].status == RuntimeResourceStatus.STOPPED
        assert states[RESOURCE_LOGGING].status == RuntimeResourceStatus.STOPPED
        assert states[RESOURCE_DISTRIBUTED_LOCK].status == RuntimeResourceStatus.STOPPED
        assert states[RESOURCE_KEY_MANAGEMENT].status == RuntimeResourceStatus.STOPPED
        with pytest.raises(HttpFaultException):
            resource_mount.get_http_client()
        with pytest.raises(HttpFaultException):
            resource_mount.get_cache_store()
        with pytest.raises(HttpFaultException):
            resource_mount.get_structured_log_handler()
        with pytest.raises(HttpFaultException):
            resource_mount.get_distributed_lock_provider()
        with pytest.raises(HttpFaultException):
            resource_mount.get_key_management_service()
