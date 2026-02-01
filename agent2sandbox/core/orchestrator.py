"""
Agent Orchestrator - Coordinates interaction between Agent, tools, and sandbox.
"""

import asyncio
from typing import Optional, Callable, Awaitable, List, Any

from opensandbox import Sandbox
from code_interpreter import CodeInterpreter

from agent2sandbox.core.types import (
    SandboxConfig,
    ToolCall,
    ToolResult,
    LLMMessage,
    LLMResponse,
)
from agent2sandbox.core.state_manager import StateManager
from agent2sandbox.adapters.tool_adapter import ToolAdapter
from agent2sandbox.adapters.result_converter import ResultConverter
from agent2sandbox.tools.definitions import get_tool_definitions


class AgentOrchestrator:
    """Orchestrates interaction between Agent, tools, and sandbox."""

    def __init__(
        self,
        config: SandboxConfig,
        llm_client: Optional[Any] = None,
    ):
        self.config = config
        self.llm_client = llm_client
        self.state_manager = StateManager(config)
        self.tool_adapter: Optional[ToolAdapter] = None
        self.result_converter = ResultConverter()

    async def initialize(self) -> None:
        """Initialize the orchestrator by creating the sandbox."""
        # Create sandbox
        sandbox = await Sandbox.create(
            self.config.image,
            entrypoint=self.config.entrypoint,
            env=self.config.env,
            timeout=self.config.timeout,
        )

        self.state_manager.sandbox = sandbox

        # Create code interpreter if using code-interpreter image
        try:
            code_interpreter = await CodeInterpreter.create(sandbox)
            self.state_manager.code_interpreter = code_interpreter
        except Exception:
            # Code interpreter may not be available, that's OK
            pass

        # Create tool adapter
        self.tool_adapter = ToolAdapter(
            sandbox,
            self.state_manager.code_interpreter,
        )

        self.state_manager.mark_initialized()

    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call."""
        if self.tool_adapter is None:
            return ToolResult(
                status="error",
                error="Tool adapter not initialized",
            )

        self.state_manager.record_tool_call(tool_call)

        result = await self.tool_adapter.execute(tool_call)
        self.state_manager.record_result(result)
        self.state_manager.increment_step()

        return result

    async def execute_tools(self, tool_calls: List[ToolCall]) -> List[ToolResult]:
        """Execute multiple tool calls in parallel."""
        tasks = [self.execute_tool(tc) for tc in tool_calls]
        return await asyncio.gather(*tasks)

    async def step(
        self,
        user_message: str,
        tool_call_handler: Optional[Callable[[List[ToolCall]], Awaitable[List[ToolResult]]]] = None,
    ) -> LLMResponse:
        """
        Execute a single step of the agent interaction.

        Args:
            user_message: The user message to process
            tool_call_handler: Optional handler for tool calls. If provided, this handler
                              will be called to execute tools instead of using the internal
                              tool adapter. Useful for testing or custom implementations.

        Returns:
            LLMResponse: The response from the LLM
        """
        if tool_call_handler:
            # Use the provided handler for tool execution
            response = await self.llm_client.chat(
                messages=[LLMMessage(role="user", content=user_message)],
                tools=get_tool_definitions(),
            )

            if response.tool_calls:
                results = await tool_call_handler(response.tool_calls)
                # Continue the conversation with tool results
                response = await self._continue_conversation(response.tool_calls, results)

            return response
        else:
            # Internal tool execution (requires LLM client)
            if self.llm_client is None:
                raise ValueError("LLM client is required for autonomous execution")

            response = await self.llm_client.chat(
                messages=[LLMMessage(role="user", content=user_message)],
                tools=get_tool_definitions(),
            )

            # Execute tools if requested
            if response.tool_calls:
                results = await self.execute_tools(response.tool_calls)
                # Continue the conversation with tool results
                response = await self._continue_conversation(response.tool_calls, results)

            return response

    async def _continue_conversation(
        self,
        tool_calls: List[ToolCall],
        results: List[ToolResult],
    ) -> LLMResponse:
        """Continue the conversation with tool results."""
        messages: List[LLMMessage] = []

        # Add assistant message with tool calls
        messages.append(
            LLMMessage(
                role="assistant",
                tool_calls=tool_calls,
            )
        )

        # Add tool results
        for tool_call, result in zip(tool_calls, results):
            messages.append(
                LLMMessage(
                    role="tool",
                    content=result.output or result.error or "No output",
                    tool_call_id=tool_call.call_id,
                    name=tool_call.name.value,
                )
            )

        # Get next response from LLM
        if self.llm_client is None:
            raise ValueError("LLM client is required for autonomous execution")

        return await self.llm_client.chat(
            messages=messages,
            tools=get_tool_definitions(),
        )

    async def run(
        self,
        user_message: str,
        max_steps: int = 10,
        completion_check: Optional[Callable[[LLMResponse], bool]] = None,
    ) -> LLMResponse:
        """
        Run the full task loop until completion or max steps reached.

        Args:
            user_message: The initial user message
            max_steps: Maximum number of steps to execute
            completion_check: Optional function to check if task is complete

        Returns:
            LLMResponse: The final response from the LLM
        """
        current_message = user_message
        response = None

        for _ in range(max_steps):
            response = await self.step(current_message)

            # Check if task is complete
            if completion_check and completion_check(response):
                break

            # Check if no more tool calls
            if not response.tool_calls:
                break

            # Continue with the next response
            current_message = response.content or ""

        return response

    def get_tools(self) -> List[dict]:
        """Get tool definitions for the LLM."""
        return get_tool_definitions()

    async def close(self) -> None:
        """Close the orchestrator and clean up resources."""
        if self.state_manager.sandbox:
            await self.state_manager.sandbox.kill()
            await self.state_manager.sandbox.close()
