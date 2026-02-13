"""
Test: Basic Sandbox Interaction (Direct OpenSandbox)

This script verifies connectivity between local client and OpenSandbox Server.
It is kept as a smoke test for Docker + OpenSandbox Server availability.
"""

import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from code_interpreter import CodeInterpreter, SupportedLanguage

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent2sandbox.settings import load_sandbox_server_config


async def test_basic_sandbox_interaction() -> None:
    print("=" * 60)
    print("Test: Basic Sandbox Interaction (Direct OpenSandbox)")
    print("=" * 60)

    sandbox_cfg_file = Path(
        os.getenv("A2S_SANDBOX_CFG_FILE", "config/sandbox-server-cfg.yaml")
    )
    sandbox_cfg = load_sandbox_server_config(cfg_file=sandbox_cfg_file)

    connection_config = ConnectionConfig(
        domain=sandbox_cfg.domain,
        api_key=sandbox_cfg.api_key,
        request_timeout=timedelta(seconds=sandbox_cfg.request_timeout_seconds),
    )

    async with await Sandbox.create(
        "sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.1",
        connection_config=connection_config,
        entrypoint=["/opt/opensandbox/code-interpreter.sh"],
    ) as sandbox:
        interpreter = await CodeInterpreter.create(sandbox)

        print("\n[1] Checking system information...")
        result = await sandbox.commands.run("uname -a && python --version")
        print(result.logs.stdout[0].text if result.logs.stdout else "No output")

        print("\n[2] Executing Python code...")
        python_code = (
            "import math\n"
            "print(f'Pi is approximately: {math.pi:.5f}')\n"
            "list_len = len([i for i in range(10)])\n"
            "print(f'List length is: {list_len}')\n"
            "result = 2 + 2\n"
            "result"
        )
        result = await interpreter.codes.run(
            python_code, language=SupportedLanguage.PYTHON
        )
        print(result.logs.stdout[0].text if result.logs.stdout else "No output")
        if result.result:
            print(f"Result: {result.result[0].text}")

        print("\n[3] Creating and reading file...")
        await sandbox.files.write_file("/tmp/test.txt", "Hello from inside sandbox!")
        content = await sandbox.files.read_file("/tmp/test.txt")
        print(f"Content: {content}")

    print("\n[4] Sandbox cleaned up successfully.\n")


if __name__ == "__main__":
    asyncio.run(test_basic_sandbox_interaction())
