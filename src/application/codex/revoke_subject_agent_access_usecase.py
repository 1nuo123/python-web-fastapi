"""按用户主体立即撤销 Codex Agent 在线访问。"""

from __future__ import annotations

import asyncio
from uuid import UUID

from src.application.ports.codex_agent_revocation_signal_port import (
    CodexAgentRevocationSignalPort,
)
from src.application.ports.codex_control_port import CodexControlPort


class RevokeCodexSubjectAgentAccessUsecase:
    """停用用户后提升其所有活动主机撤销代次并关闭在线连接。"""

    def __init__(
        self,
        *,
        control_port: CodexControlPort,
        revocation_signal: CodexAgentRevocationSignalPort,
    ) -> None:
        self._control_port = control_port
        self._revocation_signal = revocation_signal

    async def execute(self, *, subject_id: str) -> tuple[UUID, ...]:
        """读取主体活动主机，并并发发送可跨实例传播的撤销信号。"""

        host_ids = await asyncio.to_thread(self._list_active_host_ids, subject_id)
        if host_ids:
            await asyncio.gather(*(self._revocation_signal.revoke(host_id) for host_id in host_ids))
        return host_ids

    def _list_active_host_ids(self, subject_id: str) -> tuple[UUID, ...]:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            hosts = self._control_port.create_codex_host_repository(
                unit_of_work.get_session()
            ).list_by_owner(subject_id)
            unit_of_work.commit()
            return tuple(host.host_id for host in hosts if host.revoked_at is None)
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()
