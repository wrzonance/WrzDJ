"""File-format renderers for WrzDJSet export (issue #396) — stdlib only.

Rekordbox XML (DJ_PLAYLISTS 1.0.0): server can't know local audio paths,
so ``Location`` is a synthetic ``file://localhost/WrzDJ/...`` placeholder;
rekordbox imports the playlist + metadata and the DJ relinks files. M3U
uses #EXTINF metadata with a path-less "Artist - Title.mp3" line. For all
file formats "unresolved" = missing title/artist (orphan timeline slots);
pool-backed tracks always have both (NOT NULL columns).
"""

import re
import xml.etree.ElementTree as ET  # nosec B405 — XML generation/serialization only; never parses untrusted input
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
