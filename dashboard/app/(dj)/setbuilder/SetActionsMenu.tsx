'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import type { SetDetail } from '@/lib/api-types';
import ShareDialog from './ShareDialog';
import ExportModal from './components/ExportModal';

interface SetActionsMenuProps {
  set: SetDetail;
  /** Lets the builder page keep its copy of the set in sync after share changes. */
  onShareChanged: (token: string | null) => void;
  /** Lets the builder page keep its copy of the set in sync after export. */
  onSetUpdated: (patch: Partial<SetDetail>) => void;
}

/** Export + Duplicate + Share actions for the builder topbar. */
export default function SetActionsMenu({ set, onShareChanged, onSetUpdated }: SetActionsMenuProps) {
  const router = useRouter();
  const [shareOpen, setShareOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [duplicating, setDuplicating] = useState(false);
  const [error, setError] = useState(false);

  const duplicate = async () => {
    setDuplicating(true);
    setError(false);
    try {
      const dup = await api.duplicateSet(set.id);
      router.push(`/setbuilder/${dup.id}`);
    } catch {
      setError(true);
      setDuplicating(false);
    }
  };

  return (
    <span style={{ display: 'inline-flex', gap: '0.5rem', alignItems: 'center' }}>
      {error && (
        <span style={{ color: 'var(--color-danger)', fontSize: '0.75rem' }}>Duplicate failed</span>
      )}
      <button
        type="button"
        className="btn btn-sm"
        style={{ background: 'var(--surface-raised)' }}
        onClick={() => setExportOpen(true)}
      >
        Export
      </button>
      <button
        type="button"
        className="btn btn-sm"
        style={{ background: 'var(--surface-raised)' }}
        disabled={duplicating}
        onClick={duplicate}
      >
        {duplicating ? 'Duplicating…' : 'Duplicate'}
      </button>
      <button
        type="button"
        className="btn btn-sm"
        style={{ background: 'var(--surface-raised)' }}
        onClick={() => setShareOpen(true)}
      >
        {set.share_token ? 'Shared' : 'Share'}
      </button>
      {exportOpen && (
        <ExportModal
          set={set}
          onClose={() => setExportOpen(false)}
          onSetUpdated={onSetUpdated}
        />
      )}
      {shareOpen && (
        <ShareDialog set={set} onClose={() => setShareOpen(false)} onChanged={onShareChanged} />
      )}
    </span>
  );
}
