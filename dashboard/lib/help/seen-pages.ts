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

export function initSeenPages(pages: string[]) {
  seenPages.clear();
  pages.forEach((p) => seenPages.add(p));
}

export function isPageSeen(page: string): boolean {
  return seenPages.has(page);
}

export function markPageSeen(page: string) {
  seenPages.add(page);
}
