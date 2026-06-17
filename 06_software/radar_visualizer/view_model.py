import math


def radar_origin(width: int, height: int) -> tuple[int, int]:
    return width // 2, height - 100


def radar_radius(width: int, height: int) -> float:
    return max(50.0, min(width * 0.62, height - 200.0))


def polar_to_xy(
    distance_m: float,
    angle_deg: float,
    max_range_m: float,
    width: int,
    height: int,
) -> tuple[int, int]:
    distance = max(0.0, min(float(distance_m), float(max_range_m)))
    radius = radar_radius(width, height)
    origin_x, origin_y = radar_origin(width, height)
    scale = radius / float(max_range_m)
    angle_rad = math.radians(angle_deg)

    x = origin_x + math.sin(angle_rad) * distance * scale
    y = origin_y - math.cos(angle_rad) * distance * scale
    return round(x), round(y)
