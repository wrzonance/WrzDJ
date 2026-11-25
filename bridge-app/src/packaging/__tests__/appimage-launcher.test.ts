import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { execFileSync } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { appImageLauncherScript } from '../appimage-launcher';

// Runs the generated launcher with bash against a stub binary that prints
// its arguments as JSON, a stub `unshare` on PATH that succeeds or fails,
// and a stand-in for Ubuntu's AppArmor user-namespace restriction sysctl.
let dir: string;

function writeExecutable(file: string, body: string): void {
  fs.writeFileSync(file, `#!/bin/bash\n${body}\n`, { mode: 0o755 });
}

interface LaunchSetup {
  /**
   * works: every namespace Chromium's sandbox needs is available (the stub
   *   only succeeds when asked for all of them).
   * user-only: user namespaces work but PID/network ones are blocked.
   */
  unshare: 'works' | 'user-only' | 'fails' | 'missing';
  appArmorRestrict?: '0' | '1';
}

function runLauncher(setup: LaunchSetup, args: string[] = []): string[] {
  const stubBin = path.join(dir, 'stub-bin');
  fs.rmSync(stubBin, { recursive: true, force: true });
  fs.mkdirSync(stubBin);
  for (const tool of ['readlink', 'dirname']) {
    const real = execFileSync('bash', ['-c', `command -v ${tool}`], { encoding: 'utf8' }).trim();
    fs.symlinkSync(real, path.join(stubBin, tool));
  }
  if (setup.unshare !== 'missing') {
    const has = (flag: string) => `[[ " $* " == *" ${flag} "* ]]`;
    const stubs = {
      works: `${['--user', '--map-root-user', '--pid', '--net', '--fork'].map(has).join(' && ')}`,
      'user-only': `! ${has('--pid')} && ! ${has('--net')}`,
      fails: 'exit 1',
    };
    writeExecutable(path.join(stubBin, 'unshare'), stubs[setup.unshare]);
  }
  const sysctl = path.join(dir, 'apparmor_restrict_unprivileged_userns');
  if (setup.appArmorRestrict !== undefined) fs.writeFileSync(sysctl, `${setup.appArmorRestrict}\n`);
  fs.writeFileSync(
    path.join(dir, 'wrzdj-bridge'),
    appImageLauncherScript('wrzdj-bridge', { appArmorRestrictSysctl: sysctl }),
    { mode: 0o755 },
  );

  const out = execFileSync(path.join(dir, 'wrzdj-bridge'), args, {
    // Only the stub dir (stubs + readlink/dirname), so a real `unshare` on
    // the host can't leak in.
    env: { PATH: stubBin },
    encoding: 'utf8',
  });
  return JSON.parse(out) as string[];
}

beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), 'appimage-launcher-'));
  // The stub binary is Node itself (absolute path, independent of PATH), so
  // arguments round-trip through a real JSON encoder.
  fs.writeFileSync(
    path.join(dir, 'wrzdj-bridge.real'),
    `#!${process.execPath}\nprocess.stdout.write(JSON.stringify(process.argv.slice(2)));\n`,
    { mode: 0o755 },
  );
});

afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true });
});

describe('appImageLauncherScript', () => {
  it('keeps the Chromium sandbox when unprivileged user namespaces work', () => {
    expect(runLauncher({ unshare: 'works', appArmorRestrict: '0' }, ['--flag'])).toEqual([
      '--flag',
    ]);
  });

  it('keeps the sandbox on kernels without the AppArmor restriction sysctl', () => {
    expect(runLauncher({ unshare: 'works' })).toEqual([]);
  });

  it('falls back to --no-sandbox when AppArmor restricts user namespaces, even if unshare may use them', () => {
    // AppArmor is per-executable: a profile can allow `unshare` while the
    // AppImage's unprofiled Electron binary stays restricted.
    expect(runLauncher({ unshare: 'works', appArmorRestrict: '1' }, ['--flag'])).toEqual([
      '--no-sandbox',
      '--flag',
    ]);
  });

  it('falls back to --no-sandbox when user namespaces are blocked', () => {
    expect(runLauncher({ unshare: 'fails', appArmorRestrict: '0' }, ['--flag'])).toEqual([
      '--no-sandbox',
      '--flag',
    ]);
  });

  it('falls back to --no-sandbox when user namespaces work but PID/network ones are blocked', () => {
    // e.g. user.max_pid_namespaces=0: Chromium's namespace sandbox needs all three.
    expect(runLauncher({ unshare: 'user-only', appArmorRestrict: '0' })).toEqual(['--no-sandbox']);
  });

  it('keeps the sandbox when it cannot probe (fails closed; the user can still pass --no-sandbox)', () => {
    expect(runLauncher({ unshare: 'missing' })).toEqual([]);
    expect(runLauncher({ unshare: 'missing' }, ['--no-sandbox'])).toEqual(['--no-sandbox']);
  });

  it('still honours the AppArmor restriction when it cannot probe', () => {
    expect(runLauncher({ unshare: 'missing', appArmorRestrict: '1' })).toEqual(['--no-sandbox']);
  });

  it('passes quotes, backslashes, newlines and empty arguments through unchanged', () => {
    const args = ['quote"here', String.raw`back\slash\path`, 'line1\nline2', '', '$HOME *'];
    expect(runLauncher({ unshare: 'works' }, args)).toEqual(args);
    expect(runLauncher({ unshare: 'fails' }, args)).toEqual(['--no-sandbox', ...args]);
  });

  it('treats the binary name and sysctl path as literal text, not shell code', () => {
    const binName = `we'ird $(touch pwned) "bin" \`x\``;
    const sysctl = path.join(dir, `it's $HOME`);
    fs.writeFileSync(sysctl, '1\n');
    fs.copyFileSync(path.join(dir, 'wrzdj-bridge.real'), path.join(dir, `${binName}.real`));
    const launcher = path.join(dir, 'launcher');
    fs.writeFileSync(
      launcher,
      appImageLauncherScript(binName, { appArmorRestrictSysctl: sysctl }),
      { mode: 0o755 },
    );

    const out = execFileSync(launcher, ['--flag'], { cwd: dir, encoding: 'utf8' });

    // The restriction file was read (so --no-sandbox), the oddly named
    // binary was the one executed, and no command substitution ran.
    expect(JSON.parse(out)).toEqual(['--no-sandbox', '--flag']);
    expect(fs.existsSync(path.join(dir, 'pwned'))).toBe(false);
  });
});
