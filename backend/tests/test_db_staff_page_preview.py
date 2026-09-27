"""Staff page review shows a scan the browser can render, and only to signed-in staff."""

from __future__ import annotations

import pytest

from archive import storage
from archive.ingest import processing
from archive.models import FileVersion, Page, PageStatus, StaffUser
from archive.security import hash_password

from .conftest import png_page
from .factories import make_item, make_rights

pytestmark = pytest.mark.db


def _login(client, db) -> dict[str, str]:
    db.add(StaffUser(email="archivist@test", display_name="archivist@test", password_hash=hash_password("pw-123456"),
                     roles=["archivist"], languages=[]))
    db.commit()
    token = client.post("/api/staff/login", json={"email": "archivist@test", "password": "pw-123456"}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _pdf_page(db, *, with_delivery: bool) -> Page:
    item = make_item(db, make_rights(db), [], title="PDF master item", access="restricted", approve=False)
    stored = storage.put_bytes(b"%PDF-1.4\n% synthetic multi-page master\n", "preservation_master", ".pdf")
    master = FileVersion(item_id=item.id, role="preservation_master", kind="original", format="application/pdf",
                         byte_size=stored.byte_size, sha256=stored.sha256, storage_uri=stored.uri)
    db.add(master)
    db.flush()
    page = Page(item_id=item.id, sequence=23, image_file_id=master.id, doc_class="printed", language="hi",
                status=PageStatus.needs_full_review.value, ocr_route="sarvam",
                preprocessing_params={"pdf_page_index": 22})
    db.add(page)
    db.flush()
    if with_delivery:
        processing._store_delivery(db, page, png_page("page 23"), master.id)
    db.commit()
    return page


class TestStaffPagePreview:
    def test_pdf_master_previews_the_delivery_jpeg(self, db, client):
        page = _pdf_page(db, with_delivery=True)
        h = _login(client, db)
        body = client.get(f"/api/staff/pages/{page.id}", headers=h).json()
        assert body["master_file_id"] == page.image_file_id
        assert body["preview_file_id"] == page.delivery_file_id

        r = client.get(f"/api/staff/files/{body['preview_file_id']}", headers=h)
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/jpeg"

    def test_preview_file_needs_a_staff_token(self, db, client):
        page = _pdf_page(db, with_delivery=True)
        assert client.get(f"/api/staff/files/{page.delivery_file_id}").status_code == 401
        assert client.get(f"/api/visitor/files/{page.delivery_file_id}").status_code in (403, 404)

    def test_pdf_master_without_delivery_has_no_preview(self, db, client):
        page = _pdf_page(db, with_delivery=False)
        body = client.get(f"/api/staff/pages/{page.id}", headers=_login(client, db)).json()
        assert body["preview_file_id"] is None

    def test_image_master_without_delivery_previews_the_master(self, db, client):
        item = make_item(db, make_rights(db), ["Image master page."], approve=False)
        page = item.pages[0]
        page.delivery_file_id = None
        db.commit()
        body = client.get(f"/api/staff/pages/{page.id}", headers=_login(client, db)).json()
        assert body["preview_file_id"] == page.image_file_id
