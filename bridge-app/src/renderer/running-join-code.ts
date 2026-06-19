import type { EventInfo } from '../shared/types.js';

/**
 * Pick the join code to display for the *running* bridge.
 *
 * The running bridge's authoritative identifier is its collection code
 * (`status.eventCode`). The join code lives on the selected event, but the
 * event list stays clickable while the bridge runs — so the selection can
 * diverge from what's actually running. Only surface the selected event's join
 * code when it still matches the running event; otherwise return null so the
 * caller falls back to the authoritative running code rather than showing a
 * different event's join code.
 */
export function runningJoinCode(
  selectedEvent: EventInfo | null,
  runningEventCode: string | null,
): string | null {
  if (!selectedEvent || runningEventCode === null) {
    return null;
  }
  return selectedEvent.code === runningEventCode ? selectedEvent.joinCode : null;
}
