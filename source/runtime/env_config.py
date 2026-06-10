from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: str | Path | None = None) -> None:
    env_paths = [Path(path)] if path else [REPO_ROOT / ".env"]

    for env_path in env_paths:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class ModelConfig:
    chat_completions_url: str
    api_key: str
    model: str
    timeout_seconds: int
    temperature: float
    max_tokens: int
    stream: bool
    package_id: str

    @classmethod
    def from_env(cls) -> "ModelConfig":
        load_dotenv()
        chat_url = os.getenv("MODEL_CHAT_COMPLETIONS_URL", "").strip()
        base_url = os.getenv("MODEL_BASE_URL", "").strip()
        if not chat_url and base_url:
            chat_url = base_url.rstrip("/") + "/chat/completions"
        if chat_url and not chat_url.rstrip("/").endswith("/chat/completions"):
            chat_url = chat_url.rstrip("/") + "/chat/completions"
        return cls(
            chat_completions_url=chat_url,
            api_key=os.getenv("MODEL_API_KEY", "").strip(),
            model=os.getenv("MODEL_NAME", "").strip(),
            timeout_seconds=env_int("AGENT_DEMO_TIMEOUT_SECONDS", 60),
            temperature=env_float("AGENT_DEMO_TEMPERATURE", 0.2),
            max_tokens=env_int("AGENT_DEMO_MAX_TOKENS", 0),
            stream=env_bool("AGENT_DEMO_STREAM", False),
            package_id=(os.getenv("PACKAGE_ID", "").strip() or os.getenv("packageId", "").strip()),
        )

    def is_configured(self) -> bool:
        return bool(self.chat_completions_url and self.api_key and self.model)
