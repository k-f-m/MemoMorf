from __future__ import annotations

import io
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from tqdm.auto import tqdm

from .audio_support import (
    AudioPreviewError,
    AudioSupportError,
    load_audio_visual_data,
    start_audio_preview,
    stop_audio_preview,
)
from .clip_utils import format_timestamp, parse_time_input

from .constants import (
    APP_NAME,
    APP_VERSION,
    COMPRESSED_EXTENSIONS,
    COMPRESSED_EXTENSIONS_LABEL,
    DEFAULT_TRANSCRIPT_VIEW_MODE,
    LANGUAGE_MAP,
    LEGACY_SETTINGS_FILE,
    MODEL_CACHE_DIR,
    MODEL_DISPLAY_NAMES,
    MODEL_DISPLAY_ORDER,
    MODEL_REPOSITORY_MAP,
    MODEL_REQUIRED_FILES,
    MODEL_UI_LABELS,
    SETTINGS_FILE,
    SUPPORTED_EXTENSIONS,
    SUPPORTED_FILE_DIALOG_PATTERN,
    TRANSCRIPT_VIEW_MODES,
    TRANSCRIPTION_PRESETS,
)
from .model_cache import ModelCacheManager, ModelStatusInfo
from .speaker_diarization import (
    SpeakerDiarizationUnavailable,
    SpeakerDiarizer,
    format_speaker_diarization_error_with_diagnostics,
    get_speaker_diarization_diagnostics,
    get_speaker_diarization_prerequisite_issue,
)
from .settings import SettingsManager
from .transcript_processing import TranscriptSegment, render_transcript
from .waveform_selector import WaveformClipSelector

try:
    from faster_whisper import WhisperModel
    from huggingface_hub import hf_hub_download, snapshot_download

    IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - depends on local environment.
    WhisperModel = None
    hf_hub_download = None
    snapshot_download = None
    IMPORT_ERROR = exc


class OperationCancelled(Exception):
    pass


class SilentTqdm(tqdm):
    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("file", io.StringIO())
        kwargs.setdefault("leave", False)
        super().__init__(*args, **kwargs)


def format_size(num_bytes: float) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


class MemoMorfApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title(APP_NAME)
        self.geometry("980x720")
        self.minsize(760, 560)

        self.cache_manager = ModelCacheManager(
            cache_dir=MODEL_CACHE_DIR,
            repository_map=MODEL_REPOSITORY_MAP,
            required_files=MODEL_REQUIRED_FILES,
            display_names=MODEL_DISPLAY_NAMES,
            display_order=MODEL_DISPLAY_ORDER,
        )
        self.settings_manager = SettingsManager(SETTINGS_FILE, LEGACY_SETTINGS_FILE)

        self.selected_file: Path | None = None
        self.transcript_segments: list[TranscriptSegment] = []
        self.speaker_labeled_segments: list[TranscriptSegment] | None = None
        self.worker_thread: threading.Thread | None = None
        self.speaker_thread: threading.Thread | None = None
        self.message_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.loaded_model: WhisperModel | None = None
        self.loaded_model_size: str | None = None
        self.ffmpeg_warning_shown = False
        self.speaker_diarizer = SpeakerDiarizer()
        self.last_speaker_error: str | None = None
        self.audio_duration_seconds: float | None = None
        self.audio_waveform_points: list[float] = []
        self.preview_process: subprocess.Popen[object] | None = None
        self.updating_clip_controls = False

        self.pause_event = threading.Event()
        self.pause_event.set()
        self.stop_event = threading.Event()
        self.is_paused = False
        self.current_activity = "idle"
        self.active_model_key: str | None = None
        self.latest_model_statuses: dict[str, ModelStatusInfo] = {}
        self.model_status_overrides: dict[str, str] = {}

        self.language_var = ctk.StringVar(value="Auto-Detect")
        self.model_var = ctk.StringVar(value="base (fast)")
        self.speed_var = ctk.StringVar(value="Standard")
        self.transcript_view_var = ctk.StringVar(value=DEFAULT_TRANSCRIPT_VIEW_MODE)
        self.clip_start_var = ctk.StringVar(value="")
        self.clip_end_var = ctk.StringVar(value="")
        self.status_var = ctk.StringVar(value="Ready. Select a media file to begin.")
        self.file_var = ctk.StringVar(value="No media file selected yet")
        self.download_var = ctk.StringVar(value="No model activity yet")
        self.version_var = ctk.StringVar(value=f"Version {APP_VERSION}")
        self.selected_downloaded_model_var = ctk.StringVar(value="")
        self.audio_duration_var = ctk.StringVar(value="Duration: No media loaded")
        self.clip_selection_var = ctk.StringVar(value="Selected clip: Full file")
        self.readiness_var = ctk.StringVar(value="Ready check: Select a media file.")

        self._build_ui()
        self._load_settings()
        self._bind_setting_persistence()
        self.refresh_downloaded_models_panel()
        self._update_preview_button_state()
        self._refresh_readiness_state()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(250, self._check_ffmpeg_setup)
        self.after(100, self._poll_queue)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.grid(row=0, column=0, padx=24, pady=(24, 12), sticky="ew")
        header_frame.grid_columnconfigure(0, weight=1)

        header = ctk.CTkLabel(
            header_frame,
            text=APP_NAME,
            font=ctk.CTkFont(size=30, weight="bold"),
        )
        header.grid(row=0, column=0, sticky="w")

        subtitle = ctk.CTkLabel(
            header_frame,
            text="Local CPU transcription with clear progress, reusable models, and interruption controls.",
            anchor="w",
            justify="left",
            text_color="gray70",
        )
        subtitle.grid(row=1, column=0, pady=(4, 0), sticky="w")

        version_label = ctk.CTkLabel(
            header_frame,
            textvariable=self.version_var,
            anchor="e",
            text_color="gray70",
        )
        version_label.grid(row=0, column=1, rowspan=2, sticky="e")

        content_frame = ctk.CTkFrame(self, fg_color="transparent")
        content_frame.grid(row=1, column=0, padx=24, pady=(0, 24), sticky="nsew")
        content_frame.grid_columnconfigure(0, weight=0, minsize=340)
        content_frame.grid_columnconfigure(1, weight=1)
        content_frame.grid_rowconfigure(0, weight=1)

        left_panel = ctk.CTkScrollableFrame(
            content_frame,
            width=340,
            corner_radius=18,
        )
        left_panel.grid(row=0, column=0, padx=(0, 16), sticky="nsew")
        left_panel.grid_columnconfigure(0, weight=1)

        source_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        source_frame.grid(row=0, column=0, padx=18, pady=(18, 12), sticky="ew")
        source_frame.grid_columnconfigure(0, weight=1)

        source_title = ctk.CTkLabel(
            source_frame,
            text="1. Select Media",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        source_title.grid(row=0, column=0, sticky="w")

        source_hint = ctk.CTkLabel(
            source_frame,
            text="Choose a local audio or video file. Compressed formats require FFmpeg.",
            anchor="w",
            justify="left",
            wraplength=280,
            text_color="gray70",
        )
        source_hint.grid(row=1, column=0, pady=(4, 12), sticky="w")

        browse_button = ctk.CTkButton(
            source_frame,
            text="Browse Media File",
            command=self.browse_file,
            height=42,
            fg_color="#0f766e",
            hover_color="#115e59",
        )
        browse_button.grid(row=2, column=0, sticky="ew")

        file_label = ctk.CTkLabel(
            source_frame,
            textvariable=self.file_var,
            anchor="w",
            justify="left",
            wraplength=280,
            text_color="gray80",
        )
        file_label.grid(row=3, column=0, pady=(10, 0), sticky="ew")

        settings_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        settings_frame.grid(row=1, column=0, padx=18, pady=12, sticky="ew")
        settings_frame.grid_columnconfigure(0, weight=1)

        settings_title = ctk.CTkLabel(
            settings_frame,
            text="2. Configure",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        settings_title.grid(row=0, column=0, sticky="w")

        settings_hint = ctk.CTkLabel(
            settings_frame,
            text="Pick transcription quality and language before starting.",
            anchor="w",
            justify="left",
            wraplength=280,
            text_color="gray70",
        )
        settings_hint.grid(row=1, column=0, pady=(4, 12), sticky="w")

        language_label = ctk.CTkLabel(settings_frame, text="Language")
        language_label.grid(row=2, column=0, pady=(0, 6), sticky="w")

        language_menu = ctk.CTkOptionMenu(
            settings_frame,
            variable=self.language_var,
            values=list(LANGUAGE_MAP.keys()),
            height=38,
        )
        language_menu.grid(row=3, column=0, pady=(0, 12), sticky="ew")

        model_label = ctk.CTkLabel(settings_frame, text="Model Size")
        model_label.grid(row=4, column=0, pady=(0, 6), sticky="w")

        model_menu = ctk.CTkOptionMenu(
            settings_frame,
            variable=self.model_var,
            values=list(MODEL_UI_LABELS.keys()),
            height=38,
        )
        model_menu.grid(row=5, column=0, pady=(0, 12), sticky="ew")

        speed_label = ctk.CTkLabel(settings_frame, text="Speed Profile")
        speed_label.grid(row=6, column=0, pady=(0, 6), sticky="w")

        speed_menu = ctk.CTkOptionMenu(
            settings_frame,
            variable=self.speed_var,
            values=list(TRANSCRIPTION_PRESETS.keys()),
            height=38,
        )
        speed_menu.grid(row=7, column=0, pady=(0, 8), sticky="ew")

        speed_hint = ctk.CTkLabel(
            settings_frame,
            text="Standard is safest. Fast and Ultra Fast reduce latency at some accuracy cost.",
            anchor="w",
            justify="left",
            wraplength=280,
            text_color="gray70",
        )
        speed_hint.grid(row=8, column=0, pady=(0, 12), sticky="w")

        clip_label = ctk.CTkLabel(settings_frame, text="Clip Range (optional)")
        clip_label.grid(row=9, column=0, pady=(0, 6), sticky="w")

        clip_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        clip_frame.grid(row=10, column=0, pady=(0, 8), sticky="ew")
        clip_frame.grid_columnconfigure((0, 1), weight=1)

        clip_start_entry = ctk.CTkEntry(
            clip_frame,
            textvariable=self.clip_start_var,
            placeholder_text="Start, e.g. 90 or 00:01:30",
            height=36,
        )
        clip_start_entry.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        clip_end_entry = ctk.CTkEntry(
            clip_frame,
            textvariable=self.clip_end_var,
            placeholder_text="End, e.g. 180 or 00:03:00",
            height=36,
        )
        clip_end_entry.grid(row=0, column=1, padx=(6, 0), sticky="ew")
        clip_start_entry.bind("<FocusOut>", self._on_clip_entry_commit)
        clip_start_entry.bind("<Return>", self._on_clip_entry_commit)
        clip_end_entry.bind("<FocusOut>", self._on_clip_entry_commit)
        clip_end_entry.bind("<Return>", self._on_clip_entry_commit)

        clip_hint = ctk.CTkLabel(
            settings_frame,
            text="Leave both blank for the full file. Accepted formats: seconds, mm:ss, or hh:mm:ss.",
            anchor="w",
            justify="left",
            wraplength=280,
            text_color="gray70",
        )
        clip_hint.grid(row=11, column=0, pady=(0, 12), sticky="w")

        duration_label = ctk.CTkLabel(
            settings_frame,
            textvariable=self.audio_duration_var,
            anchor="w",
            justify="left",
            text_color="gray80",
        )
        duration_label.grid(row=12, column=0, pady=(0, 4), sticky="w")

        clip_selection_label = ctk.CTkLabel(
            settings_frame,
            textvariable=self.clip_selection_var,
            anchor="w",
            justify="left",
            wraplength=280,
            text_color="gray80",
        )
        clip_selection_label.grid(row=13, column=0, pady=(0, 8), sticky="w")

        presets_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        presets_frame.grid(row=14, column=0, pady=(0, 8), sticky="ew")
        presets_frame.grid_columnconfigure((0, 1), weight=1)

        clip_clear_button = ctk.CTkButton(
            presets_frame,
            text="Full File",
            command=self.clear_clip_range,
            height=34,
        )
        clip_clear_button.grid(row=0, column=0, padx=(0, 6), pady=(0, 6), sticky="ew")

        clip_current_button = ctk.CTkButton(
            presets_frame,
            text="Current 30s",
            command=self.set_current_30_second_clip,
            height=34,
        )
        clip_current_button.grid(row=0, column=1, padx=(6, 0), pady=(0, 6), sticky="ew")

        clip_first_button = ctk.CTkButton(
            presets_frame,
            text="First 5 min",
            command=self.set_first_five_minutes_clip,
            height=34,
        )
        clip_first_button.grid(row=1, column=0, padx=(0, 6), sticky="ew")

        clip_last_button = ctk.CTkButton(
            presets_frame,
            text="Last 5 min",
            command=self.set_last_five_minutes_clip,
            height=34,
        )
        clip_last_button.grid(row=1, column=1, padx=(6, 0), sticky="ew")

        self.clip_selector = WaveformClipSelector(
            settings_frame,
            on_start_change=self._on_clip_start_slider_changed,
            on_end_change=self._on_clip_end_slider_changed,
        )
        self.clip_selector.grid(row=15, column=0, pady=(0, 12), sticky="ew")

        actions_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        actions_frame.grid(row=2, column=0, padx=18, pady=12, sticky="ew")
        actions_frame.grid_columnconfigure((0, 1), weight=1)

        actions_title = ctk.CTkLabel(
            actions_frame,
            text="3. Control",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        actions_title.grid(row=0, column=0, columnspan=2, sticky="w")

        self.start_button = ctk.CTkButton(
            actions_frame,
            text="Start Transcription",
            command=self.start_transcription,
            height=44,
            font=ctk.CTkFont(size=15, weight="bold"),
            fg_color="#2563eb",
            hover_color="#1d4ed8",
        )
        self.start_button.grid(row=1, column=0, columnspan=2, pady=(12, 10), sticky="ew")

        self.pause_button = ctk.CTkButton(
            actions_frame,
            text="Pause",
            command=self.toggle_pause,
            state="disabled",
            height=40,
        )
        self.pause_button.grid(row=2, column=0, padx=(0, 6), sticky="ew")

        self.stop_button = ctk.CTkButton(
            actions_frame,
            text="Stop",
            command=self.stop_operation,
            state="disabled",
            height=40,
            fg_color="#7f1d1d",
            hover_color="#991b1b",
        )
        self.stop_button.grid(row=2, column=1, padx=(6, 0), sticky="ew")

        self.save_button = ctk.CTkButton(
            actions_frame,
            text="Save Transcript",
            command=self.save_transcript,
            state="disabled",
            height=40,
        )
        self.save_button.grid(row=3, column=0, columnspan=2, pady=(10, 0), sticky="ew")

        self.preview_clip_button = ctk.CTkButton(
            actions_frame,
            text="Play Selected Clip",
            command=self.toggle_clip_preview,
            state="disabled",
            height=38,
            fg_color="#475569",
            hover_color="#334155",
        )
        self.preview_clip_button.grid(row=4, column=0, columnspan=2, pady=(10, 0), sticky="ew")

        readiness_card = ctk.CTkFrame(left_panel)
        readiness_card.grid(row=3, column=0, padx=18, pady=(0, 12), sticky="ew")
        readiness_card.grid_columnconfigure(0, weight=1)

        readiness_title = ctk.CTkLabel(
            readiness_card,
            text="Ready Check",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        readiness_title.grid(row=0, column=0, padx=14, pady=(12, 6), sticky="w")

        readiness_hint = ctk.CTkLabel(
            readiness_card,
            textvariable=self.readiness_var,
            anchor="w",
            justify="left",
            wraplength=280,
            text_color="gray80",
        )
        readiness_hint.grid(row=1, column=0, padx=14, pady=(0, 12), sticky="ew")

        models_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        models_frame.grid(row=4, column=0, padx=18, pady=(12, 18), sticky="nsew")
        models_frame.grid_columnconfigure(0, weight=1)
        left_panel.grid_rowconfigure(4, weight=1)

        models_header = ctk.CTkFrame(models_frame, fg_color="transparent")
        models_header.grid(row=0, column=0, sticky="ew")
        models_header.grid_columnconfigure(0, weight=1)

        models_title = ctk.CTkLabel(
            models_header,
            text="Downloaded Models",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        models_title.grid(row=0, column=0, sticky="w")

        self.refresh_models_button = ctk.CTkButton(
            models_header,
            text="Refresh",
            command=self.refresh_downloaded_models_panel,
            width=90,
            height=34,
        )
        self.refresh_models_button.grid(row=0, column=1, padx=(8, 0), sticky="e")

        models_hint = ctk.CTkLabel(
            models_frame,
            text="Downloaded models stay in the local project cache for reuse.",
            anchor="w",
            justify="left",
            wraplength=280,
            text_color="gray70",
        )
        models_hint.grid(row=1, column=0, pady=(4, 10), sticky="w")

        self.models_list_frame = ctk.CTkScrollableFrame(models_frame, height=210)
        self.models_list_frame.grid(row=2, column=0, sticky="nsew")
        self.models_list_frame.grid_columnconfigure(0, weight=1)
        models_frame.grid_rowconfigure(2, weight=1)

        models_footer = ctk.CTkFrame(models_frame, fg_color="transparent")
        models_footer.grid(row=3, column=0, pady=(10, 0), sticky="ew")
        models_footer.grid_columnconfigure(0, weight=1)

        cache_path_value = ctk.CTkLabel(
            models_footer,
            text=f"Cache: {MODEL_CACHE_DIR}",
            anchor="w",
            justify="left",
            wraplength=280,
            text_color="gray70",
        )
        cache_path_value.grid(row=0, column=0, sticky="ew")

        self.delete_selected_model_button = ctk.CTkButton(
            models_footer,
            text="Delete Selected Model",
            command=self.delete_selected_model,
            state="disabled",
            height=38,
            fg_color="#7f1d1d",
            hover_color="#991b1b",
        )
        self.delete_selected_model_button.grid(row=1, column=0, pady=(10, 8), sticky="ew")

        self.clear_all_models_button = ctk.CTkButton(
            models_footer,
            text="Clear All Models",
            command=self.clear_model_cache,
            height=36,
            fg_color="#4b5563",
            hover_color="#374151",
        )
        self.clear_all_models_button.grid(row=2, column=0, sticky="ew")

        workspace_frame = ctk.CTkFrame(content_frame, corner_radius=18)
        workspace_frame.grid(row=0, column=1, sticky="nsew")
        workspace_frame.grid_columnconfigure(0, weight=1)
        workspace_frame.grid_rowconfigure(3, weight=1)

        transcript_header = ctk.CTkFrame(workspace_frame, fg_color="transparent")
        transcript_header.grid(row=0, column=0, padx=18, pady=(18, 10), sticky="ew")
        transcript_header.grid_columnconfigure(0, weight=1)

        transcript_title = ctk.CTkLabel(
            transcript_header,
            text="Transcript Workspace",
            font=ctk.CTkFont(size=20, weight="bold"),
        )
        transcript_title.grid(row=0, column=0, sticky="w")

        transcript_view_label = ctk.CTkLabel(
            transcript_header,
            text="View",
            text_color="gray70",
        )
        transcript_view_label.grid(row=0, column=1, padx=(12, 8), sticky="e")

        transcript_view_menu = ctk.CTkOptionMenu(
            transcript_header,
            variable=self.transcript_view_var,
            values=list(TRANSCRIPT_VIEW_MODES),
            width=230,
            command=self._on_transcript_view_selected,
        )
        transcript_view_menu.grid(row=0, column=2, sticky="e")

        transcript_hint = ctk.CTkLabel(
            transcript_header,
            text="Live progress and transcript output appear here while the model runs.",
            anchor="w",
            justify="left",
            text_color="gray70",
        )
        transcript_hint.grid(row=1, column=0, columnspan=3, pady=(4, 0), sticky="w")

        status_card = ctk.CTkFrame(workspace_frame)
        status_card.grid(row=1, column=0, padx=18, pady=(0, 10), sticky="ew")
        status_card.grid_columnconfigure(0, weight=1)

        status_caption = ctk.CTkLabel(
            status_card,
            text="Current Status",
            anchor="w",
            text_color="gray70",
        )
        status_caption.grid(row=0, column=0, padx=14, pady=(12, 4), sticky="w")

        status_label = ctk.CTkLabel(
            status_card,
            textvariable=self.status_var,
            anchor="w",
            justify="left",
            font=ctk.CTkFont(size=15, weight="bold"),
        )
        status_label.grid(row=1, column=0, padx=14, pady=(0, 12), sticky="ew")

        progress_card = ctk.CTkFrame(workspace_frame)
        progress_card.grid(row=2, column=0, padx=18, pady=(0, 10), sticky="ew")
        progress_card.grid_columnconfigure(0, weight=1)

        download_label = ctk.CTkLabel(
            progress_card,
            textvariable=self.download_var,
            anchor="w",
            justify="left",
        )
        download_label.grid(row=0, column=0, padx=14, pady=(12, 8), sticky="ew")

        self.download_progress_bar = ctk.CTkProgressBar(progress_card, height=14)
        self.download_progress_bar.grid(row=1, column=0, padx=14, pady=(0, 12), sticky="ew")
        self.download_progress_bar.set(0)

        self.transcript_box = ctk.CTkTextbox(workspace_frame, wrap="word", corner_radius=14)
        self.transcript_box.grid(row=3, column=0, padx=18, pady=(0, 18), sticky="nsew")
        self.transcript_box.insert("1.0", self._default_transcript_placeholder())
        self.transcript_box.configure(state="disabled")

    def browse_file(self) -> None:
        file_path = filedialog.askopenfilename(
            title="Select an audio or video file",
            filetypes=[(
                "Supported media files",
                SUPPORTED_FILE_DIALOG_PATTERN,
            )],
        )
        if not file_path:
            return

        self.selected_file = Path(file_path)
        self.file_var.set(str(self.selected_file))
        self._load_audio_visual_data()
        self._sync_clip_controls_from_entries()
        self.status_var.set("Ready to transcribe.")
        self._update_preview_button_state()
        self._refresh_readiness_state()

    def start_transcription(self) -> None:
        if self._is_transcription_running() or self._is_speaker_analysis_running():
            return

        if IMPORT_ERROR is not None:
            self.status_var.set(f"Dependency error: {IMPORT_ERROR}")
            return

        if self.selected_file is None:
            self.status_var.set("Please select a media file first.")
            return

        if self.selected_file.suffix.lower() not in SUPPORTED_EXTENSIONS:
            self.status_var.set("Unsupported file type selected.")
            return

        if self._requires_ffmpeg(self.selected_file):
            self.status_var.set("FFmpeg not found for compressed media input.")
            self._show_ffmpeg_guidance(
                "FFmpeg is required for this media format on this machine.\n\n"
                f"Selected file: {self.selected_file.name}\n\n"
                "Install it with:\n"
                "winget install Gyan.FFmpeg\n\n"
                "Then restart the app and try again."
            )
            return

        try:
            clip_range = self._get_clip_range()
        except ValueError as exc:
            self.status_var.set(f"Invalid clip range: {exc}")
            return

        model_key = MODEL_UI_LABELS[self.model_var.get()]
        self.active_model_key = model_key
        if self.cache_manager.get_local_model_snapshot(model_key) is None:
            self.current_activity = "downloading model"
        else:
            self.current_activity = "loading model"
        self._sync_active_model_override()

        self.transcript_segments.clear()
        self.speaker_labeled_segments = None
        self.last_speaker_error = None
        self._stop_clip_preview()
        self._set_transcript_text("")
        if clip_range is None:
            self.status_var.set("Loading model...")
        else:
            self.status_var.set(
                f"Loading model for clip {format_timestamp(clip_range[0])} to {format_timestamp(clip_range[1])}..."
            )
        self._queue_download_progress(0.0, "Checking local model cache...")
        self.save_button.configure(state="disabled")
        self.start_button.configure(state="disabled")
        self.pause_button.configure(state="normal", text="Pause")
        self.stop_button.configure(state="normal")
        self.pause_event.set()
        self.stop_event.clear()
        self.is_paused = False
        self._update_model_action_buttons()
        self._update_preview_button_state()

        self.worker_thread = threading.Thread(target=self._run_transcription, daemon=True)
        self.worker_thread.start()

    def _run_transcription(self) -> None:
        try:
            model_key = MODEL_UI_LABELS[self.model_var.get()]
            language_code = LANGUAGE_MAP[self.language_var.get()]
            preset_name = self.speed_var.get()
            clip_range = self._get_clip_range()
            collected_segments: list[TranscriptSegment] = []

            model = self._get_model(model_key)
            self._wait_if_paused_or_cancelled()
            self.message_queue.put(("activity", "transcribing"))
            self.message_queue.put(("status", "Transcribing..."))
            self._queue_download_progress(1.0, "Model ready.")

            transcribe_options = self._build_transcribe_options(language_code, preset_name)
            segments, _info = model.transcribe(str(self.selected_file), **transcribe_options)

            for segment in segments:
                self._wait_if_paused_or_cancelled()
                transcript_segment = TranscriptSegment(
                    start=float(segment.start),
                    end=float(segment.end),
                    text=segment.text.strip(),
                )
                collected_segments.append(transcript_segment)
                self.message_queue.put(("segment", transcript_segment))

            if self._requires_speaker_labels() and collected_segments and self.selected_file is not None:
                self.message_queue.put(("status", "Analyzing speakers..."))
                speaker_segments = self.speaker_diarizer.diarize(
                    self.selected_file,
                    collected_segments,
                    clip_range=clip_range,
                    checkpoint=self._wait_if_paused_or_cancelled,
                )
                self.message_queue.put(("speaker_segments", speaker_segments))

            self.message_queue.put(("done", "Done!"))
        except OperationCancelled:
            self.message_queue.put(("cancelled", "Stopped."))
        except SpeakerDiarizationUnavailable as exc:
            self.message_queue.put(("speaker_error", str(exc)))
            self.message_queue.put(("done", "Transcription finished without speaker labels."))
        except Exception as exc:
            self.message_queue.put(("error", f"Error: {exc}"))

    def _get_model(self, model_key: str) -> WhisperModel:
        if self.loaded_model is not None and self.loaded_model_size == model_key:
            self.message_queue.put(("status", "Reusing loaded model from memory..."))
            self._queue_download_progress(1.0, "Model already loaded in memory.")
            return self.loaded_model

        MODEL_CACHE_DIR.mkdir(exist_ok=True)
        local_snapshot = self.cache_manager.get_local_model_snapshot(model_key)
        if local_snapshot is None:
            self.message_queue.put(("activity", "downloading model"))
            self._ensure_model_downloaded(model_key)
            local_snapshot = self.cache_manager.get_local_model_snapshot(model_key)
        else:
            self._queue_download_progress(1.0, f"Using cached {model_key} model.")

        if local_snapshot is None:
            raise RuntimeError(f"Local cache for model '{model_key}' is incomplete.")

        self._wait_if_paused_or_cancelled()
        self.message_queue.put(("activity", "loading model"))
        self.message_queue.put(("status", "Loading model from local .models cache..."))

        self.loaded_model = WhisperModel(
            str(local_snapshot),
            device="cpu",
            compute_type="int8",
        )
        self.loaded_model_size = model_key
        return self.loaded_model

    def _ensure_model_downloaded(self, model_key: str) -> None:
        repository_id = MODEL_REPOSITORY_MAP[model_key]
        self.cache_manager.cleanup_incomplete_model_files(model_key)
        dry_run_files = snapshot_download(
            repository_id,
            cache_dir=str(MODEL_CACHE_DIR),
            dry_run=True,
            tqdm_class=SilentTqdm,
        )

        files_to_download = [file_info for file_info in dry_run_files if file_info.will_download]
        total_bytes = sum(file_info.file_size or 0 for file_info in files_to_download)

        if total_bytes <= 0:
            self._queue_download_progress(1.0, "Model already cached locally.")
            self.message_queue.put(("models_changed", None))
            return

        downloaded_by_file: dict[str, float] = {}
        self._queue_download_progress(0.0, f"Downloading model: 0% of {format_size(total_bytes)}")

        for file_info in files_to_download:
            self._wait_if_paused_or_cancelled()
            tqdm_class = self._create_download_tqdm_class(
                file_info.filename,
                downloaded_by_file,
                total_bytes,
            )
            hf_hub_download(
                repository_id,
                file_info.filename,
                revision=file_info.commit_hash,
                cache_dir=str(MODEL_CACHE_DIR),
                tqdm_class=tqdm_class,
            )

        self._queue_download_progress(1.0, "Model download complete.")
        self.message_queue.put(("models_changed", None))

    def _create_download_tqdm_class(
        self,
        filename: str,
        downloaded_by_file: dict[str, float],
        total_bytes: float,
    ) -> type[tqdm]:
        app = self
        file_key = filename
        short_name = Path(filename).name

        class DownloadProgressTqdm(SilentTqdm):
            def _report(self) -> None:
                current_bytes = min(float(self.n), float(self.total or 0))
                downloaded_by_file[file_key] = current_bytes
                total_downloaded = sum(downloaded_by_file.values())
                fraction = min(total_downloaded / total_bytes, 1.0) if total_bytes else 1.0
                app._queue_download_progress(
                    fraction,
                    (
                        f"Downloading model: {fraction * 100:.1f}% "
                        f"({format_size(total_downloaded)} / {format_size(total_bytes)}) - {short_name}"
                    ),
                )

            def update(self, n: int = 1) -> None:
                app._wait_if_paused_or_cancelled()
                super().update(n)
                self._report()

            def close(self) -> None:
                self._report()
                super().close()

        return DownloadProgressTqdm

    def _build_transcribe_options(
        self,
        language_code: str | None,
        preset_name: str,
    ) -> dict[str, object]:
        transcribe_options: dict[str, object] = {"language": language_code}
        transcribe_options.update(TRANSCRIPTION_PRESETS[preset_name])
        clip_range = self._get_clip_range()
        if clip_range is not None:
            transcribe_options["clip_timestamps"] = [clip_range[0], clip_range[1]]
        return transcribe_options

    def _load_audio_visual_data(self) -> None:
        if self.selected_file is None:
            self.audio_duration_seconds = None
            self.audio_waveform_points = []
            self.audio_duration_var.set("Duration: No media loaded")
            self._configure_clip_selector()
            return

        try:
            audio_data = load_audio_visual_data(self.selected_file)
        except AudioSupportError as exc:
            self.audio_duration_seconds = None
            self.audio_waveform_points = []
            self.audio_duration_var.set(str(exc))
            self._configure_clip_selector()
            return

        self.audio_duration_seconds = audio_data.duration_seconds
        self.audio_waveform_points = audio_data.waveform_points
        self.audio_duration_var.set(f"Duration: {format_timestamp(audio_data.duration_seconds)}")
        self._configure_clip_selector()

    def _configure_clip_selector(self) -> None:
        self.clip_selector.configure_audio(self.audio_duration_seconds, self.audio_waveform_points)

    def _on_clip_entry_commit(self, _event: object) -> None:
        self._sync_clip_controls_from_entries()

    def _sync_clip_controls_from_entries(self) -> None:
        if self.updating_clip_controls:
            return

        start_raw = self.clip_start_var.get().strip()
        end_raw = self.clip_end_var.get().strip()

        if not start_raw and not end_raw:
            self._set_slider_positions(0.0, self.audio_duration_seconds or 1.0)
            self.clip_selection_var.set("Selected clip: Full file")
            return

        if not start_raw or not end_raw:
            self.clip_selection_var.set("Selected clip: Enter both start and end times")
            return

        try:
            start_seconds = parse_time_input(start_raw)
            end_seconds = parse_time_input(end_raw)
            start_seconds, end_seconds = self._normalize_clip_range(start_seconds, end_seconds)
        except ValueError as exc:
            self.clip_selection_var.set(f"Selected clip: {exc}")
            return

        self._set_clip_values(start_seconds, end_seconds)

    def _set_slider_positions(self, start_seconds: float, end_seconds: float) -> None:
        self.updating_clip_controls = True
        try:
            self.clip_selector.set_clip(start_seconds, end_seconds)
        finally:
            self.updating_clip_controls = False

    def _set_clip_values(self, start_seconds: float, end_seconds: float) -> None:
        normalized_start, normalized_end = self._normalize_clip_range(start_seconds, end_seconds)

        self.updating_clip_controls = True
        try:
            self.clip_start_var.set(format_timestamp(normalized_start))
            self.clip_end_var.set(format_timestamp(normalized_end))
        finally:
            self.updating_clip_controls = False

        self._set_slider_positions(normalized_start, normalized_end)
        self.clip_selection_var.set(
            "Selected clip: "
            f"{format_timestamp(normalized_start)} to {format_timestamp(normalized_end)} "
            f"({format_timestamp(normalized_end - normalized_start)})"
        )
        self._refresh_readiness_state()

    def _normalize_clip_range(self, start_seconds: float, end_seconds: float) -> tuple[float, float]:
        if start_seconds < 0:
            raise ValueError("start time cannot be negative")

        duration = self.audio_duration_seconds
        if duration is not None:
            start_seconds = min(start_seconds, duration)
            end_seconds = min(end_seconds, duration)

        if end_seconds <= start_seconds:
            raise ValueError("end time must be greater than start time")

        return (start_seconds, end_seconds)

    def _on_clip_start_slider_changed(self, value: float) -> None:
        if self.updating_clip_controls:
            return

        duration = self.audio_duration_seconds or max(float(value), self.clip_selector.get_end_value(), 1.0)
        start_value = max(0.0, min(float(value), duration))
        end_value = max(self.clip_selector.get_end_value(), start_value + 1.0)
        end_value = min(end_value, duration)
        if end_value <= start_value:
            start_value = max(0.0, end_value - 1.0)
        self._set_clip_values(start_value, end_value)

    def _on_clip_end_slider_changed(self, value: float) -> None:
        if self.updating_clip_controls:
            return

        duration = self.audio_duration_seconds or max(float(value), self.clip_selector.get_start_value(), 1.0)
        end_value = min(max(float(value), 0.0), duration)
        start_value = min(self.clip_selector.get_start_value(), end_value - 1.0)
        start_value = max(0.0, start_value)
        if end_value <= start_value:
            end_value = min(duration, start_value + 1.0)
        self._set_clip_values(start_value, end_value)

    def clear_clip_range(self) -> None:
        self.updating_clip_controls = True
        try:
            self.clip_start_var.set("")
            self.clip_end_var.set("")
        finally:
            self.updating_clip_controls = False

        self._set_slider_positions(0.0, self.audio_duration_seconds or 1.0)
        self.clip_selection_var.set("Selected clip: Full file")
        self._refresh_readiness_state()

    def set_first_five_minutes_clip(self) -> None:
        self._set_preset_clip(0.0, 300.0)

    def set_last_five_minutes_clip(self) -> None:
        duration = self.audio_duration_seconds
        if duration is None:
            self.clip_selection_var.set("Selected clip: Load a media file first")
            return
        self._set_preset_clip(max(0.0, duration - 300.0), duration)

    def set_current_30_second_clip(self) -> None:
        duration = self.audio_duration_seconds
        if duration is None:
            self.clip_selection_var.set("Selected clip: Load a media file first")
            return

        try:
            existing_clip = self._get_clip_range()
        except ValueError:
            existing_clip = None

        center = (
            existing_clip[0] + ((existing_clip[1] - existing_clip[0]) / 2)
            if existing_clip
            else self.clip_selector.get_start_value()
        )
        start_seconds = max(0.0, center - 15.0)
        end_seconds = min(duration, start_seconds + 30.0)
        if duration >= 30.0 and end_seconds - start_seconds < 30.0:
            start_seconds = max(0.0, duration - 30.0)
            end_seconds = duration
        self._set_preset_clip(start_seconds, end_seconds)

    def _set_preset_clip(self, start_seconds: float, end_seconds: float) -> None:
        if self.audio_duration_seconds is None:
            self.clip_selection_var.set("Selected clip: Load a media file first")
            return
        self._set_clip_values(start_seconds, end_seconds)

    def toggle_clip_preview(self) -> None:
        self._sync_preview_process_state()
        if self.preview_process is not None and self.preview_process.poll() is None:
            self._stop_clip_preview()
            self.status_var.set("Clip preview stopped.")
            return

        if self.selected_file is None:
            self.status_var.set("Select a media file before previewing a clip.")
            return

        clip_range = self._get_clip_range()
        if clip_range is None:
            if self.audio_duration_seconds is None:
                self.status_var.set("Audio duration is unavailable for preview.")
                return
            clip_range = (0.0, self.audio_duration_seconds)

        try:
            self.preview_process = start_audio_preview(self.selected_file, clip_range[0], clip_range[1])
        except AudioPreviewError as exc:
            self.status_var.set(str(exc))
            self.preview_process = None
            self._update_preview_button_state()
            return

        self.status_var.set(
            f"Previewing clip {format_timestamp(clip_range[0])} to {format_timestamp(clip_range[1])}."
        )
        self._update_preview_button_state()

    def _stop_clip_preview(self) -> None:
        stop_audio_preview(self.preview_process)
        self.preview_process = None
        self._update_preview_button_state()

    def _sync_preview_process_state(self) -> None:
        if self.preview_process is not None and self.preview_process.poll() is not None:
            self.preview_process = None
            self._update_preview_button_state()

    def _update_preview_button_state(self) -> None:
        if self.preview_process is not None and self.preview_process.poll() is None:
            self.preview_clip_button.configure(text="Stop Preview", state="normal")
            return

        if self.selected_file is None or self._is_transcription_running() or self._is_speaker_analysis_running():
            self.preview_clip_button.configure(text="Play Selected Clip", state="disabled")
            return

        self.preview_clip_button.configure(text="Play Selected Clip", state="normal")

    def _collect_readiness_issues(self) -> list[str]:
        issues: list[str] = []

        if self.selected_file is None:
            issues.append("Select a media file.")
            return issues

        if self.selected_file.suffix.lower() not in SUPPORTED_EXTENSIONS:
            issues.append("Select a supported media file type.")

        if self._requires_ffmpeg(self.selected_file):
            issues.append("Install FFmpeg for compressed media input on this machine.")

        try:
            self._get_clip_range()
        except ValueError as exc:
            issues.append(f"Fix clip range: {exc}.")

        if self._requires_speaker_labels():
            speaker_issue = get_speaker_diarization_prerequisite_issue()
            if speaker_issue:
                issues.append(speaker_issue)

        return issues

    def _refresh_readiness_state(self) -> None:
        if self._is_transcription_running() or self._is_speaker_analysis_running():
            self.readiness_var.set("Ready check: Busy. Wait for the current operation to finish.")
            return

        issues = self._collect_readiness_issues()
        diagnostics: list[str] = []
        if self.selected_file is not None and self._requires_speaker_labels():
            diagnostics = get_speaker_diarization_diagnostics()

        if issues:
            details = "\n".join(f"- {issue}" for issue in issues)
            if diagnostics:
                details = f"{details}\nDiagnostics:\n" + "\n".join(
                    f"- {diagnostic}" for diagnostic in diagnostics
                )
            self.readiness_var.set(f"Ready check:\n{details}")
            self.start_button.configure(state="disabled")
            return

        if diagnostics:
            details = "\n".join(f"- {diagnostic}" for diagnostic in diagnostics)
            self.readiness_var.set(
                "Ready check: All required inputs are available.\n"
                f"Diagnostics:\n{details}"
            )
        else:
            self.readiness_var.set("Ready check: All required inputs are available.")
        self.start_button.configure(state="normal")

    def _get_clip_range(self) -> tuple[float, float] | None:
        start_raw = self.clip_start_var.get().strip()
        end_raw = self.clip_end_var.get().strip()

        if not start_raw and not end_raw:
            return None
        if not start_raw or not end_raw:
            raise ValueError("enter both start and end times")

        start_seconds = parse_time_input(start_raw)
        end_seconds = parse_time_input(end_raw)
        return self._normalize_clip_range(start_seconds, end_seconds)

    def _bind_setting_persistence(self) -> None:
        self.language_var.trace_add("write", self._on_setting_changed)
        self.model_var.trace_add("write", self._on_setting_changed)
        self.speed_var.trace_add("write", self._on_setting_changed)
        self.clip_start_var.trace_add("write", self._on_setting_changed)
        self.clip_end_var.trace_add("write", self._on_setting_changed)

    def _on_setting_changed(self, *_args: object) -> None:
        self._save_settings()
        self._refresh_readiness_state()

    def _load_settings(self) -> None:
        settings = self.settings_manager.load()
        self.language_var.set(settings["language"])
        self.model_var.set(settings["model"])
        self.speed_var.set(settings["speed"])
        self.transcript_view_var.set(settings["transcript_view"])
        self.clip_start_var.set(settings["clip_start"])
        self.clip_end_var.set(settings["clip_end"])
        self.ffmpeg_warning_shown = bool(settings["ffmpeg_warning_shown"])
        geometry = settings.get("geometry")
        if isinstance(geometry, str) and geometry:
            self.geometry(geometry)
        self._refresh_readiness_state()

    def _save_settings(self) -> None:
        self.settings_manager.save(
            {
                "language": self.language_var.get(),
                "model": self.model_var.get(),
                "speed": self.speed_var.get(),
                "transcript_view": self.transcript_view_var.get(),
                "clip_start": self.clip_start_var.get(),
                "clip_end": self.clip_end_var.get(),
                "geometry": self.geometry(),
                "ffmpeg_warning_shown": self.ffmpeg_warning_shown,
            }
        )

    def refresh_downloaded_models_panel(self) -> None:
        statuses = self.cache_manager.list_statuses()
        self.latest_model_statuses = {status.model_key: status for status in statuses}

        selected = self.selected_downloaded_model_var.get()
        if selected and selected not in self.latest_model_statuses:
            self.selected_downloaded_model_var.set("")

        for child in self.models_list_frame.winfo_children():
            child.destroy()

        for row_index, status in enumerate(statuses):
            row = ctk.CTkFrame(self.models_list_frame, fg_color="transparent")
            row.grid(row=row_index, column=0, padx=4, pady=4, sticky="ew")
            row.grid_columnconfigure(1, weight=1)

            radio_state = "normal" if status.can_delete and not self._is_model_locked(status.model_key) else "disabled"
            radio = ctk.CTkRadioButton(
                row,
                text=status.display_name,
                variable=self.selected_downloaded_model_var,
                value=status.model_key,
                state=radio_state,
                command=self._update_model_action_buttons,
            )
            radio.grid(row=0, column=0, padx=(4, 12), pady=4, sticky="w")

            status_text = self.model_status_overrides.get(status.model_key, status.state)
            status_label = ctk.CTkLabel(row, text=status_text, anchor="w")
            status_label.grid(row=0, column=1, padx=(0, 12), pady=4, sticky="ew")

            if status.snapshot_dir is not None:
                detail_text = str(status.snapshot_dir)
            elif status.can_delete:
                detail_text = str(status.cache_root)
            else:
                detail_text = "No local files present"

            detail_label = ctk.CTkLabel(
                row,
                text=detail_text,
                anchor="w",
                justify="left",
                wraplength=560,
                text_color="gray70",
            )
            detail_label.grid(row=1, column=1, columnspan=2, padx=(0, 12), pady=(0, 4), sticky="ew")

        self._update_model_action_buttons()

    def _is_model_locked(self, model_key: str) -> bool:
        if not self.worker_thread or not self.worker_thread.is_alive():
            return False
        return model_key == self.active_model_key or model_key == self.loaded_model_size

    def _update_model_action_buttons(self) -> None:
        selected_model = self.selected_downloaded_model_var.get()
        status = self.latest_model_statuses.get(selected_model)
        can_delete_selected = (
            status is not None
            and status.can_delete
            and not self._is_model_locked(selected_model)
        )

        self.delete_selected_model_button.configure(
            state="normal" if can_delete_selected else "disabled"
        )
        self.clear_all_models_button.configure(
            state="disabled" if self._is_transcription_running() or self._is_speaker_analysis_running() else "normal"
        )

    def _sync_active_model_override(self) -> None:
        self.model_status_overrides.clear()
        if self.active_model_key is None:
            self.refresh_downloaded_models_panel()
            return

        if self.stop_event.is_set():
            override = "Stopping..."
        elif self.is_paused:
            if self.current_activity == "downloading model":
                override = "Download paused"
            elif self.current_activity == "transcribing":
                override = "Transcription paused"
            else:
                override = "Paused"
        elif self.current_activity == "downloading model":
            override = "Downloading"
        elif self.current_activity == "loading model":
            override = "Loading into memory"
        elif self.current_activity == "transcribing":
            override = "In use"
        else:
            override = ""

        if override:
            self.model_status_overrides[self.active_model_key] = override
        self.refresh_downloaded_models_panel()

    def toggle_pause(self) -> None:
        if not self._is_transcription_running():
            return

        if self.is_paused:
            self.is_paused = False
            self.pause_event.set()
            self.pause_button.configure(text="Pause")
            self.status_var.set(f"Resuming {self.current_activity}...")
            self._sync_active_model_override()
            return

        self.is_paused = True
        self.pause_event.clear()
        self.pause_button.configure(text="Resume")
        self.status_var.set(f"Paused {self.current_activity}.")
        self._sync_active_model_override()

    def stop_operation(self) -> None:
        if not self._is_transcription_running():
            return

        self.stop_event.set()
        self.pause_event.set()
        self.is_paused = False
        self.pause_button.configure(text="Pause", state="disabled")
        self.stop_button.configure(state="disabled")
        self.status_var.set(f"Stopping {self.current_activity}...")
        self._sync_active_model_override()

    def delete_selected_model(self) -> None:
        selected_model = self.selected_downloaded_model_var.get()
        status = self.latest_model_statuses.get(selected_model)
        if status is None or not status.can_delete:
            self.status_var.set("Select a downloaded or partial model to delete.")
            return

        if self._is_model_locked(selected_model):
            self.status_var.set("That model is currently in use and cannot be deleted.")
            return

        confirmed = messagebox.askyesno(
            "Delete Model",
            f"Delete the local '{selected_model}' model cache?",
            parent=self,
        )
        if not confirmed:
            self.status_var.set("Model delete cancelled.")
            return

        if self.cache_manager.delete_model(selected_model):
            if self.loaded_model_size == selected_model:
                self.loaded_model = None
                self.loaded_model_size = None
            self.selected_downloaded_model_var.set("")
            self.refresh_downloaded_models_panel()
            self.status_var.set(f"Deleted local '{selected_model}' model cache.")
            self._queue_download_progress(0.0, "No model activity yet")

    def clear_model_cache(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            self.status_var.set("Wait for the current transcription to finish before clearing cache.")
            return

        if not MODEL_CACHE_DIR.exists():
            self.status_var.set("Local model cache is already empty.")
            return

        confirmed = messagebox.askyesno(
            "Clear All Models",
            "Delete all cached local Whisper models from this project?",
            parent=self,
        )
        if not confirmed:
            self.status_var.set("Model cache clear cancelled.")
            return

        self.cache_manager.clear_all()
        self.loaded_model = None
        self.loaded_model_size = None
        self.selected_downloaded_model_var.set("")
        self.download_progress_bar.set(0)
        self.download_var.set("No model activity yet")
        self.refresh_downloaded_models_panel()
        self.status_var.set("Local model cache cleared.")

    def _wait_if_paused_or_cancelled(self) -> None:
        if self.stop_event.is_set():
            raise OperationCancelled()

        while not self.pause_event.wait(timeout=0.1):
            if self.stop_event.is_set():
                raise OperationCancelled()

    def _queue_download_progress(self, progress: float, text: str) -> None:
        progress = max(0.0, min(progress, 1.0))
        self.message_queue.put(("download_progress", {"progress": progress, "text": text}))

    def _requires_ffmpeg(self, selected_file: Path) -> bool:
        return selected_file.suffix.lower() in COMPRESSED_EXTENSIONS and shutil.which("ffmpeg") is None

    def _show_ffmpeg_guidance(self, message: str) -> None:
        messagebox.showwarning("FFmpeg Not Found", message, parent=self)

    def _check_ffmpeg_setup(self) -> None:
        if shutil.which("ffmpeg"):
            self._refresh_readiness_state()
            return

        self.status_var.set("FFmpeg not found. Install it for audio decoding support.")
        if self.ffmpeg_warning_shown:
            return

        self.ffmpeg_warning_shown = True
        self._save_settings()
        self._show_ffmpeg_guidance(
            "FFmpeg was not found on this computer.\n\n"
            f"Compressed formats such as {COMPRESSED_EXTENSIONS_LABEL} may fail without it.\n\n"
            "Recommended Windows fix:\n"
            "1. Open PowerShell\n"
            "2. Run: winget install Gyan.FFmpeg\n"
            "3. Close and reopen this app after installation.",
        )
        self._refresh_readiness_state()

    def _poll_queue(self) -> None:
        self._sync_preview_process_state()
        while not self.message_queue.empty():
            message_type, payload = self.message_queue.get()

            if message_type == "status":
                self.status_var.set(str(payload))
            elif message_type == "download_progress":
                progress_payload = payload
                self.download_progress_bar.set(progress_payload["progress"])
                self.download_var.set(progress_payload["text"])
            elif message_type == "segment":
                self.transcript_segments.append(payload)
                self._refresh_transcript_view()
            elif message_type == "speaker_segments":
                self.speaker_labeled_segments = payload
                self.last_speaker_error = None
                self._refresh_transcript_view()
            elif message_type == "speaker_error":
                self.last_speaker_error = str(payload)
                self.status_var.set(str(payload))
                self._refresh_transcript_view()
                self._finish_speaker_analysis(save_state="normal" if self.transcript_segments else "disabled")
            elif message_type == "speaker_analysis_done":
                self.status_var.set(str(payload))
                self._finish_speaker_analysis(save_state="normal" if self.transcript_segments else "disabled")
            elif message_type == "activity":
                self.current_activity = str(payload)
                self._sync_active_model_override()
            elif message_type == "models_changed":
                self.refresh_downloaded_models_panel()
            elif message_type == "done":
                self.status_var.set(str(payload))
                self._finish_worker("normal" if self.transcript_segments else "disabled")
            elif message_type == "cancelled":
                self.status_var.set(str(payload))
                self._finish_worker("normal" if self.transcript_segments else "disabled")
            elif message_type == "error":
                self.status_var.set(str(payload))
                self._finish_worker("normal" if self.transcript_segments else "disabled")

        self.after(100, self._poll_queue)

    def _finish_worker(self, save_state: str) -> None:
        self.pause_button.configure(state="disabled", text="Pause")
        self.stop_button.configure(state="disabled")
        self.save_button.configure(state=save_state)
        self.pause_event.set()
        self.stop_event.clear()
        self.is_paused = False
        self.current_activity = "idle"
        self.active_model_key = None
        self.model_status_overrides.clear()
        self.refresh_downloaded_models_panel()
        self._update_preview_button_state()
        self._refresh_readiness_state()

    def _finish_speaker_analysis(self, save_state: str) -> None:
        self.save_button.configure(state=save_state)
        self.current_activity = "idle"
        self.refresh_downloaded_models_panel()
        self._update_preview_button_state()
        self._refresh_readiness_state()

    def _set_transcript_text(self, text: str) -> None:
        self.transcript_box.configure(state="normal")
        self.transcript_box.delete("1.0", "end")
        self.transcript_box.insert("1.0", text)
        self.transcript_box.configure(state="disabled")

    def _default_transcript_placeholder(self) -> str:
        return "Transcript output will appear here once transcription starts.\n"

    def _refresh_transcript_view(self) -> None:
        rendered = self._get_rendered_transcript()
        self._set_transcript_text(rendered or self._default_transcript_placeholder())

    def _get_rendered_transcript(self) -> str:
        if not self.transcript_segments:
            return ""

        mode = self.transcript_view_var.get()
        if not self._requires_speaker_labels(mode):
            return render_transcript(self.transcript_segments, mode)

        if self.speaker_labeled_segments is not None:
            return render_transcript(self.speaker_labeled_segments, mode)

        base_mode = "Paragraphs" if mode == "Speaker-labeled paragraphs" else "Raw"
        fallback_text = render_transcript(self.transcript_segments, base_mode)

        if self._is_transcription_running():
            return (
                "Speaker labels are added after transcription completes.\n\n"
                f"{fallback_text}"
            )

        if self._is_speaker_analysis_running():
            return (
                "Speaker analysis is running. This view will update automatically when it finishes.\n\n"
                f"{fallback_text}"
            )

        if self.last_speaker_error:
            error_text = format_speaker_diarization_error_with_diagnostics(self.last_speaker_error)
            return f"Speaker labeling is unavailable right now:\n{error_text}\n\n{fallback_text}"

        return fallback_text

    def _requires_speaker_labels(self, mode: str | None = None) -> bool:
        active_mode = mode or self.transcript_view_var.get()
        return active_mode.startswith("Speaker-labeled")

    def _on_transcript_view_selected(self, _selection: str) -> None:
        self._save_settings()
        self._refresh_transcript_view()
        self._refresh_readiness_state()
        if self._requires_speaker_labels() and self.transcript_segments and self.speaker_labeled_segments is None:
            self._start_speaker_analysis()

    def _start_speaker_analysis(self) -> None:
        if self._is_transcription_running() or self._is_speaker_analysis_running():
            return

        if not self.transcript_segments or self.selected_file is None:
            return

        self.last_speaker_error = None
        self.current_activity = "speaker analysis"
        self.status_var.set("Analyzing speakers...")
        self.start_button.configure(state="disabled")
        self.save_button.configure(state="disabled")
        self._update_model_action_buttons()
        self._update_preview_button_state()
        self.speaker_thread = threading.Thread(target=self._run_speaker_analysis, daemon=True)
        self.speaker_thread.start()
        self._refresh_transcript_view()

    def _run_speaker_analysis(self) -> None:
        try:
            if self.selected_file is None:
                return

            clip_range = self._get_clip_range()
            speaker_segments = self.speaker_diarizer.diarize(
                self.selected_file,
                self.transcript_segments,
                clip_range=clip_range,
            )
            self.message_queue.put(("speaker_segments", speaker_segments))
            self.message_queue.put(("speaker_analysis_done", "Speaker analysis complete."))
        except SpeakerDiarizationUnavailable as exc:
            self.message_queue.put(("speaker_error", str(exc)))
        except Exception as exc:
            self.message_queue.put(("speaker_error", f"Speaker analysis failed: {exc}"))

    def _is_transcription_running(self) -> bool:
        return self.worker_thread is not None and self.worker_thread.is_alive()

    def _is_speaker_analysis_running(self) -> bool:
        return self.speaker_thread is not None and self.speaker_thread.is_alive()

    def save_transcript(self) -> None:
        rendered_transcript = self._get_rendered_transcript()
        if not rendered_transcript:
            self.status_var.set("There is no transcript to save yet.")
            return

        initial_name = "transcript.txt"
        if self.selected_file is not None:
            initial_name = f"{self.selected_file.stem}_transcript.txt"

        save_path = filedialog.asksaveasfilename(
            title="Save transcript",
            defaultextension=".txt",
            initialfile=initial_name,
            filetypes=[("Text files", "*.txt")],
        )
        if not save_path:
            return

        Path(save_path).write_text(rendered_transcript, encoding="utf-8")
        self.status_var.set("Transcript saved.")

    def on_close(self) -> None:
        self._stop_clip_preview()
        self._save_settings()
        self.destroy()