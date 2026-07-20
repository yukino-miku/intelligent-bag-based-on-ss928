from __future__ import annotations

import errno
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Protocol, TypeVar

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows only.
    fcntl = None  # type: ignore[assignment]


I2C_SLAVE = 0x0703
DEFAULT_LOCK_FILE = "/run/lock/smartbag-i2c0-mux.lock"
T = TypeVar("T")


class I2cAdapter(Protocol):
    def open(self, device: str) -> object: ...

    def close(self, handle: object) -> None: ...

    def set_address(self, handle: object, address: int) -> None: ...

    def write(self, handle: object, data: bytes) -> None: ...

    def read(self, handle: object, length: int) -> bytes: ...


class LinuxI2cAdapter:
    def open(self, device: str) -> object:
        if fcntl is None:
            raise RuntimeError("Linux I2C requires fcntl/i2c-dev")
        return os.open(device, os.O_RDWR)

    def close(self, handle: object) -> None:
        os.close(int(handle))

    def set_address(self, handle: object, address: int) -> None:
        if fcntl is None:
            raise RuntimeError("Linux I2C requires fcntl/i2c-dev")
        fcntl.ioctl(int(handle), I2C_SLAVE, int(address))

    def write(self, handle: object, data: bytes) -> None:
        written = os.write(int(handle), data)
        if written != len(data):
            raise OSError(errno.EIO, f"short I2C write {written}/{len(data)}")

    def read(self, handle: object, length: int) -> bytes:
        data = os.read(int(handle), int(length))
        if len(data) != length:
            raise OSError(errno.EIO, f"short I2C read {len(data)}/{length}")
        return data


@dataclass
class I2cTransactionMetrics:
    transaction_count: int = 0
    error_count: int = 0
    eio_count: int = 0
    total_lock_wait_ms: float = 0.0
    max_lock_wait_ms: float = 0.0
    last_error: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "transaction_count": self.transaction_count,
            "error_count": self.error_count,
            "eio_count": self.eio_count,
            "total_lock_wait_ms": round(self.total_lock_wait_ms, 3),
            "max_lock_wait_ms": round(self.max_lock_wait_ms, 3),
            "last_error": self.last_error,
        }


class CrossProcessI2cLock:
    """Thread and process lock shared by every I2C0 mux client."""

    _registry_guard = threading.Lock()
    _thread_locks: dict[str, threading.RLock] = {}

    def __init__(self, path: str = DEFAULT_LOCK_FILE) -> None:
        self.path = os.path.abspath(path)
        with self._registry_guard:
            self._thread_lock = self._thread_locks.setdefault(self.path, threading.RLock())

    @contextmanager
    def acquire(self) -> Iterator[float]:
        started = time.perf_counter()
        self._thread_lock.acquire()
        fd: int | None = None
        try:
            if fcntl is not None:
                parent = Path(self.path).parent
                if not parent.exists():
                    raise RuntimeError(
                        f"I2C lock directory {parent} does not exist; run board install/preflight"
                    )
                fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o660)
                fcntl.flock(fd, fcntl.LOCK_EX)
            yield (time.perf_counter() - started) * 1000.0
        finally:
            if fd is not None and fcntl is not None:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)
            self._thread_lock.release()


@dataclass(frozen=True)
class Tca9548aMux:
    address: int = 0x70

    def __post_init__(self) -> None:
        if not 0x03 <= int(self.address) <= 0x77:
            raise ValueError(f"invalid TCA9548A address: 0x{int(self.address):02x}")

    @staticmethod
    def channel_mask(channel: int) -> bytes:
        if channel not in range(8):
            raise ValueError(f"TCA9548A channel must be 0..7, got {channel}")
        return bytes((1 << channel,))

    def select(self, adapter: I2cAdapter, handle: object, channel: int) -> None:
        adapter.set_address(handle, self.address)
        adapter.write(handle, self.channel_mask(channel))


class I2cDeviceHandle:
    def __init__(self, adapter: I2cAdapter, handle: object) -> None:
        self.adapter = adapter
        self.handle = handle

    def write(self, data: bytes) -> None:
        self.adapter.write(self.handle, bytes(data))

    def read(self, length: int) -> bytes:
        return self.adapter.read(self.handle, int(length))

    def write_then_read(self, data: bytes, length: int) -> bytes:
        self.write(data)
        return self.read(length)


class I2cMuxTransaction:
    """One atomic target transaction, including mux selection."""

    def __init__(
        self,
        device: str,
        target_address: int,
        *,
        mux_address: int | None = None,
        mux_channel: int | None = None,
        lock_file: str = DEFAULT_LOCK_FILE,
        adapter: I2cAdapter | None = None,
        metrics: I2cTransactionMetrics | None = None,
    ) -> None:
        self.device = str(device)
        self.target_address = int(target_address)
        self.mux = Tca9548aMux(int(mux_address)) if mux_address is not None else None
        self.mux_channel = mux_channel
        if self.mux is not None and mux_channel not in range(8):
            raise ValueError("mux_channel must be 0..7 when mux_address is configured")
        if self.mux is None and mux_channel is not None:
            raise ValueError("mux_channel requires mux_address")
        self.lock = CrossProcessI2cLock(lock_file)
        self.adapter = adapter or LinuxI2cAdapter()
        self.metrics = metrics or I2cTransactionMetrics()

    @contextmanager
    def open(self) -> Iterator[I2cDeviceHandle]:
        with self.lock.acquire() as wait_ms:
            self.metrics.total_lock_wait_ms += wait_ms
            self.metrics.max_lock_wait_ms = max(self.metrics.max_lock_wait_ms, wait_ms)
            handle: object | None = None
            try:
                handle = self.adapter.open(self.device)
                if self.mux is not None:
                    assert self.mux_channel is not None
                    self.mux.select(self.adapter, handle, self.mux_channel)
                self.adapter.set_address(handle, self.target_address)
                self.metrics.transaction_count += 1
                yield I2cDeviceHandle(self.adapter, handle)
            except Exception as exc:
                self.metrics.error_count += 1
                if isinstance(exc, OSError) and exc.errno == errno.EIO:
                    self.metrics.eio_count += 1
                self.metrics.last_error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                if handle is not None:
                    self.adapter.close(handle)

    def execute(self, operation: Callable[[I2cDeviceHandle], T]) -> T:
        with self.open() as device:
            return operation(device)

    def status(self) -> dict[str, object]:
        result = self.metrics.as_dict()
        result.update(
            {
                "device": self.device,
                "target_address": f"0x{self.target_address:02x}",
                "mux_address": f"0x{self.mux.address:02x}" if self.mux else None,
                "mux_channel": self.mux_channel,
                "lock_file": self.lock.path,
            }
        )
        return result

