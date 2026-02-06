import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent2sandbox.config import Config
from agent2sandbox.llm import OpenAIClient
from agent2sandbox import AgentOrchestrator, SandboxConfig


async def test_simple():
    config = Config.from_env()

    print("Configuration:")
    print(f"  Model: {config.model_name}")

    sandbox_config = SandboxConfig(
        image=config.sandbox_image,
        entrypoint=["/opt/opensandbox/code-interpreter.sh"],
        domain=os.getenv("SANDBOX_DOMAIN", "localhost:8080"),
        api_key=os.getenv("SANDBOX_API_KEY"),
    )

    llm_client = OpenAIClient.from_config(config)
    orchestrator = AgentOrchestrator(sandbox_config, llm_client=llm_client)

    try:
        print("Initializing...")
        await orchestrator.initialize()
        print(f"Sandbox ID: {orchestrator.state_manager.sandbox_id}")

        print("\nRunning simple task with max_steps=2...")
        response = await orchestrator.run(
            "Execute 'echo hello' and show me the output",
            max_steps=2,
            on_step=lambda step, resp: print(
                f"  Step {step}: {resp.content[:50] if resp.content else 'No content'}"
            ),
        )

        print(f"\nFinal response: {response.content}")
        print(f"Tool calls: {len(response.tool_calls) if response.tool_calls else 0}")
        print(f"Finish reason: {response.finish_reason}")
        print(f"\nConversation history:")
        for i, msg in enumerate(orchestrator.conversation_history):
            print(
                f"  {i + 1}. {msg.role}: {msg.content[:50] if msg.content else '[no content]'}"
            )
            if msg.tool_calls:
                print(f"     Tool calls: {[tc.name.value for tc in msg.tool_calls]}")
            if msg.tool_call_id:
                print(f"     Tool call ID: {msg.tool_call_id}")

    finally:
        await orchestrator.close()
        print("\nCleaned up.")


if __name__ == "__main__":
    asyncio.run(test_simple())
