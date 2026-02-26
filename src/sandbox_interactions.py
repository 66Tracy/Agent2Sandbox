"""Sandbox interaction helpers for Agent2Sandbox."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from utils import _build_missing_config_error, _load_yaml_object, _require, _resolve_ref

from task_definition import TaskDefinition


def _stream_to_text(stream: Any) -> str:
    if not stream:
        return ""
    lines: List[str] = []
    for item in stream:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            lines.append(text)
        elif text is not None:
            lines.append(str(text))
    return "".join(lines)


def _extract_sandbox_id(sandbox: Any) -> str:
    for attr in ("sandbox_id", "id"):
        value = getattr(sandbox, attr, None)
        if value:
            return str(value)
    return "unknown"


@dataclass(frozen=True)
class SandboxServerConfig:
    """Sandbox server connection configuration."""

    domain: str
    api_key: Optional[str] = None
    request_timeout_seconds: int = 90


def load_sandbox_server_config(
    cfg_file: Union[str, Path] = "config/sandbox-server-cfg.yaml",
) -> SandboxServerConfig:
    """Load sandbox server configuration from YAML."""

    cfg_path = Path(cfg_file)
    if not cfg_path.exists():
        raise _build_missing_config_error(cfg_path, "sandbox server")

    data = _load_yaml_object(cfg_path)
    server = data.get("server", data)
    if not isinstance(server, dict):
        raise ValueError("`server` must be an object")

    domain = _resolve_ref(str(_require(server, "domain")))
    if not domain:
        raise ValueError("sandbox server domain cannot be empty")

    api_key_ref = server.get("api_key_ref")
    api_key_value = server.get("api_key")
    api_key: Optional[str] = None
    if api_key_ref is not None:
        api_key = _resolve_ref(str(api_key_ref))
    elif api_key_value is not None:
        value = str(api_key_value).strip()
        api_key = value or None

    timeout_value = server.get("request_timeout_seconds", 90)
    timeout_seconds = int(timeout_value)
    if timeout_seconds <= 0:
        raise ValueError("request_timeout_seconds must be > 0")

    return SandboxServerConfig(
        domain=domain,
        api_key=api_key,
        request_timeout_seconds=timeout_seconds,
    )


@dataclass
class SandboxRunResult:
    task_name: str
    sandbox_id: str
    command: str
    stdout: str
    stderr: str
    error: Optional[str]
    artifacts: Dict[str, str]

    @property
    def success(self) -> bool:
        return self.error is None


class SandboxTaskRunner:
    """Runs a task through OpenSandbox without coupling to LLM-Proxy."""

    def __init__(self, sandbox_cfg_file: Union[str, Path] = "config/sandbox-server-cfg.yaml"):
        self.sandbox_cfg_file = Path(sandbox_cfg_file)

    async def run_task(
        self,
        task: TaskDefinition,
        env_override: Optional[Dict[str, str]] = None,
    ) -> SandboxRunResult:
        try:
            from opensandbox import Sandbox
            from opensandbox.config import ConnectionConfig
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Missing dependency `opensandbox`. "
                "Install project dependencies in your runtime environment first."
            ) from exc

        sandbox_server = load_sandbox_server_config(cfg_file=self.sandbox_cfg_file)

        conn = ConnectionConfig(
            domain=sandbox_server.domain,
            api_key=sandbox_server.api_key,
            request_timeout=timedelta(seconds=sandbox_server.request_timeout_seconds),
        )

        runtime_env = dict(task.env)
        if env_override:
            runtime_env.update(env_override)

        command = task.command_as_shell()
        artifacts: Dict[str, str] = {}
        sandbox_id = "unknown"

        async with await Sandbox.create(
            task.image,
            connection_config=conn,
            entrypoint=task.sandbox_entrypoint,
            env=runtime_env,
        ) as sandbox:
            sandbox_id = _extract_sandbox_id(sandbox)
            execution = await sandbox.commands.run(command)
            stdout = _stream_to_text(getattr(execution.logs, "stdout", None))
            stderr = _stream_to_text(getattr(execution.logs, "stderr", None))
            error_obj = getattr(execution, "error", None)
            error_text = None
            if error_obj:
                name = getattr(error_obj, "name", "error")
                value = getattr(error_obj, "value", "")
                error_text = f"{name}: {value}"

            for artifact_path in task.artifacts:
                try:
                    artifacts[artifact_path] = await sandbox.files.read_file(artifact_path)
                except Exception as exc:
                    artifacts[artifact_path] = f"[artifact_read_error] {exc}"

        return SandboxRunResult(
            task_name=task.name,
            sandbox_id=sandbox_id,
            command=command,
            stdout=stdout,
            stderr=stderr,
            error=error_text,
            artifacts=artifacts,
        )
