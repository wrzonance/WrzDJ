"""Tests for TrackVibe LLM enrichment + community consensus + resolver (issue #391)."""

from app.services.system_settings import get_system_settings, update_system_settings


class TestVibeConsensusSettings:
    def test_defaults(self, db):
        s = get_system_settings(db)
        assert s.vibe_consensus_min_sample == 3
        assert s.vibe_consensus_max_stddev == 1.5

    def test_update(self, db):
        s = update_system_settings(db, vibe_consensus_min_sample=5, vibe_consensus_max_stddev=2.0)
        assert s.vibe_consensus_min_sample == 5
        assert s.vibe_consensus_max_stddev == 2.0

    def test_admin_patch_endpoint(self, client, admin_headers):
        resp = client.patch(
            "/api/admin/settings",
            json={"vibe_consensus_min_sample": 4, "vibe_consensus_max_stddev": 1.0},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["vibe_consensus_min_sample"] == 4
        assert body["vibe_consensus_max_stddev"] == 1.0

    def test_min_sample_bounds_rejected(self, client, admin_headers):
        for bad in (0, 101):
            resp = client.patch(
                "/api/admin/settings",
                json={"vibe_consensus_min_sample": bad},
                headers=admin_headers,
            )
            assert resp.status_code == 422

    def test_max_stddev_bounds_rejected(self, client, admin_headers):
        for bad in (0.0, 5.1):
            resp = client.patch(
                "/api/admin/settings",
                json={"vibe_consensus_max_stddev": bad},
                headers=admin_headers,
            )
            assert resp.status_code == 422
