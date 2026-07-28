from __future__ import annotations

import ctypes
import errno
import mmap
import os
import select
import struct
import time
from dataclasses import dataclass


IOC_NRBITS = 8
IOC_TYPEBITS = 8
IOC_SIZEBITS = 14
IOC_NRSHIFT = 0
IOC_TYPESHIFT = IOC_NRSHIFT + IOC_NRBITS
IOC_SIZESHIFT = IOC_TYPESHIFT + IOC_TYPEBITS
IOC_DIRSHIFT = IOC_SIZESHIFT + IOC_SIZEBITS
IOC_WRITE = 1
IOC_READ = 2

V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_MEMORY_MMAP = 1
V4L2_FIELD_ANY = 0
V4L2_FORMAT_SIZE = 208
V4L2_FORMAT_PIX_OFFSET = 8
V4L2_STREAMPARM_SIZE = 204
V4L2_STREAMPARM_CAPTURE_OFFSET = 4


def _ioc(direction: int, request_type: str, number: int, size: int) -> int:
    return (
        (direction << IOC_DIRSHIFT)
        | (ord(request_type) << IOC_TYPESHIFT)
        | (number << IOC_NRSHIFT)
        | (size << IOC_SIZESHIFT)
    )


def _fourcc(text: str) -> int:
    data = text.encode("ascii")
    if len(data) != 4:
        raise ValueError(f"invalid FOURCC: {text!r}")
    return data[0] | (data[1] << 8) | (data[2] << 16) | (data[3] << 24)


class _RequestBuffers(ctypes.Structure):
    _fields_ = [
        ("count", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("memory", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("flags", ctypes.c_uint8),
        ("reserved", ctypes.c_uint8 * 3),
    ]


class _Timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]


class _Timecode(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("frames", ctypes.c_uint8),
        ("seconds", ctypes.c_uint8),
        ("minutes", ctypes.c_uint8),
        ("hours", ctypes.c_uint8),
        ("userbits", ctypes.c_uint8 * 4),
    ]


class _Buffer(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("bytesused", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("field", ctypes.c_uint32),
        ("timestamp", _Timeval),
        ("timecode", _Timecode),
        ("sequence", ctypes.c_uint32),
        ("memory", ctypes.c_uint32),
        ("m", ctypes.c_uint64),
        ("length", ctypes.c_uint32),
        ("reserved2", ctypes.c_uint32),
        ("request_fd", ctypes.c_int32),
    ]


VIDIOC_S_FMT = _ioc(IOC_READ | IOC_WRITE, "V", 5, V4L2_FORMAT_SIZE)
VIDIOC_REQBUFS = _ioc(IOC_READ | IOC_WRITE, "V", 8, ctypes.sizeof(_RequestBuffers))
VIDIOC_QUERYBUF = _ioc(IOC_READ | IOC_WRITE, "V", 9, ctypes.sizeof(_Buffer))
VIDIOC_QBUF = _ioc(IOC_READ | IOC_WRITE, "V", 15, ctypes.sizeof(_Buffer))
VIDIOC_DQBUF = _ioc(IOC_READ | IOC_WRITE, "V", 17, ctypes.sizeof(_Buffer))
VIDIOC_STREAMON = _ioc(IOC_WRITE, "V", 18, ctypes.sizeof(ctypes.c_int))
VIDIOC_STREAMOFF = _ioc(IOC_WRITE, "V", 19, ctypes.sizeof(ctypes.c_int))
VIDIOC_S_PARM = _ioc(IOC_READ | IOC_WRITE, "V", 22, V4L2_STREAMPARM_SIZE)


@dataclass(frozen=True)
class NativeV4L2Config:
    device: str
    width: int
    height: int
    fps: float
    buffer_count: int = 4
    pixel_format: str = "MJPG"


class NativeV4L2SnapshotCamera:
    """Persistent V4L2 fd/mmap allocation with short STREAMON/OFF cycles."""

    def __init__(self, config: NativeV4L2Config) -> None:
        self.config = config
        self._fd: int | None = None
        self._buffers: list[mmap.mmap] = []
        self._streaming = False
        self.width = config.width
        self.height = config.height
        self.pixel_format = config.pixel_format

    @property
    def prepared(self) -> bool:
        return self._fd is not None

    @property
    def streaming(self) -> bool:
        return self._streaming

    def prepare(self) -> None:
        if self._fd is not None:
            return
        if os.name != "posix":
            raise RuntimeError("native V4L2 capture is only available on Linux")
        fd = os.open(self.config.device, os.O_RDWR | os.O_NONBLOCK)
        buffers: list[mmap.mmap] = []
        try:
            fmt = (ctypes.c_char * V4L2_FORMAT_SIZE)()
            struct.pack_into("I", fmt, 0, V4L2_BUF_TYPE_VIDEO_CAPTURE)
            struct.pack_into(
                "IIII",
                fmt,
                V4L2_FORMAT_PIX_OFFSET,
                self.config.width,
                self.config.height,
                _fourcc(self.config.pixel_format),
                V4L2_FIELD_ANY,
            )
            _xioctl(fd, VIDIOC_S_FMT, fmt, "VIDIOC_S_FMT")
            self.width, self.height, pixfmt = struct.unpack_from("III", bytes(fmt), V4L2_FORMAT_PIX_OFFSET)
            self.pixel_format = "".join(chr((pixfmt >> (8 * index)) & 0xFF) for index in range(4))

            if self.config.fps > 0:
                parm = (ctypes.c_char * V4L2_STREAMPARM_SIZE)()
                struct.pack_into("I", parm, 0, V4L2_BUF_TYPE_VIDEO_CAPTURE)
                struct.pack_into(
                    "IIII",
                    parm,
                    V4L2_STREAMPARM_CAPTURE_OFFSET,
                    0,
                    0,
                    1,
                    max(1, int(round(self.config.fps))),
                )
                _xioctl(fd, VIDIOC_S_PARM, parm, "VIDIOC_S_PARM")

            request = _RequestBuffers()
            request.count = max(2, self.config.buffer_count)
            request.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            request.memory = V4L2_MEMORY_MMAP
            _xioctl(fd, VIDIOC_REQBUFS, request, "VIDIOC_REQBUFS")
            if request.count < 2:
                raise RuntimeError(f"V4L2 allocated only {request.count} mmap buffers")
            for index in range(request.count):
                buffer = _new_buffer(index)
                _xioctl(fd, VIDIOC_QUERYBUF, buffer, "VIDIOC_QUERYBUF")
                buffers.append(
                    mmap.mmap(
                        fd,
                        buffer.length,
                        mmap.MAP_SHARED,
                        mmap.PROT_READ | mmap.PROT_WRITE,
                        offset=buffer.m,
                    )
                )
        except Exception:
            for mapped in buffers:
                mapped.close()
            os.close(fd)
            raise
        self._fd = fd
        self._buffers = buffers

    def stream_on(self) -> None:
        self.prepare()
        if self._streaming:
            return
        assert self._fd is not None
        for index in range(len(self._buffers)):
            _xioctl(self._fd, VIDIOC_QBUF, _new_buffer(index), "VIDIOC_QBUF")
        _xioctl(
            self._fd,
            VIDIOC_STREAMON,
            ctypes.c_int(V4L2_BUF_TYPE_VIDEO_CAPTURE),
            "VIDIOC_STREAMON",
        )
        self._streaming = True

    def read(self, timeout_s: float) -> tuple[bool, object | None]:
        if self._fd is None or not self._streaming:
            return False, None
        readable, _writable, _error = select.select([self._fd], [], [], max(0.0, timeout_s))
        if not readable:
            return False, None
        buffer = _new_buffer()
        try:
            _xioctl(self._fd, VIDIOC_DQBUF, buffer, "VIDIOC_DQBUF")
        except OSError as exc:
            if exc.errno == errno.EAGAIN:
                return False, None
            raise
        payload = bytes(self._buffers[buffer.index][: buffer.bytesused])
        _xioctl(self._fd, VIDIOC_QBUF, buffer, "VIDIOC_QBUF")
        return True, _decode_frame(payload, self.pixel_format, self.width, self.height)

    def stream_off(self) -> None:
        if self._fd is None or not self._streaming:
            return
        try:
            _xioctl(
                self._fd,
                VIDIOC_STREAMOFF,
                ctypes.c_int(V4L2_BUF_TYPE_VIDEO_CAPTURE),
                "VIDIOC_STREAMOFF",
            )
        finally:
            self._streaming = False

    def close(self) -> None:
        try:
            self.stream_off()
        finally:
            for mapped in self._buffers:
                mapped.close()
            self._buffers.clear()
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None


def _new_buffer(index: int = 0) -> _Buffer:
    buffer = _Buffer()
    buffer.index = index
    buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
    buffer.memory = V4L2_MEMORY_MMAP
    return buffer


def _xioctl(fd: int, request: int, argument: object, name: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    while True:
        result = libc.ioctl(fd, ctypes.c_ulong(request), ctypes.byref(argument))
        if result == 0:
            return
        error = ctypes.get_errno()
        if error == errno.EINTR:
            continue
        raise OSError(error, f"{name}: {os.strerror(error)}")


def _decode_frame(payload: bytes, pixel_format: str, width: int, height: int) -> object:
    import cv2
    import numpy as np

    normalized = pixel_format.strip("\0 ")
    if normalized in {"MJPG", "JPEG"}:
        image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    elif normalized == "YUYV":
        raw = np.frombuffer(payload, dtype=np.uint8).reshape((height, width, 2))
        image = cv2.cvtColor(raw, cv2.COLOR_YUV2BGR_YUYV)
    else:
        raise RuntimeError(f"unsupported V4L2 snapshot pixel format: {normalized}")
    if image is None:
        raise RuntimeError("V4L2 frame decode failed")
    return image
