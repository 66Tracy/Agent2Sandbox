"""Simple local LLM proxy with model routing and trajectory logging."""

from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent2sandbox.settings import (
    LLMProxyRoute,
    LLMProxyRoutingConfig,
    ProxyConfig,
    load_llmproxy_routing_config,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_file_token(token: str) -> str:
    return "".join(ch for ch in token if ch.isalnum() or ch in {"-", "_"})[:64] or "anonymous"


def _extract_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
    return ""


def _normalize_anthropic_content_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    if isinstance(content, list):
        return [item for item in content if isinstance(item, dict)]
    if isinstance(content, dict):
        return [content]
    return []


def _safe_json_loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return None


def _serialize_block_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    text = _extract_text_content(content)
    if text:
        return text
    try:
        return json.dumps(content, ensure_ascii=False)
    except Exception:
        return str(content)


def _anthropic_tool_choice_to_openai(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"auto", "none"}:
            return lowered
        if lowered == "any":
            return "required"
        return None
    if isinstance(value, dict):
        choice_type = str(value.get("type", "")).strip().lower()
        if choice_type in {"auto", "none"}:
            return choice_type
        if choice_type == "any":
            return "required"
        if choice_type == "tool":
            name = str(value.get("name", "")).strip()
            if name:
                return {"type": "function", "function": {"name": name}}
    return None


def _openai_tool_choice_to_anthropic(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"auto", "none"}:
            return {"type": lowered}
        if lowered in {"required", "any"}:
            return {"type": "any"}
        return None
    if isinstance(value, dict):
        choice_type = str(value.get("type", "")).strip().lower()
        if choice_type == "function":
            function = value.get("function")
            if isinstance(function, dict):
                name = str(function.get("name", "")).strip()
                if name:
                    return {"type": "tool", "name": name}
    return None


def _anthropic_tools_to_openai(raw_tools: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_tools, list):
        return []
    tools: list[dict[str, Any]] = []
    for item in raw_tools:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        schema = item.get("input_schema")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        function: dict[str, Any] = {
            "name": name,
            "parameters": schema,
        }
        description = item.get("description")
        if isinstance(description, str) and description.strip():
            function["description"] = description
        tools.append({"type": "function", "function": function})
    return tools


def _openai_tools_to_anthropic(raw_tools: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_tools, list):
        return []
    tools: list[dict[str, Any]] = []
    for item in raw_tools:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "function":
            continue
        function = item.get("function")
        if not isinstance(function, dict):
            continue
        name = str(function.get("name", "")).strip()
        if not name:
            continue
        schema = function.get("parameters")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        tool: dict[str, Any] = {
            "name": name,
            "input_schema": schema,
        }
        description = function.get("description")
        if isinstance(description, str) and description.strip():
            tool["description"] = description
        tools.append(tool)
    return tools


def _anthropic_messages_to_openai(body: dict[str, Any]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    system = body.get("system")
    if system:
        system_text = _extract_text_content(system)
        if system_text:
            messages.append({"role": "system", "content": system_text})

    raw_messages = body.get("messages", [])
    if not isinstance(raw_messages, list):
        return messages

    for item in raw_messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip()
        if role not in {"user", "assistant", "system"}:
            continue

        blocks = _normalize_anthropic_content_blocks(item.get("content"))
        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in blocks:
                block_type = str(block.get("type", "")).strip()
                if block_type == "text":
                    text = block.get("text")
                    if isinstance(text, str):
                        text_parts.append(text)
                    continue
                if block_type != "tool_use":
                    continue
                tool_name = str(block.get("name", "")).strip()
                if not tool_name:
                    continue
                call_id = str(block.get("id", "")).strip() or f"call_{uuid4().hex[:12]}"
                raw_input = block.get("input", {})
                if not isinstance(raw_input, (dict, list)):
                    raw_input = {"value": raw_input}
                tool_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(raw_input, ensure_ascii=False),
                        },
                    }
                )

            assistant_message: dict[str, Any] = {"role": "assistant"}
            assistant_message["content"] = "\n".join(text_parts) if text_parts else ""
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
            if assistant_message["content"] or tool_calls:
                messages.append(assistant_message)
            continue

        if role == "user":
            pending_text: list[str] = []

            def _flush_pending_user_text() -> None:
                if pending_text:
                    messages.append({"role": "user", "content": "\n".join(pending_text)})
                    pending_text.clear()

            for block in blocks:
                block_type = str(block.get("type", "")).strip()
                if block_type == "text":
                    text = block.get("text")
                    if isinstance(text, str):
                        pending_text.append(text)
                    continue
                if block_type != "tool_result":
                    continue

                _flush_pending_user_text()
                call_id = str(block.get("tool_use_id", "")).strip()
                tool_text = _serialize_block_content(block.get("content"))
                if block.get("is_error") is True:
                    tool_text = f"[tool_error]\n{tool_text}"

                if call_id:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call_id,
                            "content": tool_text,
                        }
                    )
                else:
                    pending_text.append(tool_text)

            _flush_pending_user_text()
            continue

        # role == "system"
        content = _extract_text_content(item.get("content"))
        if content:
            messages.append({"role": "system", "content": content})

    return messages


def _openai_messages_to_anthropic(
    raw_messages: Any,
) -> tuple[list[dict[str, Any]], str | list[dict[str, Any]] | None]:
    if not isinstance(raw_messages, list):
        return [], None

    system_parts: list[str] = []
    anthropic_messages: list[dict[str, Any]] = []
    for item in raw_messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).strip()
        if role == "system":
            system_text = _serialize_block_content(item.get("content"))
            if system_text:
                system_parts.append(system_text)
            continue

        if role == "tool":
            tool_call_id = str(item.get("tool_call_id", "")).strip()
            if not tool_call_id:
                continue
            tool_text = _serialize_block_content(item.get("content"))
            anthropic_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_call_id,
                            "content": tool_text,
                        }
                    ],
                }
            )
            continue

        if role == "assistant":
            content_blocks: list[dict[str, Any]] = []
            assistant_text = _serialize_block_content(item.get("content"))
            if assistant_text:
                content_blocks.append({"type": "text", "text": assistant_text})
            tool_calls = item.get("tool_calls")
            if isinstance(tool_calls, list):
                for call in tool_calls:
                    if not isinstance(call, dict):
                        continue
                    function = call.get("function")
                    if not isinstance(function, dict):
                        continue
                    name = str(function.get("name", "")).strip()
                    if not name:
                        continue
                    call_id = str(call.get("id", "")).strip() or f"toolu_{uuid4().hex[:12]}"
                    raw_args = function.get("arguments", "{}")
                    if isinstance(raw_args, str):
                        parsed_args = _safe_json_loads(raw_args)
                    else:
                        parsed_args = raw_args
                    if not isinstance(parsed_args, (dict, list)):
                        parsed_args = {"value": parsed_args if parsed_args is not None else raw_args}
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": call_id,
                            "name": name,
                            "input": parsed_args,
                        }
                    )
            if content_blocks:
                anthropic_messages.append({"role": "assistant", "content": content_blocks})
            continue

        if role == "user":
            user_text = _serialize_block_content(item.get("content"))
            if user_text:
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": user_text}],
                    }
                )

    if not system_parts:
        return anthropic_messages, None
    if len(system_parts) == 1:
        return anthropic_messages, system_parts[0]
    return anthropic_messages, [{"type": "text", "text": "\n".join(system_parts)}]


def _join_url(base_url: str, suffix: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith(suffix):
        return base
    return f"{base}{suffix}"


@dataclass
class ProxySession:
    token: str
    sandbox_id: str | None
    task_name: str | None
    created_at: str
    updated_at: str


@dataclass
class UpstreamHTTPResult:
    status_code: int
    content_type: str
    body: bytes


@dataclass
class ProxyResponse:
    status_code: int
    payload: dict[str, Any] | str
    mode: str = "json"  # json | sse_synth | sse_raw


class TrajectoryStore:
    """Per-session QA trajectory writer."""

    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._suffix_counter: dict[tuple[str, str], int] = {}

    def _session_dir(self, token: str) -> Path:
        session_dir = self.log_dir / _safe_file_token(token)
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def _alloc_stamp(self, token: str) -> str:
        base = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M-%S")
        key = (_safe_file_token(token), base)
        count = self._suffix_counter.get(key, 0)
        self._suffix_counter[key] = count + 1
        if count == 0:
            return base
        return f"{base}-{count:03d}"

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def append(self, token: str, event_type: str, payload: dict[str, Any]) -> Path:
        session_dir = self._session_dir(token)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M-%S-%f")
        event_name = _safe_file_token(event_type)
        path = session_dir / "events" / f"{stamp}-{event_name}.json"
        record = {"timestamp": _utc_now(), "event_type": event_type, "payload": payload}
        with self._lock:
            self._write_json(path, record)
        return path

    def write_query(self, token: str, payload: dict[str, Any]) -> str:
        with self._lock:
            stamp = self._alloc_stamp(token)
            path = self._session_dir(token) / "query" / f"{stamp}.json"
            record = {
                "timestamp": stamp,
                "captured_at": _utc_now(),
                "payload": payload,
            }
            self._write_json(path, record)
        return stamp

    def write_answer(self, token: str, stamp: str, payload: dict[str, Any]) -> Path:
        with self._lock:
            path = self._session_dir(token) / "answer" / f"{stamp}.json"
            record = {
                "timestamp": stamp,
                "captured_at": _utc_now(),
                "payload": payload,
            }
            self._write_json(path, record)
        return path

    def path_for(self, token: str) -> Path:
        return self._session_dir(token)


class ProxyRuntime:
    """In-memory runtime state shared by all HTTP handlers."""

    def __init__(self, routing: LLMProxyRoutingConfig, proxy: ProxyConfig):
        self.routing = routing
        self.proxy = proxy
        self.store = TrajectoryStore(proxy.log_dir)
        self._sessions: dict[str, ProxySession] = {}
        self._lock = threading.Lock()
        self._reasoning_by_token: dict[str, dict[str, str]] = {}

    def register_session(
        self,
        token: str,
        sandbox_id: str | None,
        task_name: str | None,
    ) -> ProxySession:
        now = _utc_now()
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                session = ProxySession(
                    token=token,
                    sandbox_id=sandbox_id,
                    task_name=task_name,
                    created_at=now,
                    updated_at=now,
                )
                self._sessions[token] = session
            else:
                session.sandbox_id = sandbox_id or session.sandbox_id
                session.task_name = task_name or session.task_name
                session.updated_at = now
        self.store.append(
            token=token,
            event_type="session_registered",
            payload={
                "sandbox_id": sandbox_id,
                "task_name": task_name,
            },
        )
        return session

    def record_event(self, token: str, event_type: str, payload: dict[str, Any]) -> None:
        now = _utc_now()
        with self._lock:
            session = self._sessions.get(token)
            if session:
                session.updated_at = now
        self.store.append(token=token, event_type=event_type, payload=payload)

    def sessions_snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "token": session.token,
                    "sandbox_id": session.sandbox_id,
                    "task_name": session.task_name,
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                }
                for session in self._sessions.values()
            ]

    def trajectory_path(self, token: str) -> Path:
        return self.store.path_for(token)

    def _remember_reasoning_for_tool_calls(
        self,
        token: str,
        openai_response: dict[str, Any],
    ) -> None:
        choices = openai_response.get("choices")
        if not isinstance(choices, list) or not choices:
            return
        first = choices[0]
        if not isinstance(first, dict):
            return
        message = first.get("message")
        if not isinstance(message, dict):
            return
        reasoning_content = message.get("reasoning_content")
        if not isinstance(reasoning_content, str) or not reasoning_content.strip():
            return
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            return

        call_ids: list[str] = []
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            call_id = str(call.get("id", "")).strip()
            if call_id:
                call_ids.append(call_id)
        if not call_ids:
            return

        with self._lock:
            token_cache = self._reasoning_by_token.setdefault(token, {})
            token_cache["__last__"] = reasoning_content
            for call_id in call_ids:
                token_cache[call_id] = reasoning_content
            if len(token_cache) > 1024:
                for key in list(token_cache.keys())[:256]:
                    if key != "__last__":
                        token_cache.pop(key, None)

    def _inject_reasoning_content(
        self,
        token: str,
        messages: list[dict[str, Any]],
    ) -> None:
        with self._lock:
            token_cache = dict(self._reasoning_by_token.get(token, {}))
        if not token_cache:
            return

        for message in messages:
            if not isinstance(message, dict):
                continue
            if str(message.get("role", "")).strip() != "assistant":
                continue
            if "reasoning_content" in message:
                continue

            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list) or not tool_calls:
                continue

            reasoning_value: str | None = None
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                call_id = str(call.get("id", "")).strip()
                if call_id and call_id in token_cache:
                    reasoning_value = token_cache[call_id]
                    break
            if not reasoning_value:
                fallback = token_cache.get("__last__")
                if isinstance(fallback, str) and fallback.strip():
                    reasoning_value = fallback
            if reasoning_value:
                message["reasoning_content"] = reasoning_value

    def _masked_headers(self, headers: dict[str, str]) -> dict[str, str]:
        masked: dict[str, str] = {}
        for key, value in headers.items():
            lowered = key.lower()
            if lowered in {"authorization", "x-api-key", "api-key"}:
                masked[key] = "***"
            else:
                masked[key] = value
        return masked

    def _log_upstream_query(
        self,
        token: str,
        route: LLMProxyRoute,
        downstream_protocol: str,
        upstream_url: str,
        upstream_headers: dict[str, str],
        upstream_payload: dict[str, Any],
    ) -> str:
        return self.store.write_query(
            token=token,
            payload={
                "route_name": route.name,
                "downstream_protocol": downstream_protocol,
                "upstream_provider": route.upstream_provider,
                "upstream_url": upstream_url,
                "upstream_headers": self._masked_headers(upstream_headers),
                "request_body": upstream_payload,
            },
        )

    def _log_upstream_answer(
        self,
        token: str,
        stamp: str,
        route: LLMProxyRoute,
        downstream_protocol: str,
        upstream_result: UpstreamHTTPResult,
        upstream_json: dict[str, Any] | None = None,
        downstream_payload: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "route_name": route.name,
            "downstream_protocol": downstream_protocol,
            "upstream_provider": route.upstream_provider,
            "status_code": upstream_result.status_code,
            "content_type": upstream_result.content_type,
        }
        if upstream_json is not None:
            payload["upstream_response_body"] = upstream_json
        else:
            payload["upstream_response_text"] = upstream_result.body.decode(
                "utf-8", errors="replace"
            )
        if downstream_payload is not None:
            payload["downstream_response_body"] = downstream_payload
        self.store.write_answer(token=token, stamp=stamp, payload=payload)

    def _parse_json_body(self, result: UpstreamHTTPResult) -> dict[str, Any] | None:
        try:
            parsed = json.loads(result.body.decode("utf-8"))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    def _post_json(
        self,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> UpstreamHTTPResult:
        body = json.dumps(payload).encode("utf-8")
        merged_headers = {"Content-Type": "application/json"}
        merged_headers.update(headers)

        request = urllib.request.Request(
            url=url,
            data=body,
            method="POST",
            headers=merged_headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                content_type = response.headers.get("Content-Type", "application/json")
                return UpstreamHTTPResult(
                    status_code=response.getcode(),
                    content_type=content_type,
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            content_type = exc.headers.get("Content-Type", "application/json")
            return UpstreamHTTPResult(
                status_code=exc.code,
                content_type=content_type,
                body=exc.read(),
            )
        except urllib.error.URLError as exc:
            payload = {
                "type": "error",
                "error": {
                    "type": "network_error",
                    "message": str(exc),
                },
            }
            return UpstreamHTTPResult(
                status_code=502,
                content_type="application/json",
                body=json.dumps(payload, ensure_ascii=True).encode("utf-8"),
            )

    def _anthropic_response_from_openai(
        self,
        openai_response: dict[str, Any],
        requested_model: str | None,
    ) -> dict[str, Any]:
        choices = openai_response.get("choices", [])
        content_blocks: list[dict[str, Any]] = []
        stop_reason = "end_turn"
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message", {})
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    if content:
                        content_blocks.append({"type": "text", "text": content})
                elif isinstance(content, list):
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text = item.get("text")
                            if isinstance(text, str) and text:
                                content_blocks.append({"type": "text", "text": text})

                tool_calls = message.get("tool_calls")
                if isinstance(tool_calls, list):
                    for call in tool_calls:
                        if not isinstance(call, dict):
                            continue
                        function = call.get("function")
                        if not isinstance(function, dict):
                            continue
                        name = str(function.get("name", "")).strip()
                        if not name:
                            continue
                        call_id = str(call.get("id", "")).strip() or f"toolu_{uuid4().hex[:12]}"
                        raw_arguments = function.get("arguments", "{}")
                        if isinstance(raw_arguments, str):
                            parsed_arguments = _safe_json_loads(raw_arguments)
                        else:
                            parsed_arguments = raw_arguments
                        if not isinstance(parsed_arguments, (dict, list)):
                            parsed_arguments = {
                                "value": parsed_arguments
                                if parsed_arguments is not None
                                else raw_arguments
                            }
                        content_blocks.append(
                            {
                                "type": "tool_use",
                                "id": call_id,
                                "name": name,
                                "input": parsed_arguments,
                            }
                        )

            finish_reason = choices[0].get("finish_reason")
            if finish_reason == "length":
                stop_reason = "max_tokens"
            elif finish_reason == "tool_calls":
                stop_reason = "tool_use"

        usage = openai_response.get("usage", {})
        input_tokens = int(usage.get("prompt_tokens", 0)) if isinstance(usage, dict) else 0
        output_tokens = int(usage.get("completion_tokens", 0)) if isinstance(usage, dict) else 0

        return {
            "id": f"msg_{uuid4().hex}",
            "type": "message",
            "role": "assistant",
            "model": requested_model or "unknown-model",
            "content": content_blocks,
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        }

    def _openai_response_from_anthropic(
        self,
        anthropic_response: dict[str, Any],
        requested_model: str | None,
    ) -> dict[str, Any]:
        blocks = anthropic_response.get("content", [])
        if not isinstance(blocks, list):
            blocks = []

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type", "")).strip()
            if block_type == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    text_parts.append(text)
                continue
            if block_type != "tool_use":
                continue
            name = str(block.get("name", "")).strip()
            if not name:
                continue
            call_id = str(block.get("id", "")).strip() or f"call_{uuid4().hex[:12]}"
            raw_input = block.get("input", {})
            if not isinstance(raw_input, (dict, list)):
                raw_input = {"value": raw_input}
            tool_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(raw_input, ensure_ascii=False),
                    },
                }
            )

        stop_reason = anthropic_response.get("stop_reason")
        finish_reason = "stop"
        if stop_reason == "max_tokens":
            finish_reason = "length"
        elif stop_reason == "tool_use":
            finish_reason = "tool_calls"

        usage = anthropic_response.get("usage", {})
        prompt_tokens = int(usage.get("input_tokens", 0)) if isinstance(usage, dict) else 0
        completion_tokens = int(usage.get("output_tokens", 0)) if isinstance(usage, dict) else 0

        message: dict[str, Any] = {
            "role": "assistant",
            "content": "\n".join(text_parts) if text_parts else "",
        }
        if tool_calls:
            message["tool_calls"] = tool_calls

        return {
            "id": anthropic_response.get("id", f"chatcmpl-{uuid4().hex}"),
            "object": "chat.completion",
            "created": int(time.time()),
            "model": requested_model
            or str(anthropic_response.get("model", "")).strip()
            or "unknown-model",
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }

    def _error_response(self, status_code: int, error_type: str, message: str) -> ProxyResponse:
        return ProxyResponse(
            status_code=status_code,
            payload={
                "type": "error",
                "error": {
                    "type": error_type,
                    "message": message,
                },
            },
        )

    def _select_route(
        self,
        token: str,
        requested_model: str,
    ) -> LLMProxyRoute | None:
        try:
            route = self.routing.match(requested_model)
        except Exception as exc:
            self.record_event(
                token=token,
                event_type="route_not_found",
                payload={
                    "requested_model": requested_model,
                    "error": str(exc),
                },
            )
            return None
        self.record_event(
            token=token,
            event_type="route_selected",
            payload={
                "route_name": route.name,
                "request_model": requested_model,
                "upstream_provider": route.upstream_provider,
                "upstream_model": route.upstream_model,
            },
        )
        return route

    def _process_anthropic_passthrough(
        self,
        token: str,
        route: LLMProxyRoute,
        body: dict[str, Any],
    ) -> ProxyResponse:
        upstream_payload = dict(body)
        upstream_payload["model"] = route.upstream_model
        upstream_url = _join_url(route.upstream_base_url, "/v1/messages")
        upstream_headers = {
            "x-api-key": route.upstream_api_key,
            "anthropic-version": "2023-06-01",
        }
        qa_stamp = self._log_upstream_query(
            token=token,
            route=route,
            downstream_protocol="anthropic",
            upstream_url=upstream_url,
            upstream_headers=upstream_headers,
            upstream_payload=upstream_payload,
        )

        upstream_result = self._post_json(
            url=upstream_url,
            payload=upstream_payload,
            headers=upstream_headers,
            timeout_seconds=route.timeout_seconds,
        )

        stream_requested = body.get("stream") is True
        if upstream_result.status_code >= 400:
            decoded = upstream_result.body.decode("utf-8", errors="replace")
            self._log_upstream_answer(
                token=token,
                stamp=qa_stamp,
                route=route,
                downstream_protocol="anthropic",
                upstream_result=upstream_result,
            )
            self.record_event(
                token=token,
                event_type="upstream_error",
                payload={
                    "status_code": upstream_result.status_code,
                    "upstream_provider": route.upstream_provider,
                    "error": decoded[:1000],
                },
            )
            return self._error_response(
                status_code=upstream_result.status_code,
                error_type="upstream_error",
                message=decoded,
            )

        self.record_event(
            token=token,
            event_type="anthropic_passthrough",
            payload={
                "route_name": route.name,
                "stream": stream_requested,
                "status_code": upstream_result.status_code,
                "content_type": upstream_result.content_type,
            },
        )

        if stream_requested and "text/event-stream" in upstream_result.content_type.lower():
            self._log_upstream_answer(
                token=token,
                stamp=qa_stamp,
                route=route,
                downstream_protocol="anthropic",
                upstream_result=upstream_result,
            )
            return ProxyResponse(
                status_code=upstream_result.status_code,
                payload=upstream_result.body.decode("utf-8", errors="replace"),
                mode="sse_raw",
            )

        parsed = self._parse_json_body(upstream_result)
        if parsed is None:
            self._log_upstream_answer(
                token=token,
                stamp=qa_stamp,
                route=route,
                downstream_protocol="anthropic",
                upstream_result=upstream_result,
            )
            return self._error_response(
                status_code=502,
                error_type="invalid_upstream_response",
                message="Anthropic upstream returned non-JSON response",
            )
        self._log_upstream_answer(
            token=token,
            stamp=qa_stamp,
            route=route,
            downstream_protocol="anthropic",
            upstream_result=upstream_result,
            upstream_json=parsed,
            downstream_payload=parsed,
        )
        return ProxyResponse(status_code=upstream_result.status_code, payload=parsed, mode="json")

    def _process_anthropic_to_openai(
        self,
        token: str,
        route: LLMProxyRoute,
        body: dict[str, Any],
    ) -> ProxyResponse:
        requested_model = body.get("model")
        openai_payload: dict[str, Any] = {
            "model": route.upstream_model,
            "messages": _anthropic_messages_to_openai(body),
            "max_tokens": int(body.get("max_tokens", 1024)),
        }
        if "temperature" in body:
            openai_payload["temperature"] = body["temperature"]
        if "top_p" in body:
            openai_payload["top_p"] = body["top_p"]
        stop_sequences = body.get("stop_sequences")
        if stop_sequences:
            openai_payload["stop"] = stop_sequences
        tools = _anthropic_tools_to_openai(body.get("tools"))
        if tools:
            openai_payload["tools"] = tools
            tool_choice = _anthropic_tool_choice_to_openai(body.get("tool_choice"))
            if tool_choice is not None:
                openai_payload["tool_choice"] = tool_choice
        # DeepSeek reasoner requires reasoning_content in assistant/tool_call turns.
        self._inject_reasoning_content(token, openai_payload["messages"])

        upstream_url = _join_url(route.upstream_base_url, "/chat/completions")
        upstream_headers = {"Authorization": f"Bearer {route.upstream_api_key}"}
        qa_stamp = self._log_upstream_query(
            token=token,
            route=route,
            downstream_protocol="anthropic",
            upstream_url=upstream_url,
            upstream_headers=upstream_headers,
            upstream_payload=openai_payload,
        )

        upstream_result = self._post_json(
            url=upstream_url,
            payload=openai_payload,
            headers=upstream_headers,
            timeout_seconds=route.timeout_seconds,
        )
        upstream_json = self._parse_json_body(upstream_result)
        if upstream_json is None:
            self._log_upstream_answer(
                token=token,
                stamp=qa_stamp,
                route=route,
                downstream_protocol="anthropic",
                upstream_result=upstream_result,
            )
            decoded = upstream_result.body.decode("utf-8", errors="replace")
            return self._error_response(
                status_code=502,
                error_type="invalid_upstream_response",
                message=decoded,
            )

        if upstream_result.status_code >= 400:
            self.record_event(
                token=token,
                event_type="upstream_error",
                payload={
                    "status_code": upstream_result.status_code,
                    "upstream_provider": route.upstream_provider,
                    "error": upstream_json,
                },
            )
            self._log_upstream_answer(
                token=token,
                stamp=qa_stamp,
                route=route,
                downstream_protocol="anthropic",
                upstream_result=upstream_result,
                upstream_json=upstream_json,
            )
            return self._error_response(
                status_code=upstream_result.status_code,
                error_type="upstream_error",
                message=json.dumps(upstream_json, ensure_ascii=True),
            )

        anthropic_response = self._anthropic_response_from_openai(
            openai_response=upstream_json,
            requested_model=requested_model if isinstance(requested_model, str) else None,
        )
        self._remember_reasoning_for_tool_calls(token=token, openai_response=upstream_json)
        self.record_event(
            token=token,
            event_type="anthropic_converted_response",
            payload={
                "route_name": route.name,
                "status_code": upstream_result.status_code,
                "output_tokens": anthropic_response["usage"]["output_tokens"],
            },
        )
        self._log_upstream_answer(
            token=token,
            stamp=qa_stamp,
            route=route,
            downstream_protocol="anthropic",
            upstream_result=upstream_result,
            upstream_json=upstream_json,
            downstream_payload=anthropic_response,
        )
        if body.get("stream") is True:
            return ProxyResponse(
                status_code=200,
                payload=anthropic_response,
                mode="sse_synth",
            )
        return ProxyResponse(status_code=200, payload=anthropic_response, mode="json")

    def process_anthropic_messages(
        self,
        token: str,
        body: dict[str, Any],
    ) -> ProxyResponse:
        requested_model = str(body.get("model", "")).strip()
        if not requested_model:
            return self._error_response(
                status_code=400,
                error_type="bad_request",
                message="`model` is required in anthropic request body",
            )

        self.record_event(
            token=token,
            event_type="anthropic_request",
            payload={
                "requested_model": requested_model,
                "stream": body.get("stream") is True,
                "messages_count": len(body.get("messages", []))
                if isinstance(body.get("messages"), list)
                else 0,
            },
        )

        route = self._select_route(
            token=token,
            requested_model=requested_model,
        )
        if route is None:
            return self._error_response(
                status_code=404,
                error_type="route_not_found",
                message=f"No route for anthropic model: {requested_model}",
            )

        if route.upstream_provider == "anthropic":
            return self._process_anthropic_passthrough(token=token, route=route, body=body)
        return self._process_anthropic_to_openai(token=token, route=route, body=body)

    def process_openai_chat_completions(
        self,
        token: str,
        body: dict[str, Any],
    ) -> ProxyResponse:
        requested_model = str(body.get("model", "")).strip()
        if not requested_model:
            return self._error_response(
                status_code=400,
                error_type="bad_request",
                message="`model` is required in openai request body",
            )

        route = self._select_route(
            token=token,
            requested_model=requested_model,
        )
        if route is None:
            return self._error_response(
                status_code=404,
                error_type="route_not_found",
                message=f"No route for openai model: {requested_model}",
            )
        if route.upstream_provider == "openai":
            payload = dict(body)
            payload["model"] = route.upstream_model
            if isinstance(payload.get("messages"), list):
                self._inject_reasoning_content(token, payload["messages"])
            upstream_url = _join_url(route.upstream_base_url, "/chat/completions")
            upstream_headers = {"Authorization": f"Bearer {route.upstream_api_key}"}
            qa_stamp = self._log_upstream_query(
                token=token,
                route=route,
                downstream_protocol="openai",
                upstream_url=upstream_url,
                upstream_headers=upstream_headers,
                upstream_payload=payload,
            )
            upstream_result = self._post_json(
                url=upstream_url,
                payload=payload,
                headers=upstream_headers,
                timeout_seconds=route.timeout_seconds,
            )
            upstream_json = self._parse_json_body(upstream_result)
            if upstream_json is None:
                self._log_upstream_answer(
                    token=token,
                    stamp=qa_stamp,
                    route=route,
                    downstream_protocol="openai",
                    upstream_result=upstream_result,
                )
                decoded = upstream_result.body.decode("utf-8", errors="replace")
                return self._error_response(
                    status_code=502,
                    error_type="invalid_upstream_response",
                    message=decoded,
                )
            self._log_upstream_answer(
                token=token,
                stamp=qa_stamp,
                route=route,
                downstream_protocol="openai",
                upstream_result=upstream_result,
                upstream_json=upstream_json,
                downstream_payload=upstream_json,
            )
            self._remember_reasoning_for_tool_calls(token=token, openai_response=upstream_json)
            return ProxyResponse(status_code=upstream_result.status_code, payload=upstream_json)

        anthropic_messages, anthropic_system = _openai_messages_to_anthropic(body.get("messages"))
        anthropic_payload: dict[str, Any] = {
            "model": route.upstream_model,
            "messages": anthropic_messages,
            "max_tokens": int(
                body.get("max_tokens", body.get("max_completion_tokens", 1024))
            ),
        }
        if anthropic_system is not None:
            anthropic_payload["system"] = anthropic_system
        if "temperature" in body:
            anthropic_payload["temperature"] = body["temperature"]
        if "top_p" in body:
            anthropic_payload["top_p"] = body["top_p"]
        anthropic_tools = _openai_tools_to_anthropic(body.get("tools"))
        if anthropic_tools:
            anthropic_payload["tools"] = anthropic_tools
            tool_choice = _openai_tool_choice_to_anthropic(body.get("tool_choice"))
            if tool_choice is not None:
                anthropic_payload["tool_choice"] = tool_choice

        upstream_url = _join_url(route.upstream_base_url, "/v1/messages")
        upstream_headers = {
            "x-api-key": route.upstream_api_key,
            "anthropic-version": "2023-06-01",
        }
        qa_stamp = self._log_upstream_query(
            token=token,
            route=route,
            downstream_protocol="openai",
            upstream_url=upstream_url,
            upstream_headers=upstream_headers,
            upstream_payload=anthropic_payload,
        )

        upstream_result = self._post_json(
            url=upstream_url,
            payload=anthropic_payload,
            headers=upstream_headers,
            timeout_seconds=route.timeout_seconds,
        )
        anthropic_json = self._parse_json_body(upstream_result)
        if anthropic_json is None:
            self._log_upstream_answer(
                token=token,
                stamp=qa_stamp,
                route=route,
                downstream_protocol="openai",
                upstream_result=upstream_result,
            )
            decoded = upstream_result.body.decode("utf-8", errors="replace")
            return self._error_response(
                status_code=502,
                error_type="invalid_upstream_response",
                message=decoded,
            )

        if upstream_result.status_code >= 400:
            self._log_upstream_answer(
                token=token,
                stamp=qa_stamp,
                route=route,
                downstream_protocol="openai",
                upstream_result=upstream_result,
                upstream_json=anthropic_json,
            )
            return self._error_response(
                status_code=upstream_result.status_code,
                error_type="upstream_error",
                message=json.dumps(anthropic_json, ensure_ascii=True),
            )

        openai_response = self._openai_response_from_anthropic(
            anthropic_response=anthropic_json,
            requested_model=requested_model,
        )
        self._log_upstream_answer(
            token=token,
            stamp=qa_stamp,
            route=route,
            downstream_protocol="openai",
            upstream_result=upstream_result,
            upstream_json=anthropic_json,
            downstream_payload=openai_response,
        )
        return ProxyResponse(status_code=200, payload=openai_response)


class ProxyRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the local proxy server."""

    server: "ProxyHTTPServer"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_sse_raw(self, payload: str) -> None:
        body = payload.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_sse_message(self, payload: dict[str, Any]) -> None:
        """Send a synthesized Anthropic-compatible SSE stream."""
        content_blocks = payload.get("content", [])
        if not isinstance(content_blocks, list):
            content_blocks = []

        message_obj = {
            "id": payload.get("id", f"msg_{uuid4().hex}"),
            "type": "message",
            "role": "assistant",
            "content": [],
            "model": payload.get("model"),
            "stop_reason": None,
            "stop_sequence": None,
            "usage": {
                "input_tokens": payload.get("usage", {}).get("input_tokens", 0),
                "output_tokens": 0,
            },
        }
        usage = payload.get("usage", {})
        output_tokens = int(usage.get("output_tokens", 0)) if isinstance(usage, dict) else 0
        stop_reason = payload.get("stop_reason", "end_turn")

        events: list[tuple[str, dict[str, Any]]] = [
            ("message_start", {"type": "message_start", "message": message_obj})
        ]

        for index, block in enumerate(content_blocks):
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type", "")).strip()
            if block_type == "text":
                events.append(
                    (
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": index,
                            "content_block": {"type": "text", "text": ""},
                        },
                    )
                )
                events.append(
                    (
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": index,
                            "delta": {"type": "text_delta", "text": str(block.get("text", ""))},
                        },
                    )
                )
                events.append(
                    ("content_block_stop", {"type": "content_block_stop", "index": index})
                )
                continue

            if block_type == "tool_use":
                tool_input = block.get("input", {})
                if not isinstance(tool_input, (dict, list)):
                    tool_input = {"value": tool_input}
                tool_block = {
                    "type": "tool_use",
                    "id": str(block.get("id", f"toolu_{uuid4().hex[:12]}")),
                    "name": str(block.get("name", "")),
                    # For streamed tool_use, clients reconstruct input from input_json_delta.
                    # Keep start payload input empty and send full JSON in delta.
                    "input": {},
                }
                events.append(
                    (
                        "content_block_start",
                        {
                            "type": "content_block_start",
                            "index": index,
                            "content_block": tool_block,
                        },
                    )
                )
                tool_input_json = json.dumps(tool_input, ensure_ascii=False)
                events.append(
                    (
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": index,
                            "delta": {
                                "type": "input_json_delta",
                                "partial_json": tool_input_json,
                            },
                        },
                    )
                )
                events.append(
                    ("content_block_stop", {"type": "content_block_stop", "index": index})
                )
                continue

            events.append(
                (
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": index,
                        "content_block": block,
                    },
                )
            )
            events.append(("content_block_stop", {"type": "content_block_stop", "index": index}))

        events.extend(
            [
                (
                    "message_delta",
                    {
                        "type": "message_delta",
                        "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                        "usage": {"output_tokens": output_tokens},
                    },
                ),
                ("message_stop", {"type": "message_stop"}),
            ]
        )

        chunks: list[str] = []
        for event, data in events:
            chunks.append(f"event: {event}\n")
            chunks.append(f"data: {json.dumps(data, ensure_ascii=True)}\n\n")

        body = "".join(chunks).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length_raw = self.headers.get("Content-Length", "0")
        try:
            length = int(length_raw)
        except ValueError:
            length = 0
        raw = self.rfile.read(max(length, 0)).decode("utf-8")
        if not raw:
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Request body must be JSON object")
        return data

    def _extract_token(self, body: dict[str, Any] | None = None) -> str:
        authorization = self.headers.get("Authorization")
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization.split(" ", 1)[1].strip()
            if token:
                return token
        header_key = self.headers.get("x-api-key")
        if header_key:
            return header_key
        if body and isinstance(body.get("session_token"), str):
            return str(body["session_token"])
        return "anonymous"

    def do_GET(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        if path == "/healthz":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "routes": len(self.server.runtime.routing.routes),
                },
            )
            return
        if path == "/routes":
            self._send_json(
                200,
                {
                    "routes": [
                        {
                            "name": route.name,
                            "request_model": route.name,
                            "legacy_model_alias": route.request_model,
                            "upstream_provider": route.upstream_provider,
                            "upstream_base_url": route.upstream_base_url,
                            "upstream_model": route.upstream_model,
                        }
                        for route in self.server.runtime.routing.routes
                    ]
                },
            )
            return
        if path == "/sessions":
            self._send_json(200, {"sessions": self.server.runtime.sessions_snapshot()})
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        path = urllib.parse.urlparse(self.path).path
        try:
            body = self._read_json()
        except Exception as exc:
            self._send_json(400, {"error": f"invalid_json: {exc}"})
            return

        if path == "/sessions/register":
            token = str(body.get("token", "")).strip()
            if not token:
                self._send_json(400, {"error": "`token` is required"})
                return
            sandbox_id = body.get("sandbox_id")
            task_name = body.get("task_name")
            session = self.server.runtime.register_session(
                token=token,
                sandbox_id=str(sandbox_id) if sandbox_id else None,
                task_name=str(task_name) if task_name else None,
            )
            self._send_json(
                200,
                {
                    "token": session.token,
                    "sandbox_id": session.sandbox_id,
                    "task_name": session.task_name,
                    "created_at": session.created_at,
                },
            )
            return

        if path == "/sessions/event":
            token = str(body.get("token", "")).strip()
            event_type = str(body.get("event_type", "")).strip()
            payload = body.get("payload", {})
            if not token or not event_type:
                self._send_json(400, {"error": "`token` and `event_type` are required"})
                return
            if not isinstance(payload, dict):
                self._send_json(400, {"error": "`payload` must be an object"})
                return
            self.server.runtime.record_event(
                token=token,
                event_type=event_type,
                payload=payload,
            )
            self._send_json(200, {"ok": True})
            return

        token = self._extract_token(body=body)
        if path in {"/v1/messages", "/v1/message"}:
            response = self.server.runtime.process_anthropic_messages(token=token, body=body)
            if response.mode == "sse_raw" and isinstance(response.payload, str):
                self._send_sse_raw(response.payload)
            elif response.mode == "sse_synth" and isinstance(response.payload, dict):
                self._send_sse_message(response.payload)
            elif isinstance(response.payload, dict):
                self._send_json(response.status_code, response.payload)
            else:
                self._send_json(500, {"error": "invalid_proxy_response"})
            return

        if path == "/v1/chat/completions":
            response = self.server.runtime.process_openai_chat_completions(
                token=token,
                body=body,
            )
            if isinstance(response.payload, dict):
                self._send_json(response.status_code, response.payload)
            else:
                self._send_json(500, {"error": "invalid_proxy_response"})
            return

        self._send_json(404, {"error": "not_found"})


class ProxyHTTPServer(ThreadingHTTPServer):
    """HTTP server type holding shared proxy runtime."""

    def __init__(self, server_address: tuple[str, int], runtime: ProxyRuntime):
        super().__init__(server_address=server_address, RequestHandlerClass=ProxyRequestHandler)
        self.runtime = runtime


class LLMProxyServer:
    """Threaded local LLM proxy server with trajectory persistence."""

    def __init__(self, routing: LLMProxyRoutingConfig, proxy: ProxyConfig):
        self.runtime = ProxyRuntime(routing=routing, proxy=proxy)
        self._httpd = ProxyHTTPServer((proxy.host, proxy.port), runtime=self.runtime)
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return self.runtime.proxy.base_url

    def trajectory_path(self, token: str) -> Path:
        return self.runtime.trajectory_path(token)

    def register_session(
        self,
        token: str,
        sandbox_id: str | None,
        task_name: str | None,
    ) -> None:
        self.runtime.register_session(token=token, sandbox_id=sandbox_id, task_name=task_name)

    def record_event(self, token: str, event_type: str, payload: dict[str, Any]) -> None:
        self.runtime.record_event(token=token, event_type=event_type, payload=payload)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread:
            self._thread.join(timeout=3)

    @contextmanager
    def running(self) -> Any:
        self.start()
        try:
            yield self
        finally:
            self.stop()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local LLM proxy for Agent2Sandbox")
    parser.add_argument(
        "--cfg-file",
        default="config/llmproxy-cfg.yaml",
        help="Path to llmproxy routing config yaml",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Proxy listen host")
    parser.add_argument("--port", type=int, default=18080, help="Proxy listen port")
    parser.add_argument(
        "--log-dir",
        default="logs/trajectory",
        help="Directory for per-session trajectory files",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    routing = load_llmproxy_routing_config(cfg_file=args.cfg_file)
    proxy = ProxyConfig(host=args.host, port=args.port, log_dir=Path(args.log_dir))
    server = LLMProxyServer(routing=routing, proxy=proxy)
    print(f"LLM proxy listening on {proxy.base_url}")
    print(f"Routes loaded: {len(routing.routes)}")
    with server.running():
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
