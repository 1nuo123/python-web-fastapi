"""修复历史 Codex 审批摘要与过期运行状态。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

REVISION_ID = "202608101300"
DOWN_REVISION_ID = "202608101100"
APPROVAL_AUDIT_TABLE_NAME = "codex_approval_audit"
DISPLAY_SUMMARY_COLUMN_NAME = "display_summary"
RISK_LEVEL_COLUMN_NAME = "risk_level"
STATE_COLUMN_NAME = "state"
VERSION_COLUMN_NAME = "version"
EXPIRES_AT_COLUMN_NAME = "expires_at"
UPDATED_AT_COLUMN_NAME = "updated_at"
WORKSPACE_NAME_FIELD = "workspace_name"
RISK_LEVEL_FIELD = "risk_level"
COMMAND_SUMMARY_FIELD = "command_summary"
FILE_SCOPE_FIELD = "file_scope"
PERMISSION_NAMES_FIELD = "permission_names"
NETWORK_REQUESTED_FIELD = "network_requested"
EXTRA_ROOT_REQUESTED_FIELD = "extra_root_requested"
PENDING_APPROVAL_STATE = "pending"
EXPIRED_APPROVAL_STATE = "expired"
EMPTY_JSON_ARRAY = "[]"

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class Migration:
    """把已部署的旧审批记录迁移到当前冻结契约。"""

    def upgrade(self) -> None:
        """补齐摘要扩展字段，并终结已经超过有效期的待审批记录。"""

        approval_audit = sa.table(
            APPROVAL_AUDIT_TABLE_NAME,
            sa.column(DISPLAY_SUMMARY_COLUMN_NAME, postgresql.JSONB()),
            sa.column(RISK_LEVEL_COLUMN_NAME, sa.String()),
            sa.column(STATE_COLUMN_NAME, sa.String()),
            sa.column(VERSION_COLUMN_NAME, sa.Integer()),
            sa.column(EXPIRES_AT_COLUMN_NAME, sa.DateTime(timezone=True)),
            sa.column(UPDATED_AT_COLUMN_NAME, sa.DateTime(timezone=True)),
        )
        empty_json_array = sa.cast(sa.literal(EMPTY_JSON_ARRAY), postgresql.JSONB())
        summary_defaults = sa.func.jsonb_build_object(
            sa.literal(WORKSPACE_NAME_FIELD),
            sa.cast(sa.null(), sa.Text()),
            sa.literal(RISK_LEVEL_FIELD),
            approval_audit.c[RISK_LEVEL_COLUMN_NAME],
            sa.literal(COMMAND_SUMMARY_FIELD),
            sa.cast(sa.null(), sa.Text()),
            sa.literal(FILE_SCOPE_FIELD),
            empty_json_array,
            sa.literal(PERMISSION_NAMES_FIELD),
            empty_json_array,
            sa.literal(NETWORK_REQUESTED_FIELD),
            sa.false(),
            sa.literal(EXTRA_ROOT_REQUESTED_FIELD),
            sa.false(),
        )
        op.execute(
            sa.update(approval_audit).values(
                {
                    DISPLAY_SUMMARY_COLUMN_NAME: summary_defaults.op("||")(
                        approval_audit.c[DISPLAY_SUMMARY_COLUMN_NAME]
                    )
                }
            )
        )
        op.execute(
            sa.update(approval_audit)
            .where(
                approval_audit.c[STATE_COLUMN_NAME] == PENDING_APPROVAL_STATE,
                approval_audit.c[EXPIRES_AT_COLUMN_NAME].is_not(None),
                approval_audit.c[EXPIRES_AT_COLUMN_NAME] <= sa.func.current_timestamp(),
            )
            .values(
                {
                    STATE_COLUMN_NAME: EXPIRED_APPROVAL_STATE,
                    VERSION_COLUMN_NAME: approval_audit.c[VERSION_COLUMN_NAME] + 1,
                    UPDATED_AT_COLUMN_NAME: sa.func.current_timestamp(),
                }
            )
        )

    def downgrade(self) -> None:
        """保留已经修复的审计数据，避免降级过程破坏历史记录。"""


upgrade = Migration().upgrade
downgrade = Migration().downgrade
