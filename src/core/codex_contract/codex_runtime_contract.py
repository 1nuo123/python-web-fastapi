"""Codex 控制面运行时配置契约。"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CodexSecurityRateLimitOperation(StrEnum):
    """Codex 设备安全操作的封闭限流策略名。"""

    DEVICE_AUTHORIZATION_CREATE = "codex.device_authorization.create"
    DEVICE_AUTHORIZATION_POLL = "codex.device_authorization.poll"
    DEVICE_AUTHORIZATION_READ = "codex.device_authorization.read"
    DEVICE_AUTHORIZATION_DECIDE = "codex.device_authorization.decide"
    DEVICE_CHALLENGE_ISSUE = "codex.device_challenge.issue"
    DEVICE_CONNECTION_TICKET = "codex.device_connection.ticket"
    DEVICE_KEY_ROTATION = "codex.device_key.rotation"
    HOST_REVOKE = "codex.host.revoke"


class CodexRuntimeSettings(BaseModel):
    """长期连接、容量和安全边界的重启生效配置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    agent_heartbeat_seconds: int = Field(gt=0)
    agent_offline_after_seconds: int = Field(gt=0)
    agent_rpc_ack_timeout_seconds: int = Field(gt=0)
    agent_reconnect_min_seconds: int = Field(gt=0)
    agent_reconnect_max_seconds: int = Field(gt=0)
    max_connected_agents: int = Field(gt=0)
    max_active_turns_per_host: int = Field(gt=0)
    max_active_write_turns_per_workspace: int = Field(gt=0)
    agent_outgoing_queue_size: int = Field(gt=0)
    browser_event_queue_size: int = Field(gt=0)
    browser_event_replay_ttl_seconds: int = Field(gt=0, le=86_400)
    browser_event_replay_max_events: int = Field(gt=0, le=100_000)
    browser_replay_read_limit: int = Field(gt=0, le=1_000)
    agent_event_replay_buffer_size: int = Field(gt=0)
    max_agent_frame_bytes: int = Field(gt=0)
    max_browser_frame_bytes: int = Field(gt=0)
    realtime_ticket_ttl_seconds: int = Field(gt=0)
    pairing_code_ttl_seconds: int = Field(gt=0)
    step_up_grant_ttl_seconds: int = Field(gt=0)
    operation_idempotency_ttl_seconds: int = Field(gt=0)
    command_outbox_retry_seconds: int = Field(gt=0, le=300)
    command_outbox_scan_interval_seconds: int = Field(gt=0, le=300)
    command_outbox_batch_size: int = Field(gt=0, le=1_000)
    command_outbox_completed_retention_seconds: int = Field(gt=0, le=2_592_000)
    instance_control_stream_ttl_seconds: int = Field(gt=0, le=86_400)
    instance_control_stream_max_events: int = Field(gt=0, le=100_000)
    instance_control_read_limit: int = Field(gt=0, le=1_000)
    device_authorization_ttl_seconds: int = Field(gt=0, le=1_800)
    device_authorization_poll_interval_seconds: int = Field(gt=0, le=60)
    device_authorization_create_attempts: int = Field(gt=0, le=20)
    device_authorization_max_poll_attempts: int = Field(gt=0, le=1_000)
    device_challenge_ttl_seconds: int = Field(gt=0, le=300)
    device_key_rotation_grace_seconds: int = Field(ge=0, le=86_400)
    device_security_rate_limit: int = Field(gt=0, le=10_000)
    device_security_rate_window_seconds: int = Field(gt=0, le=86_400)
    device_security_block_seconds: int = Field(gt=0, le=86_400)
    device_security_ip_block_ttl_seconds: int = Field(gt=0, le=604_800)
    allow_legacy_agent_bearer: bool = False
    allow_experimental_app_server_api: bool = False
    allowed_codex_versions: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_runtime_boundaries(self) -> CodexRuntimeSettings:
        """校验关联时间边界和版本白名单。"""

        if self.agent_offline_after_seconds <= self.agent_heartbeat_seconds:
            raise ValueError("agent_offline_after_seconds 必须大于 agent_heartbeat_seconds。")
        if self.agent_reconnect_max_seconds < self.agent_reconnect_min_seconds:
            raise ValueError("agent_reconnect_max_seconds 不得小于 agent_reconnect_min_seconds。")
        if any(version.strip() == "" for version in self.allowed_codex_versions):
            raise ValueError("allowed_codex_versions 不允许空字符串。")
        if self.device_authorization_poll_interval_seconds >= self.device_authorization_ttl_seconds:
            raise ValueError("设备授权轮询间隔必须小于授权有效期。")
        if self.device_challenge_ttl_seconds >= self.device_authorization_ttl_seconds:
            raise ValueError("设备挑战有效期必须小于设备授权有效期。")
        if self.command_outbox_retry_seconds >= self.operation_idempotency_ttl_seconds:
            raise ValueError("命令outbox重试间隔必须小于幂等保留期。")
        return self
