from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import ttk

from recorder_core import (
    DEFAULT_DEVICE_NAME,
    DEFAULT_FRAMERATE,
    DEFAULT_VIDEO_SIZE,
    FFmpegRecordingSession,
    RESOLUTION_PRESETS,
    RecordingConfig,
    default_output_dir,
    format_duration,
    start_recording,
)


class UsbCameraRecorderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.session: FFmpegRecordingSession | None = None

        root.title("USB Camera Recorder")
        root.geometry("720x360")
        root.minsize(680, 340)

        self.device_var = tk.StringVar(value=DEFAULT_DEVICE_NAME)
        self.size_var = tk.StringVar(value=DEFAULT_VIDEO_SIZE)
        self.fps_var = tk.StringVar(value=str(DEFAULT_FRAMERATE))
        self.output_dir_var = tk.StringVar(value=str(default_output_dir()))
        self.status_var = tk.StringVar(value="Ready")
        self.file_var = tk.StringVar(value="-")
        self.duration_var = tk.StringVar(value="00:00:00")

        frame = tk.Frame(root, padx=18, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)

        self._add_labeled_entry(frame, 0, "Device", self.device_var)
        self._add_resolution_row(frame, 1)
        self._add_labeled_entry(frame, 2, "FPS", self.fps_var)
        self._add_output_dir_row(frame, 3)

        tk.Label(frame, text="Status", anchor="w").grid(row=4, column=0, sticky="w", pady=(18, 4))
        tk.Label(frame, textvariable=self.status_var, anchor="w").grid(row=4, column=1, columnspan=2, sticky="ew", pady=(18, 4))

        tk.Label(frame, text="Current file", anchor="w").grid(row=5, column=0, sticky="w", pady=4)
        tk.Label(frame, textvariable=self.file_var, anchor="w", wraplength=520, justify=tk.LEFT).grid(row=5, column=1, columnspan=2, sticky="ew", pady=4)

        tk.Label(frame, text="Duration", anchor="w").grid(row=6, column=0, sticky="w", pady=4)
        tk.Label(frame, textvariable=self.duration_var, anchor="w", font=("Consolas", 12, "bold")).grid(row=6, column=1, columnspan=2, sticky="ew", pady=4)

        button_row = tk.Frame(frame)
        button_row.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(22, 0))

        self.start_button = tk.Button(button_row, text="Start Recording", width=18, command=self.start)
        self.start_button.pack(side=tk.LEFT)

        self.stop_button = tk.Button(button_row, text="Stop Recording", width=18, command=self.stop, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(10, 0))

        self.open_button = tk.Button(button_row, text="Open Save Folder", width=18, command=self.open_output_dir)
        self.open_button.pack(side=tk.LEFT, padx=(10, 0))

        frame.columnconfigure(1, weight=1)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(500, self.refresh_status)

    def _add_labeled_entry(self, parent: tk.Frame, row: int, label: str, variable: tk.StringVar) -> None:
        tk.Label(parent, text=label, anchor="w").grid(row=row, column=0, sticky="w", pady=4)
        tk.Entry(parent, textvariable=variable).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)

    def _add_resolution_row(self, parent: tk.Frame, row: int) -> None:
        tk.Label(parent, text="Resolution", anchor="w").grid(row=row, column=0, sticky="w", pady=4)
        combo = ttk.Combobox(parent, textvariable=self.size_var, values=RESOLUTION_PRESETS)
        combo.grid(row=row, column=1, columnspan=2, sticky="ew", pady=4)

    def _add_output_dir_row(self, parent: tk.Frame, row: int) -> None:
        tk.Label(parent, text="Save folder", anchor="w").grid(row=row, column=0, sticky="w", pady=4)
        tk.Entry(parent, textvariable=self.output_dir_var).grid(row=row, column=1, sticky="ew", pady=4)
        tk.Button(parent, text="Browse", command=self.choose_output_dir).grid(row=row, column=2, sticky="e", padx=(8, 0), pady=4)

    def choose_output_dir(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.output_dir_var.get())
        if selected:
            self.output_dir_var.set(selected)

    def config(self) -> RecordingConfig:
        try:
            framerate = int(self.fps_var.get())
        except ValueError as exc:
            raise ValueError("FPS must be an integer.") from exc
        if framerate <= 0:
            raise ValueError("FPS must be greater than 0.")

        device_name = self.device_var.get().strip()
        if not device_name:
            raise ValueError("Device cannot be empty.")

        video_size = self.size_var.get().strip()
        if not video_size:
            raise ValueError("Resolution cannot be empty.")

        return RecordingConfig(
            device_name=device_name,
            video_size=video_size,
            framerate=framerate,
            output_dir=Path(self.output_dir_var.get()),
        )

    def start(self) -> None:
        if self.session is not None and self.session.is_running():
            return

        try:
            self.session = start_recording(self.config())
        except Exception as exc:
            self.session = None
            messagebox.showerror("Recording failed", str(exc))
            self.status_var.set("Failed to start")
            return

        self.file_var.set(str(self.session.output_path))
        self.duration_var.set("00:00:00")
        self.status_var.set("Recording with preview")
        self.start_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)

    def stop(self) -> None:
        if self.session is None:
            return

        session = self.session
        self.status_var.set("Stopping")
        self.root.update_idletasks()

        try:
            session.stop()
        except Exception as exc:
            messagebox.showerror("Stop failed", str(exc))
            self.status_var.set("Stop failed")
            return
        finally:
            self.session = None
            self.start_button.configure(state=tk.NORMAL)
            self.stop_button.configure(state=tk.DISABLED)

        self.status_var.set("Saved")
        self.file_var.set(str(session.output_path))

    def open_output_dir(self) -> None:
        output_dir = Path(self.output_dir_var.get())
        output_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(output_dir)

    def refresh_status(self) -> None:
        if self.session is not None:
            if self.session.is_running():
                self.duration_var.set(format_duration(self.session.elapsed_seconds()))
            else:
                self.status_var.set("Stopped")
                self.start_button.configure(state=tk.NORMAL)
                self.stop_button.configure(state=tk.DISABLED)
                self.session = None

        self.root.after(500, self.refresh_status)

    def on_close(self) -> None:
        if self.session is not None and self.session.is_running():
            if not messagebox.askyesno("Recording active", "Stop recording and exit?"):
                return
            self.stop()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    UsbCameraRecorderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
