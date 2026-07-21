from __future__ import annotations

from dataclasses import asdict, dataclass


VALID_ROTATIONS = (0, 90, 180, 270)


@dataclass(frozen=True)
class CameraImageTransform:
    """Apply one side's physical mounting orientation before vision processing."""

    rotation_deg: int = 0
    flip_horizontal: bool = False
    flip_vertical: bool = False

    def __post_init__(self) -> None:
        if self.rotation_deg not in VALID_ROTATIONS:
            raise ValueError(f"rotation_deg must be one of {VALID_ROTATIONS}")

    def output_size(self, width: int, height: int) -> tuple[int, int]:
        if width <= 0 or height <= 0:
            raise ValueError("image dimensions must be positive")
        if self.rotation_deg in (90, 270):
            return height, width
        return width, height

    def apply(self, frame):
        import cv2

        transformed = frame
        if self.rotation_deg == 90:
            transformed = cv2.rotate(transformed, cv2.ROTATE_90_CLOCKWISE)
        elif self.rotation_deg == 180:
            transformed = cv2.rotate(transformed, cv2.ROTATE_180)
        elif self.rotation_deg == 270:
            transformed = cv2.rotate(transformed, cv2.ROTATE_90_COUNTERCLOCKWISE)
        if self.flip_horizontal:
            transformed = cv2.flip(transformed, 1)
        if self.flip_vertical:
            transformed = cv2.flip(transformed, 0)
        return transformed

    def as_dict(self) -> dict[str, object]:
        return asdict(self)
