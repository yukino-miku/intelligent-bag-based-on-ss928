from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar


class GroundPointLike(Protocol):
    x_m: float
    z_m: float


PointT = TypeVar("PointT", bound=GroundPointLike)


@dataclass(frozen=True)
class CameraExtrinsics:
    """Camera ground-plane pose in the backpack coordinate frame.

    Backpack x is positive to the wearer's right, z is positive behind the
    wearer, and positive yaw turns the camera optical axis toward x-positive.
    """

    yaw_deg: float = 0.0
    roll_deg: float = 0.0
    mount_x_m: float = 0.0
    mount_z_m: float = 0.0
    calibrated: bool = False

    def camera_to_backpack(self, point: PointT) -> PointT:
        roll_rad = math.radians(self.roll_deg)
        yaw_rad = math.radians(self.yaw_deg)
        roll_corrected_x = point.x_m * math.cos(roll_rad)
        backpack_x = (
            self.mount_x_m
            + math.cos(yaw_rad) * roll_corrected_x
            + math.sin(yaw_rad) * point.z_m
        )
        backpack_z = (
            self.mount_z_m
            - math.sin(yaw_rad) * roll_corrected_x
            + math.cos(yaw_rad) * point.z_m
        )
        return type(point)(x_m=backpack_x, z_m=backpack_z)


def extrinsics_from_mapping(
    mapping: dict[str, Any],
    fallback: CameraExtrinsics | None = None,
) -> CameraExtrinsics:
    fallback = fallback or CameraExtrinsics()
    source = mapping.get("extrinsics", mapping)
    if not isinstance(source, dict):
        source = {}
    return CameraExtrinsics(
        yaw_deg=float(source.get("yaw_deg", fallback.yaw_deg)),
        roll_deg=float(source.get("roll_deg", fallback.roll_deg)),
        mount_x_m=float(source.get("mount_x_m", fallback.mount_x_m)),
        mount_z_m=float(source.get("mount_z_m", fallback.mount_z_m)),
        calibrated=bool(source.get("calibrated", fallback.calibrated)),
    )
