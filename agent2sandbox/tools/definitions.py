"""
Tool definitions for Agent2Sandbox.
Defines the tools available to the Agent in OpenAI format.
"""

from typing import List, Dict, Any


# Tool definitions in OpenAI function calling format
TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "execute_command",
            "description": "Execute a shell command in the sandbox. Useful for running system commands, checking system status, or executing scripts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute. For example: 'ls -la', 'cat file.txt', 'python script.py'",
                    }
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file in the sandbox.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The file path to read. For example: '/tmp/test.txt', './script.py'",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file in the sandbox. Creates the file if it doesn't exist, overwrites if it does.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The file path to write. For example: '/tmp/test.txt', './script.py'",
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file.",
                    }
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files in a directory in the sandbox. Useful for exploring the filesystem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The directory path to list. Defaults to current directory or root.",
                        "default": ".",
                    },
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to filter files. For example: '*.py', 'test_*.txt'. Defaults to '*'.",
                        "default": "*",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_code",
            "description": "Execute code in the code interpreter. Supports Python, Java, JavaScript, Go, Bash, and TypeScript. The code is executed in an isolated environment with Jupyter kernel support.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "The code to execute. Can be multi-line code.",
                    },
                    "language": {
                        "type": "string",
                        "enum": ["python", "java", "javascript", "go", "bash", "typescript"],
                        "description": "The programming language of the code. Defaults to python.",
                        "default": "python",
                    }
                },
                "required": ["code"],
            },
        },
    },
]


def get_tool_definitions() -> List[Dict[str, Any]]:
    """Get all tool definitions."""
    return TOOLS


def get_tool_schema(tool_name: str) -> Dict[str, Any]:
    """Get the schema for a specific tool."""
    for tool in TOOLS:
        if tool["function"]["name"] == tool_name:
            return tool
    raise ValueError(f"Unknown tool: {tool_name}")


def get_available_tool_names() -> List[str]:
    """Get a list of available tool names."""
    return [tool["function"]["name"] for tool in TOOLS]
