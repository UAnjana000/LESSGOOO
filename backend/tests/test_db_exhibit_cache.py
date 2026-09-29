"""Kiosk cache policy: browser caching follows the item's access level, and only kiosk devices are recorded
when they fetch the exhibit manifest. All content is synthetic."""

from __future__ import annotations

import pytest

from archive.models import KioskSync

from .factories import make_item, make_rights, publish_item

pytestmark = pytest.mark.db


def _file_id(db, access: str, title: str) -> int:
    item = make_item(db, make_rights(db, key=f"r-{title}"), [f"{title} page text"], title=title, access=access)
    publish_item(db, item)
    db.commit()
    return item.pages[0].delivery_file_id


class TestBrowserCaching:
    def test_public_items_are_cacheable(self, db, client):
        fid = _file_id(db, "public", "open-letter")
        assert client.get(f"/api/visitor/files/{fid}").headers["cache-control"] == "public, max-age=3600"
        assert client.get(f"/iiif/{fid}/info.json").headers["cache-control"] == "public, max-age=3600"
        tile = client.get(f"/iiif/{fid}/full/200,/0/default.jpg")
        assert tile.status_code == 200 and tile.headers["cache-control"] == "public, max-age=86400"

    def test_online_only_items_are_never_stored(self, db, client):
        fid = _file_id(db, "public_online_only", "online-gazette")
        for path in (f"/api/visitor/files/{fid}", f"/iiif/{fid}/info.json", f"/iiif/{fid}/full/200,/0/default.jpg"):
            r = client.get(path)
            assert r.status_code == 200 and r.headers["cache-control"] == "private, no-store", path


class TestExhibitManifest:
    def test_signage_is_in_the_shared_offline_set(self, client):
        assert "/api/visitor/signage" in client.get("/api/visitor/exhibit/manifest").json()["payload"]["shared_urls"]

    def test_only_kiosk_device_ids_are_recorded(self, db, client):
        for device_id in ("kiosk-1a2b3c4d", "kiosk-lxq9z0ab"):
            r = client.get("/api/visitor/exhibit/manifest", params={"device_id": device_id})
            assert r.status_code == 200 and r.json()["signature"]
        for device_id in ("unregistered", "phone", "kiosk-", "kiosk-1A2B3C4D", "kiosk-1a2b3c4d5", "x" * 80):
            r = client.get("/api/visitor/exhibit/manifest", params={"device_id": device_id})
            assert r.status_code == 200 and r.json()["signature"]
        client.get("/api/visitor/exhibit/manifest")
        db.expire_all()
        assert sorted(k.device_id for k in db.query(KioskSync).all()) == ["kiosk-1a2b3c4d", "kiosk-lxq9z0ab"]
