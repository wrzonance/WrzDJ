"""Public playlist URL validation for WrzDJSet pool import (issue #388).

Security posture (SSRF defense): we NEVER fetch the user-supplied URL.
This module only *parses* it — https scheme enforced, exact-match host
allowlist, no userinfo/port tricks, playlist IDs constrained to strict
charsets — and importers then call official APIs (spotipy / tidalapi)
with the extracted ID.

Recognized-but-unsupported providers (Apple Music, YouTube, SoundCloud,
Beatport) parse successfully with ``supported=False`` so the UI can show
a precise message instead of a generic "invalid URL" error.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_SPOTIFY_PLAYLIST_RE = re.compile(r"^/playlist/([A-Za-z0-9]{16,40})/?$")
_TIDAL_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_TIDAL_PLAYLIST_RE = re.compile(rf"^/(?:browse/)?playlist/({_TIDAL_UUID})/?$")

_UNSUPPORTED_HOSTS: dict[str, tuple[str, str]] = {
    "music.apple.com": (
        "apple_music",
        "Apple Music playlists aren't supported yet — no public API access is configured.",
    ),
    "www.youtube.com": (
        "youtube",
        "YouTube playlists aren't supported yet — no public API access is configured.",
    ),
    "youtube.com": (
        "youtube",
        "YouTube playlists aren't supported yet — no public API access is configured.",
    ),
    "music.youtube.com": (
        "youtube",
        "YouTube playlists aren't supported yet — no public API access is configured.",
    ),
    "soundcloud.com": (
        "soundcloud",
        "SoundCloud playlists aren't supported yet — no public API access is configured.",
    ),
    "www.beatport.com": (
        "beatport",
        "Use the Beatport import option instead — it pulls playlists via your connected account.",
    ),
    "beatport.com": (
        "beatport",
        "Use the Beatport import option instead — it pulls playlists via your connected account.",
    ),
}


class InvalidPlaylistUrl(ValueError):
    """Raised when a URL is not a recognizable https playlist URL."""


@dataclass(frozen=True)
class ParsedPlaylistUrl:
    provider: str  # "spotify" | "tidal" | "apple_music" | "youtube" | "soundcloud" | "beatport"
    playlist_id: str | None
    supported: bool
    message: str | None = None


def parse_public_playlist_url(url: str) -> ParsedPlaylistUrl:
    """Parse and validate a public playlist URL against the host allowlist.

    Raises InvalidPlaylistUrl for anything that is not an https URL on a
    known playlist host with a well-formed playlist path.
    """
    if not url or len(url) > 500:
        raise InvalidPlaylistUrl("URL is empty or too long")

    try:
        split = urlsplit(url.strip())
    except ValueError as e:
        raise InvalidPlaylistUrl("URL could not be parsed") from e

    if split.scheme != "https":
        raise InvalidPlaylistUrl("Only https playlist URLs are accepted")
    if split.username or split.password:
        raise InvalidPlaylistUrl("URLs with credentials are not accepted")
    try:
        if split.port is not None:
            raise InvalidPlaylistUrl("URLs with explicit ports are not accepted")
    except ValueError as e:  # non-numeric port
        raise InvalidPlaylistUrl("URL could not be parsed") from e

    host = (split.hostname or "").lower()
    path = split.path or ""

    if host == "open.spotify.com":
        m = _SPOTIFY_PLAYLIST_RE.match(path)
        if not m:
            raise InvalidPlaylistUrl("Not a Spotify playlist URL (expected /playlist/<id>)")
        return ParsedPlaylistUrl(provider="spotify", playlist_id=m.group(1), supported=True)

    if host in ("tidal.com", "listen.tidal.com", "www.tidal.com"):
        m = _TIDAL_PLAYLIST_RE.match(path)
        if not m:
            raise InvalidPlaylistUrl("Not a Tidal playlist URL (expected /playlist/<uuid>)")
        return ParsedPlaylistUrl(provider="tidal", playlist_id=m.group(1).lower(), supported=True)

    if host in _UNSUPPORTED_HOSTS:
        provider, message = _UNSUPPORTED_HOSTS[host]
        return ParsedPlaylistUrl(
            provider=provider, playlist_id=None, supported=False, message=message
        )

    raise InvalidPlaylistUrl(
        "Unrecognized playlist host — supported: Spotify, Tidal "
        "(Apple Music / YouTube / SoundCloud coming later)"
    )
