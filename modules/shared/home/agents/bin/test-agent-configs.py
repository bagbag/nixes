#!/usr/bin/env python3
"""Validate shared skills and both generated custom-agent formats."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path


EXPLICIT_ONLY_SKILLS = {"architect", "autopilot", "retro", "supervisor"}
sys.dont_write_bytecode = True


def load_generator(root: Path):
    path = root / "bin" / "generate-agent-configs.py"
    spec = importlib.util.spec_from_file_location("agent_generator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parse_skill_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError(f"{path}: expected YAML frontmatter")

    metadata: dict[str, str] = {}
    lines = parts[1].strip("\n").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line or line[0].isspace() or ":" not in line:
            index += 1
            continue
        key, raw_value = line.split(":", 1)
        value = raw_value.strip().strip("\"'")
        if value in {">", ">-", "|", "|-"}:
            folded: list[str] = []
            index += 1
            while index < len(lines) and (
                not lines[index] or lines[index][0].isspace()
            ):
                folded.append(lines[index].strip())
                index += 1
            value = " ".join(part for part in folded if part)
        else:
            index += 1
        metadata[key] = value

    if set(metadata) != {"name", "description"}:
        raise ValueError(
            f"{path}: skill frontmatter must contain only name and description"
        )
    if metadata["name"] != path.parent.name:
        raise ValueError(f"{path}: skill name must match its directory")
    if not metadata["description"] or not parts[2].strip():
        raise ValueError(f"{path}: description and instructions must not be empty")
    return metadata


def validate_skills(root: Path) -> None:
    skills_dir = root / "skills"
    skill_files = sorted(skills_dir.glob("*/SKILL.md"))
    if not skill_files:
        raise ValueError(f"{skills_dir}: no skills found")

    names = {parse_skill_frontmatter(path)["name"] for path in skill_files}
    if len(names) != len(skill_files):
        raise ValueError(f"{skills_dir}: duplicate skill names")

    for name in EXPLICIT_ONLY_SKILLS:
        policy = skills_dir / name / "agents" / "openai.yaml"
        expected = "policy:\n  allow_implicit_invocation: false\n"
        if not policy.is_file() or policy.read_text(encoding="utf-8") != expected:
            raise ValueError(f"{policy}: missing explicit-only Codex policy")

    worker_arcs = skills_dir / "shared" / "worker-arcs.md"
    if not worker_arcs.is_file() or not worker_arcs.read_text(encoding="utf-8").strip():
        raise ValueError(f"{worker_arcs}: missing shared worker-arc convention")
    worker_arcs_path = "$HOME/.agents/skills/shared/worker-arcs.md"
    for name in ("autopilot", "supervisor"):
        instructions = (skills_dir / name / "SKILL.md").read_text(encoding="utf-8")
        if instructions.count(worker_arcs_path) != 1:
            raise ValueError(
                f"{name}: expected exactly one shared worker-arc reference"
            )


def validate_generated_agents(root: Path, generator) -> None:
    source = root / "definitions"
    codex = generator.expected_outputs(source, "codex")
    claude = generator.expected_outputs(source, "claude")

    expected_codex = {
        "build.toml",
        "craft.toml",
        "explorer.toml",
        "plan.toml",
        "review.toml",
        "scout.toml",
        "transform.toml",
        "verify.toml",
    }
    expected_claude = {
        "build.md",
        "craft.md",
        "Explore.md",
        "Plan.md",
        "review.md",
        "scout.md",
        "transform.md",
        "verify.md",
    }
    if set(codex) != expected_codex:
        raise ValueError(f"unexpected Codex agents: {sorted(codex)}")
    if set(claude) != expected_claude:
        raise ValueError(f"unexpected Claude agents: {sorted(claude)}")

    parsed = {filename: tomllib.loads(content) for filename, content in codex.items()}
    if len({agent["name"] for agent in parsed.values()}) != len(parsed):
        raise ValueError("duplicate effective Codex agent names")
    if parsed["verify.toml"]["sandbox_mode"] != "workspace-write":
        raise ValueError("verify must permit incidental verification artifacts")
    if "readonly-guard.sh" not in claude["Explore.md"]:
        raise ValueError("Claude Explore lost its readonly Bash hook")


def validate_multiline_and_optional_names(generator) -> None:
    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "sample.md"
        source.write_text(
            """---
name: sample
claude-name: Sample
codex-name: sampler
description: >-
  First line of a multiline description.
  Second line remains part of it.
effort: medium
codex-model: gpt-5.6-terra
codex-sandbox: read-only
---

First instruction.
Second instruction.
""",
            encoding="utf-8",
        )
        codex_name, codex_text = generator.render_codex_agent(source)
        claude_name, claude_text = generator.render_claude_agent(source)
        parsed = tomllib.loads(codex_text)
        if codex_name != "sampler.toml" or parsed["name"] != "sampler":
            raise ValueError("codex-name override failed")
        if claude_name != "Sample.md" or "name: Sample" not in claude_text:
            raise ValueError("claude-name override failed")
        if "Second line remains part of it." not in parsed["description"]:
            raise ValueError("multiline description was not preserved")
        if "Second instruction." not in parsed["developer_instructions"]:
            raise ValueError("multiline instructions were not preserved")


def run_hook(path: Path, payload: dict[str, object]) -> dict[str, object] | None:
    result = subprocess.run(
        ["bash", str(path)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def validate_hooks(root: Path) -> None:
    hooks = root / "hooks"
    stash = run_hook(
        hooks / "git-stash-guard.sh",
        {
            "hook_event_name": "PreToolUse",
            "turn_id": "test-turn",
            "tool_input": {"command": "git stash push"},
        },
    )
    if stash is None or stash["hookSpecificOutput"]["permissionDecision"] != "deny":
        raise ValueError("git-stash-guard did not deny an unapproved stash")

    approved_stash = run_hook(
        hooks / "git-stash-guard.sh",
        {
            "hook_event_name": "PreToolUse",
            "turn_id": "test-turn",
            "tool_input": {"command": "AGENT_ALLOW_STASH=1 git stash push"},
        },
    )
    if approved_stash is not None:
        raise ValueError("git-stash-guard did not accept Codex's approved marker")

    readonly = run_hook(
        hooks / "readonly-guard.sh",
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {"command": "touch forbidden"},
        },
    )
    if readonly is None or readonly["hookSpecificOutput"]["permissionDecision"] != "deny":
        raise ValueError("readonly-guard did not deny a mutating command")

    readonly_search = run_hook(
        hooks / "readonly-guard.sh",
        {
            "hook_event_name": "PreToolUse",
            "tool_input": {"command": "rg pattern source"},
        },
    )
    if readonly_search is not None:
        raise ValueError("readonly-guard blocked a read-only search")

    compact = run_hook(
        hooks / "compact-reorient.sh",
        {"hook_event_name": "SessionStart", "source": "compact"},
    )
    context = (
        compact["hookSpecificOutput"].get("additionalContext", "")
        if compact is not None
        else ""
    )
    if "re-orient" not in context or "agent instructions" not in context:
        raise ValueError("compact-reorient did not emit recovery context")


def main() -> int:
    root = (
        Path(sys.argv[1]).resolve()
        if len(sys.argv) > 1
        else Path(__file__).resolve().parents[1]
    )
    generator = load_generator(root)
    validate_skills(root)
    validate_generated_agents(root, generator)
    validate_multiline_and_optional_names(generator)
    validate_hooks(root)
    print("shared agent and skill validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
