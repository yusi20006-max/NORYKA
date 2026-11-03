"""Resolve NORYKA_HOME for standalone skill scripts.

Skill scripts may run outside the Noryka process (e.g. system Python,
nix env, CI) where ``noryka_constants`` is not importable.  This module
provides the same ``get_noryka_home()`` and ``display_noryka_home()``
contracts as ``noryka_constants`` without requiring it on ``sys.path``.

When ``noryka_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically.  The fallback path replicates the core logic
from ``noryka_constants.py`` using only the stdlib.

All scripts under ``google-workspace/scripts/`` should import from here
instead of duplicating the ``NORYKA_HOME = Path(os.getenv(...))`` pattern.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from noryka_constants import display_noryka_home
    from noryka_constants import get_noryka_home
except (ModuleNotFoundError, ImportError):

    def get_noryka_home() -> Path:
        """Return the Noryka home directory (default: ~/.noryka).

        Mirrors ``noryka_constants.get_noryka_home()``."""
        val = os.environ.get("NORYKA_HOME", "").strip()
        return Path(val) if val else Path.home() / ".noryka"

    def display_noryka_home() -> str:
        """Return a user-friendly ``~/``-shortened display string.

        Mirrors ``noryka_constants.display_noryka_home()``."""
        home = get_noryka_home()
        try:
            return "~/" + home.relative_to(Path.home()).as_posix()
        except ValueError:
            return str(home)
