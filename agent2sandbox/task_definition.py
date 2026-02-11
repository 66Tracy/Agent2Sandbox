"""Task definition model and loader."""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LLMTaskConfig:
    provider: str
    proxy_url: str
    model: str
    api_key_ref: str


@dataclass(frozen=True)
class TaskDefinition:
    name: str
    image: str
    sandbox_entrypoint: list[str]
    task_command: list[str]
    llm: LLMTaskConfig
    artifacts: list[str] = field(default_factory=list)
    goal: str | None = None
    finish_condition: dict[str, Any] | None = None
    env: dict[str, str] = field(default_factory=dict)

    def command_as_shell(self) -> str:
        """Convert list command tokens into a shell-safe command string."""
        return shlex.join(self.task_command)


def _require(mapping: dict[str, Any], key: str) -> Any:
    value = mapping.get(key)
    if value is None:
        raise ValueError(f"Missing required task field: {key}")
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required to load YAML task files. Install `pyyaml`."
        ) from exc
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Task file {path} must contain an object at top level")
    return data


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Task file {path} must contain an object at top level")
    return data


def load_task_definition(path: str | Path) -> TaskDefinition:
    """Load a task definition from JSON or YAML."""

    task_path = Path(path)
    suffix = task_path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        data = _load_yaml(task_path)
    elif suffix == ".json":
        data = _load_json(task_path)
    else:
        raise ValueError(f"Unsupported task file extension: {suffix}")

    llm_raw = _require(data, "llm")
    if not isinstance(llm_raw, dict):
        raise ValueError("`llm` must be an object")

    llm = LLMTaskConfig(
        provider=str(_require(llm_raw, "provider")),
        proxy_url=str(_require(llm_raw, "proxy_url")),
        model=str(_require(llm_raw, "model")),
        api_key_ref=str(_require(llm_raw, "api_key_ref")),
    )

    entrypoint = _require(data, "sandbox_entrypoint")
    command = _require(data, "task_command")
    if not isinstance(entrypoint, list) or not all(isinstance(i, str) for i in entrypoint):
        raise ValueError("`sandbox_entrypoint` must be a list[str]")
    if not isinstance(command, list) or not all(isinstance(i, str) for i in command):
        raise ValueError("`task_command` must be a list[str]")

    artifacts_raw = data.get("artifacts", [])
    artifacts: list[str] = []
    if isinstance(artifacts_raw, list):
        for item in artifacts_raw:
            if isinstance(item, str):
                artifacts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("path"), str):
                artifacts.append(item["path"])
            else:
                raise ValueError("`artifacts` entries must be string paths or objects with `path`")

    env_raw = data.get("env", {})
    if env_raw is None:
        env_raw = {}
    if not isinstance(env_raw, dict):
        raise ValueError("`env` must be an object")
    env = {str(k): str(v) for k, v in env_raw.items()}

    return TaskDefinition(
        name=str(_require(data, "name")),
        image=str(_require(data, "image")),
        sandbox_entrypoint=entrypoint,
        task_command=command,
        llm=llm,
        artifacts=artifacts,
        goal=data.get("goal"),
        finish_condition=data.get("finish_condition"),
        env=env,
    )

