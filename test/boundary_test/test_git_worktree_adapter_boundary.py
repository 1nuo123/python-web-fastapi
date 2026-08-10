"""Git worktree 适配器边界测试。"""

from __future__ import annotations

from src.core.worktree_contract.worktree_contract import GitWorktreePolicy


class TestGitWorktreeAdapterBoundary:
    """验证策略上下界。"""

    def test_policy_whenAtMaximum_shouldAccept(self) -> None:
        policy = GitWorktreePolicy(
            max_active=128,
            retention_seconds=31_536_000,
            disk_watermark_percent=99,
        )
        assert policy.max_active == 128
        assert policy.retention_seconds == 31_536_000
        assert policy.disk_watermark_percent == 99

    def test_policy_whenBeyondMaximum_shouldReject(self) -> None:
        for field, value in (
            ("max_active", 129),
            ("retention_seconds", 31_536_001),
            ("disk_watermark_percent", 100),
        ):
            try:
                GitWorktreePolicy(**{field: value})
            except ValueError:
                continue
            raise AssertionError(f"策略字段 {field} 越界未被拒绝。")
