import { describe, it, expect, vi } from 'vitest';
import path from 'path';
import { handleSquirrelEvent, type SquirrelDeps } from '../squirrel-startup';

const EXEC_PATH = 'C:\\Users\\dj\\AppData\\Local\\wrzdj_bridge\\app-1.0.0\\WrzDJ Bridge.exe';

function makeDeps(overrides: Partial<SquirrelDeps> = {}) {
  const onClose = vi.fn();
  const spawn = vi.fn(() => ({ on: onClose }));
  const quit = vi.fn();
  const deps: SquirrelDeps = {
    platform: 'win32',
    argv: [EXEC_PATH],
    execPath: EXEC_PATH,
    spawn,
    quit,
    ...overrides,
  };
  return { deps, spawn, quit, onClose };
}

const updateExe = path.resolve(path.dirname(EXEC_PATH), '..', 'Update.exe');
const target = path.basename(EXEC_PATH);

describe('handleSquirrelEvent', () => {
  it.each(['--squirrel-install', '--squirrel-updated'])(
    'creates the shortcut via Update.exe and quits when it closes on %s',
    (flag) => {
      const { deps, spawn, quit, onClose } = makeDeps({ argv: [EXEC_PATH, flag] });

      expect(handleSquirrelEvent(deps)).toBe(true);
      expect(spawn).toHaveBeenCalledWith(updateExe, [`--createShortcut=${target}`], {
        detached: true,
      });
      expect(onClose).toHaveBeenCalledWith('close', quit);
    },
  );

  it('removes the shortcut via Update.exe on --squirrel-uninstall', () => {
    const { deps, spawn, onClose, quit } = makeDeps({
      argv: [EXEC_PATH, '--squirrel-uninstall'],
    });

    expect(handleSquirrelEvent(deps)).toBe(true);
    expect(spawn).toHaveBeenCalledWith(updateExe, [`--removeShortcut=${target}`], {
      detached: true,
    });
    expect(onClose).toHaveBeenCalledWith('close', quit);
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
