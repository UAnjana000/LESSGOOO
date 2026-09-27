"""Operator CLI: python -m archive.cli <command> [...]"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import random
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

from archive import audit, exhibit, ops, storage
from archive.config import get_settings
from archive.db import session_scope
from archive.logging_setup import configure_logging
from archive.models import (
    ArchivalItem,
    CollectionSetting,
    Derivative,
    FileVersion,
    KnowledgeEdge,
    KnowledgeNode,
    MediaSegment,
    Page,
    PageStatus,
    Passage,
    PhotoMetadata,
    ReviewBatch,
    StaffUser,
    Story,
    TimelineEvent,
    Translation,
    utcnow,
)

log = logging.getLogger("archive.cli")
SEED = "fixture-seed"


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))


# ------------------------------------------------------------------ bootstrap

def cmd_bootstrap(_: argparse.Namespace) -> None:
    from archive.security import hash_password

    s = get_settings()
    storage.ensure_roots()
    exhibit.signing_key()
    created = []
    with session_scope() as db:
        users = []
        if s.bootstrap_admin_password:
            users.append((s.bootstrap_admin_email, "Administrator", ["admin", "archivist", "curator", "reviewer"], []))
        if s.demo_staff_password:
            users += [
                ("archivist@demo.local", "Demo Archivist", ["archivist", "reviewer"], []),
                ("curator@demo.local", "Demo Curator", ["curator"], []),
                ("reviewer-hi@demo.local", "Demo Hindi Reviewer", ["translation_reviewer"], ["hi"]),
                ("reviewer-mr@demo.local", "Demo Marathi Reviewer", ["translation_reviewer"], ["mr"]),
            ]
        for email, name, roles, langs in users:
            pw = s.bootstrap_admin_password if email == s.bootstrap_admin_email else s.demo_staff_password
            u = db.execute(select(StaffUser).where(StaffUser.email == email)).scalar_one_or_none()
            if u is None:
                db.add(StaffUser(email=email, display_name=name, password_hash=hash_password(pw), roles=roles,
                                 languages=langs))
                created.append(email)
        for c in ("writings", "speeches", "debates", "manuscripts", "photographs", "audio_video"):
            if db.get(CollectionSetting, c) is None:
                db.add(CollectionSetting(collection=c, machine_translation_enabled=True))
        if created:
            audit.record(db, "bootstrap", "staff.create", "staff_user", ",".join(created))
    _print({"created_staff": created, "admin_configured": bool(s.bootstrap_admin_password),
            "demo_staff": bool(s.demo_staff_password)})


# ------------------------------------------------------------------ fixtures

HI_ESSAY_P1 = (
    "सार्वजनिक वाचनालयों के बारे में\n\nवाचनालय एक वादा है जो कोई शहर अपने दरवाज़े से आने वाले हर व्यक्ति से करता है। "
    "वादा सरल है: अलमारी में रखा ज्ञान हर उस व्यक्ति का है जो उस तक हाथ बढ़ा सके। समरपुर शहर में पहला वाचनालय 1921 "
    "में एक अनाज की दुकान के ऊपर किराये के दो कमरों में खुला। उसमें चार सौ पुस्तकें, तीन समाचारपत्र और एक ही दीपक था। "
    "उसे चलाने वाली समिति ने अपनी पहली रिपोर्ट में लिखा कि दरवाज़े मिलों की पाली शुरू होने से पहले खुलने चाहिए और "
    "पाली खत्म होने के बाद बंद होने चाहिए, ताकि मज़दूर काम पर जाते और घर लौटते समय पढ़ सकें।")
MR_ESSAY_P1 = (
    "सार्वजनिक वाचनालयांविषयी\n\nवाचनालय म्हणजे एखाद्या गावाने त्याच्या दारातून येणाऱ्या प्रत्येक व्यक्तीला दिलेले वचन. "
    "वचन साधे आहे: कपाटात ठेवलेले ज्ञान ते हाती घेऊ शकणाऱ्या प्रत्येकाचे आहे. समरपूर गावात पहिले वाचनालय 1921 मध्ये "
    "धान्याच्या दुकानावरील भाड्याच्या दोन खोल्यांत सुरू झाले. त्यात चारशे पुस्तके, तीन वृत्तपत्रे आणि एकच दिवा होता. "
    "ते चालवणाऱ्या समितीने आपल्या पहिल्या अहवालात लिहिले की गिरण्यांच्या पाळ्या सुरू होण्यापूर्वी दारे उघडली पाहिजेत आणि "
    "पाळ्या संपल्यानंतर बंद झाली पाहिजेत, जेणेकरून कामगार कामावर जाताना आणि घरी परतताना वाचू शकतील.")

SUMMARIES = {
    "fx-essay-reading-rooms": "A synthetic essay describing how a fictional town's first reading room opened in "
                              "1921, kept hours around mill shifts, and ran evening reading classes.",
    "fx-proceedings-1": "Synthetic proceedings of a fictional civic assembly debating a municipal library board, "
                        "whether to charge a reading fee, and the vote that carried the motion 21 to 6.",
    "fx-lecture-education": "A synthetic lecture arguing for municipally funded night schools so that workers "
                            "and their families can learn to read.",
}

ITEM_TEXT_KEYS = {
    "fx-essay-reading-rooms": "essay", "fx-lecture-education": "lecture_clean", "fx-lecture-tank": "lecture_degraded",
    "fx-proceedings-1": "proceedings", "fx-pamphlet-hi": "hindi", "fx-petition-mr": "marathi",
    "fx-manuscript-note": "manuscript", "fx-restricted-memo": "restricted", "fx-online-only-report": "online_only",
}


def _items_by_key(db) -> dict[str, ArchivalItem]:
    out = {}
    for it in db.execute(select(ArchivalItem).where(ArchivalItem.is_fixture.is_(True))).scalars():
        key = (it.capture_details or {}).get("item_key")
        if key:
            out[key] = it
    return out


def _seed_reviews(db, gt: dict[str, Any]) -> dict[str, Any]:
    """Seeded fixture approvals. They exercise the workflow; they are NOT human reviews."""
    from archive.ingest import review

    texts = gt["texts"]
    done: dict[str, Any] = {}
    for key, item in _items_by_key(db).items():
        actions = []
        truth = texts.get(ITEM_TEXT_KEYS.get(key, ""), [])
        for batch in db.execute(select(ReviewBatch).where(ReviewBatch.item_id == item.id,
                                                          ReviewBatch.status == "open")).scalars():
            checks = {}
            for pid in batch.sample_page_ids:
                p = db.get(Page, pid)
                if p.ocr_route != "text_layer" and p.sequence - 1 < len(truth):
                    checks[pid] = {"text": truth[p.sequence - 1]}
                else:
                    checks[pid] = {}
            review.decide_batch(db, batch, True, SEED, reason="seeded fixture sample check", sample_checks=checks,
                                seeded=True)
            actions.append(f"batch {batch.id} passed (seeded)")
        for p in item.pages:
            if p.status in (PageStatus.needs_full_review.value, PageStatus.sarvam_pending.value,
                            PageStatus.manual_transcription.value) and p.doc_class != "photograph":
                text = truth[p.sequence - 1] if p.sequence - 1 < len(truth) else None
                if text:
                    review.review_page(db, p, "correct", SEED, "archivist", text=text, seeded=True,
                                       reason="seeded fixture: ground-truth transcription")
                    actions.append(f"page {p.sequence} corrected from {p.ocr_route} (seeded)")
        photo = db.get(PhotoMetadata, item.id)
        if photo and photo.review_status != "approved":
            review.review_photo(db, photo, "approve", SEED, seeded=True)
            actions.append("caption approved (seeded)")
        for seg in db.execute(select(MediaSegment).where(MediaSegment.item_id == item.id,
                                                         MediaSegment.review_status == "draft")).scalars():
            review.review_segment(db, seg, "approve", SEED, reason="seeded fixture transcript", seeded=True)
            actions.append(f"segment {seg.start_ms}ms approved (seeded)")
        review._update_item_state(db, item)
        done[key] = {"state": item.publication_state, "actions": actions}
    return done


def _seed_quote_checks(db) -> list[str]:
    from archive.ingest import review

    out = []
    items = _items_by_key(db)
    for key in ("fx-essay-reading-rooms", "fx-lecture-education"):
        item = items.get(key)
        if not item:
            continue
        for p in item.pages:
            if p.status == PageStatus.approved.value and not p.quote_verified:
                review.verify_page_quotes(db, p, SEED, confirm_compared_with_scan=True, seeded=True)
                out.append(f"{key} p{p.sequence}")
    return out


def _seed_media_delivery(db) -> dict[str, str]:
    """Fixture recordings need a delivery copy whose SHA-256 publish.verify can confirm on disk.

    Ingest normally makes an FFmpeg copy; if that copy is absent or fails its checksum, the synthetic
    master bytes are stored as the delivery copy instead."""
    out = {}
    for key, item in _items_by_key(db).items():
        if item.item_type not in ("audio", "video"):
            continue
        live = db.execute(select(FileVersion).where(
            FileVersion.item_id == item.id, FileVersion.role == "delivery", FileVersion.kind == "media",
            FileVersion.deleted_at.is_(None))).scalars().first()
        if live and storage.verify(live.storage_uri, live.sha256):
            out[key] = f"present ({live.generator})"
            continue
        if live:
            live.deleted_at = utcnow()
        master = db.execute(select(FileVersion).where(
            FileVersion.item_id == item.id, FileVersion.role == "preservation_master")).scalars().first()
        if master is None:
            out[key] = "no preservation master"
            continue
        stored = storage.put_bytes(storage.read_bytes(master.storage_uri), "delivery",
                                   Path(master.storage_uri).suffix)
        fv = FileVersion(item_id=item.id, role="delivery", kind="media", format=master.format,
                         byte_size=stored.byte_size, sha256=stored.sha256, storage_uri=stored.uri,
                         derived_from_id=master.id, generator="fixture-seed: copy of synthetic master")
        db.add(fv)
        db.flush()
        audit.record(db, SEED, "file.store_delivery", "file_version", fv.id, checksum_after=stored.sha256,
                     detail={"item_id": item.id, "replaced": live.id if live else None,
                             "seeded_fixture": True})
        out[key] = "stored"
    return out


def _seed_publish(graph, ready: list[tuple[str, int]]) -> dict[str, Any]:
    from archive.ingest import graph as ingest_graph
    from archive.ingest import publish

    pub = {}
    for key, item_id in ready:
        if ingest_graph.has_checkpoint(graph, item_id):
            state = ingest_graph.resume_publish(graph, item_id, SEED)
            pub[key] = state.get("result") or {"blocked": state.get("review_problems") or state.get("error")}
        else:
            with session_scope() as db:
                try:
                    r = publish.publish_item(db, db.get(ArchivalItem, item_id), SEED)
                    pub[key] = {k: v for k, v in r.items() if k != "verification"}
                except publish.PublicationError as exc:
                    pub[key] = {"blocked": str(exc)}
    return pub


def _seed_translations(db) -> list[str]:
    from archive.ingest import review

    out = []
    item = _items_by_key(db).get("fx-essay-reading-rooms")
    if not item or not item.published_version_id:
        return out
    page1 = next(p for p in item.pages if p.sequence == 1)
    src = db.execute(select(Passage).where(Passage.item_version_id == item.published_version_id,
                                           Passage.page_id == page1.id, Passage.kind == "source_text")
                     .order_by(Passage.char_start)).scalars().first()
    if src is None:
        return out
    for lang, text in (("hi", HI_ESSAY_P1), ("mr", MR_ESSAY_P1)):
        exists = db.execute(select(Translation).where(Translation.source_passage_id == src.id,
                                                      Translation.target_language == lang)).scalar()
        if exists:
            continue
        tr = Translation(source_passage_id=src.id, target_language=lang, text=text, method="machine",
                         provider="build-agent (AI-written fixture translation)", model=None)
        db.add(tr)
        db.flush()
        review.review_translation(db, tr, "approve", SEED, ["hi", "mr"], seeded=True)
        out.append(lang)
    return out


def _seed_summaries(db) -> list[str]:
    from archive.ingest import review

    out = []
    items = _items_by_key(db)
    for key, text in SUMMARIES.items():
        item = items.get(key)
        if not item or db.execute(select(Derivative).where(Derivative.item_id == item.id,
                                                           Derivative.kind == "summary")).scalar():
            continue
        d = Derivative(kind="summary", item_id=item.id, language="en", content=text,
                       generator="build-agent (hand-written fixture summary)", label_shown="Summary draft")
        db.add(d)
        db.flush()
        review.review_derivative(db, d, "approve", SEED, seeded=True)
        out.append(key)
    return out


def _seed_narration(db) -> list[str]:
    from archive.services.narration import NarrationError, narrate_passage

    out = []
    item = _items_by_key(db).get("fx-essay-reading-rooms")
    if not item or not item.published_version_id:
        return out
    if db.execute(select(Derivative).where(Derivative.item_id == item.id, Derivative.kind == "narration")).scalar():
        return ["already present"]
    passages = db.execute(select(Passage).where(Passage.item_version_id == item.published_version_id)
                          .order_by(Passage.id)).scalars().all()
    wanted = {("source_text", "en"), ("reviewed_translation", "hi"), ("reviewed_translation", "mr")}
    for p in passages:
        if (p.kind, p.language) in wanted:
            wanted.discard((p.kind, p.language))
            try:
                d = narrate_passage(db, p, p.language, SEED, prefer_local=not get_settings().sarvam_available)
                out.append(f"{p.language}:{d.generator}")
            except (NarrationError, OSError) as exc:
                out.append(f"{p.language}: failed ({exc})")
    return out


def _seed_curation(db) -> dict[str, int]:
    items = _items_by_key(db)

    def iid(key: str) -> list[int]:
        return [items[key].id] if key in items else []

    if db.execute(select(TimelineEvent)).first():
        return {"timeline": 0, "stories": 0, "nodes": 0}
    events = [
        ("1921", "1921-01-01", "approximate", "First reading room opens", "पहला वाचनालय खुला", "पहिले वाचनालय सुरू",
         "Two rented rooms above a grain shop, four hundred books.", "fx-essay-reading-rooms"),
        ("1923", "1923-01-01", "approximate", "Evening reading classes begin", "सायंकालीन पठन कक्षाएँ शुरू",
         "संध्याकाळचे वाचन वर्ग सुरू", "Members learn to read the books they borrow.", "fx-essay-reading-rooms"),
        ("around 1925", "1925-01-01", "approximate", "Register passes eleven hundred names",
         "रजिस्टर में ग्यारह सौ से अधिक नाम", "नोंदवहीत अकराशेहून अधिक नावे", "The borrower register grows.",
         "fx-photo-reading-room"),
        ("1926", "1926-01-01", "approximate", "Committee's annual report", "समिति की वार्षिक रिपोर्ट",
         "समितीचा वार्षिक अहवाल", "Reading rooms judged by readers, not shelves.", "fx-essay-reading-rooms"),
        ("10 Feb 1927", "1927-02-10", "exact", "Civic Assembly debates a library board",
         "नागरिक सभा में पुस्तकालय बोर्ड पर बहस", "नागरी सभेत ग्रंथालय मंडळावर चर्चा",
         "Motion carried 21 to 6; no fee for reading.", "fx-proceedings-1"),
        ("3 Mar 1927", "1927-03-03", "exact", "Note on longer harvest-month hours", "फसल के महीनों में देर तक खुलने पर टिप्पणी",
         "सुगीच्या महिन्यांतील वेळेविषयी टिपण", "Handwritten note asking for rooms open until ten.", "fx-manuscript-note"),
        ("12 Apr 1927", "1927-04-12", "exact", "Library board's first meeting", "पुस्तकालय बोर्ड की पहली बैठक",
         "ग्रंथालय मंडळाची पहिली बैठक", "Three branch reading rooms resolved.", "fx-online-only-report"),
        ("1928", "1928-03-01", "approximate", "Lecture on the common tank", "सार्वजनिक तालाब पर व्याख्यान",
         "सार्वजनिक तलावावर व्याख्यान", "Public resources must be open to the whole public.", "fx-lecture-tank"),
        ("1928", "1928-05-01", "approximate", "Water petition in Marathi", "मराठी में पानी पर निवेदन",
         "पाणवठ्याविषयी मराठी निवेदन", "Rules of the tank to be posted by the steps.", "fx-petition-mr"),
        ("1929", "1929-06-01", "approximate", "Lecture on education and work", "शिक्षा और काम पर व्याख्यान",
         "शिक्षण आणि काम यावर व्याख्यान", "Night schools in every ward.", "fx-lecture-education"),
        ("1930", "1930-01-01", "approximate", "Hindi reading-room pamphlet", "वाचनालय पर हिंदी पर्चा",
         "वाचनालयावरील हिंदी पत्रक", "A pamphlet calls for open reading rooms.", "fx-pamphlet-hi"),
    ]
    for date_text, sort, cert, en, hi, mr, desc, key in events:
        db.add(TimelineEvent(date_text=date_text + " (fictional)", sort_date=dt.date.fromisoformat(sort),
                             date_certainty=cert, titles={"en": en, "hi": hi, "mr": mr}, descriptions={"en": desc},
                             item_ids=iid(key), curator=SEED, status="approved"))
    db.add(Story(slug="samarpur-reading-rooms",
                 titles={"en": "Reading rooms of Samarpur (synthetic story)", "hi": "समरपुर के वाचनालय (कृत्रिम कथा)",
                         "mr": "समरपूरची वाचनालये (कृत्रिम कथा)"},
                 blocks=[{"item_id": i, "captions": {"en": c}} for i, c in [
                     (iid("fx-photo-reading-room")[0], "Evening readers, as imagined in a synthetic illustration."),
                     (iid("fx-essay-reading-rooms")[0], "The essay that describes the first reading room."),
                     (iid("fx-proceedings-1")[0], "The Assembly decides that reading will stay free."),
                     (iid("fx-talk-audio")[0], "A synthetic talk summarising the story."),
                 ] if i],
                 curator=SEED, status="approved"))
    node_specs = [
        ("person", "A. N. Example (fictional)", ["fx-essay-reading-rooms", "fx-lecture-education", "fx-lecture-tank"]),
        ("person", "Member Rao (fictional)", ["fx-proceedings-1"]),
        ("person", "Member Desai (fictional)", ["fx-proceedings-1"]),
        ("person", "The Chairman (fictional)", ["fx-proceedings-1"]),
        ("place", "Samarpur (fictional town)", ["fx-essay-reading-rooms", "fx-photo-reading-room"]),
        ("place", "Mill districts", ["fx-online-only-report"]),
        ("place", "Common tank", ["fx-lecture-tank", "fx-petition-mr"]),
        ("organisation", "Samarpur Civic Assembly", ["fx-proceedings-1"]),
        ("organisation", "Municipal library board", ["fx-proceedings-1", "fx-online-only-report", "fx-manuscript-note"]),
        ("organisation", "Reading room committee", ["fx-essay-reading-rooms"]),
        ("organisation", "Village council", ["fx-lecture-tank", "fx-petition-mr"]),
        ("event", "Opening of the first reading room (1921)", ["fx-essay-reading-rooms"]),
        ("event", "Assembly Sitting 1 (1927)", ["fx-proceedings-1"]),
        ("event", "Board's first meeting (1927)", ["fx-online-only-report"]),
        ("concept", "Reading rooms", ["fx-essay-reading-rooms", "fx-pamphlet-hi", "fx-talk-audio"]),
        ("concept", "Night schools", ["fx-lecture-education", "fx-pamphlet-hi"]),
        ("concept", "Free access (no reading fee)", ["fx-proceedings-1", "fx-talk-audio"]),
        ("concept", "Public water", ["fx-lecture-tank", "fx-petition-mr"]),
        ("concept", "Workers' education", ["fx-lecture-education", "fx-essay-reading-rooms"]),
        ("document", "On Public Reading Rooms", ["fx-essay-reading-rooms"]),
        ("document", "Lecture on Education and Work", ["fx-lecture-education"]),
        ("document", "Lecture on Water and the Common Tank", ["fx-lecture-tank"]),
        ("document", "Proceedings, Sitting 1", ["fx-proceedings-1"]),
        ("document", "Reading-room pamphlet (Hindi)", ["fx-pamphlet-hi"]),
    ]
    nodes = {}
    for ntype, label, keys in node_specs:
        n = KnowledgeNode(node_type=ntype, labels={"en": label}, item_ids=sum((iid(k) for k in keys), []),
                          status="approved", approved_by=SEED)
        db.add(n)
        db.flush()
        nodes[label] = n
    edges = [
        ("A. N. Example (fictional)", "On Public Reading Rooms", "authored", "fx-essay-reading-rooms"),
        ("A. N. Example (fictional)", "Lecture on Education and Work", "delivered", "fx-lecture-education"),
        ("A. N. Example (fictional)", "Lecture on Water and the Common Tank", "delivered", "fx-lecture-tank"),
        ("Member Rao (fictional)", "Assembly Sitting 1 (1927)", "spoke_at", "fx-proceedings-1"),
        ("Member Desai (fictional)", "Assembly Sitting 1 (1927)", "spoke_at", "fx-proceedings-1"),
        ("The Chairman (fictional)", "Assembly Sitting 1 (1927)", "presided", "fx-proceedings-1"),
        ("Assembly Sitting 1 (1927)", "Samarpur Civic Assembly", "held_by", "fx-proceedings-1"),
        ("Assembly Sitting 1 (1927)", "Municipal library board", "established", "fx-proceedings-1"),
        ("Assembly Sitting 1 (1927)", "Free access (no reading fee)", "about", "fx-proceedings-1"),
        ("Proceedings, Sitting 1", "Assembly Sitting 1 (1927)", "records", "fx-proceedings-1"),
        ("Opening of the first reading room (1921)", "Samarpur (fictional town)", "located_in", "fx-essay-reading-rooms"),
        ("Reading room committee", "Reading rooms", "about", "fx-essay-reading-rooms"),
        ("On Public Reading Rooms", "Reading rooms", "about", "fx-essay-reading-rooms"),
        ("On Public Reading Rooms", "Workers' education", "about", "fx-essay-reading-rooms"),
        ("Lecture on Education and Work", "Night schools", "about", "fx-lecture-education"),
        ("Lecture on Water and the Common Tank", "Public water", "about", "fx-lecture-tank"),
        ("Lecture on Water and the Common Tank", "Village council", "mentions", "fx-lecture-tank"),
        ("Common tank", "Public water", "about", "fx-petition-mr"),
        ("Board's first meeting (1927)", "Municipal library board", "held_by", "fx-online-only-report"),
        ("Board's first meeting (1927)", "Mill districts", "about", "fx-online-only-report"),
        ("Reading-room pamphlet (Hindi)", "Reading rooms", "about", "fx-pamphlet-hi"),
        ("Reading-room pamphlet (Hindi)", "Night schools", "mentions", "fx-pamphlet-hi"),
    ]
    for a, b, rel, key in edges:
        db.add(KnowledgeEdge(from_node=nodes[a].id, to_node=nodes[b].id, relation=rel, evidence_item_ids=iid(key),
                             proposed_by=SEED, approved_by=SEED, status="approved"))
    audit.record(db, SEED, "curation.seed", "timeline_event", "*",
                 detail={"events": len(events), "nodes": len(nodes), "edges": len(edges), "seeded_fixture": True})
    return {"timeline": len(events), "stories": 1, "nodes": len(nodes), "edges": len(edges)}


FIXTURE_TAGS = {  # key: (subjects, people, places) — all fictional
    "fx-essay-reading-rooms": (["Reading rooms", "Workers' education"], ["A. N. Example (fictional)"],
                               ["Samarpur (fictional)"]),
    "fx-lecture-education": (["Education", "Night schools"], ["A. N. Example (fictional)"], []),
    "fx-lecture-tank": (["Public water"], ["A. N. Example (fictional)"], ["Common tank (fictional)"]),
    "fx-proceedings-1": (["Libraries", "Free access"], ["Member Rao (fictional)", "Member Desai (fictional)"],
                         ["Samarpur (fictional)"]),
    "fx-photo-reading-room": (["Reading rooms"], [], ["Samarpur (fictional)"]),
    "fx-talk-audio": (["Reading rooms"], [], []),
    "fx-talk-video": (["Reading rooms"], [], []),
    "fx-manuscript-note": (["Libraries"], [], []),
}
FIXTURE_ARTICLES = [("41", {"en": "Right to work, to education and to public assistance in certain cases"}, "IV")]
FIXTURE_LINKS = [("fx-proceedings-1", 1, "41",
                  "Synthetic demonstration link on a fictional debate; not a historical claim.")]


def _seed_tags_and_links(db) -> dict[str, Any]:
    """Seeded fixture tags and one curated-link demonstration. Not human cataloguing."""
    from archive import metadata
    from archive.models import ConstitutionArticle, ConstitutionLink

    items = _items_by_key(db)
    tagged = []
    for key, (subjects, people, places) in FIXTURE_TAGS.items():
        item = items.get(key)
        if item is None or item.subjects or item.people or item.places:
            continue
        before = metadata.snapshot(item)
        item.subjects, item.people, item.places = subjects, people, places
        if metadata.record_revision(db, item, before, SEED, "seeded fixture tags", seeded=True):
            tagged.append(key)
    for number, titles, part in FIXTURE_ARTICLES:
        if db.get(ConstitutionArticle, number) is None:
            db.add(ConstitutionArticle(number=number, titles=titles, part=part, created_by=SEED))
    db.flush()
    linked = []
    for key, page_seq, number, note in FIXTURE_LINKS:
        item = items.get(key)
        if item is None or not item.published_version_id:
            continue
        page = next((p for p in item.pages if p.sequence == page_seq), None)
        passage = db.execute(select(Passage).where(
            Passage.item_version_id == item.published_version_id, Passage.page_id == page.id,
            Passage.translation_of_id.is_(None)).order_by(Passage.char_start)).scalars().first() if page else None
        if passage is None or db.execute(select(ConstitutionLink.id).where(
                ConstitutionLink.item_id == item.id, ConstitutionLink.article_number == number,
                ConstitutionLink.removed_at.is_(None))).first():
            continue
        lk = ConstitutionLink(article_number=number, item_id=item.id, page_id=page.id, passage_id=passage.id,
                              text_hash=passage.text_hash, note=note, created_by=SEED)
        db.add(lk)
        db.flush()
        audit.record(db, SEED, "constitution.link.add", "constitution_link", lk.id,
                     detail={"article": number, "item_id": item.id, "passage_id": passage.id,
                             "seeded_fixture": True}, checksum_after=passage.text_hash)
        linked.append(f"{key} p{page_seq} -> Article {number}")
    return {"tagged": tagged, "links": linked}


def cmd_seed_fixtures(args: argparse.Namespace) -> None:
    from archive.ingest import graph as ingest_graph
    from archive.ingest import intake, publish
    from archive.worker import postgres_checkpointer

    root = Path(args.fixtures)
    gt = json.loads((root / "ground_truth.json").read_text(encoding="utf-8"))
    manifest_path = root / "manifests" / "fixture_manifest.json"
    report: dict[str, Any] = {}
    with session_scope() as db:
        imp = intake.import_manifest(db, intake.load_manifest(manifest_path), manifest_path.parent, SEED)
        report["import"] = {"items": [(i["item_key"], i.get("status", "imported")) for i in imp["items"]],
                            "rejected": imp["rejected"]}
    with postgres_checkpointer() as cp:
        graph = ingest_graph.build_ingest_graph(checkpointer=cp, rng=random.Random(7))
        with session_scope() as db:
            todo = [(k, i.id) for k, i in _items_by_key(db).items() if i.publication_state in ("draft", "in_review")]
        routes = {}
        for key, item_id in todo:
            if ingest_graph.has_checkpoint(graph, item_id):
                continue
            state = ingest_graph.run_ingest(graph, item_id, SEED)
            routes[key] = [(o["route"], o["status"], o["gate_passed"]) for o in state.get("page_outcomes", [])]
        report["routing"] = routes
        with session_scope() as db:
            report["reviews"] = _seed_reviews(db, gt)
        with session_scope() as db:
            report["quote_checks_seeded"] = _seed_quote_checks(db)
        with session_scope() as db:
            report["media_delivery"] = _seed_media_delivery(db)
        with session_scope() as db:
            ready = [(k, i.id) for k, i in _items_by_key(db).items() if i.publication_state == "approved"]
        report["publication"] = _seed_publish(graph, ready)
    with session_scope() as db:
        report["translations_seeded"] = _seed_translations(db)
    if report["translations_seeded"]:
        with session_scope() as db:
            item = _items_by_key(db)["fx-essay-reading-rooms"]
            r = publish.publish_item(db, item, SEED)
            report["essay_republished_with_translations"] = {k: v for k, v in r.items() if k != "verification"}
    with session_scope() as db:
        report["summaries_seeded"] = _seed_summaries(db)
    with session_scope() as db:
        report["narration"] = _seed_narration(db)
    with session_scope() as db:
        report["tags_and_constitution_links"] = _seed_tags_and_links(db)
    with session_scope() as db:
        report["curation"] = _seed_curation(db)
        for c, enabled in (("debates", False),):
            cs = db.get(CollectionSetting, c) or CollectionSetting(collection=c)
            cs.machine_translation_enabled = enabled
            db.merge(cs)
    _print(report)


def cmd_seed_fixture_media(_: argparse.Namespace) -> None:
    """Repair already-seeded fixture recordings in place: delivery copy, review state, then the normal
    publish step. Approves nothing, so an item whose transcript review is incomplete stays unpublished."""
    from archive.ingest import graph as ingest_graph
    from archive.ingest import review
    from archive.worker import postgres_checkpointer

    report: dict[str, Any] = {}
    with session_scope() as db:
        report["media_delivery"] = _seed_media_delivery(db)
        items = _items_by_key(db)
        for key in report["media_delivery"]:
            review._update_item_state(db, items[key])
    keys = set(report["media_delivery"])
    with postgres_checkpointer() as cp:
        graph = ingest_graph.build_ingest_graph(checkpointer=cp, rng=random.Random(7))
        with session_scope() as db:
            ready = [(k, i.id) for k, i in _items_by_key(db).items()
                     if k in keys and i.publication_state == "approved"]
        report["publication"] = _seed_publish(graph, ready)
    with session_scope() as db:
        report["state"] = {k: {"publication_state": i.publication_state,
                               "published_version_id": i.published_version_id}
                           for k, i in _items_by_key(db).items() if k in keys}
    _print(report)


# ------------------------------------------------------------------ manifests / datasets

def cmd_validate_manifest(args: argparse.Namespace) -> None:
    from archive.ingest.intake import load_manifest, validate_manifest

    errors = validate_manifest(load_manifest(Path(args.path)))
    _print({"valid": not errors, "errors": errors})
    sys.exit(1 if errors else 0)


def cmd_import_manifest(args: argparse.Namespace) -> None:
    from archive import jobs
    from archive.ingest.intake import import_manifest, load_manifest

    path = Path(args.path)
    with session_scope() as db:
        report = import_manifest(db, load_manifest(path), path.parent, args.actor)
        if args.enqueue:
            for it in report["items"]:
                if it.get("item_id") and it.get("status") != "already_imported":
                    jobs.enqueue(db, "ingest_item", {"item_id": it["item_id"], "actor": args.actor})
    _print(report)


def cmd_freeze_dataset(args: argparse.Namespace) -> None:
    from archive.datasets.corpus import freeze_dataset

    with session_scope() as db:
        dv = freeze_dataset(db, args.name, args.actor)
        _print({"id": dv.id, "name": dv.name, "passages": dv.passage_count, "items": dv.item_count,
                "sha256": dv.manifest_sha256, "splits": dv.split_definition, "gate": dv.gate_report})


def cmd_load_labels(args: argparse.Namespace) -> None:
    from archive.datasets.corpus import load_labels

    labels = json.loads(Path(args.path).read_text(encoding="utf-8"))["labels"]
    with session_scope() as db:
        added, problems = load_labels(db, labels, args.reviewer)
    _print({"added": added, "problems": problems})


def cmd_dataset_preview(_: argparse.Namespace) -> None:
    from sqlalchemy import text

    from archive.datasets.corpus import preview_dataset

    with session_scope() as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        report = preview_dataset(db)
    report.pop("entries")
    _print(report)


def cmd_mine_hard_negatives(args: argparse.Namespace) -> None:
    from archive.datasets.hard_negatives import mine

    with session_scope() as db:
        report = mine(db, per_question=args.per_question, candidate_k=args.candidate_k, actor=args.actor,
                      example_ids=args.example_id)
    _print(report)


def cmd_list_hard_negatives(args: argparse.Namespace) -> None:
    from archive.datasets.hard_negatives import list_candidates

    with session_scope() as db:
        rows = list_candidates(db, None if args.status == "all" else args.status, args.limit)
    if args.out:
        Path(args.out).write_text(json.dumps({
            "_note": "Fill 'decision' (confirm | relevant | reject) and optionally 'note' per row, then run "
                     "review-hard-negatives --file <this file> --reviewer <your name>. Same text in another edition "
                     "or volume is relevant, not a negative (spec 7.3 step 2).",
            "candidates": rows}, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        _print({"written": args.out, "candidates": len(rows)})
    else:
        _print(rows)


def cmd_review_hard_negative(args: argparse.Namespace) -> None:
    from archive.datasets.hard_negatives import review

    with session_scope() as db:
        _print(review(db, args.candidate_id, args.decision, args.reviewer, args.note))


def cmd_review_hard_negatives(args: argparse.Namespace) -> None:
    from archive.datasets.hard_negatives import review

    rows = json.loads(Path(args.file).read_text(encoding="utf-8"))["candidates"]
    done, skipped = [], []
    with session_scope() as db:
        for r in rows:
            if not r.get("decision"):
                skipped.append(r["candidate_id"])
                continue
            done.append(review(db, int(r["candidate_id"]), r["decision"], args.reviewer, r.get("note")))
    _print({"reviewed": len(done), "undecided": skipped, "warnings": [d["warning"] for d in done if d["warning"]]})


def cmd_export_labels(args: argparse.Namespace) -> None:
    from archive.datasets.hard_negatives import export_labels
    from archive.models import DatasetVersion

    with session_scope() as db:
        dv = db.execute(select(DatasetVersion).where(DatasetVersion.name == args.name)).scalar_one()
        data = export_labels(db, dv)
    Path(args.out).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    _print({"written": args.out, "labels": len(data["labels"])})


# ------------------------------------------------------------------ evaluation

def _resolve_positives(db, positives: list[dict[str, str]]) -> list[int]:
    out = []
    for pos in positives:
        item = db.execute(select(ArchivalItem).where(
            ArchivalItem.capture_details["item_key"].astext == pos["item_key"])).scalar()
        if item is None or not item.published_version_id:
            continue
        pid = db.execute(select(Passage.id).where(Passage.item_version_id == item.published_version_id,
                                                  Passage.indexed.is_(True),
                                                  Passage.text.contains(pos["anchor"]))).scalars().first()
        if pid:
            out.append(pid)
    return out


def cmd_eval_retrieval(args: argparse.Namespace) -> None:
    from archive.evaluation import evaluate_retrieval, write_result

    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    with session_scope() as db:
        qs, unresolved = [], []
        for q in data["questions"]:
            pids = _resolve_positives(db, q["positives"])
            if pids:
                qs.append({"question": q["question"], "language": q["language"], "positive_passage_ids": pids})
            else:
                unresolved.append(q["id"])
        result = evaluate_retrieval(db, qs, k=args.k)
    result.update({"question_set": args.path, "unresolved_questions": unresolved,
                   "note": data.get("_note", "")})
    _print({"written": str(write_result("retrieval", result, Path(args.out))), "modes": result["modes"]})


def cmd_eval_ocr(args: argparse.Namespace) -> None:
    from archive.evaluation import calibrate_gate, evaluate_ocr, write_result
    from archive.ingest import ocr_local, preprocess
    from archive.ingest.graph import default_fallback
    from archive.ingest.quality import apply_gate, compute_signals

    gt_path = Path(args.path)
    gt = json.loads(gt_path.read_text(encoding="utf-8"))
    rows = [r for r in gt["pages"] if r["doc_class"] == "printed"]
    fallback = default_fallback()

    def engine(row: dict[str, Any]) -> dict[str, Any]:
        gray = preprocess.load_gray((gt_path.parent / row["image"]).read_bytes())
        if "half" in row:
            x = preprocess.find_spread_gutter(gray)
            gray = gray[:, :x] if row["half"] == 0 else gray[:, x:]
        prepared = preprocess.preprocess(preprocess.to_png(gray), split_spreads=False)[0]
        out = ocr_local.run_ocr(prepared.image, row["language"])
        sig = compute_signals(out.words, out.text, row["language"], preprocess.detect_text_blocks(prepared.image))
        decision = apply_gate(sig, "printed", row["language"])
        sarvam = None
        if fallback is not None and (not decision.passed or args.sarvam_all):
            sarvam = fallback.digitise_page(preprocess.to_png(prepared.image), row["language"]).text
        return {"local": out.text, "signals": sig.as_dict(), "gate_passed": decision.passed, "sarvam": sarvam}

    result = evaluate_ocr(rows, engine)
    result["calibration_suggestion"] = calibrate_gate(result["rows"])
    result["sarvam_configured"] = fallback is not None
    result["note"] = gt.get("_note", "")
    result["measured_at"] = dt.datetime.now(dt.UTC).isoformat()
    path = write_result("ocr", result, Path(args.out))
    _print({"written": str(path), **{k: v for k, v in result.items() if k != "rows"}})


def cmd_eval_answers(args: argparse.Namespace) -> None:
    from archive.ask.service import ask
    from archive.evaluation import answer_cost_latency, evaluate_answer_behaviour, write_result

    data = json.loads(Path(args.path).read_text(encoding="utf-8"))
    rows = []
    with session_scope() as db:
        for q in data["questions"]:
            res = ask(db, q["question"], [], q.get("language", "en"), session_id=f"eval-{q['id']}")
            rows.append({"id": q["id"], "category": q["category"], "expected": q["expected"],
                         "outcome": res["outcome"], "citations": [c["passage_id"] for c in res.get("citations", [])]})
        summary = evaluate_answer_behaviour(rows)
        summary["cost_latency"] = answer_cost_latency(db)
    summary.update({"rows": rows, "llm_configured": get_settings().llm_available,
                    "prompt_version": get_settings().prompt_version,
                    "sufficiency_threshold": get_settings().sufficiency_threshold,
                    "sufficiency_threshold_version": get_settings().sufficiency_threshold_version})
    path = write_result("answers", summary, Path(args.out))
    _print({"written": str(path), **{k: v for k, v in summary.items() if k != "rows"}})


# ------------------------------------------------------------------ ops

def cmd_backup(args: argparse.Namespace) -> None:
    _print(ops.backup(Path(args.dest) if args.dest else None))


def cmd_restore(args: argparse.Namespace) -> None:
    _print(ops.restore(Path(args.backup), args.target_db, Path(args.target_root)))


def cmd_snapshot_dump(args: argparse.Namespace) -> None:
    cmd = args.dump_cmd[1:] if args.dump_cmd[:1] == ["--"] else args.dump_cmd
    if not cmd:
        sys.exit("snapshot-dump needs a dump command after --")
    res = ops.snapshot_dump(cmd)
    Path(args.counts_out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    _print(res)


def cmd_verify_restore(args: argparse.Namespace) -> None:
    expected = None
    if args.expected_counts:  # bare counts (ops.backup) or the snapshot-dump result that wraps them
        raw = json.loads(Path(args.expected_counts).read_text(encoding="utf-8"))
        expected = raw["counts"] if isinstance(raw.get("counts"), dict) else raw
    res = ops.verify_restore(args.target_db, Path(args.target_root), expected)
    if args.out:
        Path(args.out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    _print(res)
    sys.exit(0 if res["success"] else 1)


def cmd_fixity(_: argparse.Namespace) -> None:
    with session_scope() as db:
        r = ops.fixity(db)
    _print({"checked": r["checked"], "failed": r["failed"]})
    sys.exit(1 if r["failed"] else 0)


def cmd_storage_report(args: argparse.Namespace) -> None:
    from archive.evaluation import storage_report, write_result

    with session_scope() as db:
        r = storage_report(db)
    if args.out:
        write_result("storage", r, Path(args.out))
    _print(r)


def cmd_draft_agent_summaries(args: argparse.Namespace) -> None:
    import httpx

    from archive.ask.llm import OpenAICompatibleLLM
    from archive.services import summaries

    if not get_settings().llm_available:
        _print({"error": "no answer model configured"})
        sys.exit(1)
    llm = OpenAICompatibleLLM(client=httpx.Client(timeout=httpx.Timeout(180, connect=10)))
    out, failed = [], False
    for item_id in args.item:
        with session_scope() as db:
            item = db.get(ArchivalItem, item_id)
            try:
                if item is None:
                    raise summaries.SummaryError(f"item {item_id} not found")
                d = summaries.draft_from_published_text(db, item, llm, args.actor)
                out.append({"item_id": item_id, "derivative_id": d.id, "label": d.label_shown,
                            "status": d.status, "passages": len(d.source_ids), "text": d.content})
            except summaries.SummaryError as exc:
                failed = True
                out.append({"item_id": item_id, "error": str(exc)})
    _print(out)
    sys.exit(1 if failed else 0)


def cmd_approve_agent_summary(args: argparse.Namespace) -> None:
    from archive.services import summaries

    corrected = sys.stdin.read() if args.corrected_text_stdin else None
    if corrected is not None and len(args.derivative) != 1:
        raise SystemExit("--corrected-text-stdin takes exactly one --derivative")
    with session_scope() as db:
        out = []
        for d_id in args.derivative:
            d = db.get(Derivative, d_id)
            if d is None:
                raise SystemExit(f"derivative {d_id} not found")
            summaries.approve_as_agent(db, d, args.actor, corrected_text=corrected)
            out.append({"derivative_id": d.id, "item_id": d.item_id, "status": d.status, "label": d.label_shown,
                        "reviewed_by": d.reviewed_by})
    _print(out)


def cmd_audit_verify(_: argparse.Namespace) -> None:
    with session_scope() as db:
        ok, n = audit.verify_chain(db)
    _print({"chain_ok": ok, "events": n})
    sys.exit(0 if ok else 1)


def main(argv: list[str] | None = None) -> None:
    configure_logging(get_settings().log_level)
    ap = argparse.ArgumentParser(prog="archive")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bootstrap").set_defaults(fn=cmd_bootstrap)
    p = sub.add_parser("seed-fixtures")
    p.add_argument("--fixtures", default="/fixtures")
    p.set_defaults(fn=cmd_seed_fixtures)
    sub.add_parser("seed-fixture-media").set_defaults(fn=cmd_seed_fixture_media)
    p = sub.add_parser("validate-manifest")
    p.add_argument("path")
    p.set_defaults(fn=cmd_validate_manifest)
    p = sub.add_parser("import-manifest")
    p.add_argument("path")
    p.add_argument("--actor", default="cli-import")
    p.add_argument("--enqueue", action="store_true", help="queue ingestion jobs for the worker")
    p.set_defaults(fn=cmd_import_manifest)
    p = sub.add_parser("freeze-dataset")
    p.add_argument("name")
    p.add_argument("--actor", default="cli")
    p.set_defaults(fn=cmd_freeze_dataset)
    p = sub.add_parser("load-labels")
    p.add_argument("path")
    p.add_argument("--reviewer", required=True)
    p.set_defaults(fn=cmd_load_labels)
    sub.add_parser("dataset-preview", help="read-only: next dataset version's splits and gate report"
                   ).set_defaults(fn=cmd_dataset_preview)
    p = sub.add_parser("mine-hard-negatives", help="base-retriever candidates for reviewed, unfrozen examples")
    p.add_argument("--per-question", type=int, default=5)
    p.add_argument("--candidate-k", type=int)
    p.add_argument("--example-id", type=int, action="append")
    p.add_argument("--actor", default="hard-negative-miner")
    p.set_defaults(fn=cmd_mine_hard_negatives)
    p = sub.add_parser("list-hard-negatives")
    p.add_argument("--status", default="candidate", choices=["candidate", "confirmed", "false_negative", "rejected", "all"])
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--out", help="write a reviewer worksheet (JSON) instead of printing")
    p.set_defaults(fn=cmd_list_hard_negatives)
    p = sub.add_parser("review-hard-negative")
    p.add_argument("candidate_id", type=int)
    p.add_argument("--decision", required=True, choices=["confirm", "relevant", "reject"])
    p.add_argument("--reviewer", required=True)
    p.add_argument("--note")
    p.set_defaults(fn=cmd_review_hard_negative)
    p = sub.add_parser("review-hard-negatives", help="apply decisions from a list-hard-negatives --out worksheet")
    p.add_argument("--file", required=True)
    p.add_argument("--reviewer", required=True)
    p.set_defaults(fn=cmd_review_hard_negatives)
    p = sub.add_parser("export-labels", help="frozen dataset version as a labels file (for check_training_leakage.py)")
    p.add_argument("name")
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_export_labels)
    p = sub.add_parser("eval-retrieval")
    p.add_argument("path")
    p.add_argument("--out", default="/eval/results")
    p.add_argument("--k", type=int, default=5)
    p.set_defaults(fn=cmd_eval_retrieval)
    p = sub.add_parser("eval-ocr")
    p.add_argument("path")
    p.add_argument("--out", default="/eval/results")
    p.add_argument("--sarvam-all", action="store_true", help="also send gate-passing pages to Sarvam (comparison only)")
    p.set_defaults(fn=cmd_eval_ocr)
    p = sub.add_parser("eval-answers")
    p.add_argument("path")
    p.add_argument("--out", default="/eval/results")
    p.set_defaults(fn=cmd_eval_answers)
    p = sub.add_parser("backup")
    p.add_argument("--dest")
    p.set_defaults(fn=cmd_backup)
    p = sub.add_parser("restore")
    p.add_argument("backup")
    p.add_argument("--target-db", required=True)
    p.add_argument("--target-root", required=True)
    p.set_defaults(fn=cmd_restore)
    p = sub.add_parser("snapshot-dump", help="count key tables in an exported snapshot, then run the given dump "
                                              "command with --snapshot=<id> appended")
    p.add_argument("--counts-out", required=True)
    p.add_argument("dump_cmd", nargs=argparse.REMAINDER)
    p.set_defaults(fn=cmd_snapshot_dump)
    p = sub.add_parser("verify-restore", help="file rows, key-table counts and audit chain of a restored copy")
    p.add_argument("--target-db", required=True)
    p.add_argument("--target-root", required=True)
    p.add_argument("--expected-counts", help="DB_COUNTS.json written by snapshot-dump")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_verify_restore)
    sub.add_parser("fixity").set_defaults(fn=cmd_fixity)
    p = sub.add_parser("storage-report")
    p.add_argument("--out")
    p.set_defaults(fn=cmd_storage_report)
    sub.add_parser("audit-verify").set_defaults(fn=cmd_audit_verify)
    p = sub.add_parser("draft-agent-summaries", help="one answer-model call per published item; drafts stay hidden")
    p.add_argument("--item", type=int, action="append", required=True)
    p.add_argument("--actor", default="summary-agent")
    p.set_defaults(fn=cmd_draft_agent_summaries)
    p = sub.add_parser("approve-agent-summary", help="show an agent-drafted summary to visitors, labelled as AI")
    p.add_argument("--derivative", type=int, action="append", required=True)
    p.add_argument("--actor", default="summary-agent")
    p.add_argument("--corrected-text-stdin", action="store_true",
                   help="replace the model draft with text read from stdin (recorded as a correction)")
    p.set_defaults(fn=cmd_approve_agent_summary)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
