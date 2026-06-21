from __future__ import annotations


def format_timestamp(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, remaining_seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{remaining_seconds:02d}"
    return f"{minutes:02d}:{remaining_seconds:02d}"


def parse_time_input(value: str) -> float:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Time value is empty.")

    parts = normalized.split(":")
    if len(parts) == 1:
        seconds = float(parts[0])
    elif len(parts) == 2:
        minutes = float(parts[0])
        seconds = float(parts[1])
        seconds += minutes * 60
    elif len(parts) == 3:
        hours = float(parts[0])
        minutes = float(parts[1])
        seconds = float(parts[2])
        seconds += (hours * 3600) + (minutes * 60)
    else:
        raise ValueError("Use seconds or hh:mm:ss format.")

    if seconds < 0:
        raise ValueError("Time cannot be negative.")
    return seconds