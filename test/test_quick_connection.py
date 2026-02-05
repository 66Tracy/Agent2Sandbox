"""
Quick Sandbox Connection Test
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from opensandbox import Sandbox
from datetime import timedelta


async def test_simple_connection():
    """Test simple sandbox creation and command execution."""
    print("Testing simple sandbox connection...")

    try:
        print("\n[1] Creating sandbox...")
        sandbox = await Sandbox.create(
            "sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.1",
            entrypoint=["/opt/opensandbox/code-interpreter.sh"],
            timeout=timedelta(minutes=2),
        )
        print(f"[2] Sandbox created: {sandbox.id}")

        async with sandbox:
            print("[3] Running simple command...")
            result = await sandbox.commands.run("echo 'Sandbox connection successful!'")

            if result.logs.stdout:
                print(f"[4] Output: {result.logs.stdout[0].text}")
            else:
                print("[4] No output")

        print("\n✅ Test PASSED")
        return True

    except Exception as e:
        print(f"\n❌ Test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    result = await test_simple_connection()
    return 0 if result else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
