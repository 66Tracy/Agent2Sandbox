"""
Agent Task Tests

Tests representative agent tasks with real LLM API and sandbox interaction.
"""

import asyncio
import sys
import os
from pathlib import Path

# Add parent directory to path to import agent2sandbox
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent2sandbox.config import Config
from agent2sandbox.llm import OpenAIClient
from agent2sandbox import (
    AgentOrchestrator,
    SandboxConfig,
    ToolCall,
    ToolName,
)


async def test_data_analysis_task():
    """
    Task 1: Data Analysis
    Agent analyzes data, calculates statistics, and saves results to a file.

    Task:
    "请分析以下数据：[10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    计算平均值、最大值、最小值、标准差，并将结果保存到 /tmp/analysis.txt"
    """
    print("=" * 60)
    print("Task 1: Data Analysis")
    print("=" * 60)

    # Load config
    config = Config.from_env()
    config.validate()

    print(f"\n[1] Configuration:")
    print(f"   Model: {config.model_name}")
    print(f"   Sandbox: {config.sandbox_image}")

    # Create orchestrator
    sandbox_config = SandboxConfig(
        image=config.sandbox_image,
        entrypoint=["/opt/opensandbox/code-interpreter.sh"],
        domain=os.getenv("SANDBOX_DOMAIN", "localhost:8080"),
        api_key=os.getenv("SANDBOX_API_KEY"),
    )

    llm_client = OpenAIClient.from_config(config)
    orchestrator = AgentOrchestrator(sandbox_config, llm_client=llm_client)

    # Step callback for progress tracking
    def on_step(step: int, response):
        tool_calls = response.tool_calls or []
        print(f"\n[Step {step}]")
        print(
            f"   Response: {response.content[:80]}{'...' if len(response.content) > 80 else ''}"
        )
        print(f"   Tool calls: {len(tool_calls)}")
        if tool_calls:
            for tc in tool_calls:
                print(f"      - {tc.name.value}")

    try:
        # Initialize orchestrator
        print("\n[2] Initializing orchestrator...")
        await orchestrator.initialize()
        print(f"   Sandbox ID: {orchestrator.state_manager.sandbox_id}")

        # Define the task
        task = """
请分析以下数据：[10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

要求：
1. 使用 Python 计算以下统计量：
   - 平均值 (mean)
   - 最大值 (max)
   - 最小值 (min)
   - 标准差 (standard deviation)

2. 将分析结果保存到文件 /tmp/analysis.txt

3. 读取文件内容验证保存是否正确

4. 最后总结分析结果
"""

        print("\n[3] Starting task execution...")
        print(f"   Task: {task[:100]}...")

        # Run the task with step callback
        response = await orchestrator.run(
            task,
            max_steps=config.max_steps,
            on_step=on_step,
        )

        print("\n" + "=" * 60)
        print("Task Completion Summary")
        print("=" * 60)
        print(f"\nFinal Response:")
        print(f"   {response.content}")
        print(f"\nTotal Steps: {orchestrator.state_manager.get_step_count()}")

        # Verify task completion
        success = True
        checks = []

        # Check 1: Verify the response contains analysis
        if response.content and any(
            word in response.content.lower()
            for word in ["平均", "mean", "最大", "max", "最小", "min"]
        ):
            checks.append(("Analysis in response", True))
        else:
            checks.append(("Analysis in response", False))
            success = False

        # Check 2: Check if file was created by reading it
        file_read_result = None
        try:
            from agent2sandbox import ToolName

            file_read_result = await orchestrator.execute_tool(
                ToolCall(
                    name=ToolName.READ_FILE, arguments={"path": "/tmp/analysis.txt"}
                )
            )
            if file_read_result.status.value == "success" and file_read_result.data:
                checks.append(("File created and readable", True))
                print(f"\nFile Content:\n{file_read_result.data}")
            else:
                checks.append(("File created and readable", False))
                success = False
        except Exception as e:
            checks.append(("File created and readable", False))
            print(f"\nError reading file: {e}")
            success = False

        # Check 3: Verify statistics are in the file
        if (
            file_read_result
            and file_read_result.data
            and (
                "mean" in file_read_result.data.lower()
                or "平均" in file_read_result.data
            )
        ):
            checks.append(("Statistics in file", True))
        else:
            checks.append(("Statistics in file", False))
            success = False

        # Print verification results
        print("\n" + "=" * 60)
        print("Verification Results")
        print("=" * 60)
        for check, passed in checks:
            status = "✅" if passed else "❌"
            print(f"{status} {check}")

        if success:
            print("\n🎉 Data Analysis Task PASSED")
            return True
        else:
            print("\n❌ Data Analysis Task FAILED")
            return False

    finally:
        await orchestrator.close()
        print("\n[4] Orchestrator cleaned up.")


async def test_code_debugging_task():
    """
    Task 2: Code Debugging
    Agent writes code, tests it, discovers errors, and fixes them.

    Task:
    "请编写一个 Python 函数来计算斐波那契数列的第 n 项，
    测试 n=10 的情况，如果输出不是 55，请调试并修复代码。"
    """
    print("\n" + "=" * 60)
    print("Task 2: Code Debugging")
    print("=" * 60)

    # Load config
    config = Config.from_env()
    config.validate()

    print(f"\n[1] Configuration:")
    print(f"   Model: {config.model_name}")

    # Create orchestrator
    sandbox_config = SandboxConfig(
        image=config.sandbox_image,
        entrypoint=["/opt/opensandbox/code-interpreter.sh"],
        domain=os.getenv("SANDBOX_DOMAIN", "localhost:8080"),
        api_key=os.getenv("SANDBOX_API_KEY"),
    )

    llm_client = OpenAIClient.from_config(config)
    orchestrator = AgentOrchestrator(sandbox_config, llm_client=llm_client)

    # Step callback for progress tracking
    def on_step(step: int, response):
        tool_calls = response.tool_calls or []
        print(f"\n[Step {step}]")
        print(
            f"   Response: {response.content[:80]}{'...' if len(response.content) > 80 else ''}"
        )
        print(f"   Tool calls: {len(tool_calls)}")
        if tool_calls:
            for tc in tool_calls:
                print(f"      - {tc.name.value}")

    try:
        # Initialize orchestrator
        print("\n[2] Initializing orchestrator...")
        await orchestrator.initialize()
        print(f"   Sandbox ID: {orchestrator.state_manager.sandbox_id}")

        # Define the task
        task = """
请编写一个 Python 函数来计算斐波那契数列的第 n 项。

要求：
1. 实现斐波那契函数（可以使用递归或迭代）
2. 测试 n=10 的情况
3. 如果输出不是 55，请调试代码并修复错误
4. 重新测试验证修复后的结果
5. 总结修复过程和最终结果

注意：正确的斐波那契数列第10项应该是 55
"""

        print("\n[3] Starting task execution...")
        print(f"   Task: {task[:100]}...")

        # Run the task with step callback
        response = await orchestrator.run(
            task,
            max_steps=15,  # Allow more steps for debugging
            on_step=on_step,
        )

        print("\n" + "=" * 60)
        print("Task Completion Summary")
        print("=" * 60)
        print(f"\nFinal Response:")
        print(f"   {response.content}")
        print(f"\nTotal Steps: {orchestrator.state_manager.get_step_count()}")

        # Verify task completion
        success = True
        checks = []

        # Check 1: Verify the response mentions testing and debugging
        if response.content and any(
            word in response.content.lower()
            for word in ["test", "debug", "debugging", "fix", "修复", "测试"]
        ):
            checks.append(("Testing/debugging mentioned", True))
        else:
            checks.append(("Testing/debugging mentioned", False))
            success = False

        # Check 2: Verify the final result is 55
        if response.content and "55" in response.content:
            checks.append(("Correct result (55) in response", True))
        else:
            checks.append(("Correct result (55) in response", False))
            success = False

        # Check 3: Verify fibonacci is mentioned
        if response.content and (
            "fibonacci" in response.content.lower() or "斐波那契" in response.content
        ):
            checks.append(("Fibonacci mentioned", True))
        else:
            checks.append(("Fibonacci mentioned", False))
            success = False

        # Check 4: Verify the task involved code execution
        if orchestrator.state_manager.get_step_count() > 3:
            checks.append(("Multiple steps (reasonable debugging)", True))
        else:
            checks.append(("Multiple steps (reasonable debugging)", False))

        # Print verification results
        print("\n" + "=" * 60)
        print("Verification Results")
        print("=" * 60)
        for check, passed in checks:
            status = "✅" if passed else "❌"
            print(f"{status} {check}")

        if success:
            print("\n🎉 Code Debugging Task PASSED")
            return True
        else:
            print("\n❌ Code Debugging Task FAILED")
            return False

    finally:
        await orchestrator.close()
        print("\n[4] Orchestrator cleaned up.")


async def main():
    """Run all agent task tests."""
    print("=" * 60)
    print("Agent2Sandbox - Agent Task Tests")
    print("=" * 60)
    print("\nThese tests verify that the agent can:")
    print("  1. Analyze data and save results")
    print("  2. Write, test, and debug code")
    print("=" * 60)

    try:
        # Check if API_KEY is set
        config = Config.from_env()
        if not config.api_key or config.api_key == "YOUR_API_KEY_HERE":
            print("\n❌ API_KEY not configured!")
            print(
                "Please set your API key in agent2sandbox/.env file or via environment variable."
            )
            print("Example: API_KEY=your_actual_api_key_here")
            return 1

        # Task 1: Data Analysis
        result1 = await test_data_analysis_task()

        # Task 2: Code Debugging
        result2 = await test_code_debugging_task()

        # Summary
        print("\n" + "=" * 60)
        print("Task Summary")
        print("=" * 60)

        results = [
            ("Data Analysis Task", result1),
            ("Code Debugging Task", result2),
        ]

        passed = sum(1 for _, result in results if result)
        total = len(results)

        for name, result in results:
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"{name:.<40} {status}")

        print(f"\nTotal: {passed}/{total} tasks passed")

        if passed == total:
            print("\n🎉 All tasks passed!")
            print("\n✅ Agent can successfully interact with sandbox environment")
            print("✅ Agent can complete complex multi-step tasks")
            print("✅ Agent can debug and fix code errors")
            return 0
        else:
            print(f"\n⚠️  {total - passed} task(s) failed")
            return 1

    except ValueError as e:
        if "API_KEY" in str(e):
            print(f"\n❌ {e}")
            print("\nPlease set your API key in agent2sandbox/.env file.")
            return 1
        raise
    except Exception as e:
        print(f"\n❌ Task execution failed with error: {e}")
        import traceback

        traceback.print_exc()
        return 1

    except Exception as e:
        print(f"\n❌ Task execution failed with error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
