import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SetDetail } from '@/lib/api/types';
import SetActionsMenu from '../SetActionsMenu';
import { api } from '@/lib/api';

const push = vi.fn();
vi.mock('next/navigation', () => ({ useRouter: () => ({ push }) }));
vi.mock('@/lib/api', () => ({ api: { duplicateSet: vi.fn() } }));
vi.mock('../ShareDialog', () => ({
  default: ({ onChanged, onClose }: { onChanged: (token: string | null) => void; onClose: () => void }) => (
    <div role="dialog" aria-label="Share set">
      <button onClick={() => onChanged('share-token')}>Share changed</button>
      <button onClick={onClose}>Close share</button>
    </div>
  ),
}));
vi.mock('../SaveAsTemplateDialog', () => ({
  default: ({ onSaved, onClose }: { onSaved: () => void; onClose: () => void }) => (
    <div role="dialog" aria-label="Save template">
      <button onClick={onSaved}>Template saved</button>
      <button onClick={onClose}>Close template</button>
    </div>
  ),
}));
vi.mock('../components/ExportModal', () => ({
  default: ({ onSetUpdated, onClose }: { onSetUpdated: (patch: Partial<SetDetail>) => void; onClose: () => void }) => (
    <div role="dialog" aria-label="Export set">
      <button onClick={() => onSetUpdated({ name: 'Updated' })}>Set updated</button>
      <button onClick={onClose}>Close export</button>
    </div>
  ),
}));

const set = { id: 12, share_token: null } as SetDetail;

function renderMenu(onShareChanged = vi.fn(), onSetUpdated = vi.fn()) {
  return { onShareChanged, onSetUpdated, ...render(
    <SetActionsMenu set={set} onShareChanged={onShareChanged} onSetUpdated={onSetUpdated} />,
  ) };
}

describe('SetActionsMenu', () => {
  beforeEach(() => vi.clearAllMocks());

  it('duplicates the set and navigates to the returned set', async () => {
    vi.mocked(api.duplicateSet).mockResolvedValue({ id: 35 } as SetDetail);
    renderMenu();

    fireEvent.click(screen.getByRole('button', { name: 'Duplicate' }));

    await waitFor(() => expect(push).toHaveBeenCalledWith('/setbuilder/35'));
    expect(api.duplicateSet).toHaveBeenCalledWith(12);
  });

  it('reports duplicate failure and re-enables the action', async () => {
    vi.mocked(api.duplicateSet).mockRejectedValue(new Error('offline'));
    renderMenu();

    fireEvent.click(screen.getByRole('button', { name: 'Duplicate' }));

    expect(await screen.findByText('Duplicate failed')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Duplicate' })).toBeEnabled();
  });

  it('forwards share and export updates and reports template saves', () => {
    const { onShareChanged, onSetUpdated } = renderMenu();
    fireEvent.click(screen.getByRole('button', { name: 'Share' }));
    fireEvent.click(screen.getByRole('button', { name: 'Share changed' }));
    expect(onShareChanged).toHaveBeenCalledWith('share-token');
    fireEvent.click(screen.getByRole('button', { name: 'Close share' }));

    fireEvent.click(screen.getByRole('button', { name: 'Export' }));
    fireEvent.click(screen.getByRole('button', { name: 'Set updated' }));
    expect(onSetUpdated).toHaveBeenCalledWith({ name: 'Updated' });
    fireEvent.click(screen.getByRole('button', { name: 'Close export' }));

    fireEvent.click(screen.getByRole('button', { name: 'Save as Template' }));
    fireEvent.click(screen.getByRole('button', { name: 'Template saved' }));
    expect(screen.getByText('Saved as template')).toBeInTheDocument();
    expect(screen.queryByRole('dialog', { name: 'Save template' })).not.toBeInTheDocument();
  });
});
