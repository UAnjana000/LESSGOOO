"""Curated knowledge map, timeline, story and signage: visitors see only approved curation that points at
visible items. All content is synthetic."""

from __future__ import annotations

import pytest

from archive.ingest import publish
from archive.models import ArchivalItem

from .factories import make_item, make_rights, publish_item
from .test_db_visitor_features import _login

pytestmark = pytest.mark.db


def _items(db):
    a = make_item(db, make_rights(db), ["Synthetic essay on reading rooms."], title="Essay A")
    b = make_item(db, make_rights(db, key="r2"), ["Synthetic lecture on night schools."], title="Lecture B")
    draft = make_item(db, make_rights(db, key="r3"), ["unreviewed"], title="Draft C", approve=False)
    publish_item(db, a)
    publish_item(db, b)
    db.commit()
    return a, b, draft


class TestKnowledgeMap:
    def test_only_approved_nodes_and_edges_between_visible_items_are_shown(self, db, client):
        a, b, draft = _items(db)
        h = _login(client, db, ["curator"], "curator@test")

        def node(label, item):
            nid = client.post("/api/staff/map/nodes", json={"node_type": "concept", "labels": {"en": label},
                                                            "item_ids": [item.id]}, headers=h).json()["id"]
            return nid

        na, nb, nc = node("Reading rooms", a), node("Night schools", b), node("Hidden", draft)
        assert client.get("/api/visitor/map").json()["nodes"] == []  # proposed nodes are not shown
        for n in (na, nb, nc):
            client.post(f"/api/staff/map/nodes/{n}/approve", headers=h)
        edge = client.post("/api/staff/map/edges", json={"from_node": na, "to_node": nb, "relation": "related_to",
                                                         "evidence_item_ids": [a.id]}, headers=h).json()["id"]
        client.post("/api/staff/map/edges", json={"from_node": na, "to_node": nc, "relation": "mentions",
                                                  "evidence_item_ids": [a.id]}, headers=h)

        m = client.get("/api/visitor/map").json()
        assert {n["id"] for n in m["nodes"]} == {na, nb} and m["edges"] == []

        client.post(f"/api/staff/map/edges/{edge}/approve", headers=h)
        m = client.get("/api/visitor/map").json()
        assert [(e["from"], e["to"], e["relation"]) for e in m["edges"]] == [(na, nb, "related_to")]

        publish.withdraw(db, db.get(ArchivalItem, b.id), "archivist", "test withdrawal")
        db.commit()
        m = client.get("/api/visitor/map").json()
        assert {n["id"] for n in m["nodes"]} == {na} and m["edges"] == []

    def test_map_curation_needs_curator_role_and_valid_nodes(self, db, client):
        a, _, _ = _items(db)
        archivist = _login(client, db, ["archivist"], "archivist@test")
        assert client.post("/api/staff/map/nodes", json={"node_type": "concept", "labels": {"en": "x"},
                                                         "item_ids": [a.id]}, headers=archivist).status_code == 403
        h = _login(client, db, ["curator"], "curator@test")
        n = client.post("/api/staff/map/nodes", json={"node_type": "concept", "labels": {"en": "x"},
                                                      "item_ids": [a.id]}, headers=h).json()["id"]
        assert client.post("/api/staff/map/edges", json={"from_node": n, "to_node": n, "relation": "self",
                                                         "evidence_item_ids": [a.id]}, headers=h).status_code == 422
        assert client.post("/api/staff/map/nodes", json={"node_type": "concept", "labels": {"en": "y"},
                                                         "item_ids": [999999]}, headers=h).status_code == 422


class TestTimelineAndStory:
    def test_timeline_shows_approved_events_with_visible_items_only(self, db, client):
        a, _, draft = _items(db)
        h = _login(client, db, ["curator"], "curator@test")
        ev = {"date_text": "1921 (fictional)", "sort_date": "1921-01-01", "date_certainty": "approximate",
              "titles": {"en": "Reading room opens"}}
        client.post("/api/staff/timeline", json={**ev, "item_ids": [a.id], "status": "approved"}, headers=h)
        pending = client.post("/api/staff/timeline", json={**ev, "item_ids": [a.id]}, headers=h).json()["id"]
        client.post("/api/staff/timeline", json={**ev, "item_ids": [draft.id], "status": "approved"}, headers=h)

        tl = client.get("/api/visitor/timeline").json()
        assert len(tl) == 1 and [i["id"] for i in tl[0]["items"]] == [a.id]
        assert tl[0]["date_certainty"] == "approximate"

        client.post(f"/api/staff/timeline/{pending}/approve", headers=h)
        assert len(client.get("/api/visitor/timeline").json()) == 2
        assert client.post("/api/staff/timeline", json={**ev, "item_ids": []}, headers=h).status_code == 422

    def test_story_blocks_must_cite_items_and_unpublished_blocks_are_hidden(self, db, client):
        a, b, draft = _items(db)
        h = _login(client, db, ["curator"], "curator@test")
        assert client.post("/api/staff/stories", json={"slug": "s", "titles": {"en": "S"},
                                                       "blocks": [{"captions": {"en": "no source"}}]},
                           headers=h).status_code == 422
        blocks = [{"item_id": i.id, "captions": {"en": f"about {i.title}"}} for i in (a, draft, b)]
        client.post("/api/staff/stories", json={"slug": "synthetic-story", "titles": {"en": "Synthetic story"},
                                                "blocks": blocks, "status": "approved"}, headers=h)

        st = client.get("/api/visitor/stories/synthetic-story").json()
        assert [blk["item"]["id"] for blk in st["blocks"]] == [a.id, b.id]
        assert all(blk["deep_link"].startswith(f"/item/{blk['item']['id']}") for blk in st["blocks"])

    def test_signage_loop_serves_the_timeline_and_first_story(self, db, client):
        a, _, _ = _items(db)
        h = _login(client, db, ["curator"], "curator@test")
        client.post("/api/staff/timeline", json={"date_text": "1921", "sort_date": "1921-01-01",
                                                 "titles": {"en": "Opens"}, "item_ids": [a.id],
                                                 "status": "approved"}, headers=h)
        client.post("/api/staff/stories", json={"slug": "loop", "titles": {"en": "Loop"},
                                                "blocks": [{"item_id": a.id}], "status": "approved"}, headers=h)

        sig = client.get("/api/visitor/signage").json()

        assert len(sig["timeline"]) == 1 and sig["story"]["slug"] == "loop" and sig["slide_seconds"] == 12
