import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BridgeStatusCard } from '../BridgeStatusCard';
import { api } from '@/lib/api';

describe('BridgeStatusCard', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('shows the disconnected state and disables bridge commands', () => {
    render(<BridgeStatusCard eventCode="PARTY" bridgeConnected={false} />);

    expect(screen.getByText('Bridge Not Connected')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Ping' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Reconnect' })).toBeDisabled();
  });

  it('renders supplied connection details and formats uptime', () => {
    render(
      <BridgeStatusCard
        eventCode="PARTY"
        bridgeConnected
        bridgeDetails={{
          circuitBreakerState: 'HALF_OPEN',
          bufferSize: 3,
          pluginId: 'serato',
          deckCount: 2,
          uptimeSeconds: 3665,
        }}
      />,
    );

    expect(screen.getByText('Bridge Connected')).toBeInTheDocument();
    expect(screen.getByText('HALF_OPEN')).toBeInTheDocument();
    expect(screen.getByText('3 tracks')).toBeInTheDocument();
    expect(screen.getByText('1h 1m')).toBeInTheDocument();
  });

  it('sends a selected command and surfaces request failures', async () => {
    const send = vi.spyOn(api, 'sendBridgeCommand').mockRejectedValue(new Error('Bridge did not respond'));
    render(<BridgeStatusCard eventCode="PARTY" bridgeConnected />);

    fireEvent.click(screen.getByRole('button', { name: 'Ping' }));

    expect(await screen.findByText('Bridge did not respond')).toBeInTheDocument();
    expect(send).toHaveBeenCalledWith('PARTY', 'ping');
  });

  it('requires confirmation before restarting and sends restart only after confirmation', async () => {
    const send = vi.spyOn(api, 'sendBridgeCommand').mockResolvedValue({
      command_id: 'cmd-1',
      command_type: 'restart',
      payload: {},
    });
    render(<BridgeStatusCard eventCode="PARTY" bridgeConnected />);

    fireEvent.click(screen.getByRole('button', { name: 'Restart' }));
    expect(screen.getByText('This will briefly disconnect from your equipment. Continue?')).toBeInTheDocument();
    expect(send).not.toHaveBeenCalled();

    fireEvent.click(screen.getAllByRole('button', { name: 'Restart' })[1]);
    expect(send).toHaveBeenCalledWith('PARTY', 'restart');
    expect(await screen.findByRole('button', { name: 'Restart' })).toBeDisabled();
  });
});
