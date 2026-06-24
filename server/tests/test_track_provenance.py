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
    assert should_overwrite(existing, "soundcharts") is True  # refresh same tier
    assert should_overwrite(existing, "lexicon") is True  # higher tier wins
