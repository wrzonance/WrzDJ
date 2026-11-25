import { describe, it, expect, vi } from 'vitest';
import { handleSquirrelEvent, type SquirrelDeps } from '../squirrel-startup';

const EXEC_PATH = 'C:\\Users\\dj\\AppData\\Local\\wrzdj_bridge\\app-1.0.0\\WrzDJ Bridge.exe';
// Literal Windows paths, so the expectations don't depend on the host's path module.
const UPDATE_EXE = 'C:\\Users\\dj\\AppData\\Local\\wrzdj_bridge\\Update.exe';
const TARGET = 'WrzDJ Bridge.exe';

function makeDeps(overrides: Partial<SquirrelDeps> = {}) {
  const listeners = new Map<string, (arg?: unknown) => void>();
  const child = {
    on: vi.fn((event: string, listener: (arg?: unknown) => void) => {
      listeners.set(event, listener);
      return child;
    }),
  };
  const spawn = vi.fn(() => child);
  const quit = vi.fn();
  const logError = vi.fn();
  const deps: SquirrelDeps = {
    platform: 'win32',
    argv: [EXEC_PATH],
    execPath: EXEC_PATH,
    spawn,
    quit,
    logError,
    ...overrides,
  };
  return { deps, spawn, quit, logError, listeners };
}

describe('handleSquirrelEvent', () => {
  it.each(['--squirrel-install', '--squirrel-updated'])(
    'creates the shortcut via Update.exe on %s and quits only once it closes',
    (flag) => {
      const { deps, spawn, quit, listeners } = makeDeps({ argv: [EXEC_PATH, flag] });

      expect(handleSquirrelEvent(deps)).toBe(true);
      expect(spawn).toHaveBeenCalledWith(UPDATE_EXE, [`--createShortcut=${TARGET}`], {
        detached: true,
      });
      expect(quit).not.toHaveBeenCalled();

      listeners.get('close')?.();
      expect(quit).toHaveBeenCalledOnce();
    },
  );

  it('removes the shortcut via Update.exe on --squirrel-uninstall', () => {
    const { deps, spawn, quit, listeners } = makeDeps({
      argv: [EXEC_PATH, '--squirrel-uninstall'],
    });

    expect(handleSquirrelEvent(deps)).toBe(true);
    expect(spawn).toHaveBeenCalledWith(UPDATE_EXE, [`--removeShortcut=${TARGET}`], {
      detached: true,
    });
    listeners.get('close')?.();
    expect(quit).toHaveBeenCalledOnce();
  });

  it('logs and quits when Update.exe cannot be spawned', () => {
    const { deps, quit, logError, listeners } = makeDeps({
      argv: [EXEC_PATH, '--squirrel-install'],
    });

    expect(handleSquirrelEvent(deps)).toBe(true);
    const failure = new Error('spawn Update.exe ENOENT');
    listeners.get('error')?.(failure);

    expect(logError).toHaveBeenCalledWith(expect.stringContaining('Update.exe'), failure);
    expect(quit).toHaveBeenCalledOnce();
  });

  it('quits without spawning on --squirrel-obsolete', () => {
    const { deps, spawn, quit } = makeDeps({ argv: [EXEC_PATH, '--squirrel-obsolete'] });

    expect(handleSquirrelEvent(deps)).toBe(true);
    expect(spawn).not.toHaveBeenCalled();
    expect(quit).toHaveBeenCalledOnce();
  });

  it('lets a normal Windows launch continue', () => {
    const { deps, spawn, quit } = makeDeps();

    expect(handleSquirrelEvent(deps)).toBe(false);
    expect(spawn).not.toHaveBeenCalled();
    expect(quit).not.toHaveBeenCalled();
  });

  it('only reads the first argument, like electron-squirrel-startup did', () => {
    const { deps, spawn } = makeDeps({ argv: [EXEC_PATH, '--foo', '--squirrel-install'] });

    expect(handleSquirrelEvent(deps)).toBe(false);
    expect(spawn).not.toHaveBeenCalled();
  });

  it.each(['linux', 'darwin'] as const)('ignores Squirrel flags on %s', (platform) => {
    const { deps, spawn, quit } = makeDeps({ platform, argv: [EXEC_PATH, '--squirrel-install'] });

    expect(handleSquirrelEvent(deps)).toBe(false);
    expect(spawn).not.toHaveBeenCalled();
    expect(quit).not.toHaveBeenCalled();
  });
});
