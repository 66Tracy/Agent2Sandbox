"""Project settings loaders for Agent2Sandbox demo components."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

def _fallback_env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            values[key] = value
    return values


@dataclass(frozen=True)
class UpstreamConfig:
    """Upstream model endpoint configuration loaded from `.env`."""

    base_url: str
    api_key: str
    model_name: str
    timeout_seconds: int = 120


@dataclass(frozen=True)
class ProxyConfig:
    """Local proxy listen configuration."""

    host: str = "127.0.0.1"
    port: int = 18080
    log_dir: Path = Path("logs/trajectory")

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


def load_upstream_config(env_file: str | Path = "agent2sandbox/.env") -> UpstreamConfig:
    """Load upstream model configuration from an env file."""

    env_path = Path(env_file)
    try:
        from dotenv import dotenv_values

        values = {k: v for k, v in dotenv_values(env_path).items() if v is not None}
    except ImportError:
        values = _fallback_env_values(env_path)

    base_url = values.get("BASE_URL")
    api_key = values.get("API_KEY")
    model_name = values.get("MODEL_NAME")
    timeout_value = values.get("PROXY_TIMEOUT_SECONDS", "120")

    missing = []
    if not base_url:
        missing.append("BASE_URL")
    if not api_key:
        missing.append("API_KEY")
    if not model_name:
        missing.append("MODEL_NAME")
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Missing required keys in {env_path}: {joined}")

    return UpstreamConfig(
        base_url=str(base_url),
        api_key=str(api_key),
        model_name=str(model_name),
        timeout_seconds=int(timeout_value),
    )
