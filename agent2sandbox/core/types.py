"""
Core data type definitions for Agent2Sandbox.
"""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Dict, List, Optional
from enum import Enum


class ToolName(str, Enum):
    """Enumeration of available tools."""

    EXECUTE_COMMAND = "execute_command"
    READ_FILE = "read_file"
    WRITE_FILE = "write_file"
    LIST_FILES = "list_files"
    RUN_CODE = "run_code"


class ToolStatus(str, Enum):
    """Status of a tool execution."""

    SUCCESS = "success"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class ToolCall:
    """A tool call request from the Agent."""

    name: ToolName
    arguments: Dict[str, Any]
    call_id: Optional[str] = None


@dataclass
class ToolResult:
    """Result of a tool execution."""

    status: ToolStatus
    output: Optional[str] = None
    error: Optional[str] = None
    data: Optional[Any] = None
    call_id: Optional[str] = None


@dataclass
class SandboxConfig:
    """Configuration for sandbox creation."""

    image: str = "sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.1"
    entrypoint: Optional[List[str]] = None
    env: Optional[Dict[str, str]] = None
    timeout: timedelta = timedelta(minutes=10)
    cpu_limit: Optional[float] = None
    memory_limit: Optional[int] = None
    domain: Optional[str] = None
    api_key: Optional[str] = None


@dataclass
class AgentState:
    """State of the Agent during execution."""

    sandbox_id: Optional[str] = None
    is_initialized: bool = False
    tool_call_history: List[ToolCall] = field(default_factory=list)
    result_history: List[ToolResult] = field(default_factory=list)
    current_step: int = 0


@dataclass
class LLMMessage:
    """A message in the conversation with the LLM."""

    role: str  # "system", "user", "assistant", "tool"
    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    tool_call_id: Optional[str] = None
    name: Optional[str] = None


@dataclass
class LLMResponse:
    """Response from the LLM."""

    content: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None
    finish_reason: Optional[str] = None
