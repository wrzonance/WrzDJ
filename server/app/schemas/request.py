from enum import Enum
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

from app.core.validation import contains_profanity, normalize_single_line, normalize_text
from app.models.request import RequestSource, RequestStatus
from app.schemas.common import BaseSchema, IsoDatetime
from app.services.track_normalizer import valid_isrc

ALLOWED_URL_SCHEMES = {"http", "https", "spotify"}


class RequestCreate(BaseModel):
    artist: str = Field(..., min_length=1, max_length=255)
    title: str = Field(..., min_length=1, max_length=255)
    note: str | None = Field(default=None, max_length=500)
    nickname: str | None = Field(default=None, max_length=30)
    source: RequestSource = RequestSource.MANUAL
    source_url: str | None = Field(default=None, max_length=500)
    artwork_url: str | None = Field(default=None, max_length=500)
    raw_search_query: str | None = Field(default=None, max_length=200)
    # Track metadata from search sources
    genre: str | None = Field(default=None, max_length=100)
    bpm: float | None = Field(default=None, ge=1, le=999)
    musical_key: str | None = Field(default=None, max_length=20)
    # ISRC from the chosen search result (#552); normalized on store. max_length 15
    # accommodates the hyphenated form (e.g. "US-UM7-19-00764").
    isrc: str | None = Field(default=None, max_length=15)

    @field_validator("artist", "title")
    @classmethod
    def normalize_single_line_fields(cls, v: str) -> str:
        normalized = normalize_single_line(v)
        return normalized if normalized else v

    @field_validator("isrc")
    @classmethod
    def validate_isrc(cls, v: str | None) -> str | None:
        # Normalize + drop a malformed ISRC (it would defeat the ISRC-first cache
        # and drive bad provider by-ISRC calls if treated as identity). #552
        return valid_isrc(v)

    @field_validator("note")
    @classmethod
    def normalize_note(cls, v: str | None) -> str | None:
        return normalize_text(v)

    @field_validator("nickname")
    @classmethod
    def normalize_nickname(cls, v: str | None) -> str | None:
        if v is None:
            return v
        normalized = normalize_single_line(v)
        if not normalized:
            return None
        if contains_profanity(normalized):
            raise ValueError("Please choose a different name")
        return normalized

    @field_validator("raw_search_query")
    @classmethod
    def normalize_raw_search_query(cls, v: str | None) -> str | None:
        if v is None:
            return v
        normalized = normalize_single_line(v)
        return normalized if normalized else v

    @field_validator("source_url", "artwork_url")
    @classmethod
    def validate_url_scheme(cls, v: str | None) -> str | None:
        if v is None:
            return v
        scheme = urlparse(v).scheme.lower()
        if scheme not in ALLOWED_URL_SCHEMES:
            raise ValueError(f"URL scheme '{scheme or '(empty)'}' is not allowed")
        return v


class RequestUpdate(BaseModel):
    status: RequestStatus


class RequestOut(BaseSchema):
    id: int
    event_id: int
    song_title: str
    artist: str
    source: str
    source_url: str | None
    artwork_url: str | None
    note: str | None
    nickname: str | None = None
    status: str
    created_at: IsoDatetime
    updated_at: IsoDatetime
    # First moment the request entered ACCEPTED; null until first accepted.
    # Backs the DJ "date accepted" sort (issue #478).
    accepted_at: IsoDatetime | None = None
    is_duplicate: bool = False
    # Track metadata
    genre: str | None = None
    bpm: float | None = None
    musical_key: str | None = None
    # Search intent
    raw_search_query: str | None = None
    # Multi-service sync results (JSON array)
    sync_results_json: str | None = None
    # Voting
    vote_count: int = 0
    # Priority scoring (populated only when sort=best_match)
    priority_score: float | None = None


class RequestSort(str, Enum):
    """DJ-facing sort fields for the request list (issue #478)."""

    DATE_REQUESTED = "date_requested"
    DATE_ACCEPTED = "date_accepted"
    UPVOTES = "upvotes"
    BPM = "bpm"
    KEY = "key"
    TITLE = "title"
    ARTIST = "artist"
    BEST_MATCH = "best_match"


class SortDirection(str, Enum):
    ASC = "asc"
    DESC = "desc"


class RequestListResponse(BaseSchema):
    """Paginated DJ request list.

    ``total`` is the true row count before pagination, so the dashboard never
    infers the count from the returned page length (the #411 failure mode).
    """

    requests: list[RequestOut]
    total: int
    limit: int
    offset: int
    sort: RequestSort
    direction: SortDirection
    # True per-status counts for the whole event, computed before pagination and
    # independent of the active status/since/limit/offset (issue #478). Keys:
    # all, new, accepted, playing, played, rejected (0 when absent). ``all`` is
    # the cross-status total; ``total`` stays the active filter's count.
    status_counts: dict[str, int]
