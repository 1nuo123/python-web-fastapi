"""本机有界历史补充：保留官方实时身份和官方历史未持久化的工具记录。"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from src.core.codex_contract.app_server_product_contract import (
    AppServerDiffChangedDetail,
    AppServerDiffItem,
    AppServerItemChangedDetail,
    AppServerItemDeltaDetail,
    AppServerNoticeItem,
    AppServerPlanChangedDetail,
    AppServerPlanItem,
    AppServerProductNotificationDetail,
    AppServerProductTimelineItem,
    AppServerThreadReadProductResult,
    AppServerTurnChangedDetail,
)

_ITEM = TypeAdapter(AppServerProductTimelineItem)
_TERMINAL = {"completed", "failed", "interrupted", "cancelled", "systemError"}


@dataclass(frozen=True, slots=True)
class AgentTimelineHistoryWindow:
    items: tuple[AppServerProductTimelineItem, ...]
    total_items: int
    revision: str


class AgentTimelineStore:
    """独立于命令账本；最多 128 MiB/30 天，按完整 turn 淘汰，不落服务端。"""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None)
        # 新缓存启用增量回收，旧缓存仍可正常读取并在淘汰后复用空页。
        self._db.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS timeline_turn (
                thread TEXT NOT NULL, turn TEXT NOT NULL, instance TEXT NOT NULL,
                complete INTEGER NOT NULL DEFAULT 0, updated REAL NOT NULL,
                PRIMARY KEY(thread, turn));
            CREATE TABLE IF NOT EXISTS timeline_item (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, thread TEXT NOT NULL,
                turn TEXT NOT NULL, item TEXT NOT NULL, payload TEXT NOT NULL,
                UNIQUE(thread, turn, item));
            CREATE INDEX IF NOT EXISTS timeline_item_window ON timeline_item(thread, turn, seq);
        """)
        self._instance = uuid4().hex
        self._last_prune = time.monotonic()
        self._streaming: OrderedDict[tuple[str, str, str], AppServerProductTimelineItem] = (
            OrderedDict()
        )
        self._prune()

    def close(self) -> None:
        self._db.close()

    def capture(self, detail: AppServerProductNotificationDetail) -> None:
        if isinstance(detail, (AppServerPlanChangedDetail, AppServerDiffChangedDetail)):
            item = (
                AppServerPlanItem(
                    item_id=f"plan-{detail.turn_id}",
                    explanation=detail.explanation or "",
                    steps=detail.steps,
                )
                if isinstance(detail, AppServerPlanChangedDetail)
                else AppServerDiffItem(
                    item_id=f"diff-{detail.turn_id}", unified_diff=detail.unified_diff
                )
            )
            self.capture(
                AppServerItemChangedDetail(
                    thread_id=detail.thread_id,
                    turn_id=detail.turn_id,
                    item=item,
                    status="completed",
                )
            )
        elif isinstance(detail, AppServerTurnChangedDetail):
            if detail.status not in _TERMINAL:
                self._db.execute(
                    "INSERT OR IGNORE INTO timeline_turn(thread,turn,instance,updated) VALUES(?,?,?,?)",
                    (detail.thread_id, detail.turn_id, self._instance, time.time()),
                )
            else:
                for key, item in tuple(self._streaming.items()):
                    if key[:2] == (detail.thread_id, detail.turn_id):
                        if item.kind in {"command", "diff"} and item.status == "inProgress":
                            item = item.model_copy(update={"status": "failed"})
                        self._db.execute(
                            "UPDATE timeline_item SET payload=? WHERE thread=? AND turn=? AND item=?",
                            (item.model_dump_json(), *key),
                        )
                self._db.execute(
                    "UPDATE timeline_turn SET complete=1, updated=? WHERE thread=? AND turn=? AND instance=?",
                    (time.time(), detail.thread_id, detail.turn_id, self._instance),
                )
                self._streaming = OrderedDict(
                    (key, value)
                    for key, value in self._streaming.items()
                    if key[:2] != (detail.thread_id, detail.turn_id)
                )
                self._prune()
        elif isinstance(detail, AppServerItemChangedDetail) and detail.turn_id:
            key = (detail.thread_id, detail.turn_id, detail.item.item_id)
            self._db.execute(
                "INSERT INTO timeline_item(thread,turn,item,payload) VALUES(?,?,?,?) "
                "ON CONFLICT(thread,turn,item) DO UPDATE SET payload=excluded.payload",
                (*key, detail.item.model_dump_json()),
            )
            if time.monotonic() - self._last_prune > 30:
                self._prune()
                self._last_prune = time.monotonic()
            if detail.status == "completed":
                self._streaming.pop(key, None)
            else:
                self._streaming[key] = detail.item
                while len(self._streaming) > 256:
                    dropped, item = self._streaming.popitem(last=False)
                    self._db.execute(
                        "UPDATE timeline_item SET payload=? WHERE thread=? AND turn=? AND item=?",
                        (item.model_dump_json(), *dropped),
                    )
                    self._db.execute(
                        "DELETE FROM timeline_turn WHERE thread=? AND turn=?", dropped[:2]
                    )
        elif isinstance(detail, AppServerItemDeltaDetail):
            key = (detail.thread_id, detail.turn_id, detail.item_id)
            item = self._streaming.get(key)
            if item is not None:
                field = "output" if item.kind == "command" else "text"
                current = getattr(item, field, None)
                if isinstance(current, str):
                    self._streaming[key] = item.model_copy(
                        update={field: (current + detail.delta)[-1_048_576:]}
                    )

    def read_history_window(
        self, thread_id: str, turn_id: str, *, offset: int, limit: int
    ) -> AgentTimelineHistoryWindow | None:
        """在已有完整性事实下分页读取本机工具记录，不再取出整个turn。"""
        record = self._db.execute(
            "SELECT instance,complete,updated FROM timeline_turn WHERE thread=? AND turn=?",
            (thread_id, turn_id),
        ).fetchone()
        if record is None or not (record[1] or record[0] == self._instance):
            return None
        total, last_seq = self._db.execute(
            "SELECT COUNT(*),MAX(seq) FROM timeline_item WHERE thread=? AND turn=?",
            (thread_id, turn_id),
        ).fetchone()
        rows = self._db.execute(
            "SELECT item,payload FROM timeline_item WHERE thread=? AND turn=? ORDER BY seq DESC LIMIT ? OFFSET ?",
            (thread_id, turn_id, limit, offset),
        ).fetchall()
        items = tuple(
            self._streaming.get((thread_id, turn_id, item_id)) or _ITEM.validate_json(payload)
            for item_id, payload in rows
        )
        revision = hashlib.sha256(f"{record}:{total}:{last_seq}".encode()).hexdigest()
        return AgentTimelineHistoryWindow(items=items, total_items=total, revision=revision)

    def refresh_history_window(
        self, snapshot: AppServerThreadReadProductResult
    ) -> AppServerThreadReadProductResult:
        """发送前原子刷新本窗口的已记录item；覆盖证明不等同于整个turn完整。"""
        turns = []
        covered: list[str] = []
        thread_id = snapshot.thread.thread_id
        for turn in snapshot.turns:
            items = []
            for item in turn.items:
                latest = self._streaming.get((thread_id, turn.turn_id, item.item_id))
                if latest is None:
                    record = self._db.execute(
                        "SELECT payload FROM timeline_item WHERE thread=? AND turn=? AND item=?",
                        (thread_id, turn.turn_id, item.item_id),
                    ).fetchone()
                    latest = _ITEM.validate_json(record[0]) if record is not None else None
                items.append(latest or item)
                if latest is not None:
                    covered.append(item.item_id)
            turns.append(turn.model_copy(update={"items": tuple(items)}))
        return snapshot.model_copy(
            update={"turns": tuple(turns), "covered_item_ids": tuple(covered)}
        )

    def supplement(
        self, snapshot: AppServerThreadReadProductResult
    ) -> AppServerThreadReadProductResult:
        thread_id = snapshot.thread.thread_id
        turns = []
        for turn in snapshot.turns:
            record = self._db.execute(
                "SELECT instance,complete FROM timeline_turn WHERE thread=? AND turn=?",
                (thread_id, turn.turn_id),
            ).fetchone()
            covered = record is not None and (
                bool(record[1]) or (record[0] == self._instance and turn.status not in _TERMINAL)
            )
            if covered:
                items = tuple(
                    self._streaming.get((thread_id, turn.turn_id, item_id))
                    or _ITEM.validate_json(payload)
                    for item_id, payload in self._db.execute(
                        "SELECT item,payload FROM timeline_item WHERE thread=? AND turn=? ORDER BY seq",
                        (thread_id, turn.turn_id),
                    )
                )
                turns.append(turn.model_copy(update={"items": items, "items_complete": True}))
            else:
                warning = AppServerNoticeItem(
                    item_id=f"history-coverage-{turn.turn_id}",
                    label="历史记录范围",
                    text="本机官方历史未提供完整工具输出和实时身份；该轮旧工具记录可能无法恢复。",
                )
                turns.append(
                    turn.model_copy(
                        update={"items": (*turn.items, warning), "items_complete": False}
                    )
                )
        return snapshot.model_copy(update={"turns": tuple(turns)})

    def _prune(self) -> None:
        cutoff = time.time() - 30 * 86400
        with self._db:
            self._db.execute("DELETE FROM timeline_turn WHERE updated < ?", (cutoff,))
            self._db.execute(
                "DELETE FROM timeline_item WHERE NOT EXISTS (SELECT 1 FROM timeline_turn t WHERE t.thread=timeline_item.thread AND t.turn=timeline_item.turn)"
            )
            total = self._db.execute(
                "SELECT COALESCE(SUM(length(CAST(payload AS BLOB))),0) FROM timeline_item"
            ).fetchone()[0]
            while total > 128 * 1024 * 1024:
                oldest = self._db.execute(
                    "SELECT thread,turn FROM timeline_turn ORDER BY updated LIMIT 1"
                ).fetchone()
                if oldest is None:
                    break
                size = self._db.execute(
                    "SELECT COALESCE(SUM(length(CAST(payload AS BLOB))),0) FROM timeline_item WHERE thread=? AND turn=?",
                    oldest,
                ).fetchone()[0]
                self._db.execute("DELETE FROM timeline_item WHERE thread=? AND turn=?", oldest)
                self._db.execute("DELETE FROM timeline_turn WHERE thread=? AND turn=?", oldest)
                total -= size
            self._db.execute("PRAGMA incremental_vacuum(256)")
