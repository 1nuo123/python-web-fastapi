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


class CodexAgentDeploymentProfile(StrEnum):
    """控制面应唤起的 Windows Agent 独立安装 profile。

    该 profile 是服务端发布边界的一部分。开发控制面只能返回开发协议 URI，
    避免本地验收意外唤起生产 Agent 或混用其设备身份。
    """

    PRODUCTION = "production"
    DEVELOPMENT = "development"

    @property
    def enrollment_uri_scheme(self) -> str:
        """返回与当前安装 profile 一一对应的注册 URI scheme。"""

        if self is CodexAgentDeploymentProfile.DEVELOPMENT:
            return "codexremote-dev"
        return "codexremote"


class CodexRuntimeSettings(BaseModel):
    """长期连接、容量和安全边界的重启生效配置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    agent_deployment_profile: CodexAgentDeploymentProfile = CodexAgentDeploymentProfile.PRODUCTION
    agent_heartbeat_seconds: int = Field(ge=15, le=15)
    agent_offline_after_seconds: int = Field(gt=0)
    agent_rpc_ack_timeout_seconds: int = Field(gt=0)
    agent_reconnect_min_seconds: int = Field(gt=0)
    agent_reconnect_max_seconds: int = Field(gt=0)
    max_connected_agents: int = Field(gt=0)
    max_hosts_per_user: int = Field(gt=0, le=100)
    max_workspaces_per_host: int = Field(gt=0, le=1_000)
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
    turn_runtime_lease_ttl_seconds: int = Field(ge=60, le=60)
    turn_runtime_watchdog_seconds: int = Field(ge=15, le=15)
    turn_runtime_stalled_after_seconds: int = Field(ge=90, le=90)
    instance_control_stream_ttl_seconds: int = Field(gt=0, le=86_400)
    instance_control_stream_max_events: int = Field(gt=0, le=100_000)
    instance_control_read_limit: int = Field(gt=0, le=1_000)
    device_authorization_ttl_seconds: int = Field(gt=0, le=1_800)
    enrollment_intent_ttl_seconds: int = Field(gt=0, le=900)
    device_authorization_poll_interval_seconds: int = Field(gt=0, le=60)
    device_authorization_create_attempts: int = Field(gt=0, le=20)
    device_authorization_max_poll_attempts: int = Field(gt=0, le=1_000)
    device_challenge_ttl_seconds: int = Field(gt=0, le=300)
    device_key_rotation_grace_seconds: int = Field(ge=0, le=86_400)
    device_security_rate_limit: int = Field(gt=0, le=10_000)
    device_security_rate_window_seconds: int = Field(gt=0, le=86_400)
    device_security_block_seconds: int = Field(gt=0, le=86_400)
    device_security_ip_block_ttl_seconds: int = Field(gt=0, le=604_800)
    client_diagnostic_error_collection_enabled: bool = False
    client_diagnostic_performance_collection_enabled: bool = False
    client_diagnostic_performance_sample_rate: float = Field(default=0.1, ge=0, le=1)
    client_diagnostic_cleanup_interval_seconds: int = Field(default=3600, ge=60, le=86_400)
    client_diagnostic_error_retention_days: int = Field(default=14, ge=1, le=14)
    client_diagnostic_performance_retention_days: int = Field(default=30, ge=1, le=30)
    codex_scroll_controller_v2: bool = False
    codex_realtime_batch_v2: bool = False
    codex_authority_recovery_v2: bool = False
    allow_legacy_agent_bearer: bool = False
    allow_experimental_app_server_api: bool = False
    allowed_codex_versions: list[str] = Field(min_length=1)
    agent_release_version: str = Field(min_length=1, max_length=64)
    agent_release_download_url: str = Field(min_length=1, max_length=2_048)
    agent_release_manifest_url: str = Field(min_length=1, max_length=2_048)
    agent_release_minimum_security_version: str = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_runtime_boundaries(self) -> CodexRuntimeSettings:
        """校验关联时间边界和版本白名单。"""

        if self.agent_offline_after_seconds <= self.agent_heartbeat_seconds:
            raise ValueError("agent_offline_after_seconds 必须大于 agent_heartbeat_seconds。")
        if self.agent_reconnect_max_seconds < self.agent_reconnect_min_seconds:
            raise ValueError("agent_reconnect_max_seconds 不得小于 agent_reconnect_min_seconds。")
        if any(version.strip() == "" for version in self.allowed_codex_versions):
            raise ValueError("allowed_codex_versions 不允许空字符串。")
        if not self.agent_release_download_url.startswith("https://"):
            raise ValueError("Agent下载地址必须使用HTTPS。")
        if not self.agent_release_manifest_url.startswith("https://"):
            raise ValueError("Agent发布清单地址必须使用HTTPS。")
        if self.device_authorization_poll_interval_seconds >= self.device_authorization_ttl_seconds:
            raise ValueError("设备授权轮询间隔必须小于授权有效期。")
        if self.enrollment_intent_ttl_seconds > self.device_authorization_ttl_seconds:
            raise ValueError("注册意图有效期不得大于设备授权有效期。")
        if self.device_challenge_ttl_seconds >= self.device_authorization_ttl_seconds:
            raise ValueError("设备挑战有效期必须小于设备授权有效期。")
        if self.command_outbox_retry_seconds >= self.operation_idempotency_ttl_seconds:
            raise ValueError("命令outbox重试间隔必须小于幂等保留期。")
        if self.turn_runtime_stalled_after_seconds <= self.turn_runtime_lease_ttl_seconds:
            raise ValueError("turn运行态停滞阈值必须大于租约有效期。")
        return self
