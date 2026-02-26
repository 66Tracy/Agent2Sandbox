"""
Test 2: Claude-Code Through Local LLM Proxy

Run with:
    python test/test2-claude-proxy-demo.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from llm_proxy import (
    LLMProxyConfig,
    LLMProxyServer,
    LLMProxyServerConfig,
    load_llmproxy_config,
)
from sandbox_interactions import SandboxTaskRunner
from task_definition import load_task_definition


EXPECTED_TOKEN = os.getenv("A2S_EXPECTED_TOKEN", "A2S_OK_20260211")


async def main() -> int:
    print("=" * 72)
    print("Test 2: Claude-Code Through Local LLM Proxy")
    print("=" * 72)

    task_file = Path(os.getenv("A2S_TASK_FILE", "tasks/claude_proxy_demo.yaml"))
    proxy_cfg_file = Path(os.getenv("A2S_PROXY_CFG_FILE", "config/llmproxy-cfg.yaml"))
    sandbox_cfg_file = Path(
        os.getenv("A2S_SANDBOX_CFG_FILE", "config/sandbox-server-cfg.yaml")
    )
    proxy_host = os.getenv("A2S_PROXY_HOST")
    proxy_port_raw = os.getenv("A2S_PROXY_PORT")
    proxy_port = int(proxy_port_raw) if proxy_port_raw else None
    trajectory_dir_raw = os.getenv("A2S_TRAJECTORY_DIR")
    trajectory_dir = Path(trajectory_dir_raw) if trajectory_dir_raw else None

    print(f"Task file: {task_file}")
    print(f"Proxy cfg: {proxy_cfg_file}")
    print(f"Sandbox cfg: {sandbox_cfg_file}")
    proxy_host_display = proxy_host or "<from config>"
    proxy_port_display = proxy_port or "<from config>"
    print(f"Proxy listen: {proxy_host_display}:{proxy_port_display}")
    print(f"Trajectory dir: {trajectory_dir or '<from config>'}")

    task = load_task_definition(task_file)
    proxy_cfg = load_llmproxy_config(cfg_file=proxy_cfg_file)
    server_cfg = LLMProxyServerConfig(
        host=proxy_host or proxy_cfg.server_config.host,
        port=proxy_port or proxy_cfg.server_config.port,
        log_dir=trajectory_dir or proxy_cfg.server_config.log_dir,
    )
    proxy_config = LLMProxyConfig(
        routing_config=proxy_cfg.routing_config,
        server_config=server_cfg,
    )

    session_token = f"a2s_{uuid4().hex}"
    proxy_base_url = (task.llm.proxy_url or "").strip() or server_cfg.base_url
    runtime_env = dict(task.env)
    runtime_env.update(
        {
            "ANTHROPIC_BASE_URL": proxy_base_url,
            "ANTHROPIC_AUTH_TOKEN": session_token,
            "ANTHROPIC_MODEL": task.llm.model,
            "IS_SANDBOX": "1",
        }
    )

    runner = SandboxTaskRunner(sandbox_cfg_file=sandbox_cfg_file)
    proxy_server = LLMProxyServer(config=proxy_config)

    result = None
    try:
        with proxy_server.running():
            result = await runner.run_task(task, env_override=runtime_env)
    except Exception as exc:
        print(f"\nExecution failed: {type(exc).__name__}: {exc}")
        return 1
    finally:
        proxy_server.register_session(
            token=session_token,
            sandbox_id=result.sandbox_id if result else None,
            task_name=task.name,
        )

    print("\n[1] Execution summary")
    print(f"Task: {result.task_name}")
    print(f"Sandbox ID: {result.sandbox_id}")
    print(f"Session token: {session_token}")
    trajectory_path = proxy_server.trajectory_path(session_token)
    print(f"Trajectory dir: {trajectory_path}")
    print(f"Command error: {result.error or 'None'}")

    print("\n[2] Command stdout")
    print(result.stdout or "<empty>")

    print("\n[3] Command stderr")
    print(result.stderr or "<empty>")

    print("\n[4] Artifact check")
    artifact_content = result.artifacts.get("/tmp/claude_result.txt", "")
    print(artifact_content or "<artifact missing>")

    req_files = list(trajectory_path.glob("*-req.json"))
    res_files = list(trajectory_path.glob("*-assistant.json"))

    checks = [
        ("Command exited without runtime error", result.error is None),
        (
            "Expected token appears in output or artifact",
            EXPECTED_TOKEN in result.stdout or EXPECTED_TOKEN in artifact_content,
        ),
        ("Trajectory dir exists", trajectory_path.exists()),
        ("Trajectory has req file", bool(req_files)),
        ("Trajectory has assistant file", bool(res_files)),
    ]

    print("\n[5] Verification")
    passed = 0
    for name, ok in checks:
        mark = "PASS" if ok else "FAIL"
        print(f"- {mark}: {name}")
        if ok:
            passed += 1

    total = len(checks)
    print(f"\nResult: {passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
