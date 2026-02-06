"""
Real LLM API Integration Tests

Tests the integration with real LLM API (DeepSeek).
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path to import agent2sandbox
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent2sandbox.config import Config
from agent2sandbox.llm import OpenAIClient, LLMMessage, LLMResponse
from agent2sandbox.tools.definitions import get_tool_definitions


async def test_api_connection():
    """
    Test 1: Basic API Connection
    Verify that we can connect to the LLM API and get a response.
    """
    print("=" * 60)
    print("Test 1: Basic API Connection")
    print("=" * 60)

    # Load config from environment
    config = Config.from_env()
    config.validate()

    print(f"\n[1] Configuration loaded:")
    print(f"   Base URL: {config.base_url}")
    print(f"   Model: {config.model_name}")
    print(f"   API Key: {config.api_key[:10]}...{config.api_key[-4:]}")

    # Create LLM client
    print("\n[2] Creating LLM client...")
    llm_client = OpenAIClient.from_config(config)

    # Simple chat request
    print("\n[3] Sending simple chat request...")
    response = await llm_client.chat(
        messages=[
            LLMMessage(
                role="user",
                content="Hello, please respond with 'API connection successful!'",
            )
        ]
    )

    print(f"\n[4] Response received:")
    print(f"   Content: {response.content}")
    print(f"   Finish reason: {response.finish_reason}")

    # Verify response
    if response.content and "successful" in response.content.lower():
        print("\n[5] ✅ API connection test PASSED")
        return True
    else:
        print("\n[5] ❌ API connection test FAILED")
        print(f"   Unexpected response: {response.content}")
        return False


async def test_tool_calling():
    """
    Test 2: Tool Calling
    Verify that the LLM can correctly call tools.
    """
    print("\n" + "=" * 60)
    print("Test 2: Tool Calling")
    print("=" * 60)

    # Load config
    config = Config.from_env()
    llm_client = OpenAIClient.from_config(config)

    # Get tool definitions
    tools = get_tool_definitions()

    print(f"\n[1] Available tools: {len(tools)}")

    # Request that requires tool calling
    print("\n[2] Sending request with tool definitions...")
    response = await llm_client.chat(
        messages=[
            LLMMessage(
                role="user", content="Please execute the command 'echo hello world'"
            )
        ],
        tools=tools,
    )

    print(f"\n[3] Response received:")
    print(f"   Content: {response.content}")
    print(f"   Tool calls: {len(response.tool_calls) if response.tool_calls else 0}")
    print(f"   Finish reason: {response.finish_reason}")

    if response.tool_calls:
        print("\n[4] Tool calls:")
        for i, tool_call in enumerate(response.tool_calls, 1):
            print(f"   [{i}] {tool_call.name.value}: {tool_call.arguments}")

        # Verify the tool call is correct
        if response.tool_calls[0].name.value == "execute_command":
            print("\n[5] ✅ Tool calling test PASSED")
            return True
        else:
            print(f"\n[5] ❌ Unexpected tool: {response.tool_calls[0].name.value}")
            return False
    else:
        print("\n[5] ❌ No tool calls in response")
        return False


async def test_multi_turn_conversation():
    """
    Test 3: Multi-turn Conversation
    Verify that the LLM can maintain context across multiple turns.
    """
    print("\n" + "=" * 60)
    print("Test 3: Multi-turn Conversation")
    print("=" * 60)

    # Load config
    config = Config.from_env()
    llm_client = OpenAIClient.from_config(config)

    print("\n[1] Starting multi-turn conversation...")

    # First turn
    print("\n[2] First turn: User asks about Python")
    response1 = await llm_client.chat(
        messages=[LLMMessage(role="user", content="What is Python?")]
    )
    if response1.content:
        print(f"   Response: {response1.content[:100]}...")

    # Second turn (context aware)
    print("\n[3] Second turn: Follow-up question")
    response2 = await llm_client.chat(
        messages=[
            LLMMessage(role="user", content="What is Python?"),
            LLMMessage(role="assistant", content=response1.content),
            LLMMessage(role="user", content="What are its main uses?"),
        ]
    )
    if response2.content:
        print(f"   Response: {response2.content[:100]}...")

    # Verify context is maintained
    if response2.content and "uses" in response2.content.lower():
        print("\n[4] ✅ Multi-turn conversation test PASSED")
        return True
    else:
        print("\n[4] ❌ Multi-turn conversation test FAILED")
        return False


async def test_error_handling():
    """
    Test 4: Error Handling
    Verify that the client handles errors gracefully.
    """
    print("\n" + "=" * 60)
    print("Test 4: Error Handling")
    print("=" * 60)

    # Create config with invalid API key
    print("\n[1] Testing with invalid API key...")
    try:
        config = Config(api_key="invalid_key_12345")
        llm_client = OpenAIClient.from_config(config)

        response = await llm_client.chat(
            messages=[LLMMessage(role="user", content="Hello")]
        )

        print(f"\n[2] Response: {response.content}")
        print("\n[3] ❌ Error handling test FAILED - Should have raised an exception")
        return False

    except Exception as e:
        print(f"\n[2] Exception caught: {type(e).__name__}")
        print(f"   Message: {str(e)[:100]}...")
        print("\n[3] ✅ Error handling test PASSED")
        return True


async def main():
    """Run all LLM API integration tests."""
    print("=" * 60)
    print("Agent2Sandbox - Real LLM API Integration Tests")
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

        # Test 1: API Connection
        result1 = await test_api_connection()

        # Test 2: Tool Calling
        result2 = await test_tool_calling()

        # Test 3: Multi-turn Conversation
        result3 = await test_multi_turn_conversation()

        # Test 4: Error Handling
        result4 = await test_error_handling()

        # Summary
        print("\n" + "=" * 60)
        print("Test Summary")
        print("=" * 60)

        results = [
            ("API Connection", result1),
            ("Tool Calling", result2),
            ("Multi-turn Conversation", result3),
            ("Error Handling", result4),
        ]

        passed = sum(1 for _, result in results if result)
        total = len(results)

        for name, result in results:
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"{name:.<40} {status}")

        print(f"\nTotal: {passed}/{total} tests passed")

        if passed == total:
            print("\n🎉 All tests passed!")
            return 0
        else:
            print(f"\n⚠️  {total - passed} test(s) failed")
            return 1

    except ValueError as e:
        if "API_KEY" in str(e):
            print(f"\n❌ {e}")
            print("\nPlease set your API key in agent2sandbox/.env file.")
            return 1
        raise
    except Exception as e:
        print(f"\n❌ Test execution failed with error: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
