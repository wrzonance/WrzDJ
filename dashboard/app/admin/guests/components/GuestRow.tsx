'use client';

import type { AdminGuest } from '@/lib/api';
import { formatRelativeAge } from '@/lib/format-time';
import { GUEST_TABLE_COLUMNS, guestDisplayName } from './guest-format';

interface GuestRowProps {
  guest: AdminGuest;
  expanded: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
}

function EmailCell({ guest }: { guest: AdminGuest }) {
  if (!guest.email_verified) {
    return <span className="badge badge-tone-neutral">Unverified</span>;
  }
  return (
    <>
      <span className="badge badge-tone-success">Verified</span>
      <div className="guest-meta">{guest.email_masked}</div>
      {guest.email_verified_at && (
        <div className="guest-meta guest-meta-tight">
          on {new Date(guest.email_verified_at).toLocaleDateString()}
        </div>
      )}
    </>
  );
}

function HumanCell({ guest }: { guest: AdminGuest }) {
  if (!guest.human_verified_at || guest.human_verify_count === 0) {
    return <span className="guest-muted">Never</span>;
  }
  const passes = guest.human_verify_count === 1 ? '1 pass' : `${guest.human_verify_count} passes`;
  return (
    <>
      <span className="guest-signal-ok">{passes}</span>
      <div className="guest-meta">{formatRelativeAge(guest.human_verified_at)}</div>
    </>
  );
}

function FingerprintCell({ guest }: { guest: AdminGuest }) {
  if (!guest.fingerprint_short) {
    return <span className="badge badge-tone-neutral">None</span>;
  }
  const shared = guest.fingerprint_shared_with > 0;
  return (
    <>
      <span className={`badge ${shared ? 'badge-tone-warning' : 'badge-tone-success'}`}>
        {shared ? `Shared ×${guest.fingerprint_shared_with}` : 'Unique'}
      </span>
      <div className="guest-meta guest-fp">{guest.fingerprint_short}</div>
    </>
  );
}

function MembershipList({ guest }: { guest: AdminGuest }) {
  return (
    <ul className="guest-membership-list" aria-label={`Events joined by ${guestDisplayName(guest)}`}>
      {guest.events.map((membership) => (
        <li key={membership.event_id}>
          <span className="guest-fp">{membership.code}</span>
          <span>{membership.name}</span>
          <span className="guest-meta">
            {membership.nickname ? `as ${membership.nickname}` : 'no nickname'}
          </span>
          <span className="guest-meta">
            {membership.submission_count === 1
              ? '1 submission'
              : `${membership.submission_count} submissions`}
          </span>
          <span className="guest-meta">
            joined {new Date(membership.joined_at).toLocaleDateString()}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function GuestRow({ guest, expanded, onToggle, onEdit, onDelete }: GuestRowProps) {
  const eventLabel = guest.event_count === 1 ? '1 event' : `${guest.event_count} events`;
  return (
    <>
      <tr>
        <td>
          {guest.nickname ? (
            <span className="guest-name">{guest.nickname}</span>
          ) : (
            <span className="guest-muted">No name yet</span>
          )}
          <div className="guest-meta guest-meta-row">
            <span>#{guest.id}</span>
            {guest.browser && <span>{guest.browser}</span>}
          </div>
        </td>
        <td>
          <EmailCell guest={guest} />
        </td>
        <td>
          <HumanCell guest={guest} />
        </td>
        <td>
          <FingerprintCell guest={guest} />
        </td>
        <td>{new Date(guest.created_at).toLocaleDateString()}</td>
        <td>{formatRelativeAge(guest.last_seen_at)}</td>
        <td>
          <button
            type="button"
            className="btn btn-sm btn-secondary"
            onClick={onToggle}
            disabled={guest.event_count === 0}
            aria-expanded={expanded}
          >
            {eventLabel}
          </button>
        </td>
        <td>
          <div className="guest-actions">
            <button type="button" className="btn btn-sm btn-primary" onClick={onEdit}>
              Edit
            </button>
            <button type="button" className="btn btn-sm btn-danger" onClick={onDelete}>
              Delete
            </button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="admin-table-detail">
          <td colSpan={GUEST_TABLE_COLUMNS}>
            <MembershipList guest={guest} />
          </td>
        </tr>
      )}
    </>
  );
}
