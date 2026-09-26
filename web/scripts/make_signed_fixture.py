"""Writes a cross-language test vector for web/src/exhibitVerify.ts.

Signs a sample exhibit payload with an ephemeral P-256 key using the backend's own canonical() function,
so the Vitest suite proves the browser verifier accepts exactly what the edge server signs.
Run inside the api image:  python make_signed_fixture.py /tmp/out.json
"""

import base64
import json
import sys

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

from archive.exhibit import canonical

key = ec.generate_private_key(ec.SECP256R1())
payload = {
    "manifest_version": 7,
    "issued_at": "2026-09-26T10:00:00+00:00",
    "lease_expires_at": "2026-09-29T10:00:00+00:00",
    "lease_hours": 72,
    "budget_bytes": 1000,
    "total_bytes": 10,
    "device_id": "kiosk-test",
    "items": [{"item_id": 3, "version": 2, "bytes": 10,
               "urls": ["/api/visitor/items/3", "/api/visitor/files/9"], "sha256": ["ab"]}],
    "skipped_over_budget": [],
    "withdrawn_item_ids": [5],
    "shared_urls": ["/api/visitor/home"],
    "note": "\u0938\u093e\u0930\u094d\u0935\u091c\u0928\u093f\u0915 \u2014 \u201cquotes\u201d",
}
der = key.sign(canonical(payload), ec.ECDSA(hashes.SHA256()))
r, s = decode_dss_signature(der)
spki = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
out = {
    "spki_b64": base64.b64encode(spki).decode(),
    "manifest": {"payload": payload, "alg": "ECDSA-P256-SHA256",
                 "signature": base64.b64encode(r.to_bytes(32, "big") + s.to_bytes(32, "big")).decode()},
}
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)
