from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class OwnVibeOut(BaseModel):
    """The DJ's own override tier."""

    energy: int | None
    mood: str | None


class CommunityVibeOut(BaseModel):
    """Community consensus tier (gated by SystemSettings thresholds)."""

    energy: int | None
    mood: str | None
    sample_size: int


class LlmVibeOut(BaseModel):
    """Globally-cached LLM guess tier."""

    energy: int | None
    mood: str | None
    era: str | None
    sing_along: bool | None
    dance_floor: bool | None
    transitional_role: str | None
    confidence: float | None
    low_confidence: bool
    llm_provider: str
    llm_model: str


class ResolvedVibeOut(BaseModel):
    """Per-field precedence result: own -> community -> llm."""

    energy: int | None
    energy_source: Literal["own", "community", "llm"] | None
    mood: str | None
    mood_source: Literal["own", "community", "llm"] | None


class TrackVibeStateOut(BaseModel):
    """All three tiers + resolution for one pool track."""

    pool_track_id: int
    vibe_key: str
    own: OwnVibeOut | None
    community: CommunityVibeOut | None
    llm: LlmVibeOut | None
    resolved: ResolvedVibeOut


class PoolVibesState(BaseModel):
    """Vibe state for every track in a set's pool."""

    tracks: list[TrackVibeStateOut]


class PoolVibeOverrideIn(BaseModel):
    """Explicit DJ edit for one pool track's vibe fields."""

    model_config = ConfigDict(
        json_schema_extra={
            "allOf": [
                {
                    "anyOf": [
                        {
                            "properties": {
                                "energy": {
                                    "anyOf": [
                                        {"maximum": 10.0, "minimum": 0.0, "type": "integer"},
                                        {"type": "null"},
                                    ],
                                    "title": "Energy",
                                },
                                "mood": {
                                    "anyOf": [
                                        {"maxLength": 50, "type": "string"},
                                        {"type": "null"},
                                    ],
                                    "title": "Mood",
                                },
                            },
                            "required": ["energy"],
                            "type": "object",
                        },
                        {
                            "properties": {
                                "energy": {
                                    "anyOf": [
                                        {"maximum": 10.0, "minimum": 0.0, "type": "integer"},
                                        {"type": "null"},
                                    ],
                                    "title": "Energy",
                                },
                                "mood": {
                                    "anyOf": [
                                        {"maxLength": 50, "type": "string"},
                                        {"type": "null"},
                                    ],
                                    "title": "Mood",
                                },
                            },
                            "required": ["mood"],
                            "type": "object",
                        },
                    ]
                }
            ],
            "minProperties": 1,
        }
    )

    energy: int | None = Field(default=None, ge=0, le=10)
    mood: str | None = Field(default=None, max_length=50)

    @field_validator("mood")
    @classmethod
    def _normalize_mood(cls, value: str | None) -> str | None:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    @model_validator(mode="after")
    def _requires_touched_field(self) -> "PoolVibeOverrideIn":
        if not {"energy", "mood"} & self.model_fields_set:
            raise ValueError("energy or mood is required")
        return self


class VibeEnrichmentResult(BaseModel):
    """Result of an enrichment run, plus the refreshed vibe state."""

    enriched: int
    cached: int
    failed: int
    llm_calls: int
    vibes: PoolVibesState


# ---------------------------------------------------------------------------
# Export (issue #396)


# Engine DJ and Lexicon have no proprietary import format — both ingest the
# Rekordbox DJ_PLAYLISTS XML — so they are distinct format keys that render the
# same XML (kept distinct, not aliased, so the UI lists them separately).
