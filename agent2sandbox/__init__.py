"""
Agent2Sandbox - A lightweight framework for Agent and OpenSandbox interaction.

Core concepts:
- Environment as Tools: Sandbox operations are exposed as tools to the Agent
- Agent Orchestrator: Coordinates interaction between Agent, tools, and sandbox
- Tool Adapter: Converts tool calls to sandbox operations
- Result Converter: Formats sandbox results for Agent consumption
"""

from agent2sandbox.core.orchestrator import AgentOrchestrator
from agent2sandbox.core.state_manager import StateManager
from agent2sandbox.tools.definitions import get_tool_definitions
from agent2sandbox.llm.client import LLMClient, OpenAIClient, MockLLMClient
from agent2sandbox.core.types import (
    ToolCall,
    ToolResult,
    SandboxConfig,
    AgentState,
    ToolName,
    ToolStatus,
    LLMMessage,
    LLMResponse,
)

__all__ = [
    "AgentOrchestrator",
    "StateManager",
    "get_tool_definitions",
    "LLMClient",
    "OpenAIClient",
    "MockLLMClient",
    "ToolCall",
    "ToolResult",
    "SandboxConfig",
    "AgentState",
    "ToolName",
    "ToolStatus",
    "LLMMessage",
    "LLMResponse",
]
