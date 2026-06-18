"""Service-level tests for setbuilder export (collect/render/resolve)."""

import xml.etree.ElementTree as ET
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.models.set import Set, SetSlot
from app.models.set_pool import SetPoolSource, SetPoolTrack
from app.models.user import User
from app.services.setbuilder import export_tidal
from app.services.setbuilder.export_common import ExportTrack, collect_export_tracks
from app.services.setbuilder.export_files import (
    file_unresolved,
    render_m3u,
    render_rekordbox_xml,
    render_txt,
    safe_filename,
)


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
            db,
            s,
            title="Joined",
            artist="DJ",
            track_id="tidal:111",
            bpm=128.0,
            camelot="8A",
            isrc="USX9P1234567",
            duration_sec=200,
            dedupe_sig="s1",
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
        assert (
            ExportTrack(position=0, title="t", artist="a", track_id="beatport:42").tidal_id is None
        )
        assert ExportTrack(position=0, title="t", artist="a", track_id=None).tidal_id is None


TRACKS = [
    ExportTrack(
        position=0,
        title="Opener",
        artist="DJ One",
        album="LP",
        genre="House",
        bpm=124.0,
        camelot="8A",
        duration_sec=210,
        track_id="tidal:1",
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
        node = root.find("PLAYLISTS/NODE/NODE")
        assert node.attrib["Name"] == "Friday Night"
        assert [t.attrib["Key"] for t in node.findall("TRACK")] == ["1", "2"]

    def test_escapes_special_chars(self):
        xml = render_rekordbox_xml("Friday Night", TRACKS)
        root = ET.fromstring(xml)  # parse fails if escaping is broken
        assert root.find("COLLECTION/TRACK[2]").attrib["Name"] == 'Peak "Time"'

    def test_isrc_emitted_in_comments(self):
        """ISRC has no native DJ_PLAYLISTS slot; carry it in Comments (Engine/Lexicon fidelity)."""
        track = ExportTrack(position=0, title="T", artist="A", isrc="USX9P1234567")
        xml = render_rekordbox_xml("S", [track])
        root = ET.fromstring(xml)
        assert root.find("COLLECTION/TRACK").attrib["Comments"] == "ISRC:USX9P1234567"

    def test_no_isrc_omits_comments(self):
        track = ExportTrack(position=0, title="T", artist="A")
        xml = render_rekordbox_xml("S", [track])
        root = ET.fromstring(xml)
        assert "Comments" not in root.find("COLLECTION/TRACK").attrib

    def test_isrc_control_chars_sanitized(self):
        track = ExportTrack(position=0, title="T", artist="A", isrc="US\x00X9P\x1f1234567")
        xml = render_rekordbox_xml("S", [track])
        root = ET.fromstring(xml)  # must parse; control chars stripped
        assert root.find("COLLECTION/TRACK").attrib["Comments"] == "ISRC:US X9P 1234567"


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

    def test_creates_playlist_adds_tracks_and_marks_exported(self, db, test_user, monkeypatch):
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
        monkeypatch.setattr("app.services.tidal.add_tracks_to_playlist", lambda *a, **kw: False)
        with pytest.raises(export_tidal.TidalExportError):
            export_tidal.export_to_tidal(
                db, test_user, s, [(ExportTrack(position=0, title="T", artist="A"), "1")]
            )
        db.refresh(s)
        assert s.status == "draft"
        assert s.tidal_playlist_id is None

    def test_empty_resolved_raises_before_any_api_call(self, db, test_user, monkeypatch):
        """Fix 3: empty-resolved guard must fire before get_tidal_session."""
        s = _mk_set(db, test_user)

        def boom(*a, **kw):
            raise AssertionError("get_tidal_session called despite empty resolved list")

        monkeypatch.setattr("app.services.tidal.get_tidal_session", boom)
        with pytest.raises(export_tidal.TidalExportError):
            export_tidal.export_to_tidal(db, test_user, s, [])
        db.refresh(s)
        assert s.status == "draft"

    def test_playlist_creation_failure_raises_and_set_stays_draft(self, db, test_user, monkeypatch):
        """Fix 5: playlist creation failure → TidalExportError, set stays draft."""
        s = _mk_set(db, test_user)

        def bad_session():
            def create_playlist(name, description):
                raise RuntimeError("boom")

            return SimpleNamespace(user=SimpleNamespace(create_playlist=create_playlist))

        monkeypatch.setattr("app.services.tidal.get_tidal_session", lambda db_, u: bad_session())
        with pytest.raises(export_tidal.TidalExportError):
            export_tidal.export_to_tidal(
                db, test_user, s, [(ExportTrack(position=0, title="T", artist="A"), "1")]
            )
        db.refresh(s)
        assert s.status == "draft"
        assert s.tidal_playlist_id is None


class TestRendererSanitization:
    """Fix 1: control-character sanitization in all renderers."""

    def test_newline_in_title_cannot_inject_m3u_lines(self):
        evil = ExportTrack(position=0, title="Song\n/etc/passwd", artist="A\r\n#EXTINF:9,fake")
        m3u = render_m3u("x", [evil])
        lines = m3u.splitlines()
        assert len(lines) == 4  # header, playlist, one EXTINF, one path line
        assert not any(line == "/etc/passwd" for line in lines)

    def test_control_chars_dont_break_rekordbox_xml(self):
        evil = ExportTrack(position=0, title="Bad\x0bTitle", artist="A\nB")
        xml = render_rekordbox_xml("Name\x00", [evil])
        root = ET.fromstring(xml)  # must parse without error
        assert root.find("COLLECTION/TRACK").attrib["Name"] == "Bad Title"

    def test_set_name_sanitized_in_m3u(self):
        m3u = render_m3u("Set\nName", [])
        lines = m3u.splitlines()
        assert lines[1] == "#PLAYLIST:Set Name"

    def test_set_name_sanitized_in_txt(self):
        txt = render_txt("Set\nName", [])
        assert txt.splitlines()[0] == "Set Name"

    def test_set_name_sanitized_in_rekordbox_xml(self):
        xml = render_rekordbox_xml("Set\nName", [])
        root = ET.fromstring(xml)
        node = root.find("PLAYLISTS/NODE/NODE")
        assert node.attrib["Name"] == "Set Name"

    def test_artist_and_string_attrs_sanitized_in_xml(self):
        track = ExportTrack(
            position=0,
            title="Title\x01",
            artist="Art\x02",
            album="Alb\x03",
            genre="Gen\x04",
            key="Am\x05",
        )
        xml = render_rekordbox_xml("S", [track])
        root = ET.fromstring(xml)
        t = root.find("COLLECTION/TRACK")
        assert t.attrib["Name"] == "Title "
        assert t.attrib["Artist"] == "Art "
        assert t.attrib["Album"] == "Alb "
        assert t.attrib["Genre"] == "Gen "
        assert t.attrib["Tonality"] == "Am "
