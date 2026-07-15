import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from vision_obstacle_tracker import create_yolo_model, display_wait_ms, open_capture, parse_args, read_initial_frame, video_should_skip_frames


class RuntimeOptionsTest(unittest.TestCase):
    def test_initial_camera_frame_waits_through_startup_misses(self) -> None:
        class SlowFirstFrameCapture:
            def __init__(self) -> None:
                self.calls = 0

            def read(self):
                self.calls += 1
                if self.calls < 3:
                    return False, None
                return True, "frame"

        capture = SlowFirstFrameCapture()

        ok, frame = read_initial_frame(capture, timeout_s=1.0, sleep_s=0.0)

        self.assertTrue(ok)
        self.assertEqual("frame", frame)
        self.assertEqual(3, capture.calls)

    def test_default_runtime_options_use_sensitive_camera_profile(self) -> None:
        with patch.object(sys, "argv", ["vision_obstacle_tracker.py"]):
            args = parse_args()

        self.assertEqual("camera", args.source)
        self.assertEqual("ffmpeg", args.camera_backend)
        self.assertEqual("balanced", args.runtime_profile)
        self.assertEqual(1280, args.width)
        self.assertEqual(720, args.height)
        self.assertEqual("vehicle_botsort.yaml", args.tracker)
        self.assertEqual(1024, args.imgsz)
        self.assertEqual(0.02, args.conf)
        self.assertEqual(50, args.max_det)
        self.assertFalse(args.export_openvino)
        self.assertFalse(args.prefer_openvino)
        self.assertEqual(0.0, args.roi_top_ratio)
        self.assertEqual(0.92, args.self_mask_bottom_ratio)
        self.assertFalse(args.disable_self_object_filter)
        self.assertEqual(1.0, args.display_scale)
        self.assertEqual(1, args.display_every_n)
        self.assertEqual("normal", args.overlay_verbosity)
        self.assertFalse(args.profile)
        self.assertEqual(1.2, args.camera_height)
        self.assertEqual(120.0, args.fov)
        self.assertEqual("diagonal", args.fov_type)
        self.assertEqual(5.0, args.camera_pitch)
        self.assertIsNone(args.calibration_file)
        self.assertEqual(0.25, args.pitch_adjust_step)
        self.assertEqual(1.0, args.pitch_smoothing)
        self.assertIsNone(args.risk_log_csv)
        self.assertEqual("fused", args.distance_mode)
        self.assertEqual("off", args.enhance)
        self.assertEqual("light", args.ego_motion_mode)
        self.assertEqual(5, args.ego_motion_every_n)
        self.assertIn("car", args.target_classes)
        self.assertIn("bicycle", args.target_classes)

    def test_quality_profile_can_still_be_requested_explicitly(self) -> None:
        with patch.object(
            sys,
            "argv",
            [
                "vision_obstacle_tracker.py",
                "--runtime-profile",
                "quality",
            ],
        ):
            args = parse_args()

        self.assertEqual(1920, args.width)
        self.assertEqual(1080, args.height)
        self.assertEqual(1024, args.imgsz)
        self.assertEqual(0.02, args.conf)
        self.assertEqual(50, args.max_det)

    def test_cpu_demo_profile_uses_smaller_yolo_settings(self) -> None:
        with patch.object(
            sys,
            "argv",
            [
                "vision_obstacle_tracker.py",
                "--runtime-profile",
                "cpu_demo",
            ],
        ):
            args = parse_args()

        self.assertEqual(960, args.width)
        self.assertEqual(540, args.height)
        self.assertEqual(640, args.imgsz)
        self.assertEqual(0.05, args.conf)
        self.assertEqual(40, args.max_det)

    def test_board_cpu_profile_and_alert_options(self) -> None:
        with patch.object(
            sys,
            "argv",
            [
                "vision_obstacle_tracker.py",
                "--runtime-profile",
                "board_cpu",
                "--camera-device",
                "/dev/video0",
                "--side",
                "auto",
                "--center-side",
                "both",
                "--emit-alert-jsonl",
                "--alert-min-level",
                "2",
                "--alert-rate-limit",
                "0.4",
            ],
        ):
            args = parse_args()

        self.assertEqual(640, args.width)
        self.assertEqual(480, args.height)
        self.assertEqual(416, args.imgsz)
        self.assertEqual(0.06, args.conf)
        self.assertEqual(30, args.max_det)
        self.assertEqual("/dev/video0", args.camera_device)
        self.assertEqual("auto", args.side)
        self.assertEqual("both", args.center_side)
        self.assertTrue(args.emit_alert_jsonl)
        self.assertEqual(2, args.alert_min_level)
        self.assertEqual(0.4, args.alert_rate_limit)

    def test_ss928_om_backend_is_explicitly_selectable_but_not_faked(self) -> None:
        with patch.object(
            sys,
            "argv",
            ["vision_obstacle_tracker.py", "--detector-backend", "ss928_om", "--model", "model.om"],
        ):
            args = parse_args()

        self.assertEqual("ss928_om", args.detector_backend)

    def test_runtime_profile_can_be_overridden_by_explicit_values(self) -> None:
        with patch.object(
            sys,
            "argv",
            [
                "vision_obstacle_tracker.py",
                "--runtime-profile",
                "realtime",
                "--width",
                "1920",
                "--height",
                "1080",
                "--imgsz",
                "864",
            ],
        ):
            args = parse_args()

        self.assertEqual(1920, args.width)
        self.assertEqual(1080, args.height)
        self.assertEqual(864, args.imgsz)

    def test_openvino_export_option_reloads_exported_model(self) -> None:
        with patch.object(sys, "argv", ["vision_obstacle_tracker.py", "--model", "yolo11n.pt", "--export-openvino"]):
            args = parse_args()

        fake_model = MagicMock()
        fake_model.export.return_value = "yolo11n_openvino_model"
        fake_yolo = MagicMock(side_effect=[fake_model, "openvino-model"])

        model = create_yolo_model(args, yolo_cls=fake_yolo)

        fake_yolo.assert_any_call("yolo11n.pt")
        fake_model.export.assert_called_once_with(format="openvino")
        fake_yolo.assert_any_call("yolo11n_openvino_model")
        self.assertEqual("openvino-model", model)

    def test_prefer_openvino_loads_existing_export_without_exporting(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "bag_detector.pt"
            openvino_dir = Path(temp_dir) / "bag_detector_openvino_model"
            model_path.write_bytes(b"placeholder")
            openvino_dir.mkdir()

            with patch.object(
                sys,
                "argv",
                ["vision_obstacle_tracker.py", "--model", str(model_path), "--prefer-openvino"],
            ):
                args = parse_args()

            fake_yolo = MagicMock(return_value="openvino-model")

            model = create_yolo_model(args, yolo_cls=fake_yolo)

            fake_yolo.assert_called_once_with(str(openvino_dir))
            self.assertEqual("openvino-model", model)

    def test_prefer_openvino_falls_back_to_pt_when_export_dir_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "bag_detector.pt"
            model_path.write_bytes(b"placeholder")

            with patch.object(
                sys,
                "argv",
                ["vision_obstacle_tracker.py", "--model", str(model_path), "--prefer-openvino"],
            ):
                args = parse_args()

            fake_yolo = MagicMock(return_value="pt-model")

            model = create_yolo_model(args, yolo_cls=fake_yolo)

            fake_yolo.assert_called_once_with(str(model_path))
            self.assertEqual("pt-model", model)

    def test_prefer_openvino_missing_export_prints_actionable_hint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "bag_detector.pt"
            model_path.write_bytes(b"placeholder")

            with patch.object(
                sys,
                "argv",
                ["vision_obstacle_tracker.py", "--model", str(model_path), "--prefer-openvino"],
            ):
                args = parse_args()

            fake_yolo = MagicMock(return_value="pt-model")

            with patch("builtins.print") as print_mock:
                create_yolo_model(args, yolo_cls=fake_yolo)

        printed = "\n".join(str(call.args[0]) for call in print_mock.call_args_list if call.args)
        self.assertIn("--export-openvino", printed)
        self.assertIn("PyTorch CPU", printed)

    def test_vehicle_botsort_keeps_weak_detections_for_fast_objects(self) -> None:
        tracker_config = Path(__file__).resolve().parents[1] / "vehicle_botsort.yaml"
        text = tracker_config.read_text(encoding="utf-8")

        self.assertIn("track_high_thresh: 0.15", text)
        self.assertIn("track_low_thresh: 0.03", text)
        self.assertIn("new_track_thresh: 0.10", text)

    def test_display_wait_does_not_add_video_frame_delay_after_processing(self) -> None:
        with patch.object(sys, "argv", ["vision_obstacle_tracker.py", "--source", "video", "--video", "input.mp4"]):
            args = parse_args()

        self.assertEqual(1, display_wait_ms(args, capture_fps=30.0))

    def test_video_preview_skips_stale_frames_by_default(self) -> None:
        with patch.object(sys, "argv", ["vision_obstacle_tracker.py", "--source", "video", "--video", "input.mp4"]):
            args = parse_args()

        self.assertTrue(video_should_skip_frames(args))

    def test_video_every_frame_disables_realtime_skipping(self) -> None:
        with patch.object(
            sys,
            "argv",
            ["vision_obstacle_tracker.py", "--source", "video", "--video", "input.mp4", "--video-every-frame"],
        ):
            args = parse_args()

        self.assertFalse(video_should_skip_frames(args))

    def test_video_preview_uses_realtime_latest_frame_capture_by_default(self) -> None:
        with patch.object(sys, "argv", ["vision_obstacle_tracker.py", "--source", "video", "--video", "input.mp4"]):
            args = parse_args()
        fake_capture = MagicMock()
        fake_capture.isOpened.return_value = True

        with patch("vision_obstacle_tracker.RealtimeVideoFileCapture", return_value=fake_capture) as realtime_capture:
            capture = open_capture(args)

        realtime_capture.assert_called_once_with(Path("input.mp4"))
        self.assertIs(fake_capture, capture)


if __name__ == "__main__":
    unittest.main()
