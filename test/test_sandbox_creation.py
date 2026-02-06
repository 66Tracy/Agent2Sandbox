"""
Test Sandbox Creation

Simple test to verify sandbox can be created with the configured image.
"""

import asyncio
import sys, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from opensandbox import Sandbox
from datetime import timedelta
from opensandbox.config import ConnectionConfig

async def test_sandbox_creation():
    """Test simple sandbox creation."""
    print("Testing sandbox creation...")

    try:
        # Try creating sandbox with code-interpreter image
        print("\n[1] Creating sandbox with code-interpreter image...")
        domain = os.getenv("SANDBOX_DOMAIN", "localhost:8080")
        api_key = os.getenv("SANDBOX_API_KEY")
        image = os.getenv(
            "SANDBOX_IMAGE",
            "sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.1",
        )

        config = ConnectionConfig(
            domain=domain,
            api_key=api_key,
            request_timeout=timedelta(seconds=60),
        )

        sandbox = await Sandbox.create(
            image,
            connection_config=config,
            entrypoint=["/opt/opensandbox/code-interpreter.sh"]
        )   

        async with sandbox:
            print(f"[2] Sandbox created successfully: {sandbox.id}")

            # Test a simple command
            result = await sandbox.commands.run("echo 'Hello from sandbox!'")
            print(f"[3] Command output: {result.logs.stdout[0].text}")

        print("\n✅ Sandbox creation test PASSED")
        return True

    except Exception as e:
        print(f"\n❌ Sandbox creation test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    result = await test_sandbox_creation()
    return 0 if result else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
