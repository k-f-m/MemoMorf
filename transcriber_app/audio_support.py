from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

try:
    import av
except Exception:  # pragma: no cover - depends on local environment.
    av = None

try:
    import torch
except Exception:  # pragma: no cover - depends on local environment.
    torch = None


class AudioSupportError(RuntimeError):
    pass


class AudioPreviewError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioVisualData:
    duration_seconds: float
    waveform_points: list[float]


def load_audio_visual_data(audio_path: Path, waveform_points: int = 240) -> AudioVisualData:
    if av is None:
        raise AudioSupportError("Audio metadata support is unavailable.")

    try:
        with av.open(str(audio_path)) as container:
            audio_stream = next((stream for stream in container.streams if stream.type == "audio"), None)
            if audio_stream is None:
                raise AudioSupportError("No audio stream found in the selected file.")

            duration_seconds = _read_duration_seconds(container, audio_stream)
            waveform = _read_waveform_points(container, audio_stream, waveform_points)
    except AudioSupportError:
        raise
    except Exception as exc:  # pragma: no cover - media parsing depends on local files/codecs.
        raise AudioSupportError(f"Could not read audio metadata: {exc}") from exc

    return AudioVisualData(duration_seconds=duration_seconds, waveform_points=waveform)


def load_audio_waveform(
    audio_path: Path,
    clip_range: tuple[float, float] | None = None,
) -> dict[str, Any]:
    if av is None or torch is None:
        raise AudioSupportError("Audio decoding support is unavailable.")

    try:
        with av.open(str(audio_path)) as container:
            audio_stream = next((stream for stream in container.streams if stream.type == "audio"), None)
            if audio_stream is None:
                raise AudioSupportError("No audio stream found in the selected file.")

            waveform, sample_rate = _read_waveform_tensor(container, audio_stream)
    except AudioSupportError:
        raise
    except Exception as exc:  # pragma: no cover - media parsing depends on local files/codecs.
        raise AudioSupportError(f"Could not decode audio for speaker labeling: {exc}") from exc

    if clip_range is not None:
        waveform = _slice_waveform_tensor(waveform, sample_rate, clip_range)

    return {"waveform": waveform, "sample_rate": sample_rate}


def start_audio_preview(audio_path: Path, start_seconds: float, end_seconds: float) -> subprocess.Popen[Any]:
    ffplay_path = shutil.which("ffplay")
    if ffplay_path is None:
        raise AudioPreviewError("Clip preview requires ffplay from FFmpeg on PATH.")

    duration_seconds = max(0.1, end_seconds - start_seconds)
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        [
            ffplay_path,
            "-nodisp",
            "-autoexit",
            "-loglevel",
            "quiet",
            "-ss",
            f"{start_seconds:.3f}",
            "-t",
            f"{duration_seconds:.3f}",
            str(audio_path),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )


def stop_audio_preview(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=1.5)
    except Exception:
        process.kill()


def _read_duration_seconds(container: Any, audio_stream: Any) -> float:
    if container.duration is not None:
        return max(float(container.duration) / 1_000_000.0, 0.1)

    if audio_stream.duration is not None and audio_stream.time_base is not None:
        return max(float(audio_stream.duration * audio_stream.time_base), 0.1)

    raise AudioSupportError("Duration is unavailable for this file.")


def _read_waveform_points(container: Any, audio_stream: Any, point_count: int) -> list[float]:
    mono_chunks: list[np.ndarray[Any, Any]] = []

    for frame in container.decode(audio_stream):
        samples = frame.to_ndarray()
        mono = np.asarray(samples, dtype=np.float32)
        if mono.ndim == 2:
            mono = np.mean(np.abs(mono), axis=0)
        else:
            mono = np.abs(mono.reshape(-1))
        if mono.size:
            mono_chunks.append(mono)

    if not mono_chunks:
        return [0.0 for _ in range(point_count)]

    merged = np.concatenate(mono_chunks)
    peak = float(np.max(merged)) if merged.size else 0.0
    if peak > 0:
        merged = merged / peak

    if merged.size <= point_count:
        padded = np.zeros(point_count, dtype=np.float32)
        padded[: merged.size] = merged
        return [float(value) for value in padded]

    window_size = int(np.ceil(merged.size / point_count))
    points: list[float] = []
    for start_index in range(0, merged.size, window_size):
        window = merged[start_index : start_index + window_size]
        points.append(float(np.max(window)) if window.size else 0.0)

    if len(points) < point_count:
        points.extend([0.0] * (point_count - len(points)))
    return points[:point_count]


def _read_waveform_tensor(container: Any, audio_stream: Any) -> tuple[Any, int]:
    mono_chunks: list[np.ndarray[Any, Any]] = []
    sample_rate: int | None = None

    for frame in container.decode(audio_stream):
        samples = frame.to_ndarray()
        waveform = np.asarray(samples, dtype=np.float32)
        if waveform.ndim == 2:
            waveform = np.mean(waveform, axis=0)
        else:
            waveform = waveform.reshape(-1)

        if waveform.size == 0:
            continue

        mono_chunks.append(waveform)
        if sample_rate is None:
            frame_rate = getattr(frame, "sample_rate", None)
            stream_rate = getattr(audio_stream, "rate", None)
            sample_rate = int(frame_rate or stream_rate or 16000)

    if not mono_chunks:
        raise AudioSupportError("Could not decode any audio samples from the selected file.")

    merged = np.concatenate(mono_chunks)
    peak = float(np.max(np.abs(merged))) if merged.size else 0.0
    if peak > 1.0:
        merged = merged / peak

    waveform_tensor = torch.from_numpy(merged.copy()).unsqueeze(0)
    return waveform_tensor, sample_rate or 16000


def _slice_waveform_tensor(
    waveform: Any,
    sample_rate: int,
    clip_range: tuple[float, float],
) -> Any:
    start_seconds, end_seconds = clip_range
    total_samples = waveform.shape[-1]
    start_index = max(0, min(int(round(start_seconds * sample_rate)), total_samples))
    end_index = max(start_index, min(int(round(end_seconds * sample_rate)), total_samples))

    if end_index <= start_index:
        raise AudioSupportError("Selected clip range does not contain any decodable audio samples.")

    return waveform[..., start_index:end_index]