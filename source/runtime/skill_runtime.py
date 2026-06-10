from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SOURCE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SKILLS_DIR = SOURCE_DIR / "solution" / "skills"
RESOURCE_ROOTS = {"references", "assets"}


@dataclass(frozen=True)
class SkillPackage:
    name: str
    description: str
    skill_dir: Path
    skill_md_path: Path
    raw_markdown: str
    instructions: str
    metadata: dict[str, Any]
    entrypoint: str | None
    input_schema: dict[str, Any]
    timeout_seconds: int
    resources: list[str]

    @property
    def has_executable(self) -> bool:
        return bool(self.entrypoint)

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "has_executable": self.has_executable,
            "resources": self.resources,
        }


class SkillRuntime:
    def __init__(self, skills_dir: Path = DEFAULT_SKILLS_DIR):
        self.skills_dir = skills_dir
        self._skills: dict[str, SkillPackage] = {}
        self._aliases: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        skills: dict[str, SkillPackage] = {}
        aliases: dict[str, str] = {}
        if not self.skills_dir.exists():
            self._skills = {}
            self._aliases = {}
            return

        for skill_dir in sorted(path for path in self.skills_dir.iterdir() if path.is_dir()):
            skill_md_path = skill_dir / "SKILL.md"
            if not skill_md_path.exists():
                continue

            raw_markdown = skill_md_path.read_text(encoding="utf-8")
            frontmatter, instructions = _split_frontmatter(raw_markdown)
            metadata = _read_json(skill_dir / "skill.json")

            name = str(frontmatter.get("name") or metadata.get("name") or skill_dir.name).strip()
            description = str(
                frontmatter.get("description")
                or metadata.get("description")
                or _first_heading_or_line(instructions)
                or name
            ).strip()
            input_schema = metadata.get("input_schema") or metadata.get("parameters") or {}
            if not isinstance(input_schema, dict):
                input_schema = {}

            package = SkillPackage(
                name=name,
                description=description,
                skill_dir=skill_dir,
                skill_md_path=skill_md_path,
                raw_markdown=raw_markdown,
                instructions=instructions.strip(),
                metadata=metadata,
                entrypoint=metadata.get("entrypoint"),
                input_schema=input_schema,
                timeout_seconds=int(metadata.get("timeout_seconds", 20)),
                resources=_list_resources(skill_dir),
            )
            skills[name] = package
            for alias in {name, skill_dir.name, _normalize_name(name), _normalize_name(skill_dir.name)}:
                aliases[alias] = name

        self._skills = skills
        self._aliases = aliases

    def skill_names(self) -> list[str]:
        return sorted(self._skills)

    def list_skill_summaries(self) -> list[dict[str, Any]]:
        return [self._skills[name].summary() for name in self.skill_names()]

    def load_skill(self, name: str, max_chars: int = 20000) -> str:
        skill = self._resolve(name)
        content = _truncate(skill.raw_markdown, max_chars)
        payload = {
            "name": skill.name,
            "description": skill.description,
            "skill_dir": str(skill.skill_dir),
            "resources": skill.resources,
            "has_executable": skill.has_executable,
            "entrypoint": skill.entrypoint,
            "input_schema": skill.input_schema,
            "usage": "Follow the SKILL.md instructions. If execution is needed, call skill_run with this skill name and arguments matching input_schema.",
            "SKILL.md": content,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def read_resource(self, name: str, path: str, max_chars: int = 12000) -> str:
        skill = self._resolve(name)
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("resource path must be a relative path inside the skill package")
        if not relative.parts or relative.parts[0] not in RESOURCE_ROOTS:
            raise ValueError("resource path must be under references/ or assets/")

        target = (skill.skill_dir / relative).resolve()
        if not target.is_relative_to(skill.skill_dir.resolve()):
            raise ValueError("resource path escapes skill package")
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(f"resource not found: {path}")

        data = target.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        return _truncate(text, max_chars)

    def run_skill(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        skill = self._resolve(name)
        if not skill.entrypoint:
            raise RuntimeError(f"skill {skill.name} has no executable entrypoint")

        entrypoint = Path(skill.entrypoint)
        if entrypoint.is_absolute() or ".." in entrypoint.parts:
            raise ValueError("skill entrypoint must be a relative path inside the skill package")
        script_path = (skill.skill_dir / entrypoint).resolve()
        if not script_path.is_relative_to(skill.skill_dir.resolve()):
            raise ValueError("skill entrypoint escapes skill package")
        if not script_path.exists() or not script_path.is_file():
            raise FileNotFoundError(f"skill entrypoint not found: {skill.entrypoint}")

        stdin = json.dumps(arguments or {}, ensure_ascii=False)
        completed = subprocess.run(
            [sys.executable, str(script_path)],
            input=stdin,
            text=True,
            capture_output=True,
            cwd=str(skill.skill_dir),
            timeout=skill.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            error = completed.stderr.strip() or completed.stdout.strip()
            raise RuntimeError(f"skill {skill.name} failed with exit code {completed.returncode}: {error}")
        return completed.stdout.strip()

    def _resolve(self, name: str) -> SkillPackage:
        key = self._aliases.get(name) or self._aliases.get(_normalize_name(name))
        if key and key in self._skills:
            return self._skills[key]
        available = ", ".join(self.skill_names()) or "<none>"
        raise KeyError(f"unknown skill: {name}. available skills: {available}")


_RUNTIME: SkillRuntime | None = None


def get_skill_runtime() -> SkillRuntime:
    global _RUNTIME
    if _RUNTIME is None:
        _RUNTIME = SkillRuntime()
    return _RUNTIME


def refresh_skill_runtime() -> SkillRuntime:
    global _RUNTIME
    _RUNTIME = SkillRuntime()
    return _RUNTIME


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _split_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    text = markdown.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, markdown
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, markdown

    frontmatter_text = text[4:end]
    body = text[end + len("\n---\n") :]
    parsed: dict[str, str] = {}
    for line in frontmatter_text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        parsed[key.strip()] = value.strip().strip("\"'")
    return parsed, body


def _first_heading_or_line(markdown: str) -> str:
    for line in markdown.splitlines():
        clean = line.strip().lstrip("#").strip()
        if clean:
            return clean
    return ""


def _list_resources(skill_dir: Path) -> list[str]:
    resources: list[str] = []
    for root_name in sorted(RESOURCE_ROOTS):
        root = skill_dir / root_name
        if not root.exists():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            resources.append(path.relative_to(skill_dir).as_posix())
    return resources


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[truncated]"


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace("-", "_")
