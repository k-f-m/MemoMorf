from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from .constants import PARAGRAPH_BREAK_SECONDS


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    speaker_label: str | None = None


def clone_with_speakers(
    segments: Iterable[TranscriptSegment],
    speaker_labels: Iterable[str | None],
) -> list[TranscriptSegment]:
    return [
        replace(segment, speaker_label=speaker_label)
        for segment, speaker_label in zip(segments, speaker_labels, strict=True)
    ]


def render_transcript(segments: list[TranscriptSegment], mode: str) -> str:
    cleaned_segments = [segment for segment in segments if segment.text.strip()]
    if not cleaned_segments:
        return ""

    if mode == "Raw":
        return "\n".join(_render_raw_segment(segment) for segment in cleaned_segments)
    if mode == "Paragraphs":
        return "\n\n".join(_render_paragraphs(cleaned_segments))
    if mode == "Speaker-labeled":
        return "\n\n".join(_render_speaker_turns(cleaned_segments, paragraph_mode=False))
    if mode == "Speaker-labeled paragraphs":
        return "\n\n".join(_render_speaker_turns(cleaned_segments, paragraph_mode=True))
    return "\n".join(_render_raw_segment(segment) for segment in cleaned_segments)


def _render_paragraphs(segments: list[TranscriptSegment]) -> list[str]:
    paragraph_groups = _group_segments_by_pause(segments)
    rendered: list[str] = []
    for group in paragraph_groups:
        if not group:
            continue
        start = format_timestamp(group[0].start)
        end = format_timestamp(group[-1].end)
        rendered.append(f"[{start} -> {end}] {_join_segment_text(group)}")
    return rendered


def _render_speaker_turns(
    segments: list[TranscriptSegment],
    *,
    paragraph_mode: bool,
) -> list[str]:
    speaker_groups = _group_segments_by_speaker_turn(segments)
    rendered: list[str] = []
    for group in speaker_groups:
        if not group:
            continue
        label = group[0].speaker_label or "Unknown speaker"
        start = format_timestamp(group[0].start)
        end = format_timestamp(group[-1].end)
        if paragraph_mode:
            body = "\n\n".join(_join_segment_text(paragraph) for paragraph in _group_segments_by_pause(group))
        else:
            body = _join_segment_text(group)
        rendered.append(f"[{label} | {start} -> {end}]\n{body}")
    return rendered


def _group_segments_by_pause(segments: list[TranscriptSegment]) -> list[list[TranscriptSegment]]:
    groups: list[list[TranscriptSegment]] = []
    current_group: list[TranscriptSegment] = []

    for segment in segments:
        if not current_group:
            current_group.append(segment)
            continue

        previous = current_group[-1]
        if _should_start_new_paragraph(previous, segment):
            groups.append(current_group)
            current_group = [segment]
            continue

        current_group.append(segment)

    if current_group:
        groups.append(current_group)
    return groups


def _group_segments_by_speaker_turn(segments: list[TranscriptSegment]) -> list[list[TranscriptSegment]]:
    groups: list[list[TranscriptSegment]] = []
    current_group: list[TranscriptSegment] = []

    for segment in segments:
        if not current_group:
            current_group.append(segment)
            continue

        previous = current_group[-1]
        if previous.speaker_label != segment.speaker_label:
            groups.append(current_group)
            current_group = [segment]
            continue

        current_group.append(segment)

    if current_group:
        groups.append(current_group)
    return groups


def _should_start_new_paragraph(previous: TranscriptSegment, current: TranscriptSegment) -> bool:
    pause = max(0.0, current.start - previous.end)
    if pause >= PARAGRAPH_BREAK_SECONDS:
        return True

    previous_text = previous.text.strip()
    current_text = current.text.strip()
    if not previous_text or not current_text:
        return False

    if previous_text.endswith((".", "?", "!")) and current_text[:1].isupper():
        return True
    return False


def _join_segment_text(segments: list[TranscriptSegment]) -> str:
    parts = [segment.text.strip() for segment in segments if segment.text.strip()]
    return " ".join(parts)


def _render_raw_segment(segment: TranscriptSegment) -> str:
    return f"[{format_timestamp(segment.start)} -> {format_timestamp(segment.end)}] {segment.text.strip()}"


def format_timestamp(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes:02d}:{remaining_seconds:02d}"