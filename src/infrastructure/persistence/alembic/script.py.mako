"""${message}"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


class Migration:
    """定义迁移逻辑。"""

    def upgrade(self) -> None:
${upgrades if upgrades else "        pass"}

    def downgrade(self) -> None:
${downgrades if downgrades else "        pass"}


upgrade = Migration().upgrade
downgrade = Migration().downgrade
