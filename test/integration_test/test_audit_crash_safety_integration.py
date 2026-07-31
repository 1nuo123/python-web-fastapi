"""
审计关键事件崩溃安全集成测试模块。
"""

from __future__ import annotations

import os
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
]

CHILD_PROCESS_TIMEOUT_SECONDS = 60
CHILD_PROCESS_EXIT_CODE = 9
PYTHON_EXECUTE_CODE_ARGUMENT = "-c"
PYTHONPATH_ENV_NAME = "PYTHONPATH"
DATABASE_URL_ENV_NAME = "DATABASE_URL"
CURRENT_WORKDIR = "."
APP_LOG_RECORD_TABLE_NAME = "app_log_record"
EVENT_ID_QUERY_SQL = (
    f"SELECT event_id FROM {APP_LOG_RECORD_TABLE_NAME} "
    "WHERE event_id IN (:standard_event_id, :audit_event_id)"
)
EVENT_ID_CLEANUP_SQL = (
    f"DELETE FROM {APP_LOG_RECORD_TABLE_NAME} "
    "WHERE event_id IN (:standard_event_id, :audit_event_id)"
)
STANDARD_EVENT_ID_BIND = "standard_event_id"
AUDIT_EVENT_ID_BIND = "audit_event_id"
CRASH_CHILD_SCRIPT_TEMPLATE = """
import os

from datetime import UTC, datetime

from sqlalchemy import create_engine

from src.core.logging_contract.log_event_contract import (
    AccessLogDetail,
    LogEventEnvelope,
    LogEventHeader,
    LogEventKind,
    LogLevel,
    LogPersistencePriority,
)
from src.infrastructure.logging.database_log_writer import DatabaseLogWriter
from src.infrastructure.logging.log_buffer_dispatcher import LogBufferDispatcher
from src.infrastructure.persistence.sqlalchemy_session_factory import (
    SqlAlchemySessionFactory,
)
from src.infrastructure.resource_slot.shared_db_session_manager import (
    SharedDbSessionManager,
)

import logging

DATABASE_URL = os.environ["DATABASE_URL"]
STANDARD_EVENT_ID = {standard_event_id!r}
AUDIT_EVENT_ID = {audit_event_id!r}
EXIT_CODE = {exit_code}


def build_event(event_id: str, priority: LogPersistencePriority) -> LogEventEnvelope:
    return LogEventEnvelope(
        header=LogEventHeader(
            event_id=event_id,
            occurred_at=datetime.now(UTC),
            level=LogLevel.INFO,
            kind=LogEventKind.ACCESS,
            persistence_priority=priority,
            message="崩溃安全集成测试事件。",
            source_module="infrastructure",
            source_component="crash_safety_test",
        ),
        detail=AccessLogDetail(
            request_path="/crash-safety",
            request_method="GET",
            status_code=200,
            elapsed_milliseconds=1.0,
        ),
    )


engine = create_engine(DATABASE_URL)
session_manager = SharedDbSessionManager(SqlAlchemySessionFactory(engine))
writer = DatabaseLogWriter(
    session_manager=session_manager,
    logger=logging.getLogger("crash_safety_child"),
    fallback_to_stdout=False,
)
dispatcher = LogBufferDispatcher(
    writer=writer,
    logger=logging.getLogger("crash_safety_child"),
    buffer_max_items=1000,
    flush_interval_seconds=3600,
    max_batch_size=1000,
)
dispatcher.emit(build_event(STANDARD_EVENT_ID, LogPersistencePriority.STANDARD))
dispatcher.emit(build_event(AUDIT_EVENT_ID, LogPersistencePriority.AUDIT_CRITICAL))
os._exit(EXIT_CODE)
"""


class TestAuditCrashSafetyIntegration:
    """
    审计关键事件崩溃安全集成测试集合。
    """

    def test_audit_critical_event_should_survive_forced_process_kill(
        self,
        integration_database: str,
    ) -> None:
        """
        验证进程被强制终止后审计关键事件已落库、普通缓冲日志允许窗口丢失。
        """

        standard_event_id = f"crash-standard-{uuid4().hex}"
        audit_event_id = f"crash-audit-{uuid4().hex}"
        child_environment = os.environ.copy()
        child_environment[PYTHONPATH_ENV_NAME] = CURRENT_WORKDIR
        child_environment[DATABASE_URL_ENV_NAME] = integration_database

        completed_process = subprocess.run(
            [
                sys.executable,
                PYTHON_EXECUTE_CODE_ARGUMENT,
                CRASH_CHILD_SCRIPT_TEMPLATE.format(
                    standard_event_id=standard_event_id,
                    audit_event_id=audit_event_id,
                    exit_code=CHILD_PROCESS_EXIT_CODE,
                ),
            ],
            cwd=CURRENT_WORKDIR,
            env=child_environment,
            capture_output=True,
            text=True,
            timeout=CHILD_PROCESS_TIMEOUT_SECONDS,
            check=False,
        )

        assert completed_process.returncode == CHILD_PROCESS_EXIT_CODE, (
            completed_process.stderr or completed_process.stdout
        )
        engine = create_engine(integration_database)
        try:
            with engine.begin() as connection:
                persisted_event_ids = {
                    row[0]
                    for row in connection.execute(
                        text(EVENT_ID_QUERY_SQL),
                        {
                            STANDARD_EVENT_ID_BIND: standard_event_id,
                            AUDIT_EVENT_ID_BIND: audit_event_id,
                        },
                    )
                }

            assert audit_event_id in persisted_event_ids
            assert standard_event_id not in persisted_event_ids
        finally:
            with engine.begin() as connection:
                connection.execute(
                    text(EVENT_ID_CLEANUP_SQL),
                    {
                        STANDARD_EVENT_ID_BIND: standard_event_id,
                        AUDIT_EVENT_ID_BIND: audit_event_id,
                    },
                )
            engine.dispose()
