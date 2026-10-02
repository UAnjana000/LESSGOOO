"""Kiosk offline exhibit set (spec 3.3, 4.7, 6.3, 6.4).

The manifest lists only published, display-cleared, fully public items (rights-sensitive items are
online-only and never cached), within a fixed byte budget. It is signed with an ECDSA P-256 key so the
kiosk can verify it with WebCrypto, and carries a lease: a kiosk that has not re-synced before the lease
expires stops showing cached items. The withdrawal list is applied before any cached item is shown.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from sqlalchemy import select
from sqlalchemy.orm import Session

from archive.config import get_settings
from archive.ingest.publish import current_index_version, withdrawn_item_ids
from archive.models import ArchivalItem, FileVersion, RightsRecord
from archive.rights import item_cacheable


@lru_cache
def signing_key() -> ec.EllipticCurvePrivateKey:
    s = get_settings()
    path = Path(s.exhibit_signing_key_path or (Path(s.derivative_root) / "keys" / "exhibit-signing.pem"))
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    path.parent.mkdir(parents=True, exist_ok=True)
    key = ec.generate_private_key(ec.SECP256R1())
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    path.chmod(0o600)
    return key


def public_key_spki_b64() -> str:
    der = signing_key().public_key().public_bytes(serialization.Encoding.DER,
                                                  serialization.PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(der).decode()


def canonical(obj: Any) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sign(payload: dict[str, Any]) -> str:
    """IEEE P1363 (r||s) signature as expected by WebCrypto ECDSA verify."""
    der = signing_key().sign(canonical(payload), ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return base64.b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).decode()


def verify_signature(payload: dict[str, Any], signature_b64: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    raw = base64.b64decode(signature_b64)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    try:
        signing_key().public_key().verify(der, canonical(payload), ec.ECDSA(hashes.SHA256()))
        return True
    except InvalidSignature:
        return False


def build_manifest(db: Session, device_id: str | None = None) -> dict[str, Any]:
    s = get_settings()
    now = dt.datetime.now(dt.UTC)
    items = db.execute(select(ArchivalItem).join(RightsRecord).where(item_cacheable())
                       .order_by(ArchivalItem.id)).scalars().all()
    budget = s.exhibit_cache_budget_bytes
    used = 0
    entries, skipped = [], []
    for item in items:
        files = db.execute(select(FileVersion).where(FileVersion.item_id == item.id, FileVersion.role == "delivery",
                                                     FileVersion.deleted_at.is_(None))).scalars().all()
        size = sum(f.byte_size for f in files)
        if used + size > budget:
            skipped.append(item.id)
            continue
        used += size
        urls = [f"/api/visitor/items/{item.id}"]
        for f in files:
            urls.append(f"/api/visitor/files/{f.id}")
        entries.append({"item_id": item.id, "version": item.version, "bytes": size, "urls": urls,
                        "sha256": [f.sha256 for f in files]})
    payload = {
        "manifest_version": current_index_version(db),
        "issued_at": now.isoformat(),
        "lease_expires_at": (now + dt.timedelta(hours=s.exhibit_lease_hours)).isoformat(),
        "lease_hours": s.exhibit_lease_hours,
        "budget_bytes": budget,
        "total_bytes": used,
        "items": entries,
        "skipped_over_budget": skipped,
        "withdrawn_item_ids": withdrawn_item_ids(db),
        "shared_urls": ["/api/visitor/home", "/api/visitor/timeline", "/api/visitor/stories", "/api/visitor/map",
                        "/api/visitor/signage"],
        "device_id": device_id,
    }
    return {"payload": payload, "signature": sign(payload), "alg": "ECDSA-P256-SHA256"}
