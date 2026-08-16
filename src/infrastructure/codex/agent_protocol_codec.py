"""Agent protocol v1/v2 独立 codec 与边界 mapper。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final, Literal, TypeAlias, cast
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, JsonValue

from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentApprovalOpened,
    CodexAgentCommand,
    CodexAgentCommandAck,
    CodexAgentCommandResult,
    CodexAgentHeartbeat,
    CodexAgentHello,
    CodexAgentHelloAck,
    CodexAgentRealtimeEvent,
    CodexAgentStateSnapshot,
)
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentApprovalReplyCommandDetail,
    AgentCommandHeader,
    AgentCommandV2Detail,
    AgentProtocolMessageType,
    AgentProtocolV2Detail,
    AgentProtocolV2Envelope,
    AgentProtocolV2Header,
    AgentThreadArchiveCommandDetail,
    AgentThreadCompactCommandDetail,
    AgentThreadListCommandDetail,
    AgentThreadNameSetCommandDetail,
    AgentThreadReadCommandDetail,
    AgentThreadResumeCommandDetail,
    AgentThreadStartCommandDetail,
    AgentThreadUnarchiveCommandDetail,
    AgentTurnInterruptCommandDetail,
    AgentTurnStartCommandDetail,
    AgentTurnSteerCommandDetail,
)
from src.core.codex_contract.connection_session_contract import (
    CodexConnectionFrame,
    CodexConnectionProtocolVersion,
)
from src.core.codex_contract.host_contract import CodexApprovalPolicy, CodexSandboxMode

APPROVAL_DECISION_COMMAND_TYPE: Final = "approval.decision"
THREAD_LIST_COMMAND_TYPE: Final = "thread.list"
THREAD_READ_COMMAND_TYPE: Final = "thread.read"
THREAD_START_COMMAND_TYPE: Final = "thread.start"
THREAD_RESUME_COMMAND_TYPE: Final = "thread.resume"
THREAD_NAME_SET_COMMAND_TYPE: Final = "thread.name_set"
THREAD_ARCHIVE_COMMAND_TYPE: Final = "thread.archive"
THREAD_UNARCHIVE_COMMAND_TYPE: Final = "thread.unarchive"
THREAD_COMPACT_COMMAND_TYPE: Final = "thread.compact"
TURN_START_COMMAND_TYPE: Final = "turn.start"
TURN_STEER_COMMAND_TYPE: Final = "turn.steer"
TURN_INTERRUPT_COMMAND_TYPE: Final = "turn.interrupt"

APPROVAL_ID_PARAM: Final = "approvalId"
APPROVAL_VERSION_PARAM: Final = "approvalVersion"
CURSOR_PARAM: Final = "cursor"
DECISION_PARAM: Final = "decision"
EFFORT_PARAM: Final = "effort"
EXPECTED_TURN_ID_PARAM: Final = "expectedTurnId"
INCLUDE_TURNS_PARAM: Final = "includeTurns"
INPUT_PARAM: Final = "input"
LIMIT_PARAM: Final = "limit"
MODEL_PARAM: Final = "model"
NAME_PARAM: Final = "name"
TEXT_PARAM: Final = "text"
TEXT_ELEMENTS_PARAM: Final = "text_elements"
THREAD_ID_PARAM: Final = "threadId"
TURN_ID_PARAM: Final = "turnId"
TYPE_PARAM: Final = "type"
WORKSPACE_KEY_PARAM: Final = "workspace_key"
WORKTREE_POLICY_PARAM: Final = "worktree_policy"
TEXT_INPUT_TYPE: Final = "text"

CURSOR_DETAIL_FIELD: Final = "cursor"
INCLUDE_TURNS_DETAIL_FIELD: Final = "include_turns"
LIMIT_DETAIL_FIELD: Final = "limit"
MESSAGE_DETAIL_FIELD: Final = "message"
MODEL_DETAIL_FIELD: Final = "model"
DISPLAY_NAME_DETAIL_FIELD: Final = "display_name"
REASONING_EFFORT_DETAIL_FIELD: Final = "reasoning_effort"
THREAD_ID_DETAIL_FIELD: Final = "thread_id"
WORKTREE_POLICY_DETAIL_FIELD: Final = "worktree_policy"
SANDBOX_MODE_DETAIL_FIELD: Final = "sandbox_mode"
APPROVAL_POLICY_DETAIL_FIELD: Final = "approval_policy"

AGENT_COMMAND_PARAM_NAMES: Final = {
    APPROVAL_DECISION_COMMAND_TYPE: frozenset(
        {APPROVAL_ID_PARAM, DECISION_PARAM, APPROVAL_VERSION_PARAM}
    ),
    THREAD_LIST_COMMAND_TYPE: frozenset({WORKSPACE_KEY_PARAM, LIMIT_PARAM, CURSOR_PARAM}),
    THREAD_READ_COMMAND_TYPE: frozenset(
        {WORKSPACE_KEY_PARAM, THREAD_ID_PARAM, INCLUDE_TURNS_PARAM}
    ),
    THREAD_START_COMMAND_TYPE: frozenset({WORKSPACE_KEY_PARAM, MODEL_PARAM, WORKTREE_POLICY_PARAM}),
    THREAD_RESUME_COMMAND_TYPE: frozenset({WORKSPACE_KEY_PARAM, THREAD_ID_PARAM}),
    THREAD_NAME_SET_COMMAND_TYPE: frozenset({WORKSPACE_KEY_PARAM, THREAD_ID_PARAM, NAME_PARAM}),
    THREAD_ARCHIVE_COMMAND_TYPE: frozenset({WORKSPACE_KEY_PARAM, THREAD_ID_PARAM}),
    THREAD_UNARCHIVE_COMMAND_TYPE: frozenset({WORKSPACE_KEY_PARAM, THREAD_ID_PARAM}),
    THREAD_COMPACT_COMMAND_TYPE: frozenset({WORKSPACE_KEY_PARAM, THREAD_ID_PARAM}),
    TURN_START_COMMAND_TYPE: frozenset(
        {WORKSPACE_KEY_PARAM, THREAD_ID_PARAM, INPUT_PARAM, MODEL_PARAM, EFFORT_PARAM}
    ),
    TURN_STEER_COMMAND_TYPE: frozenset(
        {WORKSPACE_KEY_PARAM, THREAD_ID_PARAM, EXPECTED_TURN_ID_PARAM, INPUT_PARAM}
    ),
    TURN_INTERRUPT_COMMAND_TYPE: frozenset({WORKSPACE_KEY_PARAM, THREAD_ID_PARAM, TURN_ID_PARAM}),
}
TEXT_INPUT_PARAM_NAMES: Final = frozenset({TYPE_PARAM, TEXT_PARAM, TEXT_ELEMENTS_PARAM})


class AgentV1MessageType(StrEnum):
    """v1 frame 的封闭消息类型。"""

    HELLO = "hello"
    HELLO_ACK = "hello_ack"
    HEARTBEAT = "heartbeat"
    COMMAND = "command"
    COMMAND_ACK = "command.ack"
    COMMAND_RESULT = "command.result"
    STATE_SNAPSHOT = "state.snapshot"
    REALTIME_EVENT = "realtime.event"
    APPROVAL_OPENED = "approval.opened"


AgentV1Payload: TypeAlias = (
    CodexAgentHello
    | CodexAgentHelloAck
    | CodexAgentHeartbeat
    | CodexAgentCommand
    | CodexAgentCommandAck
    | CodexAgentCommandResult
    | CodexAgentStateSnapshot
    | CodexAgentRealtimeEvent
    | CodexAgentApprovalOpened
)
AGENT_PROTOCOL_V2_TRANSPORT_MESSAGE_TYPE = "protocol.v2"
AGENT_V1_MODEL_BY_MESSAGE_TYPE: dict[AgentV1MessageType, type[BaseModel]] = {
    AgentV1MessageType.HELLO: CodexAgentHello,
    AgentV1MessageType.HELLO_ACK: CodexAgentHelloAck,
    AgentV1MessageType.HEARTBEAT: CodexAgentHeartbeat,
    AgentV1MessageType.COMMAND: CodexAgentCommand,
    AgentV1MessageType.COMMAND_ACK: CodexAgentCommandAck,
    AgentV1MessageType.COMMAND_RESULT: CodexAgentCommandResult,
    AgentV1MessageType.STATE_SNAPSHOT: CodexAgentStateSnapshot,
    AgentV1MessageType.REALTIME_EVENT: CodexAgentRealtimeEvent,
    AgentV1MessageType.APPROVAL_OPENED: CodexAgentApprovalOpened,
}


class AgentProtocolV1Decoded(BaseModel):
    """v1 codec 输出的强类型消息。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message_type: AgentV1MessageType
    payload: AgentV1Payload


@dataclass(frozen=True, slots=True)
class DecodedAgentProtocolMessage:
    """协议协商后的 v1/v2 消息。"""

    protocol_version: CodexConnectionProtocolVersion
    v1: AgentProtocolV1Decoded | None = None
    v2: AgentProtocolV2Envelope | None = None


class AgentProtocolV1Codec:
    """只负责旧 frame 与旧强类型 payload 的编码解码。"""

    def decode(self, frame: CodexConnectionFrame) -> AgentProtocolV1Decoded:
        """按 v1 message type 校验 payload。"""

        try:
            message_type = AgentV1MessageType(frame.message_type)
        except ValueError as exc:
            raise ValueError("Agent protocol v1消息类型不受支持。") from exc
        model = AGENT_V1_MODEL_BY_MESSAGE_TYPE[message_type]
        payload = cast(AgentV1Payload, model.model_validate(frame.payload))
        return AgentProtocolV1Decoded(message_type=message_type, payload=payload)

    def encode(
        self, message_type: AgentV1MessageType, payload: AgentV1Payload
    ) -> CodexConnectionFrame:
        """编码旧版 frame。"""

        return CodexConnectionFrame(
            schema_version=CodexConnectionProtocolVersion.V1.value,
            message_id=str(uuid4()),
            message_type=message_type.value,
            payload=cast(dict[str, JsonValue], payload.model_dump(mode="json")),
        )


class AgentProtocolV2Codec:
    """v2 envelope 编码解码；不接受 v1 裸 payload。"""

    def decode(self, frame: CodexConnectionFrame) -> AgentProtocolV2Envelope:
        """从 transport frame 读取完整 v2 envelope。"""

        if frame.message_type != AGENT_PROTOCOL_V2_TRANSPORT_MESSAGE_TYPE:
            raise ValueError("Agent protocol v2 transport类型不正确。")
        return AgentProtocolV2Envelope.model_validate(frame.payload)

    def encode(self, envelope: AgentProtocolV2Envelope) -> CodexConnectionFrame:
        """把 v2 envelope 编码为长期连接 transport frame。"""

        return CodexConnectionFrame(
            schema_version=CodexConnectionProtocolVersion.V2.value,
            message_id=str(envelope.header.message_id),
            message_type=AGENT_PROTOCOL_V2_TRANSPORT_MESSAGE_TYPE,
            payload=cast(dict[str, JsonValue], envelope.model_dump(mode="json")),
        )


class AgentProtocolCodecRegistry:
    """只根据 transport schema version 选择独立 codec。"""

    def __init__(self) -> None:
        self._v1 = AgentProtocolV1Codec()
        self._v2 = AgentProtocolV2Codec()

    def decode(self, frame: CodexConnectionFrame) -> DecodedAgentProtocolMessage:
        """解码一帧，不让 route/use case 检查 JSON 字段。"""

        version = CodexConnectionProtocolVersion(frame.schema_version)
        if version == CodexConnectionProtocolVersion.V1:
            return DecodedAgentProtocolMessage(
                protocol_version=version,
                v1=self._v1.decode(frame),
            )
        return DecodedAgentProtocolMessage(
            protocol_version=version,
            v2=self._v2.decode(frame),
        )

    def encode_v1(
        self,
        message_type: AgentV1MessageType,
        payload: AgentV1Payload,
    ) -> CodexConnectionFrame:
        """通过独立 v1 codec 编码旧协议消息。"""

        return self._v1.encode(message_type, payload)

    def encode_v2(
        self,
        *,
        host_id: UUID,
        key_id: UUID | None = None,
        message_id: UUID,
        detail: AgentProtocolV2Detail,
        sent_at: datetime | None = None,
    ) -> CodexConnectionFrame:
        """构造公共头与指定强类型 detail。"""

        envelope = AgentProtocolV2Envelope(
            header=AgentProtocolV2Header(
                message_id=message_id,
                message_type=AgentProtocolMessageType(detail.kind),
                detail_kind=AgentProtocolMessageType(detail.kind),
                host_id=host_id,
                key_id=key_id,
                sent_at=sent_at or datetime.now(UTC),
            ),
            detail=detail,
        )
        return self._v2.encode(envelope)


class AgentCommandV2Mapper:
    """旧控制面 command 迁移为 v2 强类型 command detail。"""

    def from_v1_command(self, command: CodexAgentCommand) -> AgentCommandV2Detail:
        """集中读取旧 params；其他业务层不得判断这些字段。"""

        detail = self._build_detail(command)
        return AgentCommandV2Detail(
            header=AgentCommandHeader(
                command_id=command.command_id,
                operation_id=command.operation_id,
                request_digest=command.request_digest,
                deadline=command.deadline,
            ),
            detail=detail,
        )

    def to_v1_command(
        self,
        *,
        host_id: UUID,
        command: AgentCommandV2Detail,
    ) -> CodexAgentCommand:
        """仅在 Agent mapper 边界把 v2 typed detail 转为现有执行器输入。"""

        command_type, params = self._to_v1_request(command.detail)
        sandbox_mode = None
        approval_policy = None
        if isinstance(
            command.detail,
            (AgentThreadStartCommandDetail, AgentTurnStartCommandDetail),
        ):
            sandbox_mode = command.detail.sandbox_mode
            approval_policy = command.detail.approval_policy
        return CodexAgentCommand(
            command_id=command.header.command_id,
            operation_id=command.header.operation_id,
            host_id=host_id,
            request_digest=command.header.request_digest,
            command_type=command_type,
            params=params,
            deadline=command.header.deadline,
            sandbox_mode=sandbox_mode,
            approval_policy=approval_policy,
        )

    def _to_v1_request(
        self,
        detail: (
            AgentThreadListCommandDetail
            | AgentThreadReadCommandDetail
            | AgentThreadStartCommandDetail
            | AgentThreadResumeCommandDetail
            | AgentThreadNameSetCommandDetail
            | AgentThreadArchiveCommandDetail
            | AgentThreadUnarchiveCommandDetail
            | AgentThreadCompactCommandDetail
            | AgentTurnStartCommandDetail
            | AgentTurnSteerCommandDetail
            | AgentTurnInterruptCommandDetail
            | AgentApprovalReplyCommandDetail
        ),
    ) -> tuple[str, dict[str, JsonValue]]:
        if isinstance(detail, AgentApprovalReplyCommandDetail):
            return APPROVAL_DECISION_COMMAND_TYPE, {
                APPROVAL_ID_PARAM: str(detail.approval_id),
                DECISION_PARAM: detail.decision,
                APPROVAL_VERSION_PARAM: detail.approval_version,
            }
        params: dict[str, JsonValue] = {WORKSPACE_KEY_PARAM: detail.workspace_key}
        if isinstance(detail, AgentThreadListCommandDetail):
            if LIMIT_DETAIL_FIELD in detail.model_fields_set:
                params[LIMIT_PARAM] = detail.limit
            if CURSOR_DETAIL_FIELD in detail.model_fields_set:
                params[CURSOR_PARAM] = detail.cursor
        elif isinstance(detail, AgentThreadReadCommandDetail):
            params[THREAD_ID_PARAM] = detail.thread_id
            if INCLUDE_TURNS_DETAIL_FIELD in detail.model_fields_set:
                params[INCLUDE_TURNS_PARAM] = detail.include_turns
        elif isinstance(detail, AgentThreadStartCommandDetail):
            if MODEL_DETAIL_FIELD in detail.model_fields_set:
                params[MODEL_PARAM] = detail.model
            if WORKTREE_POLICY_DETAIL_FIELD in detail.model_fields_set:
                params[WORKTREE_POLICY_PARAM] = (
                    detail.worktree_policy.model_dump(mode="json")
                    if detail.worktree_policy is not None
                    else None
                )
        elif isinstance(detail, AgentThreadResumeCommandDetail):
            params[THREAD_ID_PARAM] = detail.thread_id
        elif isinstance(detail, AgentThreadNameSetCommandDetail):
            params.update(
                {
                    THREAD_ID_PARAM: detail.thread_id,
                    NAME_PARAM: detail.display_name,
                }
            )
        elif isinstance(
            detail,
            (AgentThreadArchiveCommandDetail, AgentThreadUnarchiveCommandDetail),
        ):
            params[THREAD_ID_PARAM] = detail.thread_id
        elif isinstance(detail, AgentThreadCompactCommandDetail):
            params[THREAD_ID_PARAM] = detail.thread_id
        elif isinstance(detail, AgentTurnStartCommandDetail):
            params.update(
                {
                    THREAD_ID_PARAM: detail.thread_id,
                    INPUT_PARAM: [
                        {
                            TYPE_PARAM: TEXT_INPUT_TYPE,
                            TEXT_PARAM: detail.message,
                            TEXT_ELEMENTS_PARAM: [],
                        }
                    ],
                }
            )
            if MODEL_DETAIL_FIELD in detail.model_fields_set:
                params[MODEL_PARAM] = detail.model
            if REASONING_EFFORT_DETAIL_FIELD in detail.model_fields_set:
                params[EFFORT_PARAM] = detail.reasoning_effort
        elif isinstance(detail, AgentTurnSteerCommandDetail):
            params.update(
                {
                    THREAD_ID_PARAM: detail.thread_id,
                    EXPECTED_TURN_ID_PARAM: detail.turn_id,
                    INPUT_PARAM: [
                        {
                            TYPE_PARAM: TEXT_INPUT_TYPE,
                            TEXT_PARAM: detail.message,
                            TEXT_ELEMENTS_PARAM: [],
                        }
                    ],
                }
            )
        elif isinstance(detail, AgentTurnInterruptCommandDetail):
            params.update({THREAD_ID_PARAM: detail.thread_id, TURN_ID_PARAM: detail.turn_id})
        return detail.kind, params

    def _build_detail(
        self,
        command: CodexAgentCommand,
    ) -> (
        AgentThreadListCommandDetail
        | AgentThreadReadCommandDetail
        | AgentThreadStartCommandDetail
        | AgentThreadResumeCommandDetail
        | AgentThreadNameSetCommandDetail
        | AgentThreadArchiveCommandDetail
        | AgentThreadUnarchiveCommandDetail
        | AgentThreadCompactCommandDetail
        | AgentTurnStartCommandDetail
        | AgentTurnSteerCommandDetail
        | AgentTurnInterruptCommandDetail
        | AgentApprovalReplyCommandDetail
    ):
        params = command.params
        self._validate_parameter_keys(command.command_type, params)
        if command.command_type == APPROVAL_DECISION_COMMAND_TYPE:
            return AgentApprovalReplyCommandDetail(
                approval_id=UUID(self._read_required_string(params, APPROVAL_ID_PARAM)),
                decision=cast(
                    Literal["accept", "decline", "cancel"],
                    self._read_required_string(params, DECISION_PARAM),
                ),
                approval_version=self._read_required_int(params, APPROVAL_VERSION_PARAM),
            )
        workspace_key = self._read_required_string(params, WORKSPACE_KEY_PARAM)
        if command.command_type == THREAD_LIST_COMMAND_TYPE:
            list_detail_values: dict[str, JsonValue] = {
                WORKSPACE_KEY_PARAM: workspace_key,
            }
            if LIMIT_PARAM in params:
                list_detail_values[LIMIT_DETAIL_FIELD] = self._read_optional_int(
                    params,
                    LIMIT_PARAM,
                    default=50,
                )
            if CURSOR_PARAM in params:
                list_detail_values[CURSOR_DETAIL_FIELD] = self._read_optional_string(
                    params,
                    CURSOR_PARAM,
                )
            return AgentThreadListCommandDetail.model_validate(list_detail_values)
        if command.command_type == THREAD_READ_COMMAND_TYPE:
            read_detail_values: dict[str, JsonValue] = {
                WORKSPACE_KEY_PARAM: workspace_key,
                THREAD_ID_DETAIL_FIELD: self._read_required_string(params, THREAD_ID_PARAM),
            }
            if INCLUDE_TURNS_PARAM in params:
                read_detail_values[INCLUDE_TURNS_DETAIL_FIELD] = self._read_optional_bool(
                    params,
                    INCLUDE_TURNS_PARAM,
                    default=True,
                )
            return AgentThreadReadCommandDetail.model_validate(read_detail_values)
        if command.command_type == THREAD_START_COMMAND_TYPE:
            start_detail_values: dict[str, JsonValue] = {
                WORKSPACE_KEY_PARAM: workspace_key,
                SANDBOX_MODE_DETAIL_FIELD: self._read_command_sandbox_mode(command).value,
                APPROVAL_POLICY_DETAIL_FIELD: self._read_command_approval_policy(command).value,
            }
            if MODEL_PARAM in params:
                start_detail_values[MODEL_DETAIL_FIELD] = self._read_optional_string(
                    params,
                    MODEL_PARAM,
                )
            if WORKTREE_POLICY_PARAM in params:
                start_detail_values[WORKTREE_POLICY_DETAIL_FIELD] = params[WORKTREE_POLICY_PARAM]
            return AgentThreadStartCommandDetail.model_validate(start_detail_values)
        if command.command_type == THREAD_RESUME_COMMAND_TYPE:
            return AgentThreadResumeCommandDetail(
                workspace_key=workspace_key,
                thread_id=self._read_required_string(params, THREAD_ID_PARAM),
            )
        if command.command_type == THREAD_NAME_SET_COMMAND_TYPE:
            return AgentThreadNameSetCommandDetail(
                workspace_key=workspace_key,
                thread_id=self._read_required_string(params, THREAD_ID_PARAM),
                display_name=self._read_required_string(params, NAME_PARAM),
            )
        if command.command_type == THREAD_ARCHIVE_COMMAND_TYPE:
            return AgentThreadArchiveCommandDetail(
                workspace_key=workspace_key,
                thread_id=self._read_required_string(params, THREAD_ID_PARAM),
            )
        if command.command_type == THREAD_UNARCHIVE_COMMAND_TYPE:
            return AgentThreadUnarchiveCommandDetail(
                workspace_key=workspace_key,
                thread_id=self._read_required_string(params, THREAD_ID_PARAM),
            )
        if command.command_type == THREAD_COMPACT_COMMAND_TYPE:
            return AgentThreadCompactCommandDetail(
                workspace_key=workspace_key,
                thread_id=self._read_required_string(params, THREAD_ID_PARAM),
            )
        if command.command_type == TURN_START_COMMAND_TYPE:
            turn_start_detail_values: dict[str, JsonValue] = {
                WORKSPACE_KEY_PARAM: workspace_key,
                THREAD_ID_DETAIL_FIELD: self._read_required_string(params, THREAD_ID_PARAM),
                MESSAGE_DETAIL_FIELD: self._read_input_message(params),
                SANDBOX_MODE_DETAIL_FIELD: self._read_command_sandbox_mode(command).value,
                APPROVAL_POLICY_DETAIL_FIELD: self._read_command_approval_policy(command).value,
            }
            if MODEL_PARAM in params:
                turn_start_detail_values[MODEL_DETAIL_FIELD] = self._read_optional_string(
                    params,
                    MODEL_PARAM,
                )
            if EFFORT_PARAM in params:
                turn_start_detail_values[REASONING_EFFORT_DETAIL_FIELD] = (
                    self._read_optional_string(
                        params,
                        EFFORT_PARAM,
                    )
                )
            return AgentTurnStartCommandDetail.model_validate(turn_start_detail_values)
        if command.command_type == TURN_STEER_COMMAND_TYPE:
            return AgentTurnSteerCommandDetail(
                workspace_key=workspace_key,
                thread_id=self._read_required_string(params, THREAD_ID_PARAM),
                turn_id=self._read_required_string(params, EXPECTED_TURN_ID_PARAM),
                message=self._read_input_message(params),
            )
        if command.command_type == TURN_INTERRUPT_COMMAND_TYPE:
            return AgentTurnInterruptCommandDetail(
                workspace_key=workspace_key,
                thread_id=self._read_required_string(params, THREAD_ID_PARAM),
                turn_id=self._read_required_string(params, TURN_ID_PARAM),
            )
        raise ValueError("Agent command无法映射到v2强类型detail。")

    def _read_command_sandbox_mode(self, command: CodexAgentCommand) -> CodexSandboxMode:
        if command.sandbox_mode is None:
            raise ValueError("Agent command缺少用户确认的沙箱限制。")
        return command.sandbox_mode

    def _read_command_approval_policy(
        self,
        command: CodexAgentCommand,
    ) -> CodexApprovalPolicy:
        if command.approval_policy is None:
            raise ValueError("Agent command缺少用户确认的审批限制。")
        return command.approval_policy

    def _validate_parameter_keys(
        self,
        command_type: str,
        params: dict[str, JsonValue],
    ) -> None:
        """拒绝强类型 detail 无法无损保存的未知参数。"""

        allowed_names = AGENT_COMMAND_PARAM_NAMES.get(command_type)
        if allowed_names is None:
            raise ValueError("Agent command无法映射到v2强类型detail。")
        unexpected_names = set(params).difference(allowed_names)
        if unexpected_names:
            raise ValueError("Agent command包含v2强类型detail不支持的字段。")

    def _read_required_string(self, params: dict[str, JsonValue], key: str) -> str:
        value = params.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Agent command缺少字段：{key}。")
        return value

    def _read_optional_string(self, params: dict[str, JsonValue], key: str) -> str | None:
        value = params.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise ValueError(f"Agent command字段类型错误：{key}。")
        return value

    def _read_optional_int(self, params: dict[str, JsonValue], key: str, *, default: int) -> int:
        value = params.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"Agent command字段类型错误：{key}。")
        return value

    def _read_required_int(self, params: dict[str, JsonValue], key: str) -> int:
        value = params.get(key)
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"Agent command缺少整数字段：{key}。")
        return value

    def _read_optional_bool(
        self,
        params: dict[str, JsonValue],
        key: str,
        *,
        default: bool,
    ) -> bool:
        value = params.get(key, default)
        if not isinstance(value, bool):
            raise ValueError(f"Agent command字段类型错误：{key}。")
        return value

    def _read_input_message(self, params: dict[str, JsonValue]) -> str:
        input_items = params.get(INPUT_PARAM)
        if not isinstance(input_items, list) or len(input_items) != 1:
            raise ValueError("Agent command input必须只包含一个文本项。")
        item = input_items[0]
        if not isinstance(item, dict):
            raise ValueError("Agent command input文本项结构错误。")
        if set(item) != TEXT_INPUT_PARAM_NAMES:
            raise ValueError("Agent command input文本项字段不受支持。")
        if item.get(TYPE_PARAM) != TEXT_INPUT_TYPE or item.get(TEXT_ELEMENTS_PARAM) != []:
            raise ValueError("Agent command input文本项结构错误。")
        text = item.get(TEXT_PARAM)
        if not isinstance(text, str) or not text:
            raise ValueError("Agent command input缺少文本。")
        return text
