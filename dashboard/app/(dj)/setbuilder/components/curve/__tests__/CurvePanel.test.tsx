import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SetDocumentSnapshot } from '@/lib/api/types';
import type { SlotView } from '../../types';
import CurvePanel from '../CurvePanel';

const mockApi = vi.hoisted(() => ({
  getCurveTemplates: vi.fn(),
  createCurveTemplate: vi.fn(),
  updateCurveTemplate: vi.fn(),
  deleteCurveTemplate: vi.fn(),
  applyCurveTemplate: vi.fn(),
  getVibeWindows: vi.fn(),
  putVibeWindows: vi.fn(),
  updateSlotTarget: vi.fn(),
  getSetDocument: vi.fn(),
  putSetDocument: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ api: mockApi }));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function makeSlots(): SlotView[] {
  return [
    {
      id: 11,
      position: 0,
      locked: false,
      targetEnergy: null,
      transitionScore: null,
      nextPairingId: null,
      nextIsDjPairing: false,
      track: {
        id: 'track-1',
        title: 'Test track',
        artist: 'Test artist',
        durationSec: 600,
        energy: 5,
        bpm: 120,
        key: '8A',
      },
    },
  ];
}

function makeSnapshot(label: string, startSec = 100, endSec = 200): SetDocumentSnapshot {
  return {
    curve_points: [
      {
        id: 1,
        position_sec: startSec,
        energy: 5,
        is_slow_window_start: true,
        is_slow_window_end: false,
        label,
      },
      {
        id: 2,
        position_sec: endSec,
        energy: 5,
        is_slow_window_start: false,
        is_slow_window_end: true,
        label: null,
      },
    ],
    pool: { sources: [], tracks: [] },
    settings: {
      bpm_ceiling: null,
      bpm_floor: null,
      key_strictness: 0.2,
      target_duration_sec: null,
      vibe_theme: null,
    },
    slots: [],
  };
}

function makeReplacementSnapshot(): SetDocumentSnapshot {
  return {
    curve_points: [],
    pool: {
      sources: [],
      tracks: [
        {
          id: 71,
          track_id: 'replacement-track',
          title: 'Replacement track',
          artist: 'Replacement artist',
          album: null,
          artwork_url: null,
          bpm: 122,
          camelot: '8A',
          created_at: '2026-01-01T00:00:00Z',
          dedupe_sig: 'replacement-signature',
          duration_sec: 180,
          energy: 8,
          enrichment_status: 'enriched',
          genre: null,
          isrc: null,
          key: '8A',
          source_id: 1,
        },
      ],
    },
    settings: {
      bpm_ceiling: null,
      bpm_floor: null,
      key_strictness: 0.2,
      target_duration_sec: null,
      vibe_theme: null,
    },
    slots: [
      {
        id: 11,
        position: 0,
        track_id: 'track-1',
        locked: false,
        notes: null,
        transition_score: null,
        transition_warnings: null,
        target_energy: null,
      },
    ],
  };
}

function panelElement(setId = 1, snapshot?: SetDocumentSnapshot | null, snapshotVersion = 0) {
  return (
    <CurvePanel
      setId={setId}
      slots={makeSlots()}
      onSlotsChange={vi.fn()}
      hoveredIdx={null}
      onHover={vi.fn()}
      onBlockClick={vi.fn()}
      snapshot={snapshot}
      snapshotVersion={snapshotVersion}
      suggestReplacementsSetting={false}
    />
  );
}

function renderPanel(setId = 1, snapshot?: SetDocumentSnapshot | null, snapshotVersion = 0) {
  return render(panelElement(setId, snapshot, snapshotVersion));
}

async function addSlowDanceWindow() {
  fireEvent.click(screen.getByTestId('vibe-dropdown-trigger'));
  fireEvent.click(screen.getByTestId('vibe-preset-slow-dance'));
  await screen.findByText('SLOW DANCE');
}

beforeEach(() => {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.clearAllMocks();
  mockApi.getCurveTemplates.mockResolvedValue({ builtin: [], user: [] });
  mockApi.createCurveTemplate.mockResolvedValue({ id: 8, name: 'Created', points: [] });
  mockApi.updateCurveTemplate.mockResolvedValue({ id: 7, name: 'Updated', points: [] });
  mockApi.deleteCurveTemplate.mockResolvedValue(undefined);
  mockApi.putVibeWindows.mockResolvedValue({ windows: [] });
  mockApi.updateSlotTarget.mockResolvedValue({});
});

afterEach(() => vi.unstubAllGlobals());

describe('CurvePanel vibe-window orchestration', () => {
  it('queues an edit during initial load and persists it with the loaded windows', async () => {
    const load = deferred<{ windows: { t0_sec: number; t1_sec: number; label: string }[] }>();
    mockApi.getVibeWindows.mockReturnValue(load.promise);
    renderPanel();
    await waitFor(() => expect(mockApi.getVibeWindows).toHaveBeenCalledWith(1));

    await addSlowDanceWindow();
    expect(mockApi.putVibeWindows).not.toHaveBeenCalled();

    await act(async () => {
      load.resolve({ windows: [{ t0_sec: 60, t1_sec: 120, label: 'Loaded window' }] });
      await load.promise;
    });

    await waitFor(() => expect(mockApi.putVibeWindows).toHaveBeenCalledTimes(1));
    expect(mockApi.putVibeWindows).toHaveBeenCalledWith(1, [
      { t0_sec: 60, t1_sec: 120, label: 'Loaded window' },
      { t0_sec: 252, t1_sec: 300, label: 'Slow Dance' },
    ]);
    expect(screen.getByTestId('vibe-window-label-w-0-60')).toBeInTheDocument();
    expect(screen.getByText('SLOW DANCE')).toBeInTheDocument();
  });

  it('combines a local edit with the snapshot that arrives afterward', async () => {
    const load = deferred<{ windows: { t0_sec: number; t1_sec: number; label: string }[] }>();
    mockApi.getVibeWindows.mockReturnValue(load.promise);
    const view = renderPanel();
    await waitFor(() => expect(mockApi.getVibeWindows).toHaveBeenCalledWith(1));
    await addSlowDanceWindow();

    view.rerender(panelElement(1, makeSnapshot('Snapshot window', 120, 240), 1));

    await waitFor(() => expect(mockApi.putVibeWindows).toHaveBeenCalledTimes(1));
    expect(mockApi.putVibeWindows).toHaveBeenCalledWith(1, [
      { t0_sec: 120, t1_sec: 240, label: 'Snapshot window' },
      { t0_sec: 252, t1_sec: 300, label: 'Slow Dance' },
    ]);
    await act(async () => {
      load.resolve({ windows: [{ t0_sec: 30, t1_sec: 90, label: 'Stale load' }] });
      await load.promise;
    });
    expect(mockApi.putVibeWindows).toHaveBeenCalledTimes(1);
    expect(screen.queryByText('STALE LOAD')).not.toBeInTheDocument();
    expect(screen.getByText('SNAPSHOT WINDOW')).toBeInTheDocument();
    expect(screen.getByText('SLOW DANCE')).toBeInTheDocument();
  });

  it('persists an edit to its original set after switching during its initial load', async () => {
    // Regression at 57cfcdc6867f: switching sets used to cancel this queued write.
    const firstLoad = deferred<{ windows: { t0_sec: number; t1_sec: number; label: string }[] }>();
    const secondLoad = deferred<{ windows: { t0_sec: number; t1_sec: number; label: string }[] }>();
    mockApi.getVibeWindows.mockImplementation((setId: number) =>
      setId === 1 ? firstLoad.promise : secondLoad.promise,
    );
    const view = renderPanel(1);
    await waitFor(() => expect(mockApi.getVibeWindows).toHaveBeenCalledWith(1));
    await addSlowDanceWindow();

    view.rerender(panelElement(2));
    await waitFor(() => expect(mockApi.getVibeWindows).toHaveBeenCalledWith(2));

    await act(async () => {
      secondLoad.resolve({ windows: [{ t0_sec: 300, t1_sec: 420, label: 'Second set' }] });
      await secondLoad.promise;
    });
    expect(screen.getByText('SECOND SET')).toBeInTheDocument();
    expect(screen.queryByText('SLOW DANCE')).not.toBeInTheDocument();

    await act(async () => {
      firstLoad.resolve({ windows: [{ t0_sec: 60, t1_sec: 120, label: 'First set' }] });
      await firstLoad.promise;
    });

    await waitFor(() => expect(mockApi.putVibeWindows).toHaveBeenCalledTimes(1));
    expect(mockApi.putVibeWindows).toHaveBeenCalledWith(1, [
      { t0_sec: 60, t1_sec: 120, label: 'First set' },
      { t0_sec: 252, t1_sec: 300, label: 'Slow Dance' },
    ]);
    expect(screen.getByText('SECOND SET')).toBeInTheDocument();
    expect(screen.queryByText('FIRST SET')).not.toBeInTheDocument();
    expect(screen.queryByText('SLOW DANCE')).not.toBeInTheDocument();
  });

  it('keeps a pending write scoped to the prior set after switching', async () => {
    mockApi.getVibeWindows.mockImplementation(async (setId: number) => ({
      windows: [{ t0_sec: setId === 1 ? 60 : 300, t1_sec: setId === 1 ? 120 : 420, label: `Set ${setId}` }],
    }));
    const write = deferred<{ windows: [] }>();
    mockApi.putVibeWindows.mockReturnValue(write.promise);
    const view = renderPanel(1);
    await screen.findByText('SET 1');
    await addSlowDanceWindow();

    await waitFor(() => expect(mockApi.putVibeWindows).toHaveBeenCalledWith(1, expect.any(Array)));
    view.rerender(panelElement(2));
    await screen.findByText('SET 2');
    expect(screen.queryByText('SLOW DANCE')).not.toBeInTheDocument();

    await act(async () => {
      write.resolve({ windows: [] });
      await write.promise;
    });

    expect(mockApi.putVibeWindows).toHaveBeenCalledTimes(1);
    expect(mockApi.putVibeWindows.mock.calls[0][0]).toBe(1);
    expect(screen.getByText('SET 2')).toBeInTheDocument();
    expect(screen.queryByText('SLOW DANCE')).not.toBeInTheDocument();
  });

  it('does not apply a completed replacement to slots after switching sets', async () => {
    // Regression at 57cfcdc6867f: a delayed replacement updated the newly active set.
    const write = deferred<SetDocumentSnapshot>();
    const onSlotsChange = vi.fn();
    const pool = [
      {
        id: 'replacement-track',
        title: 'Replacement track',
        artist: 'Replacement artist',
        durationSec: 180,
        energy: 8,
        bpm: 122,
        key: '8A',
      },
    ];
    const element = (setId: number) => (
      <CurvePanel
        setId={setId}
        slots={makeSlots()}
        onSlotsChange={onSlotsChange}
        hoveredIdx={null}
        onHover={vi.fn()}
        onBlockClick={vi.fn()}
        pool={pool}
        suggestReplacementsSetting
      />
    );
    mockApi.getVibeWindows.mockResolvedValue({ windows: [] });
    mockApi.getSetDocument.mockResolvedValue(makeReplacementSnapshot());
    mockApi.putSetDocument.mockReturnValue(write.promise);
    const view = render(element(1));

    fireEvent.pointerDown(screen.getByTestId('target-handle-0'));
    fireEvent.pointerMove(window, { clientY: 44 });
    fireEvent.pointerUp(window);
    fireEvent.click(await screen.findByTestId('replace-candidate-replacement-track'));

    await waitFor(() => expect(mockApi.putSetDocument).toHaveBeenCalledWith(1, expect.anything()));
    const slotChangesBeforeSwitch = onSlotsChange.mock.calls.length;
    view.rerender(element(2));

    await act(async () => {
      write.resolve(makeReplacementSnapshot());
      await write.promise;
    });

    expect(onSlotsChange).toHaveBeenCalledTimes(slotChangesBeforeSwitch);
    expect(mockApi.getSetDocument).toHaveBeenCalledWith(1);
    expect(mockApi.putSetDocument).toHaveBeenCalledWith(1, expect.anything());
  });

  it('keeps a failed replacement available to retry and shows the save error', async () => {
    const onSlotsChange = vi.fn();
    const pool = [
      {
        id: 'replacement-track',
        title: 'Replacement track',
        artist: 'Replacement artist',
        durationSec: 180,
        energy: 8,
        bpm: 122,
        key: '8A',
      },
    ];
    mockApi.getVibeWindows.mockResolvedValue({ windows: [] });
    mockApi.getSetDocument.mockResolvedValue(makeReplacementSnapshot());
    mockApi.putSetDocument
      .mockRejectedValueOnce(new Error('Save unavailable'))
      .mockResolvedValueOnce(makeReplacementSnapshot());
    render(
      <CurvePanel
        setId={1}
        slots={makeSlots()}
        onSlotsChange={onSlotsChange}
        hoveredIdx={null}
        onHover={vi.fn()}
        onBlockClick={vi.fn()}
        pool={pool}
        suggestReplacementsSetting
      />,
    );

    fireEvent.pointerDown(screen.getByTestId('target-handle-0'));
    fireEvent.pointerMove(window, { clientY: 44 });
    fireEvent.pointerUp(window);
    const changesAfterRetarget = onSlotsChange.mock.calls.length;
    const candidate = await screen.findByTestId('replace-candidate-replacement-track');
    fireEvent.click(candidate);

    const error = await screen.findByRole('alert');
    expect(error).toHaveTextContent('Could not replace this track. Please try again.');
    expect(screen.getByTestId('replace-candidate-replacement-track')).toBeEnabled();
    expect(onSlotsChange).toHaveBeenCalledTimes(changesAfterRetarget);

    fireEvent.click(screen.getByTestId('replace-candidate-replacement-track'));

    await waitFor(() => expect(onSlotsChange).toHaveBeenCalledTimes(changesAfterRetarget + 1));
    expect(mockApi.putSetDocument).toHaveBeenCalledTimes(2);
    expect(screen.queryByTestId('replace-popover')).not.toBeInTheDocument();
  });

  it('does not apply a template after its confirmation belongs to a prior set', async () => {
    // Regression at 57cfcdc6867f: a stale confirmation could start a write after navigation.
    const confirmation = deferred<boolean>();
    const requestConfirmation = vi.fn(() => confirmation.promise);
    const element = (setId: number) => (
      <CurvePanel
        setId={setId}
        slots={makeSlots()}
        onSlotsChange={vi.fn()}
        hoveredIdx={null}
        onHover={vi.fn()}
        onBlockClick={vi.fn()}
        requestConfirmation={requestConfirmation}
      />
    );
    mockApi.getCurveTemplates.mockResolvedValue({
      builtin: [{ name: 'Warmup', points: [] }],
      user: [],
    });
    mockApi.getVibeWindows.mockResolvedValue({ windows: [] });
    const view = render(element(1));

    await waitFor(() => expect(mockApi.getCurveTemplates).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId('template-dropdown-trigger'));
    fireEvent.click(screen.getByTestId('apply-builtin-Warmup'));
    await waitFor(() => expect(requestConfirmation).toHaveBeenCalledTimes(1));

    view.rerender(element(2));
    await act(async () => {
      confirmation.resolve(true);
      await confirmation.promise;
    });

    expect(mockApi.applyCurveTemplate).not.toHaveBeenCalled();
  });

  it('keeps template results scoped to their original set after switching', async () => {
    const apply = deferred<{
      targets: { slot_id: number; target_energy: number | null }[];
      windows: { t0: number; t1: number }[];
    }>();
    const onSlotsChange = vi.fn();
    const element = (setId: number) => (
      <CurvePanel
        setId={setId}
        slots={makeSlots()}
        onSlotsChange={onSlotsChange}
        hoveredIdx={null}
        onHover={vi.fn()}
        onBlockClick={vi.fn()}
        confirmRecompute={false}
      />
    );
    mockApi.getCurveTemplates.mockResolvedValue({
      builtin: [{ name: 'Warmup', points: [] }],
      user: [],
    });
    mockApi.getVibeWindows.mockResolvedValue({ windows: [] });
    mockApi.applyCurveTemplate.mockReturnValue(apply.promise);
    const view = render(element(1));

    await waitFor(() => expect(mockApi.getCurveTemplates).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId('template-dropdown-trigger'));
    fireEvent.click(screen.getByTestId('apply-builtin-Warmup'));
    await waitFor(() => expect(mockApi.applyCurveTemplate).toHaveBeenCalledWith(1, { builtin: 'Warmup' }, [0.5]));

    view.rerender(element(2));
    await act(async () => {
      apply.resolve({ targets: [{ slot_id: 11, target_energy: 8 }], windows: [{ t0: 0.1, t1: 0.2 }] });
      await apply.promise;
    });

    await waitFor(() => expect(mockApi.putVibeWindows).toHaveBeenCalledWith(1, [
      { t0_sec: 60, t1_sec: 120, label: 'Slow set' },
    ]));
    expect(onSlotsChange).not.toHaveBeenCalled();
    expect(screen.getByTestId('template-dropdown-trigger')).toHaveTextContent('Pick curve…');
    expect(screen.queryByText('SLOW SET')).not.toBeInTheDocument();
  });

  it('keeps a new template draft open and retryable after a save failure', async () => {
    mockApi.createCurveTemplate
      .mockRejectedValueOnce(new Error('Template could not be saved'))
      .mockResolvedValueOnce({ id: 8, name: 'Late night arc', points: [] });
    renderPanel();

    await waitFor(() => expect(mockApi.getCurveTemplates).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId('template-dropdown-trigger'));
    fireEvent.click(screen.getByTestId('template-create-new'));
    fireEvent.change(screen.getByLabelText('Template name'), {
      target: { value: 'Late night arc' },
    });
    fireEvent.click(screen.getByTestId('template-save-as'));

    expect(await screen.findByRole('alert')).toHaveTextContent('Template could not be saved');
    expect(screen.getByRole('dialog', { name: 'Curve template editor' })).toBeInTheDocument();
    expect(screen.getByLabelText('Template name')).toHaveValue('Late night arc');

    fireEvent.click(screen.getByTestId('template-save-as'));

    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Curve template editor' })).not.toBeInTheDocument());
    expect(mockApi.createCurveTemplate).toHaveBeenCalledTimes(2);
    expect(mockApi.createCurveTemplate).toHaveBeenLastCalledWith('Late night arc', expect.any(Array));
  });

  it('offers a list-only retry when template creation succeeds but refresh fails', async () => {
    const created = { id: 8, name: 'Late night arc', points: [] };
    mockApi.getCurveTemplates
      .mockResolvedValueOnce({ builtin: [], user: [] })
      .mockRejectedValueOnce(new Error('List temporarily unavailable'))
      .mockResolvedValueOnce({ builtin: [], user: [created] });
    mockApi.createCurveTemplate.mockResolvedValueOnce(created);
    renderPanel();

    await waitFor(() => expect(mockApi.getCurveTemplates).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId('template-dropdown-trigger'));
    fireEvent.click(screen.getByTestId('template-create-new'));
    fireEvent.change(screen.getByLabelText('Template name'), {
      target: { value: 'Late night arc' },
    });
    fireEvent.click(screen.getByTestId('template-save-as'));

    expect(await screen.findByRole('alert')).toHaveTextContent('List temporarily unavailable');
    expect(screen.queryByRole('dialog', { name: 'Curve template editor' })).not.toBeInTheDocument();
    expect(mockApi.createCurveTemplate).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: 'Retry list refresh' }));

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(mockApi.getCurveTemplates).toHaveBeenCalledTimes(3);
    expect(mockApi.createCurveTemplate).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId('template-dropdown-trigger'));
    expect(screen.getByTestId('apply-user-8')).toBeInTheDocument();
  });

  it('keeps an edited template open and retryable after an update failure', async () => {
    mockApi.getCurveTemplates.mockResolvedValue({
      builtin: [],
      user: [{ id: 7, name: 'Existing curve', points: [], updated_at: '2026-01-01T00:00:00Z' }],
    });
    mockApi.updateCurveTemplate
      .mockRejectedValueOnce(new Error('Update failed'))
      .mockResolvedValueOnce({ id: 7, name: 'Updated curve', points: [] });
    renderPanel();

    await waitFor(() => expect(mockApi.getCurveTemplates).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId('template-dropdown-trigger'));
    fireEvent.click(screen.getByTestId('edit-user-7'));
    fireEvent.change(screen.getByLabelText('Template name'), {
      target: { value: 'Updated curve' },
    });
    fireEvent.click(screen.getByTestId('template-save'));

    expect(await screen.findByRole('alert')).toHaveTextContent('Update failed');
    expect(screen.getByLabelText('Template name')).toHaveValue('Updated curve');
    expect(screen.getByRole('dialog', { name: 'Curve template editor' })).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('template-save'));

    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Curve template editor' })).not.toBeInTheDocument());
    expect(mockApi.updateCurveTemplate).toHaveBeenCalledTimes(2);
    expect(mockApi.updateCurveTemplate).toHaveBeenLastCalledWith(7, 'Updated curve', expect.any(Array));
  });

  it('keeps a template editor open and retryable after delete failure', async () => {
    mockApi.getCurveTemplates.mockResolvedValue({
      builtin: [],
      user: [{ id: 7, name: 'Existing curve', points: [], updated_at: '2026-01-01T00:00:00Z' }],
    });
    mockApi.deleteCurveTemplate
      .mockRejectedValueOnce(new Error('Delete failed'))
      .mockResolvedValueOnce(undefined);
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderPanel();

    await waitFor(() => expect(mockApi.getCurveTemplates).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId('template-dropdown-trigger'));
    fireEvent.click(screen.getByTestId('edit-user-7'));
    fireEvent.click(screen.getByTestId('template-delete'));

    expect(await screen.findByRole('alert')).toHaveTextContent('Delete failed');
    expect(screen.getByRole('dialog', { name: 'Curve template editor' })).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('template-delete'));

    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Curve template editor' })).not.toBeInTheDocument());
    expect(mockApi.deleteCurveTemplate).toHaveBeenCalledTimes(2);
    expect(mockApi.deleteCurveTemplate).toHaveBeenLastCalledWith(7);
  });

  it('shows template apply failures and allows the same template to be retried', async () => {
    mockApi.getCurveTemplates.mockResolvedValue({
      builtin: [{ name: 'Warmup', points: [] }],
      user: [],
    });
    mockApi.applyCurveTemplate
      .mockRejectedValueOnce(new Error('Template placement failed'))
      .mockResolvedValueOnce({ targets: [{ slot_id: 11, target_energy: 7 }], windows: [] });
    mockApi.getVibeWindows.mockResolvedValue({ windows: [] });
    render(
      <CurvePanel
        setId={1}
        slots={makeSlots()}
        onSlotsChange={vi.fn()}
        hoveredIdx={null}
        onHover={vi.fn()}
        onBlockClick={vi.fn()}
        confirmRecompute={false}
      />,
    );

    await waitFor(() => expect(mockApi.getCurveTemplates).toHaveBeenCalled());
    fireEvent.click(screen.getByTestId('template-dropdown-trigger'));
    fireEvent.click(screen.getByTestId('apply-builtin-Warmup'));
    expect(await screen.findByRole('alert')).toHaveTextContent('Template placement failed');
    expect(screen.getByTestId('template-dropdown-trigger')).toHaveTextContent('Pick curve…');

    fireEvent.click(screen.getByTestId('template-dropdown-trigger'));
    fireEvent.click(screen.getByTestId('apply-builtin-Warmup'));

    await waitFor(() => expect(screen.getByTestId('template-dropdown-trigger')).toHaveTextContent('Warmup'));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(mockApi.applyCurveTemplate).toHaveBeenCalledTimes(2);
  });
});
