"""Resolve NORYKA_HOME for standalone skill scripts.

Skill scripts may run outside the Noryka process (system Python, nix env,
CI) where ``noryka_constants`` is not importable.  This module provides the
same ``get_noryka_home()`` contract without requiring it on ``sys.path``.

When ``noryka_constants`` IS available it is used directly so profile
resolution and any future enhancements are picked up automatically.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from noryka_constants import get_noryka_home
except (ModuleNotFoundError, ImportError):

    def get_noryka_home() -> Path:
        """Return the Noryka home directory (default: ``~/.noryka``)."""
        val = os.environ.get("NORYKA_HOME", "").strip()
        return Path(val) if val else Path.home() / ".noryka"
