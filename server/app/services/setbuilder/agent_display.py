"""Render an applied tool call as the one-line summary shown in ToolCard.

Pure formatting over the call payload/result and before/after slot snapshots;
no DB or model access.
"""

from __future__ import annotations

from typing import Any


def _position_label(position: int) -> str:
    return f"slot {position + 1}"


def _tool_display_summary(
    name: str,
    payload: dict[str, Any],
    result: dict[str, Any],
    before: dict[int, dict[str, Any]],
    after: dict[int, dict[str, Any]],
) -> str:
    if name == "swap_slots":
        a = before.get(int(payload["slot_a_id"]))
        b = before.get(int(payload["slot_b_id"]))
        if a and b:
            return (
                f"Swapped {_position_label(a['position'])} {a['label']} with "
                f"{_position_label(b['position'])} {b['label']}."
            )
    if name == "reorder_slot":
        slot = before.get(int(payload["slot_id"]))
        if slot:
            return (
                f"Moved {slot['label']} from {_position_label(slot['position'])} to "
                f"{_position_label(int(result['position']))}."
            )
    if name == "remove_slot":
        removed = before.get(int(payload["slot_id"]))
        if removed:
            return f"Removed {removed['label']} from {_position_label(removed['position'])}."
    if name == "replace_slot":
        slot_id = int(result["slot_id"])
        old = before.get(slot_id)
        new = after.get(slot_id)
        if old and new:
            return (
                f"Replaced {old['label']} with {new['label']} at "
                f"{_position_label(new['position'])}."
            )
    if name in {"lock_slot", "unlock_slot"}:
        slot = before.get(int(result["slot_id"]))
        verb = "Locked" if result.get("locked") else "Unlocked"
        where = _position_label(slot["position"]) if slot else f"slot {result['slot_id']}"
        return f"{verb} {where}."
    if name in {"insert_from_pool", "search_and_insert"}:
        position = int(result["position"])
        inserted = next((s for s in after.values() if s["position"] == position), None)
        label = inserted["label"] if inserted else "a pool track"
        return f"Added {label} at {_position_label(position)}."
    if name == "bump_energy":
        updated = int(result.get("updated") or 0)
        amount = float(payload["amount"])
        direction = "Raised" if amount >= 0 else "Lowered"
        return (
            f"{direction} target energy by {abs(amount):g} across {updated} "
            f"slot{'s' if updated != 1 else ''}."
        )
    if name == "set_peak_at":
        position = int(payload["position"])
        slot = next((s for s in after.values() if s["position"] == position), None)
        label = f" {slot['label']}" if slot else ""
        return (
            f"Set {_position_label(position)}{label} as the energy peak at "
            f"{float(result['target_energy']):g}."
        )
    if name == "add_slow_window":
        label = str(result.get("label") or "Slow window")
        return (
            f"Added slow window {label} from {int(result['t0_sec'])}s to {int(result['t1_sec'])}s."
        )
    if name == "set_curve_point":
        label = result.get("label")
        suffix = f" ({label})" if label else ""
        return (
            f"Set curve point at {int(result['position_sec'])}s to energy "
            f"{int(result['energy'])}{suffix}."
        )
    if name == "remove_curve_point":
        return f"Removed curve point at {int(result['removed_position_sec'])}s."
    if name == "apply_curve_template":
        shape = str(payload.get("builtin") or "saved template")
        count = len(result.get("targets") or [])
        return f"Applied curve template {shape} to {count} slot{'s' if count != 1 else ''}."
    if name == "analyze_transition":
        base = (
            f"Analyzed transition into {_position_label(int(result['position']))}: "
            f"{round(float(result['score']))}."
        )
        warnings = result.get("warnings") or []
        if warnings:
            readable = ", ".join(str(warning).replace("_", " ") for warning in warnings)
            return f"{base} Warnings: {readable}."
        return base
    if name == "explain_transition":
        base = f"Explained transition into {_position_label(int(result['position']))}."
        explanations = result.get("explanations") or []
        if explanations:
            details = " ".join(str(item.get("detail") or "") for item in explanations)
            return f"{base} {details}".strip()
        return f"{base} No transition issues."
    if name == "get_track_vibes":
        where = _position_label(int(result["position"]))
        if not result.get("has_vibe"):
            return f"No vibe tags on record for {where}."
        resolved = result.get("resolved") or {}
        parts = []
        if resolved.get("energy") is not None:
            parts.append(f"energy {resolved['energy']} ({resolved.get('energy_source')})")
        if resolved.get("mood"):
            parts.append(f"mood {resolved['mood']} ({resolved.get('mood_source')})")
        return f"Vibe tags for {where}: {', '.join(parts)}."
    if name == "set_target":
        return _set_target_summary(result)
    if name == "summarize_set":
        return _summarize_set_summary(result)
    if name == "analyze_pool_gaps":
        missing = result.get("missing_camelot_keys") or []
        sparse = result.get("sparse_bands") or []
        return (
            f"Analyzed pool gaps over {int(result.get('pool_size') or 0)} tracks: "
            f"{len(missing)} missing Camelot key{'s' if len(missing) != 1 else ''}, "
            f"{len(sparse)} sparse BPM band{'s' if len(sparse) != 1 else ''}."
        )
    if name == "critique_set":
        grade = result.get("overall_grade")
        if grade:
            summary = str(result.get("summary") or "").strip()
            head = f"Critique grade {grade}."
            return f"{head} {summary}" if summary else head
        return "Recomputed critique context."
    return name.replace("_", " ").capitalize() + "."


def _set_target_summary(result: dict[str, Any]) -> str:
    """One human-readable sentence over only the target fields the call set."""
    parts: list[str] = []
    if "target_duration_sec" in result:
        secs = result["target_duration_sec"]
        if secs is None:
            parts.append("cleared duration target")
        else:
            parts.append(f"duration {int(secs) // 60} min")
    parts.extend(_bpm_window_summary_parts(result))
    if "key_strictness" in result:
        parts.append(f"key strictness {float(result['key_strictness']):g}")
    if "avg_transition_overlap_sec" in result:
        parts.append(f"transition overlap {int(result['avg_transition_overlap_sec'])}s")
    if not parts:
        return "Updated set targets."
    return "Set targets: " + ", ".join(parts) + "."


def _bpm_window_summary_parts(result: dict[str, Any]) -> list[str]:
    """Render the BPM bounds the call set: combined as a window when both are present."""
    floor, ceiling = result.get("bpm_floor"), result.get("bpm_ceiling")
    has_floor, has_ceiling = "bpm_floor" in result, "bpm_ceiling" in result
    if has_floor and has_ceiling and floor is not None and ceiling is not None:
        return [f"BPM {int(floor)}-{int(ceiling)}"]
    parts: list[str] = []
    if has_floor:
        parts.append("cleared BPM floor" if floor is None else f"BPM floor {int(floor)}")
    if has_ceiling:
        parts.append("cleared BPM ceiling" if ceiling is None else f"BPM ceiling {int(ceiling)}")
    return parts


def _summarize_set_summary(result: dict[str, Any]) -> str:
    count = int(result.get("slot_count") or 0)
    total = int(result.get("total_duration_sec") or 0)
    parts = [f"Set has {count} slot{'s' if count != 1 else ''}, {total // 60} min total"]
    delta = result.get("duration_delta_sec")
    if delta is not None and delta != 0:
        over_under = "over" if delta > 0 else "under"
        parts.append(f"{abs(int(delta)) // 60} min {over_under} target")
    arc = result.get("bpm_arc")
    if arc:
        parts.append(f"BPM {arc['min']:g}-{arc['max']:g}")
    return "; ".join(parts) + "."
