"""Simple local LLM proxy with model routing and trajectory logging."""

from __future__ import annotations

import argparse
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
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
        parts: List[str] = []
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


def _safe_json_loads(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return None


def _join_url(base_url: str, suffix: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith(suffix):
        return base
    return f"{base}{suffix}"


@dataclass
class ProxySession:
    token: str
    sandbox_id: Optional[str]
    task_name: Optional[str]
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
    payload: Union[Dict[str, Any], str]
    mode: str = "json"  # json | sse_synth | sse_raw


class TrajectoryStore:
    """Per-session QA trajectory writer."""

    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._suffix_counter: Dict[Tuple[str, str], int] = {}

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

    def _write_json(self, path: Path, payload: Dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def write_qa(
        self,
        token: str,
        request_payload: Dict[str, Any],
        response_payload: Dict[str, Any],
    ) -> str:
        with self._lock:
            stamp = self._alloc_stamp(token)
            session_dir = self._session_dir(token)
            req_path = session_dir / f"{stamp}-req.json"
            res_path = session_dir / f"{stamp}-assistant.json"
            self._write_json(req_path, request_payload)
            self._write_json(res_path, response_payload)
        return stamp

    def path_for(self, token: str) -> Path:
        return self._session_dir(token)


class ProxyRuntime:
    """In-memory runtime state shared by all HTTP handlers."""

    def __init__(self, routing: LLMProxyRoutingConfig, proxy: ProxyConfig):
        self.routing = routing
        self.proxy = proxy
        self.store = TrajectoryStore(proxy.log_dir)
        self._sessions: Dict[str, ProxySession] = {}
        self._lock = threading.Lock()
        self._reasoning_by_token: Dict[str, Dict[str, str]] = {}

    def register_session(
        self,
        token: str,
        sandbox_id: Optional[str],
        task_name: Optional[str],
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
        return session

    def record_event(self, token: str, event_type: str, payload: Dict[str, Any]) -> None:
        now = _utc_now()
        with self._lock:
            session = self._sessions.get(token)
            if session:
                session.updated_at = now
        # Intentionally skip persisting event logs to keep trajectory logs focused on QA pairs.

    def sessions_snapshot(self) -> List[Dict[str, Any]]:
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
        openai_response: Dict[str, Any],
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

        call_ids: List[str] = []
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
        messages: List[Dict[str, Any]],
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

            reasoning_value: Optional[str] = None
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

    def _should_skip_trajectory(self, request_payload: Dict[str, Any]) -> bool:
        messages = request_payload.get("messages")
        if isinstance(messages, list):
            for message in messages:
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role", "")).strip()
                content = message.get("content")
                if role == "user":
                    user_text = _extract_text_content(content).strip()
                    if user_text.lower() == "warmup":
                        return True
                    lowered = user_text.lower()
                    if "analyze if this message indicates a new conversation topic" in lowered:
                        return True
                    break

        system_text = _extract_text_content(request_payload.get("system")).lower()
        if "summarize this coding conversation" in system_text:
            return True
        if "analyze if this message indicates a new conversation topic" in system_text:
            return True
        return False

    def _log_downstream_qa(
        self,
        token: str,
        request_payload: Optional[Dict[str, Any]],
        response_payload: Optional[Dict[str, Any]],
    ) -> None:
        if request_payload is None or response_payload is None:
            return
        if self._should_skip_trajectory(request_payload):
            return
        self.store.write_qa(
            token=token,
            request_payload=request_payload,
            response_payload=response_payload,
        )

    def _parse_json_body(self, result: UpstreamHTTPResult) -> Optional[Dict[str, Any]]:
        try:
            parsed = json.loads(result.body.decode("utf-8"))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
        return None

    def _anthropic_response_from_sse(self, payload: str) -> Optional[Dict[str, Any]]:
        content_blocks: List[Dict[str, Any]] = []
        blocks_by_index: Dict[int, Dict[str, Any]] = {}
        input_buffers: Dict[int, str] = {}
        response: Dict[str, Any] = {
            "id": f"msg_{uuid4().hex}",
            "type": "message",
            "role": "assistant",
            "model": "",
            "content": content_blocks,
            "stop_reason": "end_turn",
            "stop_sequence": None,
        }
        usage: Dict[str, Any] = {}

        for raw_line in payload.splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            event = _safe_json_loads(data)
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type", "")).strip()
            if event_type == "message_start":
                message = event.get("message")
                if isinstance(message, dict):
                    response["id"] = message.get("id", response["id"])
                    response["model"] = message.get("model", response.get("model", ""))
                    response["role"] = message.get("role", "assistant")
                    if "usage" in message and isinstance(message["usage"], dict):
                        usage.update(message["usage"])
                continue
            if event_type == "content_block_start":
                index = event.get("index")
                block = event.get("content_block")
                if isinstance(index, int) and isinstance(block, dict):
                    blocks_by_index[index] = dict(block)
                continue
            if event_type == "content_block_delta":
                index = event.get("index")
                delta = event.get("delta")
                if not isinstance(index, int) or not isinstance(delta, dict):
                    continue
                block = blocks_by_index.setdefault(index, {"type": delta.get("type", "text")})
                delta_type = str(delta.get("type", "")).strip()
                if delta_type == "text_delta":
                    text = delta.get("text")
                    if isinstance(text, str):
                        block["text"] = f"{block.get('text', '')}{text}"
                elif delta_type == "thinking_delta":
                    thinking = delta.get("thinking") or delta.get("text")
                    if isinstance(thinking, str):
                        block["type"] = "thinking"
                        block["thinking"] = f"{block.get('thinking', '')}{thinking}"
                elif delta_type == "signature_delta":
                    signature = delta.get("signature")
                    if isinstance(signature, str):
                        block["signature"] = f"{block.get('signature', '')}{signature}"
                elif delta_type == "input_json_delta":
                    fragment = delta.get("partial_json")
                    if isinstance(fragment, str):
                        input_buffers[index] = input_buffers.get(index, "") + fragment
                        parsed = _safe_json_loads(input_buffers[index])
                        if isinstance(parsed, (dict, list)):
                            block["input"] = parsed
                continue
            if event_type == "content_block_stop":
                continue
            if event_type == "message_delta":
                delta = event.get("delta")
                if isinstance(delta, dict):
                    stop_reason = delta.get("stop_reason")
                    if isinstance(stop_reason, str) and stop_reason:
                        response["stop_reason"] = stop_reason
                    if "usage" in delta and isinstance(delta["usage"], dict):
                        usage.update(delta["usage"])
                continue

        if blocks_by_index:
            for index in sorted(blocks_by_index.keys()):
                block = blocks_by_index[index]
                if block.get("type") == "tool_use" and "input" not in block:
                    raw_input = input_buffers.get(index)
                    if isinstance(raw_input, str) and raw_input.strip():
                        parsed = _safe_json_loads(raw_input)
                        if parsed is not None:
                            block["input"] = parsed
                content_blocks.append(block)
        if usage:
            response["usage"] = usage
        if not content_blocks and not response.get("model"):
            return None
        return response

    def _openai_response_from_sse(
        self,
        payload: str,
        requested_model: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        response_id: Optional[str] = None
        model: Optional[str] = None
        created: Optional[int] = None
        finish_reason: Optional[str] = None
        usage: Optional[Dict[str, Any]] = None

        message: Dict[str, Any] = {"role": "assistant", "content": ""}
        tool_calls_map: Dict[int, Dict[str, Any]] = {}
        reasoning_content = ""

        for raw_line in payload.splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            event = _safe_json_loads(data)
            if not isinstance(event, dict):
                continue
            if response_id is None:
                value = event.get("id")
                if isinstance(value, str) and value:
                    response_id = value
            if model is None:
                value = event.get("model")
                if isinstance(value, str) and value:
                    model = value
            if created is None:
                value = event.get("created")
                if isinstance(value, int):
                    created = value
            if isinstance(event.get("usage"), dict):
                usage = event.get("usage")

            choices = event.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            choice = choices[0]
            if not isinstance(choice, dict):
                continue
            if choice.get("finish_reason") is not None:
                finish_reason = choice.get("finish_reason")
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                continue

            if "role" in delta and isinstance(delta.get("role"), str):
                message["role"] = delta["role"]
            if "content" in delta and isinstance(delta.get("content"), str):
                message["content"] = f"{message.get('content', '')}{delta['content']}"
            if "reasoning_content" in delta and isinstance(delta.get("reasoning_content"), str):
                reasoning_content += delta["reasoning_content"]

            tool_calls = delta.get("tool_calls")
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    index = tool_call.get("index")
                    if not isinstance(index, int):
                        index = len(tool_calls_map)
                    entry = tool_calls_map.get(index)
                    if entry is None:
                        entry = {
                            "id": str(tool_call.get("id", "")) or f"call_{uuid4().hex[:12]}",
                            "type": str(tool_call.get("type", "function")) or "function",
                            "function": {"name": "", "arguments": ""},
                        }
                        tool_calls_map[index] = entry
                    if tool_call.get("id"):
                        entry["id"] = str(tool_call.get("id"))
                    function = tool_call.get("function")
                    if isinstance(function, dict):
                        name = function.get("name")
                        if isinstance(name, str) and name:
                            entry["function"]["name"] += name
                        arguments = function.get("arguments")
                        if isinstance(arguments, str) and arguments:
                            entry["function"]["arguments"] += arguments

        if tool_calls_map:
            message["tool_calls"] = [tool_calls_map[i] for i in sorted(tool_calls_map.keys())]
        if reasoning_content:
            message["reasoning_content"] = reasoning_content

        if not response_id and not model and not message.get("content") and not tool_calls_map:
            return None

        response: Dict[str, Any] = {
            "id": response_id or f"chatcmpl-{uuid4().hex}",
            "object": "chat.completion",
            "model": model or requested_model or "unknown-model",
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason or "stop",
                }
            ],
        }
        if created is not None:
            response["created"] = created
        if usage is not None:
            response["usage"] = usage
        return response

    def _post_json(
        self,
        url: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
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
    ) -> Optional[LLMProxyRoute]:
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
        body: Dict[str, Any],
    ) -> ProxyResponse:
        request_log = dict(body)
        upstream_payload = dict(body)
        upstream_payload["model"] = route.upstream_model
        upstream_url = _join_url(route.upstream_base_url, "/v1/messages")
        upstream_headers = {
            "x-api-key": route.upstream_api_key,
            "anthropic-version": "2023-06-01",
        }

        upstream_result = self._post_json(
            url=upstream_url,
            payload=upstream_payload,
            headers=upstream_headers,
            timeout_seconds=route.timeout_seconds,
        )

        stream_requested = body.get("stream") is True
        if upstream_result.status_code >= 400:
            decoded = upstream_result.body.decode("utf-8", errors="replace")
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
            sse_payload = upstream_result.body.decode("utf-8", errors="replace")
            downstream_log = self._anthropic_response_from_sse(sse_payload)
            if downstream_log is not None:
                self._log_downstream_qa(
                    token=token,
                    request_payload=request_log,
                    response_payload=downstream_log,
                )
            return ProxyResponse(
                status_code=upstream_result.status_code,
                payload=sse_payload,
                mode="sse_raw",
            )

        parsed = self._parse_json_body(upstream_result)
        if parsed is None:
            return self._error_response(
                status_code=502,
                error_type="invalid_upstream_response",
                message="Anthropic upstream returned non-JSON response",
            )
        if isinstance(parsed, dict):
            self._log_downstream_qa(
                token=token,
                request_payload=request_log,
                response_payload=parsed,
            )
        return ProxyResponse(status_code=upstream_result.status_code, payload=parsed, mode="json")

    def process_anthropic_messages(
        self,
        token: str,
        body: Dict[str, Any],
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

        if route.upstream_provider != "anthropic":
            return self._error_response(
                status_code=400,
                error_type="provider_mismatch",
                message=(
                    "Downstream request is anthropic, but route upstream_provider is "
                    f"{route.upstream_provider}. Configure matching provider in task yaml."
                ),
            )
        return self._process_anthropic_passthrough(token=token, route=route, body=body)

    def process_openai_chat_completions(
        self,
        token: str,
        body: Dict[str, Any],
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
            request_log = dict(body)
            payload = dict(body)
            payload["model"] = route.upstream_model
            if isinstance(payload.get("messages"), list):
                self._inject_reasoning_content(token, payload["messages"])
            upstream_url = _join_url(route.upstream_base_url, "/chat/completions")
            upstream_headers = {"Authorization": f"Bearer {route.upstream_api_key}"}
            upstream_result = self._post_json(
                url=upstream_url,
                payload=payload,
                headers=upstream_headers,
                timeout_seconds=route.timeout_seconds,
            )
            stream_requested = body.get("stream") is True
            if stream_requested and "text/event-stream" in upstream_result.content_type.lower():
                sse_payload = upstream_result.body.decode("utf-8", errors="replace")
                downstream_log = self._openai_response_from_sse(
                    payload=sse_payload,
                    requested_model=requested_model,
                )
                if downstream_log is not None:
                    self._log_downstream_qa(
                        token=token,
                        request_payload=request_log,
                        response_payload=downstream_log,
                    )
                return ProxyResponse(
                    status_code=upstream_result.status_code,
                    payload=sse_payload,
                    mode="sse_raw",
                )
            upstream_json = self._parse_json_body(upstream_result)
            if upstream_json is None:
                decoded = upstream_result.body.decode("utf-8", errors="replace")
                return self._error_response(
                    status_code=502,
                    error_type="invalid_upstream_response",
                    message=decoded,
                )
            if upstream_result.status_code >= 400:
                return ProxyResponse(
                    status_code=upstream_result.status_code,
                    payload=upstream_json,
                )
            self._remember_reasoning_for_tool_calls(token=token, openai_response=upstream_json)
            self._log_downstream_qa(
                token=token,
                request_payload=request_log,
                response_payload=upstream_json,
            )
            return ProxyResponse(status_code=upstream_result.status_code, payload=upstream_json)
        return self._error_response(
            status_code=400,
            error_type="provider_mismatch",
            message=(
                "Downstream request is openai, but route upstream_provider is "
                f"{route.upstream_provider}. Configure matching provider in task yaml."
            ),
        )


class ProxyRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the local proxy server."""

    server: "ProxyHTTPServer"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status_code: int, payload: Dict[str, Any]) -> None:
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

    def _send_sse_message(self, payload: Dict[str, Any]) -> None:
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

        events: List[Tuple[str, Dict[str, Any]]] = [
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

        chunks: List[str] = []
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

    def _read_json(self) -> Dict[str, Any]:
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

    def _extract_token(self, body: Optional[Dict[str, Any]] = None) -> str:
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
        if path in {"/v1/messages", "/v1/message", "/messages", "/message"}:
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

        if path in {"/v1/chat/completions", "/chat/completions"}:
            response = self.server.runtime.process_openai_chat_completions(
                token=token,
                body=body,
            )
            if response.mode == "sse_raw" and isinstance(response.payload, str):
                self._send_sse_raw(response.payload)
            elif isinstance(response.payload, dict):
                self._send_json(response.status_code, response.payload)
            else:
                self._send_json(500, {"error": "invalid_proxy_response"})
            return

        self._send_json(404, {"error": "not_found"})


class ProxyHTTPServer(ThreadingHTTPServer):
    """HTTP server type holding shared proxy runtime."""

    def __init__(self, server_address: Tuple[str, int], runtime: ProxyRuntime):
        super().__init__(server_address=server_address, RequestHandlerClass=ProxyRequestHandler)
        self.runtime = runtime


class LLMProxyServer:
    """Threaded local LLM proxy server with trajectory persistence."""

    def __init__(self, routing: LLMProxyRoutingConfig, proxy: ProxyConfig):
        self.runtime = ProxyRuntime(routing=routing, proxy=proxy)
        self._httpd = ProxyHTTPServer((proxy.host, proxy.port), runtime=self.runtime)
        self._thread: Optional[threading.Thread] = None

    @property
    def base_url(self) -> str:
        return self.runtime.proxy.base_url

    def trajectory_path(self, token: str) -> Path:
        return self.runtime.trajectory_path(token)

    def register_session(
        self,
        token: str,
        sandbox_id: Optional[str],
        task_name: Optional[str],
    ) -> None:
        self.runtime.register_session(token=token, sandbox_id=sandbox_id, task_name=task_name)

    def record_event(self, token: str, event_type: str, payload: Dict[str, Any]) -> None:
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
