import { act, render, screen, waitFor, fireEvent } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { SetDocumentSnapshot } from '@/lib/api-types';
import { useSetDocumentHistory } from '../useSetDocumentHistory';

const mockApi = vi.hoisted(() => ({
  getSetDocument: vi.fn(),
  putSetDocument: vi.fn(),
}));

vi.mock('@/lib/api', () => ({ api: mockApi }));

function snapshot(targetEnergy: number | null): SetDocumentSnapshot {
  return {
    settings: {
      vibe_theme: null,
      target_duration_sec: null,
      bpm_floor: null,
      bpm_ceiling: null,
      key_strictness: 0.2,
    },
    slots: [
      {
        id: 1,
        position: 0,
        track_id: 'manual:1',
        locked: false,
        notes: null,
        transition_score: null,
        transition_warnings: null,
        target_energy: targetEnergy,
      },
    ],
    curve_points: [],
    pool: { sources: [], tracks: [] },
  };
}

function clone(doc: SetDocumentSnapshot): SetDocumentSnapshot {
  return JSON.parse(JSON.stringify(doc)) as SetDocumentSnapshot;
}

async function flushReact() {
  await act(async () => {
    await Promise.resolve();
  });
}

function Harness({ mutate }: { mutate: () => Promise<void> }) {
  const history = useSetDocumentHistory(5);
  return (
    <div>
      <div data-testid="undo-depth">{history.undoDepth}</div>
      <div data-testid="redo-depth">{history.redoDepth}</div>
      <div data-testid="dirty">{String(history.isDirty)}</div>
      <div data-testid="undo-label">{history.nextUndoLabel ?? ''}</div>
      <div data-testid="redo-label">{history.nextRedoLabel ?? ''}</div>
      <div data-testid="slot-target">{history.snapshot?.slots[0]?.target_energy ?? 'none'}</div>
      <button onClick={() => void history.commit('Retarget slot 1', mutate)}>commit</button>
      <button onClick={() => void history.undo()}>undo</button>
      <button onClick={() => void history.redo()}>redo</button>
      <button onClick={() => void history.saveNow()}>save</button>
    </div>
  );
}

describe('useSetDocumentHistory', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    let serverDoc = snapshot(null);
    mockApi.getSetDocument.mockImplementation(() => Promise.resolve(clone(serverDoc)));
    mockApi.putSetDocument.mockImplementation((_setId: number, doc: SetDocumentSnapshot) => {
      serverDoc = clone(doc);
      return Promise.resolve(clone(serverDoc));
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('records labeled commits, undo restores the prior snapshot, and redo restores the later one', async () => {
    let serverDoc = snapshot(null);
    mockApi.getSetDocument.mockImplementation(() => Promise.resolve(clone(serverDoc)));
    mockApi.putSetDocument.mockImplementation((_setId: number, doc: SetDocumentSnapshot) => {
      serverDoc = clone(doc);
      return Promise.resolve(clone(serverDoc));
    });

    render(<Harness mutate={() => Promise.resolve().then(() => void (serverDoc = snapshot(8.5)))} />);

    await waitFor(() => expect(screen.getByTestId('slot-target')).toHaveTextContent('none'));
    fireEvent.click(screen.getByText('commit'));

    await waitFor(() => expect(screen.getByTestId('undo-depth')).toHaveTextContent('1'));
    expect(screen.getByTestId('undo-label')).toHaveTextContent('Retarget slot 1');
    expect(screen.getByTestId('slot-target')).toHaveTextContent('8.5');

    fireEvent.click(screen.getByText('undo'));
    await waitFor(() => expect(screen.getByTestId('slot-target')).toHaveTextContent('none'));
    expect(screen.getByTestId('redo-depth')).toHaveTextContent('1');
    expect(screen.getByTestId('redo-label')).toHaveTextContent('Retarget slot 1');
    expect(mockApi.putSetDocument).toHaveBeenLastCalledWith(5, snapshot(null));

    fireEvent.click(screen.getByText('redo'));
    await waitFor(() => expect(screen.getByTestId('slot-target')).toHaveTextContent('8.5'));
    expect(mockApi.putSetDocument).toHaveBeenLastCalledWith(5, snapshot(8.5));
  });

  it('manual save writes the current snapshot without adding history depth', async () => {
    render(<Harness mutate={() => Promise.resolve()} />);

    await waitFor(() => expect(mockApi.getSetDocument).toHaveBeenCalledWith(5));
    fireEvent.click(screen.getByText('save'));

    await waitFor(() => expect(mockApi.putSetDocument).toHaveBeenCalledWith(5, snapshot(null)));
    expect(screen.getByTestId('undo-depth')).toHaveTextContent('0');
  });

  it('autosaves every 30s while dirty after a failed save', async () => {
    vi.useFakeTimers();
    mockApi.putSetDocument.mockRejectedValueOnce(new Error('network failed'));
    render(<Harness mutate={() => Promise.resolve()} />);

    await flushReact();
    expect(mockApi.getSetDocument).toHaveBeenCalledWith(5);
    fireEvent.click(screen.getByText('save'));

    await flushReact();
    expect(screen.getByTestId('dirty')).toHaveTextContent('true');
    mockApi.putSetDocument.mockResolvedValue(clone(snapshot(null)));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });

    expect(screen.getByTestId('dirty')).toHaveTextContent('false');
    expect(mockApi.putSetDocument).toHaveBeenCalledTimes(2);
  });
});
