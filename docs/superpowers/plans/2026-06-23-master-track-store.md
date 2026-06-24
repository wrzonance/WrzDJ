# Master Track Store — Foundation (PR1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the master `tracks` table + its read/write service (provenance-aware, precedence-guarded), the additive foundation of the hard cutover — mergeable on its own with no reader behavior change.

**Architecture:** A single ISRC-first / signature-fallback `tracks` table is the future single source of truth for song data. A thin `app/services/tracks/` service exposes `get_track` and `upsert_track`; `upsert_track` writes each field's value + provenance together, gated by a source-precedence ladder so a lower-trust source never downgrades a higher one. This PR is purely additive — nothing reads from the table yet.

**Tech Stack:** FastAPI · SQLAlchemy 2.0 (Mapped/mapped_column) · Alembic · Pydantic v2 · pytest (SQLite in-memory).

**Spec:** `docs/superpowers/specs/2026-06-23-master-track-store-design.md` (§3 schema, §4 identity, §5 service, §9 errors, §10 testing).

## Global Constraints

- Backend lint: **ruff line-length 100**, rules E, F, I, UP (`== None`/`== True` allowed). Run `.venv/bin/ruff check . && .venv/bin/ruff format --check .` from `server/`.
- **Energy scale is integer 0–10** everywhere.
- **Coverage gate 85%** (`--cov-fail-under`) must hold — run the full `.venv/bin/pytest` before the final commit.
- **Migrations:** numeric revision ids; current head is **`061`**, so the new revision is **`062`**, `down_revision="061"`. `alembic upgrade head && alembic check` must pass.
- **Model registration:** every model is imported + listed in `server/app/models/__init__.py`; the test schema is `Base.metadata.create_all` over those, so registering `Track` there makes it appear in tests automatically.
- **JSON columns:** use SQLAlchemy `JSON` (portable across SQLite tests + Postgres 16 prod).
- **Imports to reuse:** `from app.models.base import Base`, `from app.core.time import utcnow`, `dedupe_signature` from `app.services.setbuilder.pool`.
- **Commits:** Conventional Commits; end each with `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Branch:** `feat/540-master-track-store` off `origin/main`; never commit to `main`.

---

### Task 1: Read-site inventory (cutover blast-radius map)

**Files:**
- Create: `docs/superpowers/specs/2026-06-23-track-read-site-inventory.md`

**Interfaces:**
- Consumes: nothing.
- Produces: a documented enumeration consumed by the later cutover PRs (not by this PR's code).

- [ ] **Step 1: Grep every track-metadata read/write site**

Run from `server/`:
```bash
grep -rnE "\.(bpm|musical_key|camelot|genre|energy|duration_sec|isrc)\b|\.key\b" app | grep -vE "tests/|\.pyc" > /tmp/track_reads.txt
grep -rnE "SetPoolTrack|TrackVibe|vibe_resolver|enrich_request_metadata|_track_meta" app | grep -vE "tests/|\.pyc" >> /tmp/track_reads.txt
wc -l /tmp/track_reads.txt
```

- [ ] **Step 2: Write the inventory doc**

Group the hits into a table with columns: `file:line` · field(s) touched · read|write · subsystem (request-pipeline | setbuilder | vibe | recommendation | dashboard). Include a "Cutover action" column (which PR repoints it). Write to the file above with this header:
```markdown
# Track-metadata read-site inventory (cutover blast-radius)
Date: 2026-06-23 · Feeds #540 hard cutover (repoint targets for PR3/PR4, drop targets for PR5).
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-06-23-track-read-site-inventory.md
git commit -m "docs(tracks): read-site inventory for the master-table cutover (#540)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Provenance model + precedence ladder

**Files:**
- Create: `server/app/services/tracks/__init__.py` (empty package marker)
- Create: `server/app/services/tracks/provenance.py`
- Test: `server/tests/test_track_provenance.py`

**Interfaces:**
- Produces:
  - `class FieldProvenance(BaseModel)` with `source: str`, `fetched_at: datetime`
  - `SOURCE_PRECEDENCE: dict[str, int]`
  - `def precedence(source: str) -> int`
  - `def should_overwrite(existing: dict | None, new_source: str) -> bool` — `existing` is a stored provenance entry `{"source","fetched_at"}` or None
  - `class FieldProvenance` is consumed by `upsert_track` (Task 5) to build/serialize each entry; no separate merge helper — gating happens inline in upsert via `should_overwrite`.

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_track_provenance.py
from datetime import datetime

from app.services.tracks.provenance import (
    precedence,
    should_overwrite,
)

T0 = datetime(2026, 6, 23, 12, 0, 0)


def test_precedence_ladder_orders_sources():
    assert precedence("manual") > precedence("lexicon") > precedence("soundcharts")
    assert precedence("soundcharts") > precedence("community") > precedence("llm")
    assert precedence("unknown-source") == 0


def test_should_overwrite_null_existing_is_true():
    assert should_overwrite(None, "llm") is True


def test_should_overwrite_blocks_downgrade():
    existing = {"source": "soundcharts", "fetched_at": T0.isoformat()}
    assert should_overwrite(existing, "llm") is False  # llm cannot clobber measured


def test_should_overwrite_allows_equal_or_higher():
    existing = {"source": "soundcharts", "fetched_at": T0.isoformat()}
    assert should_overwrite(existing, "soundcharts") is True   # refresh same tier
    assert should_overwrite(existing, "lexicon") is True       # higher tier wins
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_track_provenance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.tracks'`

- [ ] **Step 3: Write minimal implementation**

```python
# server/app/services/tracks/__init__.py
```
(empty file)

```python
# server/app/services/tracks/provenance.py
"""Per-field provenance + source-precedence for the master tracks store (#540).

The stored JSON shape is {field: {"source": str, "fetched_at": ISO8601 str}}.
Precedence guards the cascade: a lower-trust source never downgrades a higher
one (measured energy must survive a later LLM re-inference).
"""

from datetime import datetime

from pydantic import BaseModel

SOURCE_PRECEDENCE: dict[str, int] = {
    "manual": 100,
    "lexicon": 90,
    "soundcharts": 50,
    "beatport": 50,
    "tidal": 50,
    "musicbrainz": 50,
    "community": 40,
    "llm": 10,
}


class FieldProvenance(BaseModel):
    source: str
    fetched_at: datetime


def precedence(source: str) -> int:
    return SOURCE_PRECEDENCE.get(source, 0)


def should_overwrite(existing: dict | None, new_source: str) -> bool:
    """True if a value sourced from new_source may replace the existing field."""
    if existing is None:
        return True
    return precedence(new_source) >= precedence(existing.get("source", ""))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_track_provenance.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add server/app/services/tracks/__init__.py server/app/services/tracks/provenance.py server/tests/test_track_provenance.py
git commit -m "feat(tracks): provenance model + source-precedence ladder (#540)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `Track` SQLAlchemy model + registration

**Files:**
- Create: `server/app/models/track.py`
- Modify: `server/app/models/__init__.py` (add import + `__all__` entry)
- Test: `server/tests/test_track_model.py`

**Interfaces:**
- Produces: `class Track(Base)` (table `tracks`) with the columns in spec §3; unique constraints `uq_tracks_isrc`, `uq_tracks_signature`.

- [ ] **Step 1: Write the failing test**

```python
# server/tests/test_track_model.py
from app.models.track import Track


def test_track_table_and_columns():
    cols = Track.__table__.columns.keys()
    for expected in (
        "isrc", "signature", "title", "artist", "soundcharts_uuid",
        "bpm", "musical_key", "camelot", "genre", "duration_sec",
        "energy", "danceability", "valence", "acousticness",
        "instrumentalness", "speechiness", "liveness", "loudness_db",
        "time_signature", "explicit", "artwork_url", "provenance",
        "created_at", "updated_at",
    ):
        assert expected in cols, f"missing column {expected}"
    assert Track.__tablename__ == "tracks"
    assert Track.__table__.columns["signature"].nullable is False
    assert Track.__table__.columns["isrc"].nullable is True


def test_track_unique_constraints():
    names = {c.name for c in Track.__table__.constraints}
    assert "uq_tracks_isrc" in names
    assert "uq_tracks_signature" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_track_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.track'`

- [ ] **Step 3: Write minimal implementation**

```python
# server/app/models/track.py
"""Master enriched-track table (#540) — single source of truth for song data.

ISRC-first identity with a normalized artist/title signature fallback, so every
track gets exactly one row. Typed value columns are queryable; per-field
source/freshness lives in the `provenance` JSON sidecar (see services/tracks).
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utcnow
from app.models.base import Base


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (
        UniqueConstraint("isrc", name="uq_tracks_isrc"),
        UniqueConstraint("signature", name="uq_tracks_signature"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    isrc: Mapped[str | None] = mapped_column(String(15), nullable=True, index=True)
    signature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    artist: Mapped[str] = mapped_column(String(255), nullable=False)
    soundcharts_uuid: Mapped[str | None] = mapped_column(String(36), nullable=True)

    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    musical_key: Mapped[str | None] = mapped_column(String(20), nullable=True)
    camelot: Mapped[str | None] = mapped_column(String(3), nullable=True)
    genre: Mapped[str | None] = mapped_column(String(100), nullable=True)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    energy: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-10
    danceability: Mapped[float | None] = mapped_column(Float, nullable=True)
    valence: Mapped[float | None] = mapped_column(Float, nullable=True)
    acousticness: Mapped[float | None] = mapped_column(Float, nullable=True)
    instrumentalness: Mapped[float | None] = mapped_column(Float, nullable=True)
    speechiness: Mapped[float | None] = mapped_column(Float, nullable=True)
    liveness: Mapped[float | None] = mapped_column(Float, nullable=True)
    loudness_db: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_signature: Mapped[int | None] = mapped_column(Integer, nullable=True)
    explicit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    artwork_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
```

Then add to `server/app/models/__init__.py`: insert `from app.models.track import Track` in alphabetical position (after `from app.models.system_settings import SystemSettings`) and add `"Track",` to `__all__` (after `"SystemSettings",`).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_track_model.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add server/app/models/track.py server/app/models/__init__.py server/tests/test_track_model.py
git commit -m "feat(tracks): Track model (ISRC+signature keyed master table) (#540)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `normalize_isrc` helper + `get_track` lookup

**Files:**
- Modify: `server/services/track_normalizer.py` (add `normalize_isrc`)
- Create: `server/app/services/tracks/store.py`
- Test: `server/tests/test_track_normalizer.py` (add a test), `server/tests/test_track_store.py`

**Interfaces:**
- Consumes: `Track` (Task 3), `dedupe_signature` (existing).
- Produces:
  - `def normalize_isrc(isrc: str | None) -> str | None` in `track_normalizer`
  - `def get_track(db: Session, *, isrc: str | None = None, signature: str | None = None) -> Track | None` in `store.py`

> NOTE: `_normalize_isrc` already exists privately in `setbuilder/pool.py` and `services/soundcharts.py`. This task introduces the canonical public version in `track_normalizer`; migrating those two callers to it is deferred to a follow-up (out of scope for PR1 — don't touch the held `soundcharts.py`).

- [ ] **Step 1: Write the failing tests**

```python
# add to server/tests/test_track_normalizer.py
from app.services.track_normalizer import normalize_isrc  # if module path differs, match existing imports


def test_normalize_isrc_strips_and_uppercases():
    assert normalize_isrc("us-um7-1900764") == "USUM71900764"
    assert normalize_isrc("  usum71900764 ") == "USUM71900764"


def test_normalize_isrc_empty_is_none():
    assert normalize_isrc("") is None
    assert normalize_isrc(None) is None
```

```python
# server/tests/test_track_store.py
from app.models.track import Track
from app.services.tracks.store import get_track


def _make_track(db, **kw):
    t = Track(signature=kw.pop("signature", "sig-1"), title="T", artist="A", **kw)
    db.add(t)
    db.flush()
    return t


def test_get_track_by_isrc_wins(db):
    _make_track(db, signature="sig-x", isrc="USUM71900764", energy=8)
    found = get_track(db, isrc="USUM71900764")
    assert found is not None and found.energy == 8


def test_get_track_falls_back_to_signature(db):
    _make_track(db, signature="sig-y", isrc=None, energy=5)
    assert get_track(db, isrc="NONEXISTENT00", signature="sig-y").energy == 5


def test_get_track_normalizes_isrc(db):
    _make_track(db, signature="sig-z", isrc="USUM71900764")
    assert get_track(db, isrc="us-um7-1900764") is not None


def test_get_track_miss_returns_none(db):
    assert get_track(db, isrc="MISS00000000", signature="nope") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_track_store.py tests/test_track_normalizer.py::test_normalize_isrc_strips_and_uppercases -v`
Expected: FAIL — `ImportError`/`ModuleNotFoundError` for `normalize_isrc` / `app.services.tracks.store`

- [ ] **Step 3: Write minimal implementation**

Add to `server/services/track_normalizer.py`:
```python
def normalize_isrc(isrc: str | None) -> str | None:
    """Uppercase, trim, and strip hyphens/spaces so an ISRC matches as a key."""
    if not isrc:
        return None
    cleaned = isrc.strip().upper().replace("-", "").replace(" ", "")
    return cleaned or None
```

```python
# server/app/services/tracks/store.py
"""Read/write service for the master tracks table (#540)."""

from sqlalchemy.orm import Session

from app.models.track import Track
from app.services.track_normalizer import normalize_isrc


def get_track(
    db: Session, *, isrc: str | None = None, signature: str | None = None
) -> Track | None:
    """Look up a track ISRC-first, then by signature."""
    norm = normalize_isrc(isrc)
    if norm:
        found = db.query(Track).filter(Track.isrc == norm).first()
        if found:
            return found
    if signature:
        return db.query(Track).filter(Track.signature == signature).first()
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_track_store.py tests/test_track_normalizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/services/track_normalizer.py server/app/services/tracks/store.py server/tests/test_track_store.py server/tests/test_track_normalizer.py
git commit -m "feat(tracks): normalize_isrc + get_track ISRC-first lookup (#540)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `upsert_track` — insert + value/provenance write

**Files:**
- Modify: `server/app/services/tracks/store.py`
- Test: `server/tests/test_track_store.py` (add)

**Interfaces:**
- Consumes: `get_track`, `FieldProvenance`, `Track`.
- Produces:
  - `@dataclass class TrackIdentity` with `title: str`, `artist: str`, `signature: str`, `isrc: str | None = None`, `soundcharts_uuid: str | None = None`
  - `def upsert_track(db, *, identity: TrackIdentity, values: dict[str, object], sources: dict[str, str], fetched_at: datetime) -> Track`

> This task writes values UNCONDITIONALLY (last-writer-wins). The precedence guard (Task 6) and ISRC backfill (Task 7) are added on top, each red-first — so this task's `upsert_track` must NOT yet gate on precedence or backfill ISRC on the update path.

- [ ] **Step 1: Write the failing test**

```python
# add to server/tests/test_track_store.py
from datetime import datetime
from app.services.tracks.store import TrackIdentity, upsert_track

T0 = datetime(2026, 6, 23, 12, 0, 0)


def test_upsert_inserts_new_track(db):
    t = upsert_track(
        db,
        identity=TrackIdentity(title="Sandstorm", artist="Darude", signature="sig-sand", isrc="FIXXX1234567"),
        values={"energy": 9, "bpm": 136.0},
        sources={"energy": "soundcharts", "bpm": "beatport"},
        fetched_at=T0,
    )
    assert t.id is not None
    assert t.energy == 9 and t.bpm == 136.0
    assert t.provenance["energy"]["source"] == "soundcharts"
    assert t.provenance["bpm"]["source"] == "beatport"


def test_upsert_updates_existing_by_signature_no_duplicate(db):
    upsert_track(db, identity=TrackIdentity(title="S", artist="D", signature="sig-1"),
                 values={"bpm": 120.0}, sources={"bpm": "tidal"}, fetched_at=T0)
    upsert_track(db, identity=TrackIdentity(title="S", artist="D", signature="sig-1"),
                 values={"genre": "trance"}, sources={"genre": "musicbrainz"}, fetched_at=T0)
    rows = db.query(Track).filter(Track.signature == "sig-1").all()
    assert len(rows) == 1
    assert rows[0].bpm == 120.0 and rows[0].genre == "trance"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_track_store.py -k upsert -v`
Expected: FAIL — `ImportError: cannot import name 'upsert_track'`

- [ ] **Step 3: Write minimal implementation**

Add to `server/app/services/tracks/store.py`:
```python
from dataclasses import dataclass
from datetime import datetime

from app.services.tracks.provenance import FieldProvenance


@dataclass
class TrackIdentity:
    title: str
    artist: str
    signature: str
    isrc: str | None = None
    soundcharts_uuid: str | None = None


def upsert_track(
    db: Session,
    *,
    identity: TrackIdentity,
    values: dict[str, object],
    sources: dict[str, str],
    fetched_at: datetime,
) -> Track:
    """Insert or update the master row, writing each field's value + provenance
    entry. Precedence gating is added in Task 6; ISRC backfill in Task 7."""
    norm_isrc = normalize_isrc(identity.isrc)
    track = get_track(db, isrc=norm_isrc, signature=identity.signature)
    if track is None:
        track = Track(
            signature=identity.signature,
            title=identity.title,
            artist=identity.artist,
            isrc=norm_isrc,
            soundcharts_uuid=identity.soundcharts_uuid,
        )
        db.add(track)

    prov: dict = dict(track.provenance or {})
    for field, value in values.items():
        setattr(track, field, value)
        prov[field] = FieldProvenance(
            source=sources[field], fetched_at=fetched_at
        ).model_dump(mode="json")
    track.provenance = prov
    db.flush()
    return track
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_track_store.py -k upsert -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/app/services/tracks/store.py server/tests/test_track_store.py
git commit -m "feat(tracks): upsert_track insert + value/provenance write (#540)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `upsert_track` — precedence guard (no downgrade)

**Files:**
- Modify: `server/app/services/tracks/store.py`
- Test: `server/tests/test_track_store.py` (add)

**Interfaces:**
- Consumes: `upsert_track`, `should_overwrite` (Task 2).

- [ ] **Step 1: Write the failing test**

```python
# add to server/tests/test_track_store.py
def test_upsert_does_not_downgrade_measured_energy(db):
    upsert_track(db, identity=TrackIdentity(title="S", artist="D", signature="sig-e"),
                 values={"energy": 8}, sources={"energy": "soundcharts"}, fetched_at=T0)
    upsert_track(db, identity=TrackIdentity(title="S", artist="D", signature="sig-e"),
                 values={"energy": 3}, sources={"energy": "llm"}, fetched_at=T0)
    row = db.query(Track).filter(Track.signature == "sig-e").one()
    assert row.energy == 8  # llm did not clobber soundcharts
    assert row.provenance["energy"]["source"] == "soundcharts"


def test_upsert_allows_higher_precedence_override(db):
    upsert_track(db, identity=TrackIdentity(title="S", artist="D", signature="sig-o"),
                 values={"energy": 8}, sources={"energy": "soundcharts"}, fetched_at=T0)
    upsert_track(db, identity=TrackIdentity(title="S", artist="D", signature="sig-o"),
                 values={"energy": 6}, sources={"energy": "lexicon"}, fetched_at=T0)
    row = db.query(Track).filter(Track.signature == "sig-o").one()
    assert row.energy == 6 and row.provenance["energy"]["source"] == "lexicon"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_track_store.py -k "downgrade or higher_precedence" -v`
Expected: `test_upsert_does_not_downgrade_measured_energy` FAILS — Task 5 writes unconditionally, so `llm` energy 3 clobbers soundcharts 8 (`row.energy == 3`). (`test_upsert_allows_higher_precedence_override` already passes; together they characterize the guard.)

- [ ] **Step 3: Add the precedence guard**

In `server/app/services/tracks/store.py`, import `should_overwrite` and gate the write loop:
```python
from app.services.tracks.provenance import FieldProvenance, should_overwrite
```
Replace the value-write loop in `upsert_track` with:
```python
    prov: dict = dict(track.provenance or {})
    for field, value in values.items():
        if should_overwrite(prov.get(field), sources[field]):
            setattr(track, field, value)
            prov[field] = FieldProvenance(
                source=sources[field], fetched_at=fetched_at
            ).model_dump(mode="json")
    track.provenance = prov
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_track_store.py -k upsert -v`
Expected: PASS (all upsert tests, including the precedence pair)

- [ ] **Step 5: Commit**

```bash
git add server/app/services/tracks/store.py server/tests/test_track_store.py
git commit -m "feat(tracks): precedence guard in upsert_track (no downgrade) (#540)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: `upsert_track` — ISRC backfill onto signature-matched row

**Files:**
- Modify: `server/app/services/tracks/store.py`
- Test: `server/tests/test_track_store.py` (add)

**Interfaces:**
- Consumes: `upsert_track`, `get_track`.

- [ ] **Step 1: Write the failing test**

```python
# add to server/tests/test_track_store.py
def test_upsert_backfills_isrc_onto_signature_row(db):
    # First seen with no ISRC (e.g. manual add)
    upsert_track(db, identity=TrackIdentity(title="Sandstorm", artist="Darude", signature="sig-bf"),
                 values={"bpm": 136.0}, sources={"bpm": "manual"}, fetched_at=T0)
    # Later seen WITH an ISRC, same signature → backfill, one row
    upsert_track(db, identity=TrackIdentity(title="Sandstorm", artist="Darude", signature="sig-bf", isrc="FIXXX1234567"),
                 values={"energy": 9}, sources={"energy": "soundcharts"}, fetched_at=T0)
    rows = db.query(Track).filter(Track.signature == "sig-bf").all()
    assert len(rows) == 1
    assert rows[0].isrc == "FIXXX1234567"
    assert rows[0].bpm == 136.0 and rows[0].energy == 9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_track_store.py -k backfill -v`
Expected: FAIL — Task 5 sets `isrc` only on INSERT, so the second (update) call leaves `rows[0].isrc is None` (assert `isrc == "FIXXX1234567"` fails).

- [ ] **Step 3: Add the backfill branch**

In `upsert_track`, after the get_track / insert block and before the value-write loop, add:
```python
    if norm_isrc and not track.isrc:
        track.isrc = norm_isrc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_track_store.py -k upsert -v`
Expected: PASS (all upsert tests)

- [ ] **Step 5: Commit**

```bash
git add server/app/services/tracks/store.py server/tests/test_track_store.py
git commit -m "feat(tracks): ISRC backfill onto signature-matched row in upsert_track (#540)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Alembic migration for the `tracks` table

**Files:**
- Create: `server/alembic/versions/062_master_tracks_table.py`

**Interfaces:**
- Consumes: the `Track` model (Task 3).

- [ ] **Step 1: Autogenerate the migration**

Run from `server/` (DB must be up: `docker compose up -d db`):
```bash
.venv/bin/alembic revision --autogenerate -m "master tracks table"
```
Then rename the generated file to `062_master_tracks_table.py` and set `revision = "062"`, `down_revision = "061"` (match the format of `061_add_request_accepted_at.py`). Verify the autogenerated `upgrade()` creates `tracks` with all columns + `uq_tracks_isrc` / `uq_tracks_signature` + the `isrc`/`signature` indexes, and `downgrade()` drops the table. If autogenerate produced unrelated diffs, delete them — this migration is `tracks`-only.

- [ ] **Step 2: Apply + verify no drift**

Run:
```bash
.venv/bin/alembic upgrade head && .venv/bin/alembic check
```
Expected: upgrade succeeds; `alembic check` prints "No new upgrade operations detected."

- [ ] **Step 3: Verify downgrade**

Run:
```bash
.venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head
```
Expected: both succeed (table drops then recreates cleanly).

- [ ] **Step 4: Commit**

```bash
git add server/alembic/versions/062_master_tracks_table.py
git commit -m "feat(tracks): migration for the master tracks table (#540)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Full CI gate + package export

**Files:**
- Modify: `server/app/services/tracks/__init__.py` (re-export the public API)

**Interfaces:**
- Produces: `from app.services.tracks import get_track, upsert_track, TrackIdentity`

- [ ] **Step 1: Add the package re-exports**

```python
# server/app/services/tracks/__init__.py
from app.services.tracks.provenance import FieldProvenance, should_overwrite
from app.services.tracks.store import TrackIdentity, get_track, upsert_track

__all__ = [
    "FieldProvenance",
    "TrackIdentity",
    "get_track",
    "should_overwrite",
    "upsert_track",
]
```

- [ ] **Step 2: Run the full backend CI gate**

Run from `server/`:
```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && \
.venv/bin/bandit -r app -c pyproject.toml -q && \
.venv/bin/pytest --tb=short -q
```
Expected: ruff clean; bandit "No issues identified"; pytest all pass with **coverage ≥ 85%**.

- [ ] **Step 3: Commit**

```bash
git add server/app/services/tracks/__init__.py
git commit -m "feat(tracks): export master-track-store public API (#540)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:** §3 schema → Task 3 + Task 8. §4 identity (ISRC-first, signature fallback, backfill) → Tasks 4, 5, 7. §5 service API + precedence ladder → Tasks 2, 5, 6. §9 error handling (null fields, no-ISRC→signature) → Tasks 4/5 (null-safe upsert, signature fallback). §10 testing → every task is TDD; cache-aside reuse + characterization tests + #543 regression belong to the **write-wiring/cutover PRs** (out of PR1 scope, noted). Read-site inventory (§7, #540 AC) → Task 1.

**Out of PR1 scope (follow-on plans, seeded by Task 1's inventory):** cache-aside populate-and-reuse write wiring (#541), repointing setbuilder/pass-1 reads + #543 regression (#542/#543), repointing request/recommendation reads, dropping legacy columns (#544 write path uses the already-built Soundcharts adapter).

**Placeholder scan:** none — every code step has complete code; Task 1's "content" is data-gathering output, not a code placeholder.

**Type consistency:** `get_track(db, *, isrc, signature)`, `upsert_track(db, *, identity, values, sources, fetched_at)`, `TrackIdentity(title, artist, signature, isrc?, soundcharts_uuid?)`, `FieldProvenance(source, fetched_at)`, `should_overwrite(existing, new_source)` — names/signatures consistent across Tasks 2/4/5/6/7/9. (`merge_provenance` dropped: gating happens inline in `upsert_track` via `should_overwrite`, so no separate merge helper exists.)

**TDD ordering (pre-flight fix):** Task 5 implements `upsert_track` with UNCONDITIONAL writes; Task 6 adds the precedence guard red-first (its downgrade test fails against Task 5); Task 7 adds ISRC backfill red-first (its test fails against Task 5/6). Each task has a genuine red→green cycle.
