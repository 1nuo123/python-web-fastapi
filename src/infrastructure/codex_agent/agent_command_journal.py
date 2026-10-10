"""使用SQLite实现Agent非幂等命令的崩溃安全去重账本。"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Final, cast
from uuid import UUID, uuid4

from src.core.codex_contract.agent_command_contract import (
    AgentCommandClaim,
    AgentCommandClaimKind,
    AgentCommandIdentity,
    AgentCommandJournalRecord,
    AgentCommandJournalState,
    AgentCommandResultSummary,
)

AGENT_COMMAND_JOURNAL_SCHEMA_VERSION: Final = "1"
SQLITE_MEMORY_PATH: Final = ":memory:"
AGENT_COMMAND_RESTARTED_OUTCOME_CODE: Final = "agent_process_restarted_during_execution"


class AgentCommandDigestConflictError(ValueError):
    """相同command_id被用于不同命令内容。"""


class AgentCommandStateConflictError(ValueError):
    """命令账本状态转换不合法。"""


ALLOWED_AGENT_COMMAND_TRANSITIONS: Final = {
    AgentCommandJournalState.RECEIVED: frozenset(
        {
            AgentCommandJournalState.EXECUTING,
            AgentCommandJournalState.FAILED,
            AgentCommandJournalState.UNKNOWN,
        }
    ),
    AgentCommandJournalState.EXECUTING: frozenset(
        {
            AgentCommandJournalState.ACCEPTED,
            AgentCommandJournalState.COMPLETED,
            AgentCommandJournalState.FAILED,
            AgentCommandJournalState.UNKNOWN,
        }
    ),
    AgentCommandJournalState.ACCEPTED: frozenset(
        {
            AgentCommandJournalState.COMPLETED,
            AgentCommandJournalState.FAILED,
            AgentCommandJournalState.UNKNOWN,
        }
    ),
    AgentCommandJournalState.COMPLETED: frozenset(),
    AgentCommandJournalState.FAILED: frozenset(),
    AgentCommandJournalState.UNKNOWN: frozenset(),
}


class AgentCommandJournal:
    """在调用App Server前落盘，并在重投时回放原结果。"""

    def __init__(self, database_path: str | Path) -> None:
        """打开账本并创建冻结的最小表结构。"""

        database_value = str(database_path)
        if database_value != SQLITE_MEMORY_PATH:
            Path(database_value).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_value, isolation_level=None)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=FULL")
        self._create_schema()

    def close(self) -> None:
        """关闭SQLite连接。"""

        self._connection.close()

    def claim(self, identity: AgentCommandIdentity) -> AgentCommandClaim:
        """原子登记新命令，或返回已存在命令的原状态。"""

        now = time.time()
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._select_row(identity.command_id)
            if row is None:
                self._connection.execute(
                    """
                    INSERT INTO codex_agent_command_journal (
                        command_id,
                        operation_id,
                        command_type,
                        request_digest,
                        state,
                        result_summary_json,
                        created_at_epoch,
                        updated_at_epoch
                    ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?)
                    """,
                    (
                        identity.command_id,
                        identity.operation_id,
                        identity.command_type,
                        identity.request_digest,
                        AgentCommandJournalState.RECEIVED.value,
                        now,
                        now,
                    ),
                )
                self._connection.execute("COMMIT")
                return AgentCommandClaim(
                    kind=AgentCommandClaimKind.NEW,
                    record=AgentCommandJournalRecord(
                        identity=identity,
                        state=AgentCommandJournalState.RECEIVED,
                        result_summary=None,
                        created_at_epoch=now,
                        updated_at_epoch=now,
                    ),
                )
            record = self._build_record(row)
            self._assert_same_identity(expected=record.identity, actual=identity)
            self._connection.execute("COMMIT")
            return AgentCommandClaim(kind=AgentCommandClaimKind.REPLAY, record=record)
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def mark_executing(self, command_id: str) -> AgentCommandJournalRecord:
        """在调用App Server之前标记命令正在执行。"""

        return self._transition(
            command_id=command_id,
            target=AgentCommandJournalState.EXECUTING,
            result_summary=None,
        )

    def mark_accepted(
        self,
        command_id: str,
        *,
        result_summary: AgentCommandResultSummary,
    ) -> AgentCommandJournalRecord:
        """持久化App Server已接受及其上游标识。"""

        return self._transition(
            command_id=command_id,
            target=AgentCommandJournalState.ACCEPTED,
            result_summary=result_summary,
        )

    def mark_completed(
        self,
        command_id: str,
        *,
        result_summary: AgentCommandResultSummary,
    ) -> AgentCommandJournalRecord:
        """持久化命令最终完成摘要。"""

        return self._transition(
            command_id=command_id,
            target=AgentCommandJournalState.COMPLETED,
            result_summary=result_summary,
        )

    def mark_failed(
        self,
        command_id: str,
        *,
        result_summary: AgentCommandResultSummary,
    ) -> AgentCommandJournalRecord:
        """持久化明确失败摘要。"""

        return self._transition(
            command_id=command_id,
            target=AgentCommandJournalState.FAILED,
            result_summary=result_summary,
        )

    def mark_unknown(
        self,
        command_id: str,
        *,
        result_summary: AgentCommandResultSummary,
    ) -> AgentCommandJournalRecord:
        """把无法确认的副作用标记为 unknown，要求人工或快照恢复。"""

        return self._transition(
            command_id=command_id,
            target=AgentCommandJournalState.UNKNOWN,
            result_summary=result_summary,
        )

    def read(self, command_id: str) -> AgentCommandJournalRecord | None:
        """读取命令账本状态。"""

        row = self._select_row(command_id)
        return None if row is None else self._build_record(row)

    def list_recovery_records(self) -> list[AgentCommandJournalRecord]:
        """返回最多 512 个恢复摘要；不含命令参数，优先未确认写操作。"""

        cursor = self._connection.execute(
            """
            SELECT command_id
            FROM codex_agent_command_journal
            WHERE command_type != 'thread.read'
            ORDER BY state IN ('received', 'executing', 'accepted', 'unknown') DESC, updated_at_epoch DESC
            LIMIT 512
            """
        )
        records: list[AgentCommandJournalRecord] = []
        for row in cursor.fetchall():
            record = self.read(str(row["command_id"]))
            if record is not None:
                records.append(record)
        return records

    def load_or_create_event_epoch(self) -> UUID:
        """读取本进程事件 epoch；首次启动生成并持久化一个新 epoch。"""

        row = self._connection.execute(
            "SELECT event_epoch FROM codex_agent_connection_state WHERE state_key = 'current'"
        ).fetchone()
        if row is not None:
            return UUID(str(row[0]))
        epoch = uuid4()
        self._connection.execute(
            """
            INSERT INTO codex_agent_connection_state (
                state_key, event_epoch, next_event_seq, acknowledged_seq
            ) VALUES ('current', ?, 1, 0)
            """,
            (str(epoch),),
        )
        return epoch

    def start_event_epoch(self) -> UUID:
        """为新的 Agent 进程轮换事件 epoch 并重置序号与 ACK。"""

        epoch = uuid4()
        self._connection.execute(
            """
            INSERT INTO codex_agent_connection_state (
                state_key, event_epoch, next_event_seq, acknowledged_seq
            ) VALUES ('current', ?, 1, 0)
            ON CONFLICT(state_key) DO UPDATE SET
                event_epoch = excluded.event_epoch,
                next_event_seq = excluded.next_event_seq,
                acknowledged_seq = excluded.acknowledged_seq
            """,
            (str(epoch),),
        )
        return epoch

    def next_event_seq(self) -> int:
        """为当前 epoch 分配下一个严格递增事件序号。"""

        self._connection.execute(
            "UPDATE codex_agent_connection_state SET next_event_seq = next_event_seq + 1 WHERE state_key = 'current'"
        )
        row = self._connection.execute(
            "SELECT next_event_seq FROM codex_agent_connection_state WHERE state_key = 'current'"
        ).fetchone()
        if row is None:
            raise RuntimeError("Agent事件状态尚未初始化。")
        return int(row[0]) - 1

    def read_event_ack(self) -> tuple[UUID, int]:
        """读取当前 epoch 与服务端累计 ACK。"""

        row = self._connection.execute(
            "SELECT event_epoch, acknowledged_seq FROM codex_agent_connection_state WHERE state_key = 'current'"
        ).fetchone()
        if row is None:
            raise RuntimeError("Agent事件状态尚未初始化。")
        return UUID(str(row[0])), int(row[1])

    def write_event_ack(self, *, epoch: UUID, after_seq: int) -> None:
        """只接受当前 epoch 的单调 ACK。"""

        current_epoch, current_ack = self.read_event_ack()
        if epoch != current_epoch:
            raise ValueError("Agent事件ACK epoch与本地状态不匹配。")
        if after_seq < current_ack:
            return
        self._connection.execute(
            "UPDATE codex_agent_connection_state SET acknowledged_seq = ? WHERE state_key = 'current'",
            (after_seq,),
        )

    def _transition(
        self,
        *,
        command_id: str,
        target: AgentCommandJournalState,
        result_summary: AgentCommandResultSummary | None,
    ) -> AgentCommandJournalRecord:
        """执行带状态前置条件的原子转换。"""

        self._connection.execute("BEGIN IMMEDIATE")
        try:
            row = self._select_row(command_id)
            if row is None:
                raise KeyError(f"Agent命令不存在: {command_id}")
            current = AgentCommandJournalState(str(row["state"]))
            if target not in ALLOWED_AGENT_COMMAND_TRANSITIONS[current]:
                raise AgentCommandStateConflictError(
                    f"Agent命令状态不能从{current.value}转换为{target.value}。"
                )
            now = time.time()
            result_summary_json = (
                result_summary.model_dump_json() if result_summary is not None else None
            )
            self._connection.execute(
                """
                UPDATE codex_agent_command_journal
                SET state = ?, result_summary_json = ?, updated_at_epoch = ?
                WHERE command_id = ?
                """,
                (target.value, result_summary_json, now, command_id),
            )
            updated = self._select_row(command_id)
            if updated is None:
                raise RuntimeError("Agent命令状态更新后记录丢失。")
            self._connection.execute("COMMIT")
            return self._build_record(updated)
        except Exception:
            self._connection.execute("ROLLBACK")
            raise

    def _select_row(self, command_id: str) -> sqlite3.Row | None:
        """按稳定command_id读取单条记录。"""

        cursor = self._connection.execute(
            """
            SELECT
                command_id,
                operation_id,
                command_type,
                request_digest,
                state,
                result_summary_json,
                created_at_epoch,
                updated_at_epoch
            FROM codex_agent_command_journal
            WHERE command_id = ?
            """,
            (command_id,),
        )
        return cast(sqlite3.Row | None, cursor.fetchone())

    def _build_record(self, row: sqlite3.Row) -> AgentCommandJournalRecord:
        """把SQLite行转换为强类型账本记录。"""

        result_payload = row["result_summary_json"]
        return AgentCommandJournalRecord(
            identity=AgentCommandIdentity(
                command_id=str(row["command_id"]),
                operation_id=str(row["operation_id"]),
                command_type=str(row["command_type"]),
                request_digest=str(row["request_digest"]),
            ),
            state=AgentCommandJournalState(str(row["state"])),
            result_summary=(
                AgentCommandResultSummary.model_validate_json(str(result_payload))
                if result_payload is not None
                else None
            ),
            created_at_epoch=float(row["created_at_epoch"]),
            updated_at_epoch=float(row["updated_at_epoch"]),
        )

    def _assert_same_identity(
        self,
        *,
        expected: AgentCommandIdentity,
        actual: AgentCommandIdentity,
    ) -> None:
        """阻止同一command_id被替换为不同副作用。"""

        if expected != actual:
            raise AgentCommandDigestConflictError(
                "相同command_id的operation、类型或request_digest不一致。"
            )

    def _create_schema(self) -> None:
        """创建Phase 0冻结的最小命令账本。"""

        self._connection.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS codex_agent_journal_meta (
                schema_version TEXT PRIMARY KEY
            );
            INSERT OR IGNORE INTO codex_agent_journal_meta(schema_version)
            VALUES ('{AGENT_COMMAND_JOURNAL_SCHEMA_VERSION}');

            CREATE TABLE IF NOT EXISTS codex_agent_command_journal (
                command_id TEXT PRIMARY KEY,
                operation_id TEXT NOT NULL,
                command_type TEXT NOT NULL,
                request_digest TEXT NOT NULL,
                state TEXT NOT NULL,
                result_summary_json TEXT,
                created_at_epoch REAL NOT NULL,
                updated_at_epoch REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS codex_agent_connection_state (
                state_key TEXT PRIMARY KEY,
                event_epoch TEXT NOT NULL,
                next_event_seq INTEGER NOT NULL,
                acknowledged_seq INTEGER NOT NULL
            );
            """
        )
        self._recover_interrupted_commands()
        self.start_event_epoch()

    def _recover_interrupted_commands(self) -> None:
        """进程重启时把可能已产生副作用的命令收敛为 unknown。"""

        now = time.time()
        summary = AgentCommandResultSummary(
            outcome_code=AGENT_COMMAND_RESTARTED_OUTCOME_CODE
        ).model_dump_json()
        self._connection.execute(
            """
            UPDATE codex_agent_command_journal
            SET state = ?, result_summary_json = ?, updated_at_epoch = ?
            WHERE state IN ('executing', 'accepted')
            """,
            (AgentCommandJournalState.UNKNOWN.value, summary, now),
        )
