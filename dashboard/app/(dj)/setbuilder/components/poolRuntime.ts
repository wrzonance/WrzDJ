import { effectiveDurationSec, type TargetSettings } from './targetMath';

// Mirror of the backend builder constants (server/app/services/setbuilder/
// pass1_deterministic.py): the avg fallback for a missing/<=0 track duration and
// the 3-hour hard cap used when no explicit target is set (#538). Kept in sync so
// the build-dialog projection matches what the engine will actually produce.
export const AVG_TRACK_LENGTH_SEC = 210;
export const DEFAULT_FALLBACK_SET_DURATION_SEC = 3 * 60 * 60;

export interface PoolRuntimeTrack {
  duration_sec: number | null;
}

/**
 * Total candidate runtime of a pool, in seconds — Σ duration_sec with the avg
 * fallback for missing/non-positive durations (matches the backend
 * pool.pool_runtime_sec so the dialog and server agree).
 */
export function poolRuntimeSec(tracks: readonly PoolRuntimeTrack[]): number {
  return tracks.reduce(
    (acc, t) => acc + (t.duration_sec && t.duration_sec > 0 ? t.duration_sec : AVG_TRACK_LENGTH_SEC),
    0,
  );
}

/**
 * How many slots the generated set will hold, mirroring the engine's
 * overlap-aware, duration-accumulating stop (pass1_deterministic.build_set):
 * walk the candidate durations, subtracting transition overlaps, and stop once
 * the effective playtime reaches the target (or the 3h fallback when no target).
 * Bounded by the pool size, so it never claims more slots than the pool can fill.
 */
export function projectedSlotCount(
  tracks: readonly PoolRuntimeTrack[],
  settings: TargetSettings,
): number {
  const target =
    settings.targetDurationSec && settings.targetDurationSec > 0
      ? settings.targetDurationSec
      : DEFAULT_FALLBACK_SET_DURATION_SEC;
  const overlap = Math.max(0, Math.round(settings.avgTransitionOverlapSec));

  let total = 0;
  let count = 0;
  for (const track of tracks) {
    const dur = track.duration_sec && track.duration_sec > 0 ? track.duration_sec : AVG_TRACK_LENGTH_SEC;
    total += dur;
    count += 1;
    if (effectiveDurationSec(total, count, overlap) >= target) break;
  }
  return count;
}
