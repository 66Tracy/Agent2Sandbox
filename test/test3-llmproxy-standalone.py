"""
Test 3: Run LLM-Proxy as standalone service.

Usage:
    python test/test3-llmproxy-standalone.py
    python test/test3-llmproxy-standalone.py --duration 60
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent2sandbox.llm_proxy import LLMProxyServer
from agent2sandbox.settings import ProxyConfig, load_llmproxy_routing_config


def _http_get_json(url: str, timeout_seconds: int = 5) -> dict[str, Any]:
    request = urllib.request.Request(url=url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run standalone LLM-Proxy for manual tests")
    parser.add_argument(
        "--cfg-file",
        default=os.getenv("A2S_PROXY_CFG_FILE", "config/llmproxy-cfg.yaml"),
        help="Path to llmproxy config yaml",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("A2S_PROXY_HOST", "127.0.0.1"),
        help="Proxy listen host",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("A2S_PROXY_PORT", "18080")),
        help="Proxy listen port",
    )
    parser.add_argument(
        "--log-dir",
        default=os.getenv("A2S_TRAJECTORY_DIR", "logs/trajectory"),
        help="Trajectory log directory",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=0,
        help="Keep proxy alive for N seconds. 0 means run until Ctrl+C.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    routing = load_llmproxy_routing_config(cfg_file=args.cfg_file)
    proxy = ProxyConfig(host=args.host, port=args.port, log_dir=Path(args.log_dir))
    server = LLMProxyServer(routing=routing, proxy=proxy)

    print("=" * 72)
    print("Test 3: Standalone LLM-Proxy")
    print("=" * 72)
    print(f"Proxy listen: {proxy.base_url}")
    print(f"Proxy cfg: {args.cfg_file}")
    print(f"Trajectory dir: {proxy.log_dir}")
    print(f"Routes loaded: {len(routing.routes)}")
    print("Press Ctrl+C to stop.")

    with server.running():
        try:
            health = _http_get_json(f"{proxy.base_url}/healthz")
            routes = _http_get_json(f"{proxy.base_url}/routes")
            print(f"\nHealth: {health}")
            print("Routes:")
            for route in routes.get("routes", []):
                print(
                    "- {name}: request_model={request_model}, upstream={provider}:{model}".format(
                        name=route.get("name"),
                        request_model=route.get("request_model"),
                        provider=route.get("upstream_provider"),
                        model=route.get("upstream_model"),
                    )
                )
        except urllib.error.URLError as exc:
            print(f"\nProxy startup check failed: {exc}")
            return 1

        try:
            if args.duration > 0:
                deadline = time.time() + args.duration
                while time.time() < deadline:
                    time.sleep(0.5)
                print(f"\nDuration reached ({args.duration}s), proxy stopped.")
                return 0
            threading.Event().wait()
        except KeyboardInterrupt:
            print("\nReceived Ctrl+C, proxy stopped.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
