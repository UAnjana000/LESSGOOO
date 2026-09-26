"""Small builders for DB tests. All content is synthetic."""

from __future__ import annotations

import datetime as dt

from archive import storage
from archive.ingest import processing, publish, review
from archive.models import ArchivalItem, FileVersion, Page, PageStatus, RightsRecord

from .conftest import png_page


def make_rights(db, key="r-open", display="allowed", training="allowed", external="allowed",
                discovery=False) -> RightsRecord:
    r = RightsRecord(source_key=key, title=f"rights {key}", source_institution="Synthetic test source",
                     rights_holder="Test", basis_for_use="test", display_permission=display,
                     training_permission=training, external_processing=external, evidence="test",
                     attribution="Synthetic", date_checked=dt.date(2026, 9, 26), checked_by="tester",
                     discovery_only=discovery, is_fixture=True, training_basis="synthetic")
    db.add(r)
    db.flush()
    return r


def make_item(db, rights: RightsRecord, texts: list[str], *, title="Synthetic item", access="public",
              doc_class="printed", collection="writings", language="en", item_key=None, approve=True,
              item_type="printed_scan") -> ArchivalItem:
    item = ArchivalItem(title=title, item_type=item_type, collection=collection,
                        source_institution="Synthetic test source", original_languages=[language], scripts=["Latn"],
                        rights_record_id=rights.id, access_level=access, created_by="tester", is_fixture=True,
                        capture_details={"item_key": item_key or title.lower().replace(" ", "-"),
                                         "work_key": item_key or title})
    db.add(item)
    db.flush()
    for seq, text in enumerate(texts, 1):
        data = png_page(f"{title} page {seq}")
        stored = storage.put_bytes(data, "preservation_master", ".png")
        fv = FileVersion(item_id=item.id, role="preservation_master", kind="original", format="image/png",
                         byte_size=stored.byte_size, sha256=stored.sha256, storage_uri=stored.uri)
        db.add(fv)
        db.flush()
        page = Page(item_id=item.id, sequence=seq, image_file_id=fv.id, doc_class=doc_class, language=language,
                    status=PageStatus.needs_full_review.value, ocr_route="local")
        db.add(page)
        db.flush()
        processing._store_delivery(db, page, data, fv.id)
        if approve:
            review.review_page(db, page, "approve", "test-reviewer", "archivist", text=text)
    db.flush()
    db.refresh(item)
    return item


def publish_item(db, item: ArchivalItem) -> dict:
    return publish.publish_item(db, item, "test-archivist")
