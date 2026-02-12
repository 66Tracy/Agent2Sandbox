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
    return ""


def _anthropic_messages_to_openai(body: dict[str, Any]) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
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
        role = item.get("role")
        if role not in {"user", "assistant", "system"}:
            continue
        content = _extract_text_content(item.get("content"))
        messages.append({"role": str(role), "content": content})

    return messages


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
    """JSONL writer for per-session trajectory logs."""

    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def append(self, token: str, event_type: str, payload: dict[str, Any]) -> Path:
        record = {
            "timestamp": _utc_now(),
            "event_type": event_type,
            "payload": payload,
        }
        session_file = self.path_for(token)
        line = json.dumps(record, ensure_ascii=True)
        with self._lock:
            with session_file.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return session_file

    def path_for(self, token: str) -> Path:
        return self.log_dir / f"{_safe_file_token(token)}.jsonl"


class ProxyRuntime:
    """In-memory runtime state shared by all HTTP handlers."""

    def __init__(self, routing: LLMProxyRoutingConfig, proxy: ProxyConfig):
        self.routing = routing
        self.proxy = proxy
        self.store = TrajectoryStore(proxy.log_dir)
        self._sessions: dict[str, ProxySession] = {}
        self._lock = threading.Lock()

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

    def _anthropic_response_from_openai(
        self,
        openai_response: dict[str, Any],
        requested_model: str | None,
    ) -> dict[str, Any]:
        choices = openai_response.get("choices", [])
        assistant_text = ""
        stop_reason = "end_turn"
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message", {})
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    assistant_text = content
            finish_reason = choices[0].get("finish_reason")
            if finish_reason == "length":
                stop_reason = "max_tokens"

        usage = openai_response.get("usage", {})
        input_tokens = int(usage.get("prompt_tokens", 0)) if isinstance(usage, dict) else 0
        output_tokens = int(usage.get("completion_tokens", 0)) if isinstance(usage, dict) else 0

        return {
            "id": f"msg_{uuid4().hex}",
            "type": "message",
            "role": "assistant",
            "model": requested_model or "unknown-model",
            "content": [{"type": "text", "text": assistant_text}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
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
        downstream_provider: str,
        requested_model: str,
    ) -> LLMProxyRoute | None:
        try:
            route = self.routing.match(downstream_provider, requested_model)
        except Exception as exc:
            self.record_event(
                token=token,
                event_type="route_not_found",
                payload={
                    "downstream_provider": downstream_provider,
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
                "downstream_provider": downstream_provider,
                "downstream_model": requested_model,
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

        upstream_result = self._post_json(
            url=_join_url(route.upstream_base_url, "/v1/messages"),
            payload=upstream_payload,
            headers={
                "x-api-key": route.upstream_api_key,
                "anthropic-version": "2023-06-01",
            },
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
            return ProxyResponse(
                status_code=upstream_result.status_code,
                payload=upstream_result.body.decode("utf-8", errors="replace"),
                mode="sse_raw",
            )

        parsed = self._parse_json_body(upstream_result)
        if parsed is None:
            return self._error_response(
                status_code=502,
                error_type="invalid_upstream_response",
                message="Anthropic upstream returned non-JSON response",
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

        upstream_result = self._post_json(
            url=_join_url(route.upstream_base_url, "/chat/completions"),
            payload=openai_payload,
            headers={"Authorization": f"Bearer {route.upstream_api_key}"},
            timeout_seconds=route.timeout_seconds,
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
            self.record_event(
                token=token,
                event_type="upstream_error",
                payload={
                    "status_code": upstream_result.status_code,
                    "upstream_provider": route.upstream_provider,
                    "error": upstream_json,
                },
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
        self.record_event(
            token=token,
            event_type="anthropic_converted_response",
            payload={
                "route_name": route.name,
                "status_code": upstream_result.status_code,
                "output_tokens": anthropic_response["usage"]["output_tokens"],
            },
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
            downstream_provider="anthropic",
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
            downstream_provider="openai",
            requested_model=requested_model,
        )
        if route is None:
            return self._error_response(
                status_code=404,
                error_type="route_not_found",
                message=f"No route for openai model: {requested_model}",
            )
        if route.upstream_provider != "openai":
            return self._error_response(
                status_code=501,
                error_type="unsupported_conversion",
                message="openai downstream to anthropic upstream conversion is not implemented",
            )

        payload = dict(body)
        payload["model"] = route.upstream_model
        upstream_result = self._post_json(
            url=_join_url(route.upstream_base_url, "/chat/completions"),
            payload=payload,
            headers={"Authorization": f"Bearer {route.upstream_api_key}"},
            timeout_seconds=route.timeout_seconds,
        )
        upstream_json = self._parse_json_body(upstream_result)
        if upstream_json is None:
            decoded = upstream_result.body.decode("utf-8", errors="replace")
            return self._error_response(
                status_code=502,
                error_type="invalid_upstream_response",
                message=decoded,
            )
        return ProxyResponse(status_code=upstream_result.status_code, payload=upstream_json)


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
        """Send a minimal Anthropic-compatible SSE stream."""
        content_blocks = payload.get("content", [])
        text = ""
        if isinstance(content_blocks, list) and content_blocks:
            first = content_blocks[0]
            if isinstance(first, dict):
                text = str(first.get("text", ""))

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

        events = [
            ("message_start", {"type": "message_start", "message": message_obj}),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": text},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
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
                            "downstream_provider": route.downstream_provider,
                            "downstream_model": route.downstream_model,
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
    parser.add_argument("--env-file", default="agent2sandbox/.env", help="Path to env file")
    parser.add_argument("--host", default="127.0.0.1", help="Proxy listen host")
    parser.add_argument("--port", type=int, default=18080, help="Proxy listen port")
    parser.add_argument(
        "--log-dir",
        default="logs/trajectory",
        help="Directory for trajectory jsonl files",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    routing = load_llmproxy_routing_config(cfg_file=args.cfg_file, env_file=args.env_file)
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
