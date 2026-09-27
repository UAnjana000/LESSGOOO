import json
import ssl
import urllib.error
import urllib.request

ctx = ssl._create_unverified_context()
base = "https://localhost:9443"


def req(method: str, path: str, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None if data is None else json.dumps(data).encode()
    r = urllib.request.Request(base + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, context=ctx) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


token = req("POST", "/api/staff/login", {"email": "admin@archive.local", "password": "e2e-admin-password"})[1]["token"]
print("item6", req("GET", "/api/staff/items/6", token=token)[0])
code, body = req("GET", "/api/staff/items/6", token=token)
print(code)
print(body if isinstance(body, str) else json.dumps({k: body.get(k) for k in ("id", "title", "state", "ready", "problems")}, indent=2))
