"""收紧 Codex 设备指纹唯一性与主机所有权不可变约束。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

REVISION_ID = "202608101000"
DOWN_REVISION_ID = "202608081000"
ACTIVE_FINGERPRINT_INDEX_NAME = "uq_codex_host_device_key_active_fingerprint"
HOST_OWNER_TRIGGER_NAME = "trg_codex_host_owner_immutable"
HOST_OWNER_FUNCTION_NAME = "prevent_codex_host_owner_change"

revision = REVISION_ID
down_revision = DOWN_REVISION_ID
branch_labels = None
depends_on = None


class Migration:
    """建立数据库层的设备独占安全门。"""

    def upgrade(self) -> None:
        """增加未撤销指纹全局唯一索引和主机所有者保护触发器。"""

        op.create_index(
            ACTIVE_FINGERPRINT_INDEX_NAME,
            "codex_host_device_key",
            ["fingerprint"],
            unique=True,
            postgresql_where=sa.text("revoked_at IS NULL"),
        )
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION {HOST_OWNER_FUNCTION_NAME}()
                RETURNS trigger AS $$
                BEGIN
                    IF NEW.owner_subject_id IS DISTINCT FROM OLD.owner_subject_id THEN
                        RAISE EXCEPTION 'Codex主机所有者创建后不可修改。';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;

                CREATE TRIGGER {HOST_OWNER_TRIGGER_NAME}
                BEFORE UPDATE OF owner_subject_id ON codex_host
                FOR EACH ROW EXECUTE FUNCTION {HOST_OWNER_FUNCTION_NAME}();
                """
            )
        )

    def downgrade(self) -> None:
        """删除所有权保护触发器和活动指纹唯一索引。"""

        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {HOST_OWNER_TRIGGER_NAME} ON codex_host"))
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS {HOST_OWNER_FUNCTION_NAME}()"))
        op.drop_index(ACTIVE_FINGERPRINT_INDEX_NAME, table_name="codex_host_device_key")


upgrade = Migration().upgrade
downgrade = Migration().downgrade
