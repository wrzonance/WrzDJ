"""The drift check's comparison logic (offline; the live calls are run by hand, never in CI)."""

import importlib.util
from pathlib import Path

from tests.fakes import providers

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "provider_drift_check.py"
_spec = importlib.util.spec_from_file_location("provider_drift_check", _PATH)
drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drift)


def test_shape_keeps_keys_and_types_and_describes_lists_by_first_item():
    assert drift.shape({"b": [{"x": 1}, {"y": "z"}], "a": "s"}) == {"a": "str", "b": [{"x": "int"}]}


def test_missing_reports_fake_keys_absent_from_the_live_answer():
    fake = drift.shape({"artist_mbid": "m", "stats": {"listens": 1, "users": 2}})
    live = drift.shape({"artist_mbid": "m", "stats": {"listens": 1}, "extra": True})
    assert drift.missing(fake, live) == ["stats.users"]


def test_missing_is_empty_when_the_live_answer_has_every_fake_key():
    fake = drift.shape([{"id": 1}])
    assert drift.missing(fake, drift.shape([{"id": 2, "name": "n"}])) == []


def test_fake_body_reads_the_registered_fake_response():
    body = drift.fake_body(
        providers.listenbrainz_popular,
        "POST",
        providers.LISTENBRAINZ_POPULARITY,
        b'{"artist_mbids": ["a74b1b7f-71a5-4011-9441-d0b5e4122711"]}',
    )
    assert isinstance(body, list | dict)


def test_missing_flags_an_empty_live_list_whose_fake_item_has_keys():
    """An empty live list gives no item to check the fake item's keys against; that is drift,
    not a match."""
    assert drift.missing(drift.shape([{"id": 1}]), drift.shape([])) == ["[0]"]
    fake = drift.shape({"items": [{"id": 1}]})
    assert drift.missing(fake, drift.shape({"items": []})) == ["items[0]"]


def test_tidal_token_reports_an_unreachable_session_check(monkeypatch):
    """A network failure while validating TIDAL_ACCESS_TOKEN is a why-not, not a crash."""
    import httpx

    def unreachable(*_args, **_kwargs):
        raise httpx.ConnectError("boom")

    monkeypatch.setenv("TIDAL_ACCESS_TOKEN", "a-token")
    monkeypatch.setattr(drift.httpx, "get", unreachable)

    assert drift.tidal_token(login=False) == (
        None,
        None,
        "",
        "TIDAL_ACCESS_TOKEN check unreachable: ConnectError",
    )
