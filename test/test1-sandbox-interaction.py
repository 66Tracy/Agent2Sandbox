"""
Test 1: Sandbox Interaction

This test verifies basic interaction between Agent and OpenSandbox
using Agent2Sandbox framework.

The test covers:
1. Sandbox initialization
2. Tool execution (command, file operations, code execution)
3. Multi-round interaction
4. Cleanup
"""

import asyncio
import sys
from pathlib import Path
from datetime import timedelta

# Add parent directory to path to import agent2sandbox
sys.path.insert(0, str(Path(__file__).parent.parent))

from opensandbox import Sandbox
from code_interpreter import CodeInterpreter, SupportedLanguage

from agent2sandbox import (
    AgentOrchestrator,
    SandboxConfig,
    MockLLMClient,
    ToolCall,
    ToolResult,
    ToolName,
    LLMMessage,
    LLMResponse,
)


async def test_basic_sandbox_interaction():
    """
    Test 1: Basic sandbox interaction without Agent2Sandbox framework.
    This is original test to verify OpenSandbox works correctly.
    """
    print("=" * 60)
    print("Test 1: Basic Sandbox Interaction (Direct OpenSandbox)")
    print("=" * 60)

    # Create sandbox with code interpreter
    async with await Sandbox.create(
        "python:3.12-slim",
        entrypoint=["/opt/opensandbox/code-interpreter.sh"],
        timeout=timedelta(minutes=5),
    ) as sandbox:

        # Create code interpreter
        interpreter = await CodeInterpreter.create(sandbox)

        # Test 1: Check system info via command
        print("\n[1] Checking system information...")
        result = await sandbox.commands.run("uname -a && python --version")
        print(result.logs.stdout[0].text if result.logs.stdout else "No output")

        # Test 2: Execute Python code via code interpreter
        print("\n[2] Executing Python code...")
        python_code = """import math
print(f"Pi is approximately: {math.pi:.5f}")
list_len = len([i for i in range(10)])
print(f"List length is: {list_len}")
result = 2 + 2
result"""
        result = await interpreter.codes.run(python_code, language=SupportedLanguage.PYTHON)
        print(result.logs.stdout[0].text if result.logs.stdout else "No output")
        if result.result:
            print(f"Result: {result.result[0].text}")

        # Test 3: File operations
        print("\n[3] Creating and reading file...")
        await sandbox.files.write_file("/tmp/test.txt", "Hello from inside sandbox!")
        content = await sandbox.files.read_file("/tmp/test.txt")
        print(f"Content: {content}")

    print("\n[4] Sandbox cleaned up successfully.\n")


async def test_agent2sandbox_tool_execution():
    """
    Test 2: Agent2Sandbox Framework - Tool Execution

    Tests: - AgentOrchestrator initialization
    - Tool execution through framework
    - Various tool types (command, file, code)
    """
    print("=" * 60)
    print("Test 2: Agent2Sandbox Framework - Tool Execution")
    print("=" * 60)

    # Create orchestrator with sandbox config
    config = SandboxConfig(
        image="python:3.12-slim",
        entrypoint=["/opt/opensandbox/code-interpreter.sh"],
    )

    orchestrator = AgentOrchestrator(config)

    try:
        # Initialize orchestrator
        print("\n[1] Initializing AgentOrchestrator...")
        await orchestrator.initialize()
        print(f"   Sandbox initialized: {orchestrator.state_manager.sandbox_id}")

        # Test execute_command tool
        print("\n[2] Testing execute_command tool...")
        tool_call = ToolCall(
            name=ToolName.EXECUTE_COMMAND,
            arguments={"command": "echo 'Hello from Agent2Sandbox!'"}
        )
        result = await orchestrator.execute_tool(tool_call)
        print(f"   Status: {result.status}")
        print(f"   Output: {result.output}")

        # Test write_file tool
        print("\n[3] Testing write_file tool...")
        tool_call = ToolCall(
            name=ToolName.WRITE_FILE,
            arguments={
                "path": "/tmp/test.txt",
                "content": "This is a test file created by Agent2Sandbox."
            }
        )
        result = await orchestrator.execute_tool(tool_call)
        print(f"   Status: {result.status}")
        print(f"   Output: {result.output}")

        # Test read_file tool
        print("\n[4] Testing read_file tool...")
        tool_call = ToolCall(
            name=ToolName.READ_FILE,
            arguments={"path": "/tmp/test.txt"}
        )
        result = await orchestrator.execute_tool(tool_call)
        print(f"   Status: {result.status}")
        print(f"   Content: {result.data}")

        # Test run_code tool (Python)
        print("\n[5] Testing run_code tool (Python)...")
        tool_call = ToolCall(
            name=ToolName.RUN_CODE,
            arguments={
                "code": "import math\nprint(f'Pi = {math.pi}')\n2 + 2",
                "language": "python"
            }
        )
        result = await orchestrator.execute_tool(tool_call)
        print(f"   Status: {result.status}")
        print(f"   Output: {result.output}")

        # Test list_files tool
        print("\n[6] Testing list_files tool...")
        tool_call = ToolCall(
            name=ToolName.LIST_FILES,
            arguments={"path": "/tmp", "pattern": "*.txt"}
        )
        result = await orchestrator.execute_tool(tool_call)
        print(f"   Status: {result.status}")
        print(f"   Files: {result.data}")

        print("\n[7] Tool execution history:")
        print(f"   Total tool calls: {orchestrator.state_manager.get_step_count()}")

    finally:
        await orchestrator.close()
        print("\n[8] Orchestrator cleaned up successfully.\n")


async def test_agent2sandbox_multi_round():
    """
    Test 3: Agent2Sandbox Framework - Multi-round Interaction

    Tests multi-round interaction between Agent and sandbox:
    - User requests task
    - Agent calls tools
    - Tools return results
    - Agent processes results and continues
    """
    print("=" * 60)
    print("Test 3: Agent2Sandbox Framework - Multi-round Interaction")
    print("=" * 60)

    # Create orchestrator
    config = SandboxConfig(
        image="python:3.12-slim",
        entrypoint=["/opt/opensandbox/code-interpreter.sh"],
    )

    orchestrator = AgentOrchestrator(config)

    # Create mock LLM client that returns predefined tool calls
    responses = [
        # First response: Ask to calculate fibonacci
        LLMResponse(
            content="I'll calculate the 10th Fibonacci number for you.",
            tool_calls=[
                ToolCall(
                    name=ToolName.RUN_CODE,
                    arguments={
                        "code": """def fibonacci(n):
    if n <= 1:
        return n
    return fibonacci(n-1) + fibonacci(n-2)

result = fibonacci(10)
print(f'The 10th Fibonacci number is: {result}')
result""",
                        "language": "python"
                    },
                    call_id="call_1"
                )
            ],
        ),
        # Second response: Final answer
        LLMResponse(
            content="The 10th Fibonacci number is 55.",
            tool_calls=None,
            finish_reason="stop"
        )
    ]

    llm_client = MockLLMClient(responses=responses)
    orchestrator.llm_client = llm_client

    try:
        # Initialize
        print("\n[1] Initializing...")
        await orchestrator.initialize()

        # Run multi-round interaction
        print("\n[2] Running multi-round interaction...")
        response = await orchestrator.run(
            user_message="Calculate the 10th Fibonacci number",
            max_steps=5
        )

        print(f"\n[3] Final response: {response.content}")
        print(f"   Finish reason: {response.finish_reason}")
        print(f"   Total steps: {orchestrator.state_manager.get_step_count()}")

    finally:
        await orchestrator.close()
        print("\n[4] Orchestrator cleaned up successfully.\n")


async def test_agent2sandbox_with_custom_handler():
    """
    Test 4: Agent2Sandbox Framework - Custom Tool Handler

    Tests using a custom tool handler for executing tools,
    allowing more control over the execution process.
    """
    print("=" * 60)
    print("Test 4: Agent2Sandbox Framework - Custom Tool Handler")
    print("=" * 60)

    # Create orchestrator
    config = SandboxConfig(
        image="python:3.12-slim",
        entrypoint=["/opt/opensandbox/code-interpreter.sh"],
    )

    orchestrator = AgentOrchestrator(config)

    try:
        # Initialize
        print("\n[1] Initializing...")
        await orchestrator.initialize()

        # Define custom tool handler
        async def custom_tool_handler(tool_calls):
            print(f"   [Custom Handler] Processing {len(tool_calls)} tool call(s)...")
            results = []

            for tc in tool_calls:
                print(f"   [Custom Handler] Executing: {tc.name.value}")
                result = await orchestrator.execute_tool(tc)
                results.append(result)
                print(f"   [Custom Handler] Result: {result.status}")

            return results

        # Test with custom handler
        print("\n[2] Testing with custom tool handler...")
        tool_calls = [
            ToolCall(
                name=ToolName.EXECUTE_COMMAND,
                arguments={"command": "echo 'Custom handler test'"},
                call_id="call_1"
            ),
            ToolCall(
                name=ToolName.EXECUTE_COMMAND,
                arguments={"command": "echo 'Second command'"},
                call_id="call_2"
            ),
        ]

        results = await orchestrator.execute_tools(tool_calls)

        print(f"\n[3] All tools executed: {len(results)} results")

    finally:
        await orchestrator.close()
        print("\n[4] Orchestrator cleaned up successfully.\n")


async def main():
    """Run all tests."""
    try:
        # Test 1: Basic sandbox interaction
        await test_basic_sandbox_interaction()

        # Test 2: Agent2Sandbox tool execution
        await test_agent2sandbox_tool_execution()

        # Test 3: Multi-round interaction
        await test_agent2sandbox_multi_round()

        # Test 4: Custom tool handler
        await test_agent2sandbox_with_custom_handler()

        print("=" * 60)
        print("All tests completed successfully!")
        print("=" * 60)

    except Exception as e:
        print(f"\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
