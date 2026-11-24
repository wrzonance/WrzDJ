import path from 'path';

/**
 * Windows Squirrel installer hooks, inlined from the archived
 * `electron-squirrel-startup` package with the same behaviour.
 *
 * Squirrel launches the app with one of these flags as the first argument
 * during install/update/uninstall. The app must create or remove its
 * shortcuts through Squirrel's Update.exe and exit instead of opening a
 * window.
 */
export interface SquirrelDeps {
  platform: NodeJS.Platform;
  argv: readonly string[];
  execPath: string;
  spawn: (
    command: string,
    args: string[],
    options: { detached: boolean },
  ) => { on: (event: 'close', listener: () => void) => unknown };
  quit: () => void;
}

/** Returns true when this launch was a Squirrel event and the app should exit. */
export function handleSquirrelEvent(deps: SquirrelDeps): boolean {
  if (deps.platform !== 'win32') return false;

  const command = deps.argv[1];
  const target = path.basename(deps.execPath);
  const runUpdateExe = (args: string[]) => {
    const updateExe = path.resolve(path.dirname(deps.execPath), '..', 'Update.exe');
    deps.spawn(updateExe, args, { detached: true }).on('close', deps.quit);
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
