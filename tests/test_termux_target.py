"""Regression tests for Linux/Bionic target selection used by setup-noryka.sh."""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "termux" / "target.sh"


def detect(os_name: str, arch: str, termux_version: str = "",
           prefix: str = "", termux_root: str = "/path/that/does/not/exist") -> str:
    command = (
        'source "$1"; '
        'noryka_target_for "$2" "$3" "$4" "$5" "$6"'
    )
    result = subprocess.run(
        ["bash", "-c", command, "bash", str(HELPER), os_name, arch,
         termux_version, prefix, termux_root],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_termux_version_selects_bionic_target() -> None:
    assert detect("linux", "arm64", termux_version="0.118.3") == "linux-arm64-bionic"


def test_termux_prefix_selects_bionic_target() -> None:
    assert detect("linux", "arm64", prefix="/data/data/com.termux/files/usr") == "linux-arm64-bionic"


def test_termux_root_selects_bionic_target(tmp_path: Path) -> None:
    assert detect("linux", "arm64", termux_root=str(tmp_path)) == "linux-arm64-bionic"


def test_regular_linux_keeps_gnu_target() -> None:
    assert detect("linux", "arm64") == "linux-arm64"


def test_non_linux_target_is_unchanged() -> None:
    assert detect("darwin", "arm64", termux_version="0.118.3") == "darwin-arm64"
