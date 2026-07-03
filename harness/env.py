"""Config + environment loading for OptionsAgent.

Single import-point for config.json and .env so every module reads the same
resolved values. Mirrors DeterministicAgent's env.py pattern.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.json"

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass

_config_cache: dict[str, Any] | None = None


def config() -> dict[str, Any]:
    """Load config/config.json once per process."""
    global _config_cache
    if _config_cache is None:
        with open(CONFIG_PATH) as f:
            _config_cache = json.load(f)
    return _config_cache


def active_phase() -> str:
    return config().get("phase", "wheel")


def allowed_strategies() -> list[str]:
    """Strategy types the current rollout phase permits. Phase 1 = wheel only."""
    phase = active_phase()
    phases = config().get("phase_strategies", {})
    return phases.get(phase, ["csp", "covered_call"])


def universe() -> list[str]:
    path = ROOT / config()["screener"]["universe_file"]
    symbols = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                symbols.append(line.upper())
    return symbols


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


def require_env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"required env var {key} is not set")
    return val
