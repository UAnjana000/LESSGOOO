"""Test configuration.

DB tests run against a real PostgreSQL+pgvector database named archive_test (created and migrated here).
Retrieval uses deterministic test doubles (hash embedder, lexical reranker) so tests are reproducible;
they are never presented as the live models. External providers (Sarvam, LLM, Langfuse) are disabled.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="archive-test-"))
_base = os.environ.get("ARCHIVE_DATABASE_URL", "postgresql+psycopg://archive:archive-dev@localhost:55432/archive")
TEST_DB_URL = os.environ.get("ARCHIVE_TEST_DATABASE_URL") or _base.rsplit("/", 1)[0] + "/archive_test"

os.environ.update({
    "ARCHIVE_ENVIRONMENT": "test",
    "ARCHIVE_DATABASE_URL": TEST_DB_URL,
    "ARCHIVE_PRESERVATION_ROOT": str(_TMP / "preservation"),
    "ARCHIVE_DELIVERY_ROOT": str(_TMP / "delivery"),
    "ARCHIVE_DERIVATIVE_ROOT": str(_TMP / "derivatives"),
    "ARCHIVE_QUARANTINE_ROOT": str(_TMP / "quarantine"),
    "ARCHIVE_TRACE_ROOT": str(_TMP / "traces"),
    "ARCHIVE_BACKUP_ROOT": str(_TMP / "backups"),
    "ARCHIVE_MODEL_CACHE": str(_TMP / "models"),
    "ARCHIVE_EMBEDDING_BACKEND": "hash",
    "ARCHIVE_RERANKER_BACKEND": "lexical",
    "ARCHIVE_SARVAM_API_KEY": "",
    "ARCHIVE_LLM_PROVIDER": "none",
    "ARCHIVE_LANGFUSE_PUBLIC_KEY": "",
    "ARCHIVE_LANGFUSE_SECRET_KEY": "",
    "ARCHIVE_JWT_SECRET": "test-secret-not-for-production-0123456789",
    "ARCHIVE_SUFFICIENCY_THRESHOLD": "0.3",
})

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


def _db_available() -> bool:
    from sqlalchemy import create_engine, text

    admin = TEST_DB_URL.rsplit("/", 1)[0] + "/postgres"
    try:
        eng = create_engine(admin, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
        with eng.connect() as c:
            if not c.execute(text("SELECT 1 FROM pg_database WHERE datname='archive_test'")).scalar():
                c.execute(text("CREATE DATABASE archive_test"))
        eng.dispose()
        return True
    except Exception:
        return False


_DB_OK: bool | None = None


@pytest.fixture(scope="session")
def migrated():
    global _DB_OK
    if _DB_OK is None:
        _DB_OK = _db_available()
    if not _DB_OK:
        pytest.skip("PostgreSQL test database not reachable")
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(cfg, "head")
    from archive import storage

    storage.ensure_roots()
    yield


@pytest.fixture
def db(migrated):
    from sqlalchemy import text

    from archive.db import get_engine, new_session

    with get_engine().begin() as c:
        tables = c.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' "
                                "AND tablename NOT IN ('alembic_version') AND tablename NOT LIKE 'checkpoint%'")).scalars().all()
        c.execute(text("TRUNCATE " + ", ".join(f'"{t}"' for t in tables) + " RESTART IDENTITY CASCADE"))
    s = new_session()
    yield s
    s.close()


@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from archive.api.main import app

    with TestClient(app) as c:
        yield c


def png_page(text: str = "Synthetic test page", size=(800, 1000)) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("L", size, 250)
    d = ImageDraw.Draw(img)
    for i, line in enumerate(text.split("\n")):
        d.text((60, 80 + i * 30), line, fill=10)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def sarvam_image_dump_markdown(images: int = 7, transcription: str = "") -> str:
    """Shape of the live Sarvam Doc AI output for fx-lecture-tank-degraded.png (docs/LIVE_TEST.md 3.3):
    inline data-URI JPEGs, each followed by a model-written description, and no transcription."""
    import base64

    blob = base64.b64encode(bytes(range(256)) * 60).decode("ascii")  # ~20k chars per image, like the live dump
    parts = []
    for i in range(images):
        parts.append(f"![Image {i + 1}](data:image/jpeg;base64,{blob})")
        parts.append("*The image appears to be a grayscale, low-resolution photograph of a printed page. "
                     "The text is blurred and largely illegible, with heavy noise across the scan.*")
        parts.append("This image depicts a document with several paragraphs; details cannot be made out.")
    if transcription:
        parts.insert(3, transcription)
    return "\n\n".join(parts)


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TMP, ignore_errors=True)
