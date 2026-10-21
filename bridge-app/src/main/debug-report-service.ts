import { readFile, writeFile } from 'fs/promises';
import type { BridgeSettings, BridgeStatus } from '../shared/types.js';

type DebugReportStatus = Pick<
  BridgeStatus,
  | 'isRunning'
  | 'eventCode'
  | 'connectedDevice'
  | 'backendReachable'
  | 'stopReason'
  | 'currentTrack'
  | 'deckStates'
  | 'networkWarnings'
>;

function isMissingFileError(error: unknown): boolean {
  return error instanceof Error && 'code' in error && error.code === 'ENOENT';
}

interface DebugReportContext {
  appVersion: string;
  electronVersion: string;
  nodeVersion: string;
  chromeVersion: string;
  os: string;
  logPath: string;
  status: DebugReportStatus;
  settings: BridgeSettings;
}

async function readLogContents(logPath: string): Promise<string> {
  for (const path of [logPath, `${logPath}.1`]) {
    try {
      return await readFile(path, 'utf-8');
    } catch (error) {
      if (!isMissingFileError(error)) throw error;
    }
  }
  return '(no log file found)';
}

export async function writeDebugReport(
  filePath: string,
  context: DebugReportContext,
): Promise<void> {
  const { status, settings } = context;
  const logContents = await readLogContents(context.logPath);
  const lines = [
    '=== WrzDJ Bridge Debug Report ===',
    `Generated: ${new Date().toISOString()}`,
    '',
    '--- System ---',
    `App Version: ${context.appVersion}`,
    `Electron: ${context.electronVersion}`,
    `Node: ${context.nodeVersion}`,
    `Chrome: ${context.chromeVersion}`,
    `OS: ${context.os}`,
    '',
    '--- Bridge Status ---',
    `Running: ${status.isRunning}`,
    `Event Code: ${status.eventCode ?? 'none'}`,
    `Connected Device: ${status.connectedDevice ?? 'none'}`,
    `Backend Reachable: ${status.backendReachable}`,
    `Stop Reason: ${status.stopReason ?? 'none'}`,
    `Current Track: ${status.currentTrack ? `"${status.currentTrack.title}" by ${status.currentTrack.artist}` : 'none'}`,
    `Active Decks: ${status.deckStates.length}`,
    `Network Warnings: ${status.networkWarnings.length > 0 ? status.networkWarnings.join('; ') : 'none'}`,
    '',
    '--- Settings ---',
    `Protocol: ${settings.protocol}`,
    `Live Threshold: ${settings.liveThresholdSeconds}s`,
    `Pause Grace: ${settings.pauseGraceSeconds}s`,
    `Now Playing Pause: ${settings.nowPlayingPauseSeconds}s`,
    `Fader Detection: ${settings.useFaderDetection}`,
    `Master Deck Priority: ${settings.masterDeckPriority}`,
    `Min Play Seconds: ${settings.minPlaySeconds}`,
    ...(settings.pluginConfig ? [`Plugin Config: ${JSON.stringify(settings.pluginConfig)}`] : []),
    '',
    '--- Log File ---',
    logContents,
  ];
  await writeFile(filePath, lines.join('\n'), 'utf-8');
}
