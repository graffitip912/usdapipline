"""Harness configuration loader.

Reads harness.yaml from the project root and provides typed accessors
for runtime rules, retry policies, and verification settings.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HARNESS_PATH = _PROJECT_ROOT / "harness.yaml"

_DEFAULTS: dict[str, Any] = {
    "runtime_rules": {
        "schedule_triggers": {
            "weekly": "0 6 * * 1",
            "monthly": "0 6 15 * *",
        },
        "retry_policy": {
            "max_retries": 3,
            "backoff_strategy": "none",
            "stale_recovery": "next_scheduled_run",
        },
        "verification": {
            "auto_validation_enabled": True,
            "auto_schema": "GrainSchema",
            "user_confirmation_required": True,
            "preview_sample_rows": 20,
            "anomaly_zscore_threshold": 3.0,
        },
        "change_request_policy": {
            "max_loop_iterations": 10,
            "require_re_collect_after_apply": True,
            "require_user_verify_after_re_collect": True,
        },
    },
}


@lru_cache(maxsize=1)
def load_harness_config() -> dict[str, Any]:
    """Load harness.yaml. Returns defaults if file is missing."""
    if not _HARNESS_PATH.exists():
        log.warning("harness.yaml not found at %s — using defaults", _HARNESS_PATH)
        return _DEFAULTS
    with open(_HARNESS_PATH, encoding="utf-8") as f:
        config = yaml.safe_load(f) or {}
    log.info("Loaded harness config from %s", _HARNESS_PATH)
    return config


def get_runtime_rules() -> dict[str, Any]:
    """Return the runtime_rules section."""
    return load_harness_config().get("runtime_rules", _DEFAULTS["runtime_rules"])


def get_retry_policy() -> dict[str, Any]:
    """Return retry policy. Can replace manifest.py MAX_RETRIES."""
    rules = get_runtime_rules()
    return rules.get("retry_policy", _DEFAULTS["runtime_rules"]["retry_policy"])


def get_verification_config() -> dict[str, Any]:
    """Return verification settings."""
    rules = get_runtime_rules()
    return rules.get("verification", _DEFAULTS["runtime_rules"]["verification"])


def get_change_request_policy() -> dict[str, Any]:
    """Return change request loop policy."""
    rules = get_runtime_rules()
    return rules.get("change_request_policy", _DEFAULTS["runtime_rules"]["change_request_policy"])


def reload() -> dict[str, Any]:
    """Force reload of harness config (clears cache)."""
    load_harness_config.cache_clear()
    return load_harness_config()
