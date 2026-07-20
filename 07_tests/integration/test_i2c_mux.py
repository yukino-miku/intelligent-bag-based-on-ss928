from __future__ import annotations

import errno
import multiprocessing
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / "06_software" / "board_runtime" / "common"
BMI = ROOT / "06_software" / "board_runtime" / "bmi270_backpack"
sys.path[:0] = [str(COMMON), str(BMI)]

from i2c_mux import CrossProcessI2cLock, I2cMuxTransaction, Tca9548aMux  # noqa: E402
from bmi270_backpack import UserspaceI2cBmi270, apply_hardware_profile, load_config  # noqa: E402


class FakeAdapter:
    def __init__(self) -> None:
        self.events: list[tuple[object, ...]] = []
        self.next_handle = 0
        self.read_data = b"\x24"
        self.fail_write = False

    def open(self, device: str) -> object:
        self.next_handle += 1
        handle = self.next_handle
        self.events.append((handle, "open", device))
        return handle

    def close(self, handle: object) -> None:
        self.events.append((handle, "close"))

    def set_address(self, handle: object, address: int) -> None:
        self.events.append((handle, "address", address))

    def write(self, handle: object, data: bytes) -> None:
        self.events.append((handle, "write", bytes(data)))
        if self.fail_write:
            self.fail_write = False
            raise OSError(errno.EIO, "mock EIO")

    def read(self, handle: object, length: int) -> bytes:
        self.events.append((handle, "read", length))
        return self.read_data[:length]


def _process_lock_worker(lock_path: str, output_path: str, name: str) -> None:
    lock = CrossProcessI2cLock(lock_path)
    with lock.acquire():
        with open(output_path, "a", encoding="ascii") as handle:
            handle.write(name + ":start\n")
            handle.flush()
            time.sleep(0.05)
            handle.write(name + ":end\n")


class I2cMuxTransactionTest(unittest.TestCase):
    def test_bmi270_uses_channel_zero_from_rev2_hardware_profile(self) -> None:
        profile = ROOT / "09_deliverables/board_deploy/hardware-profiles/rev2_tm6605_mr20.json"
        config = apply_hardware_profile(load_config(None), str(profile))
        self.assertEqual("0x70", config["device"]["i2c_mux_addr"])
        self.assertEqual(0, config["device"]["i2c_mux_channel"])
        self.assertEqual("0x68", config["device"]["i2c_addr"])

    def test_bmi270_uses_direct_i2c_from_legacy_hardware_profile(self) -> None:
        profile = ROOT / "09_deliverables/board_deploy/hardware-profiles/legacy_pwm_haptics.json"
        config = apply_hardware_profile(load_config(None), str(profile))
        self.assertIsNone(config["device"]["i2c_mux_addr"])
        self.assertIsNone(config["device"]["i2c_mux_channel"])

    def test_selects_mux_then_target_for_every_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = FakeAdapter()
            transaction = I2cMuxTransaction(
                "/dev/i2c-0",
                0x68,
                mux_address=0x70,
                mux_channel=0,
                lock_file=str(Path(temp_dir) / "mux.lock"),
                adapter=adapter,
            )
            result = transaction.execute(lambda device: device.write_then_read(b"\x00", 1))
            self.assertEqual(b"\x24", result)
            self.assertEqual(
                [event[1:] for event in adapter.events],
                [
                    ("open", "/dev/i2c-0"),
                    ("address", 0x70),
                    ("write", b"\x01"),
                    ("address", 0x68),
                    ("write", b"\x00"),
                    ("read", 1),
                    ("close",),
                ],
            )
            transaction.execute(lambda device: device.write(b"\x7d\x0e"))
            self.assertEqual(2, transaction.status()["transaction_count"])
            self.assertEqual(2, sum(1 for event in adapter.events if event[1:] == ("write", b"\x01")))

    def test_left_and_right_same_address_use_different_channels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = FakeAdapter()
            lock_file = str(Path(temp_dir) / "mux.lock")
            left = I2cMuxTransaction(
                "/dev/i2c-0", 0x2D, mux_address=0x70, mux_channel=1,
                lock_file=lock_file, adapter=adapter,
            )
            right = I2cMuxTransaction(
                "/dev/i2c-0", 0x2D, mux_address=0x70, mux_channel=2,
                lock_file=lock_file, adapter=adapter,
            )
            left.execute(lambda device: device.write(b"L"))
            right.execute(lambda device: device.write(b"R"))
            writes = [event[2] for event in adapter.events if event[1] == "write"]
            self.assertEqual([b"\x02", b"L", b"\x04", b"R"], writes)

    def test_bmi270_reselects_channel_zero_for_each_register_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = FakeAdapter()
            transaction = I2cMuxTransaction(
                "/dev/i2c-0", 0x68, mux_address=0x70, mux_channel=0,
                lock_file=str(Path(temp_dir) / "mux.lock"), adapter=adapter,
            )
            sensor = UserspaceI2cBmi270(
                0, 0x68, init_sensor=False, transaction=transaction
            )
            self.assertEqual(0x24, sensor.read_reg(sensor.CHIP_ID))
            mux_writes = [
                event for event in adapter.events if event[1:] == ("write", b"\x01")
            ]
            self.assertEqual(2, len(mux_writes))

    def test_direct_i2c_fallback_does_not_select_mux(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = FakeAdapter()
            transaction = I2cMuxTransaction(
                "/dev/i2c-0", 0x2D,
                lock_file=str(Path(temp_dir) / "mux.lock"), adapter=adapter,
            )
            transaction.execute(lambda device: device.write(b"X"))
            addresses = [event[2] for event in adapter.events if event[1] == "address"]
            self.assertEqual([0x2D], addresses)

    def test_invalid_channel_and_missing_lock_directory_are_explicit(self) -> None:
        with self.assertRaises(ValueError):
            Tca9548aMux.channel_mask(8)
        with tempfile.TemporaryDirectory() as temp_dir:
            transaction = I2cMuxTransaction(
                "/dev/i2c-0", 0x68, mux_address=0x70, mux_channel=0,
                lock_file=str(Path(temp_dir) / "missing" / "mux.lock"), adapter=FakeAdapter(),
            )
            if os.name != "nt":
                with self.assertRaisesRegex(RuntimeError, "lock directory"):
                    transaction.execute(lambda device: device.write(b"X"))

    def test_error_is_counted_and_lock_is_released(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = FakeAdapter()
            transaction = I2cMuxTransaction(
                "/dev/i2c-0", 0x68, mux_address=0x70, mux_channel=0,
                lock_file=str(Path(temp_dir) / "mux.lock"), adapter=adapter,
            )
            adapter.fail_write = True
            with self.assertRaises(OSError):
                transaction.execute(lambda device: device.write(b"X"))
            transaction.execute(lambda device: device.write(b"Y"))
            status = transaction.status()
            self.assertEqual(1, status["error_count"])
            self.assertEqual(1, status["eio_count"])

    def test_threaded_transactions_do_not_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_file = str(Path(temp_dir) / "mux.lock")
            active = 0
            max_active = 0
            guard = threading.Lock()
            transactions = [
                I2cMuxTransaction(
                    "/dev/i2c-0", 0x68, mux_address=0x70, mux_channel=channel,
                    lock_file=lock_file, adapter=FakeAdapter(),
                )
                for channel in (0, 1)
            ]

            def run(transaction: I2cMuxTransaction) -> None:
                def operation(device: object) -> None:
                    nonlocal active, max_active
                    with guard:
                        active += 1
                        max_active = max(max_active, active)
                    time.sleep(0.03)
                    device.write(b"X")  # type: ignore[attr-defined]
                    with guard:
                        active -= 1

                transaction.execute(operation)

            threads = [threading.Thread(target=run, args=(transaction,)) for transaction in transactions]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(1, max_active)

    @unittest.skipIf(os.name == "nt", "fcntl process lock is Linux-only")
    def test_process_lock_serializes_independent_processes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = str(Path(temp_dir) / "mux.lock")
            output_path = str(Path(temp_dir) / "events.txt")
            processes = [
                multiprocessing.Process(target=_process_lock_worker, args=(lock_path, output_path, name))
                for name in ("a", "b")
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(2.0)
                self.assertEqual(0, process.exitcode)
            lines = Path(output_path).read_text(encoding="ascii").splitlines()
            self.assertIn(lines, (["a:start", "a:end", "b:start", "b:end"], ["b:start", "b:end", "a:start", "a:end"]))


if __name__ == "__main__":
    unittest.main()
