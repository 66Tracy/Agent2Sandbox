"""
Result Converter - Formats sandbox results for Agent consumption.
"""

from agent2sandbox.core.types import ToolResult, ToolStatus


class ResultConverter:
    """Converts sandbox results to Agent-consumable format."""

    @staticmethod
    def to_message(result: ToolResult) -> str:
        """Convert a ToolResult to a message string for the Agent."""
        if result.status == ToolStatus.SUCCESS:
            message = f"Tool executed successfully."
            if result.output:
                message += f"\n\nOutput:\n{result.output}"
            if result.data:
                message += f"\n\nResult: {result.data}"
            return message
        else:
            return f"Tool execution failed: {result.error}"

    @staticmethod
    def to_tool_response(result: ToolResult) -> dict:
        """Convert a ToolResult to OpenAI tool response format."""
        content = result.output or result.error or "No output"

        return {
            "tool_call_id": result.call_id,
            "role": "tool",
            "content": content,
        }
