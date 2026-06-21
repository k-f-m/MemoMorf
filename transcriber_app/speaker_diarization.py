from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .audio_support import AudioSupportError, load_audio_waveform
from .constants import SPEAKER_DIARIZATION_MODEL
from .transcript_processing import TranscriptSegment, clone_with_speakers


class SpeakerDiarizationUnavailable(RuntimeError):
    pass


class SpeakerDiarizer:
    def __init__(self, model_name: str = SPEAKER_DIARIZATION_MODEL) -> None:
        self.model_name = model_name
        self._pipeline: Any | None = None

    def diarize(
        self,
        audio_path: Path,
        segments: list[TranscriptSegment],
        clip_range: tuple[float, float] | None = None,
        checkpoint: Callable[[], None] | None = None,
    ) -> list[TranscriptSegment]:
        if not segments:
            return []

        if checkpoint is not None:
            checkpoint()

        pipeline = self._get_pipeline()

        if checkpoint is not None:
            checkpoint()

        try:
            diarization_input = load_audio_waveform(audio_path, clip_range=clip_range)
        except AudioSupportError as exc:
            raise SpeakerDiarizationUnavailable(str(exc)) from exc

        diarization = pipeline(diarization_input)
        speaker_turns = _extract_speaker_turns(diarization, time_offset=clip_range[0] if clip_range else 0.0)
        if not speaker_turns:
            return clone_with_speakers(segments, ["Speaker 1" for _ in segments])

        speaker_labels = [_pick_speaker_label(segment, speaker_turns) for segment in segments]
        return clone_with_speakers(segments, speaker_labels)

    def _get_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline

        token = _get_hugging_face_token()
        if token is None:
            raise SpeakerDiarizationUnavailable(
                "Speaker labeling requires a Hugging Face access token in HF_TOKEN, "
                "HUGGINGFACE_TOKEN, or HUGGINGFACE_HUB_TOKEN."
            )

        try:
            _disable_pyannote_telemetry()
            from pyannote.audio import Pipeline
        except Exception as exc:  # pragma: no cover - depends on optional dependency.
            raise SpeakerDiarizationUnavailable(
                "Speaker labeling dependency missing. Install requirements again to add pyannote.audio."
            ) from exc

        _disable_pyannote_telemetry()

        try:
            self._pipeline = Pipeline.from_pretrained(self.model_name, token=token)
        except TypeError:
            try:
                self._pipeline = Pipeline.from_pretrained(self.model_name, use_auth_token=token)
            except Exception as exc:  # pragma: no cover - depends on local auth/model access.
                raise SpeakerDiarizationUnavailable(_format_pipeline_load_error(exc)) from exc
        except Exception as exc:  # pragma: no cover - depends on local auth/model access.
            raise SpeakerDiarizationUnavailable(_format_pipeline_load_error(exc)) from exc

        return self._pipeline


def get_speaker_diarization_prerequisite_issue() -> str | None:
    token = _get_hugging_face_token()
    if token is None:
        return (
            "Speaker labeling requires a Hugging Face Read token with access to "
            "pyannote/speaker-diarization-community-1, exposed in HF_TOKEN, "
            "HUGGINGFACE_TOKEN, or HUGGINGFACE_HUB_TOKEN."
        )

    try:
        _disable_pyannote_telemetry()
        from pyannote.audio import Pipeline  # noqa: F401
    except Exception:
        return (
            "Speaker labeling requires a Hugging Face Read token with access to "
            "pyannote/speaker-diarization-community-1, and pyannote.audio must be available in this app "
            "runtime. If you are using the packaged .exe, rebuild it after installing pyannote.audio."
        )

    return None


def get_speaker_diarization_diagnostics() -> list[str]:
    token = _get_hugging_face_token()
    token_source = _get_hugging_face_token_source()
    runtime_available = _is_pyannote_runtime_available()

    diagnostics = [
        f"HF token detected: {'yes' if token is not None else 'no'}"
    ]
    if token_source is not None:
        diagnostics[0] += f" ({token_source})"

    diagnostics.append(
        f"pyannote.audio runtime available: {'yes' if runtime_available else 'no'}"
    )
    return diagnostics


def format_speaker_diarization_error_with_diagnostics(error_text: str) -> str:
    diagnostics = get_speaker_diarization_diagnostics()
    if not diagnostics:
        return error_text

    details = "\n".join(f"- {diagnostic}" for diagnostic in diagnostics)
    return f"{error_text}\nDiagnostics:\n{details}"


def _get_hugging_face_token() -> str | None:
    for env_name in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGINGFACE_HUB_TOKEN"):
        token = os.getenv(env_name)
        if token:
            return token.strip()
    return None


def _get_hugging_face_token_source() -> str | None:
    for env_name in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGINGFACE_HUB_TOKEN"):
        token = os.getenv(env_name)
        if token and token.strip():
            return env_name
    return None


def _is_pyannote_runtime_available() -> bool:
    try:
        _disable_pyannote_telemetry()
        from pyannote.audio import Pipeline  # noqa: F401
    except Exception:
        return False

    return True


def _format_pipeline_load_error(exc: Exception) -> str:
    detail = _summarize_exception(exc)
    token_source = _get_hugging_face_token_source()

    if "401" in detail or "403" in detail or "gatedrepoerror" in detail.lower():
        if token_source is not None:
            return (
                "Could not load the speaker diarization model. A Hugging Face token was detected in this app "
                f"process ({token_source}), but access to pyannote/speaker-diarization-community-1 was rejected. "
                "Confirm that this exact token has Read access and that the model terms were accepted on the same "
                f"account. Details: {detail}"
            )

        return (
            "Could not load the speaker diarization model because this app process does not currently see a Hugging "
            "Face token in HF_TOKEN, HUGGINGFACE_TOKEN, or HUGGINGFACE_HUB_TOKEN. Restart the app from a process "
            f"that has the token loaded. Details: {detail}"
        )

    return (
        "Could not load the speaker diarization model. The Hugging Face model request failed for a local runtime "
        f"reason. Details: {detail}"
    )


def _summarize_exception(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    if not text:
        text = exc.__class__.__name__

    return text[:280]


def _disable_pyannote_telemetry() -> None:
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    try:
        from pyannote.audio.telemetry import set_telemetry_metrics
    except Exception:
        return

    try:
        set_telemetry_metrics(False, save_choice_as_default=True)
    except TypeError:
        set_telemetry_metrics(False)
    except Exception:
        return


def _extract_speaker_turns(
    diarization: Any,
    time_offset: float = 0.0,
) -> list[tuple[float, float, str]]:
    annotation = getattr(diarization, "speaker_diarization", diarization)
    raw_turns: list[tuple[float, float, str]] = []

    if hasattr(annotation, "itertracks"):
        for turn, _track, speaker in annotation.itertracks(yield_label=True):
            raw_turns.append((float(turn.start), float(turn.end), str(speaker)))

    if not raw_turns and hasattr(annotation, "speaker_diarization"):
        for turn, speaker in annotation.speaker_diarization:
            raw_turns.append((float(turn.start), float(turn.end), str(speaker)))

    label_map: dict[str, str] = {}
    normalized_turns: list[tuple[float, float, str]] = []
    for start, end, raw_label in raw_turns:
        if raw_label not in label_map:
            label_map[raw_label] = f"Speaker {len(label_map) + 1}"
        normalized_turns.append((start + time_offset, end + time_offset, label_map[raw_label]))
    return normalized_turns


def _pick_speaker_label(
    segment: TranscriptSegment,
    speaker_turns: list[tuple[float, float, str]],
) -> str:
    best_label = "Speaker 1"
    best_overlap = -1.0
    segment_midpoint = (segment.start + segment.end) / 2
    nearest_distance = float("inf")

    for turn_start, turn_end, label in speaker_turns:
        overlap = min(segment.end, turn_end) - max(segment.start, turn_start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_label = label

        turn_midpoint = (turn_start + turn_end) / 2
        distance = abs(segment_midpoint - turn_midpoint)
        if best_overlap <= 0 and distance < nearest_distance:
            nearest_distance = distance
            best_label = label

    return best_label