"""
LLM Client - Interface for interacting with LLM providers.
"""

from abc import ABC, abstractmethod
from typing import List, Optional, Any
from openai import AsyncOpenAI

from agent2sandbox.core.types import LLMMessage, LLMResponse, ToolCall, ToolName


class LLMClient(ABC):
    """Abstract base class for LLM clients."""

    @abstractmethod
    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[dict]] = None,
    ) -> LLMResponse:
        """Send a chat request to the LLM."""
        pass


class OpenAIClient(LLMClient):
    """OpenAI API client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        **kwargs,
    ):
        """Initialize the OpenAI client.

        Args:
            api_key: OpenAI API key. If None, will use OPENAI_API_KEY env var.
            base_url: Custom base URL for API requests.
            model: Model to use for chat requests.
            temperature: Temperature for sampling.
            **kwargs: Additional arguments to pass to AsyncOpenAI.
        """
        self.model = model
        self.temperature = temperature
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            **kwargs,
        )

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[dict]] = None,
    ) -> LLMResponse:
        """Send a chat request to the LLM."""
        # Convert our message format to OpenAI format
        openai_messages = []

        for msg in messages:
            openai_msg: dict[str, Any] = {"role": msg.role}

            if msg.content:
                openai_msg["content"] = msg.content

            if msg.tool_calls:
                openai_msg["tool_calls"] = [
                    {
                        "id": tc.call_id or "",
                        "type": "function",
                        "function": {
                            "name": tc.name.value,
                            "arguments": str(tc.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]

            if msg.tool_call_id:
                openai_msg["tool_call_id"] = msg.tool_call_id

            if msg.name:
                openai_msg["name"] = msg.name

            openai_messages.append(openai_msg)

        # Build request kwargs
        kwargs: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": openai_messages,
        }

        if tools:
            kwargs["tools"] = tools

        # Call the API
        response = await self.client.chat.completions.create(**kwargs)

        # Parse the response
        choice = response.choices[0]
        message = choice.message

        tool_calls = None
        if message.tool_calls:
            tool_calls = [
                ToolCall(
                    name=ToolName(tc.function.name),
                    arguments=eval(tc.function.arguments),
                    call_id=tc.id,
                )
                for tc in message.tool_calls
            ]

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
        )


class MockLLMClient(LLMClient):
    """Mock LLM client for testing without an actual LLM.

    This client returns predefined responses or echoes tool calls.
    """

    def __init__(self, responses: Optional[List[LLMResponse]] = None):
        """Initialize the mock client.

        Args:
            responses: Optional list of predefined responses. If provided, will return
                       these responses in order. If exhausted, will echo tool calls.
        """
        self.responses = responses or []
        self.response_index = 0

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[dict]] = None,
    ) -> LLMResponse:
        """Return a predefined response or echo tool calls."""
        # Check if we have a predefined response
        if self.response_index < len(self.responses):
            response = self.responses[self.response_index]
            self.response_index += 1
            return response

        # Default: echo the last user message or tool results
        last_message = messages[-1] if messages else None

        if last_message and last_message.role == "tool":
            # Echo tool result
            return LLMResponse(
                content=f"Tool output: {last_message.content}",
                tool_calls=None,
                finish_reason="stop",
            )
        elif last_message and last_message.role == "user":
            # No tool calls, just echo
            return LLMResponse(
                content=f"Received: {last_message.content}",
                tool_calls=None,
                finish_reason="stop",
            )
        else:
            return LLMResponse(
                content="I'm ready to help you interact with the sandbox.",
                tool_calls=None,
                finish_reason="stop",
            )
