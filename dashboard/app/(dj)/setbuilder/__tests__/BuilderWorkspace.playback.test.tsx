import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { POOL_TRACKS, SLOTS, largePoolTracks, largeSlots, mockGetPool, mockGetSetSlots, mockSendTransportCommand } from './BuilderWorkspaceTestSupport';
import BuilderWorkspace from '../components/BuilderWorkspace';

describe('BuilderWorkspace', () => {


  it('play queues a Tidal Bridge command for the current slot', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('transport-bar')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Play' }));

    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(1));
    expect(mockSendTransportCommand).toHaveBeenCalledWith(
      5,
      expect.objectContaining({
        action: 'play',
        source: 'tidal',
        slot_index: 0,
        track_id: 'a',
        title: 'Track A',
      }),
    );
    expect(screen.getByTestId('timeline-vu-0')).toBeInTheDocument();
  });

  it('double-clicking a timeline row jumps and plays that slot', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toBeInTheDocument());

    fireEvent.doubleClick(screen.getByTestId('timeline-row-1'));

    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(1));
    expect(mockSendTransportCommand).toHaveBeenCalledWith(
      5,
      expect.objectContaining({
        action: 'play',
        slot_index: 1,
        position_sec: 0,
        title: 'Track B',
      }),
    );
    expect(screen.getByTestId('timeline-vu-1')).toBeInTheDocument();
  });

  it('virtualizes hundreds of timeline rows while preserving visible row actions', async () => {
    // Regression for 7459707: large timelines must not mount every row.
    const slots = largeSlots(400);
    const tracks = largePoolTracks(400);
    mockGetSetSlots.mockResolvedValue(slots);
    mockGetPool.mockResolvedValue({ sources: [], tracks });

    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-0')).toBeInTheDocument());

    expect(screen.getByTestId('timeline-list')).toHaveAttribute('data-virtualized', 'true');
    expect(screen.queryAllByTestId(/^timeline-row-/).length).toBeLessThan(60);

    fireEvent.doubleClick(screen.getByTestId('timeline-row-1'));

    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(1));
    expect(mockSendTransportCommand).toHaveBeenCalledWith(
      5,
      expect.objectContaining({
        action: 'play',
        slot_index: 1,
        title: 'Large Track 1',
      }),
    );
  });

  it('click-to-scrub queues a seek command and keeps the active row in sync', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toBeInTheDocument());
    fireEvent.doubleClick(screen.getByTestId('timeline-row-1'));
    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId('curve-scrub-hit'), { clientX: 0 });

    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(2));
    expect(mockSendTransportCommand).toHaveBeenLastCalledWith(
      5,
      expect.objectContaining({
        action: 'seek',
        slot_index: 0,
        position_sec: 0,
      }),
    );
    expect(screen.getByTestId('timeline-vu-0')).toBeInTheDocument();
  });

  it('auto-pauses Bridge when playback reaches the end of the set', async () => {
    mockGetSetSlots.mockResolvedValue([SLOTS[0]]);
    mockGetPool.mockResolvedValue({
      sources: [],
      tracks: [{ ...POOL_TRACKS[0], duration_sec: 1 }],
    });

    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('transport-bar')).toBeInTheDocument());

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole('button', { name: 'Play' }));
    expect(mockSendTransportCommand).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(mockSendTransportCommand).toHaveBeenCalledTimes(2);
    expect(mockSendTransportCommand).toHaveBeenLastCalledWith(
      5,
      expect.objectContaining({
        action: 'pause',
        slot_index: 0,
        position_sec: 1,
      }),
    );
    expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument();
  });

  it('scrubs when clicking a curve block covered by the block hit target', async () => {
    render(<BuilderWorkspace setId={5} />);
    await waitFor(() => expect(screen.getByTestId('timeline-row-1')).toBeInTheDocument());
    fireEvent.doubleClick(screen.getByTestId('timeline-row-1'));
    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByTestId('slot-block-0'), { clientX: 0 });

    await waitFor(() => expect(mockSendTransportCommand).toHaveBeenCalledTimes(2));
    expect(mockSendTransportCommand).toHaveBeenLastCalledWith(
      5,
      expect.objectContaining({
        action: 'seek',
        slot_index: 0,
        position_sec: 0,
      }),
    );
  });
});
