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


EXPLICIT_ONLY_SKILLS = {"autopilot", "retro", "supervisor"}
IMPLICIT_SKILLS = {"architect", "define-goal", "second-opinion"}
sys.dont_write_bytecode = True


def load_generator(root: Path):
    path = root / "bin" / "generate-agent-configs.py"
    spec = importlib.util.spec_from_file_location("agent_generator", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_skill_expander(root: Path):
    path = root / "bin" / "expand-skills.py"
    spec = importlib.util.spec_from_file_location("skill_expander", path)
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


def skill_frontmatter_bytes(path: Path) -> bytes:
    lines = path.read_bytes().splitlines(keepends=True)
    if not lines or lines[0].rstrip(b"\r\n") != b"---":
        raise ValueError(f"{path}: expected YAML frontmatter")

    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip(b"\r\n") == b"---":
            return b"".join(lines[: index + 1])
    raise ValueError(f"{path}: unterminated YAML frontmatter")


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

    for name in IMPLICIT_SKILLS:
        policy = skills_dir / name / "agents" / "openai.yaml"
        expected = "policy:\n  allow_implicit_invocation: true\n"
        if not policy.is_file() or policy.read_text(encoding="utf-8") != expected:
            raise ValueError(f"{policy}: missing implicit Codex policy")

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

    define_goal_owners = (
        skills_dir / "shared" / "worker-arcs.md",
        skills_dir / "supervisor" / "SKILL.md",
        skills_dir / "autopilot" / "SKILL.md",
    )
    for path in define_goal_owners:
        if "`define-goal`" not in path.read_text(encoding="utf-8"):
            raise ValueError(f"{path}: missing define-goal integration")

    path_contracts = {
        root / "AGENTS.md": (
            "docs/<topic-slug>/",
            ".scratch/<topic-slug>/<arc-slug>/",
        ),
        skills_dir / "shared" / "board-files.md": (
            ".scratch/<topic-slug>/<arc-slug>/board.md",
            "docs/<topic-slug>/",
            "log.md",
            "history/",
        ),
        skills_dir / "shared" / "durable-docs.md": (
            "docs/<topic-slug>/",
            "index.md",
        ),
        skills_dir / "handover" / "SKILL.md": (
            ".scratch/<topic-slug>/<arc-slug>/handover.md",
        ),
        skills_dir / "supervisor" / "SKILL.md": (
            ".scratch/<topic-slug>/<arc-slug>/board.md",
            "docs/<topic-slug>/",
        ),
        skills_dir / "autopilot" / "SKILL.md": (
            ".scratch/<topic-slug>/<arc-slug>/board.md",
            "docs/<topic-slug>/",
        ),
    }
    for path, required in path_contracts.items():
        text = path.read_text(encoding="utf-8")
        missing = [marker for marker in required if marker not in text]
        if missing:
            raise ValueError(f"{path}: missing path contract {missing}")


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
        "second-opinion.toml",
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
        "second-opinion.md",
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
    second_opinion = parsed["second-opinion.toml"]
    if second_opinion["model"] != "gpt-5.6-sol":
        raise ValueError("second-opinion must use Sol")
    if second_opinion["sandbox_mode"] != "read-only":
        raise ValueError("second-opinion must remain read-only")
    if "readonly-guard.sh" not in claude["Explore.md"]:
        raise ValueError("Claude Explore lost its readonly Bash hook")
    if "readonly-guard.sh" not in claude["second-opinion.md"]:
        raise ValueError("Claude second-opinion lost its readonly Bash hook")


def validate_skill_expander(root: Path, expander) -> None:
    with tempfile.TemporaryDirectory() as directory:
        temporary = Path(directory)
        source = temporary / "source"
        output = temporary / "output"
        (source / "shared").mkdir(parents=True)
        (source / "sample").mkdir()
        (source / "shared" / "nested.md").write_text(
            "Nested rule.\n", encoding="utf-8"
        )
        (source / "shared" / "rule.md").write_text(
            "Rule start.\n<!-- @include shared/nested.md -->\nRule end.\n",
            encoding="utf-8",
        )
        skill = source / "sample" / "SKILL.md"
        frontmatter = "---\nname: sample\ndescription: Sample skill.\n---\n"
        skill.write_text(
            frontmatter + "\n<!-- @include shared/rule.md -->\n",
            encoding="utf-8",
        )
        binary = source / "sample" / "asset.bin"
        binary.write_bytes(b"\x00skill-asset\xff")

        expander.expand_tree(source, output)
        rendered = (output / "sample" / "SKILL.md").read_text(encoding="utf-8")
        if not rendered.startswith(frontmatter):
            raise ValueError("skill expansion changed YAML frontmatter")
        if "Rule start.\nNested rule.\nRule end." not in rendered:
            raise ValueError("nested skill include was not expanded")
        if "@include" in rendered:
            raise ValueError("rendered skill contains an include marker")
        if (output / "sample" / "asset.bin").read_bytes() != binary.read_bytes():
            raise ValueError("skill expansion changed a copied asset")

        invalid = temporary / "invalid"
        invalid.mkdir()
        cases = {
            "missing.md": "<!-- @include shared/missing.md -->\n",
            "escape.md": "<!-- @include ../outside.md -->\n",
            "frontmatter.md": "---\n<!-- @include shared/rule.md -->\n---\n",
            "malformed.md": "<!-- @include shared/rule.md-->",
        }
        for name, content in cases.items():
            path = source / name
            path.write_text(content, encoding="utf-8")
            try:
                expander.expand_markdown(path, source.resolve())
            except ValueError:
                pass
            else:
                raise ValueError(f"skill expander accepted invalid case: {name}")

        cycle_a = source / "shared" / "cycle-a.md"
        cycle_b = source / "shared" / "cycle-b.md"
        cycle_a.write_text(
            "<!-- @include shared/cycle-b.md -->\n", encoding="utf-8"
        )
        cycle_b.write_text(
            "<!-- @include shared/cycle-a.md -->\n", encoding="utf-8"
        )
        try:
            expander.expand_markdown(cycle_a, source.resolve())
        except ValueError as error:
            if "include cycle" not in str(error):
                raise
        else:
            raise ValueError("skill expander accepted an include cycle")


def validate_rendered_skills(root: Path, expander) -> None:
    with tempfile.TemporaryDirectory() as directory:
        temporary_root = Path(directory)
        rendered_skills = temporary_root / "skills"
        expander.expand_tree(root / "skills", rendered_skills)
        (temporary_root / "AGENTS.md").write_text(
            (root / "AGENTS.md").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        validate_skills(temporary_root)

        source_skills = root / "skills"
        for source in sorted(source_skills.glob("*/SKILL.md")):
            rendered = rendered_skills / source.relative_to(source_skills)
            if skill_frontmatter_bytes(source) != skill_frontmatter_bytes(rendered):
                raise ValueError(f"{source}: rendered frontmatter changed")

        marker = "<!-- @include shared/decision-discipline.md -->"
        include_owners = (
            source_skills / "architect" / "SKILL.md",
            source_skills / "second-opinion" / "SKILL.md",
            source_skills / "shared" / "worker-arcs.md",
        )
        for path in include_owners:
            if path.read_text(encoding="utf-8").count(marker) != 1:
                raise ValueError(f"{path}: expected one decision-discipline include")

        for name in ("autopilot", "supervisor"):
            path = source_skills / name / "SKILL.md"
            if marker in path.read_text(encoding="utf-8"):
                raise ValueError(f"{path}: must inherit decision discipline via worker-arcs")

        canonical_rules = (
            "authoritative domain state from operational execution state",
            "timeout, routing, transaction, recovery, observability",
            "consequential architectural property before descending into an implementation preference",
            "Apply reconciliation only when the disagreement could materially change",
            "Treat position-swapping without resolved premises as continued disagreement",
            "Do not force consensus or decide by majority",
        )
        rendered_owners = (
            rendered_skills / "architect" / "SKILL.md",
            rendered_skills / "second-opinion" / "SKILL.md",
            rendered_skills / "shared" / "worker-arcs.md",
        )
        for path in rendered_owners:
            normalized = " ".join(path.read_text(encoding="utf-8").split())
            for rule in canonical_rules:
                if normalized.count(rule) != 1:
                    raise ValueError(
                        f"{path}: decision rule was not rendered once: {rule}"
                    )

        rendered_architect = rendered_skills / "architect" / "SKILL.md"
        architect_text = rendered_architect.read_text(encoding="utf-8")
        if architect_text.count("Apply the shared decision discipline above") != 2:
            raise ValueError(
                f"{rendered_architect}: expected DESIGN and REVIEW discipline pointers"
            )

        rendered_second_opinion = (
            rendered_skills / "second-opinion" / "SKILL.md"
        )
        second_opinion_text = rendered_second_opinion.read_text(encoding="utf-8")
        if second_opinion_text.count("Apply the shared discipline only when") != 1:
            raise ValueError(
                f"{rendered_second_opinion}: missing reconciliation ceremony gate"
            )

        for path in sorted(rendered_skills.glob("*/SKILL.md")):
            headings = [
                line for line in path.read_text(encoding="utf-8").splitlines()
                if line.startswith("# ")
            ]
            if len(headings) != 1:
                raise ValueError(f"{path}: expected exactly one H1, got {headings}")

        worker_arcs = rendered_skills / "shared" / "worker-arcs.md"
        worker_headings = [
            line for line in worker_arcs.read_text(encoding="utf-8").splitlines()
            if line.startswith("# ")
        ]
        if len(worker_headings) != 1:
            raise ValueError(
                f"{worker_arcs}: expected exactly one H1, got {worker_headings}"
            )

        unresolved = [
            path
            for path in rendered_skills.rglob("*.md")
            if "<!-- @include " in path.read_text(encoding="utf-8")
        ]
        if unresolved:
            raise ValueError(f"rendered skills contain include markers: {unresolved}")


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
    expander = load_skill_expander(root)
    validate_skills(root)
    validate_skill_expander(root, expander)
    validate_rendered_skills(root, expander)
    validate_generated_agents(root, generator)
    validate_multiline_and_optional_names(generator)
    validate_hooks(root)
    print("shared agent and skill validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
