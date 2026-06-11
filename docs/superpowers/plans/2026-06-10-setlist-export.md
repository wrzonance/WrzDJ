# WrzDJSet Setlist Export (Tidal, Rekordbox XML, M3U) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Export a built set to a Tidal playlist (via the DJ's existing OAuth session) or as a downloadable Rekordbox XML / M3U / plaintext file, with a mandatory pre-export resolution check that surfaces unresolved tracks (skip/cancel) — never silently dropped.

**Architecture:** Three small service modules under `server/app/services/setbuilder/` — `export_common.py` (collect the ordered export tracklist from timeline slots, falling back to the pool), `export_files.py` (stdlib-only Rekordbox `DJ_PLAYLISTS` XML, M3U8, plaintext renderers), `export_tidal.py` (3-stage resolution: namespaced `tidal:` id → ISRC exact match → fuzzy search, then playlist create + batched add following the `tidal_adapter.py` precedent). Three authenticated DJ endpoints on the existing `/api/setbuilder` router: `export/preflight`, `export/tidal`, `export/file`. The unresolved-track interrupt is enforced **server-side**: export endpoints return 409 unless `skip_unresolved=true`. Frontend: `ExportModal.tsx` platform picker with roadmap badges, wired into `SetActionsMenu`.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 (no new deps; XML via `xml.etree.ElementTree`), existing `tidalapi`-backed `services/tidal.py`, Next.js/React vanilla-CSS frontend.

**Branch:** `feat/issue-396` in worktree `/home/adam/github/WrzDJ/.worktrees/feat/issue-396`. NEVER commit to main.

**Python tooling:** shared venv at `/home/adam/github/WrzDJ/server/.venv/bin/{pytest,ruff,bandit,alembic}` run from `<worktree>/server`. NEVER pip install.

---

## Design decisions (document in PR)

1. **No new migration.** `tidal_playlist_id`, `exported_at`, and the `"exported"` status value already exist on `sets` (migration `046_add_setbuilder_tables.py`). The orchestrator's 057 instruction was conditional; nothing to migrate.
2. **Export source = timeline slots, pool fallback.** The setlist is the ordered `SetSlot` timeline (joined to `SetPoolTrack` metadata via the namespaced `track_id`). Slot auto-fill (#390) hasn't landed, so when the timeline is empty we fall back to the pool (insertion order) and tell the DJ via `source: "pool"` in the preflight response — visible, not silent.
3. **Resolution semantics per format:**
   - *Tidal*: resolved = has a Tidal track ID via (a) `tidal:` namespaced `track_id`, (b) ISRC exact lookup, or (c) fuzzy search ≥ 0.5 combined score with unwanted-version filtering (mirrors `TidalSyncAdapter`). Everything else is unresolved (`reason: "no_tidal_match"`).
   - *Rekordbox XML / M3U / txt*: file paths are unknowable server-side, so resolved = has title+artist metadata. Only "orphan" slots (slot `track_id` with no pool-track metadata) are unresolved (`reason: "missing_metadata"`).
4. **Rekordbox XML `Location`** uses a synthetic `file://localhost/WrzDJ/<artist> - <title>.mp3` placeholder — rekordbox imports the playlist structure and metadata; the DJ relinks audio. Documented in module docstring.
5. **Each Tidal export creates a fresh playlist** (`WrzDJ Set: <name>`) and overwrites `set.tidal_playlist_id` with the newest. Reusing/clearing an existing playlist risks destroying DJ edits; appending would break setlist order. Old playlists are left untouched in the DJ's account.
6. **Server-side interrupt enforcement:** export endpoints recompute resolution and return **409** `{code: "unresolved_tracks", unresolved: [...]}` unless `skip_unresolved=true`. The modal's happy path uses the preflight response, so it never parses the 409 — the 409 is defense-in-depth for the acceptance criterion.
7. **File download mechanism:** backend returns file content with `Content-Disposition: attachment`; frontend `rawFetch`es the bytes with the Bearer token, builds a blob URL, clicks a synthetic `<a download>`. Filename falls back to a client-computed name if the header isn't CORS-exposed.
8. **Only the Tidal export mutates set state** (`status="exported"`, `exported_at`, `tidal_playlist_id`) — exactly what the issue specifies. File downloads are read-only.
9. **Tidal preflight does live matching** (search per non-`tidal:` track) — that's the cost of an honest resolution list; rate-limited 5/minute.

---

### Task 1: `export_common.py` — ordered export tracklist

**Files:**
- Create: `server/app/services/setbuilder/export_common.py`
- Test: `server/tests/test_setbuilder_export_service.py`

- [ ] **Step 1: Write failing tests** (`server/tests/test_setbuilder_export_service.py`)

```python
"""Service-level tests for setbuilder export (collect/render/resolve)."""

from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.setbuilder.export_common import ExportTrack, collect_export_tracks


def _mk_set(db: Session, user: User) -> Set:
    s = Set(owner_id=user.id, name="Friday Night")
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _mk_pool_track(db: Session, s: Set, **kw) -> SetPoolTrack:
    src = db.query(SetPoolSource).filter(SetPoolSource.set_id == s.id).one_or_none()
    if src is None:
        src = SetPoolSource(set_id=s.id, kind="manual", label="Manual")
        db.add(src)
        db.commit()
        db.refresh(src)
    defaults = dict(
        set_id=s.id,
        source_id=src.id,
        title="Track",
        artist="Artist",
        dedupe_sig=f"sig-{kw.get('title', 'Track')}-{kw.get('artist', 'Artist')}",
    )
    defaults.update(kw)
    t = SetPoolTrack(**defaults)
    db.add(t)
    db.commit()
    db.refresh(t)
    return t


class TestCollectExportTracks:
    def test_empty_set_returns_pool_source_and_no_tracks(self, db: Session, test_user: User):
        s = _mk_set(db, test_user)
        source, tracks = collect_export_tracks(s)
        assert source == "pool"
        assert tracks == []

    def test_pool_fallback_preserves_insertion_order(self, db: Session, test_user: User):
        s = _mk_set(db, test_user)
        _mk_pool_track(db, s, title="B Song", artist="B", dedupe_sig="s1")
        _mk_pool_track(db, s, title="A Song", artist="A", dedupe_sig="s2")
        db.refresh(s)
        source, tracks = collect_export_tracks(s)
        assert source == "pool"
        assert [t.title for t in tracks] == ["B Song", "A Song"]
        assert [t.position for t in tracks] == [0, 1]

    def test_timeline_joins_pool_metadata_by_track_id(self, db: Session, test_user: User):
        s = _mk_set(db, test_user)
        _mk_pool_track(
            db, s, title="Joined", artist="DJ", track_id="tidal:111",
            bpm=128.0, camelot="8A", isrc="USX9P1234567", duration_sec=200, dedupe_sig="s1",
        )
        db.add(SetSlot(set_id=s.id, position=0, track_id="tidal:111"))
        db.commit()
        db.refresh(s)
        source, tracks = collect_export_tracks(s)
        assert source == "timeline"
        assert len(tracks) == 1
        t = tracks[0]
        assert (t.title, t.artist, t.bpm, t.camelot) == ("Joined", "DJ", 128.0, "8A")
        assert t.tidal_id == "111"

    def test_timeline_orders_by_position_and_skips_empty_slots(self, db: Session, test_user: User):
        s = _mk_set(db, test_user)
        _mk_pool_track(db, s, title="First", artist="A", track_id="tidal:1", dedupe_sig="s1")
        _mk_pool_track(db, s, title="Second", artist="B", track_id="tidal:2", dedupe_sig="s2")
        db.add_all(
            [
                SetSlot(set_id=s.id, position=1, track_id="tidal:2"),
                SetSlot(set_id=s.id, position=0, track_id="tidal:1"),
                SetSlot(set_id=s.id, position=2, track_id=None),  # empty slot
            ]
        )
        db.commit()
        db.refresh(s)
        _, tracks = collect_export_tracks(s)
        assert [t.title for t in tracks] == ["First", "Second"]

    def test_orphan_slot_yields_metadata_less_track(self, db: Session, test_user: User):
        s = _mk_set(db, test_user)
        db.add(SetSlot(set_id=s.id, position=0, track_id="beatport:999"))
        db.commit()
        db.refresh(s)
        source, tracks = collect_export_tracks(s)
        assert source == "timeline"
        assert tracks[0].title == ""
        assert tracks[0].track_id == "beatport:999"
        assert not tracks[0].has_metadata


class TestExportTrack:
    def test_tidal_id_parses_namespace(self):
        assert ExportTrack(position=0, title="t", artist="a", track_id="tidal:42").tidal_id == "42"
        assert ExportTrack(position=0, title="t", artist="a", track_id="beatport:42").tidal_id is None
        assert ExportTrack(position=0, title="t", artist="a", track_id=None).tidal_id is None
```

- [ ] **Step 2: Run tests, verify they fail** — `cd /home/adam/github/WrzDJ/.worktrees/feat/issue-396/server && /home/adam/github/WrzDJ/server/.venv/bin/pytest tests/test_setbuilder_export_service.py -q --no-cov` → ImportError (`export_common` missing).

- [ ] **Step 3: Implement** `server/app/services/setbuilder/export_common.py`

```python
"""Shared export-tracklist collection for WrzDJSet exports (issue #396).

The exported setlist is the ordered SetSlot timeline, with track metadata
joined from the pool via the namespaced ``track_id`` convention
("tidal:123", "beatport:45", ...). Until timeline auto-fill (#390) lands,
sets typically have no slots — in that case we fall back to the pool in
insertion order and report ``source="pool"`` so the UI can say so
(visible, never silent).

A slot whose ``track_id`` has no matching pool row is an "orphan": it
exports as a metadata-less ExportTrack and surfaces in the unresolved
list — never silently dropped (exec summary §10).
"""

from dataclasses import dataclass
from typing import Literal

from app.models.set import Set
from app.models.set_pool import SetPoolTrack

ExportSource = Literal["timeline", "pool"]

_TIDAL_PREFIX = "tidal:"


@dataclass(frozen=True)
class ExportTrack:
    """One ordered entry of the exportable setlist."""

    position: int
    title: str
    artist: str
    album: str | None = None
    genre: str | None = None
    bpm: float | None = None
    key: str | None = None
    camelot: str | None = None
    isrc: str | None = None
    duration_sec: int | None = None
    track_id: str | None = None  # namespaced pool/slot id, e.g. "tidal:123"

    @property
    def tidal_id(self) -> str | None:
        """Tidal track id when the namespaced id is a Tidal one."""
        if self.track_id and self.track_id.startswith(_TIDAL_PREFIX):
            return self.track_id[len(_TIDAL_PREFIX) :]
        return None

    @property
    def has_metadata(self) -> bool:
        """True when the track carries enough text metadata to export."""
        return bool(self.title and self.artist)


def _from_pool_track(position: int, pt: SetPoolTrack) -> ExportTrack:
    return ExportTrack(
        position=position,
        title=pt.title,
        artist=pt.artist,
        album=pt.album,
        genre=pt.genre,
        bpm=pt.bpm,
        key=pt.key,
        camelot=pt.camelot,
        isrc=pt.isrc,
        duration_sec=pt.duration_sec,
        track_id=pt.track_id,
    )


def collect_export_tracks(set_obj: Set) -> tuple[ExportSource, list[ExportTrack]]:
    """Ordered exportable tracklist for a set.

    Timeline slots (sorted by position) joined to pool metadata when any
    non-empty slots exist; otherwise the pool in insertion order.
    """
    slots = sorted(
        (s for s in set_obj.slots if s.track_id), key=lambda s: s.position
    )
    if slots:
        pool_by_tid = {pt.track_id: pt for pt in set_obj.pool_tracks if pt.track_id}
        tracks: list[ExportTrack] = []
        for idx, slot in enumerate(slots):
            pt = pool_by_tid.get(slot.track_id)
            if pt is not None:
                tracks.append(_from_pool_track(idx, pt))
            else:  # orphan slot — keep it visible, never drop
                tracks.append(
                    ExportTrack(position=idx, title="", artist="", track_id=slot.track_id)
                )
        return "timeline", tracks

    pool = sorted(set_obj.pool_tracks, key=lambda pt: pt.id)
    return "pool", [_from_pool_track(idx, pt) for idx, pt in enumerate(pool)]
```

- [ ] **Step 4: Run tests, verify pass** — same pytest command → all `TestCollectExportTracks` + `TestExportTrack` pass.
- [ ] **Step 5: Lint + format + commit**

```bash
cd /home/adam/github/WrzDJ/.worktrees/feat/issue-396/server
/home/adam/github/WrzDJ/server/.venv/bin/ruff format app/services/setbuilder/export_common.py tests/test_setbuilder_export_service.py
/home/adam/github/WrzDJ/server/.venv/bin/ruff check app/services/setbuilder/export_common.py tests/test_setbuilder_export_service.py
cd .. && git add server/app/services/setbuilder/export_common.py server/tests/test_setbuilder_export_service.py
git commit -m "feat(setbuilder): export tracklist collection — timeline slots with pool fallback (#396)"
```

---

### Task 2: `export_files.py` — Rekordbox XML / M3U / txt renderers

**Files:**
- Create: `server/app/services/setbuilder/export_files.py`
- Test: append to `server/tests/test_setbuilder_export_service.py`

- [ ] **Step 1: Write failing tests** (append)

```python
import xml.etree.ElementTree as ET

from app.services.setbuilder.export_files import (
    file_unresolved,
    render_m3u,
    render_rekordbox_xml,
    render_txt,
    safe_filename,
)

TRACKS = [
    ExportTrack(
        position=0, title="Opener", artist="DJ One", album="LP", genre="House",
        bpm=124.0, camelot="8A", duration_sec=210, track_id="tidal:1",
    ),
    ExportTrack(position=1, title='Peak "Time"', artist="A & B", bpm=128.5, key="Am"),
]


class TestRekordboxXml:
    def test_dj_playlists_schema_round_trip(self):
        xml = render_rekordbox_xml("Friday Night", TRACKS)
        root = ET.fromstring(xml)
        assert root.tag == "DJ_PLAYLISTS"
        assert root.attrib["Version"] == "1.0.0"
        coll = root.find("COLLECTION")
        assert coll.attrib["Entries"] == "2"
        entries = coll.findall("TRACK")
        assert entries[0].attrib["Name"] == "Opener"
        assert entries[0].attrib["Artist"] == "DJ One"
        assert entries[0].attrib["AverageBpm"] == "124.00"
        assert entries[0].attrib["Tonality"] == "8A"
        assert entries[0].attrib["TotalTime"] == "210"
        assert entries[0].attrib["Location"].startswith("file://localhost/")
        # playlist node references collection keys in order
        node = root.find("PLAYLISTS/NODE/NODE")
        assert node.attrib["Name"] == "Friday Night"
        assert [t.attrib["Key"] for t in node.findall("TRACK")] == ["1", "2"]

    def test_escapes_special_chars(self):
        xml = render_rekordbox_xml("Friday Night", TRACKS)
        root = ET.fromstring(xml)  # parse fails if escaping is broken
        assert root.find("COLLECTION/TRACK[2]").attrib["Name"] == 'Peak "Time"'


class TestM3u:
    def test_extm3u_with_extinf_metadata(self):
        m3u = render_m3u("Friday Night", TRACKS)
        lines = m3u.splitlines()
        assert lines[0] == "#EXTM3U"
        assert lines[1] == "#PLAYLIST:Friday Night"
        assert lines[2] == "#EXTINF:210,DJ One - Opener"
        assert lines[3] == "DJ One - Opener.mp3"
        assert lines[4] == '#EXTINF:-1,A & B - Peak "Time"'

    def test_path_line_strips_separators(self):
        m3u = render_m3u("x", [ExportTrack(position=0, title="a/b\\c", artist="d")])
        assert "a-b-c" in m3u.splitlines()[3]


class TestTxt:
    def test_numbered_plaintext(self):
        txt = render_txt("Friday Night", TRACKS)
        lines = txt.splitlines()
        assert lines[0] == "Friday Night"
        assert lines[2] == "1. DJ One - Opener"
        assert lines[3] == '2. A & B - Peak "Time"'


class TestFileHelpers:
    def test_file_unresolved_flags_metadata_less_tracks(self):
        orphan = ExportTrack(position=2, title="", artist="", track_id="beatport:9")
        assert file_unresolved([*TRACKS, orphan]) == [orphan]

    def test_safe_filename(self):
        assert safe_filename('Fri/day: "Night"', "xml") == "Friday Night.xml"
        assert safe_filename("???", "m3u8") == "set.m3u8"
```

- [ ] **Step 2: Run, verify ImportError** (same pytest command).
- [ ] **Step 3: Implement** `server/app/services/setbuilder/export_files.py`

```python
"""File-format renderers for WrzDJSet export (issue #396) — stdlib only.

Rekordbox XML (DJ_PLAYLISTS 1.0.0): server can't know local audio paths,
so ``Location`` is a synthetic ``file://localhost/WrzDJ/...`` placeholder;
rekordbox imports the playlist + metadata and the DJ relinks files. M3U
uses #EXTINF metadata with a path-less "Artist - Title.mp3" line. For all
file formats "unresolved" = missing title/artist (orphan timeline slots);
pool-backed tracks always have both (NOT NULL columns).
"""

import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

from app.services.setbuilder.export_common import ExportTrack

_FILENAME_KEEP = re.compile(r"[^A-Za-z0-9 _\-]")


def file_unresolved(tracks: list[ExportTrack]) -> list[ExportTrack]:
    """Tracks that can't be represented in a metadata file export."""
    return [t for t in tracks if not t.has_metadata]


def safe_filename(name: str, ext: str) -> str:
    """Sanitized ASCII download filename with extension."""
    cleaned = _FILENAME_KEEP.sub("", name).strip()
    return f"{cleaned or 'set'}.{ext}"


def _display(track: ExportTrack) -> str:
    return f"{track.artist} - {track.title}"


def _placeholder_location(track: ExportTrack) -> str:
    """Synthetic rekordbox Location (no real path is knowable server-side)."""
    return "file://localhost/WrzDJ/" + quote(f"{_display(track)}.mp3")


def render_rekordbox_xml(set_name: str, tracks: list[ExportTrack]) -> str:
    """Rekordbox DJ_PLAYLISTS XML: COLLECTION entries + one playlist node."""
    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    ET.SubElement(root, "PRODUCT", Name="WrzDJ", Version="1.0.0", Company="WrzDJ")
    collection = ET.SubElement(root, "COLLECTION", Entries=str(len(tracks)))
    for idx, track in enumerate(tracks, start=1):
        attrs: dict[str, str] = {
            "TrackID": str(idx),
            "Name": track.title,
            "Artist": track.artist,
            "Kind": "MP3 File",
            "Location": _placeholder_location(track),
        }
        if track.album:
            attrs["Album"] = track.album
        if track.genre:
            attrs["Genre"] = track.genre
        if track.duration_sec:
            attrs["TotalTime"] = str(track.duration_sec)
        if track.bpm:
            attrs["AverageBpm"] = f"{track.bpm:.2f}"
        tonality = track.key or track.camelot
        if tonality:
            attrs["Tonality"] = tonality
        ET.SubElement(collection, "TRACK", attrs)

    playlists = ET.SubElement(root, "PLAYLISTS")
    root_node = ET.SubElement(playlists, "NODE", Type="0", Name="ROOT", Count="1")
    node = ET.SubElement(
        root_node, "NODE", Name=set_name, Type="1", KeyType="0", Entries=str(len(tracks))
    )
    for idx in range(1, len(tracks) + 1):
        ET.SubElement(node, "TRACK", Key=str(idx))

    body = ET.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'


def _path_line(track: ExportTrack) -> str:
    name = _display(track).replace("/", "-").replace("\\", "-")
    return f"{name}.mp3"


def render_m3u(set_name: str, tracks: list[ExportTrack]) -> str:
    """Extended M3U (UTF-8 / .m3u8) with #EXTINF metadata lines."""
    lines = ["#EXTM3U", f"#PLAYLIST:{set_name}"]
    for track in tracks:
        duration = track.duration_sec if track.duration_sec else -1
        lines.append(f"#EXTINF:{duration},{_display(track)}")
        lines.append(_path_line(track))
    return "\n".join(lines) + "\n"


def render_txt(set_name: str, tracks: list[ExportTrack]) -> str:
    """Numbered plaintext setlist."""
    lines = [set_name, ""]
    lines.extend(f"{idx}. {_display(t)}" for idx, t in enumerate(tracks, start=1))
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run tests, verify pass.**
- [ ] **Step 5: ruff format/check + commit** — `feat(setbuilder): Rekordbox XML, M3U and plaintext setlist renderers (#396)`

---

### Task 3: `export_tidal.py` — resolution + playlist export

**Files:**
- Create: `server/app/services/setbuilder/export_tidal.py`
- Test: append to `server/tests/test_setbuilder_export_service.py`

- [ ] **Step 1: Write failing tests** (append). Mocks live at the process edge: monkeypatch `app.services.tidal` functions (the module export_tidal imports as `tidal_service`).

```python
from types import SimpleNamespace

import pytest

from app.services.setbuilder import export_tidal


def _result(track_id: str, title: str, artist: str):
    """Minimal stand-in for tidal.TidalSearchResult."""
    return SimpleNamespace(track_id=track_id, title=title, artist=artist)


class TestResolveForTidal:
    def test_namespaced_tidal_id_resolves_without_api_calls(self, db, test_user, monkeypatch):
        def boom(*a, **kw):  # any API call is a test failure
            raise AssertionError("unexpected Tidal API call")

        monkeypatch.setattr("app.services.tidal.search_tidal_by_isrc", boom)
        monkeypatch.setattr("app.services.tidal.search_tidal_tracks", boom)
        tracks = [ExportTrack(position=0, title="T", artist="A", track_id="tidal:77")]
        resolved, unresolved = export_tidal.resolve_for_tidal(db, test_user, tracks)
        assert [(t.position, tid) for t, tid in resolved] == [(0, "77")]
        assert unresolved == []

    def test_isrc_exact_match_wins_over_search(self, db, test_user, monkeypatch):
        monkeypatch.setattr(
            "app.services.tidal.search_tidal_by_isrc",
            lambda db_, u, isrc: _result("55", "T", "A"),
        )
        monkeypatch.setattr(
            "app.services.tidal.search_tidal_tracks",
            lambda *a, **kw: (_ for _ in ()).throw(AssertionError("search not expected")),
        )
        tracks = [ExportTrack(position=0, title="T", artist="A", isrc="USX9P1234567")]
        resolved, unresolved = export_tidal.resolve_for_tidal(db, test_user, tracks)
        assert resolved[0][1] == "55"

    def test_fuzzy_search_resolves_above_threshold(self, db, test_user, monkeypatch):
        monkeypatch.setattr("app.services.tidal.search_tidal_by_isrc", lambda *a: None)
        monkeypatch.setattr(
            "app.services.tidal.search_tidal_tracks",
            lambda db_, u, q, limit=10: [_result("31", "Strobe", "deadmau5")],
        )
        tracks = [ExportTrack(position=0, title="Strobe", artist="deadmau5")]
        resolved, unresolved = export_tidal.resolve_for_tidal(db, test_user, tracks)
        assert resolved[0][1] == "31"

    def test_no_match_is_unresolved_not_dropped(self, db, test_user, monkeypatch):
        monkeypatch.setattr("app.services.tidal.search_tidal_by_isrc", lambda *a: None)
        monkeypatch.setattr(
            "app.services.tidal.search_tidal_tracks",
            lambda db_, u, q, limit=10: [_result("9", "Totally Different", "Nobody")],
        )
        tracks = [ExportTrack(position=0, title="Strobe", artist="deadmau5")]
        resolved, unresolved = export_tidal.resolve_for_tidal(db, test_user, tracks)
        assert resolved == []
        assert unresolved == tracks

    def test_unwanted_versions_filtered(self, db, test_user, monkeypatch):
        monkeypatch.setattr("app.services.tidal.search_tidal_by_isrc", lambda *a: None)
        monkeypatch.setattr(
            "app.services.tidal.search_tidal_tracks",
            lambda db_, u, q, limit=10: [_result("12", "Strobe (Karaoke Version)", "deadmau5")],
        )
        tracks = [ExportTrack(position=0, title="Strobe", artist="deadmau5")]
        resolved, unresolved = export_tidal.resolve_for_tidal(db, test_user, tracks)
        assert resolved == []
        assert unresolved == tracks

    def test_orphan_track_unresolved_without_search(self, db, test_user, monkeypatch):
        def boom(*a, **kw):
            raise AssertionError("unexpected Tidal API call")

        monkeypatch.setattr("app.services.tidal.search_tidal_tracks", boom)
        tracks = [ExportTrack(position=0, title="", artist="", track_id="beatport:9")]
        resolved, unresolved = export_tidal.resolve_for_tidal(db, test_user, tracks)
        assert resolved == []
        assert unresolved == tracks


class TestExportToTidal:
    def _fake_session(self, created: list):
        def create_playlist(name, description):
            created.append((name, description))
            return SimpleNamespace(id="pl-uuid-1")

        return SimpleNamespace(user=SimpleNamespace(create_playlist=create_playlist))

    def test_creates_playlist_adds_tracks_and_marks_exported(
        self, db, test_user, monkeypatch
    ):
        s = _mk_set(db, test_user)
        created: list = []
        monkeypatch.setattr(
            "app.services.tidal.get_tidal_session", lambda db_, u: self._fake_session(created)
        )
        added: dict = {}
        def fake_add(db_, u, playlist_id, track_ids):
            added["playlist_id"], added["track_ids"] = playlist_id, track_ids
            return True

        monkeypatch.setattr("app.services.tidal.add_tracks_to_playlist", fake_add)
        track = ExportTrack(position=0, title="T", artist="A", track_id="tidal:77")
        outcome = export_tidal.export_to_tidal(db, test_user, s, [(track, "77")])
        assert created == [("WrzDJ Set: Friday Night", "Exported from WrzDJ Set Builder")]
        assert added == {"playlist_id": "pl-uuid-1", "track_ids": ["77"]}
        assert outcome.playlist_id == "pl-uuid-1"
        assert outcome.added == 1
        db.refresh(s)
        assert s.status == "exported"
        assert s.tidal_playlist_id == "pl-uuid-1"
        assert s.exported_at is not None

    def test_no_session_raises_not_connected(self, db, test_user, monkeypatch):
        s = _mk_set(db, test_user)
        monkeypatch.setattr("app.services.tidal.get_tidal_session", lambda db_, u: None)
        with pytest.raises(export_tidal.TidalNotConnected):
            export_tidal.export_to_tidal(
                db, test_user, s, [(ExportTrack(position=0, title="T", artist="A"), "1")]
            )
        db.refresh(s)
        assert s.status == "draft"

    def test_add_failure_raises_and_does_not_mark_exported(self, db, test_user, monkeypatch):
        s = _mk_set(db, test_user)
        monkeypatch.setattr(
            "app.services.tidal.get_tidal_session", lambda db_, u: self._fake_session([])
        )
        monkeypatch.setattr(
            "app.services.tidal.add_tracks_to_playlist", lambda *a, **kw: False
        )
        with pytest.raises(export_tidal.TidalExportError):
            export_tidal.export_to_tidal(
                db, test_user, s, [(ExportTrack(position=0, title="T", artist="A"), "1")]
            )
        db.refresh(s)
        assert s.status == "draft"
        assert s.tidal_playlist_id is None
```

- [ ] **Step 2: Run, verify ImportError.**
- [ ] **Step 3: Implement** `server/app/services/setbuilder/export_tidal.py`

```python
"""Tidal setlist export (issue #396).

Follows the sync-adapter precedent (services/sync/tidal_adapter.py): the
DJ's existing Tidal OAuth session, fuzzy scoring (title*0.7 + artist*0.3,
threshold 0.5) with unwanted-version filtering, and one batched
add_tracks_to_playlist call.

Resolution cascade per track: namespaced ``tidal:`` id → ISRC exact lookup
→ fuzzy search. Unresolved tracks are returned to the caller — the API
layer interrupts the export (409) unless the DJ explicitly skips them.

Each export creates a *fresh* playlist ("WrzDJ Set: <name>") and stores its
id on the set: reusing an old playlist risks clobbering DJ edits, and
appending to one breaks setlist order.
"""

import logging

from sqlalchemy.orm import Session

from app.core.time import utcnow
from app.models.set import Set
from app.models.user import User
from app.services import tidal as tidal_service
from app.services.setbuilder.export_common import ExportTrack
from app.services.track_normalizer import fuzzy_match_score
from app.services.version_filter import is_unwanted_version

logger = logging.getLogger(__name__)

MATCH_THRESHOLD = 0.5
PLAYLIST_DESCRIPTION = "Exported from WrzDJ Set Builder"


class TidalNotConnected(Exception):
    """The DJ has no usable Tidal session."""


class TidalExportError(Exception):
    """Tidal API failure while creating or filling the playlist."""


from dataclasses import dataclass


@dataclass(frozen=True)
class TidalExportOutcome:
    playlist_id: str
    playlist_url: str
    added: int


def _fuzzy_resolve(db: Session, user: User, track: ExportTrack) -> str | None:
    candidates = tidal_service.search_tidal_tracks(
        db, user, f"{track.artist} {track.title}", limit=10
    )
    best_id: str | None = None
    best_score = 0.0
    for candidate in candidates:
        if is_unwanted_version(candidate.title, None):
            continue
        score = (
            fuzzy_match_score(track.title, candidate.title) * 0.7
            + fuzzy_match_score(track.artist, candidate.artist) * 0.3
        )
        if score > best_score and score >= MATCH_THRESHOLD:
            best_score = score
            best_id = candidate.track_id
    return best_id


def resolve_for_tidal(
    db: Session, user: User, tracks: list[ExportTrack]
) -> tuple[list[tuple[ExportTrack, str]], list[ExportTrack]]:
    """Split tracks into (track, tidal_id) matches and unresolved tracks."""
    resolved: list[tuple[ExportTrack, str]] = []
    unresolved: list[ExportTrack] = []
    for track in tracks:
        if track.tidal_id:
            resolved.append((track, track.tidal_id))
            continue
        if not track.has_metadata:
            unresolved.append(track)
            continue
        if track.isrc:
            hit = tidal_service.search_tidal_by_isrc(db, user, track.isrc)
            if hit is not None:
                resolved.append((track, hit.track_id))
                continue
        match_id = _fuzzy_resolve(db, user, track)
        if match_id is not None:
            resolved.append((track, match_id))
        else:
            unresolved.append(track)
    return resolved, unresolved


def export_to_tidal(
    db: Session,
    user: User,
    set_obj: Set,
    resolved: list[tuple[ExportTrack, str]],
) -> TidalExportOutcome:
    """Create a fresh Tidal playlist, batch-add tracks, mark the set exported."""
    session = tidal_service.get_tidal_session(db, user)
    if session is None:
        raise TidalNotConnected

    try:
        playlist = session.user.create_playlist(
            f"WrzDJ Set: {set_obj.name}", PLAYLIST_DESCRIPTION
        )
        playlist_id = str(playlist.id)
    except Exception as e:  # tidalapi raises broad exceptions
        logger.error("Tidal playlist creation failed: %s: %s", type(e).__name__, e)
        raise TidalExportError("Couldn't create the Tidal playlist") from e

    track_ids = [tid for _, tid in resolved]
    if not tidal_service.add_tracks_to_playlist(db, user, playlist_id, track_ids):
        raise TidalExportError("Couldn't add tracks to the Tidal playlist")

    set_obj.tidal_playlist_id = playlist_id
    set_obj.exported_at = utcnow()
    set_obj.status = "exported"
    db.commit()

    logger.info("Exported set %s to Tidal playlist %s", set_obj.id, playlist_id)
    return TidalExportOutcome(
        playlist_id=playlist_id,
        playlist_url=f"https://tidal.com/browse/playlist/{playlist_id}",
        added=len(track_ids),
    )
```

(Move the `from dataclasses import dataclass` import to the top import block — shown inline above only for plan readability.)

- [ ] **Step 4: Run tests, verify pass.** Confirm `fuzzy_match_score` and `is_unwanted_version` signatures by reading `server/app/services/track_normalizer.py` / `version_filter.py` first; adjust the call if `is_unwanted_version` needs different args (mirror `tidal_adapter.py` usage exactly).
- [ ] **Step 5: ruff format/check + commit** — `feat(setbuilder): Tidal export service — 3-stage resolution + fresh playlist per export (#396)`

---

### Task 4: schemas + API endpoints

**Files:**
- Modify: `server/app/schemas/setbuilder.py` (append)
- Modify: `server/app/api/setbuilder.py` (append)
- Test: `server/tests/test_setbuilder_export_api.py`

- [ ] **Step 1: Write failing API tests** (`server/tests/test_setbuilder_export_api.py`)

```python
"""API-boundary tests for WrzDJSet export endpoints (issue #396)."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack


@pytest.fixture
def set_id(client: TestClient, auth_headers: dict) -> int:
    resp = client.post("/api/setbuilder/sets", json={"name": "Export Set"}, headers=auth_headers)
    assert resp.status_code == 201
    return resp.json()["id"]


def _seed_pool(db: Session, set_id: int, *, with_orphan_slot: bool = False) -> None:
    src = SetPoolSource(set_id=set_id, kind="manual", label="Manual")
    db.add(src)
    db.commit()
    db.add_all(
        [
            SetPoolTrack(
                set_id=set_id, source_id=src.id, title="Opener", artist="DJ One",
                track_id="tidal:101", duration_sec=200, bpm=124.0, camelot="8A",
                dedupe_sig="sig1",
            ),
            SetPoolTrack(
                set_id=set_id, source_id=src.id, title="Closer", artist="DJ Two",
                track_id="beatport:202", dedupe_sig="sig2",
            ),
        ]
    )
    if with_orphan_slot:
        db.add(SetSlot(set_id=set_id, position=0, track_id="tidal:101"))
        db.add(SetSlot(set_id=set_id, position=1, track_id="spotify:gone"))
    db.commit()


def _connect_tidal(db: Session, test_user) -> None:
    test_user.tidal_access_token = "tok"  # nosec B105 — test fixture
    db.commit()


class TestPreflight:
    def test_owner_scoping_404(self, client, auth_headers):
        resp = client.post(
            "/api/setbuilder/sets/99999/export/preflight",
            json={"target": "m3u"},
            headers=auth_headers,
        )
        assert resp.status_code == 404

    def test_requires_auth(self, client, set_id):
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/preflight", json={"target": "m3u"}
        )
        assert resp.status_code == 401

    def test_file_target_reports_pool_fallback_and_no_unresolved(
        self, client, auth_headers, db, set_id
    ):
        _seed_pool(db, set_id)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/preflight",
            json={"target": "rekordbox"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["source"] == "pool"
        assert body["total"] == 2
        assert body["resolved_count"] == 2
        assert body["unresolved"] == []

    def test_file_target_flags_orphan_slots(self, client, auth_headers, db, set_id):
        _seed_pool(db, set_id, with_orphan_slot=True)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/preflight",
            json={"target": "m3u"},
            headers=auth_headers,
        )
        body = resp.json()
        assert body["source"] == "timeline"
        assert body["total"] == 2
        assert body["resolved_count"] == 1
        assert body["unresolved"][0]["track_id"] == "spotify:gone"
        assert body["unresolved"][0]["reason"] == "missing_metadata"

    def test_tidal_target_not_connected(self, client, auth_headers, db, set_id):
        _seed_pool(db, set_id)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/preflight",
            json={"target": "tidal"},
            headers=auth_headers,
        )
        body = resp.json()
        assert body["tidal_connected"] is False
        assert body["resolved_count"] == 0

    def test_tidal_target_resolves_and_lists_unresolved(
        self, client, auth_headers, db, set_id, test_user, monkeypatch
    ):
        _seed_pool(db, set_id)
        _connect_tidal(db, test_user)
        monkeypatch.setattr("app.services.tidal.search_tidal_by_isrc", lambda *a: None)
        monkeypatch.setattr(
            "app.services.tidal.search_tidal_tracks", lambda db_, u, q, limit=10: []
        )
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/preflight",
            json={"target": "tidal"},
            headers=auth_headers,
        )
        body = resp.json()
        assert body["tidal_connected"] is True
        assert body["resolved_count"] == 1  # the tidal:101 track
        assert body["unresolved"][0]["title"] == "Closer"
        assert body["unresolved"][0]["reason"] == "no_tidal_match"


class TestTidalExport:
    def _fake_session(self):
        return SimpleNamespace(
            user=SimpleNamespace(
                create_playlist=lambda name, desc: SimpleNamespace(id="pl-1")
            )
        )

    def test_unresolved_interrupts_with_409(
        self, client, auth_headers, db, set_id, test_user, monkeypatch
    ):
        _seed_pool(db, set_id)
        _connect_tidal(db, test_user)
        monkeypatch.setattr("app.services.tidal.search_tidal_by_isrc", lambda *a: None)
        monkeypatch.setattr(
            "app.services.tidal.search_tidal_tracks", lambda db_, u, q, limit=10: []
        )
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/tidal",
            json={"skip_unresolved": False},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert detail["code"] == "unresolved_tracks"
        assert detail["unresolved"][0]["title"] == "Closer"
        db.expire_all()
        assert db.get(Set, set_id).status == "draft"

    def test_skip_unresolved_exports_resolved_only(
        self, client, auth_headers, db, set_id, test_user, monkeypatch
    ):
        _seed_pool(db, set_id)
        _connect_tidal(db, test_user)
        monkeypatch.setattr("app.services.tidal.search_tidal_by_isrc", lambda *a: None)
        monkeypatch.setattr(
            "app.services.tidal.search_tidal_tracks", lambda db_, u, q, limit=10: []
        )
        monkeypatch.setattr(
            "app.services.tidal.get_tidal_session", lambda db_, u: self._fake_session()
        )
        calls = {}
        def fake_add(db_, u, playlist_id, track_ids):
            calls["track_ids"] = track_ids
            return True

        monkeypatch.setattr("app.services.tidal.add_tracks_to_playlist", fake_add)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/tidal",
            json={"skip_unresolved": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["playlist_id"] == "pl-1"
        assert body["added"] == 1
        assert body["skipped"] == 1
        assert body["status"] == "exported"
        assert calls["track_ids"] == ["101"]
        db.expire_all()
        s = db.get(Set, set_id)
        assert s.status == "exported"
        assert s.tidal_playlist_id == "pl-1"

    def test_not_connected_400(self, client, auth_headers, db, set_id):
        _seed_pool(db, set_id)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/tidal",
            json={"skip_unresolved": True},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_empty_set_400(self, client, auth_headers, db, set_id, test_user):
        _connect_tidal(db, test_user)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/tidal",
            json={"skip_unresolved": False},
            headers=auth_headers,
        )
        assert resp.status_code == 400


class TestFileExport:
    def test_rekordbox_download(self, client, auth_headers, db, set_id):
        _seed_pool(db, set_id)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/file",
            json={"format": "rekordbox", "skip_unresolved": False},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/xml")
        assert 'filename="Export Set.xml"' in resp.headers["content-disposition"]
        assert "DJ_PLAYLISTS" in resp.text

    def test_m3u_and_txt_downloads(self, client, auth_headers, db, set_id):
        _seed_pool(db, set_id)
        m3u = client.post(
            f"/api/setbuilder/sets/{set_id}/export/file",
            json={"format": "m3u", "skip_unresolved": False},
            headers=auth_headers,
        )
        assert m3u.status_code == 200
        assert m3u.text.startswith("#EXTM3U")
        assert 'filename="Export Set.m3u8"' in m3u.headers["content-disposition"]
        txt = client.post(
            f"/api/setbuilder/sets/{set_id}/export/file",
            json={"format": "txt", "skip_unresolved": False},
            headers=auth_headers,
        )
        assert txt.status_code == 200
        assert "1. DJ One - Opener" in txt.text

    def test_unresolved_interrupts_with_409_then_skip_succeeds(
        self, client, auth_headers, db, set_id
    ):
        _seed_pool(db, set_id, with_orphan_slot=True)
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/file",
            json={"format": "m3u", "skip_unresolved": False},
            headers=auth_headers,
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "unresolved_tracks"
        resp2 = client.post(
            f"/api/setbuilder/sets/{set_id}/export/file",
            json={"format": "m3u", "skip_unresolved": True},
            headers=auth_headers,
        )
        assert resp2.status_code == 200
        assert "DJ One - Opener" in resp2.text
        assert "spotify:gone" not in resp2.text

    def test_file_export_does_not_mutate_status(self, client, auth_headers, db, set_id):
        _seed_pool(db, set_id)
        client.post(
            f"/api/setbuilder/sets/{set_id}/export/file",
            json={"format": "txt", "skip_unresolved": False},
            headers=auth_headers,
        )
        db.expire_all()
        assert db.get(Set, set_id).status == "draft"

    def test_empty_set_400(self, client, auth_headers, set_id):
        resp = client.post(
            f"/api/setbuilder/sets/{set_id}/export/file",
            json={"format": "txt", "skip_unresolved": False},
            headers=auth_headers,
        )
        assert resp.status_code == 400
```

- [ ] **Step 2: Run, verify 404/422 failures** (endpoints missing).
- [ ] **Step 3: Append schemas** to `server/app/schemas/setbuilder.py`

```python
# ---------------------------------------------------------------------------
# Export (issue #396)


ExportTarget = Literal["tidal", "rekordbox", "m3u", "txt"]
ExportFileFormat = Literal["rekordbox", "m3u", "txt"]


class ExportPreflightIn(BaseModel):
    """Body for the pre-export resolution check."""

    target: ExportTarget


class UnresolvedTrackOut(BaseModel):
    """One track that can't be exported to the chosen target."""

    position: int
    title: str
    artist: str
    track_id: str | None
    reason: Literal["no_tidal_match", "missing_metadata"]


class ExportPreflightOut(BaseModel):
    """Resolution summary the DJ confirms before exporting."""

    target: ExportTarget
    source: Literal["timeline", "pool"]
    total: int
    resolved_count: int
    unresolved: list[UnresolvedTrackOut]
    # Only set for target="tidal"; None for file targets.
    tidal_connected: bool | None = None


class ExportTidalIn(BaseModel):
    """Body for the Tidal export. skip_unresolved is the DJ's explicit choice."""

    skip_unresolved: bool = False


class ExportTidalOut(BaseModel):
    """Successful Tidal export result."""

    playlist_id: str
    playlist_url: str
    added: int
    skipped: int
    exported_at: datetime
    status: Literal["draft", "locked", "exported"]


class ExportFileIn(BaseModel):
    """Body for the file (Rekordbox XML / M3U / txt) export."""

    format: ExportFileFormat
    skip_unresolved: bool = False
```

- [ ] **Step 4: Append endpoints** to `server/app/api/setbuilder.py` (add imports: `Response` from fastapi, the new schemas, `export_common`, `export_files`, `export_tidal`)

```python
# ---------------------------------------------------------------------------
# Export (issue #396) — preflight resolution check + Tidal / file exports.
# The unresolved-track interrupt is enforced server-side: exports return 409
# unless the DJ explicitly opted to skip (never silently dropped).


def _unresolved_out(tracks: list, reason: str) -> list[UnresolvedTrackOut]:
    return [
        UnresolvedTrackOut(
            position=t.position, title=t.title, artist=t.artist, track_id=t.track_id,
            reason=reason,
        )
        for t in tracks
    ]


def _unresolved_409(unresolved: list[UnresolvedTrackOut]) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "unresolved_tracks",
            "unresolved": [u.model_dump() for u in unresolved],
        },
    )


@router.post("/sets/{set_id}/export/preflight", response_model=ExportPreflightOut)
@limiter.limit("5/minute")
def export_preflight(
    set_id: int,
    payload: ExportPreflightIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ExportPreflightOut:
    """Pre-export resolution check (tidal targets do live Tidal matching)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    source, tracks = export_common.collect_export_tracks(set_obj)

    if payload.target == "tidal":
        connected = bool(current_user.tidal_access_token)
        if not connected:
            return ExportPreflightOut(
                target=payload.target, source=source, total=len(tracks),
                resolved_count=0, unresolved=[], tidal_connected=False,
            )
        resolved, unresolved = export_tidal.resolve_for_tidal(db, current_user, tracks)
        return ExportPreflightOut(
            target=payload.target, source=source, total=len(tracks),
            resolved_count=len(resolved),
            unresolved=_unresolved_out(unresolved, "no_tidal_match"),
            tidal_connected=True,
        )

    unresolved = export_files.file_unresolved(tracks)
    return ExportPreflightOut(
        target=payload.target, source=source, total=len(tracks),
        resolved_count=len(tracks) - len(unresolved),
        unresolved=_unresolved_out(unresolved, "missing_metadata"),
    )


@router.post("/sets/{set_id}/export/tidal", response_model=ExportTidalOut)
@limiter.limit("5/minute")
def export_set_tidal(
    set_id: int,
    payload: ExportTidalIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> ExportTidalOut:
    """Export the setlist to a fresh Tidal playlist (DJ's existing OAuth)."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    if not current_user.tidal_access_token:
        raise HTTPException(status_code=400, detail="Tidal account not connected")
    _, tracks = export_common.collect_export_tracks(set_obj)
    if not tracks:
        raise HTTPException(status_code=400, detail="Set has no tracks to export")

    resolved, unresolved = export_tidal.resolve_for_tidal(db, current_user, tracks)
    if unresolved and not payload.skip_unresolved:
        raise _unresolved_409(_unresolved_out(unresolved, "no_tidal_match"))
    if not resolved:
        raise HTTPException(status_code=400, detail="No resolvable tracks to export")

    try:
        outcome = export_tidal.export_to_tidal(db, current_user, set_obj, resolved)
    except export_tidal.TidalNotConnected:
        raise HTTPException(status_code=400, detail="Tidal account not connected") from None
    except export_tidal.TidalExportError:
        raise HTTPException(status_code=502, detail="Tidal export failed") from None

    return ExportTidalOut(
        playlist_id=outcome.playlist_id,
        playlist_url=outcome.playlist_url,
        added=outcome.added,
        skipped=len(unresolved),
        exported_at=set_obj.exported_at,
        status=set_obj.status,
    )


_FILE_MEDIA = {
    "rekordbox": ("application/xml", "xml"),
    "m3u": ("audio/x-mpegurl", "m3u8"),
    "txt": ("text/plain", "txt"),
}


@router.post("/sets/{set_id}/export/file")
@limiter.limit("10/minute")
def export_set_file(
    set_id: int,
    payload: ExportFileIn,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Response:
    """Download the setlist as Rekordbox XML, M3U8, or plaintext."""
    set_obj = _get_owned_or_404(db, set_id, current_user)
    _, tracks = export_common.collect_export_tracks(set_obj)
    if not tracks:
        raise HTTPException(status_code=400, detail="Set has no tracks to export")

    unresolved = export_files.file_unresolved(tracks)
    if unresolved and not payload.skip_unresolved:
        raise _unresolved_409(_unresolved_out(unresolved, "missing_metadata"))
    exportable = [t for t in tracks if t.has_metadata]

    if payload.format == "rekordbox":
        content = export_files.render_rekordbox_xml(set_obj.name, exportable)
    elif payload.format == "m3u":
        content = export_files.render_m3u(set_obj.name, exportable)
    else:
        content = export_files.render_txt(set_obj.name, exportable)

    media_type, ext = _FILE_MEDIA[payload.format]
    filename = export_files.safe_filename(set_obj.name, ext)
    return Response(
        content=content,
        media_type=f"{media_type}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 5: Run the full export test files + the whole suite** — both export test files green, then `/home/adam/github/WrzDJ/server/.venv/bin/pytest --tb=short -q` (coverage gate included).
- [ ] **Step 6: ruff format/check + bandit + commit** — `feat(setbuilder): export endpoints — preflight check, Tidal, Rekordbox XML, M3U/txt (#396)`

---

### Task 5: OpenAPI regen + frontend API client

**Files:**
- Regenerate: `server/openapi.json`, `dashboard/lib/api-types.generated.ts` (via `npm run types:export && npm run types:generate` — use `/home/adam/github/WrzDJ/server/.venv/bin/python scripts/export_openapi.py` since the worktree has no own venv; check how `types:export` resolves the venv path and run the underlying command manually if needed)
- Modify: `dashboard/lib/api-types.ts` (append export types)
- Modify: `dashboard/lib/api.ts` (append methods to ApiClient)

- [ ] **Step 1: Append types** to `dashboard/lib/api-types.ts`

```typescript
// --- Setlist export (#396) ---

export type ExportTarget = 'tidal' | 'rekordbox' | 'm3u' | 'txt';
export type ExportFileFormat = 'rekordbox' | 'm3u' | 'txt';

export interface UnresolvedTrack {
  position: number;
  title: string;
  artist: string;
  track_id: string | null;
  reason: 'no_tidal_match' | 'missing_metadata';
}

export interface ExportPreflight {
  target: ExportTarget;
  source: 'timeline' | 'pool';
  total: number;
  resolved_count: number;
  unresolved: UnresolvedTrack[];
  tidal_connected: boolean | null;
}

export interface ExportTidalResult {
  playlist_id: string;
  playlist_url: string;
  added: number;
  skipped: number;
  exported_at: string;
  status: 'draft' | 'locked' | 'exported';
}
```

- [ ] **Step 2: Append ApiClient methods** in `dashboard/lib/api.ts` (next to the other setbuilder methods; import the new types):

```typescript
  // --- Setlist export (#396) ---

  async exportPreflight(setId: number, target: ExportTarget): Promise<ExportPreflight> {
    return this.fetch(`/api/setbuilder/sets/${setId}/export/preflight`, {
      method: 'POST',
      body: JSON.stringify({ target }),
    });
  }

  async exportSetToTidal(setId: number, skipUnresolved: boolean): Promise<ExportTidalResult> {
    return this.fetch(`/api/setbuilder/sets/${setId}/export/tidal`, {
      method: 'POST',
      body: JSON.stringify({ skip_unresolved: skipUnresolved }),
    });
  }

  /**
   * Download a file export. Returns the blob plus the server-suggested
   * filename (falls back to `fallbackName` when Content-Disposition isn't
   * CORS-exposed).
   */
  async exportSetFile(
    setId: number,
    format: ExportFileFormat,
    skipUnresolved: boolean,
    fallbackName: string
  ): Promise<{ blob: Blob; filename: string }> {
    const res = await this.rawFetch(`/api/setbuilder/sets/${setId}/export/file`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ format, skip_unresolved: skipUnresolved }),
    });
    const match = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '');
    return { blob: await res.blob(), filename: match?.[1] ?? fallbackName };
  }
```

- [ ] **Step 3: Regenerate generated types** — from `dashboard/`: run the openapi export with the shared venv python, then `npm run types:generate`. Verify only additive diff in `api-types.generated.ts`.
- [ ] **Step 4: Frontend checks** — `npm run lint && npx tsc --noEmit && npm test -- --run` from `dashboard/`.
- [ ] **Step 5: Commit** — `feat(setbuilder): export API client methods + generated types (#396)`

---

### Task 6: ExportModal + wiring

**Files:**
- Create: `dashboard/app/(dj)/setbuilder/components/ExportModal.tsx`
- Modify: `dashboard/app/(dj)/setbuilder/SetActionsMenu.tsx` (add Export button + modal)
- Modify: `dashboard/app/(dj)/setbuilder/[setId]/page.tsx` (pass `onSetUpdated`)
- Test: `dashboard/app/(dj)/setbuilder/components/__tests__/ExportModal.test.tsx`

Mirror `ImportModal.tsx` for modal structure/styling (read it first). Dark theme, inline styles + `setbuilder.module.css` patterns, no UI framework.

- [ ] **Step 1: Write failing component tests** (`ExportModal.test.tsx`, mirroring `ImportModal.test.tsx` mocking style — `vi.mock('@/lib/api')`):

Cover, with real assertions (adapt selectors to the implemented markup):
1. Renders all 7 platform rows; Tidal / Rekordbox XML / M3U/.txt are enabled; Engine DJ XML, Serato .crate, Spotify, Apple Music are disabled with a "Coming soon" badge.
2. Picking Rekordbox calls `api.exportPreflight(setId, 'rekordbox')`; with `unresolved: []` shows "Download .xml" enabled.
3. Preflight with unresolved tracks renders the unresolved list (title/artist/track_id) and shows "Skip N & export" + "Cancel" — no download button until skip chosen.
4. "Skip N & export" then download calls `api.exportSetFile(setId, 'rekordbox', true, expect.any(String))` and triggers the blob download (mock `URL.createObjectURL`).
5. Cancel from the unresolved interrupt returns to the platform list (export not called).
6. Tidal flow: preflight `tidal_connected: false` → shows "Connect Tidal in your event's Cloud Providers first" and no export button; `tidal_connected: true, unresolved: []` → "Export to Tidal" → `api.exportSetToTidal(setId, false)` → success panel with playlist link and `onSetUpdated` called with `{ status: 'exported', tidal_playlist_id: 'pl-1', exported_at: ... }`.
7. `source: 'pool'` preflight shows the "timeline empty — exporting pool" notice.

- [ ] **Step 2: Run, verify fail.** `npm test -- --run ExportModal`
- [ ] **Step 3: Implement `ExportModal.tsx`.** Component contract:

```typescript
interface ExportModalProps {
  set: SetDetail;
  onClose: () => void;
  /** Patch the page's copy after a Tidal export marks the set exported. */
  onSetUpdated: (patch: Partial<SetDetail>) => void;
}
```

Stages: `'pick'` (platform list) → `'checking'` (preflight spinner) → `'confirm'` (summary + unresolved interrupt + export/download buttons) → `'exporting'` → `'done'` (Tidal success panel) / file download auto-triggers then returns to confirm with "Downloaded ✓". Platform rows data:

```typescript
const PLATFORMS = [
  { id: 'tidal', label: 'Tidal', sub: 'Playlist in your Tidal account', available: true },
  { id: 'rekordbox', label: 'Rekordbox XML', sub: 'DJ_PLAYLISTS import file', available: true },
  { id: 'm3u', label: 'M3U / .txt', sub: 'Universal playlist / plaintext', available: true },
  { id: 'enginedj', label: 'Engine DJ XML', available: false },
  { id: 'serato', label: 'Serato .crate', available: false },
  { id: 'spotify', label: 'Spotify', available: false },
  { id: 'applemusic', label: 'Apple Music', available: false },
] as const;
```

Unavailable rows: `opacity: 0.45`, `cursor: not-allowed`, badge `Coming soon` (small pill, `background: #2a2a2a`). The m3u confirm stage shows two download buttons (".m3u8" → format `m3u`, ".txt" → format `txt`) sharing one preflight (same resolution semantics). Download helper:

```typescript
function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
```

Unresolved interrupt panel: warning copy "N track(s) couldn't be resolved — they will NOT be exported unless you skip them explicitly", scrollable list (`maxHeight: 200, overflowY: 'auto'`) of `Artist – Title` (or `track_id` when title empty) with reason, buttons `Cancel` (back to pick) and `Skip N & continue` (sets `skipUnresolved=true`, enables export buttons).

- [ ] **Step 4: Wire into `SetActionsMenu.tsx`** — add an `Export` button (before Duplicate) opening the modal; extend props with `onSetUpdated: (patch: Partial<SetDetail>) => void`; update `[setId]/page.tsx`:

```tsx
<SetActionsMenu
  set={set}
  onShareChanged={(token) =>
    setSet((prev) => (prev ? { ...prev, share_token: token } : prev))
  }
  onSetUpdated={(patch) => setSet((prev) => (prev ? { ...prev, ...patch } : prev))}
/>
```

Check `dashboard/app/(dj)/setbuilder/__tests__/page.test.tsx` and any SetActionsMenu usage/tests for required prop updates.

- [ ] **Step 5: Run full frontend checks** — `npm run lint && npx tsc --noEmit && npm test -- --run`; restore `git checkout -- dashboard/next-env.d.ts` if dirty.
- [ ] **Step 6: Commit** — `feat(setbuilder): Export Setlist modal — platform picker, resolution interrupt, downloads (#396)`

---

### Task 7: Full local CI + finish

- [ ] Backend, from `<worktree>/server`: `ruff check .` && `ruff format --check .` && `bandit -r app -c pyproject.toml -q` && `pytest --tb=short -q` && `alembic upgrade head && alembic check` (uses worktree `.env` DB `wrzdj_issue396`; expect no new migration — both commands must still pass clean).
- [ ] Frontend, from `<worktree>/dashboard`: `npm run lint` && `npx tsc --noEmit` && `npm test -- --run`.
- [ ] `git checkout -- dashboard/next-env.d.ts` if modified.
- [ ] Use superpowers:finishing-a-development-branch, option 2 (Push + PR). PR title `feat(setbuilder): Export setlist — Tidal, Rekordbox XML, M3U (#396)`; body includes `Closes #396`, a `## Design decisions` section (copy the 9 decisions above), and a note that the live Tidal round-trip acceptance criterion is verified via mocked-edge tests only (no live Tidal credentials in CI).
