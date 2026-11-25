import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { execFileSync } from 'child_process';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { appImageLauncherScript } from '../appimage-launcher';

// Runs the generated launcher with bash against a stub binary that prints
// its arguments, and a stub `unshare` on PATH that succeeds or fails.
let dir: string;

function writeExecutable(file: string, body: string): void {
  fs.writeFileSync(file, `#!/bin/bash\n${body}\n`, { mode: 0o755 });
}

function runLauncher(options: { unshare: 'works' | 'fails' | 'missing' }, args: string[] = []) {
  const stubBin = path.join(dir, 'stub-bin');
  fs.mkdirSync(stubBin, { recursive: true });
  for (const tool of ['readlink', 'dirname']) {
    const real = execFileSync('bash', ['-c', `command -v ${tool}`], { encoding: 'utf8' }).trim();
    fs.symlinkSync(real, path.join(stubBin, tool));
  }
  if (options.unshare !== 'missing') {
    writeExecutable(path.join(stubBin, 'unshare'), options.unshare === 'works' ? 'exit 0' : 'exit 1');
  }
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
  writeExecutable(
    path.join(dir, 'wrzdj-bridge.real'),
    `printf '['; sep=''; for a in "$@"; do printf '%s"%s"' "$sep" "$a"; sep=','; done; printf ']'`,
  );
  fs.writeFileSync(path.join(dir, 'wrzdj-bridge'), appImageLauncherScript('wrzdj-bridge'), {
    mode: 0o755,
  });
});

afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true });
});

describe('appImageLauncherScript', () => {
  it('keeps the Chromium sandbox when unprivileged user namespaces work', () => {
    expect(runLauncher({ unshare: 'works' }, ['--flag', 'two words'])).toEqual([
      '--flag',
      'two words',
    ]);
  });

  it('falls back to --no-sandbox when user namespaces are blocked', () => {
    expect(runLauncher({ unshare: 'fails' }, ['--flag'])).toEqual(['--no-sandbox', '--flag']);
  });

  it('falls back to --no-sandbox when it cannot probe for user namespaces', () => {
    expect(runLauncher({ unshare: 'missing' })).toEqual(['--no-sandbox']);
  });
});
