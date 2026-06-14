"""Set-duration targeting helpers for WrzDJSet.

The pass-1 slot generator consumes this contract so target length and average
transition overlap stay consistent with the UI projection.
"""

from dataclasses import dataclass
from math import ceil

DEFAULT_AVG_TRANSITION_OVERLAP_SEC = 8


@dataclass(frozen=True)
class SlotBudget:
    """Target-driven slot count and projected effective duration."""

    slot_count: int
    projected_total_sec: int
    projected_effective_sec: int
    delta_sec: int | None
    within_overflow_tolerance: bool | None = None


def effective_duration_sec(total_sec: int, slots: int, overlap_sec: int) -> int:
    """Effective playtime after blend overlaps."""
    transitions = max(0, slots - 1)
    return max(0, int(total_sec) - transitions * max(0, int(overlap_sec)))


def pass1_slot_budget(
    *,
    target_duration_sec: int | None,
    avg_track_duration_sec: int,
    avg_transition_overlap_sec: int = DEFAULT_AVG_TRANSITION_OVERLAP_SEC,
) -> SlotBudget:
    """Compute the minimum slot count that reaches a target effective duration.

    For n tracks with average duration d and transition overlap o:
    effective = n*d - (n-1)*o = n*(d-o) + o.
    """
    if target_duration_sec is None or target_duration_sec <= 0:
        return SlotBudget(0, 0, 0, None)

    track_sec = max(1, int(avg_track_duration_sec))
    overlap_sec = max(0, int(avg_transition_overlap_sec))
    effective_per_added_track = max(1, track_sec - overlap_sec)
    slot_count = max(1, ceil((target_duration_sec - overlap_sec) / effective_per_added_track))
    total_sec = slot_count * track_sec
    projected_effective = effective_duration_sec(total_sec, slot_count, overlap_sec)
    delta_sec = projected_effective - target_duration_sec
    return SlotBudget(
        slot_count=slot_count,
        projected_total_sec=total_sec,
        projected_effective_sec=projected_effective,
        delta_sec=delta_sec,
        within_overflow_tolerance=delta_sec <= target_duration_sec * 0.10,
    )


def pass1_slot_budget_from_durations(
    *,
    target_duration_sec: int | None,
    track_durations_sec: list[int],
    avg_transition_overlap_sec: int = DEFAULT_AVG_TRANSITION_OVERLAP_SEC,
    overflow_tolerance: float = 0.10,
) -> SlotBudget:
    """Compute a target budget from actual selected track durations.

    The deterministic pass can call this as it builds candidate timelines:
    actual durations win over uniform buckets, while ``within_overflow_tolerance``
    tells callers whether the selected prefix has exceeded the target by more
    than the allowed tolerance.
    """
    if target_duration_sec is None or target_duration_sec <= 0:
        return SlotBudget(0, 0, 0, None)

    overlap_sec = max(0, int(avg_transition_overlap_sec))
    total_sec = 0
    slot_count = 0
    projected_effective = 0
    for duration_sec in track_durations_sec:
        if duration_sec <= 0:
            continue
        slot_count += 1
        total_sec += int(duration_sec)
        projected_effective = effective_duration_sec(total_sec, slot_count, overlap_sec)
        if projected_effective >= target_duration_sec:
            break

    if slot_count == 0:
        return SlotBudget(0, 0, 0, -target_duration_sec, False)

    delta_sec = projected_effective - target_duration_sec
    max_overflow = target_duration_sec * max(0.0, overflow_tolerance)
    return SlotBudget(
        slot_count=slot_count,
        projected_total_sec=total_sec,
        projected_effective_sec=projected_effective,
        delta_sec=delta_sec,
        within_overflow_tolerance=delta_sec <= max_overflow,
    )
