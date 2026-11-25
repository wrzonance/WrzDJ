/**
 * Shell launcher that wraps the Linux binary inside the AppImage.
 *
 * AppImages can't ship Chromium's SUID `chrome-sandbox` helper, so the
 * sandbox has to come from unprivileged user namespaces. Run with the
 * sandbox on where those are available to this binary, and fall back to
 * `--no-sandbox` otherwise, since Chromium would refuse to start:
 *
 * - Ubuntu 23.10+ restricts user namespaces through AppArmor
 *   (`kernel.apparmor_restrict_unprivileged_userns=1`). That policy is
 *   per-executable, and the AppImage's binary never has a profile of its own,
 *   so it is restricted even where a profile lets `unshare` through.
 * - Elsewhere the kernel gates (`unprivileged_userns_clone`,
 *   `max_user_namespaces`) apply to every process alike, so an
 *   `unshare --user` probe answers for this binary too.
 * - Without `unshare` there is nothing to probe with, so it fails closed:
 *   the sandbox stays on and Chromium decides. Users on such a system can
 *   still pass `--no-sandbox` themselves; the launcher forwards arguments.
 *
 * The flag must be a real CLI argument: Chromium's sandbox starts before
 * Node.js, so `app.commandLine.appendSwitch()` is too late.
 */
export interface LauncherOptions {
  /** Overridable for tests; the kernel's AppArmor user-namespace switch. */
  appArmorRestrictSysctl?: string;
}

const APPARMOR_RESTRICT_SYSCTL = '/proc/sys/kernel/apparmor_restrict_unprivileged_userns';

/** Quote a value as one literal bash word: single quotes, with ' written as '\''. */
function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

export function appImageLauncherScript(binName: string, options: LauncherOptions = {}): string {
  const sysctl = options.appArmorRestrictSysctl ?? APPARMOR_RESTRICT_SYSCTL;
  return [
    '#!/bin/bash',
    'here="$(dirname "$(readlink -f "$0")")"',
    `real="$here/"${shellQuote(`${binName}.real`)}`,
    'userns_usable() {',
    '  local restrict=""',
    `  read -r restrict 2>/dev/null <${shellQuote(sysctl)}`,
    '  if [ "$restrict" = "1" ]; then return 1; fi',
    '  # No unshare to probe with: keep the sandbox and let Chromium decide.',
    '  if ! command -v unshare >/dev/null 2>&1; then return 0; fi',
    '  unshare --user --map-root-user true >/dev/null 2>&1',
    '}',
    'if userns_usable; then',
    '  exec "$real" "$@"',
    'fi',
    'exec "$real" --no-sandbox "$@"',
    '',
  ].join('\n');
}
