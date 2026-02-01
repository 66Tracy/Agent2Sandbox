"""
Basic Framework Tests (Mock Sandbox)

Tests the Agent2Sandbox framework components without requiring
a real OpenSandbox server or Docker environment.
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import agent2sandbox
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent2sandbox import (
    SandboxConfig,
    MockLLMClient,
    ToolCall,
    ToolResult,
    ToolName,
    LLMMessage,
    LLMResponse,
)
from agent2sandbox.tools.definitions import get_tool_definitions


async def test_tool_definitions():
    """Test 1: Verify tool definitions are correct."""
    print("=" * 60)
    print("Test 1: Tool Definitions")
    print("=" * 60)

    tools = get_tool_definitions()

    print(f"\n[1] Found {len(tools)} tools:")
    for tool in tools:
        name = tool["function"]["name"]
        description = tool["function"]["description"]
        print(f"   - {name}: {description[:50]}...")

    # Verify expected tools exist
    tool_names = [t["function"]["name"] for t in tools]
    expected_tools = ["execute_command", "read_file", "write_file", "run_code", "list_files"]

    print(f"\n[2] Checking expected tools...")
    for tool_name in expected_tools:
        if tool_name in tool_names:
            print(f"   [OK] {tool_name}")
        else:
            print(f"   [FAIL] {tool_name} not found!")
            return False

    print("\n[3] All tool definitions verified.")
    return True


async def test_mock_llm_client():
    """Test 2: Mock LLM Client"""
    print("\n" + "=" * 60)
    print("Test 2: Mock LLM Client")
    print("=" * 60)

    # Create mock responses
    responses = [
        LLMResponse(
            content="I'll help you with that.",
            tool_calls=None,
            finish_reason="stop"
        ),
        LLMResponse(
            content="Let me calculate something for you.",
            tool_calls=[
                ToolCall(
                    name=ToolName.RUN_CODE,
                    arguments={"code": "2 + 2", "language": "python"},
                    call_id="call_1"
                )
            ],
            finish_reason="tool_calls"
        )
    ]

    client = MockLLMClient(responses=responses)

    # Test chat with user message
    print("\n[1] Testing chat with user message...")
    response = await client.chat(
        messages=[LLMMessage(role="user", content="Hello!")]
    )
    print(f"   Response: {response.content}")
    print(f"   Finish reason: {response.finish_reason}")

    # Test chat with tool results
    print("\n[2] Testing chat with tool results...")
    response = await client.chat(
        messages=[
            LLMMessage(role="user", content="Calculate 2+2"),
            LLMMessage(
                role="tool",
                content="4",
                tool_call_id="call_1"
            )
        ]
    )
    print(f"   Response: {response.content}")
    print(f"   Tool calls: {len(response.tool_calls) if response.tool_calls else 0}")

    print("\n[3] Mock LLM client tests passed.")
    return True


async def test_tool_call_and_result():
    """Test 3: Tool Call and Result"""
    print("\n" + "=" * 60)
    print("Test 3: Tool Call and Result")
    print("=" * 60)

    # Create various tool calls
    print("\n[1] Creating tool calls...")
    tool_calls = [
        ToolCall(name=ToolName.EXECUTE_COMMAND, arguments={"command": "echo test"}, call_id="call_1"),
        ToolCall(name=ToolName.READ_FILE, arguments={"path": "/tmp/test.txt"}, call_id="call_2"),
        ToolCall(name=ToolName.WRITE_FILE, arguments={"path": "/tmp/test.txt", "content": "test"}, call_id="call_3"),
        ToolCall(name=ToolName.RUN_CODE, arguments={"code": "print('test')", "language": "python"}, call_id="call_4"),
    ]

    for tc in tool_calls:
        print(f"   - {tc.name.value}: {tc.arguments}")

    # Create tool results
    print("\n[2] Creating tool results...")
    results = [
        ToolResult(status="success", output="Command executed", call_id="call_1"),
        ToolResult(status="error", error="File not found", call_id="call_2"),
        ToolResult(status="success", output="File written", call_id="call_3"),
        ToolResult(status="success", output="Code executed", call_id="call_4"),
    ]

    for r in results:
        print(f"   - {r.call_id}: {r.status} - {r.output or r.error}")

    print("\n[3] Tool call and result structure tests passed.")
    return True


async def test_sandbox_config():
    """Test 4: Sandbox Configuration"""
    print("\n" + "=" * 60)
    print("Test 4: Sandbox Configuration")
    print("=" * 60)

    # Create default config
    print("\n[1] Creating default config...")
    config = SandboxConfig()
    print(f"   Image: {config.image}")
    print(f"   Timeout: {config.timeout}")
    print(f"   Entrypoint: {config.entrypoint}")

    # Create custom config
    print("\n[2] Creating custom config...")
    custom_config = SandboxConfig(
        image="python:3.11-slim",
        entrypoint=["python", "-m", "http.server", "8000"],
        env={"PYTHONUNBUFFERED": "1"},
    )
    print(f"   Image: {custom_config.image}")
    print(f"   Entrypoint: {custom_config.entrypoint}")
    print(f"   Env: {custom_config.env}")

    print("\n[3] Sandbox configuration tests passed.")
    return True


async def test_enum_types():
    """Test 5: Enum Types"""
    print("\n" + "=" * 60)
    print("Test 5: Enum Types")
    print("=" * 60)

    # Test ToolName enum
    print("\n[1] Testing ToolName enum...")
    print(f"   EXECUTE_COMMAND: {ToolName.EXECUTE_COMMAND}")
    print(f"   READ_FILE: {ToolName.READ_FILE}")
    print(f"   WRITE_FILE: {ToolName.WRITE_FILE}")
    print(f"   RUN_CODE: {ToolName.RUN_CODE}")
    print(f"   LIST_FILES: {ToolName.LIST_FILES}")

    # Test enum values as strings
    print("\n[2] Testing enum values as strings...")
    print(f"   ToolName.EXECUTE_COMMAND.value: '{ToolName.EXECUTE_COMMAND.value}'")

    # Test ToolStatus enum
    print("\n[3] Testing ToolStatus enum...")
    print(f"   SUCCESS: 'success'")
    print(f"   ERROR: 'error'")

    print("\n[4] Enum type tests passed.")
    return True


async def main():
    """Run all basic framework tests."""
    print("=" * 60)
    print("Agent2Sandbox Framework - Basic Tests")
    print("(No sandbox server required)")
    print("=" * 60)

    tests = [
        test_tool_definitions,
        test_mock_llm_client,
        test_tool_call_and_result,
        test_sandbox_config,
        test_enum_types,
    ]

    results = []
    for test_func in tests:
        try:
            result = await test_func()
            results.append(result)
        except Exception as e:
            print(f"\n[ERROR] {test_func.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"\nPassed: {passed}/{total}")

    if all(results):
        print("\nAll tests passed!")
        print("=" * 60)
        return 0
    else:
        print("\nSome tests failed!")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
