import argparse
import math
import queue
import random
import threading
import time
import tkinter as tk
from dataclasses import dataclass

from radar_protocol import RadarStreamParser, RadarTarget
from risk import RISK_SCORE, TargetRisk, evaluate_target, summarize_targets
from view_model import polar_to_xy, radar_origin, radar_radius


RISK_COLORS = {
    "safe": "#7a7a7a",
    "low": "#38a169",
    "medium": "#d69e2e",
    "high": "#dd6b20",
    "emergency": "#e53e3e",
}


@dataclass
class DisplayState:
    targets: list[RadarTarget]
    source: str
    updated_at: float
    error: str | None = None


class SerialRadarReader(threading.Thread):
    def __init__(self, port: str, baud: int, output: queue.Queue[DisplayState]) -> None:
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.output = output
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        try:
            import serial
        except ImportError:
            self.output.put(
                DisplayState(
                    targets=[],
                    source=self.port,
                    updated_at=time.time(),
                    error="pyserial is not installed. Run: python -m pip install pyserial",
                )
            )
            return

        parser = RadarStreamParser()
        try:
            with serial.Serial(self.port, self.baud, timeout=0.05) as ser:
                while not self._stop_event.is_set():
                    chunk = ser.read(512)
                    if not chunk:
                        continue
                    for report in parser.feed(chunk):
                        if report.report_type == 0x07:
                            self.output.put(DisplayState(report.targets, self.port, time.time()))
        except Exception as exc:
            self.output.put(DisplayState([], self.port, time.time(), error=str(exc)))


class DemoRadarSource:
    def __init__(self) -> None:
        self.started_at = time.time()

    def targets(self) -> list[RadarTarget]:
        t = time.time() - self.started_at
        center_distance = 12.0 - (t * 1.8 % 11.0)
        left_distance = 6.0 + math.sin(t * 0.8) * 2.0
        right_distance = 9.0 + math.cos(t * 0.6) * 2.0
        jitter = random.choice([0, 0, 0, 1, -1])

        return [
            RadarTarget(round(center_distance), jitter, 2, 1),
            RadarTarget(round(left_distance), -28, 1, 2),
            RadarTarget(round(right_distance), 30, 0, 3),
        ]


class RadarVisualizerApp:
    def __init__(
        self,
        root: tk.Tk,
        state_queue: queue.Queue[DisplayState],
        *,
        max_range_m: int,
        demo: bool,
        invert_angle: bool,
    ) -> None:
        self.root = root
        self.state_queue = state_queue
        self.max_range_m = max_range_m
        self.demo = DemoRadarSource() if demo else None
        self.invert_angle = invert_angle
        self.current_state = DisplayState([], "demo" if demo else "serial", time.time())

        root.title("mmWave Radar Obstacle Visualizer")
        root.geometry("980x720")

        self.canvas = tk.Canvas(root, background="#101419", highlightthickness=0)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.panel = tk.Text(root, width=42, background="#161b22", foreground="#d7dde5")
        self.panel.pack(side=tk.RIGHT, fill=tk.Y)
        self.panel.configure(font=("Consolas", 10), state=tk.DISABLED)

        self.root.after(50, self._tick)

    def _tick(self) -> None:
        if self.demo is not None:
            self.current_state = DisplayState(self.demo.targets(), "demo", time.time())

        while True:
            try:
                self.current_state = self.state_queue.get_nowait()
            except queue.Empty:
                break

        self._draw()
        self.root.after(100, self._tick)

    def _draw(self) -> None:
        self.canvas.delete("all")
        width = max(self.canvas.winfo_width(), 800)
        height = max(self.canvas.winfo_height(), 600)
        origin = radar_origin(width, height)
        radius = radar_radius(width, height)

        self._draw_grid(width, height, origin, radius)

        targets = self._display_targets(self.current_state.targets)
        evaluated = [evaluate_target(target) for target in targets]
        for item in evaluated:
            self._draw_target(item, width, height)

        self._write_panel(evaluated)

    def _display_targets(self, targets: list[RadarTarget]) -> list[RadarTarget]:
        if not self.invert_angle:
            return targets
        return [
            RadarTarget(
                distance_m=target.distance_m,
                angle_deg=-target.angle_deg,
                velocity_mps=target.velocity_mps,
                target_id=target.target_id,
            )
            for target in targets
        ]

    def _draw_grid(self, width: int, height: int, origin: tuple[int, int], radius: float) -> None:
        ox, oy = origin
        self.canvas.create_text(ox, oy + 24, text="RADAR", fill="#8b949e", tags="grid")

        for angle in (-40, 0, 40):
            x, y = polar_to_xy(self.max_range_m, angle, self.max_range_m, width, height)
            self.canvas.create_line(ox, oy, x, y, fill="#30363d", width=1, tags="grid")
            self.canvas.create_text(x, y - 10, text=f"{angle:+d} deg", fill="#8b949e", tags="grid")

        ranges = [5, 10, 20, self.max_range_m]
        for distance in sorted(set(r for r in ranges if r <= self.max_range_m)):
            points: list[int] = []
            for angle in range(-40, 41, 2):
                x, y = polar_to_xy(distance, angle, self.max_range_m, width, height)
                points.extend([x, y])
            self.canvas.create_line(*points, fill="#26303a", smooth=True, tags="grid")
            label_x, label_y = polar_to_xy(distance, 0, self.max_range_m, width, height)
            self.canvas.create_text(label_x + 26, label_y, text=f"{distance}m", fill="#8b949e", tags="grid")

        fov_points: list[int] = []
        for angle in range(-40, 41, 2):
            x, y = polar_to_xy(self.max_range_m, angle, self.max_range_m, width, height)
            fov_points.extend([x, y])
        self.canvas.create_line(*fov_points, fill="#586069", width=2, smooth=True, tags="grid")
        self.canvas.create_oval(ox - 5, oy - 5, ox + 5, oy + 5, fill="#d7dde5", outline="", tags="grid")

        self.canvas.create_text(width // 2, 28, text="60GHz mmWave Radar BSD View (+/-40 deg)", fill="#f0f6fc", font=("Segoe UI", 16, "bold"))

    def _draw_target(self, item: TargetRisk, width: int, height: int) -> None:
        target = item.target
        x, y = polar_to_xy(target.distance_m, target.angle_deg, self.max_range_m, width, height)
        color = RISK_COLORS[item.risk_level]
        radius = 8 if item.risk_level in ("safe", "low") else 11
        self.canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=color, outline="#f0f6fc", width=1)

        if target.velocity_mps > 0:
            next_distance = max(0, target.distance_m - min(4, max(1, target.velocity_mps)))
            nx, ny = polar_to_xy(next_distance, target.angle_deg, self.max_range_m, width, height)
            self.canvas.create_line(x, y, nx, ny, fill=color, width=2, arrow=tk.LAST)

        label = f"ID {target.target_id}\n{target.distance_m}m {target.velocity_mps}m/s\n{target.angle_deg:+d} deg\n{item.risk_level}"
        self.canvas.create_text(x + 44, y - 10, text=label, fill="#f0f6fc", anchor=tk.W, font=("Consolas", 9))

    def _write_panel(self, evaluated: list[TargetRisk]) -> None:
        summary = summarize_targets([item.target for item in evaluated])
        lines = [
            "Radar Visualizer",
            "",
            f"source      : {self.current_state.source}",
            f"max range   : {self.max_range_m} m",
            f"target count: {len(evaluated)}",
            f"updated     : {time.strftime('%H:%M:%S', time.localtime(self.current_state.updated_at))}",
        ]
        if self.current_state.error:
            lines.extend(["", "ERROR:", self.current_state.error])

        lines.extend(["", "Highest risk by area:"])
        for area in ("left", "center", "right"):
            item = summary[area]
            if item is None:
                lines.append(f"  {area:<6}: none")
            else:
                target = item.target
                lines.append(
                    f"  {area:<6}: {item.risk_level:<9} id={target.target_id} "
                    f"d={target.distance_m}m v={target.velocity_mps}m/s a={target.angle_deg:+d}"
                )

        lines.extend(["", "Targets:"])
        for item in sorted(evaluated, key=lambda x: (-RISK_SCORE[x.risk_level], x.target.distance_m)):
            target = item.target
            lines.append(
                f"  id={target.target_id:<3} {item.area:<6} {item.risk_level:<9} "
                f"d={target.distance_m:<3}m v={target.velocity_mps:<3}m/s angle={target.angle_deg:+d}"
            )

        self.panel.configure(state=tk.NORMAL)
        self.panel.delete("1.0", tk.END)
        self.panel.insert(tk.END, "\n".join(lines))
        self.panel.configure(state=tk.DISABLED)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Visualize AT6010/MS60 BSD mmWave radar UART reports.")
    parser.add_argument("--port", help="Serial port, for example COM5 on Windows or /dev/ttyUSB0 on Linux.")
    parser.add_argument("--baud", type=int, default=921600, help="UART baud rate. Default: 921600.")
    parser.add_argument("--max-range", type=int, default=20, help="Display range in meters. Default: 20.")
    parser.add_argument("--demo", action="store_true", help="Run with synthetic targets instead of serial hardware.")
    parser.add_argument("--invert-angle", action="store_true", help="Flip angle sign if the radar's left/right direction is reversed.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.demo and not args.port:
        raise SystemExit("Specify --demo or --port COMx.")

    state_queue: queue.Queue[DisplayState] = queue.Queue()
    reader: SerialRadarReader | None = None
    if args.port:
        reader = SerialRadarReader(args.port, args.baud, state_queue)
        reader.start()

    root = tk.Tk()
    app = RadarVisualizerApp(
        root,
        state_queue,
        max_range_m=args.max_range,
        demo=args.demo,
        invert_angle=args.invert_angle,
    )

    try:
        root.mainloop()
    finally:
        if reader is not None:
            reader.stop()


if __name__ == "__main__":
    main()
