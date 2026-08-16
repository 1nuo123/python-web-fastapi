"""列出当前主体 Codex 主机用例。"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.host_contract import (
    CodexHostCollection,
    CodexHostCompatibilityState,
    CodexHostSnapshot,
)
from src.domain.codex.host_status import CodexHostStatus


class ListCodexHostsUsecase:
    """在应用层固定所有者过滤与工作单元生命周期。"""

    def __init__(self, control_port: CodexControlPort) -> None:
        self._control_port = control_port

    def execute(
        self,
        owner_subject_id: str,
        *,
        connected_host_ids: set[UUID] | None = None,
        offline_after_seconds: int | None = None,
        now: datetime | None = None,
    ) -> CodexHostCollection:
        """列出当前所有者可见主机。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_host_repository(unit_of_work.get_session())
            hosts = repository.list_by_owner(owner_subject_id)
            if connected_host_ids is not None and offline_after_seconds is not None:
                checked_at = now or datetime.now(UTC)
                hosts = [
                    self._overlay_runtime_status(
                        host,
                        connected_host_ids=connected_host_ids,
                        offline_after_seconds=offline_after_seconds,
                        checked_at=checked_at,
                    )
                    for host in hosts
                ]
            return CodexHostCollection(items=hosts)
        finally:
            unit_of_work.dispose()

    def _overlay_runtime_status(
        self,
        host: CodexHostSnapshot,
        *,
        connected_host_ids: set[UUID],
        offline_after_seconds: int,
        checked_at: datetime,
    ) -> CodexHostSnapshot:
        """用实时连接租约与心跳窗口修正可投递状态。"""

        if (
            host.status not in {CodexHostStatus.ONLINE.value, CodexHostStatus.OFFLINE.value}
            or host.revoked_at is not None
        ):
            return host
        last_seen_at = self._normalize_last_seen(host.last_seen_at)
        heartbeat_fresh = last_seen_at is not None and checked_at - last_seen_at <= timedelta(
            seconds=offline_after_seconds
        )
        target_status = (
            CodexHostStatus.ONLINE.value
            if host.host_id in connected_host_ids
            and heartbeat_fresh
            and host.compatibility.state
            in {
                CodexHostCompatibilityState.COMPATIBLE,
                CodexHostCompatibilityState.READ_ONLY,
            }
            else CodexHostStatus.OFFLINE.value
        )
        if host.status == target_status:
            return host
        return host.model_copy(update={"status": target_status})

    def overlay_runtime_status(
        self,
        collection: CodexHostCollection,
        *,
        present_host_ids: set[UUID],
        offline_after_seconds: int,
        now: datetime | None = None,
    ) -> CodexHostCollection:
        """用分布式 presence 覆盖 PostgreSQL 最后已知状态。"""

        checked_at = now or datetime.now(UTC)
        return CodexHostCollection(
            items=[
                self._overlay_runtime_status(
                    host,
                    connected_host_ids=present_host_ids,
                    offline_after_seconds=offline_after_seconds,
                    checked_at=checked_at,
                )
                for host in collection.items
            ]
        )

    def _normalize_last_seen(self, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class ListAllCodexHostsUsecase:
    """列出管理控制面可见的全部 Codex 主机。"""

    def __init__(self, control_port: CodexControlPort) -> None:
        self._control_port = control_port

    def execute(self) -> CodexHostCollection:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_host_repository(unit_of_work.get_session())
            return CodexHostCollection(items=repository.list_all())
        finally:
            unit_of_work.dispose()
