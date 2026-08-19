from __future__ import annotations

from pathlib import Path


APP_NAME = "MemoMorf"
APP_VERSION = "1.5.0"
APP_DIR = Path(__file__).resolve().parent.parent
MODEL_CACHE_DIR = APP_DIR / ".models"
SETTINGS_FILE = APP_DIR / ".memomorf_settings.json"
LEGACY_SETTINGS_FILE = APP_DIR / ".transcriber_settings.json"

TRANSCRIPT_VIEW_MODES = (
    "Raw",
    "Paragraphs",
    "Speaker-labeled",
    "Speaker-labeled paragraphs",
)
DEFAULT_TRANSCRIPT_VIEW_MODE = TRANSCRIPT_VIEW_MODES[0]

PARAGRAPH_BREAK_SECONDS = 1.75
SPEAKER_DIARIZATION_MODEL = "pyannote/speaker-diarization-community-1"

SUPPORTED_EXTENSIONS = (".m4a", ".mp3", ".wav", ".aac", ".3gp", ".mp4")
COMPRESSED_EXTENSIONS = {".m4a", ".mp3", ".aac", ".3gp", ".mp4"}
SUPPORTED_FILE_DIALOG_PATTERN = " ".join(f"*{extension}" for extension in SUPPORTED_EXTENSIONS)
COMPRESSED_EXTENSIONS_LABEL = ", ".join(sorted(COMPRESSED_EXTENSIONS))

LANGUAGE_MAP = {
    "Auto-Detect": None,
    "German": "de",
    "English": "en",
}

MODEL_UI_LABELS = {
    "base (fast)": "base",
    "small (balanced)": "small",
    "medium (precise)": "medium",
}

MODEL_DISPLAY_ORDER = ("base", "small", "medium")
MODEL_DISPLAY_NAMES = {
    "base": "base",
    "small": "small",
    "medium": "medium",
}

MODEL_REPOSITORY_MAP = {
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
}

MODEL_REQUIRED_FILES = {
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
}

FAST_MODE_SETTINGS = {
    "vad_filter": False,
    "beam_size": 1,
    "best_of": 1,
    "condition_on_previous_text": False,
}

ULTRA_FAST_MODE_SETTINGS = {
    "vad_filter": False,
    "beam_size": 1,
    "best_of": 1,
    "condition_on_previous_text": False,
    "temperature": 0.0,
    "word_timestamps": False,
}

TRANSCRIPTION_PRESETS = {
    "Standard": {
        "vad_filter": True,
    },
    "Fast": FAST_MODE_SETTINGS,
    "Ultra Fast": ULTRA_FAST_MODE_SETTINGS,
}