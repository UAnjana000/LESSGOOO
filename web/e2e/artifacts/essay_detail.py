import json
import ssl
import urllib.request
from pathlib import Path

ctx = ssl._create_unverified_context()
base = "https://localhost:9443"


def req(method: str, path: str, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None if data is None else json.dumps(data).encode()
    r = urllib.request.Request(base + path, data=body, headers=headers, method=method)
    with urllib.request.urlopen(r, context=ctx) as resp:
        return json.load(resp)


token = req("POST", "/api/staff/login", {"email": "admin@archive.local", "password": "e2e-admin-password"})["token"]
detail = req("GET", "/api/staff/items/1", token=token)
Path(__file__).with_name("essay-detail.json").write_text(json.dumps(detail, indent=2, default=str), encoding="utf-8")
print("ready", detail.get("ready"), "problems", detail.get("problems"), "files", len(detail.get("files") or []), "state", detail.get("state"))
