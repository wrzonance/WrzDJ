/**
 * Shell launcher that wraps the Linux binary inside the AppImage.
 *
 * AppImages can't ship Chromium's SUID `chrome-sandbox` helper, so the
 * sandbox has to come from unprivileged user namespaces. Where those work,
 * run with the sandbox on. Fall back to `--no-sandbox` only where they are
 * blocked (e.g. Ubuntu 24.04+ restricts them via AppArmor) or can't be
 * probed, since Chromium would otherwise refuse to start. The flag must be a
 * real CLI argument: Chromium's sandbox starts before Node.js, so
 * `app.commandLine.appendSwitch()` is too late.
 */
export function appImageLauncherScript(binName: string): string {
  return [
    '#!/bin/bash',
    'here="$(dirname "$(readlink -f "$0")")"',
    `real="$here/${binName}.real"`,
    'if command -v unshare >/dev/null 2>&1 && unshare --user --map-root-user true >/dev/null 2>&1; then',
    '  exec "$real" "$@"',
    'fi',
    'exec "$real" --no-sandbox "$@"',
    '',
  ].join('\n');
}
