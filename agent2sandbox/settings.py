"""Project settings loaders for Agent2Sandbox demo components."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _load_yaml_object(path: Path) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError(
            "PyYAML is required to load YAML configuration files. Install `pyyaml`."
        ) from exc
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"Configuration file {path} must contain an object at top level")
    return data


def _require(mapping: dict[str, Any], key: str) -> Any:
    value = mapping.get(key)
    if value is None:
        raise ValueError(f"Missing required config field: {key}")
    return value


def _resolve_ref(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("ENV:"):
        env_key = text.split(":", 1)[1].strip()
        if not env_key:
            raise ValueError("ENV reference must include key name, got empty key")
        resolved = os.environ.get(env_key)
        if resolved is None:
            raise ValueError(f"Cannot resolve environment variable: {env_key}")
        return resolved
    return text


def _build_missing_config_error(cfg_path: Path, context: str) -> FileNotFoundError:
    example_cfg = cfg_path.with_name(cfg_path.name.replace(".yaml", ".example.yaml"))
    if example_cfg.exists():
        return FileNotFoundError(
            f"Missing config file: {cfg_path}. "
            f"Copy {example_cfg} -> {cfg_path} and fill your {context} settings."
        )
    return FileNotFoundError(f"Missing config file: {cfg_path}")


@dataclass(frozen=True)
class ProxyConfig:
    """Local proxy listen configuration."""

    host: str = "127.0.0.1"
    port: int = 18080
    log_dir: Path = Path("logs/trajectory")

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(frozen=True)
class LLMProxyRoute:
    """Route describing downstream model key -> upstream model endpoint mapping."""

    name: str
    request_model: str
    upstream_provider: str
    upstream_base_url: str
    upstream_model: str
    upstream_api_key: str
    timeout_seconds: int = 120


@dataclass(frozen=True)
class LLMProxyRoutingConfig:
    """Model routing configuration loaded from `config/llmproxy-cfg.yaml`."""

    routes: list[LLMProxyRoute]
    default_timeout_seconds: int = 120

    def match(self, requested_model: str) -> LLMProxyRoute:
        model = requested_model.strip()
        # Primary rule: downstream `model` maps to route `name`.
        for route in self.routes:
            if route.name == model:
                return route
        # Backward compatibility: allow explicit `model` field per route.
        for route in self.routes:
            if route.request_model == model:
                return route
        for route in self.routes:
            if route.name == "*" or route.request_model == "*":
                return route
        raise ValueError(f"No LLM proxy route found for model={requested_model}")


@dataclass(frozen=True)
class SandboxServerConfig:
    """Sandbox server connection configuration."""

    domain: str
    api_key: str | None = None
    request_timeout_seconds: int = 90


def load_llmproxy_routing_config(
    cfg_file: str | Path = "config/llmproxy-cfg.yaml",
) -> LLMProxyRoutingConfig:
    """Load and validate LLM proxy routing configuration."""

    cfg_path = Path(cfg_file)
    if not cfg_path.exists():
        raise _build_missing_config_error(cfg_path, "upstream routing")

    data = _load_yaml_object(cfg_path)
    defaults = data.get("defaults", {}) or {}
    if not isinstance(defaults, dict):
        raise ValueError("`defaults` must be an object")
    default_timeout = int(defaults.get("timeout_seconds", 120))

    raw_routes = _require(data, "routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ValueError("`routes` must be a non-empty list")

    routes: list[LLMProxyRoute] = []
    for idx, route_item in enumerate(raw_routes):
        if not isinstance(route_item, dict):
            raise ValueError(f"routes[{idx}] must be an object")

        name = str(route_item.get("name") or "").strip()
        if not name:
            raise ValueError(f"routes[{idx}] requires non-empty `name`")

        request_model = route_item.get("model", name)

        upstream = _require(route_item, "upstream")
        if not isinstance(upstream, dict):
            raise ValueError(f"routes[{idx}].upstream must be an object")

        upstream_provider = str(_require(upstream, "provider")).strip().lower()
        upstream_base_url = str(_require(upstream, "base_url")).strip()
        upstream_model_raw = upstream.get("upstream_model_name", upstream.get("model"))
        if upstream_model_raw is None:
            raise ValueError(
                f"routes[{idx}].upstream requires `upstream_model_name` or `model`"
            )
        upstream_model = str(upstream_model_raw).strip()
        timeout_seconds = int(upstream.get("timeout_seconds", default_timeout))

        if upstream_provider not in {"openai", "anthropic"}:
            raise ValueError(
                f"routes[{idx}].upstream.provider must be `openai` or `anthropic`"
            )

        api_key_ref = upstream.get("api_key_ref")
        api_key_value = upstream.get("api_key")
        resolved_key = _resolve_ref(
            str(api_key_ref)
            if api_key_ref is not None
            else (str(api_key_value) if api_key_value is not None else None)
        )
        if not resolved_key:
            raise ValueError(
                f"routes[{idx}] requires upstream.api_key or upstream.api_key_ref (ENV:KEY)"
            )

        routes.append(
            LLMProxyRoute(
                name=name,
                request_model=str(request_model).strip(),
                upstream_provider=upstream_provider,
                upstream_base_url=upstream_base_url,
                upstream_model=upstream_model,
                upstream_api_key=resolved_key,
                timeout_seconds=timeout_seconds,
            )
        )

    return LLMProxyRoutingConfig(
        routes=routes,
        default_timeout_seconds=default_timeout,
    )


def load_sandbox_server_config(
    cfg_file: str | Path = "config/sandbox-server-cfg.yaml",
) -> SandboxServerConfig:
    """Load sandbox server configuration from YAML."""

    cfg_path = Path(cfg_file)
    if not cfg_path.exists():
        raise _build_missing_config_error(cfg_path, "sandbox server")

    data = _load_yaml_object(cfg_path)
    # Support either top-level fields or nested `server` object.
    server = data.get("server", data)
    if not isinstance(server, dict):
        raise ValueError("`server` must be an object")

    domain = _resolve_ref(str(_require(server, "domain")))
    if not domain:
        raise ValueError("sandbox server domain cannot be empty")

    api_key_ref = server.get("api_key_ref")
    api_key_value = server.get("api_key")
    api_key: str | None = None
    if api_key_ref is not None:
        api_key = _resolve_ref(str(api_key_ref))
    elif api_key_value is not None:
        value = str(api_key_value).strip()
        api_key = value or None

    timeout_value = server.get("request_timeout_seconds", 90)
    timeout_seconds = int(timeout_value)
    if timeout_seconds <= 0:
        raise ValueError("request_timeout_seconds must be > 0")

    return SandboxServerConfig(
        domain=domain,
        api_key=api_key,
        request_timeout_seconds=timeout_seconds,
    )
