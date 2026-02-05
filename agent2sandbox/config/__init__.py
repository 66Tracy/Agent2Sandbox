"""
Configuration management for Agent2Sandbox.
"""

import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load .env file from project root
project_root = Path(__file__).parent.parent.parent
env_path = project_root / "agent2sandbox" / ".env"
load_dotenv(env_path)


class Config(BaseModel):
    """Agent2Sandbox configuration."""

    base_url: str = Field(
        default="https://api.openai.com/v1",
        description="Base URL for LLM API"
    )
    api_key: str = Field(
        default="",
        description="API key for LLM provider"
    )
    model_name: str = Field(
        default="gpt-4o-mini",
        description="Model name to use"
    )
    sandbox_image: str = Field(
        default="sandbox-registry.cn-zhangjiakou.cr.aliyuncs.com/opensandbox/code-interpreter:v1.0.1",
        description="Docker image for sandbox"
    )
    max_steps: int = Field(
        default=10,
        description="Maximum number of steps for task execution"
    )

    @classmethod
    def from_env(cls) -> "Config":
        """
        Load configuration from environment variables.

        Environment variables:
            BASE_URL: LLM API base URL
            API_KEY: LLM API key
            MODEL_NAME: Model name to use
            SANDBOX_IMAGE: Sandbox Docker image
            MAX_STEPS: Maximum steps
        """
        base_url = os.getenv("BASE_URL", "https://api.openai.com/v1")
        
        # Ensure base_url has proper format
        if not base_url.startswith(("http://", "https://")):
            base_url = f"https://{base_url}"
        
        return cls(
            base_url=base_url,
            api_key=os.getenv("API_KEY", ""),
            model_name=os.getenv("MODEL_NAME", "gpt-4o-mini"),
            sandbox_image=os.getenv("SANDBOX_IMAGE", cls.__fields__["sandbox_image"].default),
            max_steps=int(os.getenv("MAX_STEPS", "10")),
        )

    def validate(self) -> bool:
        """Validate that required configuration is present."""
        if not self.api_key:
            raise ValueError("API_KEY is required. Please set it in .env file or environment variables.")
        return True

    class Config:
        """Pydantic config."""
        env_file = str(env_path)
        env_file_encoding = "utf-8"
