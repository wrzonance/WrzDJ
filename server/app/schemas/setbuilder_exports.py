from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

ExportTarget = Literal[
    "tidal", "spotify", "apple_music", "rekordbox", "m3u", "txt", "enginedj", "lexicon"
]
ExportFileFormat = Literal["rekordbox", "m3u", "txt", "enginedj", "lexicon"]


class ExportPreflightIn(BaseModel):
    """Body for the pre-export resolution check."""

    target: ExportTarget


class UnresolvedTrackOut(BaseModel):
    """One track that can't be exported to the chosen target."""

    position: int
    title: str
    artist: str
    track_id: str | None
    reason: Literal[
        "no_tidal_match", "no_spotify_match", "no_apple_music_match", "missing_metadata"
    ]


class ExportPreflightOut(BaseModel):
    """Resolution summary the DJ confirms before exporting."""

    target: ExportTarget
    source: Literal["timeline", "pool"]
    total: int
    resolved_count: int
    unresolved: list[UnresolvedTrackOut]
    # Only set for target="tidal"; None for file targets.
    tidal_connected: bool | None = None
    spotify_connected: bool | None = None
    apple_music_connected: bool | None = None


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


class ExportSpotifyIn(BaseModel):
    """Body for Spotify export; skip_unresolved requires explicit DJ choice."""

    skip_unresolved: bool = False


class ExportSpotifyOut(BaseModel):
    """Successful Spotify playlist export."""

    playlist_id: str
    playlist_url: str
    added: int
    skipped: int
    exported_at: datetime
    status: Literal["draft", "locked", "exported"]


class ExportAppleMusicIn(BaseModel):
    """Apple Music export requires an explicit choice before skipping unresolved tracks."""

    skip_unresolved: bool = False


class ExportAppleMusicRecoveryIn(BaseModel):
    """Require the DJ to explicitly reconcile an export Apple did not confirm."""

    action: Literal["playlist_found", "playlist_absent"]
    playlist_id: str | None = Field(default=None, pattern=r"^p\.[A-Za-z0-9_-]{1,98}$")

    @model_validator(mode="after")
    def validate_recovery_action(self) -> "ExportAppleMusicRecoveryIn":
        if self.action == "playlist_found" and self.playlist_id is None:
            raise ValueError("playlist_id is required when the playlist was found")
        if self.action == "playlist_absent" and self.playlist_id is not None:
            raise ValueError("playlist_id is only valid when the playlist was found")
        return self


class ExportAppleMusicRecoveryOut(BaseModel):
    """Result of the DJ's explicit Apple Music reconciliation."""

    status: Literal["exported", "ready_to_retry"]


class ExportAppleMusicOut(BaseModel):
    """A playlist confirmed by read-back from the Apple Music library."""

    playlist_id: str
    playlist_url: str | None
    added: int
    skipped: int
    exported_at: datetime
    status: Literal["draft", "locked", "exported"]


class ExportFileIn(BaseModel):
    """Body for the file (Rekordbox XML / M3U / txt) export."""

    format: ExportFileFormat
    skip_unresolved: bool = False


class UnresolvedTracksDetail(BaseModel):
    """Detail payload of the 409 unresolved-tracks interrupt."""

    code: Literal["unresolved_tracks"]
    unresolved: list[UnresolvedTrackOut]


class UnresolvedTracksError(BaseModel):
    """409 response body — export blocked until retried with skip_unresolved=true."""

    detail: UnresolvedTracksDetail


# ---------------------------------------------------------------------------
# Play-history feedback loop (issue #403) — derive-on-read planned-vs-actual.
