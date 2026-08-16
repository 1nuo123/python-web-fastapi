"""测试资源隔离策略单元测试。"""

from __future__ import annotations

import pytest

from test import conftest
from test.integration_database_fixture import (
    DATABASE_RESET_REFUSED_MESSAGE,
    TEST_DATABASE_NAME_SUFFIX,
    DatabaseResetPolicy,
    IntegrationDatabaseHarness,
)

TEST_DATABASE_NAME = f"fastapi_web_skeleton_dev{TEST_DATABASE_NAME_SUFFIX}"
NON_TEST_DATABASE_NAME = "fastapi_web_skeleton_dev"
TEST_DATABASE_URL_ENV_NAME = "TEST_DATABASE_URL"
EXPLICIT_TEST_DATABASE_URL = "postgresql+psycopg://postgres:test@127.0.0.1:55432/explicit_test"


class TestTestDatabaseIsolationUnit:
    """验证离线防护和集成数据库安全边界。"""

    def test_reset_policy_when_test_database_should_allow_reset(self) -> None:
        """验证测试库后缀允许执行重置。"""

        DatabaseResetPolicy(
            reset_enabled=True,
            database_name=TEST_DATABASE_NAME,
        ).assert_allowed()

    def test_reset_policy_when_non_test_database_should_reject_reset(self) -> None:
        """验证非测试库即使显式开启也必须拒绝重置。"""

        with pytest.raises(RuntimeError, match=DATABASE_RESET_REFUSED_MESSAGE):
            DatabaseResetPolicy(
                reset_enabled=True,
                database_name=NON_TEST_DATABASE_NAME,
            ).assert_allowed()

    def test_database_url_when_explicit_value_exists_should_use_it(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证显式测试连接串优先于派生默认值。"""

        monkeypatch.setenv(TEST_DATABASE_URL_ENV_NAME, EXPLICIT_TEST_DATABASE_URL)

        assert IntegrationDatabaseHarness.build_database_url() == EXPLICIT_TEST_DATABASE_URL

    def test_offline_guard_when_connection_attempted_should_fail(self) -> None:
        """验证未声明外部资源时连接入口会给出明确拒绝。"""

        with pytest.raises(RuntimeError, match=conftest.OFFLINE_CONNECTION_BLOCKED_MESSAGE):
            conftest.OfflineExternalResourceGuard.reject()
