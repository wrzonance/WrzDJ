"""Sandboxed installer/watchdog boundary checks; baseline 57cfcdc6867f."""

import os
import shlex
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

KIOSK = Path(__file__).resolve().parents[1]


def run_sourced_script(
    path: Path,
    body: str,
    *,
    args: Sequence[str] = (),
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    script = f"set -eu\nsource {shlex.quote(str(path))}\n{body}\n"
    return subprocess.run(
        ["bash", "-c", script, "wrzdj-test", *map(str, args)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=3,
    )


def test_hotspot_setup_generates_and_preserves_credentials(tmp_path):
    config = tmp_path / "kiosk.conf"
    config_module = KIOSK / "lib/setup-config.sh"
    body = "\n".join(
        [
            'HOTSPOT_SSID="" HOTSPOT_PASSWORD=""',
            'prepare_hotspot_config "$1"',
            'printf "%s" "$HOTSPOT_PASSWORD"',
        ]
    )
    command = [str(config)]
    first = run_sourced_script(config_module, body, args=command).stdout
    assert 8 <= len(first) <= 63
    assert first != "wrzdj1234"
    config.write_text(f'HOTSPOT_PASSWORD="{first}"\n')
    second = run_sourced_script(config_module, body, args=command).stdout
    assert second == first


@pytest.mark.parametrize("active", [True, False])
def test_preflight_requires_network_manager(active):
    body = "\n".join(
        [
            "id() { echo 0; }",
            "uname() { echo aarch64; }",
            "grep() { return 0; }",
            "warn() { :; }",
            'die() { echo "$*" >&2; exit 1; }',
            "nmcli() { :; }",
            f"systemctl() {{ return {0 if active else 1}; }}",
            "preflight",
        ]
    )
    result = run_sourced_script(KIOSK / "setup.sh", body)
    assert result.returncode == (0 if active else 1)
    if not active:
        assert "NetworkManager" in result.stderr


@pytest.mark.parametrize("rotation,expected", [("90", "1"), ("180", "2"), ("270", "3")])
def test_rotation_calls_production_function(tmp_path, rotation, expected):
    config = tmp_path / "config.txt"
    config.write_text("dtoverlay=vc4-kms-v3d\ndisplay_rotate=9\n")
    result = run_sourced_script(
        KIOSK / "setup.sh",
        'configure_rotation "$1"',
        args=[str(config)],
        env={**os.environ, "KIOSK_ROTATION": rotation},
    )
    assert result.returncode == 0, result.stderr
    assert config.read_text() == f"dtoverlay=vc4-kms-v3d\ndisplay_rotate={expected}\n"


@pytest.mark.parametrize(
    "preferences,expected",
    [
        (
            '{"exited_cleanly":false,"exit_type":"Crashed"}',
            '{"exited_cleanly":true,"exit_type":"Normal"}',
        ),
        (
            '{"exited_cleanly":true,"exit_type":"Normal"}',
            '{"exited_cleanly":true,"exit_type":"Normal"}',
        ),
    ],
)
def test_watchdog_clears_crash_flags_without_service_recovery(
    tmp_path, preferences, expected
):
    prefs = tmp_path / "Preferences"
    prefs.write_text(preferences)
    systemctl_trace = tmp_path / "systemctl"
    chown_trace = tmp_path / "chown"
    result = run_sourced_script(
        KIOSK / "systemd/wrzdj-kiosk-watchdog.sh",
        "\n".join(
            [
                'chown() { printf "%s\\n" "$*" >> "$CHOWN_TRACE"; }',
                'systemctl() { printf "%s\\n" "$*" >> "$SYSTEMCTL_TRACE"; }',
                'main "$1"',
            ]
        ),
        args=[str(prefs)],
        env={
            **os.environ,
            "CHOWN_TRACE": str(chown_trace),
            "SYSTEMCTL_TRACE": str(systemctl_trace),
        },
    )
    assert result.returncode == 0, result.stderr
    assert prefs.read_text() == expected
    assert chown_trace.read_text() == f"kiosk:kiosk {prefs}\n"
    assert not systemctl_trace.exists()
