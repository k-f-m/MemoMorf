from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from .clip_utils import format_timestamp


class WaveformClipSelector(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        on_start_change: Callable[[float], None],
        on_end_change: Callable[[float], None],
    ) -> None:
        super().__init__(master, fg_color="transparent")

        self.on_start_change = on_start_change
        self.on_end_change = on_end_change
        self.duration_seconds = 1.0
        self.waveform_values: list[float] = [0.0 for _ in range(240)]
        self._updating = False

        self.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            self,
            height=124,
            highlightthickness=0,
            bg="#0f172a",
            bd=0,
            relief="flat",
        )
        self.canvas.grid(row=0, column=0, sticky="ew")
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.start_slider = ctk.CTkSlider(
            self,
            from_=0,
            to=1,
            number_of_steps=100,
            command=self._handle_start_change,
            state="disabled",
        )
        self.start_slider.grid(row=1, column=0, pady=(10, 8), sticky="ew")
        self.start_slider.set(0)

        self.end_slider = ctk.CTkSlider(
            self,
            from_=0,
            to=1,
            number_of_steps=100,
            command=self._handle_end_change,
            state="disabled",
        )
        self.end_slider.grid(row=2, column=0, sticky="ew")
        self.end_slider.set(1)

    def configure_audio(self, duration_seconds: float | None, waveform_values: list[float] | None) -> None:
        enabled = duration_seconds is not None and duration_seconds > 0
        self.duration_seconds = max(duration_seconds or 1.0, 1.0)
        slider_state = "normal" if enabled else "disabled"
        slider_steps = max(int(self.duration_seconds), 1)
        self.start_slider.configure(to=self.duration_seconds, number_of_steps=slider_steps, state=slider_state)
        self.end_slider.configure(to=self.duration_seconds, number_of_steps=slider_steps, state=slider_state)
        self.waveform_values = waveform_values or [0.0 for _ in range(240)]
        self.set_clip(0.0, self.duration_seconds)

    def clear(self) -> None:
        self.configure_audio(None, None)

    def set_clip(self, start_seconds: float, end_seconds: float) -> None:
        self._updating = True
        try:
            self.start_slider.set(max(0.0, min(start_seconds, self.duration_seconds)))
            self.end_slider.set(max(0.0, min(end_seconds, self.duration_seconds)))
        finally:
            self._updating = False
        self._redraw_canvas()

    def get_start_value(self) -> float:
        return float(self.start_slider.get())

    def get_end_value(self) -> float:
        return float(self.end_slider.get())

    def _handle_start_change(self, value: float) -> None:
        self._redraw_canvas()
        if not self._updating:
            self.on_start_change(float(value))

    def _handle_end_change(self, value: float) -> None:
        self._redraw_canvas()
        if not self._updating:
            self.on_end_change(float(value))

    def _on_canvas_configure(self, _event: object) -> None:
        self._redraw_canvas()

    def _redraw_canvas(self) -> None:
        self.canvas.delete("all")

        width = max(self.canvas.winfo_width(), 24)
        height = max(self.canvas.winfo_height(), 48)
        midline = height / 2
        values = self.waveform_values or [0.0]
        bar_width = max(width / max(len(values), 1), 1.0)

        start_x = self._position_for_value(self.get_start_value(), width)
        end_x = self._position_for_value(self.get_end_value(), width)
        self.canvas.create_rectangle(start_x, 0, end_x, height, fill="#14345f", outline="")

        for index, value in enumerate(values):
            x0 = index * bar_width
            x1 = x0 + max(bar_width - 1, 1)
            amplitude = max(value, 0.04) * (height * 0.36)
            y0 = midline - amplitude
            y1 = midline + amplitude
            center_x = x0 + ((x1 - x0) / 2)
            color = "#7dd3fc" if start_x <= center_x <= end_x else "#475569"
            self.canvas.create_rectangle(x0, y0, x1, y1, fill=color, outline="")

        self.canvas.create_line(start_x, 0, start_x, height, fill="#f8fafc", width=2)
        self.canvas.create_line(end_x, 0, end_x, height, fill="#f8fafc", width=2)
        self._draw_tooltip(start_x, format_timestamp(self.get_start_value()), width)
        self._draw_tooltip(end_x, format_timestamp(self.get_end_value()), width)

    def _draw_tooltip(self, x_position: float, text: str, width: int) -> None:
        text_width = max(len(text) * 7, 48)
        half_width = text_width / 2
        x0 = max(6.0, min(x_position - half_width, width - text_width - 6.0))
        x1 = x0 + text_width
        y0 = 8.0
        y1 = 28.0
        self.canvas.create_rectangle(x0, y0, x1, y1, fill="#e2e8f0", outline="")
        self.canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=text, fill="#0f172a", font=("Segoe UI", 9, "bold"))

    def _position_for_value(self, value: float, width: int) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        fraction = max(0.0, min(value / self.duration_seconds, 1.0))
        return fraction * width