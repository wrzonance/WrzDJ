import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Suspense } from 'react';
import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import type { SetDetail } from '@/lib/api/types';
import BuilderPage from '../page';
import { useBuilderPairings } from '../useBuilderPairings';
import type { ConfirmAction } from '../../components/ConfirmActionDialog';

const mocks = vi.hoisted(() => ({
  push: vi.fn(),
  lastConfirm: null as (() => void) | null,
  auth: { isAuthenticated: true, isLoading: false, role: 'dj' as string | null },
  api: {
    getSet: vi.fn(),
    getPairings: vi.fn(),
    buildSet: vi.fn(),
    updateSetTargetSettings: vi.fn(),
  },
  history: {
    snapshot: { slots: [], pool: { tracks: [] } },
    snapshotVersion: 0,
    commit: vi.fn(),
    isDirty: false,
    isSaving: false,
    saveError: null,
    lastSavedAt: null,
    saveNow: vi.fn(),
    undoDepth: 0,
    redoDepth: 0,
    nextUndoLabel: null,
    nextRedoLabel: null,
    undo: vi.fn(),
    redo: vi.fn(),
    toast: null,
    autosave: true,
    setAutosave: vi.fn(),
  },
}));

vi.mock('next/navigation', () => ({ useRouter: () => ({ push: mocks.push }) }));
vi.mock('next/link', () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));
vi.mock('@/lib/auth', () => ({ useAuth: () => mocks.auth }));
vi.mock('@/lib/api', () => ({ api: mocks.api }));
vi.mock('../../components/useIsMobile', () => ({ useIsMobile: () => false }));
vi.mock('../../components/useSetDocumentHistory', () => ({ useSetDocumentHistory: () => mocks.history }));
vi.mock('../../components/BuilderBrandMenu', () => ({ default: ({ name, onSettings }: { name: string; onSettings: () => void }) => (
  <><span data-testid="set-name">{name}</span><button onClick={onSettings}>Builder settings</button></>
) }));
vi.mock('../../components/BuilderWorkspace', () => ({
  default: (props: {
    confirmRecompute: boolean;
    jumpSlotRequest: { idx: number; requestId: number } | null;
    refreshToken: number;
    onOpenPairings: (pairingId?: number | null) => void;
  }) => (
    <div>
      <div data-testid="confirm-recompute">{String(props.confirmRecompute)}</div>
      <div data-testid="workspace-refresh-token">{props.refreshToken}</div>
      <div data-testid="jump-slot-request">
        {props.jumpSlotRequest ? `${props.jumpSlotRequest.idx}|${props.jumpSlotRequest.requestId}` : 'none'}
      </div>
      <button type="button" onClick={() => props.onOpenPairings(42)}>Open selected pairing</button>
    </div>
  ),
}));
vi.mock('../../components/chat/ChatSidebar', () => ({ default: () => null }));
vi.mock('../../components/MobileAgentOverlay', () => ({ default: () => null }));
vi.mock('../../components/pairings/PairingsOverlay', () => ({
  default: (props: {
    open: boolean;
    initialPairingId: number | null;
    onClose: () => void;
    onChanged: (count?: number) => void;
    onJumpSlot: (idx: number) => void;
  }) => {
    return (
      <div data-testid="pairings-overlay">
        <div data-testid="pairings-overlay-state">
          {props.open ? 'open' : 'closed'}|{props.initialPairingId ?? 'none'}
        </div>
        <button type="button" onClick={props.onClose}>Close mocked pairings</button>
        <button type="button" onClick={() => props.onChanged(9)}>Report mocked pairing change</button>
        <button type="button" onClick={() => props.onJumpSlot(3)}>Jump from mocked pairings</button>
      </div>
    );
  },
}));
vi.mock('../../components/PlaybackReportOverlay', () => ({ default: () => null }));
vi.mock('../../components/pool/PoolPanel', () => ({ default: () => null }));
vi.mock('../../components/TargetEditor', () => ({
  default: ({ settings, dirty, saving, onSettingsChange, onSave, onUndo }: {
    settings: { targetDurationSec: number | null; avgTransitionOverlapSec: number };
    dirty: boolean;
    saving: boolean;
    onSettingsChange: (settings: { targetDurationSec: number | null; avgTransitionOverlapSec: number }) => void;
    onSave: () => void;
    onUndo: () => void;
  }) => (
    <div>
      <div data-testid="target-settings">
        {settings.targetDurationSec ?? 'none'}|{settings.avgTransitionOverlapSec}
      </div>
      <div data-testid="target-dirty">{String(dirty)}</div>
      <button
        type="button"
        onClick={() => onSettingsChange({ targetDurationSec: 3600, avgTransitionOverlapSec: 15 })}
      >
        Set target draft
      </button>
      <button type="button" onClick={onSave} disabled={!dirty || saving}>Save target</button>
      <button type="button" onClick={onUndo}>Undo target</button>
    </div>
  ),
}));
vi.mock('../../components/HistoryControls', () => ({ default: () => null }));
vi.mock('../../components/ConfirmActionDialog', () => ({
  default: ({ action, onCancel, onConfirm }: {
    action: ConfirmAction | null;
    onCancel: () => void;
    onConfirm: () => void;
  }) => {
    if (!action) return null;
    mocks.lastConfirm = onConfirm;
    return (
      <div className="modalBackdrop" onMouseDown={onCancel}>
        <div role="alertdialog" aria-label={action.title} onMouseDown={(event) => event.stopPropagation()}>
          <h2>{action.title}</h2>
          {action.body}
          <button type="button" onClick={onCancel}>Cancel</button>
          <button type="button" onClick={onConfirm}>{action.confirmLabel}</button>
        </div>
      </div>
    );
  },
}));
vi.mock('../../SetActionsMenu', () => ({ default: () => null }));
vi.mock('@/components/ThemeToggle', () => ({ ThemeToggle: () => null }));

const loadedSet = {
  id: 7,
  name: 'Friday Set',
  target_duration_sec: null,
  avg_transition_overlap_sec: 10,
  event_id: null,
} as SetDetail;

function routeElement(setId: string) {
  const params = Object.assign(Promise.resolve({ setId }), {
    status: 'fulfilled',
    value: { setId },
  });
  return (
    <Suspense fallback={<div>Loading route</div>}>
      <BuilderPage params={params} />
    </Suspense>
  );
}

function renderRoute(setId = '7') {
  return render(routeElement(setId));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

beforeEach(() => {
  mocks.push.mockReset();
  mocks.auth.isAuthenticated = true;
  mocks.auth.isLoading = false;
  mocks.auth.role = 'dj';
  mocks.api.getSet.mockReset().mockResolvedValue(loadedSet);
  mocks.api.getPairings.mockReset().mockResolvedValue({ count: 0, pairings: [] });
  mocks.api.updateSetTargetSettings.mockReset().mockResolvedValue(loadedSet);
  mocks.api.buildSet.mockReset().mockResolvedValue({ slot_count: 4, iterations: 2 });
  mocks.history.commit.mockReset().mockImplementation(async (_label: string, action: () => Promise<unknown>) => action());
  window.localStorage.clear();
});

afterEach(() => vi.clearAllMocks());

describe('Setbuilder route', () => {
  it('redirects unauthenticated and pending users to their allowed routes', async () => {
    mocks.auth.isAuthenticated = false;
    const first = renderRoute();
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith('/login'));
    first.unmount();

    mocks.push.mockClear();
    mocks.auth.isAuthenticated = true;
    mocks.auth.role = 'pending';
    renderRoute();
    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith('/pending'));
  });

  // Regression for baseline 57cfcdc6867f: routing a pending account away must
  // not issue protected set or pairing requests before the redirect completes.
  it('does not load protected set or pairing data for a pending user', async () => {
    mocks.auth.role = 'pending';
    renderRoute();

    await waitFor(() => expect(mocks.push).toHaveBeenCalledWith('/pending'));
    expect(mocks.api.getSet).not.toHaveBeenCalled();
    expect(mocks.api.getPairings).not.toHaveBeenCalled();
  });

  // Regression for baseline 57cfcdc6867f: protected resources wait until auth
  // finishes loading, even when the cached session says the user is signed in.
  it('does not load protected set or pairing data while authentication is loading', async () => {
    mocks.auth.isLoading = true;
    renderRoute();

    expect(await screen.findByText('Loading...')).toBeInTheDocument();
    expect(mocks.api.getSet).not.toHaveBeenCalled();
    expect(mocks.api.getPairings).not.toHaveBeenCalled();
  });

  // Regression for baseline 57cfcdc6867f: a previous set's late count response
  // must not overwrite the count loaded for the newly selected set.
  it('ignores a stale pairing-count response after the set id changes', async () => {
    const oldSetRequest = deferred<{ count: number; pairings: never[] }>();
    const newSetRequest = deferred<{ count: number; pairings: never[] }>();
    mocks.api.getPairings.mockImplementation((setId: number) => (
      setId === 7 ? oldSetRequest.promise : newSetRequest.promise
    ));
    const { result, rerender } = renderHook(
      ({ setId }) => useBuilderPairings(setId, true, () => {}),
      { initialProps: { setId: 7 } },
    );

    rerender({ setId: 8 });
    await waitFor(() => expect(mocks.api.getPairings).toHaveBeenCalledWith(8));
    await act(async () => newSetRequest.resolve({ count: 8, pairings: [] }));
    expect(result.current.count).toBe(8);

    await act(async () => oldSetRequest.resolve({ count: 7, pairings: [] }));
    expect(result.current.count).toBe(8);
  });

  it('saves target settings and synchronizes the saved values back into the editor', async () => {
    const updatedSet = {
      ...loadedSet,
      target_duration_sec: 3600,
      avg_transition_overlap_sec: 15,
    } as SetDetail;
    mocks.api.updateSetTargetSettings.mockResolvedValue(updatedSet);
    renderRoute();

    await waitFor(() => expect(screen.getByTestId('target-settings')).toHaveTextContent('none|10'));
    fireEvent.click(screen.getByRole('button', { name: 'Set target draft' }));
    expect(screen.getByTestId('target-dirty')).toHaveTextContent('true');
    fireEvent.click(screen.getByRole('button', { name: 'Save target' }));

    await waitFor(() => {
      expect(mocks.api.updateSetTargetSettings).toHaveBeenCalledWith(7, 3600, 15);
      expect(screen.getByTestId('target-settings')).toHaveTextContent('3600|15');
      expect(screen.getByTestId('target-dirty')).toHaveTextContent('false');
    });
  });

  it('undoes target drafts and keeps them editable after a save error', async () => {
    mocks.api.updateSetTargetSettings.mockRejectedValue(new Error('target unavailable'));
    renderRoute();
    await waitFor(() => expect(screen.getByTestId('target-settings')).toHaveTextContent('none|10'));

    fireEvent.click(screen.getByRole('button', { name: 'Set target draft' }));
    fireEvent.click(screen.getByRole('button', { name: 'Undo target' }));
    expect(screen.getByTestId('target-settings')).toHaveTextContent('none|10');
    expect(screen.getByTestId('target-dirty')).toHaveTextContent('false');

    fireEvent.click(screen.getByRole('button', { name: 'Set target draft' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save target' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('target unavailable');
    expect(screen.getByTestId('target-dirty')).toHaveTextContent('true');
    expect(screen.getByRole('button', { name: 'Save target' })).toBeEnabled();
  });

  it('renders a recoverable error when the set cannot be loaded', async () => {
    mocks.api.getSet.mockRejectedValue(new Error('private backend detail'));
    renderRoute();
    expect(await screen.findByText('Set not found')).toBeInTheDocument();
    expect(screen.queryByText('private backend detail')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Back to Sets' })).toHaveAttribute('href', '/setbuilder');
  });

  it('does not let an old set response replace the set loaded after route change', async () => {
    const oldSetRequest = deferred<SetDetail>();
    const newSetRequest = deferred<SetDetail>();
    mocks.api.getSet.mockImplementation((setId: number) => (
      setId === 7 ? oldSetRequest.promise : newSetRequest.promise
    ));
    const view = renderRoute('7');

    view.rerender(routeElement('8'));
    await waitFor(() => expect(mocks.api.getSet).toHaveBeenCalledWith(8));
    await act(async () => newSetRequest.resolve({ ...loadedSet, id: 8, name: 'Saturday Set' }));
    expect(await screen.findByTestId('set-name')).toHaveTextContent('Saturday Set');

    await act(async () => oldSetRequest.resolve(loadedSet));
    expect(screen.getByTestId('set-name')).toHaveTextContent('Saturday Set');
  });

  // Regression for baseline 57cfcdc6867f: a transient pairing refresh failure
  // must preserve the known badge count and offer a retry instead of implying empty.
  it('preserves the pairing count and exposes retry when refreshing the count fails', async () => {
    mocks.api.getPairings
      .mockResolvedValueOnce({ count: 3, pairings: [] })
      .mockRejectedValueOnce(new Error('temporary network failure'))
      .mockResolvedValueOnce({ count: 4, pairings: [] });
    renderRoute();

    const pairingsButton = await screen.findByRole('button', { name: 'Open pairings (3)' });
    fireEvent.click(pairingsButton);

    expect(await screen.findByRole('alert')).toHaveTextContent('Could not refresh saved pairings.');
    expect(screen.getByRole('button', { name: 'Open pairings (3)' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Retry pairing count' }));

    expect(await screen.findByRole('button', { name: 'Open pairings (4)' })).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('coordinates pairing open, initial selection, changes, and workspace jumps', async () => {
    const staleOpenRefresh = deferred<{ count: number; pairings: never[] }>();
    mocks.api.getPairings
      .mockResolvedValueOnce({ count: 0, pairings: [] })
      .mockReturnValueOnce(staleOpenRefresh.promise);
    renderRoute();
    await screen.findByRole('button', { name: 'Open pairings (0)' });
    expect(screen.getByTestId('workspace-refresh-token')).toHaveTextContent('0');

    fireEvent.click(screen.getByRole('button', { name: 'Open selected pairing' }));
    await waitFor(() => expect(mocks.api.getPairings).toHaveBeenCalledTimes(2));
    expect(screen.getByTestId('pairings-overlay-state')).toHaveTextContent('open|42');

    fireEvent.click(screen.getByRole('button', { name: 'Jump from mocked pairings' }));
    expect(screen.getByTestId('jump-slot-request')).toHaveTextContent('3|1');

    fireEvent.click(screen.getByRole('button', { name: 'Report mocked pairing change' }));
    expect(screen.getByRole('button', { name: 'Open pairings (9)' })).toBeInTheDocument();
    expect(screen.getByTestId('workspace-refresh-token')).toHaveTextContent('1');
    await act(async () => staleOpenRefresh.resolve({ count: 0, pairings: [] }));
    expect(screen.getByRole('button', { name: 'Open pairings (9)' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Close mocked pairings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open pairings (9)' }));
    expect(screen.getByTestId('pairings-overlay-state')).toHaveTextContent('open|none');
  });

  it('loads persisted builder preferences and writes changed settings', async () => {
    window.localStorage.setItem('wrzdj.setbuilder.settings', JSON.stringify({ confirmRecompute: false }));
    renderRoute();
    expect(await screen.findByTestId('confirm-recompute')).toHaveTextContent('false');

    fireEvent.click(screen.getByRole('button', { name: 'Builder settings' }));
    const suggestReplacements = screen.getByRole('checkbox', { name: /energy mismatch prompt/i });
    expect(suggestReplacements).toBeChecked();
    fireEvent.click(suggestReplacements);
    await waitFor(() => {
      expect(JSON.parse(window.localStorage.getItem('wrzdj.setbuilder.settings') ?? '{}'))
        .toMatchObject({ confirmRecompute: false, suggestReplacements: false });
      expect(window.localStorage.getItem('wrzdj.curve.suggestReplacements')).toBe('false');
    });
  });

  it('confirms recompute and commits the build through the history boundary', async () => {
    renderRoute();
    await screen.findByRole('button', { name: 'Recompute' });
    fireEvent.click(screen.getByRole('button', { name: 'Recompute' }));
    expect(await screen.findByRole('alertdialog', { name: 'Recompute set order?' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Yes, recompute' }));

    await waitFor(() => {
      expect(mocks.history.commit).toHaveBeenCalledWith('Recompute set order', expect.any(Function));
      expect(mocks.api.buildSet).toHaveBeenCalledWith(7, true);
      expect(screen.getByRole('status')).toHaveTextContent('Pass 1 rebuilt 4 slots');
    });
  });

  // Regression for baseline 57cfcdc6867f: dismissing a destructive confirmation
  // must never invoke the build operation.
  it('cancels recompute without building', async () => {
    renderRoute();
    fireEvent.click(await screen.findByRole('button', { name: 'Recompute' }));
    expect(await screen.findByRole('alertdialog', { name: 'Recompute set order?' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(mocks.api.buildSet).not.toHaveBeenCalled();
    expect(mocks.history.commit).not.toHaveBeenCalled();
  });

  it('cancels a pending recompute confirmation when the route changes', async () => {
    const view = renderRoute('7');
    fireEvent.click(await screen.findByRole('button', { name: 'Recompute' }));
    expect(await screen.findByRole('alertdialog', { name: 'Recompute set order?' })).toBeInTheDocument();

    view.rerender(routeElement('8'));
    const staleConfirm = mocks.lastConfirm;
    await act(async () => staleConfirm?.());

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(mocks.api.buildSet).not.toHaveBeenCalled();
  });

  it('settles a pending confirmation as cancelled on unmount', async () => {
    const view = renderRoute('7');
    fireEvent.click(await screen.findByRole('button', { name: 'Recompute' }));
    await screen.findByRole('alertdialog', { name: 'Recompute set order?' });
    const staleConfirm = mocks.lastConfirm;

    view.unmount();
    await act(async () => staleConfirm?.());

    expect(mocks.api.buildSet).not.toHaveBeenCalled();
  });

  it('keeps an in-flight old-set build from publishing into the new route', async () => {
    const buildRequest = deferred<{ slot_count: number; iterations: number }>();
    mocks.api.getSet.mockImplementation(async (setId: number) => ({
      ...loadedSet,
      id: setId,
      name: setId === 7 ? 'Friday Set' : 'Saturday Set',
    }) as SetDetail);
    mocks.api.buildSet.mockReturnValue(buildRequest.promise);
    const view = renderRoute('7');

    fireEvent.click(await screen.findByRole('button', { name: 'Recompute' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Yes, recompute' }));
    await waitFor(() => expect(mocks.api.buildSet).toHaveBeenCalledWith(7, true));

    view.rerender(routeElement('8'));
    expect(await screen.findByTestId('set-name')).toHaveTextContent('Saturday Set');
    await act(async () => buildRequest.resolve({ slot_count: 4, iterations: 2 }));

    expect(screen.getByTestId('set-name')).toHaveTextContent('Saturday Set');
    expect(screen.queryByText(/Pass 1 rebuilt/)).not.toBeInTheDocument();
  });

  // Regression for baseline 57cfcdc6867f: clicking outside the dialog is also
  // a cancel action, not an implicit confirmation.
  it('dismisses recompute on backdrop without building', async () => {
    const { container } = renderRoute();
    fireEvent.click(await screen.findByRole('button', { name: 'Recompute' }));
    expect(await screen.findByRole('alertdialog', { name: 'Recompute set order?' })).toBeInTheDocument();

    const backdrop = container.querySelector('[class*="modalBackdrop"]');
    expect(backdrop).not.toBeNull();
    fireEvent.mouseDown(backdrop!);

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(mocks.api.buildSet).not.toHaveBeenCalled();
    expect(mocks.history.commit).not.toHaveBeenCalled();
  });
});
