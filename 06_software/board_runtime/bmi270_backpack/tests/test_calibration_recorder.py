import copy
import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "bmi270_backpack.py"
SPEC = importlib.util.spec_from_file_location("bmi270_backpack", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
bmi270_backpack = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bmi270_backpack
SPEC.loader.exec_module(bmi270_backpack)


def config_with_data_dir(data_dir):
    cfg = copy.deepcopy(bmi270_backpack.DEFAULT_CONFIG)
    cfg["calibration"]["data_dir"] = str(data_dir)
    return cfg


def sample_state(t_mono=10.0):
    return {
        "t_mono": t_mono,
        "dt": 0.02,
        "roll_deg": 1.2,
        "pitch_deg": 3.4,
        "yaw_deg": 5.6,
        "speed_mps": 0.12,
        "accel_g": 1.01,
        "gyro_dps": 2.3,
        "linear_acc_mps2": 0.04,
        "vx_mps": 0.0,
        "vy_mps": 0.0,
        "vz_mps": 0.0,
        "stationary": True,
        "speed_quality": "rough_imu_integration",
        "ax_g": 0.1,
        "ay_g": 0.2,
        "az_g": 0.9,
        "gx_dps": 1.1,
        "gy_dps": 1.2,
        "gz_dps": 1.3,
    }


class CalibrationRecorderTest(unittest.TestCase):
    def test_fall_fusion_runtime_is_optional_and_uses_board_config(self):
        cfg = copy.deepcopy(bmi270_backpack.DEFAULT_CONFIG)
        self.assertIsNone(bmi270_backpack.make_fall_fusion_runtime(cfg))

        with tempfile.TemporaryDirectory() as temp:
            cfg["fall_detection"] = {
                "enabled": True,
                "warning_marker": str(Path(temp) / "warning.json"),
                "alarm_log": str(Path(temp) / "fall_alarm.jsonl"),
                "warning_window_s": 10.0,
                "recovery_window_s": 7.0,
                "standing_posture_deg": 25.0,
                "standing_hold_s": 1.0,
            }
            runtime = bmi270_backpack.make_fall_fusion_runtime(cfg)

        self.assertIsNotNone(runtime)
        self.assertEqual(runtime.fusion_config.warning_window_s, 10.0)
        self.assertEqual(runtime.fusion_config.recovery_window_s, 7.0)

    def test_starts_first_file_and_writes_csv_row(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = config_with_data_dir(temp)
            recorder = bmi270_backpack.CalibrationRecorder(cfg)

            started = recorder.start("straight")
            recorder.write_sample(sample_state(), [{"code": "TEST_ALERT"}])
            stopped = recorder.stop("manual")

            path = Path(started["path"])
            self.assertEqual("straight_01.csv", path.name)
            self.assertEqual(path, Path(stopped["path"]))
            self.assertEqual(1, stopped["rows"])

            with path.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(1, len(rows))
            self.assertEqual("straight", rows[0]["mode"])
            self.assertEqual("1.20", rows[0]["roll_deg"])
            self.assertEqual("3.40", rows[0]["pitch_deg"])
            self.assertEqual("TEST_ALERT", rows[0]["alerts"])

    def test_next_file_suffix_does_not_overwrite_existing_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            data_dir = Path(temp)
            (data_dir / "hunch_01.csv").write_text("old data\n", encoding="utf-8")
            cfg = config_with_data_dir(data_dir)
            recorder = bmi270_backpack.CalibrationRecorder(cfg)

            started = recorder.start("hunch")
            recorder.stop("manual")

            self.assertEqual("hunch_02.csv", Path(started["path"]).name)
            self.assertEqual("old data\n", (data_dir / "hunch_01.csv").read_text(encoding="utf-8"))

    def test_ble_commands_start_and_stop_recorder(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = config_with_data_dir(temp)
            estimator = bmi270_backpack.MotionEstimator(cfg)
            recorder = bmi270_backpack.CalibrationRecorder(cfg)

            response = bmi270_backpack.process_command(
                "CAL_START straight_walk duration=3",
                cfg,
                estimator,
                None,
                recorder,
            )
            recorder.write_sample(sample_state(), [])
            stopped = bmi270_backpack.process_command(
                "CAL_STOP",
                cfg,
                estimator,
                None,
                recorder,
            )

            self.assertIn("OK cal_start mode=straight_walk", response)
            self.assertIn("duration=3.0", response)
            self.assertIn("OK cal_stop mode=straight_walk", stopped)
            self.assertTrue(Path(recorder.last_completed["path"]).exists())

    def test_short_ble_command_alias_keeps_start_command_small(self):
        with tempfile.TemporaryDirectory() as temp:
            cfg = config_with_data_dir(temp)
            estimator = bmi270_backpack.MotionEstimator(cfg)
            recorder = bmi270_backpack.CalibrationRecorder(cfg)
            command = "CS straight_walk 30"

            response = bmi270_backpack.process_command(command, cfg, estimator, None, recorder)
            stopped = bmi270_backpack.process_command("CE", cfg, estimator, None, recorder)

            self.assertLessEqual(len(command + "\n"), 20)
            self.assertIn("OK cal_start mode=straight_walk", response)
            self.assertIn("OK cal_stop mode=straight_walk", stopped)


    def test_posture_correction_uses_backpack_zero(self):
        cfg = copy.deepcopy(bmi270_backpack.DEFAULT_CONFIG)
        cfg["posture"].update({
            "enabled": True,
            "roll_zero_deg": 0.08,
            "pitch_zero_deg": -10.605,
            "yaw_zero_deg": 5.0,
        })
        state = sample_state()
        state.update({"roll_deg": 1.08, "pitch_deg": -23.105, "yaw_deg": 20.0})

        corrected = bmi270_backpack.apply_posture_correction(state, cfg)

        self.assertAlmostEqual(1.0, corrected["roll_deg"], places=3)
        self.assertAlmostEqual(-12.5, corrected["pitch_deg"], places=3)
        self.assertAlmostEqual(15.0, corrected["yaw_deg"], places=3)
        self.assertAlmostEqual(-23.105, corrected["raw_pitch_deg"], places=3)
        self.assertTrue(corrected["posture_corrected"])

    def test_hunch_threshold_requires_low_dynamic_hold(self):
        cfg = copy.deepcopy(bmi270_backpack.DEFAULT_CONFIG)
        cfg["thresholds"].update({
            "tilt_enabled": False,
            "hunch_enabled": True,
            "hunch_pitch_deg": -12.5,
            "hunch_hold_s": 1.0,
            "hunch_max_gyro_dps": 30.0,
            "hunch_accel_min_g": 0.75,
            "hunch_accel_max_g": 1.25,
            "impact_g": 99.0,
            "freefall_g": 0.0,
            "speed_warn_mps": 99.0,
        })
        detector = bmi270_backpack.AnomalyDetector(cfg)
        state = sample_state()
        state.update({"pitch_deg": -13.0, "gyro_dps": 5.0, "accel_g": 1.0, "speed_mps": 0.0})

        alerts = []
        for t_mono in (10.0, 10.5, 11.0):
            state["t_mono"] = t_mono
            alerts = detector.update(state)

        self.assertEqual(["HUNCH"], [alert["code"] for alert in alerts])

        detector = bmi270_backpack.AnomalyDetector(cfg)
        state.update({"gyro_dps": 45.0})
        for t_mono in (20.0, 21.0, 22.0):
            state["t_mono"] = t_mono
            alerts = detector.update(state)
        self.assertEqual([], alerts)



if __name__ == "__main__":
    unittest.main()
