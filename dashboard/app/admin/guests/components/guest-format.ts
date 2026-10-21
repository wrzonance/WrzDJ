import type { AdminGuest } from '@/lib/api';

/** Columns in the guests table; the expanded membership row spans them all. */
export const GUEST_TABLE_COLUMNS = 8;

/** The name an admin sees for a guest: newest event nickname, else the id. */
export function guestDisplayName(guest: AdminGuest): string {
  return guest.nickname ?? `guest #${guest.id}`;
}
