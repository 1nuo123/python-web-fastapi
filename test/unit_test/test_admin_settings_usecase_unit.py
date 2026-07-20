"""
管理员配置热更新用例单元测试模块。
"""

from __future__ import annotations

from src.application.admin.apply_admin_settings_reload_usecase import (
    ApplyAdminSettingsReloadUsecase,
)
from src.application.admin.build_admin_settings_reload_candidate_usecase import (
    BuildAdminSettingsReloadCandidateUsecase,
)
from src.application.ports.admin_settings_reload_port import (
    AdminSettingsReloadCandidateSnapshot,
    AdminSettingsReloadResultSnapshot,
)

TEST_CANDIDATE_VERSION = "candidate001"
TEST_DIGEST = "0123456789abcdef"
TEST_ACTIVE_SNAPSHOT_ID = "snapshot001"
TEST_REJECT_REASON = "以下配置必须重启后生效：runtime.database.url。"
TEST_ROLLBACK_REASON = "reload_failed:资源切换失败"
TEST_RESTORED_RESOURCE = "shared_http_client"


class SettingsReloadCoordinatorStub:
    """
    配置热更新端口测试替身。
    """

    def __init__(
        self,
        reload_result: AdminSettingsReloadResultSnapshot | None = None,
    ) -> None:
        """
        初始化测试替身。
        """

        self.candidate_called = False
        self.reload_called = False
        self.reload_result = reload_result or AdminSettingsReloadResultSnapshot(
            success=True,
            rolled_back=False,
            reason=None,
            candidate_version=TEST_CANDIDATE_VERSION,
            restored_resources=[],
            active_snapshot_id=TEST_ACTIVE_SNAPSHOT_ID,
        )

    def build_admin_settings_reload_candidate(
        self,
    ) -> AdminSettingsReloadCandidateSnapshot:
        """
        构建候选配置。
        """

        self.candidate_called = True
        return AdminSettingsReloadCandidateSnapshot(
            candidate_version=TEST_CANDIDATE_VERSION,
            digest=TEST_DIGEST,
        )

    def apply_admin_settings_reload(self) -> AdminSettingsReloadResultSnapshot:
        """
        执行配置热更新。
        """

        self.reload_called = True
        return self.reload_result


class TestAdminSettingsUsecaseUnit:
    """
    管理员配置热更新用例单元测试集合。
    """

    def test_build_candidate_should_use_current_environment(self) -> None:
        """
        验证候选读取用例使用当前环境。
        """

        coordinator = SettingsReloadCoordinatorStub()
        candidate = BuildAdminSettingsReloadCandidateUsecase(
            admin_settings_reload_port=coordinator,
        ).execute()

        assert candidate.candidate_version == TEST_CANDIDATE_VERSION
        assert coordinator.candidate_called is True

    def test_apply_reload_should_return_success_result(self) -> None:
        """
        验证热更新用例返回成功结果。
        """

        coordinator = SettingsReloadCoordinatorStub()
        result = ApplyAdminSettingsReloadUsecase(
            admin_settings_reload_port=coordinator,
        ).execute()

        assert result.success is True
        assert result.rolled_back is False
        assert coordinator.reload_called is True

    def test_apply_reload_should_return_rejected_result(self) -> None:
        """
        验证热更新用例保留拒绝结果。
        """

        result = self._execute_reload_with_result(
            AdminSettingsReloadResultSnapshot(
                success=False,
                rolled_back=False,
                reason=TEST_REJECT_REASON,
                candidate_version=TEST_CANDIDATE_VERSION,
                restored_resources=[],
                active_snapshot_id=None,
            )
        )

        assert result.success is False
        assert result.rolled_back is False
        assert result.reason == TEST_REJECT_REASON

    def test_apply_reload_should_return_rollback_result(self) -> None:
        """
        验证热更新用例保留回滚结果。
        """

        result = self._execute_reload_with_result(
            AdminSettingsReloadResultSnapshot(
                success=False,
                rolled_back=True,
                reason=TEST_ROLLBACK_REASON,
                candidate_version=TEST_CANDIDATE_VERSION,
                restored_resources=[TEST_RESTORED_RESOURCE],
                active_snapshot_id=TEST_ACTIVE_SNAPSHOT_ID,
            )
        )

        assert result.success is False
        assert result.rolled_back is True
        assert result.restored_resources == [TEST_RESTORED_RESOURCE]

    def _execute_reload_with_result(
        self,
        reload_result: AdminSettingsReloadResultSnapshot,
    ) -> AdminSettingsReloadResultSnapshot:
        """
        使用指定结果执行热更新用例。
        """

        return ApplyAdminSettingsReloadUsecase(
            admin_settings_reload_port=SettingsReloadCoordinatorStub(reload_result),
        ).execute()
