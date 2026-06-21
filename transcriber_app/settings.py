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
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path

    def load(self) -> dict[str, Any]:
        if not self.file_path.exists():
            return DEFAULT_SETTINGS.copy()

        try:
            settings = json.loads(self.file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DEFAULT_SETTINGS.copy()

        merged = DEFAULT_SETTINGS.copy()
        for key in DEFAULT_SETTINGS:
            if key in settings:
                merged[key] = settings[key]
        return merged

    def save(self, settings: dict[str, Any]) -> None:
        payload = DEFAULT_SETTINGS.copy()
        payload.update(settings)
        self.file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")