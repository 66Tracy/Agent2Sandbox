"""
Tool Adapter - Converts tool calls to sandbox operations.
"""

from typing import Optional
from opensandbox import Sandbox
from code_interpreter import CodeInterpreter, SupportedLanguage

from agent2sandbox.core.types import (
    ToolCall,
    ToolResult,
    ToolName,
    ToolStatus,
)


class ToolAdapter:
    """Adapts tool calls to sandbox operations."""

    def __init__(self, sandbox: Sandbox, code_interpreter: Optional[CodeInterpreter] = None):
        self.sandbox = sandbox
        self.code_interpreter = code_interpreter

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        """Execute a tool call against the sandbox."""
        try:
            if tool_call.name == ToolName.EXECUTE_COMMAND:
                return await self._execute_command(tool_call)
            elif tool_call.name == ToolName.READ_FILE:
                return await self._read_file(tool_call)
            elif tool_call.name == ToolName.WRITE_FILE:
                return await self._write_file(tool_call)
            elif tool_call.name == ToolName.LIST_FILES:
                return await self._list_files(tool_call)
            elif tool_call.name == ToolName.RUN_CODE:
                return await self._run_code(tool_call)
            else:
                return ToolResult(
                    status=ToolStatus.ERROR,
                    error=f"Unknown tool: {tool_call.name}",
                    call_id=tool_call.call_id,
                )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=f"Execution error: {str(e)}",
                call_id=tool_call.call_id,
            )

    async def _execute_command(self, tool_call: ToolCall) -> ToolResult:
        """Execute a shell command in the sandbox."""
        command = tool_call.arguments.get("command", "")
        if not command:
            return ToolResult(
                status=ToolStatus.ERROR,
                error="Command is required",
                call_id=tool_call.call_id,
            )

        result = await self.sandbox.commands.run(command)

        # Extract stdout and stderr
        stdout = "\n".join([msg.text for msg in result.logs.stdout]) if result.logs.stdout else ""
        stderr = "\n".join([msg.text for msg in result.logs.stderr]) if result.logs.stderr else ""

        output = stdout
        if stderr:
            output += "\n" + stderr

        return ToolResult(
            status=ToolStatus.SUCCESS if result.exit_code == 0 else ToolStatus.ERROR,
            output=output,
            error=stderr if result.exit_code != 0 else None,
            call_id=tool_call.call_id,
        )

    async def _read_file(self, tool_call: ToolCall) -> ToolResult:
        """Read a file from the sandbox."""
        path = tool_call.arguments.get("path", "")
        if not path:
            return ToolResult(
                status=ToolStatus.ERROR,
                error="Path is required",
                call_id=tool_call.call_id,
            )

        try:
            content = await self.sandbox.files.read_file(path)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=content,
                call_id=tool_call.call_id,
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=f"Failed to read file: {str(e)}",
                call_id=tool_call.call_id,
            )

    async def _write_file(self, tool_call: ToolCall) -> ToolResult:
        """Write content to a file in the sandbox."""
        path = tool_call.arguments.get("path", "")
        content = tool_call.arguments.get("content", "")

        if not path:
            return ToolResult(
                status=ToolStatus.ERROR,
                error="Path is required",
                call_id=tool_call.call_id,
            )

        try:
            await self.sandbox.files.write_file(path, content)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                output=f"Successfully wrote to {path}",
                call_id=tool_call.call_id,
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=f"Failed to write file: {str(e)}",
                call_id=tool_call.call_id,
            )

    async def _list_files(self, tool_call: ToolCall) -> ToolResult:
        """List files in a directory in the sandbox."""
        path = tool_call.arguments.get("path", "/")
        pattern = tool_call.arguments.get("pattern", "*")

        try:
            files = await self.sandbox.files.search_files(path, pattern=pattern)
            return ToolResult(
                status=ToolStatus.SUCCESS,
                data=[f.path for f in files],
                call_id=tool_call.call_id,
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=f"Failed to list files: {str(e)}",
                call_id=tool_call.call_id,
            )

    async def _run_code(self, tool_call: ToolCall) -> ToolResult:
        """Run code in the code interpreter."""
        if self.code_interpreter is None:
            return ToolResult(
                status=ToolStatus.ERROR,
                error="Code interpreter not initialized",
                call_id=tool_call.call_id,
            )

        code = tool_call.arguments.get("code", "")
        language = tool_call.arguments.get("language", "python")

        if not code:
            return ToolResult(
                status=ToolStatus.ERROR,
                error="Code is required",
                call_id=tool_call.call_id,
            )

        try:
            # Map language string to SupportedLanguage enum
            lang_map = {
                "python": SupportedLanguage.PYTHON,
                "java": SupportedLanguage.JAVA,
                "javascript": SupportedLanguage.JAVASCRIPT,
                "go": SupportedLanguage.GO,
                "bash": SupportedLanguage.BASH,
                "typescript": SupportedLanguage.TYPESCRIPT,
            }

            supported_lang = lang_map.get(language.lower(), SupportedLanguage.PYTHON)

            result = await self.code_interpreter.codes.run(code, language=supported_lang)

            # Extract output
            stdout = "\n".join([msg.text for msg in result.logs.stdout]) if result.logs.stdout else ""
            stderr = "\n".join([msg.text for msg in result.logs.stderr]) if result.logs.stderr else ""

            # Extract result (last expression value)
            result_text = None
            if result.result:
                result_text = "\n".join([msg.text for msg in result.result])

            output = stdout
            if result_text:
                output += "\n" + result_text

            return ToolResult(
                status=ToolStatus.SUCCESS,
                output=output,
                data={"result": result_text, "stdout": stdout},
                call_id=tool_call.call_id,
            )
        except Exception as e:
            return ToolResult(
                status=ToolStatus.ERROR,
                error=f"Code execution error: {str(e)}",
                call_id=tool_call.call_id,
            )
