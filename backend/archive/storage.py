"""Checksummed file storage with three separate roots.

- preservation: write-once, content-addressed by SHA-256; originals are never modified or deleted by the app
- delivery: web copies served to visitors (IIIF source JPEGs, AAC audio, ...)
- derivatives: hOCR, narration, exports (regenerable)

A filesystem with checksums is the spec-allowed alternative to an S3 store and avoids an extra
service on the edge server. In production the preservation root is a separate, versioned volume.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path

from archive.config import get_settings

ROLES = ("preservation_master", "delivery", "derivative")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class StoredFile:
    uri: str
    sha256: str
    byte_size: int
    created: bool  # False when identical content already existed (exact duplicate)


def _root_for(role: str) -> Path:
    s = get_settings()
    return {
        "preservation_master": s.preservation_root,
        "delivery": s.delivery_root,
        "derivative": s.derivative_root,
    }[role]


def _scheme(role: str) -> str:
    return {"preservation_master": "pres", "delivery": "deliv", "derivative": "deriv"}[role]


def resolve(uri: str) -> Path:
    scheme, _, rel = uri.partition("://")
    role = {"pres": "preservation_master", "deliv": "delivery", "deriv": "derivative"}[scheme]
    path = (_root_for(role) / rel).resolve()
    if not str(path).startswith(str(_root_for(role).resolve())):
        raise ValueError("path escapes storage root")
    return path


def put_bytes(data: bytes, role: str, suffix: str) -> StoredFile:
    """Store bytes content-addressed. Preservation files are written once and made read-only."""
    if role not in ROLES:
        raise ValueError(role)
    digest = sha256_bytes(data)
    rel = f"{digest[:2]}/{digest[2:4]}/{digest}{suffix}"
    target = _root_for(role) / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    uri = f"{_scheme(role)}://{rel}"
    if target.exists():
        if sha256_file(target) != digest:
            raise IOError(f"fixity mismatch on existing file {uri}")
        return StoredFile(uri, digest, len(data), created=False)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, target)
    if role == "preservation_master":
        target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    return StoredFile(uri, digest, len(data), created=True)


def read_bytes(uri: str) -> bytes:
    return resolve(uri).read_bytes()


def delete_delivery(uri: str) -> None:
    """Remove a delivery/derivative copy (used by withdrawal). Preservation masters are never deleted here."""
    if uri.startswith("pres://"):
        raise PermissionError("preservation masters are not deleted by the application")
    path = resolve(uri)
    if path.exists():
        path.unlink()


def verify(uri: str, expected_sha256: str) -> bool:
    path = resolve(uri)
    return path.exists() and sha256_file(path) == expected_sha256


def ensure_roots() -> None:
    s = get_settings()
    for p in (s.preservation_root, s.delivery_root, s.derivative_root, s.quarantine_root, s.trace_root,
              s.backup_root, s.model_cache):
        Path(p).mkdir(parents=True, exist_ok=True)


def quarantine(data: bytes, name: str, reason: str) -> Path:
    s = get_settings()
    digest = sha256_bytes(data)
    folder = Path(s.quarantine_root) / digest[:12]
    folder.mkdir(parents=True, exist_ok=True)
    safe = Path(name).name or "upload.bin"
    (folder / safe).write_bytes(data)
    (folder / "REASON.txt").write_text(reason, encoding="utf-8")
    return folder


def copy_tree(src: Path, dst: Path) -> None:
    shutil.copytree(src, dst, dirs_exist_ok=True)
