"""Minimal IIIF Image API 3.0 (level 1: regions, width/height sizes, rotation 0/90/180/270, default/gray,
jpg/png/webp) served from delivery copies, rights-filtered like every visitor route.

Implemented inside the API instead of a separate Cantaloupe/IIPImage service to keep the edge-server
service count low; tiles are cached in-process. Swap for a dedicated IIIF server if the §3.4 benchmark
shows image serving competing with visitor latency.
"""

from __future__ import annotations

import io
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from PIL import Image
from sqlalchemy.orm import Session

from archive import storage
from archive.api.visitor import _file_visible
from archive.db import get_db

router = APIRouter(prefix="/iiif", tags=["iiif"])
DB = Annotated[Session, Depends(get_db)]
FORMATS = {"jpg": ("JPEG", "image/jpeg"), "png": ("PNG", "image/png"), "webp": ("WEBP", "image/webp")}


@lru_cache(maxsize=64)
def _open(uri: str) -> Image.Image:
    img = Image.open(storage.resolve(uri))
    img.load()
    return img


@router.get("/{file_id}/info.json")
def info(file_id: int, request: Request, db: DB) -> JSONResponse:
    fv = _file_visible(db, file_id)
    img = _open(fv.storage_uri)
    base = str(request.url).rsplit("/info.json", 1)[0]
    body = {
        "@context": "http://iiif.io/api/image/3/context.json",
        "id": base, "type": "ImageService3", "protocol": "http://iiif.io/api/image", "profile": "level1",
        "width": img.width, "height": img.height,
        "tiles": [{"width": 512, "scaleFactors": [1, 2, 4, 8]}],
        "extraFormats": ["png", "webp"],
    }
    return JSONResponse(body, headers={"Cache-Control": "public, max-age=3600"},
                        media_type="application/ld+json")


def _region(img: Image.Image, region: str) -> Image.Image:
    if region == "full":
        return img
    if region == "square":
        side = min(img.size)
        left, top = (img.width - side) // 2, (img.height - side) // 2
        return img.crop((left, top, left + side, top + side))
    if region.startswith("pct:"):
        x, y, w, h = (float(v) for v in region[4:].split(","))
        box = (x / 100 * img.width, y / 100 * img.height, (x + w) / 100 * img.width, (y + h) / 100 * img.height)
    else:
        x, y, w, h = (int(v) for v in region.split(","))
        box = (x, y, min(x + w, img.width), min(y + h, img.height))
    if box[2] <= box[0] or box[3] <= box[1]:
        raise HTTPException(400, "empty region")
    return img.crop(tuple(int(v) for v in box))


def _size(img: Image.Image, size: str) -> Image.Image:
    size = size.lstrip("^")
    if size in ("max", "full"):
        return img
    if size.startswith("pct:"):
        f = float(size[4:]) / 100
        return img.resize((max(1, int(img.width * f)), max(1, int(img.height * f))))
    confined = size.startswith("!")
    w_s, h_s = size.lstrip("!").split(",")
    w = int(w_s) if w_s else None
    h = int(h_s) if h_s else None
    if confined and w and h:
        copy = img.copy()
        copy.thumbnail((w, h))
        return copy
    if w and not h:
        h = max(1, round(img.height * w / img.width))
    elif h and not w:
        w = max(1, round(img.width * h / img.height))
    if not w or not h:
        raise HTTPException(400, "invalid size")
    if w > 4000 or h > 4000:
        raise HTTPException(400, "size too large")
    return img.resize((w, h))


@router.get("/{file_id}/{region}/{size}/{rotation}/{quality_format}")
def image(file_id: int, region: str, size: str, rotation: str, quality_format: str, db: DB) -> Response:
    fv = _file_visible(db, file_id)
    quality, _, fmt = quality_format.partition(".")
    if fmt not in FORMATS or quality not in ("default", "color", "gray"):
        raise HTTPException(400, "unsupported quality/format")
    if rotation.lstrip("!") not in ("0", "90", "180", "270"):
        raise HTTPException(400, "unsupported rotation")
    try:
        img = _size(_region(_open(fv.storage_uri), region), size)
    except ValueError as exc:
        raise HTTPException(400, "invalid IIIF parameters") from exc
    if rotation.startswith("!"):
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if rotation.lstrip("!") != "0":
        img = img.rotate(-int(rotation.lstrip("!")), expand=True)
    if quality == "gray":
        img = img.convert("L")
    elif img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    pil_fmt, mime = FORMATS[fmt]
    img.save(buf, format=pil_fmt, quality=82)
    return Response(buf.getvalue(), media_type=mime, headers={"Cache-Control": "public, max-age=86400"})
