"""Shared utilities for configuration loading."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional


def _load_yaml_object(path: Path) -> Dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required to load YAML configuration files. Install `pyyaml`."
        ) from exc
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Configuration file {path} must contain an object at top level")
    return data


def _require(mapping: Dict[str, Any], key: str) -> Any:
    value = mapping.get(key)
    if value is None:
        raise ValueError(f"Missing required config field: {key}")
    return value


def _resolve_ref(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("ENV:"):
        env_key = text.split(":", 1)[1].strip()
        if not env_key:
            raise ValueError("ENV reference must include key name, got empty key")
        resolved = os.environ.get(env_key)
        if resolved is None:
            raise ValueError(f"Cannot resolve environment variable: {env_key}")
        return resolved
    return text


def _build_missing_config_error(cfg_path: Path, context: str) -> FileNotFoundError:
    example_cfg = cfg_path.with_name(cfg_path.name.replace(".yaml", ".example.yaml"))
    if example_cfg.exists():
        return FileNotFoundError(
            f"Missing config file: {cfg_path}. "
            f"Copy {example_cfg} -> {cfg_path} and fill your {context} settings."
        )
    return FileNotFoundError(f"Missing config file: {cfg_path}")
