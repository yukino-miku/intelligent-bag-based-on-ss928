from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
from typing import Iterator

try:
    import fcntl
except ImportError:  # Windows unit tests and simulation.
    fcntl = None  # type: ignore[assignment]


DEFAULT_I2C_MUX_LOCK = Path("/run/lock/smartbag-i2c0-mux.lock")


@contextmanager
def interprocess_i2c_mux_lock(
    path: str | Path = DEFAULT_I2C_MUX_LOCK,
    *,
    disabled: bool = False,
) -> Iterator[None]:
    """Serialize TCA9548A channel selection and the following I2C transfer."""

    if disabled or fcntl is None:
        yield
        return
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
