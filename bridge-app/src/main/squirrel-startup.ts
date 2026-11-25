import path from 'path';

/**
 * Windows Squirrel installer hooks, inlined from the archived
 * `electron-squirrel-startup` package.
 *
 * Squirrel launches the app with one of these flags as the first argument
 * during install/update/uninstall. The app must create or remove its
 * shortcuts through Squirrel's Update.exe and exit instead of opening a
 * window. The caller must not start the app when this returns true: `quit`
 * runs once Update.exe has finished (or failed to start).
 */
interface UpdateExeProcess {
  on(event: 'close', listener: () => void): UpdateExeProcess;
  on(event: 'error', listener: (error: Error) => void): UpdateExeProcess;
}

export interface SquirrelDeps {
  platform: NodeJS.Platform;
  argv: readonly string[];
  execPath: string;
  spawn: (command: string, args: string[], options: { detached: boolean }) => UpdateExeProcess;
  quit: () => void;
  logError: (message: string, error: Error) => void;
}

/** Returns true when this launch was a Squirrel event and the app must not start. */
export function handleSquirrelEvent(deps: SquirrelDeps): boolean {
  if (deps.platform !== 'win32') return false;

  // Squirrel only exists on Windows, so resolve paths with Windows semantics
  // whatever the host (this also keeps the unit tests honest on Linux CI).
  const winPath = path.win32;
  const command = deps.argv[1];
  const target = winPath.basename(deps.execPath);
  const runUpdateExe = (args: string[]) => {
    const updateExe = winPath.resolve(winPath.dirname(deps.execPath), '..', 'Update.exe');
    deps
      .spawn(updateExe, args, { detached: true })
      .on('close', deps.quit)
      .on('error', (error) => {
        deps.logError(`Squirrel: failed to run ${updateExe}`, error);
        deps.quit();
      });
  };

  switch (command) {
    case '--squirrel-install':
    case '--squirrel-updated':
      runUpdateExe([`--createShortcut=${target}`]);
      return true;
    case '--squirrel-uninstall':
      runUpdateExe([`--removeShortcut=${target}`]);
      return true;
    case '--squirrel-obsolete':
      deps.quit();
      return true;
    default:
      return false;
  }
}
