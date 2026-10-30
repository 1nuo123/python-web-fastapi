"""当前权限、引用范围与连接能力共同约束的一次正文读取。"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from src.application.codex.codex_content_reference import CodexContentReferenceCodec
from src.application.codex.codex_thread_read_access import read_owned_codex_thread
from src.application.ports.codex_agent_command_dispatch_port import CodexAgentCommandDispatchPort
from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.agent_content_contract import (
    AgentContentReadRequest,
    CodexContentChunk,
    CodexContentReadRequest,
    ContentErrorCode,
    ContentReadError,
)
from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.codex_contract.connection_session_contract import CodexHostOfflineError
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.domain.codex.codex_error_code import CodexErrorCode

CONTENT_ERROR_STATUS = {
    ContentErrorCode.REVISION_STALE: 409,
    ContentErrorCode.REFERENCE_EXPIRED: 410,
    ContentErrorCode.RANGE_INVALID: 416,
    ContentErrorCode.CAPABILITY_UNAVAILABLE: 409,
    ContentErrorCode.SOURCE_ITEM_TOO_LARGE: 413,
    ContentErrorCode.OVERLOADED: 429,
    ContentErrorCode.TIMEOUT: 504,
    ContentErrorCode.MESSAGE_TOO_LARGE: 413,
}


def content_http_fault(code: ContentErrorCode) -> HttpFaultException:
    return HttpFaultException(
        status_code=CONTENT_ERROR_STATUS[code],
        error_code=CodexErrorCode(code.value),
        message={
            ContentErrorCode.REFERENCE_EXPIRED: "正文引用已失效，请重新加载条目。",
            ContentErrorCode.REVISION_STALE: "正文已更新，请重新加载条目。",
            ContentErrorCode.CAPABILITY_UNAVAILABLE: "当前连接或源版本不支持有界正文读取。",
            ContentErrorCode.SOURCE_ITEM_TOO_LARGE: "源端单条内容超过读取容量，当前版本不支持正文范围读取。",
            ContentErrorCode.OVERLOADED: "正文读取繁忙，请稍后重试。",
            ContentErrorCode.TIMEOUT: "正文读取超时，请稍后重试。",
            ContentErrorCode.RANGE_INVALID: "正文读取位置无效。",
            ContentErrorCode.MESSAGE_TOO_LARGE: "内容或元数据超过消息容量。",
        }[code],
    )


class ReadCodexContentUsecase:
    def __init__(
        self,
        *,
        control_port: CodexControlPort,
        dispatch_port: CodexAgentCommandDispatchPort,
        reference_codec: CodexContentReferenceCodec,
        timeout_seconds: int,
        ack_timeout_seconds: int,
    ) -> None:
        self._control = control_port
        self._dispatch = dispatch_port
        self._codec = reference_codec
        self._timeout = timeout_seconds
        self._ack_timeout = ack_timeout_seconds

    async def execute(
        self,
        *,
        owner_subject_id: str,
        host_id: UUID,
        thread_id: str,
        item_id: str,
        request: CodexContentReadRequest,
    ) -> CodexContentChunk:
        context = await asyncio.to_thread(
            read_owned_codex_thread, self._control, host_id, thread_id, owner_subject_id
        )
        try:
            claims = self._codec.decode(request.content_ref)
            if (
                claims.owner_subject_id,
                claims.host_id,
                claims.workspace_key,
                claims.thread_id,
                claims.item_id,
            ) != (
                owner_subject_id,
                host_id,
                context.workspace_key,
                thread_id,
                item_id,
            ):
                raise HttpFaultException(
                    status_code=404,
                    error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
                    message="Codex资源不存在。",
                )
            if claims.revision != request.revision:
                raise ContentReadError(ContentErrorCode.REVISION_STALE)
            budgets = await self._dispatch.read_content_budgets(host_id)
            if budgets is None or not budgets.content_read:
                raise ContentReadError(ContentErrorCode.CAPABILITY_UNAVAILABLE)
            agent_request = AgentContentReadRequest(
                **request.model_dump(exclude={"content_ref"}),
                content_ref=claims.handle,
                workspace_key=context.workspace_key,
                thread_id=thread_id,
                item_id=item_id,
                field=claims.field,
            )
            params = {"request": agent_request.model_dump(mode="json")}
            command = CodexAgentCommand(
                command_id=uuid4(),
                operation_id=uuid4(),
                host_id=host_id,
                command_type="content.read",
                request_digest=calculate_agent_request_digest("content.read", params),
                params=params,
                deadline=datetime.now(UTC) + timedelta(seconds=self._timeout),
            )
            result = await self._dispatch.dispatch_and_wait_result(
                command, ack_timeout_seconds=self._ack_timeout, result_timeout_seconds=self._timeout
            )
            if result.outcome != "completed":
                try:
                    code = ContentErrorCode(result.error_code)
                except (ValueError, TypeError):
                    raise HttpFaultException(
                        status_code=502,
                        error_code=CodexErrorCode.UPSTREAM_FAILURE,
                        message="正文读取失败。",
                    ) from None
                raise ContentReadError(code)
            if not isinstance(result.result, dict) or "contentChunk" not in result.result:
                raise ValueError("Agent正文结果缺少强类型载荷。")
            chunk = CodexContentChunk.model_validate(result.result["contentChunk"])
            if (
                chunk.revision != request.revision
                or chunk.offset != request.offset
                or chunk.next_offset != chunk.offset + len(chunk.text.encode("utf-8"))
                or (not chunk.eof and chunk.next_offset <= chunk.offset)
                or (
                    chunk.total_bytes is not None
                    and (
                        chunk.next_offset > chunk.total_bytes
                        or chunk.eof != (chunk.next_offset == chunk.total_bytes)
                    )
                )
            ):
                raise ValueError("正文块范围契约不一致。")
            return chunk
        except ContentReadError as exc:
            raise content_http_fault(exc.code) from exc
        except CodexHostOfflineError as exc:
            raise HttpFaultException(
                status_code=503,
                error_code=CodexErrorCode.HOST_OFFLINE,
                message="电脑已离线，请稍后重试。",
            ) from exc
        except TimeoutError as exc:
            raise content_http_fault(ContentErrorCode.TIMEOUT) from exc
