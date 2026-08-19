from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_SETTINGS = {
    "language": "Auto-Detect",
    "model": "base (fast)",
    "speed": "Standard",
    "transcript_view": "Raw",
    "clip_start": "",
    "clip_end": "",
    "geometry": "980x720",
    "ffmpeg_warning_shown": False,
}


class SettingsManager:
    def __init__(self, file_path: Path, legacy_file_path: Path | None = None) -> None:
        self.file_path = file_path
        self.legacy_file_path = legacy_file_path

    def load(self) -> dict[str, Any]:
        source = self.file_path
        if not source.exists():
            source = self._find_legacy_settings_file()
        if source is None:
            return DEFAULT_SETTINGS.copy()

        try:
            settings = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DEFAULT_SETTINGS.copy()

        merged = DEFAULT_SETTINGS.copy()
        for key in DEFAULT_SETTINGS:
            if key in settings:
                merged[key] = settings[key]
        return merged

    def _find_legacy_settings_file(self) -> Path | None:
        """Return the pre-rename settings file when it is the only one present."""
        if self.legacy_file_path is not None and self.legacy_file_path.exists():
            return self.legacy_file_path
        return None

    def save(self, settings: dict[str, Any]) -> None:
        payload = DEFAULT_SETTINGS.copy()
        payload.update(settings)
        self.file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")