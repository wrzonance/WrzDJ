"""Duration targeting contract for WrzDJSet pass-1 slot generation (issue #394)."""

from app.services.setbuilder import targeting


def test_effective_duration_subtracts_transition_overlap():
    assert targeting.effective_duration_sec(total_sec=1800, slots=6, overlap_sec=8) == 1760
    assert targeting.effective_duration_sec(total_sec=1800, slots=1, overlap_sec=8) == 1800
    assert targeting.effective_duration_sec(total_sec=10, slots=5, overlap_sec=8) == 0


def test_pass1_slot_budget_uses_effective_track_playtime():
    budget = targeting.pass1_slot_budget(
        target_duration_sec=3600,
        avg_track_duration_sec=210,
        avg_transition_overlap_sec=10,
    )

    assert budget.slot_count == 18
    assert budget.projected_total_sec == 3780
    assert budget.projected_effective_sec == 3610
    assert budget.delta_sec == 10


def test_pass1_slot_budget_without_target_returns_empty_contract():
    budget = targeting.pass1_slot_budget(
        target_duration_sec=None,
        avg_track_duration_sec=210,
        avg_transition_overlap_sec=8,
    )

    assert budget.slot_count == 0
    assert budget.projected_effective_sec == 0
    assert budget.delta_sec is None


def test_pass1_slot_budget_from_actual_durations_respects_overflow_tolerance():
    budget = targeting.pass1_slot_budget_from_durations(
        target_duration_sec=600,
        track_durations_sec=[240, 240, 240],
        avg_transition_overlap_sec=10,
        overflow_tolerance=0.10,
    )

    assert budget.slot_count == 3
    assert budget.projected_total_sec == 720
    assert budget.projected_effective_sec == 700
    assert budget.delta_sec == 100
    assert budget.within_overflow_tolerance is False


def test_pass1_slot_budget_from_actual_durations_prefers_tolerated_overflow():
    budget = targeting.pass1_slot_budget_from_durations(
        target_duration_sec=600,
        track_durations_sec=[210, 210, 210],
        avg_transition_overlap_sec=10,
        overflow_tolerance=0.10,
    )

    assert budget.slot_count == 3
    assert budget.projected_effective_sec == 610
    assert budget.within_overflow_tolerance is True
