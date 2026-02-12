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

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent2sandbox.demo_runner import DemoRunner


EXPECTED_TOKEN = os.getenv("A2S_EXPECTED_TOKEN", "A2S_OK_20260211")


async def main() -> int:
    print("=" * 72)
    print("Test 2: Claude-Code Through Local LLM Proxy")
    print("=" * 72)

    task_file = Path(os.getenv("A2S_TASK_FILE", "tasks/claude_proxy_demo.yaml"))
    env_file = Path(os.getenv("A2S_ENV_FILE", "agent2sandbox/.env"))
    proxy_cfg_file = Path(os.getenv("A2S_PROXY_CFG_FILE", "config/llmproxy-cfg.yaml"))
    sandbox_cfg_file = Path(
        os.getenv("A2S_SANDBOX_CFG_FILE", "config/sandbox-server-cfg.yaml")
    )
    proxy_host = os.getenv("A2S_PROXY_HOST", "127.0.0.1")
    proxy_port = int(os.getenv("A2S_PROXY_PORT", "18080"))
    trajectory_dir = Path(os.getenv("A2S_TRAJECTORY_DIR", "logs/trajectory"))

    print(f"Task file: {task_file}")
    print(f"Env file: {env_file}")
    print(f"Proxy cfg: {proxy_cfg_file}")
    print(f"Sandbox cfg: {sandbox_cfg_file}")
    print(f"Proxy listen: {proxy_host}:{proxy_port}")
    print(f"Trajectory dir: {trajectory_dir}")

    runner = DemoRunner(
        env_file=env_file,
        proxy_cfg_file=proxy_cfg_file,
        sandbox_cfg_file=sandbox_cfg_file,
        proxy_host=proxy_host,
        proxy_port=proxy_port,
        trajectory_dir=trajectory_dir,
    )
    try:
        result = await runner.run_task(task_file)
    except Exception as exc:
        print(f"\nExecution failed: {type(exc).__name__}: {exc}")
        return 1

    print("\n[1] Execution summary")
    print(f"Task: {result.task_name}")
    print(f"Sandbox ID: {result.sandbox_id}")
    print(f"Session token: {result.session_token}")
    print(f"Trajectory file: {result.trajectory_file}")
    print(f"Command error: {result.error or 'None'}")

    print("\n[2] Command stdout")
    print(result.stdout or "<empty>")

    print("\n[3] Command stderr")
    print(result.stderr or "<empty>")

    print("\n[4] Artifact check")
    artifact_content = result.artifacts.get("/tmp/claude_result.txt", "")
    print(artifact_content or "<artifact missing>")

    checks = [
        ("Command exited without runtime error", result.error is None),
        (
            "Expected token appears in output or artifact",
            EXPECTED_TOKEN in result.stdout or EXPECTED_TOKEN in artifact_content,
        ),
        ("Trajectory file exists", result.trajectory_file.exists()),
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
