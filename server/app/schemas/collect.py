"""Pydantic schemas for pre-event collection endpoints."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, StringConstraints

from app.core.validation import contains_profanity


def _check_nickname_profanity(v: str) -> str:
    if contains_profanity(v):
        raise ValueError("Please choose a different name")
    return v


def _check_note_profanity(v: str) -> str:
    if contains_profanity(v):
        raise ValueError("Note contains inappropriate content")
    return v


Nickname = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=2,
        max_length=30,
        pattern=r"^[a-zA-Z0-9 _.-]+$",
    ),
    AfterValidator(_check_nickname_profanity),
]
Note = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=500),
    AfterValidator(_check_note_profanity),
]


class CollectPhase(BaseModel):
    phase: Literal["pre_announce", "collection", "live", "closed"]
    collection_opens_at: datetime | None
    live_starts_at: datetime | None
    expires_at: datetime


class CollectEventPreview(BaseModel):
    code: str
    name: str
    banner_filename: str | None
    banner_url: str | None = None
    banner_colors: list[str] | None = None
    submission_cap_per_guest: int
    registration_enabled: bool
    phase: Literal["pre_announce", "collection", "live", "closed"]
    collection_opens_at: datetime | None
    live_starts_at: datetime | None
    expires_at: datetime


class CollectLeaderboardRow(BaseModel):
    id: int
    title: str
    artist: str
    artwork_url: str | None
    vote_count: int
    nickname: str | None
    status: Literal["new", "accepted", "playing", "played", "rejected"]
    created_at: datetime
    bpm: int | None = None
    musical_key: str | None = None
    genre: str | None = None
    requester_verified: bool = False


class CollectPreviewResponse(BaseModel):
    source: Literal["spotify", "tidal", "beatport", "manual"]
    source_url: str | None


class CollectLeaderboardResponse(BaseModel):
    requests: list[CollectLeaderboardRow]
    total: int


class CollectProfileRequest(BaseModel):
    nickname: Nickname | None = None


class CollectProfileResponse(BaseModel):
    nickname: str | None
    email_verified: bool
    submission_count: int
    submission_cap: int


class CollectMyPicksItem(CollectLeaderboardRow):
    interaction: Literal["submitted", "upvoted"]


class CollectMyPicksResponse(BaseModel):
    submitted: list[CollectMyPicksItem]
    upvoted: list[CollectMyPicksItem]
    is_top_contributor: bool
    first_suggestion_ids: list[int]
    # Every request_id this guest has voted on in this event, including votes
    # on their own submissions. Separate from `upvoted` (which is de-duped
    # against `submitted` for display purposes) so the UI can gate the vote
    # button accurately.
    voted_request_ids: list[int]


class CollectSubmitRequest(BaseModel):
    song_title: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
    ]
    artist: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
    ]
    source: Literal["spotify", "beatport", "tidal", "manual"]
    source_url: str | None = Field(default=None, max_length=500)
    artwork_url: str | None = Field(default=None, max_length=500)
    note: Note | None = None
    nickname: Nickname | None = None


class LiveJoinCodeResponse(BaseModel):
    """Returns the live join_code for an event that has entered the live phase.

    Gated by require_verified_human so the join_code never leaks to unverified
    bots scraping the collect URL during the collection-to-live transition.
    """

    join_code: str


class CollectVoteRequest(BaseModel):
    request_id: int


class UpdateCollectionSettings(BaseModel):
    collection_opens_at: datetime | None = None
    live_starts_at: datetime | None = None
    submission_cap_per_guest: int | None = Field(default=None, ge=0, le=100)
    collection_phase_override: Literal["force_collection", "force_live"] | None = None
    tidal_sync_enabled: bool | None = None
    tidal_collection_bidirectional: bool | None = None


class PendingReviewRow(BaseModel):
    id: int
    song_title: str
    artist: str
    artwork_url: str | None
    vote_count: int
    nickname: str | None
    created_at: datetime
    note: str | None
    status: Literal["new", "accepted", "playing", "played", "rejected"]


class PendingReviewResponse(BaseModel):
    requests: list[PendingReviewRow]
    total: int


class BulkReviewRequest(BaseModel):
    action: Literal[
        "accept_top_n",
        "accept_threshold",
        "accept_ids",
        "reject_ids",
        "reject_remaining",
    ]
    n: int | None = Field(default=None, ge=1, le=200)
    min_votes: int | None = Field(default=None, ge=0)
    request_ids: list[int] | None = Field(default=None, max_length=200)


class BulkReviewResponse(BaseModel):
    accepted: int
    rejected: int
    unchanged: int


class EnrichPreviewItem(BaseModel):
    title: str
    artist: str
    source_url: str | None = None


class EnrichPreviewResult(BaseModel):
    title: str
    artist: str
    bpm: int | None = None
    key: str | None = None
    genre: str | None = None


class EnrichPreviewRequest(BaseModel):
    items: list[EnrichPreviewItem]


class EnrichPreviewResponse(BaseModel):
    results: list[EnrichPreviewResult]
