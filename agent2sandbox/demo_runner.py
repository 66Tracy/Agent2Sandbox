"""Demo runner: task definition -> local LLM proxy -> sandbox command execution."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent2sandbox.llm_proxy import LLMProxyServer
from agent2sandbox.settings import ProxyConfig, load_upstream_config
from agent2sandbox.task_definition import TaskDefinition, load_task_definition


def _stream_to_text(stream: Any) -> str:
    if not stream:
        return ""
    lines: list[str] = []
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


@dataclass
class DemoRunResult:
    task_name: str
    sandbox_id: str
    session_token: str
    command: str
    stdout: str
    stderr: str
    error: str | None
    artifacts: dict[str, str]
    trajectory_file: Path

    @property
    def success(self) -> bool:
        return self.error is None


class DemoRunner:
    """Runs a task through code-interpreter sandbox and local LLM proxy."""

    def __init__(
        self,
        env_file: str | Path = "agent2sandbox/.env",
        proxy_host: str = "127.0.0.1",
        proxy_port: int = 18080,
        trajectory_dir: str | Path = "logs/trajectory",
    ):
        self.env_file = Path(env_file)
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.trajectory_dir = Path(trajectory_dir)

    async def run_task(self, task_file: str | Path) -> DemoRunResult:
        # Lazy imports keep this module importable even without opensandbox installed.
        try:
            from opensandbox import Sandbox
            from opensandbox.config import ConnectionConfig
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Missing dependency `opensandbox`. "
                "Install project dependencies in your runtime environment first."
            ) from exc

        task: TaskDefinition = load_task_definition(task_file)
        upstream = load_upstream_config(self.env_file)
        proxy = ProxyConfig(
            host=self.proxy_host,
            port=self.proxy_port,
            log_dir=self.trajectory_dir,
        )
        proxy_server = LLMProxyServer(upstream=upstream, proxy=proxy)

        session_token = f"a2s_{uuid4().hex}"
        runtime_env = dict(task.env)
        runtime_env.update(
            {
                "ANTHROPIC_BASE_URL": proxy.base_url,
                "ANTHROPIC_AUTH_TOKEN": session_token,
                "ANTHROPIC_MODEL": task.llm.model,
                "IS_SANDBOX": "1",
            }
        )

        domain = os.getenv("SANDBOX_DOMAIN", "localhost:8080")
        api_key = os.getenv("SANDBOX_API_KEY")
        conn = ConnectionConfig(
            domain=domain,
            api_key=api_key,
            request_timeout=timedelta(seconds=90),
        )

        command = task.command_as_shell()
        artifacts: dict[str, str] = {}
        sandbox_id = "unknown"

        with proxy_server.running():
            proxy_server.record_event(
                token=session_token,
                event_type="runner_started",
                payload={
                    "task_name": task.name,
                    "proxy_base_url": proxy.base_url,
                    "sandbox_domain": domain,
                },
            )
            async with await Sandbox.create(
                task.image,
                connection_config=conn,
                entrypoint=task.sandbox_entrypoint,
                env=runtime_env,
            ) as sandbox:
                sandbox_id = _extract_sandbox_id(sandbox)
                proxy_server.register_session(
                    token=session_token,
                    sandbox_id=sandbox_id,
                    task_name=task.name,
                )
                proxy_server.record_event(
                    token=session_token,
                    event_type="sandbox_status",
                    payload={"status": "created"},
                )

                execution = await sandbox.commands.run(command)
                stdout = _stream_to_text(getattr(execution.logs, "stdout", None))
                stderr = _stream_to_text(getattr(execution.logs, "stderr", None))
                error_obj = getattr(execution, "error", None)
                error_text = None
                if error_obj:
                    name = getattr(error_obj, "name", "error")
                    value = getattr(error_obj, "value", "")
                    error_text = f"{name}: {value}"

                proxy_server.record_event(
                    token=session_token,
                    event_type="task_command_finished",
                    payload={
                        "error": error_text,
                        "stdout_len": len(stdout),
                        "stderr_len": len(stderr),
                    },
                )

                for artifact_path in task.artifacts:
                    try:
                        artifacts[artifact_path] = await sandbox.files.read_file(artifact_path)
                    except Exception as exc:
                        artifacts[artifact_path] = f"[artifact_read_error] {exc}"

                proxy_server.record_event(
                    token=session_token,
                    event_type="sandbox_status",
                    payload={"status": "closed"},
                )

        return DemoRunResult(
            task_name=task.name,
            sandbox_id=sandbox_id,
            session_token=session_token,
            command=command,
            stdout=stdout,
            stderr=stderr,
            error=error_text,
            artifacts=artifacts,
            trajectory_file=proxy_server.trajectory_path(session_token),
        )


async def _amain(task_file: str) -> int:
    runner = DemoRunner()
    result = await runner.run_task(task_file)
    print("=" * 72)
    print("Agent2Sandbox Demo Runner")
    print("=" * 72)
    print(f"Task: {result.task_name}")
    print(f"Sandbox ID: {result.sandbox_id}")
    print(f"Session token: {result.session_token}")
    print(f"Trajectory: {result.trajectory_file}")
    print(f"Command: {result.command}")
    print(f"Error: {result.error or 'None'}")
    print("\n[stdout]")
    print(result.stdout or "<empty>")
    print("\n[stderr]")
    print(result.stderr or "<empty>")
    if result.artifacts:
        print("\n[artifacts]")
        for path, content in result.artifacts.items():
            print(f"- {path}: {content[:300]}")
    return 0 if result.success else 1


def main() -> None:
    task_file = os.getenv("A2S_TASK_FILE", "tasks/claude_proxy_demo.yaml")
    raise SystemExit(asyncio.run(_amain(task_file)))


if __name__ == "__main__":
    main()
