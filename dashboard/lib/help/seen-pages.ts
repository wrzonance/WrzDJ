/**
 * Module-level store for help pages the user has already seen.
 * Shared between AuthProvider (writes after /me) and HelpContext (reads).
 */
const seenPages = new Set<string>();

/**
 * Account-wide opt-out marker. Stored through the same `/help-seen` channel as a
 * page id (it has to match the backend's `^[a-z0-9-]+$` page pattern). Once
 * present, no page auto-starts its tour again; tours stay reachable from the
 * help button.
 */
export const TOURS_SKIPPED = 'tours-skipped';

/** localStorage fallback keys: `wrzdj-help-seen-<id>`; the owner key records whose they are. */
export const SEEN_KEY_PREFIX = 'wrzdj-help-seen-';
const OWNER_KEY = 'wrzdj-help-seen-owner';

export function seenStorageKey(id: string): string {
  return `${SEEN_KEY_PREFIX}${id}`;
}

/**
 * Replace the server-initialised set. When `ownerId` names a different account
 * than the browser fallback belongs to, the fallback keys are purged first so one
 * account's skip never silences tours for the next person on a shared browser.
 */
export function initSeenPages(pages: string[], ownerId?: number | string) {
  seenPages.clear();
  pages.forEach((p) => seenPages.add(p));
  if (ownerId !== undefined) claimFallbackStorage(String(ownerId));
}

export function isPageSeen(page: string): boolean {
  return seenPages.has(page);
}

export function markPageSeen(page: string) {
  seenPages.add(page);
}

function claimFallbackStorage(ownerId: string): void {
  if (typeof localStorage === 'undefined') return;
  try {
    if (localStorage.getItem(OWNER_KEY) === ownerId) return;
    const stale = Array.from({ length: localStorage.length }, (_, i) => localStorage.key(i))
      .filter((key): key is string => !!key && key.startsWith(SEEN_KEY_PREFIX) && key !== OWNER_KEY);
    stale.forEach((key) => localStorage.removeItem(key));
    localStorage.setItem(OWNER_KEY, ownerId);
  } catch {
    // localStorage unavailable (privacy mode): the server copy is still authoritative.
  }
}
