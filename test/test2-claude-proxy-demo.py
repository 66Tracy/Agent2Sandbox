"""
Test 2: Claude-Code Through External LLM Proxy

Run with:
    python test/test2-claude-proxy-demo.py

Note:
    This script assumes the LLM-Proxy is already running.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from llm_proxy import load_llmproxy_config
from sandbox_interactions import SandboxTaskRunner
from task_definition import load_task_definition


EXPECTED_TOKEN = "A2S_OK_20260211"


def _safe_file_token(token: str) -> str:
    return "".join(ch for ch in token if ch.isalnum() or ch in {"-", "_"})[:64] or "anonymous"


async def main() -> int:
    print("=" * 72)
    print("Test 2: Claude-Code Through External LLM Proxy")
    print("=" * 72)

    task_file = Path("tasks/claude_proxy_demo.yaml")
    sandbox_cfg_file = Path("config/sandbox-server-cfg.yaml")
    proxy_cfg_file = Path("config/llmproxy-cfg.yaml")

    print(f"Task file: {task_file}")
    print(f"Sandbox cfg: {sandbox_cfg_file}")
    print(f"Proxy cfg: {proxy_cfg_file}")

    task = load_task_definition(task_file)
    proxy_cfg = load_llmproxy_config(cfg_file=proxy_cfg_file)
    if task.llm.provider.strip().lower() != "anthropic":
        print("This test expects task.llm.provider=anthropic for claude-code.")
        return 1

    proxy_base_url = (task.llm.proxy_url or "").strip()
    if not proxy_base_url:
        print("Task config is missing llm.proxy_url.")
        return 1

    auth_token = (task.llm.api_key_ref or "").strip()
    if not auth_token:
        print("Task config is missing llm.api_key_ref.")
        return 1
    if auth_token.startswith("ENV:"):
        print("ENV: references are disabled; set llm.api_key_ref directly in YAML.")
        return 1

    trajectory_dir = proxy_cfg.server_config.log_dir

    print(f"Proxy url: {proxy_base_url}")
    print(f"Trajectory dir: {trajectory_dir}")

    runtime_env = dict(task.env)
    runtime_env.update(
        {
            "ANTHROPIC_BASE_URL": proxy_base_url,
            "ANTHROPIC_AUTH_TOKEN": auth_token,
            "ANTHROPIC_MODEL": task.llm.model,
            "IS_SANDBOX": "1",
        }
    )

    runner = SandboxTaskRunner(sandbox_cfg_file=sandbox_cfg_file)

    result = None
    try:
        result = await runner.run_task(task, env_override=runtime_env)
    except Exception as exc:
        print(f"\nExecution failed: {type(exc).__name__}: {exc}")
        return 1

    print("\n[1] Execution summary")
    print(f"Task: {result.task_name}")
    print(f"Sandbox ID: {result.sandbox_id}")
    print(f"Session token: {auth_token}")
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
    ]

    trajectory_path = trajectory_dir / _safe_file_token(auth_token)
    req_files = list(trajectory_path.glob("*-req.json"))
    res_files = list(trajectory_path.glob("*-assistant.json"))
    print("\n[5] Trajectory check")
    print(f"Trajectory dir: {trajectory_path}")
    checks.extend(
        [
            ("Trajectory dir exists", trajectory_path.exists()),
            ("Trajectory has req file", bool(req_files)),
            ("Trajectory has assistant file", bool(res_files)),
        ]
    )

    print("\n[6] Verification")
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
