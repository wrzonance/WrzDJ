'use client';

import { Event, ArchivedEvent } from '@/lib/api';

interface EventCustomizationCardProps {
  event: Event | ArchivedEvent;
  uploadingBanner: boolean;
  onBannerSelect: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onDeleteBanner: () => void;
}

export function EventCustomizationCard({
  event,
  uploadingBanner,
  onBannerSelect,
  onDeleteBanner,
}: EventCustomizationCardProps) {
  return (
    <div className="card" style={{ marginBottom: '1rem', padding: '1rem' }}>
      <div style={{ marginBottom: '0.75rem' }}>
        <span style={{ fontWeight: 600 }}>Event Customization</span>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', margin: '0.25rem 0 0' }}>
          Personalize the kiosk display and join page
        </p>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div>
          <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>Event Banner</span>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.75rem', margin: '0.25rem 0 0' }}>
            Custom banner for kiosk display and join page (max 5MB)
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <label
            className="btn btn-sm btn-primary"
            style={{ cursor: 'pointer', margin: 0 }}
          >
            {uploadingBanner ? 'Uploading...' : event.banner_url ? 'Replace' : 'Upload'}
            <input
              type="file"
              accept="image/jpeg,image/png,image/gif,image/webp"
              style={{ display: 'none' }}
              onChange={onBannerSelect}
              disabled={uploadingBanner}
            />
          </label>
          {event.banner_url && (
            <button
              className="btn btn-sm btn-danger"
              onClick={onDeleteBanner}
              disabled={uploadingBanner}
            >
              Remove
            </button>
          )}
        </div>
      </div>
      {event.banner_url && (
        <div style={{ marginTop: '0.75rem' }}>
          <img
            src={event.banner_url}
            alt="Event banner"
            style={{
              width: '100%',
              maxHeight: '120px',
              objectFit: 'cover',
              borderRadius: '6px',
            }}
          />
        </div>
      )}
    </div>
  );
}
