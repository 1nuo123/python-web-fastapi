"""
日志脱敏异常路径测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from http import HTTPStatus

from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.logging_contract.log_event_contract import RequestLogContext
from src.infrastructure.logging.database_log_writer import DatabaseLogWriter
from src.infrastructure.logging.log_event_builder import LogEventBuilder

SENSITIVE_DATABASE_URL = "postgresql+psycopg://user:secret-password@db:5432/app"
SENSITIVE_BEARER_TOKEN = "Bearer abcdefghijklmnopqrstuvwxyz0123456789"
SENSITIVE_JWT_TEXT = "aaaaaaaaaa.bbbbbbbbbb.cccccccccc"
SENSITIVE_PASSWORD_TEXT = "password=plain-secret"
REQUEST_ID = "request-redaction"
REQUEST_PATH = "/redaction"
REQUEST_METHOD = "GET"
ERROR_CODE = "INTERNAL_ERROR"


@dataclass(slots=True)
class CapturingLogger:
    """
    捕获降级日志输出的测试日志器。
    """

    records: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    def error(self, message: str, *arguments: object) -> None:
        """
        捕获 error 调用。
        """

        self.records.append((message, arguments))


class TestLoggingRedactionException:
    """
    日志脱敏异常路径测试集合。
    """

    def test_exception_event_when_detail_contains_secret_should_redact_detail(self) -> None:
        """
        验证异常日志 detail 应脱敏。
        """

        event = LogEventBuilder().build_exception_event(
            request_context=self._build_request_context(),
            exception=HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=ERROR_CODE,
                message="内部错误。",
                detail=f"{SENSITIVE_DATABASE_URL} {SENSITIVE_BEARER_TOKEN}",
            ),
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_code=ERROR_CODE,
            include_traceback=False,
        )

        assert "secret-password" not in str(event.detail.detail)
        assert SENSITIVE_BEARER_TOKEN not in str(event.detail.detail)
        assert "***" in str(event.detail.detail)

    def test_exception_event_when_traceback_contains_secret_should_redact_traceback(
        self,
    ) -> None:
        """
        验证异常日志 traceback 应二次脱敏。
        """

        exception = self._build_runtime_error()
        event = LogEventBuilder().build_exception_event(
            request_context=self._build_request_context(),
            exception=exception,
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_code=ERROR_CODE,
            include_traceback=True,
        )

        assert event.detail.traceback_text is not None
        assert "secret-password" not in event.detail.traceback_text
        assert SENSITIVE_PASSWORD_TEXT not in event.detail.traceback_text
        assert SENSITIVE_JWT_TEXT not in event.detail.traceback_text
        assert "***" in event.detail.traceback_text

    def test_database_log_writer_when_fallback_stdout_should_redact_event_json(
        self,
    ) -> None:
        """
        验证数据库日志降级输出应先脱敏事件 JSON。
        """

        logger = CapturingLogger()
        event = LogEventBuilder().build_exception_event(
            request_context=self._build_request_context(),
            exception=RuntimeError(SENSITIVE_DATABASE_URL),
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            error_code=ERROR_CODE,
            include_traceback=False,
        )
        writer = DatabaseLogWriter(
            session_manager=None,
            logger=logger,
            fallback_to_stdout=True,
        )

        writer._fallback_stdout(  # noqa: SLF001
            events=[event],
            failure_reason=SENSITIVE_PASSWORD_TEXT,
        )

        captured_text = " ".join(str(item) for record in logger.records for item in record[1])
        assert "secret-password" not in captured_text
        assert SENSITIVE_PASSWORD_TEXT not in captured_text
        assert "***" in captured_text

    def _build_request_context(self) -> RequestLogContext:
        """
        构建请求日志上下文。
        """

        return RequestLogContext(
            request_id=REQUEST_ID,
            trace_id=None,
            authenticated_subject_id=None,
            request_path=REQUEST_PATH,
            request_method=REQUEST_METHOD,
            client_ip=None,
            user_agent=None,
        )

    def _build_runtime_error(self) -> RuntimeError:
        """
        构建携带敏感文本的运行时异常。
        """

        try:
            raise RuntimeError(
                f"{SENSITIVE_DATABASE_URL} {SENSITIVE_PASSWORD_TEXT} {SENSITIVE_JWT_TEXT}"
            )
        except RuntimeError as exc:
            return exc
