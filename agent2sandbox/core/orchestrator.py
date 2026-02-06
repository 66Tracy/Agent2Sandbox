"""
Agent Orchestrator - Coordinates interaction between Agent, tools, and sandbox.
"""

import asyncio
import os
from typing import Optional, Callable, Awaitable, List, Any
from datetime import timedelta

from opensandbox import Sandbox
from opensandbox.config import ConnectionConfig
from code_interpreter import CodeInterpreter

from agent2sandbox.core.types import (
    SandboxConfig,
    ToolCall,
    ToolResult,
    ToolStatus,
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
        self.conversation_history: List[LLMMessage] = []

    async def initialize(self) -> None:
        """Initialize the orchestrator by creating of sandbox."""
        # Get connection config from environment or sandbox config
        domain = self.config.domain or os.getenv("SANDBOX_DOMAIN", "localhost:8080")
        api_key = self.config.api_key or os.getenv("SANDBOX_API_KEY")

        # Create connection config
        connection_config = ConnectionConfig(
            domain=domain,
            api_key=api_key,
            request_timeout=timedelta(seconds=60),
        )

        # Create sandbox with connection config
        sandbox = await Sandbox.create(
            self.config.image,
            connection_config=connection_config,
            entrypoint=self.config.entrypoint
            or ["/opt/opensandbox/code-interpreter.sh"],
            env=self.config.env,
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

        # Initialize conversation history
        self.conversation_history = []

        self.state_manager.mark_initialized()

    async def execute_tool(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call."""
        if self.tool_adapter is None:
            return ToolResult(
                status=ToolStatus.ERROR,
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
        tool_call_handler: Optional[
            Callable[[List[ToolCall]], Awaitable[List[ToolResult]]]
        ] = None,
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
        if self.llm_client is None:
            raise ValueError("LLM client is required for autonomous execution")

        # Add user message to history
        self.conversation_history.append(LLMMessage(role="user", content=user_message))

        # Get response from LLM
        response = await self.llm_client.chat(
            messages=self.conversation_history,
            tools=get_tool_definitions(),
        )

        if tool_call_handler:
            # Use the provided handler for tool execution
            if response.tool_calls:
                results = await tool_call_handler(response.tool_calls)
                # Continue the conversation with tool results
                response = await self._continue_conversation(
                    response.tool_calls, results
                )
        else:
            # Internal tool execution
            # Execute tools if requested
            if response.tool_calls:
                results = await self.execute_tools(response.tool_calls)
                # Continue the conversation with tool results
                response = await self._continue_conversation(
                    response.tool_calls, results
                )
            else:
                # Add final response to history
                self._add_response_to_history(response)

        return response

    def _add_response_to_history(self, response: LLMResponse) -> None:
        """Add assistant response to conversation history."""
        if not response:
            return

        if response.tool_calls:
            # Add assistant message with tool calls
            self.conversation_history.append(
                LLMMessage(
                    role="assistant",
                    content=response.content or "",
                    tool_calls=response.tool_calls,
                )
            )
        elif response.content:
            # Add assistant message with content
            self.conversation_history.append(
                LLMMessage(
                    role="assistant",
                    content=response.content,
                )
            )

    async def _continue_conversation(
        self,
        tool_calls: List[ToolCall],
        results: List[ToolResult],
    ) -> LLMResponse:
        """Continue the conversation with tool results."""

        # Add assistant message with tool calls to history
        self.conversation_history.append(
            LLMMessage(
                role="assistant",
                content="",  # Empty content for tool calls message
                tool_calls=tool_calls,
            )
        )

        # Add tool results to history
        for tool_call, result in zip(tool_calls, results):
            self.conversation_history.append(
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

        response = await self.llm_client.chat(
            messages=self.conversation_history,
            tools=get_tool_definitions(),
        )

        return response

    async def run(
        self,
        user_message: str,
        max_steps: int = 10,
        completion_check: Optional[Callable[[LLMResponse], bool]] = None,
        on_step: Optional[Callable[[int, LLMResponse], None]] = None,
    ) -> LLMResponse:
        """
        Run full task loop until completion or max steps reached.

        Args:
            user_message: The initial user message
            max_steps: Maximum number of steps to execute
            completion_check: Optional function to check if task is complete
            on_step: Optional callback called after each step.
                       Receives (step_number, response).

        Returns:
            LLMResponse: The final response from the LLM
        """
        # Add initial user message to history
        self.conversation_history.append(LLMMessage(role="user", content=user_message))

        response: Optional[LLMResponse] = None

        for step in range(max_steps):
            if self.llm_client is None:
                raise ValueError("LLM client is required for autonomous execution")

            # Get response from LLM using conversation history
            response = await self.llm_client.chat(
                messages=self.conversation_history,
                tools=get_tool_definitions(),
            )

            # Execute tools if requested
            if response and response.tool_calls:
                results = await self.execute_tools(response.tool_calls)

                # Add assistant message with tool calls to history
                self.conversation_history.append(
                    LLMMessage(
                        role="assistant",
                        content=response.content or "",
                        tool_calls=response.tool_calls,
                    )
                )

                # Add tool results to history
                for tool_call, result in zip(response.tool_calls, results):
                    self.conversation_history.append(
                        LLMMessage(
                            role="tool",
                            content=result.output or result.error or "No output",
                            tool_call_id=tool_call.call_id,
                            name=tool_call.name.value,
                        )
                    )
            elif response and response.content:
                # Add final assistant response to history
                self.conversation_history.append(
                    LLMMessage(
                        role="assistant",
                        content=response.content,
                    )
                )

            # Call step callback if provided
            if on_step and response:
                on_step(step + 1, response)

            # Check if task is complete
            if completion_check and response and completion_check(response):
                break

            # Check if no more tool calls
            if response and not response.tool_calls:
                break

        # Ensure we always return a valid response
        if response is None:
            response = LLMResponse(
                content="No response generated", finish_reason="stop"
            )

        return response

    def get_tools(self) -> List[dict]:
        """Get tool definitions for the LLM."""
        return get_tool_definitions()

    async def close(self) -> None:
        """Close the orchestrator and clean up resources."""
        if self.state_manager.sandbox:
            await self.state_manager.sandbox.kill()
            await self.state_manager.sandbox.close()
