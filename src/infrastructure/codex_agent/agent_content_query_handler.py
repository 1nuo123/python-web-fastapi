"""连接内的有界只读查询；不写 journal，不参与事件 replay。"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4
from pydantic import JsonValue

from src.core.codex_contract.agent_content_contract import (
    AgentContentBudgets,
    AgentContentReadRequest,
    ContentErrorCode,
    ContentReadError,
)
from src.core.codex_contract.agent_history_window_contract import (
    AgentBoundedHistoryWindowRequest,
    AgentHistoryWindowStaleError,
)
from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentCommandAckV2Detail,
    AgentCommandResultV2Detail,
    AgentContentReadCommandResult,
    AgentThreadReadCommandResult,
)
from src.core.codex_contract.app_server_jsonrpc_contract import (
    AppServerMessageTooLargeError,
    AppServerRpcClientPort,
    AppServerRpcError,
    AppServerProtocolError,
)
from src.core.codex_contract.app_server_product_contract import AppServerThreadReadProductResult
from src.core.codex_contract.connection_session_contract import (
    CodexConnectionFrame,
)
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.infrastructure.codex.agent_protocol_codec import AgentProtocolCodecRegistry
from src.infrastructure.codex.codex_connection_session import CodexDuplexConnectionSession
from src.infrastructure.codex_agent.agent_bounded_history_reader import AgentBoundedHistoryReader
from src.infrastructure.codex_agent.agent_content_reader import AgentContentReader
from src.infrastructure.codex_agent.agent_timeline_store import AgentTimelineStore
from src.infrastructure.codex_agent.agent_thread_history_window_cache import (
    AgentThreadHistoryWindowCache,
)


class AgentContentQueryHandler:
    def __init__(
        self,
        *,
        host_id: UUID,
        key_id: UUID | None,
        client: AppServerRpcClientPort,
        cache: AgentThreadHistoryWindowCache,
        budgets: AgentContentBudgets,
        timeline_store: AgentTimelineStore | None = None,
        strategy: str,
        sanitize: Callable[[AppServerThreadReadProductResult], AppServerThreadReadProductResult],
        sanitize_source: Callable[[str, dict[str, JsonValue]], dict[str, JsonValue]],
        validate_workspace: Callable[[str], object],
        source_epoch: UUID,
        source_seq: int,
    ) -> None:
        self._host_id = host_id
        self._key_id = key_id
        self._cache = cache
        self._budgets = budgets
        self._reader = AgentBoundedHistoryReader(
            client=client,
            cache=cache,
            timeline_store=timeline_store,
            strategy=strategy,
            sanitize=sanitize,
            sanitize_source=sanitize_source,
        )
        self._validate_workspace = validate_workspace
        self._codec = AgentProtocolCodecRegistry(bounded_content=True)
        self._source_epoch = source_epoch
        self._source_seq = source_seq

    async def execute(
        self,
        command: CodexAgentCommand,
        sender: CodexDuplexConnectionSession,
        *,
        overloaded: bool = False,
    ) -> None:
        if command.request_digest != calculate_agent_request_digest(
            command.command_type, command.params
        ):
            raise ValueError("查询摘要不一致。")
        message_id, sent_at = uuid4(), datetime.now(UTC)

        def frame(
            payload: AgentContentReadCommandResult | AgentThreadReadCommandResult | None,
            error: str | None = None,
        ) -> CodexConnectionFrame:
            return self._codec.encode_v2(
                host_id=self._host_id,
                key_id=self._key_id,
                message_id=message_id,
                sent_at=sent_at,
                detail=AgentCommandResultV2Detail(
                    command_id=command.command_id,
                    operation_id=command.operation_id,
                    outcome="failed" if error else "completed",
                    result=payload,
                    error_code=error,
                    error_summary="读取未完成，请根据错误原因重新读取。" if error else None,
                ),
            )

        await sender.send(
            self._codec.encode_v2(
                host_id=self._host_id,
                key_id=self._key_id,
                message_id=uuid4(),
                detail=AgentCommandAckV2Detail(
                    command_id=command.command_id,
                    operation_id=command.operation_id,
                    state="executing",
                    replayed=False,
                    recovery_required=False,
                ),
            )
        )
        if overloaded:
            await sender.send(frame(None, ContentErrorCode.OVERLOADED.value))
            return
        remaining = max(0.0, (command.deadline - datetime.now(UTC)).total_seconds())
        try:
            async with asyncio.timeout(remaining):
                if command.command_type == "content.read":
                    request = AgentContentReadRequest.model_validate(command.params["request"])
                    self._validate_workspace(request.workspace_key)
                    chunk = AgentContentReader(self._cache).read(
                        request,
                        max_message_bytes=self._budgets.content_chunk_max_message_bytes,
                        encoded_size=lambda value: len(
                            frame(AgentContentReadCommandResult(chunk=value))
                            .model_dump_json()
                            .encode("utf-8")
                        ),
                    )
                    result = frame(AgentContentReadCommandResult(chunk=chunk))
                else:
                    workspace_key, thread_id = (
                        command.params["workspace_key"],
                        command.params["threadId"],
                    )
                    if not isinstance(workspace_key, str) or not isinstance(thread_id, str):
                        raise ValueError("历史读取范围无效。")
                    self._validate_workspace(workspace_key)

                    def snapshot_frame(
                        value: AppServerThreadReadProductResult,
                    ) -> CodexConnectionFrame:
                        return frame(
                            AgentThreadReadCommandResult(
                                snapshot=value.model_copy(
                                    update={
                                        "source_epoch": self._source_epoch,
                                        "source_seq": self._source_seq,
                                    }
                                )
                            )
                        )

                    snapshot = await self._reader.read(
                        workspace_key=workspace_key,
                        thread_id=thread_id,
                        request=AgentBoundedHistoryWindowRequest.model_validate(
                            command.params["history_window"]
                        ),
                        deadline=asyncio.get_running_loop().time() + remaining,
                        operation_id=str(command.operation_id),
                        max_bytes=self._budgets.history_page_max_bytes,
                        encoded_size=lambda value: len(
                            snapshot_frame(value).model_dump_json().encode("utf-8")
                        ),
                    )
                    result = snapshot_frame(snapshot)
                await sender.send_and_wait(result)
        except ContentReadError as exc:
            await sender.send(frame(None, exc.code.value))
        except AgentHistoryWindowStaleError:
            await sender.send(frame(None, "history_cursor_stale"))
        except AppServerMessageTooLargeError:
            await sender.send(frame(None, ContentErrorCode.SOURCE_ITEM_TOO_LARGE.value))
        except AppServerRpcError as exc:
            if exc.error.code == -32600 and any(
                marker in exc.error.message.lower()
                for marker in ("thread not found", "no rollout", "not materialized")
            ):
                await sender.send(frame(None, "history_not_materialized"))
            else:
                await sender.send(frame(None, ContentErrorCode.CAPABILITY_UNAVAILABLE.value))
        except AppServerProtocolError:
            await sender.send(frame(None, ContentErrorCode.CAPABILITY_UNAVAILABLE.value))
        except (ValueError, PermissionError):
            await sender.send(frame(None, "command_rejected"))
        except TimeoutError:
            await sender.send(frame(None, ContentErrorCode.TIMEOUT.value))
