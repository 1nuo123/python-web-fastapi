"""Codex App Server schema 快照与方法目录公共契约。"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

APP_SERVER_SCHEMA_MANIFEST_KIND: Final = "app_server_schema_manifest"
APP_SERVER_SCHEMA_MANIFEST_SCHEMA_VERSION: Final = "1.0"
APP_SERVER_SCHEMA_SNAPSHOT_DETAIL_KIND: Final = "app_server_schema_snapshot"
SHA256_HEX_PATTERN: Final = r"^[0-9a-f]{64}$"


class AppServerSchemaReviewStatus(StrEnum):
    """schema 快照的审核状态。"""

    APPROVED = "approved"
    DEPRECATED = "deprecated"
    BLOCKED = "blocked"


class AppServerMethodEffect(StrEnum):
    """App Server 方法的副作用分类。"""

    READ = "read"
    MUTATION = "mutation"
    SERVER_REQUEST = "server_request"


class AppServerMethodName(StrEnum):
    """产品允许调用或回复的 App Server 方法。"""

    INITIALIZE = "initialize"
    MODEL_LIST = "model/list"
    ACCOUNT_READ = "account/read"
    CONFIG_READ = "config/read"
    CONFIG_REQUIREMENTS_READ = "configRequirements/read"
    THREAD_LIST = "thread/list"
    THREAD_READ = "thread/read"
    THREAD_TURNS_LIST = "thread/turns/list"
    THREAD_START = "thread/start"
    THREAD_RESUME = "thread/resume"
    THREAD_NAME_SET = "thread/name/set"
    THREAD_ARCHIVE = "thread/archive"
    THREAD_UNARCHIVE = "thread/unarchive"
    THREAD_DELETE = "thread/delete"
    THREAD_COMPACT_START = "thread/compact/start"
    TURN_START = "turn/start"
    TURN_STEER = "turn/steer"
    TURN_INTERRUPT = "turn/interrupt"
    COMMAND_APPROVAL = "item/commandExecution/requestApproval"
    FILE_CHANGE_APPROVAL = "item/fileChange/requestApproval"
    PERMISSIONS_APPROVAL = "item/permissions/requestApproval"


class AppServerNotificationName(StrEnum):
    """产品 mapper 当前支持的 App Server notification。"""

    ACCOUNT_RATE_LIMITS_UPDATED = "account/rateLimits/updated"
    THREAD_STARTED = "thread/started"
    THREAD_STATUS_CHANGED = "thread/status/changed"
    REMOTE_CONTROL_STATUS_CHANGED = "remoteControl/status/changed"
    MCP_SERVER_STARTUP_STATUS_UPDATED = "mcpServer/startupStatus/updated"
    THREAD_NAME_UPDATED = "thread/name/updated"
    THREAD_SETTINGS_UPDATED = "thread/settings/updated"
    THREAD_ARCHIVED = "thread/archived"
    THREAD_UNARCHIVED = "thread/unarchived"
    TURN_STARTED = "turn/started"
    TURN_COMPLETED = "turn/completed"
    ITEM_STARTED = "item/started"
    ITEM_COMPLETED = "item/completed"
    AGENT_MESSAGE_DELTA = "item/agentMessage/delta"
    COMMAND_OUTPUT_DELTA = "item/commandExecution/outputDelta"
    FILE_OUTPUT_DELTA = "item/fileChange/outputDelta"
    FILE_PATCH_UPDATED = "item/fileChange/patchUpdated"
    SERVER_REQUEST_RESOLVED = "serverRequest/resolved"
    TURN_PLAN_UPDATED = "turn/plan/updated"
    TURN_DIFF_UPDATED = "turn/diff/updated"
    WARNING = "warning"
    GUARDIAN_WARNING = "guardianWarning"
    CONFIG_WARNING = "configWarning"
    DEPRECATION_NOTICE = "deprecationNotice"
    ERROR = "error"


class AppServerCapabilityCode(StrEnum):
    """Agent 与控制面共同理解的封闭 capability 集合。"""

    MODEL_LIST = "model.list"
    THREAD_LIST = "thread.list"
    THREAD_READ = "thread.read"
    THREAD_START = "thread.start"
    THREAD_RESUME = "thread.resume"
    THREAD_NAME_SET = "thread.name_set"
    THREAD_ARCHIVE = "thread.archive"
    THREAD_UNARCHIVE = "thread.unarchive"
    THREAD_DELETE = "thread.delete"
    THREAD_COMPACT = "thread.compact"
    TURN_START = "turn.start"
    TURN_STEER = "turn.steer"
    TURN_INTERRUPT = "turn.interrupt"
    APPROVAL_COMMAND = "approval.command"
    APPROVAL_FILE_CHANGE = "approval.file_change"
    APPROVAL_PERMISSIONS = "approval.permissions"
    EVENT_REPLAY = "event.replay"
    SNAPSHOT_PAGINATION = "snapshot.pagination"


class AppServerSchemaManifestHeader(BaseModel):
    """schema manifest 公共头字段。

    :ivar kind: 契约种类。
    :vartype kind: Literal["app_server_schema_manifest"]
    :ivar schema_version: manifest 契约版本。
    :vartype schema_version: Literal["1.0"]
    :ivar codex_version: 精确 Codex CLI 版本，不允许通配符。
    :vartype codex_version: str
    :ivar review_status: 快照审核状态。
    :vartype review_status: AppServerSchemaReviewStatus
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["app_server_schema_manifest"] = APP_SERVER_SCHEMA_MANIFEST_KIND
    schema_version: Literal["1.0"] = APP_SERVER_SCHEMA_MANIFEST_SCHEMA_VERSION
    codex_version: str = Field(min_length=1, max_length=64)
    review_status: AppServerSchemaReviewStatus


class AppServerCapabilityDetail(BaseModel):
    """带版本的 Agent capability 明细。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: AppServerCapabilityCode
    version: int = Field(ge=1)


class AppServerMethodPolicy(BaseModel):
    """单个受支持方法的调用与重试策略。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    method: AppServerMethodName
    effect: AppServerMethodEffect
    idempotent: bool
    retry_on_overload: bool
    ordering_barrier: bool
    required_capability: AppServerCapabilityCode | None = None


class AppServerApprovalResponseRequirement(BaseModel):
    """审批响应 schema 的必填字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_filename: str = Field(min_length=1, max_length=256)
    required_fields: tuple[str, ...] = Field(min_length=1)


class AppServerSchemaSnapshotDetail(BaseModel):
    """已审核官方生成物的强类型扩展字段。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["app_server_schema_snapshot"] = APP_SERVER_SCHEMA_SNAPSHOT_DETAIL_KIND
    schema_version: Literal["1.0"] = APP_SERVER_SCHEMA_MANIFEST_SCHEMA_VERSION
    generated_at: datetime
    target_platform: str = Field(min_length=1, max_length=128)
    generator_commands: tuple[str, ...] = Field(min_length=1)
    json_schema_file_count: int = Field(gt=0)
    json_schema_bundle_sha256: str = Field(pattern=SHA256_HEX_PATTERN)
    typescript_file_count: int = Field(ge=0)
    typescript_bundle_sha256: str | None = Field(default=None, pattern=SHA256_HEX_PATTERN)
    approval_schema_digest_sha256: str = Field(pattern=SHA256_HEX_PATTERN)
    approval_server_request_methods: tuple[AppServerMethodName, ...] = Field(min_length=1)
    approval_response_requirements: tuple[AppServerApprovalResponseRequirement, ...] = Field(
        min_length=1
    )
    confirmation_response_expected: bool
    supported_agent_protocol_versions: tuple[str, ...] = Field(min_length=1)
    adapter_revision: Literal["1"] = "1"
    history_strategy: Literal["thread_read", "turns_page"] = "turns_page"
    allow_experimental_api: bool = True
    capabilities: tuple[AppServerCapabilityDetail, ...] = Field(min_length=1)
    method_catalog: tuple[AppServerMethodPolicy, ...] = Field(min_length=1)
    license_notice_path: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_unique_catalogs(self) -> AppServerSchemaSnapshotDetail:
        """拒绝重复 capability、方法和协议版本。"""

        capability_codes = [detail.code for detail in self.capabilities]
        method_names = [policy.method for policy in self.method_catalog]
        if len(capability_codes) != len(set(capability_codes)):
            raise ValueError("schema manifest capability 不允许重复。")
        if len(method_names) != len(set(method_names)):
            raise ValueError("schema manifest method catalog 不允许重复。")
        if len(self.supported_agent_protocol_versions) != len(
            set(self.supported_agent_protocol_versions)
        ):
            raise ValueError("schema manifest Agent protocol 版本不允许重复。")
        return self


AppServerSchemaManifestDetail = Annotated[
    AppServerSchemaSnapshotDetail,
    Field(discriminator="kind"),
]


class AppServerSchemaManifestEnvelope(BaseModel):
    """schema manifest 公共头与强类型扩展字段信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: AppServerSchemaManifestHeader
    detail: AppServerSchemaManifestDetail


class AppServerDefaultCatalog:
    """生成器与运行时共同使用的已审核方法/capability 目录。"""

    def build_capabilities(self) -> tuple[AppServerCapabilityDetail, ...]:
        """返回每项均为 v1 的当前 capability 集合。"""

        return tuple(
            AppServerCapabilityDetail(code=code, version=1) for code in AppServerCapabilityCode
        )

    def build_method_catalog(self) -> tuple[AppServerMethodPolicy, ...]:
        """返回产品允许调用或回复的方法策略。"""

        read_methods = (
            (AppServerMethodName.INITIALIZE, None),
            (AppServerMethodName.ACCOUNT_READ, None),
            (AppServerMethodName.CONFIG_READ, None),
            (AppServerMethodName.CONFIG_REQUIREMENTS_READ, None),
            (AppServerMethodName.MODEL_LIST, AppServerCapabilityCode.MODEL_LIST),
            (AppServerMethodName.THREAD_LIST, AppServerCapabilityCode.THREAD_LIST),
            (AppServerMethodName.THREAD_READ, AppServerCapabilityCode.THREAD_READ),
            (AppServerMethodName.THREAD_TURNS_LIST, None),
        )
        mutation_methods = (
            (AppServerMethodName.THREAD_START, AppServerCapabilityCode.THREAD_START, False),
            (AppServerMethodName.THREAD_RESUME, AppServerCapabilityCode.THREAD_RESUME, False),
            (AppServerMethodName.THREAD_NAME_SET, AppServerCapabilityCode.THREAD_NAME_SET, False),
            (AppServerMethodName.THREAD_ARCHIVE, AppServerCapabilityCode.THREAD_ARCHIVE, False),
            (
                AppServerMethodName.THREAD_UNARCHIVE,
                AppServerCapabilityCode.THREAD_UNARCHIVE,
                False,
            ),
            (AppServerMethodName.THREAD_DELETE, AppServerCapabilityCode.THREAD_DELETE, True),
            (
                AppServerMethodName.THREAD_COMPACT_START,
                AppServerCapabilityCode.THREAD_COMPACT,
                False,
            ),
            (AppServerMethodName.TURN_START, AppServerCapabilityCode.TURN_START, False),
            (AppServerMethodName.TURN_STEER, AppServerCapabilityCode.TURN_STEER, False),
            (AppServerMethodName.TURN_INTERRUPT, AppServerCapabilityCode.TURN_INTERRUPT, True),
        )
        server_requests = (
            (AppServerMethodName.COMMAND_APPROVAL, AppServerCapabilityCode.APPROVAL_COMMAND),
            (
                AppServerMethodName.FILE_CHANGE_APPROVAL,
                AppServerCapabilityCode.APPROVAL_FILE_CHANGE,
            ),
            (
                AppServerMethodName.PERMISSIONS_APPROVAL,
                AppServerCapabilityCode.APPROVAL_PERMISSIONS,
            ),
        )
        policies = [
            AppServerMethodPolicy(
                method=method,
                effect=AppServerMethodEffect.READ,
                idempotent=True,
                retry_on_overload=True,
                ordering_barrier=False,
                required_capability=capability,
            )
            for method, capability in read_methods
        ]
        policies.extend(
            AppServerMethodPolicy(
                method=method,
                effect=AppServerMethodEffect.MUTATION,
                idempotent=idempotent,
                retry_on_overload=idempotent,
                ordering_barrier=True,
                required_capability=capability,
            )
            for method, capability, idempotent in mutation_methods
        )
        policies.extend(
            AppServerMethodPolicy(
                method=method,
                effect=AppServerMethodEffect.SERVER_REQUEST,
                idempotent=False,
                retry_on_overload=False,
                ordering_barrier=True,
                required_capability=capability,
            )
            for method, capability in server_requests
        )
        return tuple(policies)
