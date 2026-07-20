"""
测试日志初始化测试模块。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory


class TestLoggingInitialization:
    """
    测试日志初始化测试集合，用于组织同一主题下的测试场景。
    """

    def test_app_startup_should_prepare_logging_resources(self) -> None:
        """
        验证应用启动应准备日志资源。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            assert resource_mount.get_log_event_builder() is not None
            assert resource_mount.get_structured_log_handler() is not None

    def test_app_shutdown_should_release_logging_resources(self) -> None:
        """
        验证应用关闭应释放日志资源。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            assert resource_mount.get_structured_log_handler() is not None
        assert app.state.ready is False
