"""Image-space geometry for detection overlays (standard library only).

Detections are stored as normalized ``[x, y, w, h]`` boxes in the image as a
person sees it. Phone photos often store pixels sideways and record the
display rotation in the JPEG EXIF Orientation tag; a detector that ignores
that tag returns boxes in the stored frame, which would be drawn in the
wrong place. These helpers read the tag and map boxes and polygons into the
displayed frame.
"""
from __future__ import annotations

import math
import struct
from typing import Sequence

_TOLERANCE = 0.02  # normalized overshoot accepted (and clipped) from detectors


def jpeg_exif_orientation(data: bytes) -> int:
    """Return the EXIF Orientation (1-8) of a JPEG, or 1 when absent/invalid."""
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return 1
    offset = 2
    while offset + 4 <= len(data):
        if data[offset] != 0xFF:
            return 1
        marker = data[offset + 1]
        if marker in (0xD9, 0xDA):  # end of image / start of scan
            return 1
        length = struct.unpack(">H", data[offset + 2:offset + 4])[0]
        segment = data[offset + 4:offset + 2 + length]
        if marker == 0xE1 and segment[:6] == b"Exif\x00\x00":
            return _tiff_orientation(segment[6:])
        offset += 2 + length
    return 1


def _tiff_orientation(tiff: bytes) -> int:
    if len(tiff) < 8:
        return 1
    order = tiff[:2]
    if order == b"II":
        endian = "<"
    elif order == b"MM":
        endian = ">"
    else:
        return 1
    try:
        ifd = struct.unpack(f"{endian}I", tiff[4:8])[0]
        count = struct.unpack(f"{endian}H", tiff[ifd:ifd + 2])[0]
        for index in range(count):
            entry = ifd + 2 + index * 12
            tag, kind = struct.unpack(f"{endian}HH", tiff[entry:entry + 4])
            if tag == 0x0112 and kind == 3:  # Orientation, SHORT
                value = struct.unpack(f"{endian}H", tiff[entry + 8:entry + 10])[0]
                return value if 1 <= value <= 8 else 1
    except struct.error:
        return 1
    return 1


def orientation_swaps_axes(orientation: int) -> bool:
    return orientation in (5, 6, 7, 8)


def _point_to_display(u: float, v: float, orientation: int) -> tuple[float, float]:
    """Map a normalized stored-frame point to the displayed frame."""
    return {
        1: (u, v),
        2: (1 - u, v),
        3: (1 - u, 1 - v),
        4: (u, 1 - v),
        5: (v, u),
        6: (1 - v, u),
        7: (1 - v, 1 - u),
        8: (v, 1 - u),
    }.get(orientation, (u, v))


def box_to_display(box: Sequence[float], orientation: int) -> list[float]:
    """Map a normalized ``[x, y, w, h]`` box from stored to displayed frame."""
    x, y, w, h = box
    corners = [_point_to_display(px, py, orientation) for px, py in ((x, y), (x + w, y + h))]
    xs = sorted(point[0] for point in corners)
    ys = sorted(point[1] for point in corners)
    return [xs[0], ys[0], xs[1] - xs[0], ys[1] - ys[0]]


def polygon_to_display(points: Sequence[Sequence[float]], orientation: int) -> list[list[float]]:
    return [list(_point_to_display(float(u), float(v), orientation)) for u, v in points]


def normalize_box(
    box: Sequence[float], *, box_format: str, width: int | None, height: int | None,
) -> list[float] | None:
    """Validate a detector box and return a normalized ``[x, y, w, h]``.

    Pixel boxes need the image size the detector used. Non-finite values,
    non-positive sizes, and boxes outside the image by more than a small
    tolerance are rejected (``None``); small overshoot is clipped.
    """
    if len(box) != 4:
        return None
    try:
        x, y, w, h = (float(value) for value in box)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (x, y, w, h)):
        return None
    if box_format == "pixel_xywh":
        if not width or not height or width <= 0 or height <= 0:
            return None
        x, w = x / width, w / width
        y, h = y / height, h / height
    elif box_format != "normalized_xywh":
        return None
    if w <= 0 or h <= 0:
        return None
    if x < -_TOLERANCE or y < -_TOLERANCE or x + w > 1 + _TOLERANCE or y + h > 1 + _TOLERANCE:
        return None
    x0, y0 = max(0.0, x), max(0.0, y)
    x1, y1 = min(1.0, x + w), min(1.0, y + h)
    if x1 <= x0 or y1 <= y0:
        return None
    return [round(x0, 6), round(y0, 6), round(x1 - x0, 6), round(y1 - y0, 6)]
