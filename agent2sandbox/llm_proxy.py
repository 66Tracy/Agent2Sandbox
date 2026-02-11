"""Simple local LLM proxy with sandbox trajectory logging."""

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

from agent2sandbox.settings import ProxyConfig, UpstreamConfig, load_upstream_config


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


@dataclass
class ProxySession:
    token: str
    sandbox_id: str | None
    task_name: str | None
    created_at: str
    updated_at: str


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

    def __init__(self, upstream: UpstreamConfig, proxy: ProxyConfig):
        self.upstream = upstream
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

    def _upstream_chat_completions(
        self,
        openai_payload: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        url = self.upstream.base_url.rstrip("/") + "/chat/completions"
        body = json.dumps(openai_payload).encode("utf-8")
        request = urllib.request.Request(
            url=url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.upstream.api_key}",
                "Content-Type": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=self.upstream.timeout_seconds,
            ) as response:
                raw = response.read().decode("utf-8")
                data = json.loads(raw)
                return response.getcode(), data
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(error_body)
            except json.JSONDecodeError:
                data = {"error": error_body}
            return exc.code, data

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
            "model": requested_model or self.upstream.model_name,
            "content": [{"type": "text", "text": assistant_text}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        }

    def process_anthropic_messages(
        self,
        token: str,
        body: dict[str, Any],
    ) -> tuple[int, dict[str, Any]]:
        incoming_model = body.get("model")
        openai_payload: dict[str, Any] = {
            "model": self.upstream.model_name,
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

        self.record_event(
            token=token,
            event_type="anthropic_request",
            payload={
                "requested_model": incoming_model,
                "upstream_model": self.upstream.model_name,
                "messages_count": len(openai_payload["messages"]),
                "max_tokens": openai_payload["max_tokens"],
            },
        )

        status_code, upstream_response = self._upstream_chat_completions(openai_payload)
        if status_code >= 400:
            self.record_event(
                token=token,
                event_type="upstream_error",
                payload={
                    "status_code": status_code,
                    "error": upstream_response,
                },
            )
            return status_code, {
                "type": "error",
                "error": {
                    "type": "upstream_error",
                    "message": json.dumps(upstream_response, ensure_ascii=True),
                },
            }

        anthropic_response = self._anthropic_response_from_openai(
            openai_response=upstream_response,
            requested_model=incoming_model if isinstance(incoming_model, str) else None,
        )
        self.record_event(
            token=token,
            event_type="anthropic_response",
            payload={
                "status_code": status_code,
                "output_tokens": anthropic_response["usage"]["output_tokens"],
            },
        )
        return 200, anthropic_response


class ProxyRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the local proxy server."""

    server: "ProxyHTTPServer"

    def log_message(self, format: str, *args: Any) -> None:
        # Keep proxy output quiet; logs are captured in trajectory files.
        return

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
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
            "usage": {"input_tokens": payload.get("usage", {}).get("input_tokens", 0), "output_tokens": 0},
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
                    "upstream_base_url": self.server.runtime.upstream.base_url,
                    "upstream_model": self.server.runtime.upstream.model_name,
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

        if path.endswith("/v1/messages"):
            token = self._extract_token(body=body)
            status_code, response_payload = self.server.runtime.process_anthropic_messages(
                token=token,
                body=body,
            )
            if body.get("stream") is True and status_code < 400:
                self._send_sse_message(response_payload)
            else:
                self._send_json(status_code, response_payload)
            return

        self._send_json(404, {"error": "not_found"})


class ProxyHTTPServer(ThreadingHTTPServer):
    """HTTP server type holding shared proxy runtime."""

    def __init__(self, server_address: tuple[str, int], runtime: ProxyRuntime):
        super().__init__(server_address=server_address, RequestHandlerClass=ProxyRequestHandler)
        self.runtime = runtime


class LLMProxyServer:
    """Threaded local LLM proxy server with trajectory persistence."""

    def __init__(self, upstream: UpstreamConfig, proxy: ProxyConfig):
        self.runtime = ProxyRuntime(upstream=upstream, proxy=proxy)
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
    upstream = load_upstream_config(args.env_file)
    proxy = ProxyConfig(host=args.host, port=args.port, log_dir=Path(args.log_dir))
    server = LLMProxyServer(upstream=upstream, proxy=proxy)
    print(f"LLM proxy listening on {proxy.base_url}")
    print(f"Upstream: {upstream.base_url} (model={upstream.model_name})")
    with server.running():
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
