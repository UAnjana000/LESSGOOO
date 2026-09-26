"""Page image preprocessing: deskew, crop, denoise, contrast-normalise, split two-page spreads.

Parameters and measured values are returned so they can be kept with the page record (spec 4.3).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np
from PIL import Image

PREPROCESS_VERSION = "prep-v1"


@dataclass
class PreparedPage:
    image: np.ndarray  # grayscale uint8
    params: dict[str, Any] = field(default_factory=dict)


def load_gray(data: bytes) -> np.ndarray:
    img = Image.open(io.BytesIO(data))
    img = img.convert("L")
    return np.array(img)


def estimate_skew(gray: np.ndarray) -> float:
    """Skew angle in degrees from the minimum-area rectangle of ink pixels."""
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    coords = np.column_stack(np.where(binary > 0))
    if coords.shape[0] < 50:
        return 0.0
    angle = cv2.minAreaRect(coords[:, ::-1].astype(np.float32))[-1]
    if angle > 45:
        angle -= 90
    if abs(angle) > 15:  # implausible for a page on a cradle; treat as layout, not skew
        return 0.0
    return float(angle)


def rotate(gray: np.ndarray, angle: float) -> np.ndarray:
    if abs(angle) < 0.1:
        return gray
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)


def crop_to_content(gray: np.ndarray, margin: int = 20) -> tuple[np.ndarray, list[int]]:
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ys, xs = np.where(binary > 0)
    if xs.size == 0:
        return gray, [0, 0, gray.shape[1], gray.shape[0]]
    x0, x1 = max(0, xs.min() - margin), min(gray.shape[1], xs.max() + margin)
    y0, y1 = max(0, ys.min() - margin), min(gray.shape[0], ys.max() + margin)
    return gray[y0:y1, x0:x1], [int(x0), int(y0), int(x1), int(y1)]


def find_spread_gutter(gray: np.ndarray) -> int | None:
    """Return the x of a central gutter if the image looks like a two-page spread."""
    h, w = gray.shape
    if w < h * 1.25:
        return None
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink = binary.sum(axis=0).astype(float)
    lo, hi = int(w * 0.4), int(w * 0.6)
    window = ink[lo:hi]
    x = int(np.argmin(window)) + lo
    if ink[x] < 0.02 * ink.max():
        return x
    return None


def preprocess(data: bytes, split_spreads: bool = True) -> list[PreparedPage]:
    gray = load_gray(data)
    params: dict[str, Any] = {"version": PREPROCESS_VERSION, "source_size": [int(gray.shape[1]), int(gray.shape[0])]}
    halves = [gray]
    gutter = find_spread_gutter(gray) if split_spreads else None
    if gutter is not None:
        halves = [gray[:, :gutter], gray[:, gutter:]]
        params["split_at_x"] = gutter
    out: list[PreparedPage] = []
    for idx, half in enumerate(halves):
        p = dict(params)
        angle = estimate_skew(half)
        img = rotate(half, angle)
        img = cv2.medianBlur(img, 3)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        img = clahe.apply(img)
        img, crop = crop_to_content(img)
        p.update({"deskew_degrees": round(angle, 3), "denoise": "median3", "contrast": "clahe2.0/8x8",
                  "crop_box": crop, "spread_half": idx if gutter is not None else None})
        out.append(PreparedPage(image=img, params=p))
    return out


def detect_text_blocks(gray: np.ndarray) -> list[list[int]]:
    """Layout detection independent of OCR: morphological grouping of ink into text blocks."""
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(15, gray.shape[1] // 60), max(5, gray.shape[0] // 150)))
    dilated = cv2.dilate(binary, kernel, iterations=2)
    contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    blocks = []
    min_area = gray.shape[0] * gray.shape[1] * 0.0005
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w * h >= min_area and h > 8:
            blocks.append([int(x), int(y), int(x + w), int(y + h)])
    return blocks


def to_png(gray: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", gray)
    if not ok:
        raise ValueError("png encode failed")
    return buf.tobytes()


def delivery_jpeg(data: bytes, max_side: int = 2400, quality: int = 85) -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    img.thumbnail((max_side, max_side))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()
