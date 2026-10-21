import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { NetworkInterfaceInfo } from 'os';

import { detectSubnetConflicts, detectSubnetConflictsFrom } from '../network-check.js';
import os from 'os';

beforeEach(() => {
  vi.clearAllMocks();
});

/** Helper to create a mock IPv4 interface entry */
function ipv4(address: string, netmask: string, internal = false): NetworkInterfaceInfo {
  return {
    address,
    netmask,
    family: 'IPv4',
    mac: '00:00:00:00:00:00',
    internal,
    cidr: `${address}/24`,
  };
}

/** Helper to create a mock IPv6 interface entry */
function ipv6(address: string): NetworkInterfaceInfo {
  return {
    address,
    netmask: 'ffff:ffff:ffff:ffff::',
    family: 'IPv6',
    mac: '00:00:00:00:00:00',
    internal: false,
    cidr: `${address}/64`,
    scopeid: 0,
  };
}

describe('detectSubnetConflictsFrom (pure function)', () => {
  it('returns empty array when no conflicts exist', () => {
    const interfaces: Record<string, NetworkInterfaceInfo[]> = {
      eth0: [ipv4('192.168.1.100', '255.255.255.0')],
      wlan0: [ipv4('10.0.0.50', '255.255.255.0')],
    };

    const result = detectSubnetConflictsFrom(interfaces);
    expect(result).toEqual([]);
  });

  it('detects two interfaces on the same /24 subnet', () => {
    const interfaces: Record<string, NetworkInterfaceInfo[]> = {
      eth0: [ipv4('192.168.1.100', '255.255.255.0')],
      wlan0: [ipv4('192.168.1.200', '255.255.255.0')],
    };

    const result = detectSubnetConflictsFrom(interfaces);
    expect(result).toHaveLength(1);
    expect(result[0].subnet).toBe('192.168.1.0/24');
    expect(result[0].interfaces).toEqual([
      { name: 'eth0', address: '192.168.1.100' },
      { name: 'wlan0', address: '192.168.1.200' },
    ]);
  });

  it('detects conflicts on /16 subnets', () => {
    const interfaces: Record<string, NetworkInterfaceInfo[]> = {
      br0: [ipv4('172.16.5.1', '255.255.0.0')],
      wlan0: [ipv4('172.16.99.200', '255.255.0.0')],
    };

    const result = detectSubnetConflictsFrom(interfaces);
    expect(result).toHaveLength(1);
    expect(result[0].subnet).toBe('172.16.0.0/16');
  });

  it('detects three interfaces on the same subnet', () => {
    const interfaces: Record<string, NetworkInterfaceInfo[]> = {
      eth0: [ipv4('192.168.1.10', '255.255.255.0')],
      br0: [ipv4('192.168.1.33', '255.255.255.0')],
      wlan0: [ipv4('192.168.1.200', '255.255.255.0')],
    };

    const result = detectSubnetConflictsFrom(interfaces);
    expect(result).toHaveLength(1);
    expect(result[0].interfaces).toHaveLength(3);
  });

  it('ignores internal/loopback interfaces', () => {
    const interfaces: Record<string, NetworkInterfaceInfo[]> = {
      lo: [ipv4('127.0.0.1', '255.0.0.0', true)],
      eth0: [ipv4('192.168.1.100', '255.255.255.0')],
    };

    const result = detectSubnetConflictsFrom(interfaces);
    expect(result).toEqual([]);
  });

  it('ignores IPv6 addresses', () => {
    const interfaces: Record<string, NetworkInterfaceInfo[]> = {
      eth0: [ipv4('192.168.1.100', '255.255.255.0'), ipv6('fe80::1')],
      wlan0: [ipv6('fe80::2')],
    };

    const result = detectSubnetConflictsFrom(interfaces);
    expect(result).toEqual([]);
  });

  it('returns empty array for empty interfaces', () => {
    const result = detectSubnetConflictsFrom({});
    expect(result).toEqual([]);
  });

  it('handles interface with no addresses', () => {
    const interfaces: Record<string, NetworkInterfaceInfo[]> = {
      tun0: [],
      eth0: [ipv4('10.0.0.1', '255.255.255.0')],
    };

    const result = detectSubnetConflictsFrom(interfaces);
    expect(result).toEqual([]);
  });

  it('detects conflicts on separate subnets independently', () => {
    const interfaces: Record<string, NetworkInterfaceInfo[]> = {
      eth0: [ipv4('192.168.1.10', '255.255.255.0')],
      wlan0: [ipv4('192.168.1.20', '255.255.255.0')],
      docker0: [ipv4('172.17.0.1', '255.255.0.0')],
      br_docker: [ipv4('172.17.0.2', '255.255.0.0')],
    };

    const result = detectSubnetConflictsFrom(interfaces);
    expect(result).toHaveLength(2);

    const subnets = result.map((c) => c.subnet).sort((a, b) => a.localeCompare(b));
    expect(subnets).toEqual(['172.17.0.0/16', '192.168.1.0/24']);
  });

  it('does not flag different subnets as conflicts', () => {
    const interfaces: Record<string, NetworkInterfaceInfo[]> = {
      eth0: [ipv4('192.168.1.100', '255.255.255.0')],
      wlan0: [ipv4('192.168.2.100', '255.255.255.0')],
    };

    const result = detectSubnetConflictsFrom(interfaces);
    expect(result).toEqual([]);
  });
});

describe('detectSubnetConflicts (uses os module)', () => {
  it('uses live os.networkInterfaces and returns results', () => {
    // This calls the real os.networkInterfaces() — just verify it returns an array
    const result = detectSubnetConflicts();
    expect(Array.isArray(result)).toBe(true);
  });

  it('delegates to detectSubnetConflictsFrom with os data', () => {
    const spy = vi.spyOn(os, 'networkInterfaces');
    detectSubnetConflicts();
    expect(spy).toHaveBeenCalledOnce();
    spy.mockRestore();
  });
});

describe('formatConflictWarnings', () => {
  // Import dynamically to avoid circular issues
  it('formats a single conflict into a warning string', async () => {
    const { formatConflictWarnings } = await import('../network-check.js');
    const warnings = formatConflictWarnings([
      {
        subnet: '192.168.1.0/24',
        interfaces: [
          { name: 'eth0', address: '192.168.1.100' },
          { name: 'wlan0', address: '192.168.1.200' },
        ],
      },
    ]);
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain('192.168.1.0/24');
    expect(warnings[0]).toContain('eth0');
    expect(warnings[0]).toContain('wlan0');
    expect(warnings[0]).toContain('disabling one interface');
  });

  it('returns empty array for no conflicts', async () => {
    const { formatConflictWarnings } = await import('../network-check.js');
    expect(formatConflictWarnings([])).toEqual([]);
  });
});
