"""Agent 本地 thread 历史容量索引。"""

from __future__ import annotations

from pathlib import Path


class AgentThreadHistoryCapacityRegistry:
    """只在内存中记录已确认超过远程读取上限的 rollout。"""

    def __init__(self, *, max_source_bytes: int) -> None:
        if max_source_bytes <= 0:
            raise ValueError("thread历史源文件上限必须大于零。")
        self._max_source_bytes = max_source_bytes
        self._oversized_thread_ids: set[str] = set()

    def register(self, thread_id: str, rollout_path: object) -> None:
        """读取本地文件元数据，不保存或暴露绝对路径。"""

        if not thread_id or not isinstance(rollout_path, str) or not rollout_path:
            return
        path = Path(rollout_path)
        if not path.is_absolute():
            return
        try:
            source_bytes = path.stat().st_size
        except OSError:
            return
        if source_bytes > self._max_source_bytes:
            self._oversized_thread_ids.add(thread_id)
            return
        self._oversized_thread_ids.discard(thread_id)

    def should_omit(self, thread_id: str) -> bool:
        """返回该 thread 是否应跳过完整历史读取。"""

        return thread_id in self._oversized_thread_ids
