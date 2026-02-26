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
from typing import Any, Dict

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from llm_proxy import (
    LLMProxyConfig,
    LLMProxyServer,
    LLMProxyServerConfig,
    load_llmproxy_config,
)


def _http_get_json(url: str, timeout_seconds: int = 5) -> Dict[str, Any]:
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
        "--duration",
        type=int,
        default=0,
        help="Keep proxy alive for N seconds. 0 means run until Ctrl+C.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    config = load_llmproxy_config(cfg_file=args.cfg_file)
    server = LLMProxyServer(config=config)

    print("=" * 72)
    print("Test 3: Standalone LLM-Proxy")
    print("=" * 72)
    print(f"Proxy listen: {server.base_url}")
    print(f"Proxy cfg: {args.cfg_file}")
    print(f"Trajectory dir: {config.server_config.log_dir}")
    print(f"Routes loaded: {len(config.routing_config.routes)}")
    print("Press Ctrl+C to stop.")

    with server.running():
        try:
            health = _http_get_json(f"{server.base_url}/healthz")
            routes = _http_get_json(f"{server.base_url}/routes")
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
