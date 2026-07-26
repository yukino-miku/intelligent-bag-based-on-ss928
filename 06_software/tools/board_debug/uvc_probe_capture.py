#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import mmap
import os
import select
import struct
import time
from pathlib import Path


IOC_NRBITS = 8
IOC_TYPEBITS = 8
IOC_SIZEBITS = 14
IOC_DIRBITS = 2
IOC_NRSHIFT = 0
IOC_TYPESHIFT = IOC_NRSHIFT + IOC_NRBITS
IOC_SIZESHIFT = IOC_TYPESHIFT + IOC_TYPEBITS
IOC_DIRSHIFT = IOC_SIZESHIFT + IOC_SIZEBITS
IOC_WRITE = 1
IOC_READ = 2

V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_MEMORY_MMAP = 1
V4L2_FIELD_ANY = 0
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_STREAMING = 0x04000000
V4L2_FORMAT_SIZE = 208
V4L2_FORMAT_PIX_OFFSET = 8
V4L2_STREAMPARM_SIZE = 204
V4L2_STREAMPARM_CAPTURE_OFFSET = 4


def fourcc(text: str) -> int:
    data = text.encode("ascii")
    if len(data) != 4:
        raise ValueError(text)
    return data[0] | (data[1] << 8) | (data[2] << 16) | (data[3] << 24)


def fourcc_text(value: int) -> str:
    return "".join(chr((value >> (8 * i)) & 0xFF) for i in range(4))


def ioc(direction: int, request_type: str, number: int, size: int) -> int:
    return (
        (direction << IOC_DIRSHIFT)
        | (ord(request_type) << IOC_TYPESHIFT)
        | (number << IOC_NRSHIFT)
        | (size << IOC_SIZESHIFT)
    )


class V4L2Capability(ctypes.Structure):
    _fields_ = [
        ("driver", ctypes.c_char * 16),
        ("card", ctypes.c_char * 32),
        ("bus_info", ctypes.c_char * 32),
        ("version", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("device_caps", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 3),
    ]


class V4L2FmtDesc(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("description", ctypes.c_char * 32),
        ("pixelformat", ctypes.c_uint32),
        ("mbus_code", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 3),
    ]


class V4L2RequestBuffers(ctypes.Structure):
    _fields_ = [
        ("count", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("memory", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("flags", ctypes.c_uint8),
        ("reserved", ctypes.c_uint8 * 3),
    ]


class Timeval(ctypes.Structure):
    _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]


class V4L2Timecode(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("frames", ctypes.c_uint8),
        ("seconds", ctypes.c_uint8),
        ("minutes", ctypes.c_uint8),
        ("hours", ctypes.c_uint8),
        ("userbits", ctypes.c_uint8 * 4),
    ]


class V4L2Buffer(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("bytesused", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("field", ctypes.c_uint32),
        ("timestamp", Timeval),
        ("timecode", V4L2Timecode),
        ("sequence", ctypes.c_uint32),
        ("memory", ctypes.c_uint32),
        ("m", ctypes.c_uint64),
        ("length", ctypes.c_uint32),
        ("reserved2", ctypes.c_uint32),
        ("request_fd", ctypes.c_int32),
    ]


VIDIOC_QUERYCAP = ioc(IOC_READ, "V", 0, ctypes.sizeof(V4L2Capability))
VIDIOC_ENUM_FMT = ioc(IOC_READ | IOC_WRITE, "V", 2, ctypes.sizeof(V4L2FmtDesc))
VIDIOC_G_FMT = ioc(IOC_READ | IOC_WRITE, "V", 4, V4L2_FORMAT_SIZE)
VIDIOC_S_FMT = ioc(IOC_READ | IOC_WRITE, "V", 5, V4L2_FORMAT_SIZE)
VIDIOC_REQBUFS = ioc(IOC_READ | IOC_WRITE, "V", 8, ctypes.sizeof(V4L2RequestBuffers))
VIDIOC_QUERYBUF = ioc(IOC_READ | IOC_WRITE, "V", 9, ctypes.sizeof(V4L2Buffer))
VIDIOC_QBUF = ioc(IOC_READ | IOC_WRITE, "V", 15, ctypes.sizeof(V4L2Buffer))
VIDIOC_DQBUF = ioc(IOC_READ | IOC_WRITE, "V", 17, ctypes.sizeof(V4L2Buffer))
VIDIOC_STREAMON = ioc(IOC_WRITE, "V", 18, ctypes.sizeof(ctypes.c_int))
VIDIOC_STREAMOFF = ioc(IOC_WRITE, "V", 19, ctypes.sizeof(ctypes.c_int))
VIDIOC_G_PARM = ioc(IOC_READ | IOC_WRITE, "V", 21, V4L2_STREAMPARM_SIZE)
VIDIOC_S_PARM = ioc(IOC_READ | IOC_WRITE, "V", 22, V4L2_STREAMPARM_SIZE)


libc = ctypes.CDLL(None, use_errno=True)


def xioctl(fd: int, request: int, arg, name: str = "ioctl") -> None:
    while True:
        ret = libc.ioctl(fd, ctypes.c_ulong(request), ctypes.byref(arg))
        if ret == 0:
            return
        err = ctypes.get_errno()
        if err == errno.EINTR:
            continue
        raise OSError(err, f"{name}: {os.strerror(err)}")


def decode_c_string(value: bytes) -> str:
    return value.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def query_capability(device: str) -> tuple[V4L2Capability, list[tuple[str, str]]]:
    fd = os.open(device, os.O_RDWR | os.O_NONBLOCK)
    try:
        cap = V4L2Capability()
        xioctl(fd, VIDIOC_QUERYCAP, cap, "VIDIOC_QUERYCAP")
        formats: list[tuple[str, str]] = []
        index = 0
        while True:
            desc = V4L2FmtDesc()
            desc.index = index
            desc.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            try:
                xioctl(fd, VIDIOC_ENUM_FMT, desc, "VIDIOC_ENUM_FMT")
            except OSError as exc:
                if exc.errno == errno.EINVAL:
                    break
                raise
            formats.append((fourcc_text(desc.pixelformat), decode_c_string(bytes(desc.description))))
            index += 1
        return cap, formats
    finally:
        os.close(fd)


def make_format(width: int, height: int, pixfmt: int):
    fmt = (ctypes.c_char * V4L2_FORMAT_SIZE)()
    struct.pack_into("I", fmt, 0, V4L2_BUF_TYPE_VIDEO_CAPTURE)
    struct.pack_into("IIII", fmt, V4L2_FORMAT_PIX_OFFSET, width, height, pixfmt, V4L2_FIELD_ANY)
    return fmt


def read_format(fmt) -> tuple[int, int, str, int]:
    width, height, pixfmt, _field, _bpl, sizeimage = struct.unpack_from("IIIIII", bytes(fmt), V4L2_FORMAT_PIX_OFFSET)
    return width, height, fourcc_text(pixfmt), sizeimage


def set_frame_rate(fd: int, fps: float) -> tuple[int, int] | None:
    if fps <= 0:
        return None
    parm = (ctypes.c_char * V4L2_STREAMPARM_SIZE)()
    struct.pack_into("I", parm, 0, V4L2_BUF_TYPE_VIDEO_CAPTURE)
    struct.pack_into("IIII", parm, V4L2_STREAMPARM_CAPTURE_OFFSET, 0, 0, 1, max(1, int(round(fps))))
    xioctl(fd, VIDIOC_S_PARM, parm, "VIDIOC_S_PARM")
    numerator, denominator = struct.unpack_from("II", bytes(parm), V4L2_STREAMPARM_CAPTURE_OFFSET + 8)
    return numerator, denominator


def capture_one(device: str, output_dir: Path, width: int, height: int, preferred_formats: list[str], fps: float) -> Path:
    cap, formats = query_capability(device)
    caps = cap.device_caps or cap.capabilities
    if not caps & V4L2_CAP_VIDEO_CAPTURE:
        raise RuntimeError(f"{device} is not a video capture node")
    if not caps & V4L2_CAP_STREAMING:
        raise RuntimeError(f"{device} does not support streaming")

    supported = {fmt for fmt, _desc in formats}
    choices = [fmt for fmt in preferred_formats if fmt in supported] or [fmt for fmt, _desc in formats]
    last_error: Exception | None = None
    for fmt_text in choices:
        try:
            return _capture_one_with_format(device, output_dir, width, height, fmt_text, fps)
        except Exception as exc:
            last_error = exc
            print(f"{device}: capture failed for {fmt_text}: {exc}")
    assert last_error is not None
    raise last_error


def _capture_one_with_format(device: str, output_dir: Path, width: int, height: int, fmt_text: str, fps: float) -> Path:
    fd = os.open(device, os.O_RDWR | os.O_NONBLOCK)
    buffers: list[mmap.mmap] = []
    streaming = False
    try:
        fmt = make_format(width, height, fourcc(fmt_text))
        xioctl(fd, VIDIOC_S_FMT, fmt, "VIDIOC_S_FMT")
        got_width, got_height, got_fmt, sizeimage = read_format(fmt)
        frame_rate = set_frame_rate(fd, fps)
        if frame_rate is not None:
            num, den = frame_rate
            print(f"{device}: requested fps={fps:g}, driver timeperframe={num}/{den}")

        req = V4L2RequestBuffers()
        req.count = 4
        req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        req.memory = V4L2_MEMORY_MMAP
        xioctl(fd, VIDIOC_REQBUFS, req, "VIDIOC_REQBUFS")
        if req.count < 2:
            raise RuntimeError(f"only {req.count} mmap buffers allocated")

        for index in range(req.count):
            buf = V4L2Buffer()
            buf.index = index
            buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            buf.memory = V4L2_MEMORY_MMAP
            xioctl(fd, VIDIOC_QUERYBUF, buf, "VIDIOC_QUERYBUF")
            mm = mmap.mmap(fd, buf.length, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=buf.m)
            buffers.append(mm)
            xioctl(fd, VIDIOC_QBUF, buf, "VIDIOC_QBUF")

        buf_type = ctypes.c_int(V4L2_BUF_TYPE_VIDEO_CAPTURE)
        xioctl(fd, VIDIOC_STREAMON, buf_type, "VIDIOC_STREAMON")
        streaming = True

        deadline = time.time() + 5.0
        while True:
            timeout = deadline - time.time()
            if timeout <= 0:
                raise TimeoutError("timed out waiting for frame")
            readable, _writable, _error = select.select([fd], [], [], timeout)
            if not readable:
                continue
            buf = V4L2Buffer()
            buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
            buf.memory = V4L2_MEMORY_MMAP
            try:
                xioctl(fd, VIDIOC_DQBUF, buf, "VIDIOC_DQBUF")
            except OSError as exc:
                if exc.errno == errno.EAGAIN:
                    continue
                raise
            frame = buffers[buf.index][: buf.bytesused]
            ext = "jpg" if got_fmt.strip("\0") in ("MJPG", "JPEG") else got_fmt.strip("\0").lower()
            output_dir.mkdir(parents=True, exist_ok=True)
            out = output_dir / f"{Path(device).name}_{got_width}x{got_height}_{got_fmt.strip()}_{buf.bytesused}.{ext}"
            out.write_bytes(frame)
            print(
                f"{device}: captured {buf.bytesused} bytes "
                f"{got_width}x{got_height} {got_fmt.strip()} -> {out}"
            )
            return out
    finally:
        if streaming:
            try:
                buf_type = ctypes.c_int(V4L2_BUF_TYPE_VIDEO_CAPTURE)
                xioctl(fd, VIDIOC_STREAMOFF, buf_type, "VIDIOC_STREAMOFF")
            except OSError:
                pass
        for mm in buffers:
            mm.close()
        os.close(fd)


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe and capture frames from UVC /dev/video nodes.")
    parser.add_argument("devices", nargs="*", default=["/dev/video0", "/dev/video2"])
    parser.add_argument("--out-dir", default="/tmp/smartbag_camera_probe")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=float, default=0.0, help="Optional requested camera FPS via VIDIOC_S_PARM.")
    parser.add_argument("--preferred-formats", default="MJPG,YUYV")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    preferred_formats = [item.strip() for item in args.preferred_formats.split(",") if item.strip()]
    ok = True

    print(
        "ctypes sizes: "
        f"capability={ctypes.sizeof(V4L2Capability)} "
        f"format={V4L2_FORMAT_SIZE} "
        f"buffer={ctypes.sizeof(V4L2Buffer)}"
    )
    for device in args.devices:
        print(f"\n== {device} ==")
        try:
            cap, formats = query_capability(device)
            caps = cap.device_caps or cap.capabilities
            print(f"driver={decode_c_string(bytes(cap.driver))}")
            print(f"card={decode_c_string(bytes(cap.card))}")
            print(f"bus={decode_c_string(bytes(cap.bus_info))}")
            print(f"capabilities=0x{cap.capabilities:08x} device_caps=0x{cap.device_caps:08x}")
            print("formats=" + ", ".join(f"{fmt}:{desc}" for fmt, desc in formats))
            if caps & V4L2_CAP_VIDEO_CAPTURE:
                capture_one(device, out_dir, args.width, args.height, preferred_formats, args.fps)
            else:
                print(f"{device}: skip capture, not V4L2_CAP_VIDEO_CAPTURE")
        except Exception as exc:
            ok = False
            print(f"{device}: ERROR {exc}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
