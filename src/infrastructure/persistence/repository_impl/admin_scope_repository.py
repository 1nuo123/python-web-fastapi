"""管理员 scope 仓储。"""

from __future__ import annotations

from sqlalchemy import select

from src.application.admin.identity.shared.admin_identity_command import (
    AdminScopeCreateCommand,
    AdminScopeDeleteCommand,
    AdminScopeUpdateCommand,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityDeleteResult,
    AdminScopeKind,
    AdminScopeListQuery,
    AdminScopeSnapshot,
)
from src.domain.auth.admin_route_authorization_policy import (
    PROTECTED_ADMIN_SCOPE_CODES,
)
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.infrastructure.persistence.orm_model.auth_role_scope_orm_model import (
    AuthRoleScopeOrmModel,
)
from src.infrastructure.persistence.orm_model.auth_scope_orm_model import AuthScopeOrmModel
from src.infrastructure.persistence.repository_impl.admin_identity_repository_support import (
    BOUND_SCOPE_DELETE_BLOCKED_MESSAGE,
    BUILTIN_SCOPE_DELETE_BLOCKED_MESSAGE,
    BUILTIN_SCOPE_DISABLE_BLOCKED_MESSAGE,
    DELETE_ACCEPTED_REASON,
    SCOPE_ALREADY_EXISTS_MESSAGE,
    SCOPE_NOT_FOUND_MESSAGE,
    AdminIdentityRepositorySupport,
)


class AdminScopeRepository(AdminIdentityRepositorySupport):
    """管理员 scope 仓储实现。"""

    def sync_scope_catalog(self, scope_codes: list[str]) -> None:
        """
        同步 scope 目录。

        :param scope_codes: 需要确保存在的 scope 编码。
        :type scope_codes: list[str]
        :returns: 无返回值。
        :rtype: None
        """

        for scope_code in self._normalize_unique_values(
            [scope.value for scope in AuthScopeCode] + scope_codes
        ):
            if self._get_scope_row(scope_code) is not None:
                continue
            self._session.add(
                AuthScopeOrmModel(
                    scope_code=scope_code,
                    scope_name=scope_code,
                    description=None,
                    scope_kind=self._resolve_scope_kind(scope_code).value,
                    enabled=True,
                )
            )

    def list_scopes(self, query: AdminScopeListQuery) -> list[AdminScopeSnapshot]:
        """
        查询 scope 列表。
        """

        snapshots = self._list_all_scope_snapshots()
        snapshots = [
            snapshot
            for snapshot in snapshots
            if self._matches_scope_query(snapshot=snapshot, query=query)
        ]
        return sorted(snapshots, key=lambda snapshot: snapshot.scope_code)[: query.limit]

    def get_scope(self, scope_code: str) -> AdminScopeSnapshot:
        """
        读取 scope 详情。
        """

        snapshot = self._get_scope_snapshot_or_none(scope_code)
        if snapshot is None:
            self._raise_not_found(SCOPE_NOT_FOUND_MESSAGE)
        return snapshot

    def create_scope(self, command: AdminScopeCreateCommand) -> AdminScopeSnapshot:
        """
        创建 scope。
        """

        if (
            self._is_builtin_scope(command.scope_code)
            or self._get_scope_row(command.scope_code) is not None
        ):
            self._raise_conflict(SCOPE_ALREADY_EXISTS_MESSAGE)
        self._session.add(
            AuthScopeOrmModel(
                scope_code=command.scope_code,
                scope_name=command.scope_name,
                description=command.description,
                scope_kind=AdminScopeKind.CUSTOM.value,
                enabled=command.enabled,
            )
        )
        self._session.flush()
        return self.get_scope(command.scope_code)

    def update_scope(self, command: AdminScopeUpdateCommand) -> AdminScopeSnapshot:
        """
        更新 scope。
        """

        row = self._get_scope_row(command.scope_code)
        if row is None and self._is_builtin_scope(command.scope_code):
            row = AuthScopeOrmModel(
                scope_code=command.scope_code,
                scope_name=command.scope_code,
                description=None,
                scope_kind=AdminScopeKind.BUILTIN.value,
                enabled=True,
            )
            self._session.add(row)
        if row is None:
            self._raise_not_found(SCOPE_NOT_FOUND_MESSAGE)
        if command.enabled is False and command.scope_code in PROTECTED_ADMIN_SCOPE_CODES:
            self._raise_conflict(BUILTIN_SCOPE_DISABLE_BLOCKED_MESSAGE)
        self._lock_user_table_for_admin_access_invariant()
        self._validate_actor_after_scope_change(command=command)
        if command.scope_name is not None:
            row.scope_name = command.scope_name
        if command.description is not None:
            row.description = command.description
        if command.enabled is not None:
            row.enabled = command.enabled
        self._session.flush()
        self._assert_admin_access_invariant()
        return self.get_scope(command.scope_code)

    def delete_scope(self, command: AdminScopeDeleteCommand) -> AdminIdentityDeleteResult:
        """
        删除 scope。
        """

        if self._is_builtin_scope(command.scope_code):
            self._raise_conflict(BUILTIN_SCOPE_DELETE_BLOCKED_MESSAGE)
        row = self._get_scope_row(command.scope_code)
        if row is None:
            self._raise_not_found(SCOPE_NOT_FOUND_MESSAGE)
        if self._count_scope_bindings(command.scope_code) > 0:
            self._raise_conflict(BOUND_SCOPE_DELETE_BLOCKED_MESSAGE)
        self._session.delete(row)
        self._session.flush()
        return AdminIdentityDeleteResult(
            target_id=command.scope_code,
            deleted=True,
            reason=DELETE_ACCEPTED_REASON,
        )

    def _list_all_scope_snapshots(self) -> list[AdminScopeSnapshot]:
        """
        列出全部 scope 快照，并补齐枚举内置 scope。
        """

        rows = list(self._session.scalars(select(AuthScopeOrmModel)).all())
        row_by_code = {row.scope_code: row for row in rows}
        builtin_scope_codes = {scope.value for scope in AuthScopeCode}
        snapshots = [
            self._build_scope_snapshot(
                row_by_code[scope_code],
                forced_kind=AdminScopeKind.BUILTIN,
            )
            if scope_code in row_by_code
            else AdminScopeSnapshot(
                scope_code=scope_code,
                scope_name=scope_code,
                description=None,
                scope_kind=AdminScopeKind.BUILTIN,
                enabled=True,
            )
            for scope_code in builtin_scope_codes
        ]
        snapshots.extend(
            self._build_scope_snapshot(row, forced_kind=AdminScopeKind.CUSTOM)
            for row in rows
            if row.scope_code not in builtin_scope_codes
        )
        return snapshots

    def _get_scope_snapshot_or_none(
        self,
        scope_code: str,
    ) -> AdminScopeSnapshot | None:
        """
        读取 scope 快照，内置 scope 可由枚举补齐。
        """

        row = self._get_scope_row(scope_code)
        if row is not None:
            return self._build_scope_snapshot(
                row,
                forced_kind=self._resolve_scope_kind(scope_code),
            )
        if self._is_builtin_scope(scope_code):
            return AdminScopeSnapshot(
                scope_code=scope_code,
                scope_name=scope_code,
                description=None,
                scope_kind=AdminScopeKind.BUILTIN,
                enabled=True,
            )
        return None

    def _get_scope_row(self, scope_code: str) -> AuthScopeOrmModel | None:
        """
        读取 scope ORM 行。
        """

        return self._session.get(AuthScopeOrmModel, scope_code)

    def _build_scope_snapshot(
        self,
        row: AuthScopeOrmModel,
        *,
        forced_kind: AdminScopeKind | None = None,
    ) -> AdminScopeSnapshot:
        """
        构建 scope 快照。
        """

        return AdminScopeSnapshot(
            scope_code=row.scope_code,
            scope_name=row.scope_name,
            description=row.description,
            scope_kind=forced_kind or AdminScopeKind(row.scope_kind),
            enabled=row.enabled,
        )

    def _matches_scope_query(
        self,
        *,
        snapshot: AdminScopeSnapshot,
        query: AdminScopeListQuery,
    ) -> bool:
        """
        判断 scope 是否命中查询条件。
        """

        if query.enabled is not None and snapshot.enabled != query.enabled:
            return False
        if query.keyword is None:
            return True
        keyword = query.keyword.lower()
        return (
            keyword in snapshot.scope_code.lower()
            or keyword in snapshot.scope_name.lower()
            or (snapshot.description is not None and keyword in snapshot.description.lower())
        )

    def _count_scope_bindings(self, scope_code: str) -> int:
        """
        统计 scope 绑定角色数量。
        """

        statement = select(AuthRoleScopeOrmModel).where(
            AuthRoleScopeOrmModel.scope_code == scope_code
        )
        return len(list(self._session.scalars(statement).all()))

    def _resolve_scope_kind(self, scope_code: str) -> AdminScopeKind:
        """
        解析 scope 类型。
        """

        if self._is_builtin_scope(scope_code):
            return AdminScopeKind.BUILTIN
        return AdminScopeKind.CUSTOM

    def _is_builtin_scope(self, scope_code: str) -> bool:
        """
        判断 scope 是否为内置枚举值。
        """

        return scope_code in {scope.value for scope in AuthScopeCode}
