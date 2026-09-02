"""对已 initialize 的 App Server 执行隔离、可清理的 capability probe。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Final, Protocol, cast

from pydantic import JsonValue

from src.core.codex_contract.app_server_capability_contract import (
    AppServerCapabilityProbeFailure,
    AppServerCapabilityProbeOutcome,
    AppServerCapabilityProbeResult,
)
from src.core.codex_contract.app_server_jsonrpc_contract import (
    AppServerProtocolError,
    AppServerRpcError,
    JsonRpcId,
)
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerCapabilityDetail,
    AppServerDefaultCatalog,
    AppServerMethodName,
)
from src.domain.codex.agent_command_policy import read_upstream_identifiers

READ_TIMEOUT_SECONDS: Final = 15.0
TURN_TIMEOUT_SECONDS: Final = 180.0
APPROVAL_TIMEOUT_SECONDS: Final = 90.0
NO_TOOL_PROMPT: Final = (
    "Reply exactly CODEX_REMOTE_CAPABILITY_OK. Do not use tools, execute commands, or modify files."
)
APPROVAL_PROMPT: Final = (
    "You MUST use the shell tool now. Run exactly one command: pwd. Do not read or "
    "modify files. Wait for approval before executing the command."
)
INTERRUPT_PROMPT: Final = (
    "Write a very long numbered list and continue until the request is interrupted. "
    "Do not use tools or modify files."
)
APPROVAL_METHODS: Final = frozenset(
    {
        AppServerMethodName.COMMAND_APPROVAL.value,
        AppServerMethodName.FILE_CHANGE_APPROVAL.value,
        AppServerMethodName.PERMISSIONS_APPROVAL.value,
    }
)


class AppServerCapabilityProbeClientPort(Protocol):
    """探针复用正式 JSON-RPC client 所需的最小边界。"""

    async def request(
        self,
        method: str,
        params: JsonValue,
        *,
        timeout_seconds: float,
        operation_id: str | None = None,
    ) -> JsonValue: ...

    async def reply(self, request_id: JsonRpcId, result: JsonValue) -> None: ...

    async def reply_error(self, request_id: JsonRpcId, *, code: int, message: str) -> None: ...


class AppServerCapabilityProbe:
    """收集核心读写、turn、approval 和 interrupt 的真实行为证据。"""

    def __init__(
        self,
        client: AppServerCapabilityProbeClientPort,
        *,
        workspace: str,
        initialize_passed: bool,
    ) -> None:
        self._client = client
        self._workspace = workspace
        self._initialize_passed = initialize_passed
        self._active = False
        self._thread_id: str | None = None
        self._methods: set[AppServerMethodName] = set()
        self._notifications: set[str] = set()
        self._completed_turns: set[str] = set()
        self._turn_completion_event = asyncio.Event()
        self._approval_event = asyncio.Event()
        self._approval_confirmed = False
        self._thread_cleaned = False

    @property
    def active(self) -> bool:
        """返回当前 App Server 事件是否属于探针窗口。"""

        return self._active

    async def run(
        self, *, confirm_full_capabilities: bool = True
    ) -> AppServerCapabilityProbeResult:
        """执行 probe；完整能力失败时只在核心读取已确认后降级 read_only。"""

        self._active = True
        self._methods.add(AppServerMethodName.INITIALIZE)
        try:
            read_failure = await self._probe_read_methods()
            if read_failure is not None:
                return self._build_blocked(read_failure)
            if not confirm_full_capabilities:
                return self._build_read_only()
            failure = await self._probe_mutations()
            if failure is not None:
                return self._build_read_only(failure)
            return self._build_compatible()
        finally:
            await self._cleanup_thread()
            self._active = False

    async def accept_notification(self, method: str, params: JsonValue) -> bool:
        """在连接建立前消费探针事件，避免写入产品 event buffer。"""

        if not self._active:
            return False
        self._notifications.add(method)
        if method == "turn/completed" and isinstance(params, Mapping):
            turn = cast(Mapping[str, object], params).get("turn")
            if isinstance(turn, Mapping):
                turn_id = cast(Mapping[str, object], turn).get("id")
                if isinstance(turn_id, str) and turn_id:
                    self._completed_turns.add(turn_id)
                    self._turn_completion_event.set()
        return True

    async def accept_request(
        self,
        request_id: JsonRpcId,
        method: str,
        params: JsonValue,
    ) -> bool:
        """自动拒绝隔离探针审批，验证 request/response 而不执行工具。"""

        if not self._active:
            return False
        if method not in APPROVAL_METHODS or not isinstance(params, Mapping):
            await self._client.reply_error(
                request_id,
                code=-32601,
                message="Codex Remote capability probe does not support this request.",
            )
            return True
        if method == AppServerMethodName.PERMISSIONS_APPROVAL.value:
            response: JsonValue = {"permissions": {}, "scope": "turn"}
        else:
            response = {"decision": "decline"}
        await self._client.reply(request_id, response)
        if method == AppServerMethodName.COMMAND_APPROVAL.value:
            self._approval_confirmed = True
            self._methods.add(AppServerMethodName.COMMAND_APPROVAL)
            self._approval_event.set()
        return True

    async def _probe_read_methods(self) -> AppServerCapabilityProbeFailure | None:
        try:
            model_result = await self._client.request(
                AppServerMethodName.MODEL_LIST.value,
                {},
                timeout_seconds=READ_TIMEOUT_SECONDS,
            )
            self._require_mapping(model_result)
            self._methods.add(AppServerMethodName.MODEL_LIST)
            thread_list_result = await self._client.request(
                AppServerMethodName.THREAD_LIST.value,
                {"cwd": self._workspace, "limit": 1},
                timeout_seconds=READ_TIMEOUT_SECONDS,
            )
            self._require_mapping(thread_list_result)
            self._methods.add(AppServerMethodName.THREAD_LIST)
            return None
        except TimeoutError:
            return AppServerCapabilityProbeFailure.TIMEOUT
        except (AppServerProtocolError, AppServerRpcError, ConnectionError, ValueError):
            return AppServerCapabilityProbeFailure.READ_METHOD_FAILED

    async def _probe_mutations(self) -> AppServerCapabilityProbeFailure | None:
        try:
            start_result = await self._client.request(
                AppServerMethodName.THREAD_START.value,
                {
                    "cwd": self._workspace,
                    "sandbox": "read-only",
                    "approvalPolicy": "untrusted",
                    "approvalsReviewer": "user",
                    "ephemeral": True,
                },
                timeout_seconds=READ_TIMEOUT_SECONDS,
            )
            thread_id, _ = read_upstream_identifiers(start_result)
            if thread_id is None:
                return AppServerCapabilityProbeFailure.CORE_FIELD_MISSING
            self._thread_id = thread_id
            self._methods.add(AppServerMethodName.THREAD_START)
            read_result = await self._client.request(
                AppServerMethodName.THREAD_READ.value,
                {"threadId": thread_id, "includeTurns": False},
                timeout_seconds=READ_TIMEOUT_SECONDS,
            )
            self._require_mapping(read_result)
            self._methods.add(AppServerMethodName.THREAD_READ)
            no_tool_turn = await self._start_turn(NO_TOOL_PROMPT)
            await self._wait_for_turn(no_tool_turn, TURN_TIMEOUT_SECONDS)
            approval_turn = await self._start_turn(APPROVAL_PROMPT)
            try:
                await asyncio.wait_for(
                    self._approval_event.wait(),
                    timeout=APPROVAL_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                await self._interrupt_turn(approval_turn)
                return AppServerCapabilityProbeFailure.APPROVAL_FAILED
            try:
                await self._wait_for_turn(approval_turn, READ_TIMEOUT_SECONDS)
            except TimeoutError:
                await self._interrupt_turn(approval_turn)
            interrupt_turn = await self._start_turn(INTERRUPT_PROMPT)
            await self._interrupt_turn(interrupt_turn)
            delete_succeeded = await self._delete_thread()
            if not delete_succeeded:
                return AppServerCapabilityProbeFailure.MUTATION_METHOD_FAILED
            return None
        except TimeoutError:
            return AppServerCapabilityProbeFailure.TIMEOUT
        except (AppServerProtocolError, AppServerRpcError, ConnectionError, ValueError):
            return AppServerCapabilityProbeFailure.MUTATION_METHOD_FAILED

    async def _start_turn(self, prompt: str) -> str:
        if self._thread_id is None:
            raise ValueError("capability probe缺少thread id。")
        result = await self._client.request(
            AppServerMethodName.TURN_START.value,
            {
                "threadId": self._thread_id,
                "input": [{"type": "text", "text": prompt, "text_elements": []}],
                "approvalPolicy": "untrusted",
                "approvalsReviewer": "user",
            },
            timeout_seconds=READ_TIMEOUT_SECONDS,
        )
        _, turn_id = read_upstream_identifiers(result)
        if turn_id is None:
            raise ValueError("capability probe turn/start缺少turn id。")
        self._methods.add(AppServerMethodName.TURN_START)
        return turn_id

    async def _wait_for_turn(self, turn_id: str, timeout_seconds: float) -> None:
        async with asyncio.timeout(timeout_seconds):
            while turn_id not in self._completed_turns:
                self._turn_completion_event.clear()
                await self._turn_completion_event.wait()

    async def _interrupt_turn(self, turn_id: str) -> None:
        if self._thread_id is None:
            raise ValueError("capability probe缺少thread id。")
        try:
            await self._client.request(
                AppServerMethodName.TURN_INTERRUPT.value,
                {"threadId": self._thread_id, "turnId": turn_id},
                timeout_seconds=READ_TIMEOUT_SECONDS,
            )
        except AppServerRpcError as exc:
            if exc.error.code == -32601:
                raise
        self._methods.add(AppServerMethodName.TURN_INTERRUPT)

    async def _delete_thread(self) -> bool:
        if self._thread_id is None:
            return False
        thread_id = self._thread_id
        try:
            await self._client.request(
                AppServerMethodName.THREAD_DELETE.value,
                {"threadId": thread_id},
                timeout_seconds=READ_TIMEOUT_SECONDS,
            )
        except (AppServerProtocolError, AppServerRpcError, ConnectionError, TimeoutError) as exc:
            if isinstance(exc, AppServerRpcError) and "not persisted" in exc.error.message:
                # Ephemeral probe threads are automatically discarded by Codex
                # 0.152; thread/delete correctly reports that there is nothing
                # persisted to delete.
                self._thread_id = None
                self._thread_cleaned = True
                return True
            logging.getLogger(__name__).warning("capability probe thread/delete failed: %s", exc)
            return False
        self._thread_id = None
        self._thread_cleaned = True
        self._methods.add(AppServerMethodName.THREAD_DELETE)
        return True

    async def _cleanup_thread(self) -> None:
        if self._thread_id is not None:
            # Cleanup is best-effort; a failed probe must not mask its primary result.
            try:
                await self._delete_thread()
            except Exception:
                self._thread_id = None

    def _build_compatible(self) -> AppServerCapabilityProbeResult:
        return AppServerCapabilityProbeResult(
            outcome=AppServerCapabilityProbeOutcome.COMPATIBLE,
            initialize_passed=self._initialize_passed,
            methods=self._ordered_methods(),
            notification_methods=tuple(sorted(self._notifications)),
            capabilities=self._capabilities(),
            read_only_confirmed=True,
            mutation_confirmed=True,
            approval_confirmed=self._approval_confirmed,
            interrupt_confirmed=AppServerMethodName.TURN_INTERRUPT in self._methods,
            thread_cleaned=self._thread_cleaned,
        )

    def _build_read_only(
        self,
        failure: AppServerCapabilityProbeFailure | None = None,
    ) -> AppServerCapabilityProbeResult:
        return AppServerCapabilityProbeResult(
            outcome=AppServerCapabilityProbeOutcome.READ_ONLY,
            initialize_passed=self._initialize_passed,
            methods=self._ordered_methods(),
            notification_methods=tuple(sorted(self._notifications)),
            capabilities=self._capabilities(),
            read_only_confirmed=True,
            mutation_confirmed=False,
            approval_confirmed=self._approval_confirmed,
            interrupt_confirmed=AppServerMethodName.TURN_INTERRUPT in self._methods,
            thread_cleaned=self._thread_cleaned,
            failure=failure,
        )

    def _build_blocked(
        self,
        failure: AppServerCapabilityProbeFailure,
    ) -> AppServerCapabilityProbeResult:
        return AppServerCapabilityProbeResult(
            outcome=AppServerCapabilityProbeOutcome.BLOCKED,
            initialize_passed=self._initialize_passed,
            methods=self._ordered_methods(),
            notification_methods=tuple(sorted(self._notifications)),
            capabilities=self._capabilities(),
            thread_cleaned=self._thread_cleaned,
            failure=failure,
        )

    def _ordered_methods(self) -> tuple[AppServerMethodName, ...]:
        return tuple(sorted(self._methods, key=lambda method: method.value))

    def _capabilities(self) -> tuple[AppServerCapabilityDetail, ...]:
        policies = AppServerDefaultCatalog().build_method_catalog()
        confirmed = {
            item.required_capability
            for item in policies
            if item.method in self._methods and item.required_capability is not None
        }
        return tuple(
            AppServerCapabilityDetail(code=code, version=1)
            for code in sorted(confirmed, key=lambda capability: capability.value)
        )

    @staticmethod
    def _require_mapping(value: JsonValue) -> Mapping[str, object]:
        if not isinstance(value, Mapping):
            raise ValueError("capability probe响应不是对象。")
        return cast(Mapping[str, object], value)
