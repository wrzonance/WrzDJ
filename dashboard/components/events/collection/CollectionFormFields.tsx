'use client';

import { z } from 'zod';

export const collectionSchema = z
  .object({
    collection_opens_at: z.string().optional(),
    live_starts_at: z.string().optional(),
    submission_cap_per_guest: z.number().int().min(0).max(100).optional(),
  })
  .refine(
    (value) => {
      if (value.collection_opens_at && value.live_starts_at) {
        return new Date(value.collection_opens_at) < new Date(value.live_starts_at);
      }
      return true;
    },
    { message: 'Collection opens must be before live starts' },
  );

export interface CollectionFormFieldsProps {
  collectionOpensAt: string;
  onCollectionOpensAtChange: (next: string) => void;
  liveStartsAt: string;
  onLiveStartsAtChange: (next: string) => void;
  submissionCap: number;
  onSubmissionCapChange: (next: number) => void;
  error?: string | null;
}

export function CollectionFormFields({
  collectionOpensAt,
  onCollectionOpensAtChange,
  liveStartsAt,
  onLiveStartsAtChange,
  submissionCap,
  onSubmissionCapChange,
  error,
}: CollectionFormFieldsProps) {
  return (
    <>
      <div className="form-group">
        <label htmlFor="collection-opens-at">Collection opens at</label>
        <input
          id="collection-opens-at"
          type="datetime-local"
          className="input"
          value={collectionOpensAt}
          onChange={(event) => onCollectionOpensAtChange(event.target.value)}
        />
      </div>
      <div className="form-group">
        <label htmlFor="live-starts-at">Live starts at</label>
        <input
          id="live-starts-at"
          type="datetime-local"
          className="input"
          value={liveStartsAt}
          onChange={(event) => onLiveStartsAtChange(event.target.value)}
        />
      </div>
      <div className="form-group">
        <label htmlFor="submission-cap">Submission cap per guest</label>
        <input
          id="submission-cap"
          type="number"
          min={0}
          max={100}
          className="input collection-fieldset-cap"
          value={submissionCap}
          onChange={(event) => onSubmissionCapChange(Number(event.target.value))}
        />
        <p className="collection-fieldset-hint">0 = unlimited picks per guest</p>
      </div>
      {error && <p className="collection-fieldset-error">{error}</p>}
    </>
  );
}
