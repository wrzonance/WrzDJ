import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { POOL_TRACKS, documentSnapshot, documentWithVibeWindow, mockApplyCurveTemplate, mockGetPool, mockGetVibeWindows, mockPutVibeWindows } from './BuilderWorkspaceTestSupport';
import BuilderWorkspace from '../components/BuilderWorkspace';

describe('BuilderWorkspace', () => {


  it('adding a vibe preset window persists via PUT', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('slot-block-0')).toBeInTheDocument());
    await waitFor(() => expect(mockGetVibeWindows).toHaveBeenCalledWith(5));

    fireEvent.click(screen.getByTestId('vibe-dropdown-trigger'));
    fireEvent.click(screen.getByTestId('vibe-preset-first-dance'));

    await waitFor(() => expect(mockPutVibeWindows).toHaveBeenCalledTimes(1));
    const [, windows] = mockPutVibeWindows.mock.calls[0];
    expect(windows).toHaveLength(1);
    expect(windows[0].label).toBe('First Dance');
    expect(await screen.findByText('FIRST DANCE')).toBeInTheDocument();
  });

  it('keeps a vibe preset when the initial windows load resolves late', async () => {
    let resolveInitialWindows!: (response: {
      windows: { t0_sec: number; t1_sec: number; label: string }[];
    }) => void;
    mockGetVibeWindows.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveInitialWindows = resolve;
      }),
    );
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('slot-block-0')).toBeInTheDocument());
    await waitFor(() => expect(mockGetVibeWindows).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId('vibe-dropdown-trigger'));
    fireEvent.click(screen.getByTestId('vibe-preset-first-dance'));

    expect(mockPutVibeWindows).not.toHaveBeenCalled();
    await act(async () => {
      resolveInitialWindows({ windows: [{ t0_sec: 15, t1_sec: 30, label: 'Saved window' }] });
    });
    expect(await screen.findByText('FIRST DANCE')).toBeInTheDocument();
    expect(await screen.findByText('SAVED WINDOW')).toBeInTheDocument();
    await waitFor(() => expect(mockPutVibeWindows).toHaveBeenCalledTimes(1));
    const [, windows] = mockPutVibeWindows.mock.calls[0];
    expect(windows.map((window: { label: string }) => window.label)).toEqual([
      'Saved window',
      'First Dance',
    ]);
  });

  it('merges a pending preset with a snapshot that arrives during the initial load', async () => {
    mockGetVibeWindows.mockReturnValueOnce(new Promise(() => {}));
    const { rerender } = render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(mockGetVibeWindows).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId('vibe-dropdown-trigger'));
    fireEvent.click(screen.getByTestId('vibe-preset-first-dance'));
    expect(mockPutVibeWindows).not.toHaveBeenCalled();

    rerender(
      <BuilderWorkspace setId={5} snapshot={documentWithVibeWindow('Saved window')} snapshotVersion={1} />,
    );

    expect(await screen.findByText('FIRST DANCE')).toBeInTheDocument();
    expect(await screen.findByText('SAVED WINDOW')).toBeInTheDocument();
    await waitFor(() => expect(mockPutVibeWindows).toHaveBeenCalledTimes(1));
    const [, windows] = mockPutVibeWindows.mock.calls[0];
    expect(windows.map((window: { label: string }) => window.label)).toEqual([
      'Saved window',
      'First Dance',
    ]);
  });

  it('restores vibe windows from a later document snapshot', async () => {
    const { rerender } = render(
      <BuilderWorkspace setId={5} snapshot={documentWithVibeWindow('Original')} snapshotVersion={1} />,
    );
    expect(await screen.findByText('ORIGINAL')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('vibe-dropdown-trigger'));
    fireEvent.click(screen.getByTestId('vibe-preset-first-dance'));
    expect(await screen.findByText('FIRST DANCE')).toBeInTheDocument();
    rerender(
      <BuilderWorkspace setId={5} snapshot={documentWithVibeWindow('Restored')} snapshotVersion={2} />,
    );

    expect(await screen.findByText('RESTORED')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('FIRST DANCE')).not.toBeInTheDocument());
  });

  it('does not restore an old snapshot when slot duration changes', async () => {
    const snapshot = documentWithVibeWindow('Original');
    const { rerender } = render(<BuilderWorkspace setId={5} snapshot={snapshot} snapshotVersion={1} />);
    expect(await screen.findByText('ORIGINAL')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('vibe-dropdown-trigger'));
    fireEvent.click(screen.getByTestId('vibe-preset-first-dance'));
    expect(await screen.findByText('FIRST DANCE')).toBeInTheDocument();
    const initialScale = screen.getByTestId('curve-canvas').getAttribute('data-px-per-second');

    mockGetPool.mockResolvedValueOnce({
      sources: [],
      tracks: POOL_TRACKS.map((track) => ({
        ...track,
        duration_sec: (track.duration_sec ?? 210) + 30,
      })),
    });
    rerender(
      <BuilderWorkspace
        setId={5}
        refreshToken={1}
        snapshot={snapshot}
        snapshotVersion={1}
      />,
    );

    await waitFor(() =>
      expect(screen.getByTestId('curve-canvas').getAttribute('data-px-per-second')).not.toBe(
        initialScale,
      ),
    );
    expect(await screen.findByText('FIRST DANCE')).toBeInTheDocument();
  });

  it('restores the saved windows when returning to a set edited before its first snapshot', async () => {
    const { rerender } = render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('slot-block-0')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('vibe-dropdown-trigger'));
    fireEvent.click(screen.getByTestId('vibe-preset-first-dance'));
    expect(await screen.findByText('FIRST DANCE')).toBeInTheDocument();

    rerender(
      <BuilderWorkspace setId={6} snapshot={documentWithVibeWindow('Set Six')} snapshotVersion={1} />,
    );
    expect(await screen.findByText('SET SIX')).toBeInTheDocument();

    rerender(
      <BuilderWorkspace setId={5} snapshot={documentWithVibeWindow('Set Five Saved')} snapshotVersion={2} />,
    );

    expect(await screen.findByText('SET FIVE SAVED')).toBeInTheDocument();
    expect(screen.queryByText('SET SIX')).not.toBeInTheDocument();
  });

  it('keeps another set initial load when a pending template finishes after navigation', async () => {
    let resolveTemplate!: (response: {
      targets: { slot_id: number; target_energy: number }[];
      windows: { t0: number; t1: number }[];
    }) => void;
    let resolveSetSixWindows!: (response: {
      windows: { t0_sec: number; t1_sec: number; label: string }[];
    }) => void;
    mockApplyCurveTemplate.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveTemplate = resolve;
      }),
    );
    mockGetVibeWindows.mockImplementation((requestedSetId: number) =>
      requestedSetId === 6
        ? new Promise((resolve) => {
            resolveSetSixWindows = resolve;
          })
        : Promise.resolve({ windows: [] }),
    );

    const { rerender } = render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('curve-toolbar')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('template-dropdown-trigger'));
    await waitFor(() => expect(screen.getByTestId('apply-builtin-Club Peak')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('apply-builtin-Club Peak'));
    await waitFor(() => expect(mockApplyCurveTemplate).toHaveBeenCalledWith(5, { builtin: 'Club Peak' }, expect.any(Array)));

    rerender(<BuilderWorkspace setId={6} />);
    await waitFor(() => expect(mockGetVibeWindows).toHaveBeenCalledWith(6));

    await act(async () => {
      resolveTemplate({ targets: [], windows: [{ t0: 0.25, t1: 0.5 }] });
    });
    await waitFor(() => expect(mockPutVibeWindows).toHaveBeenCalledWith(5, expect.any(Array)));
    await act(async () => {
      resolveSetSixWindows({
        windows: [{ t0_sec: 60, t1_sec: 90, label: 'Set Six Saved' }],
      });
    });

    expect(await screen.findByText('SET SIX SAVED')).toBeInTheDocument();
    expect(screen.queryByText('SLOW SET')).not.toBeInTheDocument();
  });

  it('clears the active template label when switching sets', async () => {
    mockApplyCurveTemplate.mockResolvedValue({ targets: [], windows: [] });
    const { rerender } = render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('curve-toolbar')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('template-dropdown-trigger'));
    await waitFor(() => expect(screen.getByTestId('apply-builtin-Club Peak')).toBeInTheDocument());
    fireEvent.click(screen.getByTestId('apply-builtin-Club Peak'));

    await waitFor(() =>
      expect(screen.getByTestId('template-dropdown-trigger')).toHaveTextContent('Club Peak'),
    );
    rerender(<BuilderWorkspace setId={6} />);

    await waitFor(() =>
      expect(screen.getByTestId('template-dropdown-trigger')).toHaveTextContent('Pick curve'),
    );
  });

  it('persists both vibe presets added in one batch', async () => {
    render(<BuilderWorkspace setId={5} snapshot={documentSnapshot()} />);
    await waitFor(() => expect(screen.getByTestId('slot-block-0')).toBeInTheDocument());

    fireEvent.click(screen.getByTestId('vibe-dropdown-trigger'));
    const preset = screen.getByTestId('vibe-preset-first-dance');
    act(() => {
      fireEvent.click(preset);
      fireEvent.click(preset);
    });

    await waitFor(() => expect(mockPutVibeWindows).toHaveBeenCalledTimes(2));
    const [, windows] = mockPutVibeWindows.mock.calls[1];
    expect(windows).toHaveLength(2);
    expect(windows.map((window: { label: string }) => window.label)).toEqual([
      'First Dance',
      'First Dance',
    ]);
    expect(await screen.findAllByText('FIRST DANCE')).toHaveLength(2);
  });
});
