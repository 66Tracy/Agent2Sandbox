"""
State Manager - Manages the state of the Agent and sandbox.
"""

import uuid
from typing import Optional, List

from agent2sandbox.core.types import (
    SandboxConfig,
    AgentState,
    ToolCall,
    ToolResult,
)


class StateManager:
    """Manages the state of the Agent and sandbox."""

    def __init__(self, config: SandboxConfig):
        self.config = config
        self.state = AgentState()
        self._sandbox = None
        self._code_interpreter = None

    @property
    def sandbox(self):
        """Get the sandbox instance."""
        return self._sandbox

    @sandbox.setter
    def sandbox(self, value):
        """Set the sandbox instance."""
        self._sandbox = value
        if value:
            self.state.sandbox_id = getattr(value, "id", str(uuid.uuid4()))

    @property
    def code_interpreter(self):
        """Get the code interpreter instance."""
        return self._code_interpreter

    @code_interpreter.setter
    def code_interpreter(self, value):
        """Set the code interpreter instance."""
        self._code_interpreter = value

    def mark_initialized(self):
        """Mark the agent as initialized."""
        self.state.is_initialized = True

    def record_tool_call(self, tool_call: ToolCall):
        """Record a tool call in the history."""
        if tool_call.call_id is None:
            tool_call.call_id = str(uuid.uuid4())
        self.state.tool_call_history.append(tool_call)

    def record_result(self, result: ToolResult):
        """Record a tool result in the history."""
        self.state.result_history.append(result)

    def increment_step(self):
        """Increment the current step counter."""
        self.state.current_step += 1

    def get_history(self) -> tuple[List[ToolCall], List[ToolResult]]:
        """Get the tool call and result history."""
        return self.state.tool_call_history, self.state.result_history

    def get_last_result(self) -> Optional[ToolResult]:
        """Get the most recent tool result."""
        if self.state.result_history:
            return self.state.result_history[-1]
        return None

    def is_initialized(self) -> bool:
        """Check if the agent is initialized."""
        return self.state.is_initialized

    def get_step_count(self) -> int:
        """Get the current step count."""
        return self.state.current_step

    def reset_step_count(self):
        """Reset the step count to zero."""
        self.state.current_step = 0
