from __future__ import annotations

import ctypes
import errno
import mmap
import os
import select
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX hosts
    fcntl = None


V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_MEMORY_MMAP = 1
V4L2_FIELD_ANY = 0
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_STREAMING = 0x04000000
V4L2_CAP_DEVICE_CAPS = 0x80000000
V4L2_FRMSIZE_TYPE_DISCRETE = 1
V4L2_FRMIVAL_TYPE_DISCRETE = 1


def fourcc(value: str) -> int:
    if len(value) != 4:
        raise ValueError("fourcc must contain exactly four ASCII characters")
    data = value.encode("ascii")
    return data[0] | data[1] << 8 | data[2] << 16 | data[3] << 24


def fourcc_text(value: int) -> str:
    return bytes((value >> shift) & 0xFF for shift in (0, 8, 16, 24)).decode("ascii", "replace")


V4L2_PIX_FMT_MJPEG = fourcc("MJPG")


class V4l2Capability(ctypes.Structure):
    _fields_ = [
        ("driver", ctypes.c_uint8 * 16),
        ("card", ctypes.c_uint8 * 32),
        ("bus_info", ctypes.c_uint8 * 32),
        ("version", ctypes.c_uint32),
        ("capabilities", ctypes.c_uint32),
        ("device_caps", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 3),
    ]


class V4l2PixFormat(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("pixelformat", ctypes.c_uint32),
        ("field", ctypes.c_uint32),
        ("bytesperline", ctypes.c_uint32),
        ("sizeimage", ctypes.c_uint32),
        ("colorspace", ctypes.c_uint32),
        ("priv", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("ycbcr_enc", ctypes.c_uint32),
        ("quantization", ctypes.c_uint32),
        ("xfer_func", ctypes.c_uint32),
    ]


class V4l2FormatData(ctypes.Union):
    # The kernel union also contains v4l2_window, which has pointer members.
    # Keep its 8-byte ABI alignment even though this backend only uses pix.
    _fields_ = [
        ("pix", V4l2PixFormat),
        ("raw_data", ctypes.c_uint8 * 200),
        ("_alignment", ctypes.c_uint64),
    ]


class V4l2Format(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("fmt", V4l2FormatData)]


class V4l2Fract(ctypes.Structure):
    _fields_ = [("numerator", ctypes.c_uint32), ("denominator", ctypes.c_uint32)]


class V4l2CaptureParm(ctypes.Structure):
    _fields_ = [
        ("capability", ctypes.c_uint32),
        ("capturemode", ctypes.c_uint32),
        ("timeperframe", V4l2Fract),
        ("extendedmode", ctypes.c_uint32),
        ("readbuffers", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 4),
    ]


class V4l2StreamParmData(ctypes.Union):
    _fields_ = [("capture", V4l2CaptureParm), ("raw_data", ctypes.c_uint8 * 200)]


class V4l2StreamParm(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("parm", V4l2StreamParmData)]


class V4l2RequestBuffers(ctypes.Structure):
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


class V4l2Timecode(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("frames", ctypes.c_uint8),
        ("seconds", ctypes.c_uint8),
        ("minutes", ctypes.c_uint8),
        ("hours", ctypes.c_uint8),
        ("userbits", ctypes.c_uint8 * 4),
    ]


class V4l2BufferMemory(ctypes.Union):
    _fields_ = [
        ("offset", ctypes.c_uint32),
        ("userptr", ctypes.c_ulong),
        ("planes", ctypes.c_void_p),
        ("fd", ctypes.c_int32),
    ]


class V4l2BufferRequest(ctypes.Union):
    _fields_ = [("request_fd", ctypes.c_int32), ("reserved", ctypes.c_uint32)]


class V4l2Buffer(ctypes.Structure):
    _anonymous_ = ("request",)
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("bytesused", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("field", ctypes.c_uint32),
        ("timestamp", Timeval),
        ("timecode", V4l2Timecode),
        ("sequence", ctypes.c_uint32),
        ("memory", ctypes.c_uint32),
        ("m", V4l2BufferMemory),
        ("length", ctypes.c_uint32),
        ("reserved2", ctypes.c_uint32),
        ("request", V4l2BufferRequest),
    ]


class V4l2FmtDesc(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("description", ctypes.c_uint8 * 32),
        ("pixelformat", ctypes.c_uint32),
        ("mbus_code", ctypes.c_uint32),
        ("reserved", ctypes.c_uint32 * 3),
    ]


class V4l2FrameSizeDiscrete(ctypes.Structure):
    _fields_ = [("width", ctypes.c_uint32), ("height", ctypes.c_uint32)]


class V4l2FrameSizeStepwise(ctypes.Structure):
    _fields_ = [
        ("min_width", ctypes.c_uint32),
        ("max_width", ctypes.c_uint32),
        ("step_width", ctypes.c_uint32),
        ("min_height", ctypes.c_uint32),
        ("max_height", ctypes.c_uint32),
        ("step_height", ctypes.c_uint32),
    ]


class V4l2FrameSizeData(ctypes.Union):
    _fields_ = [("discrete", V4l2FrameSizeDiscrete), ("stepwise", V4l2FrameSizeStepwise)]


class V4l2FrameSizeEnum(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("pixel_format", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("size", V4l2FrameSizeData),
        ("reserved", ctypes.c_uint32 * 2),
    ]


class V4l2FrameIntervalStepwise(ctypes.Structure):
    _fields_ = [("min", V4l2Fract), ("max", V4l2Fract), ("step", V4l2Fract)]


class V4l2FrameIntervalData(ctypes.Union):
    _fields_ = [("discrete", V4l2Fract), ("stepwise", V4l2FrameIntervalStepwise)]


class V4l2FrameIntervalEnum(ctypes.Structure):
    _fields_ = [
        ("index", ctypes.c_uint32),
        ("pixel_format", ctypes.c_uint32),
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("type", ctypes.c_uint32),
        ("interval", V4l2FrameIntervalData),
        ("reserved", ctypes.c_uint32 * 2),
    ]


_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS
_IOC_WRITE = 1
_IOC_READ = 2


def _ioc(direction: int, kind: str, number: int, data_type: type[ctypes.Structure] | type[ctypes.c_int]) -> int:
    return (
        direction << _IOC_DIRSHIFT
        | ord(kind) << _IOC_TYPESHIFT
        | number << _IOC_NRSHIFT
        | ctypes.sizeof(data_type) << _IOC_SIZESHIFT
    )


def _ior(kind: str, number: int, data_type) -> int:
    return _ioc(_IOC_READ, kind, number, data_type)


def _iow(kind: str, number: int, data_type) -> int:
    return _ioc(_IOC_WRITE, kind, number, data_type)


def _iowr(kind: str, number: int, data_type) -> int:
    return _ioc(_IOC_READ | _IOC_WRITE, kind, number, data_type)


VIDIOC_QUERYCAP = _ior("V", 0, V4l2Capability)
VIDIOC_ENUM_FMT = _iowr("V", 2, V4l2FmtDesc)
VIDIOC_G_FMT = _iowr("V", 4, V4l2Format)
VIDIOC_S_FMT = _iowr("V", 5, V4l2Format)
VIDIOC_REQBUFS = _iowr("V", 8, V4l2RequestBuffers)
VIDIOC_QUERYBUF = _iowr("V", 9, V4l2Buffer)
VIDIOC_QBUF = _iowr("V", 15, V4l2Buffer)
VIDIOC_DQBUF = _iowr("V", 17, V4l2Buffer)
VIDIOC_STREAMON = _iow("V", 18, ctypes.c_int)
VIDIOC_STREAMOFF = _iow("V", 19, ctypes.c_int)
VIDIOC_G_PARM = _iowr("V", 21, V4l2StreamParm)
VIDIOC_S_PARM = _iowr("V", 22, V4l2StreamParm)
VIDIOC_ENUM_FRAMESIZES = _iowr("V", 74, V4l2FrameSizeEnum)
VIDIOC_ENUM_FRAMEINTERVALS = _iowr("V", 75, V4l2FrameIntervalEnum)


@dataclass(frozen=True)
class NegotiatedFormat:
    width: int
    height: int
    pixel_format: str
    requested_fps: float
    actual_fps: float
    size_image: int
    buffer_count: int


@dataclass(frozen=True)
class RawMjpegFrame:
    data: bytes
    captured_at_s: float
    sequence: int
    width: int
    height: int
    pixel_format: str = "MJPG"


@dataclass
class _MappedBuffer:
    index: int
    length: int
    mapping: mmap.mmap


def _decode_c_string(value: object) -> str:
    return bytes(value).split(b"\0", 1)[0].decode("utf-8", "replace")


def _ioctl(fd: int, request: int, value: object) -> None:
    if fcntl is None:
        raise RuntimeError("native V4L2 capture requires a POSIX host with fcntl")
    while True:
        try:
            fcntl.ioctl(fd, request, value)
            return
        except OSError as exc:
            if exc.errno != errno.EINTR:
                raise


class V4l2MjpegDevice:
    """One V4L2 MJPEG device with explicit mmap STREAMON/STREAMOFF ownership."""

    backend = "v4l2_stream_toggle"

    def __init__(
        self,
        path: str,
        width: int,
        height: int,
        fps: float,
        buffer_count: int = 4,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.path = str(path)
        self.requested_width = int(width)
        self.requested_height = int(height)
        self.requested_fps = max(1.0, float(fps))
        self.requested_buffer_count = max(2, int(buffer_count))
        self.clock = clock
        self.fd = -1
        self.streaming = False
        self.buffers: list[_MappedBuffer] = []
        self.negotiated: NegotiatedFormat | None = None
        self.driver = ""
        self.card = ""
        self.bus_info = ""
        self.streamon_failures = 0
        self.streamoff_failures = 0
        self.read_failures = 0

    @property
    def is_streaming(self) -> bool:
        return self.streaming

    def open(self) -> NegotiatedFormat:
        if self.fd >= 0:
            if self.negotiated is None:
                raise RuntimeError(f"{self.path} is open without negotiated format")
            return self.negotiated
        if os.name != "posix":
            raise RuntimeError("native V4L2 capture is supported only on Linux/POSIX")
        self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        try:
            self._query_capabilities()
            self._set_format()
            self._set_frame_rate()
            self._request_and_map_buffers()
        except Exception:
            self.close()
            raise
        assert self.negotiated is not None
        return self.negotiated

    def _query_capabilities(self) -> None:
        capability = V4l2Capability()
        _ioctl(self.fd, VIDIOC_QUERYCAP, capability)
        caps = int(capability.device_caps if capability.capabilities & V4L2_CAP_DEVICE_CAPS else capability.capabilities)
        if not caps & V4L2_CAP_VIDEO_CAPTURE:
            raise RuntimeError(f"{self.path} is not a V4L2 video-capture device")
        if not caps & V4L2_CAP_STREAMING:
            raise RuntimeError(f"{self.path} does not support V4L2 streaming I/O")
        self.driver = _decode_c_string(capability.driver)
        self.card = _decode_c_string(capability.card)
        self.bus_info = _decode_c_string(capability.bus_info)

    def _set_format(self) -> None:
        video_format = V4l2Format()
        video_format.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        video_format.fmt.pix.width = self.requested_width
        video_format.fmt.pix.height = self.requested_height
        video_format.fmt.pix.pixelformat = V4L2_PIX_FMT_MJPEG
        video_format.fmt.pix.field = V4L2_FIELD_ANY
        _ioctl(self.fd, VIDIOC_S_FMT, video_format)
        if int(video_format.fmt.pix.pixelformat) != V4L2_PIX_FMT_MJPEG:
            actual = fourcc_text(int(video_format.fmt.pix.pixelformat))
            raise RuntimeError(f"{self.path} negotiated {actual}, not MJPG")
        self.negotiated = NegotiatedFormat(
            width=int(video_format.fmt.pix.width),
            height=int(video_format.fmt.pix.height),
            pixel_format=fourcc_text(int(video_format.fmt.pix.pixelformat)),
            requested_fps=self.requested_fps,
            actual_fps=self.requested_fps,
            size_image=int(video_format.fmt.pix.sizeimage),
            buffer_count=0,
        )

    def _set_frame_rate(self) -> None:
        stream_parm = V4l2StreamParm()
        stream_parm.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        stream_parm.parm.capture.timeperframe.numerator = 1
        stream_parm.parm.capture.timeperframe.denominator = max(1, int(round(self.requested_fps)))
        _ioctl(self.fd, VIDIOC_S_PARM, stream_parm)
        stream_parm = V4l2StreamParm()
        stream_parm.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        _ioctl(self.fd, VIDIOC_G_PARM, stream_parm)
        numerator = int(stream_parm.parm.capture.timeperframe.numerator)
        denominator = int(stream_parm.parm.capture.timeperframe.denominator)
        actual_fps = denominator / numerator if numerator > 0 and denominator > 0 else self.requested_fps
        assert self.negotiated is not None
        self.negotiated = NegotiatedFormat(
            **{**asdict(self.negotiated), "actual_fps": actual_fps}
        )

    def _request_and_map_buffers(self) -> None:
        request = V4l2RequestBuffers()
        request.count = self.requested_buffer_count
        request.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        request.memory = V4L2_MEMORY_MMAP
        _ioctl(self.fd, VIDIOC_REQBUFS, request)
        if request.count < 2:
            raise RuntimeError(f"{self.path} supplied only {request.count} mmap buffers")
        for index in range(int(request.count)):
            buffer = self._new_buffer(index)
            _ioctl(self.fd, VIDIOC_QUERYBUF, buffer)
            mapping = mmap.mmap(
                self.fd,
                int(buffer.length),
                flags=mmap.MAP_SHARED,
                prot=mmap.PROT_READ | mmap.PROT_WRITE,
                offset=int(buffer.m.offset),
            )
            self.buffers.append(_MappedBuffer(index, int(buffer.length), mapping))
        assert self.negotiated is not None
        self.negotiated = NegotiatedFormat(
            **{**asdict(self.negotiated), "buffer_count": len(self.buffers)}
        )

    @staticmethod
    def _new_buffer(index: int = 0) -> V4l2Buffer:
        buffer = V4l2Buffer()
        buffer.index = index
        buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
        buffer.memory = V4L2_MEMORY_MMAP
        return buffer

    def start(self) -> None:
        if self.fd < 0:
            self.open()
        if self.streaming:
            return
        try:
            for mapped in self.buffers:
                _ioctl(self.fd, VIDIOC_QBUF, self._new_buffer(mapped.index))
            buffer_type = ctypes.c_int(V4L2_BUF_TYPE_VIDEO_CAPTURE)
            _ioctl(self.fd, VIDIOC_STREAMON, buffer_type)
        except Exception:
            self.streamon_failures += 1
            self.streaming = False
            try:
                _ioctl(self.fd, VIDIOC_STREAMOFF, ctypes.c_int(V4L2_BUF_TYPE_VIDEO_CAPTURE))
            except OSError:
                pass
            raise
        self.streaming = True

    def stop(self) -> None:
        if not self.streaming:
            return
        try:
            _ioctl(self.fd, VIDIOC_STREAMOFF, ctypes.c_int(V4L2_BUF_TYPE_VIDEO_CAPTURE))
        except Exception:
            self.streamoff_failures += 1
            self.streaming = False
            raise
        self.streaming = False

    def read_frame(self, timeout_s: float) -> RawMjpegFrame:
        if not self.streaming:
            raise RuntimeError(f"cannot read {self.path} while STREAMOFF")
        deadline = self.clock() + max(0.001, float(timeout_s))
        while True:
            remaining = deadline - self.clock()
            if remaining <= 0.0:
                self.read_failures += 1
                raise TimeoutError(f"timed out waiting for a frame from {self.path}")
            readable, _, _ = select.select([self.fd], [], [], remaining)
            if not readable:
                self.read_failures += 1
                raise TimeoutError(f"timed out waiting for a frame from {self.path}")
            buffer = self._new_buffer()
            try:
                _ioctl(self.fd, VIDIOC_DQBUF, buffer)
            except OSError as exc:
                if exc.errno == errno.EAGAIN:
                    continue
                self.read_failures += 1
                raise
            if buffer.index >= len(self.buffers):
                self.read_failures += 1
                raise RuntimeError(f"driver returned invalid mmap buffer index {buffer.index}")
            mapped = self.buffers[int(buffer.index)]
            bytes_used = min(int(buffer.bytesused), mapped.length)
            mapped.mapping.seek(0)
            data = mapped.mapping.read(bytes_used)
            _ioctl(self.fd, VIDIOC_QBUF, buffer)
            captured_at_s = self.clock()
            if not data.startswith(b"\xff\xd8"):
                self.read_failures += 1
                raise RuntimeError(f"{self.path} returned a non-JPEG frame")
            negotiated = self.negotiated
            assert negotiated is not None
            return RawMjpegFrame(
                data=data,
                captured_at_s=captured_at_s,
                sequence=int(buffer.sequence),
                width=negotiated.width,
                height=negotiated.height,
                pixel_format=negotiated.pixel_format,
            )

    def close(self) -> None:
        if self.streaming:
            try:
                self.stop()
            except Exception:
                pass
        for buffer in self.buffers:
            try:
                buffer.mapping.close()
            except Exception:
                pass
        self.buffers.clear()
        if self.fd >= 0:
            try:
                request = V4l2RequestBuffers()
                request.count = 0
                request.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
                request.memory = V4L2_MEMORY_MMAP
                _ioctl(self.fd, VIDIOC_REQBUFS, request)
            except Exception:
                pass
            os.close(self.fd)
            self.fd = -1
        self.streaming = False

    def enumerate_formats(self) -> list[dict[str, object]]:
        opened_here = self.fd < 0
        if opened_here:
            self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        formats: list[dict[str, object]] = []
        try:
            format_index = 0
            while True:
                description = V4l2FmtDesc()
                description.index = format_index
                description.type = V4L2_BUF_TYPE_VIDEO_CAPTURE
                try:
                    _ioctl(self.fd, VIDIOC_ENUM_FMT, description)
                except OSError as exc:
                    if exc.errno == errno.EINVAL:
                        break
                    raise
                pixel_format = int(description.pixelformat)
                entry: dict[str, object] = {
                    "pixel_format": fourcc_text(pixel_format),
                    "description": _decode_c_string(description.description),
                    "sizes": [],
                }
                size_index = 0
                while True:
                    size = V4l2FrameSizeEnum()
                    size.index = size_index
                    size.pixel_format = pixel_format
                    try:
                        _ioctl(self.fd, VIDIOC_ENUM_FRAMESIZES, size)
                    except OSError as exc:
                        if exc.errno == errno.EINVAL:
                            break
                        raise
                    size_entry: dict[str, object] = {"type": int(size.type)}
                    if size.type == V4L2_FRMSIZE_TYPE_DISCRETE:
                        width = int(size.size.discrete.width)
                        height = int(size.size.discrete.height)
                        size_entry.update({"width": width, "height": height})
                        size_entry["fps"] = self._enumerate_fps(pixel_format, width, height)
                    else:
                        step = size.size.stepwise
                        size_entry["stepwise"] = {
                            "min_width": int(step.min_width),
                            "max_width": int(step.max_width),
                            "step_width": int(step.step_width),
                            "min_height": int(step.min_height),
                            "max_height": int(step.max_height),
                            "step_height": int(step.step_height),
                        }
                    entry["sizes"].append(size_entry)
                    size_index += 1
                formats.append(entry)
                format_index += 1
        finally:
            if opened_here and self.fd >= 0:
                os.close(self.fd)
                self.fd = -1
        return formats

    def _enumerate_fps(self, pixel_format: int, width: int, height: int) -> list[float | dict[str, object]]:
        values: list[float | dict[str, object]] = []
        index = 0
        while True:
            interval = V4l2FrameIntervalEnum()
            interval.index = index
            interval.pixel_format = pixel_format
            interval.width = width
            interval.height = height
            try:
                _ioctl(self.fd, VIDIOC_ENUM_FRAMEINTERVALS, interval)
            except OSError as exc:
                if exc.errno == errno.EINVAL:
                    break
                raise
            if interval.type == V4L2_FRMIVAL_TYPE_DISCRETE:
                numerator = int(interval.interval.discrete.numerator)
                denominator = int(interval.interval.discrete.denominator)
                values.append(round(denominator / numerator, 4) if numerator else 0.0)
            else:
                values.append({"type": int(interval.type), "continuous_or_stepwise": True})
            index += 1
        return values

    def identity(self) -> dict[str, object]:
        result: dict[str, object] = {
            "requested_path": self.path,
            "resolved_path": str(Path(self.path).resolve()),
            "driver": self.driver,
            "card": self.card,
            "bus_info": self.bus_info,
        }
        resolved = Path(self.path).resolve()
        sys_device = Path("/sys/class/video4linux") / resolved.name / "device"
        try:
            current = sys_device.resolve()
            result["sysfs_path"] = str(current)
            while current != current.parent:
                vendor = current / "idVendor"
                product = current / "idProduct"
                if vendor.exists() and product.exists():
                    result.update(
                        {
                            "usb_device": current.name,
                            "vid": vendor.read_text(encoding="ascii").strip(),
                            "pid": product.read_text(encoding="ascii").strip(),
                            "serial": (current / "serial").read_text(encoding="utf-8", errors="replace").strip()
                            if (current / "serial").exists()
                            else "",
                            "usb_speed_mbps": (current / "speed").read_text(encoding="ascii").strip()
                            if (current / "speed").exists()
                            else "",
                        }
                    )
                    break
                current = current.parent
        except OSError as exc:
            result["identity_error"] = str(exc)
        return result

    def __enter__(self) -> "V4l2MjpegDevice":
        self.open()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()
