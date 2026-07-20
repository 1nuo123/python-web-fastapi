"""
快速开发骨架主路径回归测试。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from src.api.testing.test_app_factory import TestAppFactory
from src.application.dispatch_background_job_usecase import TaskDispatchCommand
from src.core.task_contract.task_handler_contract import TaskHandler
from src.core.task_contract.task_invocation_contract import TypedTaskInvocation
from src.infrastructure.task.task_registration_registry import RegisteredTaskBinding

AUTH_TOKEN_PATH = "/auth/token"
HEALTH_LIVE_PATH = "/health/live"
SYSTEM_INFO_PATH = "/system/info"
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer"
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin"
DEMO_JOB_KIND = "demo_task"


class FastSkeletonDemoTaskPayload(BaseModel):
    """
    快速骨架示例任务载荷。
    """

    model_config = ConfigDict(extra="forbid")

    kind: str = DEMO_JOB_KIND
    schema_version: str = "1.0"
    task_id: str = "fast-skeleton-path-task"


class FastSkeletonDemoTaskHandler(TaskHandler[FastSkeletonDemoTaskPayload]):
    """
    快速骨架示例任务处理器。
    """

    def handle(
        self,
        invocation: TypedTaskInvocation[FastSkeletonDemoTaskPayload],
    ) -> None:
        """
        处理示例任务。
        """

        _ = invocation
        return None


class TestFastDevelopmentSkeletonPath:
    """
    快速开发骨架主路径回归测试集合。
    """

    def test_app_should_keep_health_auth_business_and_task_dispatch_path(self) -> None:
        """
        验证健康、认证、业务后台边界与任务分发主链路可用。
        """

        app = TestAppFactory().create(
            task_bindings=[
                RegisteredTaskBinding(
                    job_kind=DEMO_JOB_KIND,
                    payload_model=FastSkeletonDemoTaskPayload,
                    handler=FastSkeletonDemoTaskHandler(),
                )
            ]
        )

        with TestClient(app) as client:
            health_response = client.get(HEALTH_LIVE_PATH)
            token_response = client.post(
                AUTH_TOKEN_PATH,
                json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
            )
            access_token = token_response.json()["data"]["access_token"]
            system_response = client.get(
                SYSTEM_INFO_PATH,
                headers={AUTHORIZATION_HEADER: f"{BEARER_PREFIX} {access_token}"},
            )
            dispatch_result = app.state.container.dispatch_background_job_usecase.execute(
                TaskDispatchCommand(payload=FastSkeletonDemoTaskPayload())
            )

        assert health_response.status_code == 200
        assert token_response.status_code == 200
        assert system_response.status_code == 404
        assert dispatch_result.dispatched is True
        assert dispatch_result.queue_name == DEMO_JOB_KIND
