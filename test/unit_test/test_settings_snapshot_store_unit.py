"""
?????????????
"""

from __future__ import annotations

from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import AppEnvironment
from src.infrastructure.settings.settings_snapshot_store import (
    SettingsSnapshot,
    SettingsSnapshotStore,
)

SNAPSHOT_VERSION_ID = "settings-snapshot-version"
SNAPSHOT_DIGEST = "settings-snapshot-digest"
SNAPSHOT_MUTATED_APP_NAME = "mutated-app-name"


class TestSettingsSnapshotStoreUnit:
    """
    ?????????????
    """

    def test_store_should_save_and_load_deep_copied_snapshot(self) -> None:
        """
        ????????????????????
        """

        settings = AppSettingsLoader().load_for_environment(AppEnvironment.TEST)
        store = SettingsSnapshotStore()
        store.save(
            SettingsSnapshot(
                version_id=SNAPSHOT_VERSION_ID,
                digest=SNAPSHOT_DIGEST,
                settings=settings,
            )
        )

        first_loaded_snapshot = store.load_latest()
        assert first_loaded_snapshot is not None
        assert first_loaded_snapshot.version_id == SNAPSHOT_VERSION_ID
        assert first_loaded_snapshot.digest == SNAPSHOT_DIGEST
        assert first_loaded_snapshot.settings is not settings
        first_loaded_snapshot.settings.app.name = SNAPSHOT_MUTATED_APP_NAME

        second_loaded_snapshot = store.load_latest()

        assert second_loaded_snapshot is not None
        assert second_loaded_snapshot.settings.app.name == settings.app.name
