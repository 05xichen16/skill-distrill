from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


AGENTS_DIR = Path(__file__).resolve().parent / "agents"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@dataclass
class BaseSubAgent:
    name: str
    role: str

    async def run(self, *, task: str, context_text: str = "") -> str:
        raise NotImplementedError


@dataclass
class ScriptSubAgent(BaseSubAgent):
    agent_dir: Path
    entrypoint: str
    timeout_seconds: int

    async def run(self, *, task: str, context_text: str = "") -> str:
        script_path = (self.agent_dir / self.entrypoint).resolve()
        if not script_path.exists():
            raise FileNotFoundError(f"Sub-agent entrypoint not found: {script_path}")

        payload = {
            "agent_name": self.name,
            "role": self.role,
            "task": task,
            "context_text": context_text,
        }
        completed = subprocess.run(
            [sys.executable, str(script_path)],
            input=json.dumps(payload, ensure_ascii=False),
            text=True,
            capture_output=True,
            cwd=str(self.agent_dir),
            timeout=self.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"Sub-agent script failed: {script_path}\n"
                f"exit_code={completed.returncode}\n"
                f"stderr={completed.stderr.strip()}"
            )
        return completed.stdout.strip()


def _load_agent_package(agent_dir: Path) -> ScriptSubAgent | None:
    metadata_path = agent_dir / "agent.json"
    if not metadata_path.exists():
        return None
    metadata = _load_json(metadata_path)
    return ScriptSubAgent(
        name=metadata["name"],
        role=metadata.get("role", metadata.get("description", "")),
        agent_dir=agent_dir,
        entrypoint=metadata.get("entrypoint", "scripts/run.py"),
        timeout_seconds=int(metadata.get("timeout_seconds", 30)),
    )


def build_sub_agents() -> dict[str, BaseSubAgent]:
    agents: dict[str, BaseSubAgent] = {}
    if not AGENTS_DIR.exists():
        return agents
    for agent_dir in sorted(path for path in AGENTS_DIR.iterdir() if path.is_dir()):
        agent = _load_agent_package(agent_dir)
        if agent is not None:
            agents[agent.name] = agent
    return agents
