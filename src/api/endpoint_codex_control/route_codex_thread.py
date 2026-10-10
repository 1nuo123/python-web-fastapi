"""Codex 线程索引路由。"""

from __future__ import annotations

from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.core.codex_contract.host_contract import CodexSandboxMode
from src.core.codex_contract.operation_contract import CodexOperationView
from src.core.codex_contract.thread_contract import (
    CODEX_CONVERSATION_PAGE_LIMIT_DEFAULT,
    CODEX_CONVERSATION_PAGE_LIMIT_MAXIMUM,
    CODEX_CONVERSATION_PAGE_LIMIT_MINIMUM,
    CODEX_HISTORY_ITEM_RELOAD_MAXIMUM,
    CodexConversationListQuery,
    CodexConversationPage,
    CodexConversationPinRequest,
    CodexConversationRenameRequest,
    CodexThreadAuthoritySnapshot,
    CodexThreadHistoryItemReload,
    CodexThreadHistoryPage,
    CodexThreadHistoryQuery,
    CodexThreadIndexSnapshot,
)
from src.core.codex_contract.turn_contract import (
    CodexExecutionOptions,
    CodexOperationAccepted,
    CodexThreadCreateRequest,
    CodexTurnStartRequest,
)
from src.core.exception_contract.error_code_catalog_contract import SuccessCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.domain.codex.codex_authorization_policy import (
    CODEX_FULL_ACCESS_AUTHORIZATION_REQUIREMENT,
    CODEX_OPERATE_AUTHORIZATION_REQUIREMENT,
    CODEX_READ_AUTHORIZATION_REQUIREMENT,
    CODEX_TOOL_EXECUTION_AUTHORIZATION_REQUIREMENT,
)
from src.domain.codex.codex_error_code import CodexErrorCode

CODEX_THREAD_BEARER_SCHEME = HTTPBearer(auto_error=False)


def _validate_turn_operation_identity(
    body: CodexTurnStartRequest,
    idempotency_key: str,
) -> None:
    """拒绝 body 与 HTTP 头不一致的 turn 身份，避免重试落入不同副作用。"""

    if str(body.client_operation_id) == idempotency_key:
        return
    raise HttpFaultException(
        status_code=HTTPStatus.BAD_REQUEST,
        error_code=CodexErrorCode.IDEMPOTENCY_KEY_MISMATCH,
        message="Idempotency-Key必须与client_operation_id完全一致。",
    )


class CodexThreadRouteCatalog:
    """注册线程索引读取接口。"""

    def __init__(self) -> None:
        self._accessor = DependencyContextAccessor()
        self.router = APIRouter()
        self.router.add_api_route(
            "/codex/hosts/{host_id}/operations/{operation_id}",
            self.get_operation,
            methods=["GET"],
            response_model=ResponseEnvelope[CodexOperationView],
            dependencies=[Depends(self.require_codex_read)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/threads",
            self.get_threads,
            methods=["GET"],
            response_model=ResponseEnvelope[CodexConversationPage],
            dependencies=[Depends(self.require_codex_read)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/threads",
            self.create_thread,
            methods=["POST"],
            status_code=status.HTTP_202_ACCEPTED,
            response_model=ResponseEnvelope[CodexOperationAccepted],
            dependencies=[Depends(self.require_codex_operate)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/threads/{thread_id}/turns",
            self.start_turn,
            methods=["POST"],
            status_code=status.HTTP_202_ACCEPTED,
            response_model=ResponseEnvelope[CodexOperationAccepted],
            dependencies=[Depends(self.require_codex_operate)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/threads/{thread_id}",
            self.get_thread,
            methods=["GET"],
            response_model=ResponseEnvelope[CodexThreadAuthoritySnapshot],
            dependencies=[Depends(self.require_codex_read)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/threads/{thread_id}/history",
            self.get_thread_history,
            methods=["GET"],
            response_model=ResponseEnvelope[CodexThreadHistoryPage],
            dependencies=[Depends(self.require_codex_read)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/threads/{thread_id}/history/items",
            self.get_thread_history_items,
            methods=["GET"],
            response_model=ResponseEnvelope[CodexThreadHistoryItemReload],
            dependencies=[Depends(self.require_codex_read)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/threads/{thread_id}/resume",
            self.resume_thread,
            methods=["POST"],
            status_code=status.HTTP_202_ACCEPTED,
            response_model=ResponseEnvelope[CodexOperationAccepted],
            dependencies=[Depends(self.require_codex_operate)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/threads/{thread_id}/steer",
            self.steer_turn,
            methods=["POST"],
            status_code=status.HTTP_202_ACCEPTED,
            response_model=ResponseEnvelope[CodexOperationAccepted],
            dependencies=[Depends(self.require_codex_operate)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/threads/{thread_id}/interrupt",
            self.interrupt_turn,
            methods=["POST"],
            status_code=status.HTTP_202_ACCEPTED,
            response_model=ResponseEnvelope[CodexOperationAccepted],
            dependencies=[Depends(self.require_codex_operate)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/threads/{thread_id}/compact",
            self.compact_thread,
            methods=["POST"],
            status_code=status.HTTP_202_ACCEPTED,
            response_model=ResponseEnvelope[CodexOperationAccepted],
            dependencies=[Depends(self.require_codex_operate)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/threads/{thread_id}/name",
            self.rename_thread,
            methods=["PATCH"],
            status_code=status.HTTP_202_ACCEPTED,
            response_model=ResponseEnvelope[CodexOperationAccepted],
            dependencies=[Depends(self.require_codex_operate)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/threads/{thread_id}/pin",
            self.update_thread_pin,
            methods=["PATCH"],
            response_model=ResponseEnvelope[CodexThreadIndexSnapshot],
            dependencies=[Depends(self.require_codex_operate)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/threads/{thread_id}/archive",
            self.archive_thread,
            methods=["POST"],
            status_code=status.HTTP_202_ACCEPTED,
            response_model=ResponseEnvelope[CodexOperationAccepted],
            dependencies=[Depends(self.require_codex_operate)],
        )
        self.router.add_api_route(
            "/codex/hosts/{host_id}/threads/{thread_id}/unarchive",
            self.unarchive_thread,
            methods=["POST"],
            status_code=status.HTTP_202_ACCEPTED,
            response_model=ResponseEnvelope[CodexOperationAccepted],
            dependencies=[Depends(self.require_codex_operate)],
        )

    async def require_codex_read(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(CODEX_THREAD_BEARER_SCHEME),
    ) -> None:
        self._accessor.read_authorized_principal(request, CODEX_READ_AUTHORIZATION_REQUIREMENT)

    async def require_codex_operate(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(CODEX_THREAD_BEARER_SCHEME),
    ) -> None:
        self._accessor.read_authorized_principal(
            request,
            CODEX_OPERATE_AUTHORIZATION_REQUIREMENT,
        )

    async def get_operation(
        self, request: Request, host_id: UUID, operation_id: UUID
    ) -> ResponseEnvelope[CodexOperationView]:
        """核对已有操作，读取不会重新执行命令。"""

        principal = self._accessor.read_authenticated_principal(request)
        payload = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name="default_sync_usecase",
            callable_object=self._accessor.read_execute_codex_thread_command_usecase(
                request
            ).read_operation,
            operation_id=operation_id,
            host_id=host_id,
            owner_subject_id=principal.subject_id,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex操作状态读取成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def get_threads(
        self,
        request: Request,
        host_id: UUID,
        workspace_id: UUID | None = None,
        archived: bool = False,
        search_term: str | None = None,
        cursor: str | None = None,
        limit: Annotated[
            int,
            Query(
                ge=CODEX_CONVERSATION_PAGE_LIMIT_MINIMUM,
                le=CODEX_CONVERSATION_PAGE_LIMIT_MAXIMUM,
            ),
        ] = CODEX_CONVERSATION_PAGE_LIMIT_DEFAULT,
    ) -> ResponseEnvelope[CodexConversationPage]:
        """读取当前主体拥有的主机线程索引。"""

        principal = self._accessor.read_authenticated_principal(request)
        payload = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name="default_sync_usecase",
            callable_object=self._accessor.read_query_codex_threads_usecase(request).execute,
            host_id=host_id,
            owner_subject_id=principal.subject_id,
            query=CodexConversationListQuery(
                workspace_id=workspace_id,
                archived=archived,
                search_term=search_term,
                cursor=cursor,
                limit=limit,
            ),
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex 线程索引读取成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def create_thread(
        self,
        request: Request,
        host_id: UUID,
        body: CodexThreadCreateRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ) -> ResponseEnvelope[CodexOperationAccepted]:
        """提交 thread/start 并只等待 App Server 接受。"""

        principal = self._accessor.read_authenticated_principal(request)
        self._require_execution_scopes(request, body.execution)
        payload = await self._accessor.read_execute_codex_thread_command_usecase(
            request
        ).start_thread(
            host_id=host_id,
            workspace_id=body.workspace_id,
            execution=body.execution,
            actor_subject_id=principal.subject_id,
            idempotency_key=idempotency_key,
        )
        return self._accepted_response(request, payload, "Codex thread创建操作已接受。")

    async def get_thread(
        self,
        request: Request,
        host_id: UUID,
        thread_id: str,
        include_history: bool = False,
        legacy_history_cursor: str | None = Query(
            default=None,
            alias="history_cursor",
        ),
        history_limit: Annotated[
            int,
            Query(
                ge=1,
                le=100,
            ),
        ] = 50,
    ) -> ResponseEnvelope[CodexThreadAuthoritySnapshot]:
        """从 Agent/App Server 读取 thread 正文权威 snapshot。"""

        if legacy_history_cursor is not None:
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=CodexErrorCode.HISTORY_CURSOR_STALE,
                message="旧版历史游标已失效，请使用签名before_cursor重新读取。",
            )
        principal = self._accessor.read_authenticated_principal(request)
        payload = await self._accessor.read_codex_thread_snapshot_usecase(request).execute(
            host_id=host_id,
            upstream_thread_id=thread_id,
            owner_subject_id=principal.subject_id,
            include_history=include_history,
            history_limit=history_limit,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex thread权威快照读取成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def get_thread_history(
        self,
        request: Request,
        host_id: UUID,
        thread_id: str,
        before_cursor: str | None = None,
        limit: Annotated[
            int,
            Query(
                ge=1,
                le=100,
            ),
        ] = 50,
    ) -> ResponseEnvelope[CodexThreadHistoryPage]:
        """按签名边界向前读取一页历史，拒绝 offset 和跨范围游标。"""

        principal = self._accessor.read_authenticated_principal(request)
        payload = await self._accessor.read_codex_thread_snapshot_usecase(
            request
        ).read_history_page(
            host_id=host_id,
            upstream_thread_id=thread_id,
            owner_subject_id=principal.subject_id,
            query=CodexThreadHistoryQuery(
                before_cursor=before_cursor,
                limit=limit,
            ),
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex历史分页读取成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def get_thread_history_items(
        self,
        request: Request,
        host_id: UUID,
        thread_id: str,
        item_id: Annotated[
            list[str],
            Query(min_length=1, max_length=CODEX_HISTORY_ITEM_RELOAD_MAXIMUM),
        ],
    ) -> ResponseEnvelope[CodexThreadHistoryItemReload]:
        """仅按稳定 item ID 恢复当前标签页已经回收的正文，拒绝正文搜索与 offset。"""

        principal = self._accessor.read_authenticated_principal(request)
        payload = await self._accessor.read_codex_thread_snapshot_usecase(
            request
        ).read_history_items(
            host_id=host_id,
            upstream_thread_id=thread_id,
            owner_subject_id=principal.subject_id,
            item_ids=item_id,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex 已回收历史正文读取成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def resume_thread(
        self,
        request: Request,
        host_id: UUID,
        thread_id: str,
        body: CodexExecutionOptions,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ) -> ResponseEnvelope[CodexOperationAccepted]:
        """恢复已持久化 thread。"""

        principal = self._accessor.read_authenticated_principal(request)
        self._require_execution_scopes(request, body)
        payload = await self._accessor.read_execute_codex_thread_command_usecase(
            request
        ).resume_thread(
            host_id=host_id,
            upstream_thread_id=thread_id,
            actor_subject_id=principal.subject_id,
            idempotency_key=idempotency_key,
            execution=body,
        )
        return self._accepted_response(request, payload, "Codex thread恢复操作已接受。")

    async def steer_turn(
        self,
        request: Request,
        host_id: UUID,
        thread_id: str,
        body: CodexTurnStartRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ) -> ResponseEnvelope[CodexOperationAccepted]:
        """向 active turn 发送 steer。"""

        principal = self._accessor.read_authenticated_principal(request)
        _validate_turn_operation_identity(body, idempotency_key)
        self._accessor.read_authorized_principal(
            request,
            CODEX_TOOL_EXECUTION_AUTHORIZATION_REQUIREMENT,
        )
        payload = await self._accessor.read_execute_codex_thread_command_usecase(
            request
        ).steer_turn(
            host_id=host_id,
            upstream_thread_id=thread_id,
            message=body.message,
            actor_subject_id=principal.subject_id,
            idempotency_key=idempotency_key,
            client_operation_id=body.client_operation_id,
        )
        return self._accepted_response(request, payload, "Codex steer操作已接受。")

    async def interrupt_turn(
        self,
        request: Request,
        host_id: UUID,
        thread_id: str,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ) -> ResponseEnvelope[CodexOperationAccepted]:
        """中断 active turn，重复请求复用同一 operation/command。"""

        principal = self._accessor.read_authenticated_principal(request)
        payload = await self._accessor.read_execute_codex_thread_command_usecase(
            request
        ).interrupt_turn(
            host_id=host_id,
            upstream_thread_id=thread_id,
            actor_subject_id=principal.subject_id,
            idempotency_key=idempotency_key,
        )
        return self._accepted_response(request, payload, "Codex interrupt操作已接受。")

    def _accepted_response(
        self,
        request: Request,
        payload: CodexOperationAccepted,
        message: str,
    ) -> ResponseEnvelope[CodexOperationAccepted]:
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message=message,
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def start_turn(
        self,
        request: Request,
        host_id: UUID,
        thread_id: str,
        body: CodexTurnStartRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ) -> ResponseEnvelope[CodexOperationAccepted]:
        """提交 turn/start 并返回固定 operation/command 身份。"""

        principal = self._accessor.read_authenticated_principal(request)
        _validate_turn_operation_identity(body, idempotency_key)
        self._require_execution_scopes(request, body.execution)
        payload = await self._accessor.read_execute_codex_thread_command_usecase(
            request
        ).start_turn(
            host_id=host_id,
            upstream_thread_id=thread_id,
            message=body.message,
            execution=body.execution,
            actor_subject_id=principal.subject_id,
            idempotency_key=idempotency_key,
            client_operation_id=body.client_operation_id,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex turn启动操作已接受。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def compact_thread(
        self,
        request: Request,
        host_id: UUID,
        thread_id: str,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ) -> ResponseEnvelope[CodexOperationAccepted]:
        """启动 thread compact 并返回稳定 operation。"""

        principal = self._accessor.read_authenticated_principal(request)
        payload = await self._accessor.read_execute_codex_thread_command_usecase(
            request
        ).compact_thread(
            host_id=host_id,
            upstream_thread_id=thread_id,
            actor_subject_id=principal.subject_id,
            idempotency_key=idempotency_key,
        )
        return self._accepted_response(request, payload, "Codex thread压缩操作已接受。")

    async def rename_thread(
        self,
        request: Request,
        host_id: UUID,
        thread_id: str,
        body: CodexConversationRenameRequest,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ) -> ResponseEnvelope[CodexOperationAccepted]:
        """保存手工标题并投递 App Server 重命名命令。"""

        principal = self._accessor.read_authenticated_principal(request)
        payload = await self._accessor.read_execute_codex_thread_command_usecase(
            request
        ).rename_thread(
            host_id=host_id,
            upstream_thread_id=thread_id,
            display_name=body.display_name,
            actor_subject_id=principal.subject_id,
            idempotency_key=idempotency_key,
        )
        return self._accepted_response(request, payload, "Codex会话重命名操作已接受。")

    async def update_thread_pin(
        self,
        request: Request,
        host_id: UUID,
        thread_id: str,
        body: CodexConversationPinRequest,
    ) -> ResponseEnvelope[CodexThreadIndexSnapshot]:
        """更新控制面会话置顶偏好。"""

        principal = self._accessor.read_authenticated_principal(request)
        payload = await self._accessor.read_request_execution_bridge(request).run_sync(
            execution_name="default_sync_usecase",
            callable_object=(
                self._accessor.read_update_codex_thread_preference_usecase(request).execute
            ),
            host_id=host_id,
            upstream_thread_id=thread_id,
            owner_subject_id=principal.subject_id,
            request=body,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex会话置顶偏好更新成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=payload,
        )

    async def archive_thread(
        self,
        request: Request,
        host_id: UUID,
        thread_id: str,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ) -> ResponseEnvelope[CodexOperationAccepted]:
        """投递会话归档命令，等待上游结果收敛最终状态。"""

        principal = self._accessor.read_authenticated_principal(request)
        payload = await self._accessor.read_execute_codex_thread_command_usecase(
            request
        ).archive_thread(
            host_id=host_id,
            upstream_thread_id=thread_id,
            actor_subject_id=principal.subject_id,
            idempotency_key=idempotency_key,
        )
        return self._accepted_response(request, payload, "Codex会话归档操作已接受。")

    async def unarchive_thread(
        self,
        request: Request,
        host_id: UUID,
        thread_id: str,
        idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=256),
    ) -> ResponseEnvelope[CodexOperationAccepted]:
        """投递会话恢复命令，等待上游结果收敛最终状态。"""

        principal = self._accessor.read_authenticated_principal(request)
        payload = await self._accessor.read_execute_codex_thread_command_usecase(
            request
        ).unarchive_thread(
            host_id=host_id,
            upstream_thread_id=thread_id,
            actor_subject_id=principal.subject_id,
            idempotency_key=idempotency_key,
        )
        return self._accepted_response(request, payload, "Codex会话恢复操作已接受。")

    def _require_execution_scopes(
        self,
        request: Request,
        execution: CodexExecutionOptions,
    ) -> None:
        self._accessor.read_authorized_principal(
            request,
            CODEX_TOOL_EXECUTION_AUTHORIZATION_REQUIREMENT,
        )
        if execution.sandbox_mode is CodexSandboxMode.DANGER_FULL_ACCESS:
            self._accessor.read_authorized_principal(
                request,
                CODEX_FULL_ACCESS_AUTHORIZATION_REQUIREMENT,
            )
