#!/usr/bin/env python3
"""Validate shared skills and both generated custom-agent formats."""

from __future__ import annotations

import ast
import hashlib
import importlib.machinery
import itertools
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml


# User-only: Claude `disable-model-invocation: true` plus Codex's implicit-invocation policy.
USER_ONLY_SKILLS = {"ask-advisor", "board-migrate", "question-me", "release-round", "retro", "role", "explain", "start-round", "round-intake"}
EXPLICIT_ONLY_SKILLS = USER_ONLY_SKILLS
ROLE_PROTOCOLS = ("decide", "plan", "work", "review", "unattended")
RETIRED_SKILL_PATHS = (
    "goal-lead", "goal-agent", "supervisor", "autopilot", "beads-migrate",
    "shared/goal-relay.md", "shared/worker-arcs.md",
)
RETIRED_REFERENCES = re.compile(
    r"skills/(goal-lead|goal-agent|supervisor|autopilot|beads-migrate)/|worker-arcs\.md|goal-relay\.md|board-health"
)
IMPLICIT_SKILLS = {"architect", "challenge-rulings", "define-goal", "explore-options", "ground", "second-opinion", "staged-review",
                   "step-back"}
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


def parse_skill_frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError(f"{path}: expected YAML frontmatter")

    metadata = yaml.safe_load(parts[1])
    if not isinstance(metadata, dict):
        raise ValueError(f"{path}: expected a frontmatter mapping")
    for field in ("name", "description"):
        if not isinstance(metadata.get(field), str) or not metadata[field].strip():
            raise ValueError(f"{path}: {field} must be a nonempty string")
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


def validate_invocation_policy(path: Path, expected: bool) -> None:
    config = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(config, dict):
        raise ValueError(f"{path}: expected a metadata mapping")
    policy = config.get("policy", {})
    if not isinstance(policy, dict):
        raise ValueError(f"{path}: expected a policy mapping")
    if policy.get("allow_implicit_invocation", True) is not expected:
        raise ValueError(f"{path}: unexpected implicit invocation policy")


def validate_policy_semantics() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "openai.yaml"
        validate_invocation_policy(path, True)
        for value in (True, False):
            path.write_text(
                "# Invocation policy\ninterface:\n  display_name: Example\n"
                f"policy: {{allow_implicit_invocation: {str(value).lower()}}}\n",
                encoding="utf-8",
            )
            validate_invocation_policy(path, value)
            try:
                validate_invocation_policy(path, not value)
            except ValueError:
                pass
            else:
                raise ValueError("policy validation accepted the wrong invocation mode")
        path.write_text('policy: {allow_implicit_invocation: "false"}\n', encoding="utf-8")
        try:
            validate_invocation_policy(path, False)
        except ValueError:
            pass
        else:
            raise ValueError("policy validation accepted a string in place of a boolean")


def validate_skills(root: Path) -> None:
    skills_dir = root / "skills"
    skill_files = sorted(skills_dir.glob("*/SKILL.md"))
    if not skill_files:
        raise ValueError(f"{skills_dir}: no skills found")

    names = {parse_skill_frontmatter(path)["name"] for path in skill_files}
    if len(names) != len(skill_files):
        raise ValueError(f"{skills_dir}: duplicate skill names")

    for name in EXPLICIT_ONLY_SKILLS | IMPLICIT_SKILLS:
        policy = skills_dir / name / "agents" / "openai.yaml"
        validate_invocation_policy(policy, name in IMPLICIT_SKILLS)
    for name in USER_ONLY_SKILLS:
        if parse_skill_frontmatter(skills_dir / name / "SKILL.md").get("disable-model-invocation") is not True:
            raise ValueError(f"{name}: user-only skill lacks disable-model-invocation: true")

    # role/SKILL.md owns the role -> protocol mapping; protocols load by $HOME path.
    role = (skills_dir / "role" / "SKILL.md").read_text(encoding="utf-8")
    for protocol in ROLE_PROTOCOLS:
        path = skills_dir / "role" / "protocols" / f"{protocol}.md"
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            raise ValueError(f"{path}: missing role protocol")
        if f"$HOME/.agents/skills/role/protocols/{protocol}.md" not in role:
            raise ValueError(f"role/SKILL.md: does not name the {protocol} protocol by path")
    question_format = skills_dir / "shared" / "question-format.md"
    if not question_format.is_file() or not question_format.read_text(encoding="utf-8").strip():
        raise ValueError(f"{question_format}: missing shared question format")
    for retired in RETIRED_SKILL_PATHS:
        if (skills_dir / retired).exists():
            raise ValueError(f"{skills_dir / retired}: retired by /role")
    for path in sorted([*skills_dir.rglob("*.md"), *(root / "definitions").glob("*.md"), *(root / "hooks").glob("*.sh"),
                        root / "AGENTS.md", *[path for path in (root / "README.md",) if path.is_file()]]):
        match = RETIRED_REFERENCES.search(path.read_text(encoding="utf-8"))
        if match:
            raise ValueError(f"{path}: references retired {match.group(0)}")

    path_contracts = {
        root / "AGENTS.md": (
            "$HOME/.agents/skills/shared/project-memory.md",
            "$HOME/.agents/bin/scratch dir",
        ),
        skills_dir / "shared" / "project-memory.md": (
            "`scratch dir`",
            "history/",
            "docs/<topic-slug>/",
            "docs/goals.md",
            "docs/<topic-slug>/goals.md",
            "index.md",
        ),
        skills_dir / "role" / "protocols" / "plan.md": (
            "readable title",
            "`topic:<topic-slug>`",
            "$HOME/.agents/skills/shared/project-memory.md",
            "`define-goal`",
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
        "architect.toml",
        "build.toml",
        "craft.toml",
        "deep-review.toml",
        "explorer.toml",
        "option-explorer.toml",
        "plan.toml",
        "cr-refresh.toml",
        "review.toml",
        "scout.toml",
        "second-opinion.toml",
        "transform.toml",
        "verify.toml",
    }
    expected_claude = {
        "architect.md",
        "build.md",
        "craft.md",
        "deep-review.md",
        "Explore.md",
        "option-explorer.md",
        "Plan.md",
        "cr-refresh.md",
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

    # Source comparison catches omissions shared by both adapters.
    expander = load_skill_expander(root)
    for path in sorted(source.glob("*.md")):
        _, frontmatter, body = expander.expand_markdown(path, root / "skills").split("---", 2)
        metadata = yaml.safe_load(frontmatter)
        codex_name = metadata.get("codex-name", metadata["name"])
        claude_name = metadata.get("claude-name", metadata["name"])
        codex_agent = parsed[f"{codex_name}.toml"]
        _, claude_frontmatter, claude_body = claude[f"{claude_name}.md"].split("---", 2)
        claude_agent = yaml.safe_load(claude_frontmatter)
        if codex_agent["name"] != codex_name or claude_agent["name"] != claude_name:
            raise ValueError(f"{path}: adapter changed role identity")
        for target, instructions, description, effort in (
            ("codex", codex_agent["developer_instructions"],
             codex_agent["description"], codex_agent["model_reasoning_effort"]),
            ("claude", claude_body, claude_agent["description"], claude_agent["effort"]),
        ):
            if instructions.strip() != body.strip():
                raise ValueError(f"{path}: {target} changed shared instructions")
            if description.split() != metadata["description"].split():
                raise ValueError(f"{path}: {target} changed shared description")
            if effort != metadata.get(f"{target}-effort", metadata["effort"]):
                raise ValueError(f"{path}: {target} changed resolved effort")

    # r17-q103: one review method and one reuse check, expanded into both runtimes' outputs.
    method = (root / "skills" / "shared" / "review-method.md").read_text(encoding="utf-8")
    reuse = (root / "skills" / "shared" / "reuse-check.md").read_text(encoding="utf-8")
    reuse_lines = [line for line in reuse.splitlines() if line.strip()]
    method_lines = [line for line in method.splitlines() if line.strip() and "@include" not in line]
    if "<!-- @include shared/reuse-check.md -->" not in method:
        raise ValueError("review-method.md must take the reuse check by include")
    for name in ("review", "deep-review", "verify"):
        source_text = (source / f"{name}.md").read_text(encoding="utf-8")
        if "shared/" not in source_text.split("---", 2)[2]:
            raise ValueError(f"{name}: body must take shared text by include")
        for target, text in (("codex", parsed[f"{name}.toml"]["developer_instructions"]),
                             ("claude", claude[f"{name}.md"])):
            if "@include" in text:
                raise ValueError(f"{name}: {target} output keeps an include marker")
            expected = reuse_lines if name == "verify" else [*method_lines, *reuse_lines]
            missing = [line for line in expected if line not in text]
            if missing:
                raise ValueError(f"{name}: {target} output lacks shared text {missing[:1]}")
    for target, outputs, suffix in (("codex", parsed, ".toml"), ("claude", claude, ".md")):
        def instructions(name: str) -> str:
            return outputs[name + suffix]["developer_instructions"] if target == "codex" else claude[name + suffix].split("---", 2)[2]
        if instructions("review") != instructions("deep-review"):
            raise ValueError(f"{target}: review and deep-review bodies differ")

    specialists = {
        "architect": "architect",
        "deep-review": "deep-review",
        "option-explorer": "option-explorer",
        "plan": "Plan",
        "review": "review",
        "second-opinion": "second-opinion",
        "verify": "verify",
    }
    for codex_name, claude_name in specialists.items():
        if parsed[f"{codex_name}.toml"]["sandbox_mode"] != "workspace-write":
            raise ValueError(f"{codex_name} must permit assigned artifact writes")
        document = claude[f"{claude_name}.md"]
        metadata = yaml.safe_load(document.split("---", 2)[1])
        if not {"Write", "Edit"}.issubset(metadata["tools"].split(", ")):
            raise ValueError(f"Claude {claude_name} must permit artifact writes and edits")
        # Reviewers run gates and fix findings (r13-q57); the other specialists stay read-only in Bash.
        guarded = codex_name not in {"review", "deep-review", "verify"}
        if guarded != ("readonly-guard.sh" in document):
            raise ValueError(f"Claude {claude_name} readonly Bash hook must be {'on' if guarded else 'off'}")

    for codex_name, claude_name in {"scout": "scout", "explorer": "Explore", "cr-refresh": "cr-refresh"}.items():
        if parsed[f"{codex_name}.toml"]["sandbox_mode"] != "read-only":
            raise ValueError(f"{codex_name} must remain response-only and read-only")
        document = claude[f"{claude_name}.md"]
        metadata = yaml.safe_load(document.split("---", 2)[1])
        if {"Write", "Edit"}.intersection(metadata["tools"].split(", ")):
            raise ValueError(f"Claude {claude_name} must remain response-only")
        if "readonly-guard.sh" not in document:
            raise ValueError(f"Claude {claude_name} lost its readonly Bash hook")


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


SHARED_READ = re.compile(r"\$HOME/\.agents/skills/((?:shared|role/protocols)/[\w.-]+\.md)")
MARKDOWN_LINK = re.compile(r"\]\((?P<target>[^)#\s]*)(?:#(?P<anchor>[^)\s]+))?\)")


def heading_anchors(text: str) -> set[str]:
    anchors = set()
    for heading in re.findall(r"^#+ (.+)$", text, re.M):
        slug = re.sub(r"[^\w\- ]", "", heading.strip().lower())
        anchors.add(slug.replace(" ", "-"))
    return anchors


def include_closure(path: Path, skills: Path, expander) -> set[Path]:
    found: set[Path] = set()
    pending = [path]
    while pending:
        text = pending.pop().read_text(encoding="utf-8")
        for line in text.splitlines():
            match = expander.INCLUDE_MARKER.match(line)
            if match:
                target = (skills / match.group("path").strip()).resolve()
                if target not in found:
                    found.add(target)
                    pending.append(target)
    return found


def check_skill_loading(skills: Path, expander) -> None:
    """Links target loaded content: in-file anchors for included files,
    file links only to files the reader includes or reads by $HOME path."""
    skills = skills.resolve()
    rendered: dict[Path, str] = {}

    def render(path: Path) -> str:
        if path not in rendered:
            rendered[path] = expander.expand_markdown(path, skills)
        return rendered[path]

    for skill in sorted(skills.glob("*/SKILL.md")):
        included = include_closure(skill, skills, expander)
        available = set(included)
        pending = [skill, *included]
        while pending:
            for name in SHARED_READ.findall(pending.pop().read_text(encoding="utf-8")):
                target = (skills / name).resolve()
                if not target.is_file():
                    raise ValueError(f"{skill}: reads missing {name}")
                for loaded in (target, *include_closure(target, skills, expander)):
                    if loaded not in available:
                        available.add(loaded)
                        pending.append(loaded)

        for match in MARKDOWN_LINK.finditer(skill.read_text(encoding="utf-8")):
            raw, anchor = match.group("target"), match.group("anchor")
            if not raw or "://" in raw:
                continue
            target = (skill.parent / raw).resolve()
            if target in included:
                raise ValueError(f"{skill}: link into included {raw}; use an in-file anchor")
            if target not in available:
                raise ValueError(
                    f"{skill}: link to {raw}, which it neither includes nor reads by $HOME path"
                )

    for path in sorted(skills.rglob("*.md")):
        text = render(path.resolve())
        own = heading_anchors(text)
        for match in MARKDOWN_LINK.finditer(text):
            raw, anchor = match.group("target"), match.group("anchor")
            if not anchor or "://" in raw:
                continue
            target = (path.parent / raw).resolve() if raw else None
            if target is not None and not target.is_file():
                raise ValueError(f"{path}: link to missing {raw}")
            anchors = own if target is None else heading_anchors(render(target))
            if anchor not in anchors:
                raise ValueError(f"{path}: unresolved anchor {raw}#{anchor}")


def validate_skill_loading(root: Path, expander) -> None:
    check_skill_loading(root / "skills", expander)
    with tempfile.TemporaryDirectory() as directory:
        skills = Path(directory)
        (skills / "shared").mkdir()
        (skills / "sample").mkdir()
        (skills / "shared" / "part.md").write_text("## Part\n", encoding="utf-8")
        (skills / "shared" / "other.md").write_text("## Other\n", encoding="utf-8")
        skill = skills / "sample" / "SKILL.md"
        frontmatter = "---\nname: sample\ndescription: Sample.\n---\n"
        cases = {
            "included file link": "[P](../shared/part.md#part)\n<!-- @include shared/part.md -->\n",
            "unloaded file link": "[O](../shared/other.md#other)\n",
            "unresolved anchor": "[P](#missing)\n<!-- @include shared/part.md -->\n",
        }
        for name, body in cases.items():
            skill.write_text(frontmatter + body, encoding="utf-8")
            try:
                check_skill_loading(skills, expander)
            except ValueError:
                pass
            else:
                raise ValueError(f"loading validation accepted {name}")
        skill.write_text(
            frontmatter
            + "Read `$HOME/.agents/skills/shared/other.md`: [O](../shared/other.md#other).\n"
            + "[P](#part)\n<!-- @include shared/part.md -->\n",
            encoding="utf-8",
        )
        check_skill_loading(skills, expander)


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

        marker = "<!-- @include shared/decision-protocol.md -->"
        include_owners = (
            source_skills / "architect" / "SKILL.md",
            source_skills / "second-opinion" / "SKILL.md",
        )
        for path in include_owners:
            if path.read_text(encoding="utf-8").count(marker) != 1:
                raise ValueError(f"{path}: expected one decision-protocol include")

        protocol = expander.expand_markdown(
            source_skills / "shared" / "decision-protocol.md", source_skills.resolve()
        ).strip()
        for source in include_owners:
            rendered = rendered_skills / source.relative_to(source_skills)
            if rendered.read_text(encoding="utf-8").count(protocol) != 1:
                raise ValueError(f"{rendered}: shared decision protocol was not preserved once")

        for path in sorted(rendered_skills.glob("*/SKILL.md")):
            headings = [
                line for line in path.read_text(encoding="utf-8").splitlines()
                if line.startswith("# ")
            ]
            if len(headings) != 1:
                raise ValueError(f"{path}: expected exactly one H1, got {headings}")

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


def validate_agent_includes(generator) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "definitions").mkdir()
        (root / "skills" / "shared").mkdir(parents=True)
        (root / "skills" / "shared" / "rule.md").write_text("Shared rule.\n", encoding="utf-8")
        source = root / "definitions" / "sample.md"
        head = "---\nname: sample\ndescription: Sample.\neffort: medium\ncodex-model: m\ncodex-sandbox: read-only\n---\n\n"
        source.write_text(head + "Before.\n<!-- @include shared/rule.md -->\nAfter.\n", encoding="utf-8")
        _, codex_text = generator.render_codex_agent(source)
        _, claude_text = generator.render_claude_agent(source)
        if tomllib.loads(codex_text)["developer_instructions"] != "Before.\nShared rule.\nAfter.\n" or "Shared rule." not in claude_text:
            raise ValueError("agent include was not expanded for both runtimes")
        for text in (
            head + "<!-- @include shared/missing.md -->\n",
            head + "<!-- @include ../outside.md -->\n",
            head.replace("effort: medium", "effort: medium\n<!-- @include shared/rule.md -->") + "x\n",
        ):
            source.write_text(text, encoding="utf-8")
            try:
                generator.render_claude_agent(source)
            except ValueError:
                continue
            raise ValueError(f"invalid agent include accepted: {text!r}")


def validate_effort_overrides(generator) -> None:
    def write(directory: str, extra: str) -> Path:
        source = Path(directory) / "sample.md"
        source.write_text(
            f"""---
name: sample
description: Sample.
effort: medium
{extra}codex-model: gpt-5.6-terra
codex-sandbox: read-only
---

Instruction.
""",
            encoding="utf-8",
        )
        return source

    def efforts(source: Path) -> tuple[str, str]:
        _, codex_text = generator.render_codex_agent(source)
        _, claude_text = generator.render_claude_agent(source)
        claude_frontmatter = yaml.safe_load(claude_text.split("---", 2)[1])
        return (
            tomllib.loads(codex_text)["model_reasoning_effort"],
            claude_frontmatter["effort"],
        )

    with tempfile.TemporaryDirectory() as directory:
        if efforts(write(directory, "codex-effort: ultra\n")) != ("ultra", "medium"):
            raise ValueError("codex-effort override must affect only Codex")
        if efforts(write(directory, "claude-effort: max\n")) != ("medium", "max"):
            raise ValueError("claude-effort override must affect only Claude")
        for extra in ("claude-effort: ultra\n", "codex-effort: minimal\n"):
            try:
                efforts(write(directory, extra))
            except ValueError:
                continue
            raise ValueError(f"unsupported per-target effort accepted: {extra!r}")
        shared_ultra = write(directory, "").read_text(encoding="utf-8")
        shared_ultra = shared_ultra.replace("effort: medium", "effort: ultra")
        (Path(directory) / "sample.md").write_text(shared_ultra, encoding="utf-8")
        try:
            generator.render_claude_agent(Path(directory) / "sample.md")
        except ValueError:
            pass
        else:
            raise ValueError("shared effort unsupported by Claude was accepted")
        generator.render_codex_agent(Path(directory) / "sample.md")


def run_hook(
    path: Path,
    payload: dict[str, object],
    env: dict[str, str] | None = None,
) -> dict[str, object] | None:
    result = subprocess.run(
        ["bash", str(path)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, **(env or {})},
    )
    return json.loads(result.stdout) if result.stdout.strip() else None


def hook_context(result: dict[str, object] | None) -> str:
    return result["hookSpecificOutput"].get("additionalContext", "") if result is not None else ""


SESSION = "01a1641b-8b02-7501-984d-a93f189276fd"
SESSION_ACTOR = "189276fd"


def as_session(session: str, tool: str = "claude") -> dict[str, str]:
    """The environment an agent session's commands see."""
    if tool == "codex":
        return {"CLAUDE_CODE_SESSION_ID": "", "CODEX_SESSION_ID": session, "CODEX_THREAD_ID": session}
    return {"CLAUDE_CODE_SESSION_ID": session, "CODEX_SESSION_ID": "", "CODEX_THREAD_ID": ""}


def session_env(state_dir: str) -> dict[str, str]:
    # Each fixture chooses its identity independently of the invoking agent.
    return {
        "CLAUDE_CODE_SESSION_ID": "",
        "CODEX_THREAD_ID": "",
        "CODEX_SESSION_ID": "",
        "AGENT_SESSION_STATE_DIR": state_dir,
    }


def fake_board(base: Path, name: str = "proj", printed: Path | None = None) -> tuple[Path, dict[str, str]]:
    """A folder with a `.beads` and the environment of a `bd` on PATH whose `where` names it (first line the
    .beads path, as bd prints it, through `printed` when given); other bd calls fail. Returns the folder and the environment."""
    folder = base / name
    (folder / ".beads").mkdir(parents=True)
    bin_dir = base / f"{name}-bin"
    bin_dir.mkdir()
    fake = bin_dir / "bd"
    fake.write_text(f'#!/bin/sh\n[ "$1" = where ] && {{ echo "{printed or folder}/.beads"; echo "  database: x"; exit 0; }}\nexit 1\n', encoding="utf-8")
    fake.chmod(0o755)
    return folder, {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}


def validate_session_registry(root: Path) -> None:
    script = root / "bin" / "session"

    def run(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(script), *args], text=True, capture_output=True,
                              env={**os.environ, **env})

    with tempfile.TemporaryDirectory() as state_dir:
        env = session_env(state_dir)
        run("activate", "lead", env={**env, **as_session(SESSION)}).check_returncode()
        if run("get", SESSION, env=env).stdout.strip() != "lead":
            raise ValueError("session lost a registered lead")
        shown = json.loads(run("show", SESSION, env=env).stdout)
        if (shown["role"], shown["pulls"], shown["actor"], shown["tool"]) != ("lead", [], SESSION_ACTOR, "claude"):
            raise ValueError(f"session show: {shown}")

        # The bundle runs on macOS's bash 3.2, where an empty array under `set -u` is an unbound variable: the verbs
        # hooks call must work there for a session without pulls or workers (skipped where no bash 3.2 exists).
        old_bash = "/bin/bash"
        if os.path.exists(old_bash) and subprocess.run([old_bash, "-c", "((BASH_VERSINFO[0] < 4))"]).returncode == 0:
            with tempfile.TemporaryDirectory() as old_dir:
                old_env = {**os.environ, **session_env(old_dir), **as_session(SESSION)}
                for args in (("activate", "lead"), ("get", SESSION), ("show", SESSION), ("list",), ("actor",), ("alive",),
                             ("ended",), ("state-dir",)):
                    done = subprocess.run([old_bash, str(script), *args], text=True, capture_output=True, env=old_env)
                    if done.returncode or done.stderr:
                        raise ValueError(f"session {' '.join(args)} fails on bash 3.2: {done.returncode} {done.stderr}")

        # r15-q88: `help` lists every verb with an example; a bare call prints the same and exits 0.
        helped, bare = run("help", env=env), run(env=env)
        if helped.returncode or bare.returncode or helped.stdout != bare.stdout or helped.stderr:
            raise ValueError(f"session help and a bare call must print the same on stdout and exit 0: {helped} {bare}")
        for verb in ("activate", "set-workers", "actor", "get", "show", "list", "ended", "state-dir", "alive", "session-active",
                     "worker-started", "worker-active", "worker-ended", "help"):
            if not re.search(rf"^\s*session {verb}\b", helped.stdout, re.M):
                raise ValueError(f"session help lacks {verb}:\n{helped.stdout}")

        other = "0a1b2c3d-0000-4000-8000-00000000beef"
        run("activate", "agent", "--pulls", "review,plan", env={**env, **as_session(other, "codex")}).check_returncode()
        if (json.loads(run("show", other, env=env).stdout)["pulls"], json.loads(run("show", other, env=env).stdout)["tool"]) \
                != (["plan", "review"], "codex"):
            raise ValueError("session did not store the Codex agent's pulls in canonical order")

        # Every role takes pulls (presets add to them); a preset role registers none unless given.
        for role, given, stored in (("lead", "implement,plan", ["plan", "implement"]), ("solo", "review", ["review"]), ("autopilot", "design", ["design"])):
            run("activate", role, "--pulls", given, env={**env, **as_session(other)}).check_returncode()
            if json.loads(run("show", other, env=env).stdout)["pulls"] != stored:
                raise ValueError(f"session did not store {role}'s pulls {given}")
        run("activate", "solo", env={**env, **as_session(SESSION)}).check_returncode()
        changed = json.loads(run("show", SESSION, env=env).stdout)
        if changed["role"] != "solo" or changed["actor"] != SESSION_ACTOR:
            raise ValueError("a role change must keep the session's actor")

        rejected = (
            (("activate", "agent"), as_session("abcdefgh-1")),
            (("activate", "lead", "--pulls", "plan,deploy"), as_session("abcdefgh-1")),
            (("activate", "agent", "--pulls", "plan,deploy"), as_session("abcdefgh-1")),
            (("activate", "goal-lead"), as_session("abcdefgh-1")),
            (("activate", "lead", "--session", "abcdefgh-1"), as_session("abcdefgh-1")),
            (("activate", "lead"), {}),
            (("activate", "lead"), as_session("short")),
            (("activate", "lead"), as_session("../escape-1")),
            (("show",), {}),
            (("get",), {}),
        )
        for args, identity in rejected:
            if run(*args, env={**env, **identity}).returncode == 0:
                raise ValueError(f"session accepted {args} as {identity}")

        # actor: the session's, plus a Codex worker's own thread; Codex wins when both are set.
        for identity, expected in ((as_session(SESSION), SESSION_ACTOR),
                                   ({**as_session(SESSION, "codex"), "CODEX_THREAD_ID": other}, f"{SESSION_ACTOR}/{other[-8:]}"),
                                   ({**as_session(SESSION, "codex"), "CLAUDE_CODE_SESSION_ID": other}, SESSION_ACTOR)):
            if run("actor", env={**env, **identity}).stdout.strip() != expected:
                raise ValueError(f"session actor for {identity}: expected {expected}")
        if run("actor", env=env).returncode == 0:
            raise ValueError("session actor invented an actor outside an agent session")
        if sorted(path.name for path in Path(state_dir).iterdir() if path.name != ".lock") != sorted([f"{SESSION}.json", f"{other}.json"]):
            raise ValueError("a rejected activation wrote the registry")

        if run("get", "abcdefgh-unknown", env=env).stdout.strip():
            raise ValueError("session invented a role")
        unknown = json.loads(run("show", "abcdefgh-unknown", env=env).stdout)
        if unknown["role"] is not None or unknown["actor"] != "-unknown"[-8:]:
            raise ValueError(f"show of an unregistered session: {unknown}")
        if run("get", env={**env, "CLAUDE_CODE_SESSION_ID": other}).returncode == 0:
            raise ValueError("get must not take the session id from the environment")
        listed = [json.loads(line) for line in run("list", env=env).stdout.splitlines()]
        if sorted(entry["actor"] for entry in listed) != sorted([SESSION_ACTOR, other[-8:]]):
            raise ValueError(f"session list: {listed}")

    # list is one jq over all registrations: each line must equal what `show` (one registration, entry_json) prints, whatever the
    # number of files, a state dir with spaces, activity files and worker markers; an unparseable file is skipped alone.
    with tempfile.TemporaryDirectory() as raw_state:
        state_dir = str(Path(raw_state) / "state dir")
        Path(state_dir).mkdir()
        env = session_env(state_dir)
        pipe_read, pipe_write = os.pipe()  # an open stdin that never delivers: a list that reads it hangs
        try:
            def listing() -> subprocess.CompletedProcess:
                return subprocess.run(["bash", str(script), "list"], text=True, capture_output=True, env={**os.environ, **env},
                                      stdin=pipe_read, timeout=30)

            if listing().returncode != 0 or listing().stdout != "":
                raise ValueError("session list of a state dir without registrations must print nothing")
            sessions = [f"sess{n:02d}-abcdef" for n in range(12)]
            for n, session in enumerate(sessions):
                Path(state_dir, f"{session}.json").write_text(json.dumps({
                    "session": session, "role": ("lead", "solo")[n % 2], "pulls": ["plan"], "actor": session[-8:], "tool": "claude",
                    "registered_at": (datetime.now(timezone.utc) - timedelta(hours=n + 1)).strftime("%Y-%m-%dT%H:%M:%SZ"), **({"pid": 40 + n, "pid_started": "x y", "project": "/p q"} if n % 3 else {})}, indent=2), encoding="utf-8")
                if n % 2:
                    Path(state_dir, f"{session}.active").touch()
                    os.utime(Path(state_dir, f"{session}.active"), (1_700_000_000 + n, 1_700_000_000 + n))
                for marker in range(n % 4):
                    workers = Path(state_dir, f"{session}.workers")
                    workers.mkdir(exist_ok=True)
                    (workers / f"w{marker}-spaced name").touch()
                    os.utime(workers / f"w{marker}-spaced name", (1_700_001_000 + marker, 1_700_001_000 + marker))
            shown = [run("show", session, env=env).stdout for session in sorted(sessions)]
            listed = listing()
            if listed.returncode != 0 or listed.stdout.splitlines() != [line for text in shown for line in text.splitlines()] \
                    or len(shown) != 12 or '"workers":{"w0-spaced name"' not in listed.stdout or '"active_at":"2023-11-14' not in listed.stdout:
                raise ValueError(f"session list differs from show per registration: {listed.stdout!r} {listed.stderr!r}")
            Path(state_dir, "sess05-abcdef.json").write_text('{"session": "sess05-abc', encoding="utf-8")  # half-written
            Path(state_dir, "sess06-abcdef.json").write_text("", encoding="utf-8")
            Path(state_dir, "sess07-abcdef.json").write_text("[1]", encoding="utf-8")
            listed = listing()
            rows = [json.loads(row) for row in listed.stdout.splitlines()]
            if listed.returncode != 0 or listed.stderr or len([r for r in rows if "unreadable" not in r]) != 9 \
                    or [Path(r["unreadable"]).name for r in rows if "unreadable" in r] != ["sess05-abcdef.json", "sess07-abcdef.json"]:
                raise ValueError(f"session list must skip an unparseable registration alone: {listed.stdout!r} {listed.stderr!r}")
            if os.geteuid() != 0:  # a file jq cannot open is skipped alone too
                denied = Path(state_dir, "sess04-abcdef.json")
                denied.chmod(0)
                try:
                    listed = listing()
                finally:
                    denied.chmod(0o600)
                rows = [json.loads(row) for row in listed.stdout.splitlines()]
                if listed.returncode != 0 or listed.stderr or len([r for r in rows if "unreadable" not in r]) != 8 \
                        or "sess04-abcdef.json" not in [Path(r["unreadable"]).name for r in rows if "unreadable" in r]:
                    raise ValueError(f"session list must skip an unreadable file alone: {listed.stdout!r} {listed.stderr!r}")
        finally:
            os.close(pipe_read)
            os.close(pipe_write)

    # Process identity: the nearest ancestor named claude (a symlink to bash stands in); Codex records none.
    with tempfile.TemporaryDirectory() as state_dir, tempfile.TemporaryDirectory() as bin_dir:
        env = session_env(state_dir)
        fake_claude = Path(bin_dir) / "claude"
        fake_claude.symlink_to(shutil.which("bash") or "/bin/bash")
        entry_file = Path(state_dir) / f"{SESSION}.json"

        ps = shutil.which("ps") or "/bin/ps"
        try:
            ps_runs = subprocess.run([ps, "-o", "lstart=", "-p", str(os.getpid())], capture_output=True).returncode == 0
        except OSError:
            ps_runs = False
        if not ps_runs:
            raise ValueError(f"{ps} cannot read process start times here (a build sandbox refuses the setuid /bin/ps)")

        def under_claude(*args: str, tool: str = "claude") -> tuple[int, subprocess.CompletedProcess]:
            # The stand-in prints its own UTC start after the script (which also keeps bash from exec'ing it);
            # the local zone differs, so a stored local time would not match.
            process = subprocess.Popen([str(fake_claude), "-c", f'bash "{script}" "$@"; LC_ALL=C TZ=UTC0 "{ps}" -o lstart= -p $$',
                                        "claude", *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       env={**os.environ, **env, **as_session(SESSION, tool), "TZ": "Asia/Tokyo"})
            out, err = process.communicate()
            return process.pid, subprocess.CompletedProcess(args, process.returncode, out, err)

        for command in (("alive",), ("session-active",), ("worker-started", "a43f14ee58a40ea36"),
                        ("worker-active", "a43f14ee58a40ea36"), ("worker-ended", "a43f14ee58a40ea36")):
            if under_claude(*command)[1].returncode != 0 or any(Path(state_dir).iterdir()):
                raise ValueError(f"session {command[0]} must be a silent no-op for an unregistered session")
            if run(*command, env=env).returncode != 0 or any(Path(state_dir).iterdir()):
                raise ValueError(f"session {command[0]} must be a silent no-op outside an agent session")
        pid, activated = under_claude("activate", "lead")
        entry = json.loads(entry_file.read_text(encoding="utf-8"))
        if entry.get("pid") != pid or entry.get("pid_started") != " ".join(activated.stdout.split()) \
                or not entry.get("pid_started") or "ended_workers" in entry:
            raise ValueError(f"activate did not record the claude process {pid}: {entry}")
        entry_file.write_text(json.dumps({**entry, "pid": 1, "pid_started": "stale"}), encoding="utf-8")
        pid, refreshed_run = under_claude("alive")
        refreshed = json.loads(entry_file.read_text(encoding="utf-8"))
        if refreshed.get("pid") != pid or refreshed.get("pid_started") != " ".join(refreshed_run.stdout.split()) \
                or refreshed["role"] != "lead":
            raise ValueError(f"alive did not refresh the process identity: {refreshed}")

        def shown_entry() -> dict:
            return json.loads(run("show", SESSION, env=env).stdout)

        def utc(path: Path) -> str:
            return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        workers_dir = Path(state_dir) / f"{SESSION}.workers"
        fresh = shown_entry()
        if (fresh["active_at"], fresh["workers"]) != (None, {}) or "active_workers" in fresh:
            raise ValueError(f"a session without activity showed some: {fresh}")
        # One marker per running worker, named by the agent id's last 8 characters, mtime = last activity;
        # worker-active creates a missed one; worker-ended deletes it.
        for _ in range(2):
            run("worker-started", "a43f14ee58a40ea36", env={**env, **as_session(SESSION)}).check_returncode()
        run("worker-active", "01a1641b-acfc-74a1-b69b-1e2fb53ded8a", env={**env, **as_session(SESSION)}).check_returncode()
        if sorted(path.name for path in workers_dir.iterdir()) != ["8a40ea36", "b53ded8a"]:
            raise ValueError("worker-started/worker-active must keep one marker per worker, by the agent id's last 8 characters")
        old = time.time() - 16 * 60
        os.utime(workers_dir / "b53ded8a", (old, old))
        listed = shown_entry()
        if listed["workers"] != {"8a40ea36": utc(workers_dir / "8a40ea36"), "b53ded8a": utc(workers_dir / "b53ded8a")}:
            raise ValueError(f"workers must map each running worker to its last activity: {listed}")
        run("worker-active", "01a1641b-acfc-74a1-b69b-1e2fb53ded8a", env={**env, **as_session(SESSION)}).check_returncode()
        if shown_entry()["workers"]["b53ded8a"] == listed["workers"]["b53ded8a"]:
            raise ValueError("worker-active did not refresh the worker's activity")
        under_claude("activate", "solo")
        if sorted(shown_entry()["workers"]) != ["8a40ea36", "b53ded8a"]:
            raise ValueError("a role change dropped the session's running workers")
        for command in ("worker-started", "worker-active", "worker-ended"):
            if run(command, "short", env={**env, **as_session(SESSION)}).returncode == 0:
                raise ValueError(f"{command} accepted an invalid agent id")
        run("worker-ended", "a43f14ee58a40ea36", env={**env, **as_session(SESSION)}).check_returncode()
        run("worker-ended", "agent-never-started", env={**env, **as_session(SESSION)}).check_returncode()
        if sorted(shown_entry()["workers"]) != ["b53ded8a"]:
            raise ValueError("worker-ended did not delete exactly the stopped worker's marker")
        # Workers starting and stopping together keep each other's markers (one file per worker).
        parallel = [f"agent-{index:016x}" for index in range(20)]

        def together(command: str, workers: list[str]) -> bool:
            processes = [subprocess.Popen(["bash", str(script), command, worker], env={**os.environ, **env, **as_session(SESSION)},
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for worker in workers]
            return all(process.wait() == 0 for process in processes)

        if not together("worker-started", parallel) \
                or sorted(shown_entry()["workers"]) != sorted([worker[-8:] for worker in parallel] + ["b53ded8a"]):
            raise ValueError("worker-started lost the markers of workers starting together")
        if not together("worker-ended", parallel) or sorted(shown_entry()["workers"]) != ["b53ded8a"]:
            raise ValueError("worker-ended lost or kept markers of workers stopping together")
        if any(path.name.startswith(".") for path in Path(state_dir).iterdir() if path.name not in (f"{SESSION}.json", ".lock")):
            raise ValueError("session left temporary files")
        # session-active: the session's own last tool call.
        run("session-active", env={**env, **as_session(SESSION)}).check_returncode()
        if shown_entry()["active_at"] != utc(Path(state_dir) / f"{SESSION}.active"):
            raise ValueError("session-active did not record the session's activity")
        # Migration: the legacy <session>.ended/ folder (stopped workers, now a missing marker) goes on read and write.
        for trigger in (lambda: run("show", SESSION, env=env), lambda: run("list", env=env),
                        lambda: run("worker-active", "agent-0000ffff", env={**env, **as_session(SESSION)})):
            legacy = Path(state_dir) / f"{SESSION}.ended"
            legacy.mkdir()
            (legacy / "deadbeef").touch()
            trigger()
            if legacy.exists():
                raise ValueError("a registry read or write kept the legacy .ended folder")
        if "deadbeef" in shown_entry()["workers"]:
            raise ValueError("a legacy ended marker read as a running worker")
        run("worker-ended", "agent-0000ffff", env={**env, **as_session(SESSION)}).check_returncode()
        # The legacy ended_workers field is never read, and alive drops it.
        entry = json.loads(entry_file.read_text(encoding="utf-8"))
        entry_file.write_text(json.dumps({**entry, "ended_workers": ["deadbeef"]}), encoding="utf-8")
        if "ended_workers" in shown_entry():
            raise ValueError("show printed the legacy ended_workers field")
        under_claude("alive")
        if "ended_workers" in json.loads(entry_file.read_text(encoding="utf-8")):
            raise ValueError("alive kept the legacy ended_workers field")
        under_claude("activate", "lead", tool="codex")
        shown = shown_entry()
        if shown["pid"] is not None or shown["pid_started"] is not None:
            raise ValueError(f"a Codex session recorded a process identity: {shown}")
        listed = json.loads(run("list", env=env).stdout)
        if not {"pid", "pid_started", "active_at", "workers"} <= listed.keys() or {"ended_workers", "active_workers"} & listed.keys():
            raise ValueError(f"session list lacks the liveness and activity fields: {listed}")
        unregistered = json.loads(run("show", "abcdefgh-unknown", env=env).stdout)
        if (unregistered["active_at"], unregistered["workers"]) != (None, {}):
            raise ValueError(f"show of an unregistered session: {unregistered}")

        # session-activity hook: SubagentStart and a worker's tool call (agent_id) create or touch the worker's
        # marker, SubagentStop deletes it, the session's own tool call touches its activity file; it never fails.
        hook = root / "hooks" / "session-activity.sh"
        hook_env = {**env, "AGENT_SESSION_COMMAND": str(script)}
        start = {"hook_event_name": "SubagentStart", "session_id": SESSION, "agent_id": "a1b2c3d4e5f60718",
                 "agent_type": "build"}
        tool_call = {"hook_event_name": "PreToolUse", "session_id": SESSION, "tool_name": "Read", "tool_input": {}}
        (Path(state_dir) / f"{SESSION}.active").unlink()
        # Skipped payloads carry their own ids and run with the session in the environment too.
        for payload in ({**start, "agent_id": "internal-0000aaaa", "agent_type": ""},
                        {**start, "hook_event_name": "SubagentStop", "agent_id": "internal-0000aaaa", "agent_type": ""},
                        {**tool_call, "agent_id": "internal-0000aaaa", "agent_type": ""},
                        {key: value for key, value in start.items() if key != "agent_type"} | {"agent_id": "notype-0000eeee"},
                        {**start, "agent_id": "elsewhere-0000bbbb", "session_id": "abcdefgh-unknown"},
                        {**tool_call, "agent_id": "elsewhere-0000bbbb", "session_id": "abcdefgh-unknown"},
                        {**start, "agent_id": "otherevent-0000dddd", "hook_event_name": "Stop"}):
            run_hook(hook, payload, {**hook_env, **as_session(SESSION)})
        run_hook(hook, {**start, "agent_id": "nocommand-0000cccc"},
                 {**hook_env, "AGENT_SESSION_COMMAND": str(Path(bin_dir) / "missing")})
        for raw in ("", "not json", "[]"):
            if subprocess.run(["bash", str(hook)], input=raw, text=True, capture_output=True,
                              env={**os.environ, **hook_env}).returncode != 0:
                raise ValueError(f"session-activity hook failed on input {raw!r}")
        if sorted(shown_entry()["workers"]) != ["b53ded8a"] or shown_entry()["active_at"] is not None:
            raise ValueError(f"session-activity hook recorded a skipped payload: {shown_entry()}")
        # The payload's session wins over an outer Codex session in the environment.
        run_hook(hook, start, {**hook_env, "CODEX_SESSION_ID": "elsewhere-1"})
        if sorted(shown_entry()["workers"]) != ["b53ded8a", "e5f60718"]:
            raise ValueError("session-activity hook did not mark exactly the payload's worker in the payload's session")
        os.utime(workers_dir / "e5f60718", (old, old))
        # A worker's tool call (any tool, agent_type key absent as on a Codex payload) refreshes or creates its
        # marker; a call without agent_id is the session's own.
        run_hook(hook, {**tool_call, "agent_id": "a1b2c3d4e5f60718"}, hook_env)
        run_hook(hook, {**tool_call, "tool_name": "apply_patch", "agent_id": "codexwkr-00009999"}, hook_env)
        if shown_entry()["workers"].get("e5f60718") == datetime.fromtimestamp(old, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") or "00009999" not in shown_entry()["workers"]:
            raise ValueError("a worker's tool call did not refresh or create its marker")
        if shown_entry()["active_at"] is not None:
            raise ValueError("a worker's tool call counted as the session's own activity")
        run_hook(hook, tool_call, hook_env)
        if shown_entry()["active_at"] is None:
            raise ValueError("the session's own tool call did not record its activity")
        run_hook(hook, {**start, "hook_event_name": "SubagentStop"}, hook_env)
        if "e5f60718" in shown_entry()["workers"]:
            raise ValueError("session-activity hook did not delete the stopped worker's marker")
        if sorted(path.name for path in Path(state_dir).iterdir() if path.name != ".lock") != [f"{SESSION}.active", f"{SESSION}.json", f"{SESSION}.workers"]:
            raise ValueError("session-activity hook wrote an entry for an unregistered session")

    # Project (r26-q115/q116): the resolved folder of the board, found through `board bd where`; a failed lookup records
    # none and still succeeds; alive corrects it at every run; list carries it.
    with tempfile.TemporaryDirectory() as raw_base, tempfile.TemporaryDirectory() as state_dir:
        base = Path(raw_base).resolve()
        env = session_env(state_dir)
        main, main_env = fake_board(base)
        link = base / "link"
        link.symlink_to(main)
        _, linked_env = fake_board(base, "second", printed=link)
        _, broken_env = fake_board(base, "broken")
        (Path(broken_env["PATH"].split(os.pathsep)[0]) / "bd").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        worktree = base / "worktree"
        worktree.mkdir()  # a git worktree has no .beads; bd where names the main checkout's

        def registry_run(*args: str, extra: dict[str, str], cwd: Path | None = None) -> subprocess.CompletedProcess:
            return subprocess.run(["bash", str(script), *args], text=True, capture_output=True, cwd=cwd,
                                  env={**os.environ, **env, **as_session(SESSION), **extra})

        def project_of() -> object:
            return json.loads(registry_run("show", SESSION, extra={}).stdout)["project"]

        registry_run("activate", "lead", extra=main_env, cwd=worktree).check_returncode()
        if project_of() != str(main):
            raise ValueError(f"activate must record the board's folder from a worktree: {project_of()!r}")
        registry_run("activate", "lead", extra=linked_env).check_returncode()
        if project_of() != str(main):
            raise ValueError(f"activate must record the resolved (realpath) folder, not a symlink: {project_of()!r}")
        registry_run("alive", extra=broken_env).check_returncode()
        if project_of() is not None:
            raise ValueError("alive must drop the project when the lookup fails")
        entry_file = Path(state_dir) / f"{SESSION}.json"
        entry_file.write_text(json.dumps({**json.loads(entry_file.read_text(encoding="utf-8")), "project": "/elsewhere"}), encoding="utf-8")
        registry_run("alive", extra=main_env, cwd=worktree).check_returncode()
        if project_of() != str(main):
            raise ValueError(f"alive must correct a stale project: {project_of()!r}")
        listed = [json.loads(line) for line in registry_run("list", extra={}).stdout.splitlines()]
        if [entry["project"] for entry in listed] != [str(main)]:
            raise ValueError(f"session list lacks the project: {listed}")
        # Outside a board (bd where fails), activation still succeeds and records no project.
        registry_run("activate", "solo", extra=broken_env).check_returncode()
        if project_of() is not None or "project" in json.loads(entry_file.read_text(encoding="utf-8")):
            raise ValueError(f"a failed lookup recorded a project: {project_of()!r}")
        if json.loads(registry_run("show", "abcdefgh-unknown", extra={}).stdout)["project"] is not None:
            raise ValueError("show of an unregistered session lacks a null project")

    with tempfile.TemporaryDirectory() as state_home:
        env = {key: value for key, value in os.environ.items() if key != "AGENT_SESSION_STATE_DIR"}
        subprocess.run(["bash", str(script), "activate", "lead"], check=True,
                       env={**env, **as_session(SESSION), "XDG_STATE_HOME": state_home})
        if not (Path(state_home) / "agent-sessions" / f"{SESSION}.json").is_file():
            raise ValueError("the registry must live under $XDG_STATE_HOME/agent-sessions")
        # state-dir names that location, so the engine and the console never restate the rule.
        for extra, expected in (({"XDG_STATE_HOME": state_home}, f"{state_home}/agent-sessions"),
                                ({"XDG_STATE_HOME": state_home, "AGENT_SESSION_STATE_DIR": "/tmp/explicit"}, "/tmp/explicit")):
            named = subprocess.run(["bash", str(script), "state-dir"], capture_output=True, text=True, check=True,
                                   env={**env, **extra}).stdout.strip()
            if named != expected:
                raise ValueError(f"session state-dir printed {named!r}, expected {expected!r}")


def pre_tool_use(command: object, **payload: object) -> dict[str, object]:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command, "description": "kept"},
        **payload,
    }


def rewritten(result: dict[str, object] | None, codex: bool) -> str | None:
    """The rewritten command; checks the per-tool decision and kept fields."""
    if result is None:
        return None
    output = result["hookSpecificOutput"]
    if output.get("permissionDecision") == "deny":
        return None
    # Claude evaluates permissions against updatedInput without a decision;
    # Codex drops updatedInput unless the decision is "allow".
    if output.get("permissionDecision") != ("allow" if codex else None):
        raise ValueError(f"wrong permission decision for {'Codex' if codex else 'Claude'}: {output}")
    if output["updatedInput"].get("description") != "kept":
        raise ValueError("updatedInput dropped other tool_input fields")
    return output["updatedInput"]["command"]


def validate_session_register(root: Path) -> None:
    hook = root / "hooks" / "session-register.sh"
    worker = {"agent_id": "a43f14ee58a40ea36", "agent_type": "build"}
    for command in ("session activate lead", "~/.agents/bin/session activate agent --pulls plan",
                    'bash "$HOME/.agents/bin/session" activate solo', "cd x && session activate lead"):
        for extra in (worker, {**worker, "turn_id": "t"}):
            result = run_hook(hook, pre_tool_use(command, session_id=SESSION, **extra))
            if not result or result["hookSpecificOutput"].get("permissionDecision") != "deny":
                raise ValueError(f"session-register let a worker register: {command!r}")
        if run_hook(hook, pre_tool_use(command, session_id=SESSION)) is not None:
            raise ValueError(f"session-register touched a session's {command!r}")
    for command in ("session show", "rg 'session activate' skills", "echo session activate", "mysession activate lead"):
        if run_hook(hook, pre_tool_use(command, session_id=SESSION, **worker)) is not None:
            raise ValueError(f"session-register denied {command!r}")


def validate_compact_reorient(root: Path) -> None:
    hook = root / "hooks" / "compact-reorient.sh"
    env_base = {"AGENT_SESSION_COMMAND": str(root / "bin" / "session")}
    pointer = "Recover under `$HOME/.agents/skills/shared/project-memory.md` Recovery."
    # The pointer's target must keep the recovery obligations the hook used to restate.
    memory = (root / "skills" / "shared" / "project-memory.md").read_text(encoding="utf-8")
    recovery = " ".join(memory.split("## Recovery\n", 1)[1].split("\n## ", 1)[0].split())
    obligations = (
        "current task and newer user instructions",
        "the approved checkpoint",
        "deferrals, return boundary and authority",
        "`$HOME/.agents/bin/board mine`",
        "`$HOME/.agents/bin/board position`",
        "session's checkpoint",
        "canonical project goal",
        "topic goal and milestone",
        "existing authority",
        "approved sequence",
        "remains the current authorized task",
        "working tree",
    )
    missing = [item for item in obligations if item not in recovery]
    if missing:
        raise ValueError(f"project-memory Recovery lost obligations {missing}")
    with tempfile.TemporaryDirectory() as state_dir, tempfile.TemporaryDirectory() as home:
        # The hook prints the installed file's Recovery section; where it cannot, it names the file.
        installed = Path(home) / ".agents" / "skills" / "shared"
        installed.mkdir(parents=True)
        (installed / "project-memory.md").write_text(memory, encoding="utf-8")
        env = {**session_env(state_dir), **env_base, "HOME": home}
        no_memory = {**env, "HOME": str(Path(state_dir) / "no-home")}
        context = hook_context(run_hook(hook, {"hook_event_name": "SessionStart", "source": "compact", "session_id": "abcdefgh-unregistered"},
                                        no_memory))
        if pointer not in context:
            raise ValueError(f"recovery without the installed project-memory.md must name the file: {context}")
        subprocess.run(["bash", str(root / "bin" / "session"), "activate", "agent", "--pulls",
                        "implement,review"], check=True, env={**os.environ, **env, **as_session(SESSION)})
        for source in ("compact", "resume"):
            for session, registered in ((SESSION, True), ("abcdefgh-unregistered", False)):
                context = hook_context(run_hook(
                    hook, {"hook_event_name": "SessionStart", "source": source, "session_id": session}, env))
                body = " ".join(context.split())
                if pointer in context or "bd ready" in context or not all(item in body for item in obligations) \
                        or "Recovery (`$HOME/.agents/skills/shared/project-memory.md`):" not in context:
                    raise ValueError(f"{source} recovery must print the project-memory recovery section only: {context}")
                markers = ("role `agent` pulling implement, review", f"actor `{SESSION_ACTOR}`",
                           "`$HOME/.agents/skills/role/SKILL.md`", "every protocol file it lists")
                if registered and not all(marker in context for marker in markers):
                    raise ValueError(f"{source} recovery did not restore the registered role: {context}")
                if not registered and ("registered as role" in context or "role/SKILL.md" in context):
                    raise ValueError("recovery invented a role for an unregistered session")
        if run_hook(hook, {"hook_event_name": "SessionStart", "source": "startup", "session_id": SESSION}, env):
            raise ValueError("session recovery ran for a new session")
        generic = hook_context(run_hook(hook, {"hook_event_name": "SessionStart", "source": "compact"}, env))
        if "re-orient" not in generic or "the approved checkpoint" not in generic or "registered as role" in generic:
            raise ValueError("recovery without a session id must stay generic")
        # Codex sessions get the open protocol round's line; Claude's console owns that recovery.
        fake, called, failing = Path(state_dir) / "protocol", Path(state_dir) / "protocol-calls", Path(state_dir) / "protocol-fails"
        fake.write_text(f'#!/usr/bin/env bash\necho "$*" >> {called}\n[[ -f {failing} && "$3" == compacted ]] && exit 1\n'
                        '[[ "$1 $3 $4" == "--session status --line" ]] && echo "protocol: round r2 · check 1/3"\nexit 0\n')
        fake.chmod(0o755)
        codex = "cdx-recovery-0001"
        subprocess.run(["bash", str(root / "bin" / "session"), "activate", "lead"], check=True,
                       env={**os.environ, **env, **as_session(codex, "codex")})
        for session, expected in ((codex, True), (SESSION, False)):
            context = hook_context(run_hook(hook, {"hook_event_name": "SessionStart", "source": "compact",
                                                   "session_id": session}, {**env, "AGENT_PROTOCOL_COMMAND": str(fake)}))
            if ("protocol: round r2" in context) != expected:
                raise ValueError(f"compact-reorient protocol line for {session} (expected {expected}): {context}")
            if "compacted failed" in context:
                raise ValueError(f"compact-reorient reported a failure of a working protocol compacted: {context}")
        # A deciding session's engine learns of the compaction, whichever tool; an agent's has nothing to forget. A failing call is
        # said in the recovery message.
        if called.read_text().splitlines().count(f"--session {codex} compacted") != 1 or f"--session {SESSION} compacted" in called.read_text():
            raise ValueError(f"compact-reorient must call protocol compacted for deciding sessions only: {called.read_text()}")
        failing.write_text("")
        context = hook_context(run_hook(hook, {"hook_event_name": "SessionStart", "source": "compact", "session_id": codex},
                                        {**env, "AGENT_PROTOCOL_COMMAND": str(fake)}))
        if "`protocol compacted` failed: run it" not in context or "Recover" not in context:
            raise ValueError(f"compact-reorient must say a failed protocol compacted in the recovery message: {context}")
        context = hook_context(run_hook(hook, {"hook_event_name": "SessionStart", "source": "compact", "session_id": codex},
                                        {**env, "AGENT_PROTOCOL_COMMAND": str(Path(state_dir) / "missing")}))
        if "`protocol compacted` failed" not in context:
            raise ValueError(f"compact-reorient must say a missing protocol command: {context}")


def validate_bd_guard(root: Path) -> None:
    hook = root / "hooks" / "bd-guard.sh"

    def guard(command: object, **payload: object):
        return run_hook(hook, pre_tool_use(command, **payload))

    def denied(result) -> bool:
        return result is not None and result["hookSpecificOutput"].get("permissionDecision") == "deny"

    # Bare bd is denied with or without a session; board bd and mentions pass.
    bare = ["bd show x", "cd repo && bd ready", "xargs -I{} sh -c 'bd show {}' < ids", "if bd close x; then :; fi",
            "/nix/store/x/bin/bd list", "BEADS_ACTOR=a bd close x", '"$B"; bd show x', 'bash -c "cd x && bd ready"', "X=$(cat ids) bd show x"]
    passing = ["board bd show x", "$HOME/.agents/bin/board bd close x", "cd x && board bd ready",
               "xargs -I{} board bd show {} < ids", 'echo "bd close x"', 'git commit -m "bd close"', "rg pattern skills",
               'board handover x "tests pass; bd lint clean"', 'git commit -m "x (bd 1.3.1)"', 'echo "x && bd ready"',
               "rg 'a|bd ' skills", "sh -c 'board bd show x'", "g=$($HOME/.agents/bin/board bd show x)",
               "B=$HOME/.agents/bin/board\n$B bd show x", "B=board;$B bd show x",
               '"$HOME/.agents/bin/board" bd show x', 'cd x && "$B" bd show x', 'python3 a.py && "${B}" bd ready',
               'codex exec "line one\nslug \'demo\'. Run it." | grep -E "^(x|bd )"']
    # Raw item reads name board show (board bd refuses them); other bare bd names board bd.
    reads = {"bd show x", "xargs -I{} sh -c 'bd show {}' < ids", '"$B"; bd show x', "X=$(cat ids) bd show x"}
    bare += ["bd view x y", "bd comments x --json", "cd repo && bd comments x", "bd comments add x 'y'", "bd comments -h"]
    reads |= {"bd view x y", "bd comments x --json", "cd repo && bd comments x"}
    for command in bare:
        for payload in ({}, {"session_id": SESSION}, {"session_id": SESSION, "turn_id": "t"}):
            result = guard(command, **payload)
            reason = result["hookSpecificOutput"]["permissionDecisionReason"] if denied(result) else ""
            if not reason or ("board show <ids>" in reason) != (command in reads) or "board bd" not in reason:
                raise ValueError(f"bd-guard let bare bd through or named the wrong replacement: {command!r} with {payload}: {reason}")
    for command in passing:
        for payload in ({}, {"session_id": SESSION}, {"session_id": SESSION, "turn_id": "t"}):
            if guard(command, **payload) is not None:
                raise ValueError(f"bd-guard touched {command!r} with {payload}")

    # Parallel board calls are denied on embedded boards only.
    parallel = [
        ("xargs -P 6 -I{} sh -c 'board bd show {} --json' < ids", True),
        ("parallel board bd show {} ::: a b", True),
        ("board bd list --json > board.json &", True),
        ("board bd list > log 2>&1 &", True),
        ("cat <<-EOF > notes\n\tboard bd show x &\n\tEOF\nboard bd list &", True),
        ("$HOME/.agents/bin/board position &", True),
        ("xargs board bd show --json < ids", False),
        ("while read id; do board bd history $id; done < ids", False),
        ('git commit -m "blocks parallel bd calls"', False),
        ("echo parallel && board bd show x", False),
    ]
    with tempfile.TemporaryDirectory() as repo:
        (Path(repo) / ".beads").mkdir()
        (Path(repo) / "sub").mkdir()
        for mode in ("server", "embedded"):
            (Path(repo) / ".beads" / "metadata.json").write_text(json.dumps({"dolt_mode": mode}), encoding="utf-8")
            for command, expected in parallel:
                if denied(guard(command, cwd=str(Path(repo) / "sub"))) != (expected and mode == "embedded"):
                    raise ValueError(f"bd-guard misjudged parallel {command!r} on a {mode} board")

    # Only a Claude subagent's board commands are rewritten; board derives every other actor itself.
    worker = {"agent_id": "a43f14ee58a40ea36", "agent_type": "general-purpose"}
    worker_actor = f"{SESSION_ACTOR}/8a40ea36"
    worker_prefix = f"export BEADS_ACTOR={worker_actor}; "
    injected = ["board bd close x", "cd repo && board bd close x", "$HOME/.agents/bin/board claim",
                'bash "$HOME/.agents/bin/board" claim x', "~/.agents/bin/board ruling release a b",
                "xargs -I{} sh -c 'board bd show {}' < ids", f"board bd update x --actor {worker_actor}",
                'board bd comments add x "drop the --actor goal-agent habit and BEADS_ACTOR=goal-lead"',
                'cd x && "${B}" bd ready', "sh -c '$B bd show x'"]
    for command in injected:
        if rewritten(guard(command, session_id=SESSION, **worker), False) != worker_prefix + command:
            raise ValueError(f"bd-guard did not inject the worker actor into {command!r}")
        if "--actor " in command and "habit" not in command:
            continue
        for payload in ({}, {"turn_id": "t"}, {**worker, "turn_id": "t"}):
            if guard(command, session_id=SESSION, **payload) is not None:
                raise ValueError(f"bd-guard rewrote {command!r} for {payload}")
    if guard(worker_prefix + "board bd ready", session_id=SESSION, **worker) is not None:
        raise ValueError("bd-guard re-prefixed an injected command")
    if rewritten(guard("board mine", session_id=SESSION, agent_id="01a1641b-acfc-74a1-b69b-1e2fb53ded8a"),
                 False) != f"export BEADS_ACTOR={SESSION_ACTOR}/b53ded8a; board mine":
        raise ValueError("bd-guard derived the wrong worker actor without an agent type")
    if guard(f"BEADS_ACTOR={SESSION_ACTOR} board bd close x", session_id=SESSION) is not None:
        raise ValueError("bd-guard denied a session's own explicit actor")

    differing = [
        "board bd update x --status open --actor goal-lead",
        "board bd update x \\\n  --actor=goal-lead --status open",
        "BEADS_ACTOR=goal-lead board bd close x",
        "export BEADS_ACTOR=goal-lead; board bd close x",
        "BD_ACTOR=other $HOME/.agents/bin/board claim",
        'board bd create --title "Don\'t" --actor goal-lead --description "it\'s"',
        'board bd close x --actor "goal-lead"',
        'cd x && "${B}" bd ready --actor goal-lead',
    ]
    for command in differing:
        for payload in ({}, {"turn_id": "t"}):
            result = guard(command, session_id=SESSION, **payload)
            if not denied(result) or f"`{SESSION_ACTOR}`" not in result["hookSpecificOutput"]["permissionDecisionReason"]:
                raise ValueError(f"bd-guard did not deny the differing actor in {command!r}")
    if not denied(guard(f"board bd close x --actor {SESSION_ACTOR}", session_id=SESSION, **worker)):
        raise ValueError("bd-guard let a worker write as its session")

    # The prefix reaches every board call in compound commands when the shell runs them.
    with tempfile.TemporaryDirectory() as directory:
        stub = Path(directory) / "board"
        stub.write_text('#!/bin/sh\nprintf "%s\\n" "$BEADS_ACTOR"\n', encoding="utf-8")
        stub.chmod(0o755)
        for command in (f"cd {directory} && board x", "if board x; then :; fi", "board x | cat", "true; board x"):
            line = rewritten(guard(command, session_id=SESSION, **worker), False)
            for shell in ("bash", "zsh"):
                if shell == "zsh" and not any(Path(p, "zsh").exists() for p in os.environ.get("PATH", "").split(":")):
                    continue
                # PATH is set inside the command: shell startup files (nix-darwin's /etc/bashrc) may reset it.
                output = subprocess.run([shell, "-c", f'PATH="{directory}:$PATH"; {line}'], text=True,
                                        capture_output=True, check=True,
                                        env={**os.environ, "BEADS_ACTOR": ""}).stdout
                if output.strip() != worker_actor:
                    raise ValueError(f"{shell} did not pass the actor to board in {command!r}: {output!r}")


SETUP_BASH4 = re.compile(r"\$\{[^}]*(?:,,|\^\^)[^}]*\}|\$\{\w+@[QEPAa]\}|\b(?:mapfile|readarray|coproc)\b|\b(?:declare|local|typeset) -\w*A\b"
                         r"|&>>|\bwait -n\b|shopt -s globstar|\$EPOCHSECONDS")


def validate_setup_portable(root: Path) -> None:
    """The bundle's shell runs on the bash 3.2 macOS ships. The Claude-only hooks sit beside the agents root (absent
    from the store copy the build checks)."""
    shipped = [root / "bin" / "session", *sorted((root / "hooks").glob("*.sh")),
               *sorted((root.parent / "claude" / "hooks").glob("*.sh"))]
    for path in shipped:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.lstrip().startswith("#") and SETUP_BASH4.search(line):
                raise ValueError(f"{path}:{number} needs a newer bash than 3.2: {line.strip()}")


def validate_review_tiers(root: Path) -> None:
    """r7-q28: every first review goes to review; deep-review only on escalation, in the policy table, the agent
    descriptions and the plan protocol alike."""
    def description(name: str) -> str:
        front = (root / "definitions" / f"{name}.md").read_text(encoding="utf-8").split("---", 2)[1]
        return " ".join(front.split("description:", 1)[1].split("\neffort:", 1)[0].split())
    policy = (root / "skills" / "shared" / "acceptance.md").read_text(encoding="utf-8")
    rows = {line.rsplit("|", 2)[1].strip(): line for line in policy.splitlines() if line.startswith("| ") and line.count("|") == 3}
    deep = next((line for gate, line in rows.items() if gate.startswith("`deep-review`")), "")
    first = next((line for gate, line in rows.items() if gate.startswith("`review`")), "")
    if "escalat" not in deep or any(word in deep for word in ("plan", "design", "contract")):
        raise ValueError("acceptance.md: the deep-review row must name escalation only")
    if not all(word in first for word in ("plan", "design", "contract")):
        raise ValueError("acceptance.md: the review row must cover plans, designs and contracts")
    if "escalat" not in description("deep-review") or "plan, design or contract" in description("deep-review"):
        raise ValueError("deep-review description must route escalations only")
    if "deep-review" in description("second-opinion"):
        raise ValueError("second-opinion description must not name deep-review as a first gate")
    if "deep_review=" in (root / "skills" / "role" / "protocols" / "plan.md").read_text(encoding="utf-8"):
        raise ValueError("plan.md: planners no longer mark deep_review")


def validate_shebang_modes(root: Path) -> None:
    """A file starting with a shebang is executable (the Claude-only scripts beside the agents root included when present)."""
    skip = {".git", "node_modules", "__pycache__"}
    files = [p for p in root.rglob("*") if p.is_file() and not skip & set(p.relative_to(root).parts)]
    files += sorted((root.parent / "claude").rglob("*.sh"))
    for path in files:
        with path.open("rb") as handle:
            if handle.read(2) == b"#!" and not os.access(path, os.X_OK):
                raise ValueError(f"{path} starts with a shebang but is not executable: chmod +x it")


def validate_setup_installer(root: Path) -> None:
    """setup/install.py in a fake home: keeps the user's files, upgrades by its own state, stops before any change."""
    installer = root / "setup" / "install.py"
    board_version = re.search(r"\(bd (\d+\.\d+\.\d+)\)", (root / "bin" / "board").read_text(encoding="utf-8"))
    source = installer.read_text(encoding="utf-8")
    if board_version is None or f'BD_TESTED = "{board_version.group(1)}"\n' not in source:
        raise ValueError("setup/install.py BD_TESTED differs from the bd version bin/board names")
    # macOS ships python3 3.9: the installer must parse there for its version message to reach the user.
    ast.parse(source, feature_version=(3, 9))

    def hook(command: str) -> dict:
        return {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": command}]}]}}

    def bundle(base: Path, name: str, version: str, shipped: dict[str, str], claude: str, codex: str,
               grant_entries: str | None = None) -> Path:
        folder = base / name
        for rel, text in shipped.items():
            target = folder / "files" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        (folder / "settings").mkdir()
        (folder / "settings" / "claude-hooks.json").write_text(json.dumps(hook(claude)), encoding="utf-8")
        (folder / "settings" / "codex-hooks.json").write_text(json.dumps(hook(codex)), encoding="utf-8")
        (folder / "VERSION").write_text(f"{version}\n", encoding="utf-8")
        shutil.copy2(installer, folder / "install.py")
        if grant_entries is not None:
            edited = re.sub(r"GRANT_ROOTS = \(.*?\n\)\n", lambda _: f"GRANT_ROOTS = ({grant_entries})\n", source, count=1, flags=re.S)
            (folder / "install.py").write_text(edited, encoding="utf-8")
        return folder

    def tree(base: Path) -> dict[str, str]:
        return {str(path.relative_to(base)): path.read_text(encoding="utf-8") for path in sorted(base.rglob("*")) if path.is_file()}

    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        tools = base / "tools"
        tools.mkdir()
        (tools / "python3").symlink_to(sys.executable)
        fake_bd = tools / "bd"
        fake_bd.write_text(f"#!/bin/sh\necho 'bd version {board_version.group(1)} (test)'\n", encoding="utf-8")
        fake_bd.chmod(0o755)
        home = base / "home"
        home.mkdir()

        def run(folder: Path, *flags: str, path: Path = tools):
            return subprocess.run([sys.executable, str(folder / "install.py"), *flags], capture_output=True, text=True, check=False,
                                  stdin=subprocess.DEVNULL, env={"HOME": str(home), "PATH": str(path)})

        def ok(folder: Path, *flags: str):
            result = run(folder, *flags)
            if result.returncode != 0:
                raise ValueError(f"install.py {flags} failed: {result.stdout}{result.stderr}")
            return result

        def refuses(what: str, folder: Path, fragment: str, path: Path = tools) -> None:
            before = tree(home)
            result = run(folder, path=path)
            if result.returncode == 0 or fragment not in result.stderr or tree(home) != before:
                raise ValueError(f"install.py must stop on {what} before any change: {result.returncode} {result.stderr} {result.stdout}")

        def commands(rel: str) -> list[str]:
            config = json.loads((home / rel).read_text(encoding="utf-8"))
            return [entry["command"] for groups in config.get("hooks", {}).values() for group in groups for entry in group["hooks"]]

        scratch_root, records_root, extra_root = "~/.local/state/agents/scratch", "~/.local/share/agents/decisions", "~/.config/agents/extra"
        rule = lambda root_: f"Edit({root_}/**)"
        entries = {"scratch": '("XDG_STATE_HOME", ".local/state", "agents/scratch"),', "records": '("XDG_DATA_HOME", ".local/share", "agents/decisions"),',
                   "extra": '("XDG_CONFIG_HOME", ".config", "agents/extra"),'}
        v1 = bundle(base, "v1", "one", {
            ".claude/CLAUDE.md": "setup rules\n",
            ".codex/AGENTS.md": "setup rules\n",
            ".claude/skills/kept/SKILL.md": "kept\n",
            ".claude/skills/kept/dropped.md": "dropped\n",
            ".claude/skills/gone/SKILL.md": "gone\n",
            ".agents/bin/tool": "#!/bin/sh\n",
            ".agents/bin/pytool": "#!/usr/bin/env python3\nprint(1)\n",
            ".agents/bin/lib/module.py": "#!/usr/bin/env python3\n",
            ".claude/mods/console/.claude-plugin/plugin.json": "{}\n",
        }, 'bash "$HOME/.claude/hooks/one.sh"', 'bash "$HOME/.codex/hooks/one.sh"')
        (v1 / "files" / ".agents" / "bin" / "tool").chmod(0o755)

        own_hook = {"matcher": "Edit", "hooks": [{"type": "command", "command": "mine.sh"}]}
        (home / ".claude" / "skills" / "mine").mkdir(parents=True)
        (home / ".claude" / "skills" / "mine" / "SKILL.md").write_text("mine\n", encoding="utf-8")
        (home / ".claude" / "CLAUDE.md").write_text("my rules\n", encoding="utf-8")
        settings = home / ".claude" / "settings.json"
        # The user already holds the Edit rule for one granted root: it stays through upgrade and uninstall.
        settings.write_text(json.dumps({"model": "mine", "env": {"KEEP": "1"}, "hooks": {"PreToolUse": [own_hook]}, "note": "caf\u00e9",
                                        "permissions": {"allow": ["Bash(ls)", rule(scratch_root)]}}, ensure_ascii=False), encoding="utf-8")
        settings.chmod(0o640)

        # Stops before any change.
        without_bd = base / "without-bd"
        without_bd.mkdir()
        refuses("a missing bd", v1, "missing required tool: bd", without_bd)
        spoofed = "import runpy, sys; sys.version_info = (3, 9, 6, 'final', 0); sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')"

        def as_old_python(path: Path, **extra: str):
            return subprocess.run([sys.executable, "-c", spoofed, str(v1 / "install.py")], capture_output=True, text=True, check=False,
                                  stdin=subprocess.DEVNULL, env={"HOME": str(home), "PATH": str(path), **extra})

        old_python = as_old_python(tools)
        if old_python.returncode == 0 or "python3 is 3.9.6; 3.11 or newer" not in old_python.stderr:
            raise ValueError(f"install.py must name an old python3 before anything else: {old_python.stderr}")
        # With a newer python3.N on PATH it continues there instead.
        newer = base / "newer"
        newer.mkdir()
        (newer / "python3.12").write_text("#!/bin/sh\necho \"reexec $*\"\n", encoding="utf-8")
        (newer / "python3.12").chmod(0o755)
        (newer / "python3.13").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")  # a shim of an unselected version
        (newer / "python3.13").chmod(0o755)
        moved = as_old_python(newer)
        if moved.returncode != 0 or f"continuing with {newer}/python3.12" not in moved.stderr or f"reexec {v1}/install.py" not in moved.stdout:
            raise ValueError(f"install.py must re-run itself under the newest python3.N that starts: {moved.stdout}{moved.stderr}")
        looped = as_old_python(newer, CLAUDE_CODEX_SETUP_REEXEC="1")
        if looped.returncode == 0 or "python3 is 3.9.6; 3.11 or newer" not in looped.stderr or "reexec" in looped.stdout:
            raise ValueError(f"a re-run that is still too old must stop, not loop: {looped.stdout}{looped.stderr}")
        (home / ".codex").mkdir()
        (home / ".codex" / "hooks.json").write_text("{broken", encoding="utf-8")
        refuses("broken settings", v1, ".codex/hooks.json is not a JSON object", tools)
        (home / ".codex" / "hooks.json").unlink()
        config = home / ".codex" / "config.toml"
        config.write_text("model = [", encoding="utf-8")
        refuses("broken TOML", v1, ".codex/config.toml is not valid TOML", tools)
        user_config = 'model = "mine"\n'
        config.write_text(user_config, encoding="utf-8")
        # A JSON object whose hooks the merge can't read stops before the payload is replaced (install review, 2026-11-05).
        kept_settings = settings.read_text(encoding="utf-8")
        settings.write_text(json.dumps({"hooks": {"PreToolUse": "invalid"}}), encoding="utf-8")
        refuses("unmergeable hooks", v1, ".claude/settings.json has hooks or permissions the installer cannot merge", tools)
        settings.write_text(kept_settings, encoding="utf-8")
        (home / ".agents").mkdir()
        (base / "elsewhere").mkdir()
        (home / ".agents" / "bin").symlink_to(base / "elsewhere")
        refuses("a symlinked folder", v1, "~/.agents/bin is a symlink", tools)
        (home / ".agents" / "bin").unlink()
        (home / ".agents").rmdir()

        before = tree(home)
        dry = ok(v1, "--dry-run")
        if tree(home) != before or "install .claude/CLAUDE.md" not in dry.stdout or "merge   .codex/config.toml" not in dry.stdout:
            raise ValueError(f"install.py --dry-run changed files or said nothing: {dry.stdout}")

        # First install: instructions replaced with a backup, the user's files and settings kept.
        first = ok(v1)
        backups = sorted((home / ".agent-config-backup").iterdir())
        if len(backups) != 1 or (backups[0] / ".claude" / "CLAUDE.md").read_text(encoding="utf-8") != "my rules\n":
            raise ValueError(f"install.py must back up replaced instructions: {first.stdout}")
        if (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8") != "setup rules\n":
            raise ValueError("install.py must replace the global instructions")
        if not (home / ".claude" / "skills" / "mine" / "SKILL.md").is_file():
            raise ValueError("install.py removed the user's own skill")
        if not os.access(home / ".agents" / "bin" / "tool", os.X_OK):
            raise ValueError("install.py lost a tool's executable bit")
        if "caf\u00e9" not in settings.read_text(encoding="utf-8"):
            raise ValueError("install.py must keep the user's UTF-8 text unescaped in settings.json")
        merged = json.loads(settings.read_text(encoding="utf-8"))
        if merged["model"] != "mine" or merged["env"] != {"KEEP": "1", "CLAUDE_CODE_PLUGIN_DIRS": "~/.claude/mods/console"}:
            raise ValueError(f"install.py mangled settings: {merged}")
        if commands(".claude/settings.json") != ["mine.sh", 'bash "$HOME/.claude/hooks/one.sh"']:
            raise ValueError(f"install.py merged hooks wrongly: {commands('.claude/settings.json')}")
        if commands(".codex/hooks.json") != ['bash "$HOME/.codex/hooks/one.sh"']:
            raise ValueError("install.py must create the Codex hooks file")
        if settings.stat().st_mode & 0o777 != 0o640:
            raise ValueError("install.py changed the settings file's mode")

        def grants() -> tuple[list[str], list[str]]:
            allow = json.loads(settings.read_text(encoding="utf-8")).get("permissions", {}).get("allow", [])
            toml = tomllib.loads(config.read_text(encoding="utf-8"))
            return sorted(allow), toml.get("sandbox_workspace_write", {}).get("writable_roots", [])

        both = (sorted(["Bash(ls)", rule(scratch_root), rule(records_root)]), [scratch_root, records_root])
        if grants() != both or \
                tomllib.loads(config.read_text(encoding="utf-8"))["model"] != "mine" or "claude-codex-setup" not in config.read_text(encoding="utf-8"):
            raise ValueError(f"install.py must add the write grants and keep the user's settings: {grants()} {config.read_text(encoding='utf-8')}")

        # A rerun of the same bundle changes nothing, not even a backup.
        # A state file from the shell installer has no grants; it reads as none owned.
        state_file = home / ".agents" / "setup-state.json"
        recorded = state_file.read_text(encoding="utf-8")
        state_file.write_text(json.dumps({k: v for k, v in json.loads(recorded).items() if k != "grants"}), encoding="utf-8")
        again = ok(v1)
        state_file.write_text(recorded, encoding="utf-8")
        if "already up to date (one)" not in again.stdout or len(list((home / ".agent-config-backup").iterdir())) != 1:
            raise ValueError(f"a rerun of the same bundle must change nothing: {again.stdout}")
        if commands(".claude/settings.json").count('bash "$HOME/.claude/hooks/one.sh"') != 1 or grants() != both:
            raise ValueError("a rerun duplicated a hook registration or a grant")

        # Python tools name the interpreter the installer ran under (the PATH entry, not its realpath) and nothing else.
        pytool, module = home / ".agents" / "bin" / "pytool", home / ".agents" / "bin" / "lib" / "module.py"
        if pytool.read_text(encoding="utf-8") != f"#!{tools}/python3\nprint(1)\n" or module.read_text(encoding="utf-8") != "#!/usr/bin/env python3\n":
            raise ValueError(f"install.py must pin the top-level python tools only: {pytool.read_text(encoding='utf-8')!r}")
        other = base / "other"
        other.mkdir()
        (other / "python3").symlink_to(sys.executable)
        (other / "bd").symlink_to(fake_bd)
        repinned = run(v1, path=other)
        if repinned.returncode != 0 or "install .agents/bin/pytool" not in repinned.stdout or \
                pytool.read_text(encoding="utf-8") != f"#!{other}/python3\nprint(1)\n":
            raise ValueError(f"a rerun under another python must re-pin: {repinned.stdout}{repinned.stderr}")
        unlisted = base / "unlisted"
        unlisted.mkdir()
        (unlisted / "bd").symlink_to(fake_bd)
        fallback = run(v1, path=unlisted)
        if f"pinned to {sys.executable}" not in fallback.stderr or pytool.read_text(encoding="utf-8") != f"#!{sys.executable}\nprint(1)\n":
            raise ValueError(f"without a PATH entry the pin falls back to the running python with a note: {fallback.stderr}")
        ok(v1)
        if pytool.read_text(encoding="utf-8") != f"#!{tools}/python3\nprint(1)\n":
            raise ValueError("a rerun under the first python must pin it again")
        # An unversioned python3 anywhere on PATH is pinned before a python3.N; a lone python3.N is pinned with a note.
        minor = f"python3.{sys.version_info[1]}"
        versioned, plain, only = base / "versioned", base / "plain", base / "only"
        for folder in (versioned, plain, only):
            folder.mkdir()
            (folder / "bd").symlink_to(fake_bd)
        (versioned / minor).symlink_to(sys.executable)
        (plain / "python3").symlink_to(sys.executable)
        (only / minor).symlink_to(sys.executable)
        preferred = run(v1, path=f"{versioned}:{plain}")
        if preferred.returncode != 0 or pytool.read_text(encoding="utf-8") != f"#!{plain}/python3\nprint(1)\n" or "versioned" in preferred.stderr:
            raise ValueError(f"an unversioned python3 later on PATH beats a python3.N: {preferred.stderr}")
        lone = run(v1, path=only)
        if pytool.read_text(encoding="utf-8") != f"#!{only}/{minor}\nprint(1)\n" or f"versioned {only}/{minor}" not in lone.stderr:
            raise ValueError(f"a lone python3.N is pinned with a note: {lone.stderr}")
        spaced = base / "with space"
        spaced.mkdir()
        (spaced / "python3").symlink_to(sys.executable)
        (spaced / "bd").symlink_to(fake_bd)
        refuses("a python3 path with a space", v1, "holds a space", spaced)
        ok(v1)

        # Upgrade: what the last install shipped and this one doesn't goes; the user's additions stay.
        (home / ".claude" / "skills" / "kept" / "note.md").write_text("my note\n", encoding="utf-8")
        v2_files = {
            ".agents/bin/pytool": "#!/usr/bin/env python3\nprint(1)\n",
            ".agents/bin/lib/module.py": "#!/usr/bin/env python3\n",
            ".claude/CLAUDE.md": "new rules\n",
            ".codex/AGENTS.md": "new rules\n",
            ".claude/skills/kept/SKILL.md": "kept\n",
            ".agents/bin/tool": "#!/bin/sh\n",
            ".claude/mods/console/.claude-plugin/plugin.json": "{}\n",
        }
        v2 = bundle(base, "v2", "two", v2_files, 'bash "$HOME/.claude/hooks/two.sh"', 'bash "$HOME/.codex/hooks/two.sh"',
                    grant_entries="".join(entries[k] for k in ("scratch", "records", "extra")))
        # A leftover or planted `<file>.new` never redirects the settings or state write (install review, 2026-11-05).
        outside = base / "outside"
        outside.write_text("keep\n", encoding="utf-8")
        planted = [home / ".claude" / "settings.json.new", home / ".agents" / "setup-state.json.new"]
        for link in planted:
            link.symlink_to(outside)
        ok(v2)
        if outside.read_text(encoding="utf-8") != "keep\n" or settings.is_symlink() or (home / ".agents" / "setup-state.json").is_symlink():
            raise ValueError("install.py must write settings and state through files of its own, not a planted .new")
        for link in planted:
            link.unlink()
        if (home / ".claude" / "skills" / "kept" / "dropped.md").exists() or (home / ".claude" / "skills" / "gone").exists():
            raise ValueError("an upgrade must remove what it no longer ships, and the emptied folder")
        if (home / ".claude" / "skills" / "kept" / "note.md").read_text(encoding="utf-8") != "my note\n":
            raise ValueError("an upgrade removed the user's file inside a shipped folder")
        if commands(".claude/settings.json") != ["mine.sh", 'bash "$HOME/.claude/hooks/two.sh"']:
            raise ValueError(f"an upgrade must swap the setup's hooks: {commands('.claude/settings.json')}")
        if commands(".codex/hooks.json") != ['bash "$HOME/.codex/hooks/two.sh"']:
            raise ValueError("an upgrade must swap the Codex hooks")
        grown = (sorted(["Bash(ls)", *map(rule, (scratch_root, records_root, extra_root))]), [scratch_root, records_root, extra_root])
        if grants() != grown:
            raise ValueError(f"an upgrade whose list adds a root must apply it: {grants()}")
        # A list that drops a root removes its grant and keeps the user's own rule; the next list adds it back.
        v3 = bundle(base, "v3", "three", v2_files, 'bash "$HOME/.claude/hooks/two.sh"', 'bash "$HOME/.codex/hooks/two.sh"',
                    grant_entries=entries["scratch"] + entries["extra"])
        ok(v3)
        if grants() != (sorted(["Bash(ls)", rule(scratch_root), rule(extra_root)]), [scratch_root, extra_root]):
            raise ValueError(f"an upgrade whose list drops a root must remove its grant: {grants()}")
        ok(v2)
        if grants() != grown:
            raise ValueError(f"an upgrade must add a dropped root back: {grants()}")
        removed = [path for backup in (home / ".agent-config-backup").iterdir() for path in backup.rglob("dropped.md")]
        if not removed:
            raise ValueError("an upgrade must back up what it removes")

        # Without the mod: its files, API types and setting go.
        types = home / ".claude" / "mods" / "console" / ".claude-plugin" / "types"
        types.mkdir(parents=True)
        (types / "index.d.ts").write_text("laid by Claude\n", encoding="utf-8")
        ok(v2, "--no-mod")
        if (home / ".claude" / "mods").exists() and any((home / ".claude" / "mods").iterdir()):
            raise ValueError("--no-mod must remove an installed mod")
        if "CLAUDE_CODE_PLUGIN_DIRS" in json.loads(settings.read_text(encoding="utf-8"))["env"]:
            raise ValueError("--no-mod must clear the mod's setting")

        # A setting holding other plugin folders is the user's to edit.
        ok(v2)
        current = json.loads(settings.read_text(encoding="utf-8"))
        current["env"]["CLAUDE_CODE_PLUGIN_DIRS"] = "~/other"
        settings.write_text(json.dumps(current), encoding="utf-8")
        note = ok(v2)
        if "add ~/.claude/mods/console to it by hand" not in note.stderr or \
                json.loads(settings.read_text(encoding="utf-8"))["env"]["CLAUDE_CODE_PLUGIN_DIRS"] != "~/other":
            raise ValueError(f"install.py must leave another plugin folder setting alone: {note.stderr}")
        current["env"]["CLAUDE_CODE_PLUGIN_DIRS"] = "~/.claude/mods/console"
        settings.write_text(json.dumps(current), encoding="utf-8")

        # A damaged state file never reaches outside the install's folders.
        state = home / ".agents" / "setup-state.json"
        intact = state.read_text(encoding="utf-8")
        victim = home / "victim"
        victim.write_text("keep\n", encoding="utf-8")
        for entry in ("../victim", ".claude/../../victim", "victim", "/etc/hosts"):
            state.write_text(json.dumps({**json.loads(intact), "files": [entry]}), encoding="utf-8")
            refuses(f"the state entry {entry}", v2, "lists a path outside", tools)
        state.write_text(intact, encoding="utf-8")
        victim.unlink()

        # A target that is no regular file stops the plan, dry-run included, before anything is installed.
        state.write_text(json.dumps({**json.loads(intact), "files": [".claude/skills"]}), encoding="utf-8")
        refuses("a state entry naming a folder", v2, "~/.claude/skills is not a regular file", tools)
        state.write_text(intact, encoding="utf-8")
        shipped_file = home / ".claude" / "CLAUDE.md"
        shipped_file.rename(shipped_file.with_name("CLAUDE.md.away"))
        shipped_file.mkdir()
        refuses("a shipped file that exists as a folder", v2, "~/.claude/CLAUDE.md is not a regular file", tools)
        dry_run = run(v2, "--dry-run")
        if dry_run.returncode == 0:
            raise ValueError("--dry-run must refuse what the real run refuses")
        shipped_file.rmdir()
        shipped_file.with_name("CLAUDE.md.away").rename(shipped_file)

        # An unusable HOME stops at once.
        for value in ("", "/", "//", "/.", "relative", str(base / "no-such-home")):
            result = subprocess.run([sys.executable, str(v2 / "install.py"), "--dry-run"], capture_output=True, text=True, check=False,
                                    stdin=subprocess.DEVNULL, env={"HOME": value, "PATH": str(tools)})
            if result.returncode == 0 or "HOME is" not in result.stderr:
                raise ValueError(f"install.py must stop on HOME={value!r}: {result.returncode} {result.stderr}")

        # A file target that is a symlink stays, and nothing changes.
        rules = home / ".claude" / "CLAUDE.md"
        rules.unlink()
        rules.symlink_to(base / "elsewhere")
        refuses("a symlinked file", v2, "~/.claude/CLAUDE.md is a symlink", tools)
        rules.unlink()
        rules.write_text("new rules\n", encoding="utf-8")

        # Uninstall: the setup's files, hooks, setting and state go; the user's stay.
        before = tree(home)
        ok(v2, "--uninstall", "--dry-run")
        if tree(home) != before:
            raise ValueError("--uninstall --dry-run changed files")
        ok(v2, "--uninstall")
        for gone in (".claude/CLAUDE.md", ".codex/AGENTS.md", ".agents/bin/tool", ".agents/setup-state.json", ".claude/skills/kept/SKILL.md"):
            if (home / gone).exists():
                raise ValueError(f"--uninstall left {gone}")
        if not (home / ".claude" / "skills" / "kept" / "note.md").is_file() or not (home / ".claude" / "skills" / "mine" / "SKILL.md").is_file():
            raise ValueError("--uninstall removed the user's files")
        final = json.loads(settings.read_text(encoding="utf-8"))
        if commands(".claude/settings.json") != ["mine.sh"] or final["env"] != {"KEEP": "1"} or final["model"] != "mine":
            raise ValueError(f"--uninstall must leave only the user's settings: {final}")
        if commands(".codex/hooks.json"):
            raise ValueError("--uninstall left Codex hooks")
        if grants() != (sorted(["Bash(ls)", rule(scratch_root)]), []) or config.read_text(encoding="utf-8") != user_config:
            raise ValueError(f"--uninstall must remove the grants it added and keep the user's: {grants()} {config.read_text(encoding='utf-8')!r}")

        # A Codex table of the user's own is never edited: the installer names the roots to add.
        own_table = 'model = "mine"\n\n[sandbox_workspace_write]\nwritable_roots = ["' + scratch_root + '"]\n'
        config.write_text(own_table, encoding="utf-8")
        noted = ok(v2)
        if f"add {records_root}, {extra_root} to sandbox_workspace_write.writable_roots" not in noted.stderr or config.read_text(encoding="utf-8") != own_table:
            raise ValueError(f"install.py must leave the user's sandbox_workspace_write alone and say what to add: {noted.stderr}")

        # A symlinked config.toml is the user's too.
        linked = base / "elsewhere" / "config.toml"
        linked.write_text(user_config, encoding="utf-8")
        config.unlink()
        config.symlink_to(linked)
        noted = ok(v2)
        if "(it is a symlink)" not in noted.stderr or linked.read_text(encoding="utf-8") != user_config:
            raise ValueError(f"install.py must not edit a symlinked config.toml: {noted.stderr}")

        # A CRLF file keeps its line endings through the merge and the removal.
        crlf = b'model = "mine"\r\n'
        config.unlink()
        config.write_bytes(crlf)
        ok(v2)
        merged_bytes = config.read_bytes()
        if b"claude-codex-setup" not in merged_bytes or merged_bytes.count(b"\n") != merged_bytes.count(b"\r\n"):
            raise ValueError(f"install.py must keep CRLF line endings: {merged_bytes!r}")
        # Our block in a file that became a symlink, or edited by the user, is named for removal, never touched.
        linked.write_bytes(merged_bytes)
        config.unlink()
        config.symlink_to(linked)
        left = ok(v2, "--uninstall")
        if "remove the claude-codex-setup block" not in left.stderr or "it is a symlink" not in left.stderr or linked.read_bytes() != merged_bytes:
            raise ValueError(f"--uninstall must name our block in a symlinked config.toml: {left.stderr}")
        config.unlink()
        config.write_bytes(merged_bytes + b"extra = 1\r\n")
        left = ok(v2, "--uninstall")
        if "it was edited" not in left.stderr or config.read_bytes() != merged_bytes + b"extra = 1\r\n":
            raise ValueError(f"--uninstall must name an edited block and leave it: {left.stderr}")
        config.write_bytes(crlf)
        ok(v2)
        ok(v2, "--uninstall")
        if config.read_bytes() != crlf:
            raise ValueError(f"--uninstall must restore the user's config.toml byte for byte: {config.read_bytes()!r}")
        # A config.toml the installer created goes with its block; an empty permissions object of the user's stays.
        config.unlink()
        ok(v2)
        ok(v2, "--uninstall")
        if config.exists():
            raise ValueError("--uninstall must remove a config.toml the installer created")
        settings.write_text('{"permissions": {}}\n', encoding="utf-8")
        ok(v2, "--uninstall")
        if settings.read_text(encoding="utf-8") != '{"permissions": {}}\n':
            raise ValueError(f"--uninstall must not touch what it never added: {settings.read_text(encoding='utf-8')}")


def validate_hook_registrations(root: Path) -> None:
    """The Claude and Codex hook configs beside the agents root (absent from the store copy the build checks):
    session-activity runs on SubagentStart, SubagentStop and every tool's PreToolUse (a group without matcher),
    and every registered hook script exists under the agents' or the tool's own hooks/."""
    configs = {"claude": root.parent / "claude" / "settings.json", "codex": root.parent / "codex" / "hooks.json"}
    for tool, path in configs.items():
        if not path.is_file():
            continue
        events = json.loads(path.read_text(encoding="utf-8"))["hooks"]
        command = f'bash "$HOME/.{tool}/hooks/session-activity.sh"'
        for event in ("SubagentStart", "SubagentStop", "PreToolUse"):
            groups = [group for group in events.get(event, []) if "matcher" not in group
                      and any(hook.get("command") == command and "if" not in hook for hook in group.get("hooks", []))]
            if len(groups) != 1:
                raise ValueError(f"{path}: {event} needs one all-tools group running {command}")
        for group in (group for groups in events.values() for group in groups):
            for hook in group.get("hooks", []):
                for name in re.findall(rf'\$HOME/\.{tool}/hooks/([\w.-]+)', hook.get("command", "")):
                    if not any((directory / "hooks" / name).is_file() for directory in (root, path.parent)):
                        raise ValueError(f"{path} runs hooks/{name}, which does not exist")


def validate_agent_grants(root: Path) -> None:
    """The installer's grant list names the folders the tools write outside repositories: bin/scratch's root and the
    board-less decision records of protocol_engine/cli.py, both under their own agents/ folder. (This machine's own
    settings.json and config.toml are not compared with it.)"""
    spec = importlib.util.spec_from_file_location("setup_install", root / "setup" / "install.py")
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    with tempfile.TemporaryDirectory() as directory:
        home = os.path.realpath(directory)
        roots = installer.grant_roots(home, {})
        if roots != ["~/.local/state/agents/scratch", "~/.local/share/agents/decisions"]:
            raise ValueError(f"install.py grants resolve to {roots}")
        moved = installer.grant_roots(home, {"XDG_STATE_HOME": home + "/s", "XDG_DATA_HOME": "/srv/d"})
        if moved != ["~/s/agents/scratch", "/srv/d/agents/decisions"] or installer.edit_rule(moved[1]) != "Edit(//srv/d/agents/decisions/**)":
            raise ValueError(f"install.py must follow XDG_STATE_HOME and XDG_DATA_HOME: {moved}")
        loader = importlib.machinery.SourceFileLoader("scratch_grants", str(root / "bin" / "scratch"))
        scratch = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(scratch)
        saved = {key: os.environ.pop(key, None) for key in ("XDG_STATE_HOME", "XDG_DATA_HOME")}
        os.environ["HOME"], previous = home, os.environ.get("HOME")
        try:
            tool_scratch = str(scratch.root())
        finally:
            os.environ["HOME"] = previous
            os.environ.update({key: value for key, value in saved.items() if value is not None})
        if tool_scratch != roots[0].replace("~", home, 1):
            raise ValueError(f"bin/scratch writes to {tool_scratch}, not the granted {roots[0]}")
    records = (root / "bin" / "protocol_engine" / "cli.py").read_text(encoding="utf-8")
    if "call.env.get('XDG_DATA_HOME', '')" not in records or "/ '.local' / 'share'" not in records or \
            "Path(data) / 'agents' / 'decisions'" not in records:
        raise ValueError("protocol_engine/cli.py default_records moved: update GRANT_ROOTS in setup/install.py")
    if any(root_.split("/")[-2] != "agents" for root_ in roots):
        raise ValueError(f"every grant belongs under an agents/ folder: {roots}")


def validate_hooks(root: Path) -> None:
    hooks = root / "hooks"
    validate_hook_registrations(root)
    validate_agent_grants(root)
    validate_setup_portable(root)
    validate_setup_installer(root)
    validate_session_registry(root)
    validate_session_register(root)
    validate_compact_reorient(root)
    validate_bd_guard(root)

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


def validate_shared_board(root: Path) -> None:
    """Shared-board rules with bd faked; bin/test-shared-board.py runs the same behaviour through real clones, which the
    build sandbox can't."""
    import contextlib
    import io
    from types import SimpleNamespace
    from unittest.mock import patch

    loader = importlib.machinery.SourceFileLoader("board_shared", str(root / "bin" / "board"))
    board = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(board)

    def expect(ok: bool, what: str, detail: object = "") -> None:
        if not ok:
            raise ValueError(f"shared board: {what}: {detail}")

    for given, wanted in (("git@github.com:me/x.git", "git+ssh://git@github.com/me/x.git"),
                          ("https://github.com/me/x", "git+ssh://git@github.com/me/x.git"),
                          ("https://github.com/me/x.git", "git+ssh://git@github.com/me/x.git"),
                          ("ssh://git@host/me/x.git", "git+ssh://git@host/me/x.git"),
                          ("git+ssh://git@host/me/x.git", "git+ssh://git@host/me/x.git"),
                          ("/tmp/x.git", "git+file:///tmp/x.git"), ("file:///tmp/x.git", "git+file:///tmp/x.git")):
        expect(board.normalized_remote(given) == wanted, "normalized_remote", (given, board.normalized_remote(given)))

    def item(item_id, *labels, parents=(), status="open", kind="task", blockers=()):
        deps = [{"issue_id": item_id, "depends_on_id": p, "type": "parent-child"} for p in parents] \
            + [{"issue_id": item_id, "depends_on_id": b, "type": "blocks"} for b in blockers]
        return {"id": item_id, "title": item_id, "status": status, "issue_type": kind, "labels": list(labels), "dependencies": deps}

    issues = [item("top", "queue:anna"), item("kid", parents=["top"]), item("grandkid", parents=["kid"]),
              item("other", "queue:ben"), item("own", "queue:ben", parents=["top"]), item("bare"),
              item("two", parents=["top", "other"]), item("twolabels", "queue:anna", "queue:ben"), item("gate", kind="gate"),
              item("waits", parents=["top"], blockers=["other"]), item("orphan", parents=["closed-parent"])]
    snapshot = board.Board(issues, complete=False)
    outside = {"closed-parent": {"id": "closed-parent", "labels": ["queue:anna"], "dependencies": []}}
    with patch.object(board, "bd_show", lambda ids, *flags, **options: [outside[i] for i in ids if i in outside]):
        for item_id, queue in (("top", "anna"), ("kid", "anna"), ("grandkid", "anna"), ("own", "ben"), ("bare", None), ("two", None),
                               ("twolabels", None), ("orphan", "anna")):
            expect(snapshot.queue(item_id) == queue, "queue of", (item_id, snapshot.queue(item_id)))
        expect(snapshot.queues("two") == ["anna", "ben"], "disagreeing parents are named", snapshot.queues("two"))
        snapshot.view = "anna"
        expect({i["id"] for i in snapshot.listed(None)} == {"top", "kid", "grandkid", "waits", "orphan"}, "listed", snapshot.listed(None))
        summary = board.queue_summary(snapshot, None)
        expect(summary["others"] == {"ben": 2}, "others", summary["others"])
        expect({i["id"] for i in summary["unrouted"]} == {"bare", "two", "twolabels"}, "unrouted leaves gates out", summary["unrouted"])
        expect([i["id"] for i in summary["blocking"]] == ["other"], "blocking", summary["blocking"])
        snapshot.view = None
        expect(board.queue_summary(snapshot, None) is None, "no filter, no summary")

        with patch.object(board, "shared", SimpleNamespace()), patch.object(board, "person", lambda: "anna"):
            expect(board.foreign_claim(snapshot, "kid") is None, "own queue claims")
            refusal = board.foreign_claim(snapshot, "bare") or ""
            expect("unrouted" in refusal and "board route <person> bare" in refusal, "an unrouted item is refused until routed", refusal)
            refusal = board.foreign_claim(snapshot, "other")
            expect("ben's queue" in refusal and "board route anna other" in refusal, "a claim across queues names the route", refusal)
        with patch.object(board, "shared", None):
            expect(board.foreign_claim(snapshot, "other") is None, "an unshared board has no queues")

    # The inbox (r37-q207): unrouted rows with age and for:, items for you first, oldest first; finds held for your person.
    def aged(item_id, created, *labels, assignee=None):
        return {**item(item_id, *labels), "created_at": created, **({"assignee": assignee} if assignee else {})}

    inbox = board.Board([aged("old", "2026-01-01T00:00:00Z"), aged("forme", "2026-03-01T00:00:00Z", "for:anna"),
                         aged("forben", "2026-02-01T00:00:00Z", "for:ben"), aged("find", "2026-01-05T00:00:00Z", "queue:anna", "for:ben", assignee="user"),
                         aged("plainhold", "2026-01-05T00:00:00Z", "queue:anna", assignee="user")], complete=False)
    inbox.view = "anna"
    summary = board.queue_summary(inbox, None)
    expect([i["id"] for i in summary["unrouted"]] == ["forme", "old", "forben"], "unrouted: for you first, then oldest", summary["unrouted"])
    expect("1 for you" in (board.queue_line(inbox, None) or ""), "the console line counts the items for you", board.queue_line(inbox, None))
    shown = io.StringIO()
    with contextlib.redirect_stdout(shown):
        board.queue_rows(inbox, None, "health")
    row = next((r for r in shown.getvalue().splitlines() if "forben" in r), "")
    expect("for:ben" in row and " old" in row, "an unrouted row names for: and its age", shown.getvalue())
    queues = board.queues_json(inbox, None)["queues"]
    expect([i["id"] for i in queues["inbox"]] == ["forme"] and [i["id"] for i in queues["toSend"]] == ["find"], "--json inbox and held finds", queues)
    # r38-q217: an inbox item waits since `board send` stamped sent_at; others since created. Rows and JSON say which.
    waiting = board.Board([aged("old", "2026-01-01T00:00:00Z"), {**aged("sentlate", "2025-12-01T00:00:00Z", "for:ben"), "metadata": {"sent_at": "2026-02-01T00:00:00Z"}},
                           aged("unstamped", "2025-12-15T00:00:00Z", "for:ben")], complete=False)
    waiting.view = "anna"
    expect([i["id"] for i in board.queue_summary(waiting, None)["unrouted"]] == ["unstamped", "old", "sentlate"], "unrouted: oldest wait first, an inbox item by its send", board.queue_summary(waiting, None)["unrouted"])
    shown = io.StringIO()
    with contextlib.redirect_stdout(shown):
        board.queue_rows(waiting, None, "health")
    rows = {item_id: next((r for r in shown.getvalue().splitlines() if item_id in r), "") for item_id in ("old", "sentlate")}
    expect(" ago" in rows["sentlate"] and "sent " in rows["sentlate"] and " old" in rows["old"] and "sent " not in rows["old"], "rows: time since sent, else age", rows)
    unrouted = {i["id"]: i for i in board.queues_json(waiting, None)["queues"]["unrouted"]}
    expect(unrouted["sentlate"]["waitingSince"] == "2026-02-01T00:00:00Z" and unrouted["old"]["waitingSince"] == "2026-01-01T00:00:00Z"
           and unrouted["unstamped"]["waitingSince"] == "2025-12-15T00:00:00Z", "--json: waitingSince", unrouted)

    # create: one rewrite on every board, the top-level label only on a shared one.
    parent = [{"id": "fx-p", "labels": ["topic:a", "queue:ben"]}]
    with patch.object(board, "bd_show", lambda ids, *flags: parent), patch.object(board, "shared", None):
        for given in (["t", "--parent", "fx-p"], ["t", "--parent=fx-p"]):
            expect(board.rewritten_create("create", given) == ["create", "t", "--deps", "parent-child:fx-p", "--labels", "topic:a"],
                   "create --parent", board.rewritten_create("create", given))
        try:
            board.rewritten_create("q", ["t", "--parent", "fx-p"])
            raise ValueError("shared board: q --parent must be refused")
        except board.BoardError as error:
            expect("board bd create" in str(error), "q --parent names create", error)
        expect("--labels" not in board.rewritten_create("create", ["t", "--parent", "fx-p", "--no-inherit-labels"]), "--no-inherit-labels")
        expect(board.rewritten_create("create", ["t", "-l", "topic:a", "--parent", "fx-p"]).count("topic:a") == 1, "a label not repeated")
        expect(board.rewritten_create("create", ["t"]) == ["create", "t"], "an unshared top-level item stays bare")
        expect(board.rewritten_create("list", ["--all"]) == ["list", "--all"], "other commands stay as they are")
    with patch.object(board, "bd_show", lambda ids, *flags: []), patch.object(board, "shared", None):
        try:
            board.rewritten_create("create", ["t", "--parent", "fx-none"])
            raise ValueError("shared board: an unknown parent must fail")
        except board.BoardError:
            pass
    with patch.object(board, "shared", SimpleNamespace()), patch.object(board, "person", lambda: "anna"):
        expect(board.rewritten_create("create", ["t"]) == ["create", "t", "--labels", "queue:anna"], "a top-level item takes its creator")
        expect(board.rewritten_create("create", ["t", "-l", "queue:ben"]) == ["create", "t", "-l", "queue:ben"], "an explicit queue stays")
        with tempfile.TemporaryDirectory() as directory:
            plan = Path(directory) / "plan.json"
            plan.write_text(json.dumps({"nodes": [{"key": "x", "title": "x"}, {"key": "y", "title": "y", "parent": "x"}]}), encoding="utf-8")
            command = board.rewritten_create("create", ["--graph", str(plan)])
            nodes = json.loads(Path(command[command.index("--graph") + 1]).read_text(encoding="utf-8"))["nodes"]
            expect(nodes[0]["labels"] == ["queue:anna"] and "labels" not in nodes[1], "a graph labels its parentless nodes", nodes)

    # Moves: who may, and what counts.
    snapshot = board.Board(issues, complete=False)
    with patch.object(board, "shared", SimpleNamespace()), patch.object(board, "person", lambda: "anna"), \
            patch.object(board.Board, "load", classmethod(lambda cls, scope="status", ids=None: snapshot)), patch.object(board, "may_move", lambda: False):
        for command, rest in (("label", ["add", "top", "queue:ben"]), ("label", ["remove", "top", "queue:anna"]),
                              ("label", ["propagate", "top", "queue:anna"]), ("update", ["top", "--add-label", "queue:ben"]),
                              ("update", ["top", "--add-label=queue:ben"]), ("update", ["top", "--remove-label", "queue:anna"]),
                              ("update", ["top", "--set-labels", "x:y"]), ("update", ["kid", "--parent", "other"]),
                              ("dep", ["add", "kid", "other", "--type", "parent-child"]), ("dep", ["remove", "kid", "top"]),
                              ("sql", ["delete from labels where 1=1"]), ("create", ["t", "-l", "queue:ben"])):
            expect("only lead and solo" in (board.queue_guard(command, rest) or ""), "a move is refused", (command, rest))
        for command, rest in (("label", ["add", "top", "topic:x"]), ("update", ["top", "--add-label", "topic:x"]),
                              ("update", ["top", "--set-labels", "queue:anna,x:y"]), ("update", ["own", "--parent", "top"]),
                              ("dep", ["add", "top", "other"]), ("dep", ["remove", "top", "other"]),
                              ("sql", ["select * from labels"]), ("create", ["t", "-l", "queue:anna"]), ("comments", ["add", "x", "queue:ben"])):
            expect(board.queue_guard(command, rest) is None, "not a move", (command, rest))
        expect("ben's queue" in (board.queue_guard("update", ["other", "--claim"]) or ""), "update --claim across queues")
        expect("ids first" in (board.queue_guard("update", ["--claim", "other"]) or ""), "flags before the ids fail closed")
        expect(board.queue_guard("create", ["--graph", "/nonexistent/plan.json"]) is None, "an unreadable plan is bd's to report")
    with patch.object(board, "shared", SimpleNamespace()), patch.object(board, "person", lambda: "anna"), \
            patch.object(board.Board, "load", classmethod(lambda cls, scope="status", ids=None: snapshot)), patch.object(board, "may_move", lambda: True):
        expect(board.queue_guard("label", ["add", "top", "queue:ben"]) is None, "a lead moves")
    expect(board.bd_env().get("BD_NO_REMOTE_ADOPT") == "1", "board stops bd adopting git origin on every call")
    for argv, writes in ((["health"], False), (["show", "x"], False), (["bd", "list"], False), (["bd", "--json", "ready"], False), (["claim"], True),
                         (["bd", "create", "t"], True), (["route", "ben", "x"], True), (["send", "ben", "x"], True), (["create", "--for", "ben", "t"], True),
                         (["join"], False), (["bd", "dolt", "status"], False)):
        expect(board.writes(argv) == writes, "which commands write", argv)
    entries = [{"actor": "lead0001", "role": "lead"}, {"actor": "solo0001", "role": "solo"}, {"actor": "agnt0001", "role": "agent"}]
    with patch.object(board, "registrations", lambda: (entries, set())):
        for actor, allowed in (("lead0001", True), ("solo0001", True), ("agnt0001", False), ("gone0001", False), ("lead0001/wrkr", False), (None, True)):
            with patch.object(board, "derived_actor", lambda: actor):
                expect(board.may_move() == allowed, "may_move", actor)

    # The retry: this one error on a shared board, counted on stderr; never a stopped merge, never unshared.
    def attempts(message, is_shared, code=1):
        calls, errors = [], io.StringIO()

        def fake_run(command, **kwargs):
            calls.append(command)
            return subprocess.CompletedProcess(command, code if len(calls) == 1 else 0, "", message)

        with patch.object(board.subprocess, "run", fake_run), patch.object(board, "ensure_server", lambda *a: None), \
                patch.object(board, "bd_env", lambda: {}), patch.object(board.time, "sleep", lambda s: None), \
                patch.object(board, "shared", SimpleNamespace() if is_shared else None), contextlib.redirect_stderr(errors):
            board.bd("create", "t")
        return len(calls), errors.getvalue()

    count, said = attempts("Error: foreign key conflicts on commit", True)
    expect(count == 2 and "retry 1 of 4" in said, "the write retry", (count, said))
    expect(attempts("Error: Merge conflict detected", True)[0] == 1, "a stopped merge is not retried")
    expect(attempts("Error: foreign key conflicts", False)[0] == 1, "an unshared board does not retry")

    # What a command reports, and the reachable state of the wait's locks and files.
    with tempfile.TemporaryDirectory() as directory:
        beads = Path(directory) / ".beads"
        (beads / "dolt" / "db" / ".dolt").mkdir(parents=True)
        (beads / "metadata.json").write_text(json.dumps({"dolt_mode": "server", "dolt_database": "db"}), encoding="utf-8")
        (beads / "dolt" / "db" / ".dolt" / "repo_state.json").write_text(json.dumps({"remotes": {"origin": {"url": "v"}}}), encoding="utf-8")

        def no_process(*args, **kwargs):
            raise AssertionError("a process started")

        with patch.object(board.subprocess, "run", no_process), patch.object(board.subprocess, "Popen", no_process):
            expect(board.find_shared(Path(directory)) is None, "a remote alone does not share: only board's mark, read with no process")
        board.write_mark(beads, "origin")
        sharing = board.find_shared(Path(directory))
        expect(sharing is not None and sharing.remote == "origin", "the mark shares the board, naming its remote")
        expect(sharing.moved() is None, "not moved")
        sharing.update_state(moved="git+ssh://git@host/new.git")
        expect("board join git+ssh://git@host/new.git" in (sharing.problem() or ""), "a moved board reports the join", sharing.problem())
        expect("board join git+ssh://git@host/new.git" in board.moved_refusal("git+ssh://git@host/new.git"), "a moved board refuses writes with the join")
        sharing.update_state(moved=None)
        expect(sharing.problem() is None, "no state, no problem")
        sharing.failed("no route")
        sharing.failed("no route")
        expect(sharing.problem() is None, "single failures stay quiet", sharing.state())
        sharing.failed("no route")
        expect("sync failing, 3 tries: no route" in sharing.problem() and "Fix:" in sharing.problem(), "repeated failures report", sharing.problem())
        sharing.succeeded()
        expect(sharing.problem() is None and not sharing.state().get("failures"), "a success clears them")
        sharing.failed("", "conflict")
        expect(all(word in sharing.problem() for word in ("bd conflicts resolve", "CALL DOLT_MERGE", "bd rename")), "a conflict's fixes", sharing.problem())
        sharing.succeeded()
        sharing.failed("a sync ran over 300 s", "stuck")
        expect("sync stuck" in sharing.problem(), "a stuck sync reports at once", sharing.problem())
        sharing.succeeded()
        sharing.update_state(store_bytes=board.STORE_WARN_BYTES)
        expect("flatten" in sharing.store_warning(), "the store warning", sharing.store_warning())
        held = sharing.lock("wait.lock")
        expect(sharing.wait_running(), "a held lock is a running wait")
        expect(sharing.lock("wait.lock") is None, "one wait per board")
        held.close()
        expect(not sharing.wait_running(), "a dead wait frees its lock")
        (beads / "board-shared.json").unlink()
        expect(board.find_shared(Path(directory)) is None, "no mark, not shared")

    # Docs: only board's mark shares a board; the r37 commands and the lead's inbox step.
    texts = {name: (root / "skills" / path).read_text(encoding="utf-8") for name, path in
             (("setup", "shared/beads-setup.md"), ("core", "shared/board-core.md"), ("decide", "role/protocols/decide.md"))}
    texts["readme"] = (root / "README.md").read_text(encoding="utf-8")
    for name, text in texts.items():
        for stale in ("with a Dolt remote is shared", "with a sync remote", "An unrouted item can be claimed by id", "ask with a comment"):
            expect(stale not in text, f"{name} still says {stale!r}")
    for name, needle in (("setup", "board share --yes"), ("setup", "board move <url>"), ("setup", "bd import"), ("setup", "BD_NO_REMOTE_ADOPT"),
                         ("core", "board route <person> <ids"), ("core", "board send <person> <ids"), ("core", "board create --for <person>"),
                         ("core", "unrouted"), ("decide", "inbox"), ("decide", "ever decide these alone")):
        expect(needle in texts[name], f"{name} names {needle!r}")
    expect("git push <old url> --delete" not in texts["setup"].split("### History")[1].split("1.")[0], "the old data stays until everyone rejoined")
    # r38-q218: `board setup` owns the settings; the setup doc points to it, migrate runs it, nothing else lists them.
    migrate = (root / "skills" / "board-migrate" / "SKILL.md").read_text(encoding="utf-8")
    installer_readme = (root / "setup" / "README.md").read_text(encoding="utf-8")
    for name, text in (("setup", texts["setup"]), ("migrate", migrate), ("setup/README.md", installer_readme), ("readme", texts["readme"])):
        expect("board setup" in text, f"{name} names board setup")
        expect("bd config set" not in text and "no-git-ops false" not in text, f"{name} lists no settings of its own (board setup owns them)")
    expect("@include shared/beads-setup.md" not in migrate, "board-migrate reads beads-setup.md by path, not by include")
    expect(dict(board.LOCAL_CONFIG).get("no-git-ops") == "true", "stealth's no-git-ops stays true (bd doctor --fix writes a project .gitignore otherwise)")
    shared_only = {key for key, _ in (*board.SERVER_CONFIG, *board.SHARED_CONFIG)}
    expect(shared_only == {"dolt.auto-start", "dolt.auto-commit"} and not shared_only & {key for key, _ in (*board.LOCAL_CONFIG, *board.TRAVELLING_CONFIG)},
           "the server and shared settings sit apart from every board's", shared_only)


# The board fixtures are dated around 2026-10-22T15:30Z. The registry prunes by the real clock (7 days), so the board tests move
# every such date, in the fixtures the fake bd serves, the fake clock and the registrations, to just before the real now.
FIXTURE_CLOCK = datetime(2026, 10, 22, 15, 30, tzinfo=timezone.utc)
FIXTURE_SHIFT = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=1) - FIXTURE_CLOCK


def shift_dates(value):
    """`value` with every 2026-10 ISO time inside it moved by FIXTURE_SHIFT, in its own format (Z or +00:00)."""
    if isinstance(value, str):
        match = re.fullmatch(r"(2026-10-\d\dT\d\d:\d\d:\d\d)(Z|\+00:00)", value)
        if not match:
            return value
        moved = datetime.fromisoformat(match[1] + "+00:00") + FIXTURE_SHIFT
        return moved.strftime("%Y-%m-%dT%H:%M:%S") + match[2]
    if isinstance(value, list):
        return [shift_dates(one) for one in value]
    if isinstance(value, dict):
        return {key: shift_dates(one) for key, one in value.items()}
    return value


def validate_board(root: Path) -> None:
    """The board CLI against a fixture from `bd export` of a throwaway db
    (bd 1.3.1); bd writes are recorded, not run."""
    import contextlib
    import io
    from datetime import datetime, timezone
    from unittest.mock import patch

    loader = importlib.machinery.SourceFileLoader("board", str(root / "bin" / "board"))
    spec = importlib.util.spec_from_loader("board", loader)
    if spec is None:
        raise RuntimeError("cannot load board")
    board = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(board)

    def bare_deck(issues: list[dict], complete: bool = True):
        """An in-process board with no bd behind it (the nix build has none): no project settings, like a board before
        `board setup`, so reading one never shells out."""
        deck = board.Board(issues, complete=complete)
        deck.settings.update(target="")
        return deck

    fixture = [json.loads(line) for line in
               (root / "bin" / "fixtures" / "board-export.jsonl").read_text(encoding="utf-8").splitlines()]
    goal = next(issue["id"] for issue in fixture if issue["title"] == "Goal")
    ids = {issue["title"]: issue["id"] for issue in fixture}
    real_run = subprocess.run

    class Fake:
        def __init__(self, issues, lint=None, refuse=(), history=None):
            self.issues, self.lint, self.refuse, self.calls = issues, lint or {"results": []}, set(refuse), []
            self.history, self.files = history or {}, {}
            self.settings = {"custom.board.target": "main", "custom.board.setup": "true", "custom.board.checks": "true", "custom.board.look": "before", "custom.board.view": "code"}

        not_bd = ("nonsense",)  # words `bd <word> --help` rejects
        project = None  # the folder `bd where` names (its .beads); None: not in a board

        def __call__(self, command, **kwargs):
            if command[0] != "bd":
                return real_run(command, **kwargs)
            if command[1] == "where":
                return subprocess.CompletedProcess(command, *((0, f"{self.project}/.beads\n  database: x\n", "") if self.project
                                                              else (1, "", "No active beads workspace found.")))
            self.calls.append((command[1:], kwargs.get("input")))
            if command[2:] == ["--help"]:  # `bd <verb> --help`: exit 0 is a bd command
                return subprocess.CompletedProcess(command, 1 if command[1] in self.not_bd else 0, "", "")
            # board hands long text over in temporary files: keep their content for the assertions.
            for flag, path in zip(command, command[1:]):
                if flag in ("--design-file", "--body-file", "-f") and Path(path).is_file():
                    self.files[(command[1], command[2] if command[1] != "comments" else command[3], flag)] = \
                        Path(path).read_text(encoding="utf-8")
            if command[1] == "create":
                return subprocess.CompletedProcess(command, 0, "fx-new\n" if "--silent" in command else json.dumps({"id": "fx-new"}), "")
            if command[1] == "export":
                return subprocess.CompletedProcess(command, 0, "\n".join(json.dumps(shift_dates(issue)) for issue in self.issues) + "\n", "")
            if command[1] == "config" and command[2] == "get":
                return subprocess.CompletedProcess(command, 0, json.dumps({"key": command[-1], "value": self.settings.get(command[-1], "")}), "")
            if command[1] == "list" and "--parent" in command:
                parent = command[command.index("--parent") + 1]
                rows = [issue for issue in self.issues if any(d["type"] == "parent-child" and d["depends_on_id"] == parent
                                                              for d in issue.get("dependencies") or [])]
                return subprocess.CompletedProcess(command, 0, json.dumps(shift_dates(rows)), "")
            if command[1] == "list" and "--status" in command and command[command.index("--status") + 1] == "closed":
                rows = [{k: v for k, v in issue.items() if k not in ("comments", "_type", "description", "design", "acceptance_criteria", "notes")}
                        for issue in self.issues if issue["status"] == "closed"]
                return subprocess.CompletedProcess(command, 0, json.dumps(shift_dates(rows)), "")
            if command[1] == "list":
                # bd list: non-closed items with dependencies, without comments, edges ordered unlike the export's.
                rows = [{**{k: v for k, v in issue.items() if k not in ("comments", "_type")},
                         "dependencies": list(reversed(issue.get("dependencies") or []))}
                        for issue in self.issues if issue["status"] != "closed"]
                return subprocess.CompletedProcess(command, 0, json.dumps(shift_dates(rows)), "")
            if command[1] == "show":
                wanted = command[command.index("--") + 1:]
                return subprocess.CompletedProcess(command, 0, json.dumps(shift_dates(self.show_records(wanted, "--include-dependents" in command))), "")
            if command[1] == "history":
                return subprocess.CompletedProcess(command, 0, json.dumps(self.history.get(command[2], [])), "")
            if command[1] == "lint":
                return subprocess.CompletedProcess(command, 0, json.dumps(self.lint), "")
            if command[1] == "update" and command[2] in self.refuse:
                return subprocess.CompletedProcess(command, 13, "", f"assignee mismatch: {command[2]}")
            return subprocess.CompletedProcess(command, 0, "[]", "")

        def show_records(self, wanted, dependents):
            """bd show --json --include-comments --brief-deps: full records whose edges are stubs of the other end."""
            by_id = {issue["id"]: issue for issue in self.issues}

            def stub(other, kind):
                return {"id": other, "title": by_id[other].get("title", ""), "status": by_id[other]["status"],
                        "issue_type": by_id[other].get("issue_type"), "dependency_type": kind}

            records = []
            for item_id in wanted:
                if item_id not in by_id:
                    continue
                record = {k: v for k, v in by_id[item_id].items() if k not in ("dependencies", "_type")}
                record["comments"] = by_id[item_id].get("comments") or []
                record["dependencies"] = [stub(d["depends_on_id"], d["type"]) for d in by_id[item_id].get("dependencies") or []
                                          if d["depends_on_id"] in by_id]
                if dependents:
                    incoming = [(issue["id"], d["type"]) for issue in self.issues for d in issue.get("dependencies") or []
                                if d["depends_on_id"] == item_id]
                    record["dependents"] = [stub(other, kind) for other, kind in incoming]
                    if record.get("issue_type") == "epic":
                        record["epic_total_children"] = sum(1 for _, kind in incoming if kind == "parent-child")
                records.append(record)
            return records

        def reads(self):
            return [args[0] for args, _ in self.calls if args[0] in ("export", "list", "show") and "--parent" not in args]

        def writes(self):
            return [args for args, _ in self.calls if args[0] not in ("export", "list", "show", "lint", "history", "config")]

        def plain_writes(self):
            """The writes without the metadata bookkeeping of a change request claim (stage, fork point, setup; the real-bd runs check it)."""
            bookkeeping = {"since", "reviewing_tip", "landing", "rebase_onto", "review_tip", "review_base_tip", "check_new", "check_base_count", "check_tip_count", "base", "base_sha", "setup_sha", "replan", "designed", "checkpoint", "check_tip", "check_base_tip",
                           "check_result", "check_at", "check_output"}

            def only_metadata(args):
                flags = [a for a in args[2:] if a != "--json"]
                return args[0] == "update" and bool(flags) and all(
                    (flag in ("--set-metadata", "--unset-metadata")) or flag.split("=")[0] in bookkeeping for flag in flags)

            return [args for args in self.writes() if not only_metadata(args)]

    def invoke(argv, fake, actor="", now="2026-10-22T15:30:00+00:00"):
        board._prefix.clear()  # read once per process, as the real command does
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(board.subprocess, "run", fake), \
                patch.object(board, "utcnow", lambda: datetime.fromisoformat(shift_dates(now))), patch.object(board, "has_board", lambda: True), \
                patch.dict(os.environ, {"BEADS_ACTOR": actor, "CODEX_SESSION_ID": "", "CLAUDE_CODE_SESSION_ID": ""}), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            try:
                code = board.main(argv)
            except SystemExit:
                if os.environ.get("DEBUG_BOARD_TESTS"):
                    sys.__stderr__.write(f"board {argv} exited with a usage error: {errors.getvalue()}\n")
                raise
        # Each view makes the read it needs: status views one list (plus one show of the held items and the epics
        # without an open child, when there are any), the full-read views one export, show one show.
        live = [issue for issue in fake.issues if issue["status"] != "closed"]
        held = any(issue.get("assignee") for issue in live)
        parents = {d["depends_on_id"] for issue in live for d in issue.get("dependencies") or [] if d["type"] == "parent-child"}
        childless = any(issue.get("issue_type") == "epic" and issue["id"] not in parents for issue in live)
        if argv[0] == "show":
            # a second show only fetches the metadata of a pending revision's new record
            expected = fake.reads() if fake.reads() in (["show"], ["show", "show"]) else ["show"]
        elif argv[0] in ("related", "check", "block") or argv[:2] in (["ruling", "revise"], ["ruling", "release"], ["ruling", "supersede"]):
            expected = ["export"]
        elif argv[:2] == ["ruling", "record"]:
            expected = ["list"]
        elif argv[0] in ("claim", "take") and fake.reads()[:1] == ["list"] and set(fake.reads()[1:]) <= {"show", "list"}:
            # claim reads hand-over comments of in_review items, the comments of the session's other holds (staleness), and the
            # blockers a change request lifts (the closed items in a list, shows): after the one list
            expected = fake.reads()
        elif argv[0] in ("position", "console") and (held or childless) or argv[0] == "mine" and held:
            expected = ["list", "show"]
        else:
            expected = ["list"]
        if argv[0] == "console" and any(i["status"] == "needs_ratification" and i.get("issue_type") in ("task", "bug", "spike") for i in live):
            expected = [*expected, "show"]  # the ratification rows read their landed CRs (closed, so not in the list) once
        if argv[:2] == ["cr", "edits"] and any(i["status"] == "needs_ratification" and i["id"] == argv[2] for i in live):
            # a ratification edit reads its landed CR (closed, so not in the list), and with --commit the follow-up it created
            expected = fake.reads() if fake.reads()[:1] == ["list"] and set(fake.reads()[1:]) <= {"show"} else [*expected, "show"]
        # A change request whose items wait on a blocker outside the status snapshot reads it once (lifting the edge to its CR).
        everyone = {issue["id"] for issue in fake.issues}
        lifting = any(d["type"] == "blocks" and d["depends_on_id"] not in everyone and not d["depends_on_id"].startswith("external:")
                      for issue in live for d in issue.get("dependencies") or [])
        if lifting and expected != ["export"] and argv[0] != "show":
            collapse = lambda reads: [r for at, r in enumerate(reads) if not (r == "show" and reads[:at].count("show"))]
            expected = collapse([expected[0], "list", *expected[1:], "show"])  # the closed items in one list, then a show of what it lacks
            fake_reads = collapse(fake.reads())
        else:
            fake_reads = fake.reads()
        # A command refused before its last read (unknown id, wrong holder) stops early.
        if fake_reads != expected and not (code != 0 and fake_reads == expected[:len(fake_reads)]):
            raise ValueError(f"board {argv[0]} must read {expected}, read {fake_reads}: {fake.calls}")
        return code, output.getvalue(), errors.getvalue()

    def variant(**changes):
        return [{**issue, **changes.get(issue["title"], {})} for issue in fixture]

    # Change request claims run real git (worktrees) in the process cwd: a throwaway repository on branch main.
    scratch_repo = tempfile.TemporaryDirectory()
    git_env = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
    for command in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", *command], cwd=scratch_repo.name, check=True, env=git_env, capture_output=True)
    previous_cwd = os.getcwd()
    os.chdir(scratch_repo.name)
    os.environ.update(GIT_CONFIG_GLOBAL="/dev/null", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
    with tempfile.TemporaryDirectory() as state_dir, tempfile.TemporaryDirectory() as raw_base:
        registry = root / "bin" / "session"
        project, project_env = fake_board(Path(raw_base).resolve())
        Fake.project = str(project)
        for args, identity in ((("agent", "--pulls", "implement,review"), as_session("0000-aaaa1111", "codex")),
                               (("lead",), as_session("0000-lead0001")), (("solo",), as_session("0000-solo0001")),
                               (("autopilot",), as_session("0000-auto0001"))):
            subprocess.run(["bash", str(registry), "activate", *args], check=True,
                           env={**os.environ, **session_env(state_dir), **identity, **project_env})
        with patch.dict(os.environ, session_env(state_dir)):
            _, health, _ = invoke(["health", "--items", "ready"], Fake(fixture))
            for expected in ("claimable now (unassigned, unblocked): 5\n",
                             "by kind: plan 2, design 1, implement 1, review 1, question 0, accept 0, ratify 0, milestone 0, refresh 0",
                             "released rulings to plan: 2\n", "outside any epic, no topic: label: 1\n"):
                if expected not in health:
                    raise ValueError(f"board health lacks {expected!r}:\n{health}")
            for blocked in ("Implement store A", "Wire caller", "Waits on released"):
                if blocked in health:
                    raise ValueError(f"board health counted blocked {blocked} as claimable")

            ready_task = next(i for i in fixture if i["title"] == "Ready task")
            # A status read holds no closed items: a blocker missing from it is closed. A complete snapshot fails closed.
            for blocker, claimable in (("fx-missing", True), ("external:up:cap", True)):
                _, gated, _ = invoke(["queue"], Fake(variant(**{"Ready task": {"dependencies": [
                    *ready_task["dependencies"], {"issue_id": ready_task["id"], "depends_on_id": blocker, "type": "blocks"}]}})))
                if ("CR ready" in gated) != claimable:
                    raise ValueError(f"board queue misjudged a blocker outside the snapshot: {blocker}")
                gated_issues = [{**i, "dependencies": [*i["dependencies"], {"issue_id": i["id"], "depends_on_id": blocker,
                                                                           "type": "blocks"}]} if i["id"] == ready_task["id"] else i
                                for i in fixture]
                if bool(bare_deck(gated_issues).open_blockers(ready_task["id"])) != (blocker == "fx-missing"):
                    raise ValueError(f"a complete snapshot must fail closed on a blocker outside it: {blocker}")
                if bare_deck(gated_issues, complete=False).open_blockers(ready_task["id"]):
                    raise ValueError(f"a status snapshot must count a blocker outside it as closed: {blocker}")
            _, queue, _ = invoke(["queue", "--root", goal], Fake(fixture))
            if "implement: 1\n" not in queue or "Loose item" in queue or "review: 1\n" not in queue:
                raise ValueError(f"board queue ignored --root or routing:\n{queue}")

            _, recent, _ = invoke(["position"], Fake(fixture))
            _, later, _ = invoke(["position"], Fake(fixture), now="2026-10-22T17:30:00+00:00")
            # Sessions count by the kinds a role handles, not only its bare-claim kinds.
            for expected in ("implement: 1 ready (1 held, 1 wait), 1 sessions", "question: 0 ready (1 held), 3 sessions",
                             "accept: 0 ready, 3 sessions", "ratify: 0 ready, 2 sessions",
                             "aaaa1111/build-12345678 (agent implement+review, codex)", "lead0001 (lead, claude)",
                             "open questions holding work: 2", f"finished epics not closed: 1\n  {ids['Finished outcome']}"):
                if expected not in recent:
                    raise ValueError(f"board position lacks {expected!r}:\n{recent}")
            if "IDLE" in recent or "board take <id> | board unclaim <id>" in recent:
                raise ValueError("board position flagged fresh holds as idle")
            if later.count("IDLE") != 3 or "If that session is gone: board take <id> | board unclaim <id>" not in later:
                raise ValueError(f"board position missed idle holds:\n{later}")

            # Session scope (r26-q115/q116/q120): a session lists when it holds items here, or when its project is this
            # board's and the later of its registration and last activity is within 24 h.
            registered = {"othr0001": ("/another/project", "2026-10-22T15:00:00Z"), "same0001": (str(project), "2026-10-22T15:00:00Z"),
                          "samo0001": (str(project), "2026-10-19T00:00:00Z"), "oldx0001": (str(project), "2026-10-19T00:00:00Z"),
                          "nopr0001": (None, "2026-10-22T15:00:00Z"), "hold0001": ("/another/project", "2026-10-19T00:00:00Z"),
                          "nhld0001": (None, "2026-10-19T00:00:00Z")}
            for actor, (home, at) in registered.items():
                Path(state_dir, f"0000-{actor}.json").write_text(json.dumps(
                    {"session": f"0000-{actor}", "role": "lead", "pulls": [], "actor": actor, "tool": "claude", "registered_at": shift_dates(at),
                     **({"project": home} if home else {})}), encoding="utf-8")
            for actor in ("samo0001", "oldx0001"):  # registered long ago; samo0001 works now (activity hooks live)
                stamp = datetime.fromisoformat(shift_dates("2026-10-22T15:25:00+00:00")).timestamp() if actor == "samo0001" \
                    else datetime.fromisoformat(shift_dates("2026-10-19T00:00:00+00:00")).timestamp()
                Path(state_dir, f"0000-{actor}.active").touch()
                os.utime(Path(state_dir, f"0000-{actor}.active"), (stamp, stamp))
            held_template = next(i for i in fixture if i["title"] == "Held task")
            scoped_issues = [*fixture, {**held_template, "id": "fx-hold-other", "assignee": "hold0001"},
                             {**held_template, "id": "fx-hold-none", "assignee": "nhld0001"}]

            def listed_sessions(fake, now="2026-10-22T15:30:00+00:00"):
                position_view = json.loads(invoke(["position", "--json"], fake, now=now)[1])
                return position_view, {entry["actor"] for entry in position_view["sessions"]}

            def located(issues, folder):
                fake = Fake(issues)
                fake.project = folder
                return fake

            scoped_position, listed = listed_sessions(located(scoped_issues, str(project)))
            if listed != {"aaaa1111", "lead0001", "solo0001", "auto0001", "same0001", "samo0001", "hold0001", "nhld0001"}:
                raise ValueError(f"board position session scope: {sorted(listed)}")
            if scoped_position["ready"]["question"]["sessions"] != sum(1 for e in scoped_position["sessions"] if "question" in e["handles"]):
                raise ValueError("the per-kind session counts must follow the listed sessions")
            _, console_view, _ = invoke(["console"], located(scoped_issues, str(project)), "aaaa1111")
            if {e["actor"] for e in json.loads(console_view)["sessions"]} != listed:
                raise ValueError("board console must list the same sessions as board position")
            # A symlinked path names the same project; a session ages out 24 h after its last activity or registration.
            alias = Path(raw_base).resolve() / "alias"
            alias.symlink_to(project)

            if listed_sessions(located(scoped_issues, str(alias)))[1] != listed:
                raise ValueError("board resolved its project path wrongly through a symlink")
            if "samo0001" in listed_sessions(located(scoped_issues, str(project)), now="2026-10-23T16:00:00+00:00")[1]:
                raise ValueError("a session idle for over 24 h stayed listed")
            # Without a board lookup only the holders list.
            if listed_sessions(located(scoped_issues, None))[1] != {"aaaa1111", "lead0001", "hold0001", "nhld0001"}:
                raise ValueError(f"without a project only holders list: {sorted(listed_sessions(located(scoped_issues, None))[1])}")
            _, text, _ = invoke(["position"], located(scoped_issues, str(project)))
            if "sessions (holding items here, or of this project and registered or active within 24 h)" not in text:
                raise ValueError("board position's session title must state the rule")
            for actor in registered:
                for suffix in ("json", "active"):
                    Path(state_dir, f"0000-{actor}.{suffix}").unlink(missing_ok=True)

            # board check: one line per deviation with its class and board-core anchor.
            checked = [json.loads(line) for line in
                       (root / "bin" / "fixtures" / "board-check-export.jsonl").read_text(encoding="utf-8").splitlines()]
            cid = {issue["title"]: issue["id"] for issue in checked}
            gate = next(issue["id"] for issue in checked if issue["title"] == "Gate: human")
            with tempfile.TemporaryDirectory() as directory:
                words = Path(directory) / "words"
                words.write_text("snapshot\nintegration\nprivate\ncandidate\nutility\nwave\n", encoding="utf-8")
                with patch.object(board, "WORD_LIST", words):
                    code, report, _ = invoke(["check"], Fake(checked))
                    _, health_check, _ = invoke(["health"], Fake(checked))
                with patch.object(board, "WORD_LIST", words):
                    if not board.Squash(board.word_list()).squashed("snapshotintegration"):
                        raise ValueError("the squash heuristic missed dictionary-split words")
            expected_lines = [
                (cid["Legacy holder"], "holder", "actors-and-holds"),
                (cid["[Design] Prefixed title"], "title-prefix", "kinds"),
                (cid["[Gate] Release: round 3"], "title-prefix", "kinds"),
                (cid["[Gate] Release: round 3"], "release-gate", "kinds"),
                (cid["Labelled status"], "label-status", "statuses-and-labels"),
            ]
            for item_id, name, anchor in expected_lines:
                if f"  {item_id}  {name}  board-core.md#{anchor}" not in report:
                    raise ValueError(f"board check missed {name} on {item_id}:\n{report}")
            deviation_lines = [row for row in report.splitlines() if "  board-core.md#" in row]
            if code != 1 or len(deviation_lines) != len(expected_lines) or "convention deviations: 5\n" not in report:
                raise ValueError(f"board check reported extra deviations or the wrong exit code {code}:\n{report}")
            # Gate blockers carry their own reason; closed dependents of a released ruling block nothing.
            # A human gate on a question is the user's go, not a release gate; records are linted at release only.
            # milestone is a kind again (board-coordination.md#milestones), not a retired type.
            for clean in ("Clean task", "User action", "Waits on ruling", "Gated question", "Closed waiter", "Gate: human",
                          "Unformatted ruling", "Old milestone"):
                if any(f"  {cid[clean]}  " in row for row in deviation_lines):
                    raise ValueError(f"board check flagged conforming {clean}")
            # A milestone's blockers are its members: unnamed in its text, they are no deviation.
            members_edges = [{**issue, "dependencies": [*issue["dependencies"], *(
                {"issue_id": issue["id"], "depends_on_id": cid[title], "type": "blocks"} for title in ("Squashed text", "Labelled status"))]}
                if issue["title"] == "Old milestone" else issue for issue in checked]
            if f"  {cid['Old milestone']}  " in invoke(["check"], Fake(members_edges))[1]:
                raise ValueError("board check flagged a milestone's member edges")
            flag = report.split("flag, not a deviation")[1]
            if f"  {cid['Squashed text']}  squashed" not in flag or f"  {cid['Clean task']}  " in flag:
                raise ValueError(f"board check missed or misplaced the squashed-text flag:\n{report}")
            # bd keeps no reason on an edge: an unnamed wait is a flag, not a deviation.
            unnamed = report.split("flag, not a deviation")[2]
            if f"  {cid['Unnamed wait']}  unnamed-blocker" not in unnamed or f"  {cid['Old milestone']}  " in unnamed:
                raise ValueError(f"board check missed or misplaced the unnamed-wait flag:\n{report}")
            if "convention deviations: 5 — run /board-migrate" not in health_check:
                raise ValueError("board health lacks the deviation hint")
            # The user view lists gates titled with the user's words and items assigned to the user.
            waiting = [{**issue, "title": "user 2026-10-23: 'wait for my go'"} if issue["title"] == "Gate: human" else issue
                       for issue in checked]
            user_view = invoke(["health", "--items", "user"], Fake(waiting))[1]
            if "waiting on the user (gates titled user, items assigned to user): 2\n" not in user_view \
                    or gate not in user_view or cid["User action"] not in user_view:
                raise ValueError(f"board health user view:\n{user_view}")
            # A gate is a wait, not work: it needs no epic.
            if gate in invoke(["health", "--items", "outside"], Fake(checked))[1]:
                raise ValueError("board health listed a gate outside any epic")
            # The human gate sits outside the Goal epic; a lifecycle label on it is out of scope.
            outside = [{**issue, "labels": ["human"]} if issue["title"] == "Gate: human" else issue for issue in checked]
            _, scoped_check, _ = invoke(["check", "--root", cid["Goal"]], Fake(outside))
            if f"  {gate}  label-status" in scoped_check or f"  {cid['Legacy holder']}  holder" not in scoped_check:
                raise ValueError("board check ignored --root")

            # feature and chore sit outside the Kinds table: live ones are flagged and never routed.
            retired = [{**issue, "issue_type": "feature"} if issue["title"] == "Clean task"
                       else {**issue, "issue_type": "chore"} if issue["title"] == "Waits on ruling" else issue
                       for issue in checked]
            report = invoke(["check"], Fake(retired))[1]
            if f"  {cid['Clean task']}  unknown-type" not in report or f"  {cid['Waits on ruling']}  unknown-type" not in report:
                raise ValueError(f"board check did not flag live feature and chore items:\n{report}")
            other = [{**issue, "issue_type": "molecule"} if issue["title"] == "Clean task" else issue for issue in checked]
            if f"  {cid['Clean task']}  unknown-type  type molecule" not in invoke(["check"], Fake(other))[1] \
                    and f"  {cid['Clean task']}  unknown-type" not in invoke(["check"], Fake(other))[1]:
                raise ValueError("board check must flag any live type outside the Kinds table")
            checks = [{**issue, "issue_type": "check"} if issue["title"] in ("Clean task", "Closed waiter") else issue
                      for issue in checked]
            report = invoke(["check"], Fake(checks))[1]
            if f"  {cid['Clean task']}  unknown-type" not in report or f"  {cid['Closed waiter']}  unknown-type" in report:
                raise ValueError(f"board check misjudged check items (live flagged, closed skipped):\n{report}")
            chore = variant(**{"Ready task": {"issue_type": "chore"}, "Spike perf": {"issue_type": "check"}})
            if "Ready task" in invoke(["queue"], Fake(chore))[1] or "Spike perf" in invoke(["queue"], Fake(chore))[1]:
                raise ValueError("board routed a retired chore or check")

            # A closed blocker holds nothing up; comments are history and never flagged as squashed.
            satisfied = [{**issue, "status": "closed"} if issue["title"] == "Clean task"
                         else {**issue, "comments": [{"text": "Latest actual31same snapshotintegration lint0errors"}]}
                         if issue["title"] == "User action" else issue for issue in checked]
            with tempfile.TemporaryDirectory() as directory:
                words = Path(directory) / "words"
                words.write_text("snapshot\nintegration\n", encoding="utf-8")
                with patch.object(board, "WORD_LIST", words):
                    report = invoke(["check"], Fake(satisfied))[1]
            if f"  {cid['Unnamed wait']}  unnamed-blocker" in report or f"  {cid['User action']}  squashed" in report:
                raise ValueError(f"board check counted a closed blocker or squashed comments:\n{report}")

            # Closed items are immutable history: no class or flag looks at them.
            closed_all = [{**issue, "status": "closed"} if issue["title"] != "Goal" else issue for issue in checked]
            code, report, _ = invoke(["check"], Fake(closed_all))
            if code != 0 or "convention deviations: 0\n" not in report or "squashed text on open items: 0" not in report \
                    or "unnamed waits on open items (board-core.md#dependencies): 0" not in report:
                raise ValueError(f"board check looked at closed items:\n{report}")

            conforming = [issue for issue in checked if issue["title"] in ("Goal", "CR everything", "Clean task", "User action")]
            code, report, _ = invoke(["check"], Fake(conforming))
            _, health_clean, _ = invoke(["health"], Fake(conforming))
            if code != 0 or "convention deviations: 0\n" not in report or "board-migrate" in health_clean:
                raise ValueError(f"board check failed a conforming board ({code}):\n{report}")
            if "letter-digit runs only" not in invoke(["check"], Fake(conforming))[1] \
                    and not Path("/usr/share/dict/words").exists():
                raise ValueError("board check hid that the word list is missing")

            crowded_check = checked + [{**next(i for i in checked if i["title"] == "Legacy holder"), "id": f"ck-extra{n}"}
                                       for n in range(60)]
            _, capped_check, _ = invoke(["check"], Fake(crowded_check))
            _, full_check, _ = invoke(["check", "--all"], Fake(crowded_check))
            if "... 11 more" not in capped_check or "more" in full_check:
                raise ValueError("board check must cap sections at 50 rows unless --all")

            with contextlib.redirect_stderr(io.StringIO()):
                try:
                    board.main(["edges"])
                except SystemExit as error:
                    if error.code != 2:
                        raise ValueError(f"board edges exited {error.code}, expected a usage error") from None
                else:
                    raise ValueError("board edges must be gone; board check absorbs it")

            help_fake = Fake(fixture)
            help_output = io.StringIO()
            with patch.object(board.subprocess, "run", help_fake), contextlib.redirect_stdout(help_output):
                help_code = board.main(["help"])
            if help_code != 0 or "usage: board" not in help_output.getvalue() or help_fake.calls:
                raise ValueError(f"board help must print usage without reading the board:\n{help_output.getvalue()}")

            with tempfile.TemporaryDirectory() as docs:
                Path(docs, "design.md").write_text("Intro.\nTenancy owns membership.\n", encoding="utf-8")
                _, related, _ = invoke(["related", "TENANCY", "--docs", docs], Fake(fixture))
            if ids["Loose item"] not in related or "design.md:2: Tenancy owns membership." not in related:
                raise ValueError(f"board related missed an item or doc line:\n{related}")

            code, _, errors = invoke(["claim"], Fake(fixture))
            if code == 0 or "BEADS_ACTOR" not in errors:
                raise ValueError("board claim ran without an actor")

            worker = "aaaa1111/build-87654321"
            fake = Fake(fixture)
            code, claimed, _ = invoke(["claim"], fake, worker)
            if code or fake.writes() != [["update", ids["Handed task"], "--assignee", worker, "--if-assignee", "", "--json"]]:
                raise ValueError(f"board claim did not CAS-claim the in_review item first: {fake.writes()}")
            if f"this session still holds: 2\n  fx-ovo.c2" not in claimed or ids["Held task"] not in claimed:
                raise ValueError(f"board claim did not list the session's other holds:\n{claimed}")
            if f"claimed {ids['Handed task']} (review; standalone)" not in claimed:
                raise ValueError(f"board claim did not label a never-held review standalone:\n{claimed}")
            # Your own hand-over is skipped; a legacy hand-over is labelled with its old holder.
            own = {"comments": [{"author": worker, "text": "board handover: done", "created_at": "2026-10-22T15:00:00Z"}]}
            fake = Fake(variant(**{"Handed task": own}))
            invoke(["claim"], fake, worker)
            if any(ids["Handed task"] in write for write in fake.writes()):
                raise ValueError(f"board claim took the caller's own hand-over for review: {fake.writes()}")
            legacy = [{"event_type": "status_changed", "actor": "goal-agent", "new_value": json.dumps({"status": "in_review"})}]
            _, claimed, _ = invoke(["claim"], Fake(fixture, history={ids["Handed task"]: legacy}), worker)
            if "author unknown (goal-agent)" not in claimed:
                raise ValueError(f"board claim did not name the legacy hand-over:\n{claimed}")
            by_history = [{"event_type": "status_changed", "actor": "cccc3333", "new_value": json.dumps({"status": "in_review"})}]
            _, claimed, _ = invoke(["claim"], Fake(fixture, history={ids["Handed task"]: by_history}), worker)
            if "author cccc3333" not in claimed:
                raise ValueError(f"board claim did not take the author from the status history:\n{claimed}")

            fake = Fake(fixture, refuse={ids["Handed task"]})
            invoke(["claim"], fake, worker)
            if fake.plain_writes()[-1] != ["update", "fx-ovo.c1", "--claim", "--json"]:
                raise ValueError(f"board claim did not move on after a lost race: {fake.writes()}")

            # At equal priority a released ruling goes before an older task.
            subprocess.run(["bash", str(registry), "activate", "agent", "--pulls", "plan,implement"], check=True,
                           env={**os.environ, **session_env(state_dir), **as_session("0000-plan0001"), **project_env})
            fake = Fake(variant(**{"Old store ruling": {"status": "closed"}}))
            invoke(["claim"], fake, "plan0001")
            if fake.writes() != [["update", ids["Released ruling"], "--assignee", "plan0001", "--if-assignee", "", "--json"]]:
                raise ValueError(f"board claim did not take the released ruling before the equal-priority spike: {fake.writes()}")

            fake = Fake(fixture)
            code, _, _ = invoke(["claim"], fake, "lead0001")
            if code != 1 or fake.writes():
                raise ValueError("a lead's bare claim took work other than open questions")
            fake = Fake(variant(**{"Store choice": {"status": "open"}}))
            invoke(["claim"], fake, "lead0001")
            if fake.writes() != [["update", ids["Store choice"], "--claim", "--json"]]:
                raise ValueError(f"a lead did not claim the open question: {fake.writes()}")
            # A lead claims a change request waiting for its Accept by id only; the queue head that is not current is refresh work,
            # which only review pulls take; a current one goes to solo and autopilot sessions.
            main_tip = subprocess.run(["git", "rev-parse", "main"], capture_output=True, text=True, check=True).stdout.strip()
            waiting_cr = {"status": "needs_acceptance"}
            current_cr = {"status": "needs_acceptance", "metadata": {"check_tip": main_tip, "check_base_tip": main_tip, "check_result": "pass",
                                                                  "review_tip": main_tip, "review_base_tip": main_tip}}
            no_rulings = {"Released ruling": {"status": "closed"}, "Old store ruling": {"status": "closed"}}
            fake = Fake(variant(**{"CR ready": current_cr}))
            invoke(["claim"], fake, "lead0001")
            if fake.writes():
                raise ValueError(f"a lead's bare claim took a change request waiting for its Accept: {fake.writes()}")
            for session in ("solo0001", "auto0001"):
                fake = Fake(variant(**{"CR ready": current_cr, **no_rulings}))
                invoke(["claim"], fake, session)
                if fake.plain_writes()[:1] != [["update", "fx-ovo.c1", "--assignee", session, "--if-assignee", "", "--json"]]:
                    raise ValueError(f"{session}'s bare claim did not take the change request waiting for its Accept: {fake.writes()}")
                fake = Fake(variant(**{"CR ready": waiting_cr, **no_rulings}))
                invoke(["claim"], fake, session)
                if fake.writes():
                    raise ValueError(f"{session}'s bare claim took the queue head that needs its refresh: {fake.writes()}")
            fake = Fake(variant(**{"CR ready": waiting_cr, **no_rulings, "Handed task": {"status": "closed"}}))
            _, claimed, _ = invoke(["claim"], fake, "aaaa1111/build-87654321")
            if "claimed fx-ovo.c1 (refresh)" not in claimed or "board cr refresh fx-ovo.c1, then board unclaim fx-ovo.c1" not in claimed \
                    or fake.plain_writes()[:1] != [["update", "fx-ovo.c1", "--assignee", "aaaa1111/build-87654321", "--if-assignee", "", "--json"]]:
                raise ValueError(f"a review pull did not take the queue head's refresh:\n{claimed}\n{fake.writes()}")
            # The console's Refresh follows the same mark: the stale queue head only (r27-q252).
            shown = json.loads(invoke(["console"], Fake(variant(**{"CR ready": waiting_cr, "CR design": waiting_cr})), "aaaa1111")[1])["crs"]
            if [c["id"] for c in shown if c["refreshWork"]] != [shown[0]["id"]] or len(shown) < 2:
                raise ValueError(f"board console refreshWork must mark the stale queue head (the list's first) only: {[(c['id'], c['refreshWork']) for c in shown]}")
            rows = {c["id"]: c["refreshWork"] for c in json.loads(invoke(["console"], Fake(variant(**{"CR ready": current_cr})), "aaaa1111")[1])["crs"]}
            if rows.get("fx-ovo.c1") is not False:
                raise ValueError(f"board console refreshWork marked a current change request: {rows}")
            fake = Fake(variant(**{"CR ready": waiting_cr}))
            invoke(["claim", "fx-ovo.c1"], fake, "lead0001")
            if fake.plain_writes() != [["update", "fx-ovo.c1", "--assignee", "lead0001", "--if-assignee", "", "--json"]]:
                raise ValueError(f"a lead did not claim the named change request waiting for its Accept: {fake.writes()}")

            # r10-q50: a ratification row carries the landed range of its CR (tip: landing, else the checked tip; baseTip: the check's base tip).
            landed = [{**fixture[0], "id": "rt-cr", "title": "Landed CR", "issue_type": "change-request", "status": "closed", "dependencies": [],
                       "metadata": {"landing": "a" * 40, "check_tip": "a" * 40, "check_base_tip": "b" * 40}},
                      {**fixture[0], "id": "rt-1", "title": "Ratify: Landed CR", "issue_type": "task", "status": "needs_ratification", "assignee": None,
                       "dependencies": [{"issue_id": "rt-1", "depends_on_id": "rt-cr", "type": "parent-child"}]},
                      {**fixture[0], "id": "rt-2", "title": "Ratify: unknown range", "issue_type": "task", "status": "needs_ratification", "assignee": None,
                       "dependencies": []}]
            rows = json.loads(invoke(["console"], Fake([*fixture, *landed]), "aaaa1111")[1])["ratifications"]
            if rows != [{"id": "rt-1", "cr": "rt-cr", "title": "Ratify: Landed CR", "tip": "a" * 40, "baseTip": "b" * 40},
                        {"id": "rt-2", "cr": "", "title": "Ratify: unknown range", "tip": None, "baseTip": None}]:
                raise ValueError(f"board console ratifications carry the landed range of their CR: {rows}")
            # A work item is claimed by id inside a change request its session holds (a worker of it); outside one it is refused.
            fake = Fake(fixture)
            code, _, errors = invoke(["claim", ids["Ready task"]], fake, "lead0001")
            if code != 1 or fake.writes() or "fx-ovo.c1" not in errors or "claims it for its workers" not in errors:
                raise ValueError(f"board claim took an item of a change request its session does not hold: {code} {fake.writes()} {errors}")
            fake = Fake(fixture)
            code, _, errors = invoke(["claim", ids["Loose item"]], fake, "lead0001")
            if code != 1 or fake.writes() or "outside any change request" not in errors or "--parent" not in errors:
                raise ValueError(f"board claim took a work item outside any change request: {code} {fake.writes()} {errors}")
            # r10-q50: work marked no-code at creation (metadata no_code=1) is claimed outside any CR and is no `no-cr` deviation.
            no_code = variant(**{"Loose item": {"metadata": {"no_code": "1"}}})
            fake = Fake(no_code)
            code, _, errors = invoke(["claim", ids["Loose item"]], fake, "lead0001")
            if code or not any(w[:2] == ["update", ids["Loose item"]] and "--claim" in w or "lead0001" in w for w in fake.writes()):
                raise ValueError(f"board claim refused a no-code work item outside any change request: {code} {errors} {fake.writes()}")
            if f"{ids['Loose item']}  no-cr" in invoke(["check"], Fake(no_code))[1] or f"{ids['Loose item']}  no-cr" not in invoke(["check"], Fake(fixture))[1]:
                raise ValueError("board check must flag a work item outside any CR, but not a no-code one")
            held_cr = variant(**{"CR ready": {"status": "in_progress", "assignee": "lead0001"}})
            fake = Fake(held_cr)
            code, _, _ = invoke(["claim", ids["Ready task"]], fake, "lead0001/build-00000001")
            if code or fake.writes() != [["update", ids["Ready task"], "--claim", "--json"]]:
                raise ValueError(f"a worker could not claim an item of its session's change request: {code} {fake.writes()}")
            fake = Fake(fixture)
            code, _, _ = invoke(["claim", ids["Open cache question"]], fake, "lead0001")  # decisions need no change request
            if code:
                raise ValueError("board claim refused a decision")

            # Routing per role: solo plans and ratifies, autopilot plans, a lead's bare claim takes only
            # open questions, nobody claims `user`'s items.
            ratify = variant(**{"Old store ruling": {"status": "needs_ratification"},
                                "Released ruling": {"assignee": "user"}})
            for actor, expected in (("solo0001", ids["Old store ruling"]), ("auto0001", None),
                                    ("lead0001", None)):
                fake = Fake(ratify)
                invoke(["claim"], fake, actor)
                if [args[1] for args in fake.writes()] != ([expected] if expected else []):
                    raise ValueError(f"{actor} routing claimed {fake.writes()}")
            fake = Fake(fixture)
            invoke(["claim"], fake, "auto0001")
            if fake.writes() != [["update", ids["Old store ruling"], "--assignee", "auto0001", "--if-assignee", "", "--json"]]:
                raise ValueError(f"autopilot did not claim a released ruling to plan: {fake.writes()}")
            fake = Fake(ratify)
            if invoke(["claim", ids["Released ruling"]], fake, "lead0001")[0] == 0 or fake.writes():
                raise ValueError("board claim took an item held by user")

            # Milestones (board-coordination.md#milestones): synthetic issues appended to the fixture.
            def synthetic(item_id, title, kind="task", priority=2, status="open", blocks=(), parent=None, **extra):
                deps = [{"issue_id": item_id, "depends_on_id": b, "type": "blocks"} for b in blocks]
                deps += [{"issue_id": item_id, "depends_on_id": parent, "type": "parent-child"}] if parent else []
                return {"id": item_id, "title": title, "issue_type": kind, "priority": priority, "status": status,
                        "created_at": "2026-10-22T15:29:00Z", "updated_at": "2026-10-22T15:29:00Z",
                        "dependencies": deps, **extra}

            beta = synthetic("ms-1", "Beta", "milestone", 1, blocks=("ms-ready", "ms-member", "ms-epic"), parent=goal)
            members = [
                synthetic("ms-ready", "Ready member", "change-request", parent=goal),
                synthetic("ms-ready.i", "Ready member's item", parent="ms-ready"),
                synthetic("ms-member", "Blocked member", priority=3, blocks=("ms-blocker", "ms-closed"), parent=goal),
                synthetic("ms-blocker", "Member's blocker", priority=3, parent=goal),
                synthetic("ms-closed", "Closed blocker", priority=3, status="closed", blocks=("ms-closed-blocker",)),
                synthetic("ms-closed-blocker", "Behind a closed blocker", priority=3),
                synthetic("ms-epic", "Member outcome", "epic", parent=goal),
                synthetic("ms-sub", "Task with a subtask", parent="ms-epic"),
                synthetic("ms-child", "Epic child", priority=3, blocks=("ms-child-blocker",), parent="ms-sub"),
                synthetic("ms-done-child", "Closed epic child", priority=3, status="closed", parent="ms-epic"),
                synthetic("ms-child-blocker", "Child's blocker", priority=3),
                synthetic("ms-p1", "P1 outsider", "change-request", priority=1, parent=goal),
                synthetic("ms-p1.i", "P1 outsider's item", priority=1, parent="ms-p1"),
            ]
            milestone_board = fixture + [beta, *members]
            work = bare_deck(milestone_board).milestone_work("ms-1")
            if work != {"ms-ready", "ms-ready.i", "ms-member", "ms-blocker", "ms-epic", "ms-sub", "ms-child", "ms-child-blocker"}:
                raise ValueError(f"milestone work misses the closure or takes closed items and what they wait on: {sorted(work)}")
            # A descendant reached first as a blocker still brings its own descendants, whatever the edge order.
            for order in (("ord-e", "ord-m"), ("ord-m", "ord-e")):
                shape = [synthetic("ord-w", "W", "milestone", blocks=order), synthetic("ord-e", "E", "epic"),
                         synthetic("ord-m", "M", blocks=("ord-t",)), synthetic("ord-t", "T", parent="ord-e"),
                         synthetic("ord-s", "S", parent="ord-t")]
                if bare_deck(shape).milestone_work("ord-w") != {"ord-e", "ord-m", "ord-t", "ord-s"}:
                    raise ValueError(f"milestone work depends on edge order {order}: {sorted(bare_deck(shape).milestone_work(shape[0]['id']))}")
            # r24-q109: holds stops at a milestone (which counts as one), and also gives everything downstream.
            shape = [synthetic("h-q", "Q", "decision"), synthetic("h-w", "W", blocks=("h-q",)), synthetic("h-x", "X", blocks=("h-w",)),
                     synthetic("h-m", "M", "milestone", blocks=("h-q",)), synthetic("h-r", "R", blocks=("h-m",)), synthetic("h-s", "S", blocks=("h-m",))]
            if bare_deck(shape).holds("h-q") != (3, 5):
                raise ValueError(f"holds must stop at the milestone, then count everything: {bare_deck(shape).holds('h-q')}")
            built = bare_deck(milestone_board)
            if built.kind(beta) != "milestone" or built.claimable(beta) is not None:
                raise ValueError("a milestone with open work must not be claimable")

            fake = Fake(milestone_board)
            invoke(["claim"], fake, worker)
            if fake.plain_writes() != [["update", "ms-ready", "--claim", "--json"]]:
                raise ValueError(f"board claim did not take the P2 milestone member before P1 outsiders: {fake.writes()}")
            fake = Fake(milestone_board + [synthetic("ms-p0", "P0 outsider", "change-request", priority=0, parent=goal),
                                           synthetic("ms-p0.i", "P0 outsider's item", priority=0, parent="ms-p0")])
            invoke(["claim"], fake, worker)
            if fake.plain_writes() != [["update", "ms-p0", "--claim", "--json"]]:
                raise ValueError(f"board claim did not take the P0 outsider before milestone work: {fake.writes()}")

            _, queued, _ = invoke(["queue"], Fake(milestone_board))
            implement_rows = queued.split("implement:")[1].split("review:")[0].splitlines()[1:]
            if not implement_rows[0].startswith("  ms-ready ") or "m:ms-1" not in implement_rows[0] \
                    or any("m:" in row for row in implement_rows if "ms-p1" in row) or "milestone: 0\n" not in queued:
                raise ValueError(f"board queue must order and mark milestone work and hide the unready milestone:\n{queued}")
            _, scoped_queue, _ = invoke(["queue", "--root", "ms-1"], Fake(milestone_board))
            if "implement: 1\n" not in scoped_queue or "ms-p1" in scoped_queue or ids["Ready task"] in scoped_queue:
                raise ValueError(f"board queue --root <milestone> must scope to its work:\n{scoped_queue}")
            _, milestone_health, _ = invoke(["health"], Fake(milestone_board))
            if "milestone ms-1 (Beta): open work 7, ready 1, held 0, blocked 2; milestone not ready\n" not in milestone_health \
                    or "milestone ms-1 (Beta)" not in invoke(["health", "--root", "ms-1"], Fake(milestone_board))[1]:
                raise ValueError(f"board health lacks the milestone line:\n{milestone_health}")
            if json.loads(invoke(["health", "--json"], Fake(milestone_board))[1])["milestones"] != [
                    {"id": "ms-1", "title": "Beta", "openWork": 7, "ready": 1, "held": 0, "blocked": 2, "milestoneReady": False}]:
                raise ValueError("board health --json milestones")

            # A ready milestone is claimed by id only: no bare claim takes it.
            done = [beta, *({**m, "status": "closed"} if m["id"] in work else m for m in members)]
            ready_board = fixture + done
            if bare_deck(ready_board).claimable(beta) != "milestone":
                raise ValueError("a ready milestone must have kind milestone")
            if "milestone ms-1 (Beta): open work 0, ready 0, held 0, blocked 0; milestone ready\n" \
                    not in invoke(["health"], Fake(ready_board))[1]:
                raise ValueError("board health did not report the ready milestone")
            ready_position = invoke(["position"], Fake(ready_board))[1]
            if "milestone: 1 ready, 2 sessions" not in ready_position \
                    or "ready milestones: 1\n  ms-1  open  milestone  unassigned  Beta" not in ready_position \
                    or "ready milestones: 0\n" not in invoke(["position"], Fake(milestone_board))[1]:
                raise ValueError("board position must count ready milestones against lead and solo sessions")
            for session in ("lead0001", "solo0001", "auto0001"):
                fake = Fake(ready_board)
                invoke(["claim"], fake, session)
                if any("ms-1" in write for write in fake.writes()):
                    raise ValueError(f"{session}'s bare claim took the ready milestone: {fake.writes()}")
            fake = Fake(ready_board)
            invoke(["claim", "ms-1"], fake, "lead0001")
            if fake.writes() != [["update", "ms-1", "--claim", "--json"]]:
                raise ValueError(f"a lead did not claim the named ready milestone: {fake.writes()}")
            fake = Fake(milestone_board)
            code, _, errors = invoke(["claim", "ms-1"], fake, "lead0001")
            if code != 1 or fake.writes() or "not ready" not in errors:
                raise ValueError(f"board claim <id> took a milestone with open work: {fake.writes()}")

            # Within one session an item hands down to the caller; other sessions stay refused.
            fake = Fake(fixture)
            code, _, _ = invoke(["claim", ids["Held task"]], fake, worker)
            if code or fake.writes()[0] != ["update", ids["Held task"], "--assignee", worker, "--force", "--json"] \
                    or fake.writes()[1][:3] != ["comments", "add", ids["Held task"]]:
                raise ValueError(f"board claim did not hand down a same-session hold: {fake.writes()}")
            fake = Fake(fixture)
            if invoke(["claim", ids["Held task"]], fake, "lead0001")[0] == 0 or fake.writes():
                raise ValueError("board claim forced another session's hold")

            def row(text, key):
                return next(text_line for text_line in text.splitlines() if key in text_line)

            # Worker cap (r13-q71): a work item past the claiming actor's cap is refused unless forced with a reason.
            def set_workers(session, count):
                subprocess.run(["bash", str(registry), "set-workers", session, "--workers", str(count)], check=True,
                               env={**os.environ, **session_env(state_dir), **project_env})

            subprocess.run(["bash", str(registry), "activate", "agent", "--pulls", "implement,review"], check=True,
                           env={**os.environ, **session_env(state_dir), **as_session("0000-agnt0001"), **project_env})
            set_workers("0000-solo0001", 1)
            set_workers("0000-agnt0001", 1)
            ready = ids["Ready task"]

            def in_held_cr(session, **changes):
                """The fixture with CR ready held in progress by this session: its workers may claim its items."""
                return variant(**{"CR ready": {"status": "in_progress", "assignee": session}, **changes})

            holding = in_held_cr("solo0001", **{"Held task": {"assignee": "solo0001"}})
            fake = Fake(holding)
            code, _, errors = invoke(["claim", ready], fake, "solo0001")
            if code != 1 or fake.writes() or "solo0001 holds 1 of 1 work items" not in errors or '--force "<reason>"' not in errors:
                raise ValueError(f"board claim did not refuse a work item past the worker cap: {code} {fake.writes()} {errors}")
            fake = Fake(holding)
            code, _, _ = invoke(["claim", ready, "--force", "gate down"], fake, "solo0001")
            if code or fake.writes() != [["update", ready, "--claim", "--json"],
                                         ["update", ready, "--set-metadata", "forced_hold_by=solo0001",
                                          "--set-metadata", "forced_hold=gate down", "--json"]]:
                raise ValueError(f"board claim --force did not hold and flag the item: {fake.writes()}")
            try:
                invoke(["claim", ready, "--force", " "], Fake(holding), "solo0001")
            except SystemExit as error:
                if error.code != 2:
                    raise ValueError("board claim --force with an empty reason must be a usage error") from None
            else:
                raise ValueError("board claim --force took an empty reason")
            fake = Fake(in_held_cr("lead0001"))
            invoke(["claim", ready, ids["Spike perf"]], fake, "lead0001")  # a lead's cap is 3, nothing held
            if len(fake.writes()) != 2:
                raise ValueError(f"board claim refused a work item within the cap: {fake.writes()}")
            # Counted per actor: a worker's holds are not its session's, and a forced claim within the cap leaves no flag.
            fake = Fake(in_held_cr("solo0001", **{"Held task": {"assignee": "solo0001/build-12345678"}}))
            invoke(["claim", ready, "--force", "unneeded"], fake, "solo0001")
            if fake.writes() != [["update", ready, "--claim", "--json"]]:
                raise ValueError(f"board counted a worker's hold against its session, or flagged a hold within the cap: {fake.writes()}")
            # Not counted: decisions, in-review items (a reviewer's or acceptor's), change requests and planning (a released ruling).
            kept = in_held_cr("solo0001", **{"Held task": {"assignee": None, "status": "open"}, "Handed task": {"assignee": "solo0001"},
                                             "Open cache question": {"assignee": "solo0001"}})
            fake = Fake(kept)
            invoke(["claim", ready], fake, "solo0001")
            if fake.writes() != [["update", ready, "--claim", "--json"]]:
                raise ValueError(f"board claim counted a decision, a change request or an in-review hold against the cap: {fake.writes()}")
            fake = Fake(holding)
            invoke(["claim", ids["Released ruling"]], fake, "solo0001")
            if fake.writes() != [["update", ids["Released ruling"], "--assignee", "solo0001", "--if-assignee", "", "--json"]]:
                raise ValueError(f"board claim refused a planning hold past the cap: {fake.writes()}")
            # A bare claim takes change requests, which no cap counts.
            fake = Fake(variant(**{"Held task": {"assignee": "agnt0001"}, "Handed task": {"status": "closed"}}))
            invoke(["claim"], fake, "agnt0001")
            if fake.plain_writes()[:1] != [["update", "fx-ovo.c1", "--claim", "--json"]]:
                raise ValueError(f"a bare claim of a change request was held back by the worker cap: {fake.writes()}")
            # The flag shows while the forcing actor holds the item, in position, check and the holder's claim output.
            flagged = in_held_cr("solo0001", **{"Ready task": {"assignee": "solo0001", "status": "in_progress",
                                                               "metadata": {"forced_hold_by": "solo0001", "forced_hold": "gate down"}},
                                                "Spike perf": {"assignee": "lead0001", "status": "in_progress",
                                                               "metadata": {"forced_hold_by": "solo0001", "forced_hold": "old hold"}}})
            _, shown, _ = invoke(["position"], Fake(flagged))
            if "FORCED: gate down" not in row(shown, ready) or "FORCED" in row(shown, ids["Spike perf"]):
                raise ValueError(f"board position did not flag exactly the forced hold:\n{shown}")
            _, shown, _ = invoke(["check"], Fake(flagged))
            if f"{ready}  forced-hold  solo0001: gate down" not in shown or ids["Spike perf"] + "  forced-hold" in shown:
                raise ValueError(f"board check did not list the forced hold:\n{shown}")
            _, shown, _ = invoke(["claim"], Fake(flagged), "solo0001")
            if "FORCED: gate down" not in row(shown, ready):
                raise ValueError(f"board claim did not show the forced hold in the holder's list:\n{shown}")
            fake = Fake(in_held_cr("solo0001", **{"Ready task": {"assignee": None, "status": "open",
                                                                 "metadata": {"forced_hold_by": "solo0001", "forced_hold": "gate down"}}}))
            invoke(["claim", ready], fake, "solo0001")
            if fake.writes()[1:] != [["update", ready, "--unset-metadata", "forced_hold_by", "--unset-metadata", "forced_hold", "--json"]]:
                raise ValueError(f"board claim kept an earlier holder's forced mark: {fake.writes()}")
            # A takeover counts against the cap like a claim (r16-q93): a same-session claim and board take of a work item
            # held in progress are refused past it unless --force "<reason>", which flags the hold.
            stopped_worker = variant(**{"Held task": {"assignee": "solo0001/build-12345678"},
                                        "Ready task": {"assignee": "solo0001", "status": "in_progress"}})
            for verb in ("claim", "take"):
                fake = Fake(stopped_worker)
                code, _, errors = invoke([verb, ids["Held task"]], fake, "solo0001")
                if code != 1 or fake.writes() or "solo0001 holds 1 of 1 work items" not in errors or f"{verb} {ids['Held task']} --force" not in errors:
                    raise ValueError(f"board {verb} took over a work hold past the worker cap: {code} {fake.writes()} {errors}")
                fake = Fake(stopped_worker)
                code, _, _ = invoke([verb, ids["Held task"], "--force", "gate down"], fake, "solo0001")
                writes = fake.writes()
                if code or writes[0] != ["update", ids["Held task"], "--assignee", "solo0001", "--force", "--json"] \
                        or writes[-1] != ["update", ids["Held task"], "--set-metadata", "forced_hold_by=solo0001",
                                          "--set-metadata", "forced_hold=gate down", "--json"]:
                    raise ValueError(f"board {verb} --force did not take over and flag the hold: {writes}")
                fake = Fake(variant(**{"Held task": {"assignee": "solo0001/build-12345678"}}))
                code, _, _ = invoke([verb, ids["Held task"]], fake, "solo0001")
                if code or [w[0] for w in fake.writes()] != ["update", "comments"]:
                    raise ValueError(f"board {verb} refused or flagged a takeover within the cap: {fake.writes()}")
            # Two takeovers in one call: the first counts against the second.
            fake = Fake(variant(**{"Held task": {"assignee": "solo0001/build-12345678"},
                                   "Ready task": {"assignee": "solo0001/build-12345678", "status": "in_progress"}}))
            code, _, errors = invoke(["take", ids["Held task"], ready], fake, "solo0001")
            if code != 1 or len(fake.writes()) != 2 or "not taken" not in errors:
                raise ValueError(f"board take did not count its own takeovers: {code} {fake.writes()} {errors}")
            set_workers("0000-solo0001", 3)
            # Pulls (r13-q61): a lead's registered pulls come on top of its preset, for claiming and for handles.
            subprocess.run(["bash", str(registry), "activate", "lead", "--pulls", "implement"], check=True,
                           env={**os.environ, **session_env(state_dir), **as_session("0000-lead0002"), **project_env})
            fake = Fake(fixture)
            invoke(["claim"], fake, "lead0002")
            if len(fake.plain_writes()) != 1 or fake.plain_writes()[0][2:] != ["--claim", "--json"]:
                raise ValueError(f"a lead with the implement pull did not claim implement work: {fake.writes()}")
            fake = Fake(fixture)
            invoke(["claim"], fake, "lead0001")
            if fake.writes():
                raise ValueError(f"a lead without pulls claimed work: {fake.writes()}")
            Path(state_dir, "0000-lead0002.json").unlink()
            Path(state_dir, "0000-agnt0001.json").unlink()  # the later position checks count the fixture's sessions

            # Stale holds (r13-q76): a held work item without an update (fields, notes, comments) for an hour.
            later = "2026-10-22T17:00:00+00:00"
            _, shown, _ = invoke(["position"], Fake(fixture), now=later)
            if "STALE" not in row(shown, ids["Held task"]) or "STALE = no update" not in shown \
                    or "STALE" in row(shown, ids["Open cache question"]):
                raise ValueError(f"board position did not flag the stale work hold only:\n{shown}")
            # The position legend speaks to the holder of another session's hold: only the holder, the user or a deciding session frees it.
            if "board unclaim it" in shown or "Only the holder, the user or a deciding session frees it" not in shown:
                raise ValueError(f"board position's STALE legend must not tell the reader to unclaim another session's hold:\n{shown}")
            commented = variant(**{"Held task": {"comments": [{"author": "aaaa1111", "text": "waits on CI",
                                                              "created_at": "2026-10-22T16:30:00Z"}]}})
            _, shown, _ = invoke(["position"], Fake(commented), now=later)
            if "STALE" in shown:
                raise ValueError(f"a comment within the hour did not renew the hold:\n{shown}")
            _, shown, _ = invoke(["check"], Fake(fixture), now=later)
            if f"{ids['Held task']}  stale-hold  aaaa1111/build-12345678: no update for" not in shown:
                raise ValueError(f"board check did not list the stale hold:\n{shown}")
            _, shown, _ = invoke(["claim"], Fake(fixture), "aaaa1111/build-87654321", now=later)
            if "STALE" not in row(shown, ids["Held task"]):
                raise ValueError(f"board claim did not show the stale hold in the holder's list:\n{shown}")
            _, shown, _ = invoke(["mine"], Fake(fixture), "aaaa1111", now=later)
            if "STALE" not in row(shown, ids["Held task"]):
                raise ValueError(f"board mine did not show the stale hold:\n{shown}")
            _, shown, _ = invoke(["position", "--json"], Fake(fixture), now=later)
            if not next(h for h in json.loads(shown)["held"] if h["id"] == ids["Held task"])["stale"]:
                raise ValueError("board position --json lacks the stale mark")

            # Field size guard (r13-q74): a work item's description, design or acceptance stays within 2000 characters.
            def guarded(argv, issues=fixture):
                fake, errors = Fake(issues), io.StringIO()
                with patch.object(board.subprocess, "run", fake), contextlib.redirect_stderr(errors):
                    return board.size_guard(argv[0], argv[1:])[0], fake

            long = "x" * 2001
            refusal, _ = guarded(["create", "T", "-t", "bug", "--description", long])
            if not refusal or "description is 2001 characters" not in refusal or "2000" not in refusal \
                    or "current state" not in refusal or "dated history leaves" not in refusal or "still in force stays" not in refusal \
                    or "may go in a doc" not in refusal or "append" in refusal or "old text" in refusal:
                raise ValueError(f"board create took a 2001-character description: {refusal}")
            for argv in (["create", "T", f"--design={long}"], ["create", "T", "--acceptance", long]):
                if not guarded(argv)[0]:
                    raise ValueError(f"board create took an over-limit field: {argv[:3]}")
            if guarded(["create", "T", "--description", "x" * 2000])[0] or guarded(["create", "T", "-t", "decision", "--description", long])[0]:
                raise ValueError("board create refused a field within the limit, or a decision's record")
            with tempfile.TemporaryDirectory() as folder:
                body = Path(folder, "body.md")
                body.write_text(long, encoding="utf-8")
                if not guarded(["create", "T", "--body-file", str(body)])[0]:
                    raise ValueError("board create took an over-limit --body-file")
            over = variant(**{"Ready task": {"description": "y" * 2500}})
            if not guarded(["update", ready, "--description", "z" * 2600], over)[0] \
                    or guarded(["update", ready, "--description", "z" * 2400], over)[0] \
                    or guarded(["update", ready, "--description", "z" * 2400], fixture)[0] is None:
                raise ValueError("board update must refuse a field that grows or stays over the limit, and pass one that shrinks")
            # An update or an appended note has old text the board keeps (r3-q14); a new item has none.
            grown, appended = guarded(["update", ready, "--description", "z" * 2600], over)[0], guarded(["update", ready, "--append-notes", "n" * 600], noted_for_append := variant(**{"Ready task": {"notes": "n" * 1500}}))[0]
            for what, text in (("update", grown), ("append", appended)):
                if not text or "dated history leaves (the board keeps the old text); every rule, gate and criterion still in force stays." not in text:
                    raise ValueError(f"board {what} refusal keeps the old-text wording of r3-q14: {text}")
            refused = io.StringIO()
            with patch.object(board.subprocess, "run", Fake(fixture)), contextlib.redirect_stderr(refused):
                code = board.main(["bd", "create", "T", "--description", long])
            if code != 2 or "description is 2001 characters" not in refused.getvalue():
                raise ValueError(f"board bd create did not refuse the over-limit field: {code} {refused.getvalue()}")

            # Notes (r16-q96): --notes replaces, --append-notes counts the old notes plus the appended text; shrinking passes.
            noted = variant(**{"Ready task": {"notes": "n" * 1500}, "Spike perf": {"notes": "n" * 2500}})
            spike = ids["Spike perf"]
            if not guarded(["update", ready, "--notes", long], noted)[0] or guarded(["update", ready, "--notes", "n" * 2000], noted)[0] \
                    or not guarded(["create", "T", "--notes", long])[0]:
                raise ValueError("board update must refuse notes over the limit and pass notes within it")
            refusal = guarded(["update", ready, "--append-notes", "a" * 600], noted)[0]
            if not refusal or "notes is 2101 characters" not in refusal or guarded(["update", ready, "--append-notes", "a" * 400], noted)[0]:
                raise ValueError(f"--append-notes must count the old notes plus the appended text: {refusal}")
            if guarded(["update", spike, "--notes", "m" * 2200], noted)[0] or not guarded(["update", spike, "--notes", "m" * 2600], noted)[0]:
                raise ValueError("a shrinking notes edit must pass, a growing one over the limit must not")

            # Comments a session writes (r16-q87): text argument, --file, stdin; the board's own packet passes.
            PACKET = "--board-packet"

            def comment_guarded(argv):
                return board.comment_guard(argv[0], argv[1:])[0]

            if not comment_guarded(["comments", "add", ready, long]) or "comment is 2001 characters" not in comment_guarded(["comments", "add", ready, long]) \
                    or comment_guarded(["comments", "add", ready, "x" * 2000]) or comment_guarded(["comments", "list", ready]) \
                    or comment_guarded(["comments", "add", ready, long, PACKET]) or comment_guarded(["create", "T", long]):
                raise ValueError("board bd comments add must refuse a comment over the limit, pass one within it, and pass the board's own packet")
            if not comment_guarded(["comment", ready, long]) or comment_guarded(["comment", ready, "x" * 2000]):
                raise ValueError("bd's `comment` shorthand must be guarded like `comments add`")
            if not comment_guarded(["comments", "add", ready, "-a", "me", long]) or comment_guarded(["comments", "add", ready, "-a", "x" * 2100, "ok"]):
                raise ValueError("board bd comments add must judge the text, not the author")
            with tempfile.TemporaryDirectory() as folder:
                packet = Path(folder, "packet.md")
                packet.write_text(long, encoding="utf-8")
                if not comment_guarded(["comments", "add", ready, "-f", str(packet)]) or not comment_guarded(["comments", "add", ready, f"--file={packet}"]) \
                        or comment_guarded(["comments", "add", ready, "-f", str(packet), PACKET]):
                    raise ValueError("board bd comments add -f must judge the file")
                with patch.object(board.sys, "stdin", io.StringIO(long)):
                    refusal, stdin = board.comment_guard("comments", ["add", ready, "-f", "-"])
                if not refusal or stdin != long:
                    raise ValueError("board bd comments add -f - must judge stdin and hand it on")
                seen = []
                with patch.object(board.os, "execvpe", lambda *call: seen.append(call[1])), patch.object(board, "ensure_server"), \
                        patch.object(board.subprocess, "run", Fake(fixture)), contextlib.redirect_stdout(io.StringIO()):
                    code = board.main(["bd", "comments", "add", ready, "-f", str(packet), PACKET])
                if seen != [["bd", "comments", "add", ready, "-f", str(packet)]]:
                    raise ValueError(f"the board's own packet must reach bd without the marker: {code} {seen}")
            refused = io.StringIO()
            with patch.object(board.subprocess, "run", Fake(fixture)), contextlib.redirect_stderr(refused):
                code = board.main(["bd", "comments", "add", ready, long])
            if code != 2 or "comment is 2001 characters" not in refused.getvalue():
                raise ValueError(f"board bd comments add did not refuse the over-limit comment: {code} {refused.getvalue()}")
            # handover evidence, return findings and block reasons are refused before any write.
            for argv, actor in ((["handover", "fx-ovo.c2", long], "aaaa1111"),
                                (["return", "fx-ovo.c1", long], "lead0001"),
                                (["block", ready, "--on", ids["Open cache question"], "--reason", long], "lead0001")):
                fake = Fake(variant(**{"CR ready": {"status": "in_review", "assignee": "lead0001", "metadata": {}}}))
                code, _, errors = invoke(argv, fake, actor)
                if code != 1 or fake.writes() or "comment is" not in errors:
                    raise ValueError(f"board {argv[0]} took a comment over the limit: {code} {fake.writes()} {errors}")

            crowded = fixture + [{**next(i for i in fixture if i["title"] == "Held task"), "id": f"fx-extra{n}"}
                                 for n in range(60)]
            _, capped, _ = invoke(["position"], Fake(crowded))
            _, full, _ = invoke(["position", "--all"], Fake(crowded))
            if "held items: 63\n" not in capped or "... 13 more" not in capped or "more" in full:
                raise ValueError("board position must cap sections at 50 rows unless --all")

            _, mine, _ = invoke(["mine"], Fake(fixture), "aaaa1111")
            _, lead_mine, _ = invoke(["mine"], Fake(fixture), "lead0001/review-00000000")
            if ids["Held task"] not in mine or ids["Open cache question"] in mine \
                    or ids["Open cache question"] not in lead_mine or ids["Held task"] in lead_mine:
                raise ValueError(f"board mine matched the wrong holders:\n{mine}\n{lead_mine}")

            # --json views (contract-rulings R-A1, R-B5): unbudgeted JSON, every row, no capacity line after it.
            code, text, _ = invoke(["health", "--json", "--items", "questions,ready", "--limit", "1"], Fake(fixture))
            health_json = json.loads(text)
            if code or health_json["counts"] != {"questions": {"ready": 0, "held": 1, "waiting": 0}, "decided": {"ready": 1, "held": 0, "waiting": 0}, "ratification": 0, "toRatify": {"ready": 0, "held": 0, "waiting": 0},
                                                 "toPlan": {"ready": 2, "held": 0, "waiting": 0}, "toReview": {"ready": 1, "held": 0, "waiting": 0},
                                                 "toAccept": {"ready": 0, "held": 0, "waiting": 0}, "forUser": {"ready": 0, "held": 0, "waiting": 0},
                                                 "ready": 5, "held": 3, "blocked": 3, "outside": 1, "labels": 0} \
                    or health_json["claimable"] != {"plan": 2, "design": 1, "implement": 1, "review": 1, "question": 0,
                                                    "accept": 0, "ratify": 0, "milestone": 0, "refresh": 0} \
                    or len(health_json["items"]["ready"]) != 5 or set(health_json["items"]) != {"questions", "ready"} \
                    or set(health_json["items"]["questions"][0]) != {"id", "type", "status", "priority", "holder", "title", "labels", "blockedBy"} \
                    or health_json["deviations"] != {"count": 3}:
                raise ValueError(f"board health --json: {text[:1500]}")
            blocked = json.loads(invoke(["health", "--json", "--items", "blocked"], Fake(fixture))[1])["items"]["blocked"]
            if not all(row["blockedBy"] for row in blocked) or len(blocked) != 3:
                raise ValueError(f"board health --json rows must name their open blockers: {blocked}")
            _, text, _ = invoke(["mine", "--json"], Fake(fixture), "aaaa1111")
            mine_json = json.loads(text)
            if mine_json["session"] != "aaaa1111" or sorted((i["id"], i["type"], i["holder"], i["workerStopped"]) for i in mine_json["items"]) \
                    != sorted([(ids["Held task"], "task", "aaaa1111/build-12345678", False), ("fx-ovo.c2", "change-request", "aaaa1111", False)]):
                raise ValueError(f"board mine --json: {text}")
            _, text, _ = invoke(["position", "--json"], Fake(fixture))
            position_json = json.loads(text)
            sessions = {s["actor"]: s for s in position_json["sessions"]}
            lead = sessions.get("lead0001") or {}
            if set(lead) != {"session", "role", "actor", "pulls", "tool", "handles", "registeredAt", "holds", "workers",
                             "process", "state", "idleSince", "claimable"} \
                    or lead["role"] != "lead" or lead["holds"] != 1 or lead["workers"] is not None or lead["state"] is not None \
                    or sessions["aaaa1111"]["claimable"] != 2 or sessions["aaaa1111"]["pulls"] != ["implement", "review"] \
                    or position_json["ready"]["implement"] != {"ready": 1, "held": 1, "waiting": 1, "sessions": 2} \
                    or {h["id"] for h in position_json["held"]} != {ids["Held task"], ids["Open cache question"], "fx-ovo.c2"} \
                    or len(position_json["questionsHoldingWork"]) != 2 or len(position_json["finishedEpics"]) != 1:
                raise ValueError(f"board position --json: {text[:2000]}")
            # One command reads the session registry once, whatever number of views and claims consult it (a read costs a bash + jq run).
            class RegistryCounting(Fake):
                registry_reads = 0

                def __call__(self, command, **kwargs):
                    if command[0] == "bash" and command[-1] in ("list", "unreadable") and Path(command[-2]).name == "session":
                        self.registry_reads += 1
                    return super().__call__(command, **kwargs)

            for argv, who in ((["console"], "aaaa1111"), (["position"], "aaaa1111"), (["mine"], "aaaa1111"), (["claim"], "lead0001"),
                              (["take", ids["Held task"]], "aaaa1111"),
                              (["take", ids["Held task"]], "zzzz9999")):  # an unregistered session also asks whether its own file is unreadable
                counting = RegistryCounting(fixture)
                invoke(argv, counting, who)
                if counting.registry_reads != 1:
                    raise ValueError(f"board {argv[0]} read the session registry {counting.registry_reads} times, expected 1")
            # An unreadable registration is skipped alone, its warning reaches the caller once, and its session is then an unregistered
            # one: not marked gone, not allowed to move items (the other sessions are unaffected).
            solo_file = Path(state_dir, "0000-solo0001.json")
            solo_text = solo_file.read_text(encoding="utf-8")
            with patch.dict(os.environ, {"BEADS_ACTOR": "solo0001", "CODEX_SESSION_ID": "", "CLAUDE_CODE_SESSION_ID": ""}), \
                    patch.object(board.subprocess, "run", Fake(fixture)):
                if board.may_move() is not True:
                    raise ValueError("a registered solo session must be allowed to move items")
                solo_file.write_text("{bad", encoding="utf-8")
                try:
                    if board.may_move() is not False:
                        raise ValueError("a session whose registration is unreadable must not be allowed to move items")
                    _, text, errors = invoke(["position", "--json"], Fake(fixture), "lead0001")
                    position_corrupt = json.loads(text)
                    # r3-q16: its own claims and takeovers are refused with the way out, nothing is written; an unregistered session keeps no cap.
                    for verb in ("claim", "take"):
                        fake = Fake(fixture)
                        code, _, refused = invoke([verb, ids["Held task"]], fake, "solo0001")
                        if code != 1 or "this session's registration is unreadable. Register again: /role <role> (Codex: $role <role>)" not in refused or fake.writes():
                            raise ValueError(f"board {verb} by a session whose registration is unreadable must refuse and write nothing: {code} {refused!r} {fake.writes()}")
                    if "unreadable. Register again" in invoke(["claim", ids["Held task"]], Fake(fixture), "lead0001")[2]:
                        raise ValueError("another session's unreadable registration must not refuse this session")
                finally:
                    solo_file.write_text(solo_text, encoding="utf-8")
            if errors.count("skipped unreadable registration") != 1 or "0000-solo0001.json" not in errors:
                raise ValueError(f"board must relay the registry's skip warning once per command: {errors!r}")
            if {s["actor"] for s in position_corrupt["sessions"]} & {"solo0001"} or any(h["mark"] == "gone" for h in position_corrupt["held"] if h["holder"] == "solo0001"):
                raise ValueError(f"a skipped registration must not read as a gone session: {position_corrupt['sessions']}")
            # The pane reads health's counts only: the deviations scan (a bd call per candidate) stays off its path.
            with patch.object(board, "deviations", side_effect=AssertionError("board console ran the deviations scan")):
                if invoke(["console"], Fake(fixture), "aaaa1111")[0] != 0:
                    raise ValueError("board console failed without the deviations scan")
            # board console: the three views the pane draws, from one snapshot.
            prefixed = Fake(fixture)
            prefixed.settings["issue_prefix"] = "fx"
            board._prefix.clear()
            _, text, _ = invoke(["console"], prefixed, "aaaa1111")
            console_json = json.loads(text)
            # The prefix is bd's `issue_prefix`, asked once per run, whatever the ids look like.
            asked = [args for args, _ in prefixed.calls if args[:2] == ["config", "get"] and args[-1] == "issue_prefix"]
            if console_json["prefix"] != "fx" or len(asked) != 1:
                raise ValueError(f"board console must ask bd for issue_prefix once: {console_json['prefix']!r} {asked}")
            _, health_text, _ = invoke(["health", "--json"], Fake(fixture))
            _, position_text, _ = invoke(["position", "--json"], Fake(fixture), "aaaa1111")
            position_view = json.loads(position_text)
            crs_view = console_json.pop("crs")
            ratifications_view = console_json.pop("ratifications")
            console_json.pop("forYou")
            answering, queued_count = console_json.pop("waitingOnYou"), console_json.pop("queued")
            if console_json.pop("noBoard") is not False or (answering, queued_count) != (1, 2) \
                    or console_json.pop("prefix") != "fx":
                raise ValueError(f"board console: noBoard false, the board's prefix, and the 3 waiting requests split into waiting on your answers and queued: {text[:300]}")
            console_counts = console_json.pop("counts")
            position_ready = position_view["ready"]
            if {k: v for k, v in console_counts.items() if k not in ("toDesign", "toImplement")} != json.loads(health_text)["counts"] \
                    or any(console_counts[name] != {k: position_ready[kind][k] for k in ("ready", "held", "waiting")}
                           for name, kind in (("toDesign", "design"), ("toImplement", "implement"))):
                raise ValueError(f"board console counts: health's, with design and implement as position counts them: {console_counts}")
            if [c["id"] for c in crs_view] != ["fx-ovo.c2"] or ratifications_view != [] \
                    or set(crs_view[0]) != {"id", "title", "status", "stage", "holder", "look", "view", "checkpoint", "base", "branch", "worktree", "tip",
                                            "baseTip", "check", "parent", "children", "baseSha", "landBlocked", "reviewState", "refreshWork", "heldByReviewTree", "after",
                                            "setupFailed", "unblocks", "unblocksDirect", "milestone", "priority", "ownPriority", "raisedBy"}:
                raise ValueError(f"board console crs: {crs_view}")
            # The console's stub contract (tests/board-console-contract.ts) declares the CR row it reads: every key it declares must exist.
            contract_file = root / "claude" / "mods" / "console" / "tests" / "board-console-contract.ts"
            if contract_file.is_file():
                body = contract_file.read_text(encoding="utf-8").split("export function cr(")[1].split("return {")[1].split("...over")[0]
                declared = set(re.findall(r"\b([A-Za-z]\w*):", body))
                real_keys = set(crs_view[0]) | set(crs_view[0]["check"])
                if declared - real_keys:
                    raise ValueError(f"board console crs lacks keys the console's contract declares: {sorted(declared - real_keys)}")
                contract = contract_file.read_text(encoding="utf-8").split("export const BOARD_CONSOLE_CONTRACT")[1]
                top = set(re.findall(r"^  (\w+):", contract, re.M))
                if top - {"counts", "crs", "queued", "waitingOnYou", "prefix", "noBoard", "ratifications"} or {"queued", "waitingOnYou", "prefix", "noBoard"} - top \
                        or (top - {"counts", "crs", "ratifications"}) - set(json.loads(text)):
                    raise ValueError(f"the console's contract names keys board console does not print: {sorted(top)}")
                counts_body = contract.split("counts: {")[1].split("\n  },")[0]
                if set(re.findall(r"\b(\w+): \{ ready", counts_body)) - set(console_counts):
                    raise ValueError("the console's contract counts name steps board console does not count")
            if console_json != {"items": [i for i in mine_json["items"] if i["type"] != "change-request"],  # held CRs show in crs
                                "sessions": position_view["sessions"],
                                "held": [{"id": h["id"], "holder": h["holder"], "mark": h["mark"]} for h in position_view["held"]]}:
                raise ValueError(f"board console must equal the health counts, mine items and position sessions: {text[:1500]}")
            # The accept queue is computed once per console run, and handed to the rows' refresh mark.
            # The fixture holds unheld accept-stage requests, whose claimability asks for the queue's head.
            design = next(issue for issue in fixture if issue["title"] == "CR design")
            crowded = variant(**{"CR design": {"status": "needs_acceptance"}}) + [
                {**design, "id": f"fx-ovo.a{n}", "title": f"CR accept {n}", "status": "needs_acceptance"} for n in range(3)]
            stackings, real_stacked = [], board.stacked_order
            with patch.object(board, "stacked_order", side_effect=lambda deck, issues, since: (stackings.append(issues), real_stacked(deck, issues, since))[1]):
                if invoke(["console"], Fake(crowded), "aaaa1111")[0] != 0:
                    raise ValueError("board console failed on a board with accept-stage requests")
            queues = sum(1 for issues in stackings if issues and all(issue["status"] == "needs_acceptance" for issue in issues))
            if queues != 1:
                raise ValueError(f"board console computed the accept queue {queues} times")
            # A bare id gets the board's prefix where board parses ids (bd takes it already); full ids and other prefixes stay.
            prefixed = Fake(fixture)
            prefixed.settings["issue_prefix"] = "fx"
            code, shown, errors = invoke(["show", "ovo.c1"], prefixed, "aaaa1111")
            asked = [args for args, _ in prefixed.calls if args[0] == "show"]
            if code != 0 or not shown.startswith("fx-ovo.c1") or not asked or asked[0][-1] != "fx-ovo.c1":
                raise ValueError(f"board show with an id without the prefix: {code} {shown[:100]} {errors} {asked}")
            prefixed.settings["issue_prefix"] = "fx"
            board._prefix.clear()
            with patch.object(board.subprocess, "run", prefixed):
                resolved = [board.board_id(one) for one in ("28g0i", "ovo.c1", "fx-ovo.c1", "other-abc", "external:x")]
            if resolved != ["fx-28g0i", "fx-ovo.c1", "fx-ovo.c1", "other-abc", "external:x"]:
                raise ValueError(f"board_id: a bare id takes the board's prefix, a full one or another prefix stays: {resolved}")
            # The board lookup is one: BEADS_DIR (as bd reads it) names the board for has_board and ensure_server alike.
            with tempfile.TemporaryDirectory() as named:
                Path(named, "metadata.json").write_text(json.dumps({"dolt_mode": "server"}), encoding="utf-8")
                started, was_checked = [], board._server_checked
                board._server_checked = False
                with patch.dict(os.environ, {"BEADS_DIR": named}), patch.object(board.subprocess, "run", lambda command, **kw: started.append((command, kw.get("cwd")))):
                    found = board.beads_dir()
                    board.ensure_server(Path("/nonexistent"))
                board._server_checked = was_checked
                if found != Path(named) or started != [(["bd", "dolt", "start"], Path(named).parent)]:
                    raise ValueError(f"BEADS_DIR must name the board for beads_dir and ensure_server: {found} {started}")
            with tempfile.TemporaryDirectory() as docs:
                Path(docs, "a.md").write_text("store here\nnothing\nstore again\n", encoding="utf-8")
                _, text, _ = invoke(["related", "store", "--json", "--limit", "1", "--docs", docs], Fake(fixture))
                related_json = json.loads(text)
            if related_json["terms"] != ["store"] or related_json["like"] != [] or len(related_json["items"]) != 1 \
                    or set(related_json["items"][0]) != {"id", "status", "type", "priority", "holder", "title", "matched", "of"} \
                    or related_json["items"][0]["matched"] != 1 or related_json["items"][0]["of"] != 1 \
                    or [(d["line"], d["text"]) for d in related_json["docs"]] != [(1, "store here")]:
                raise ValueError(f"board related --json: {text}")
            with tempfile.TemporaryDirectory() as directory:
                like = Path(directory, "draft.md")
                like.write_text("A zebracache store draft.", encoding="utf-8")
                related_like = json.loads(invoke(["related", "--json", "--like", str(like)], Fake(fixture))[1])
            if related_like["docs"] != [] or related_like["like"] != [t for t in related_like["terms"]]:
                raise ValueError(f"board related --json --like: {related_like}")

            store = ids["Store choice"]
            fake = Fake(fixture, lint={"results": [{"id": store, "missing": ["## Rule owner"]}]})
            code, _, errors = invoke(["ruling", "release", store], fake, "lead0001")
            if code == 0 or "## Rule owner" not in errors or fake.writes():
                raise ValueError("board ruling release accepted a record failing bd lint")
            fake = Fake(fixture)
            if invoke(["ruling", "release", ids["Ready task"]], fake, "lead0001")[0] == 0 or fake.writes():
                raise ValueError("board ruling release accepted a task")
            # Resumable: an already released ruling is done, nothing is written again.
            fake = Fake(fixture)
            code, output, _ = invoke(["ruling", "release", ids["Released ruling"]], fake, "lead0001")
            if code or fake.writes() or f"already released {ids['Released ruling']}" not in output:
                raise ValueError(f"board ruling release must take an already released ruling as done: {fake.calls}\n{output}")
            fake = Fake(variant(**{"Store choice": {"dependencies": [
                *next(i for i in fixture if i["id"] == store)["dependencies"],
                {"issue_id": store, "depends_on_id": ids["Ready task"], "type": "blocks"}]}}))
            if invoke(["ruling", "release", store], fake, "lead0001")[0] == 0 or fake.writes():
                raise ValueError("board ruling release accepted a ruling with an open blocker")
            # A released ruling is a settled premise: it holds no decided record resting on it (health's blockedBy, which the
            # release's drop step reads, and board ruling release agree), an unsettled blocker is refused with its real status, and an
            # open question or work item stays held by it until it is planned.
            released_ruling, ready_task = ids["Released ruling"], ids["Ready task"]

            def with_blockers(*blockers):
                return variant(**{"Store choice": {"status": "decided", "dependencies": [
                    *next(i for i in fixture if i["id"] == store)["dependencies"],
                    *[{"issue_id": store, "depends_on_id": b, "type": "blocks"} for b in blockers]]}})

            def decided_blocked(items):
                _, output, _ = invoke(["health", "--json", "--items", "decided"], Fake(items), "lead0001")
                return next(i["blockedBy"] for i in json.loads(output)["items"]["decided"] if i["id"] == store)

            fake = Fake(with_blockers(released_ruling))
            code, _, errors = invoke(["ruling", "release", store], fake, "lead0001")
            if code or not fake.writes() or decided_blocked(with_blockers(released_ruling)):
                raise ValueError(f"a released blocker must not hold a decided record: {errors}")
            fake = Fake(with_blockers(released_ruling, ready_task))
            code, _, errors = invoke(["ruling", "release", store], fake, "lead0001")
            if code == 0 or fake.writes() or f"{store}: waits on {ready_task} (open)" not in errors \
                    or released_ruling in errors or decided_blocked(with_blockers(released_ruling, ready_task)) != [ready_task]:
                raise ValueError(f"an unsettled blocker refuses with its status, the released one unnamed: {errors}")
            held_by_ruling = variant(**{"Open cache question": {"dependencies": [
                {"issue_id": ids["Open cache question"], "depends_on_id": released_ruling, "type": "blocks"}]}})
            _, output, _ = invoke(["health", "--json", "--items", "blocked"], Fake(held_by_ruling), "lead0001")
            if not any(i["id"] == ids["Open cache question"] and i["blockedBy"] == [released_ruling]
                       for i in json.loads(output)["items"]["blocked"]):
                raise ValueError(f"a released ruling must keep holding an open question: {output}")
            for status in ("open", "in_progress", "needs_ratification"):
                fake = Fake(variant(**{"Store choice": {"status": status}}))
                code, _, errors = invoke(["ruling", "release", store], fake, "lead0001")
                if code == 0 or f"{status}, not decided" not in errors or fake.writes():
                    raise ValueError(f"board ruling release accepted a {status} record")
            fake = Fake(variant(**{"Open cache question": {"status": "decided"}}))
            code, _, _ = invoke(["ruling", "release", store, ids["Open cache question"]], fake, "lead0001")
            batch = [(args, stdin) for args, stdin in fake.calls if args[0] == "batch"]
            question = ids["Open cache question"]
            # A released ruling keeps blocking the items it changes: release only sets the status.
            expected_ops = [f'update {store} status=released assignee=""',
                            f'update {question} status=released assignee=""']
            if code or len(batch) != 1 or len(fake.writes()) != 1 or batch[0][1].splitlines() != expected_ops:
                raise ValueError(f"board ruling release must write one batch of status updates: {fake.calls}")

            # --closes: answered questions close after the release in dependency order, forced only past rulings of
            # this release and questions closed before them here (the gjfh4 case); another open blocker leaves one open.
            cache, spike, loose, ready = ids["Open cache question"], ids["Spike perf"], ids["Loose item"], ids["Ready task"]

            def blocks(item, *blockers):
                return [{"issue_id": item, "depends_on_id": b, "type": "blocks"} for b in blockers]

            answering = variant(**{"Open cache question": {"dependencies": blocks(cache, store)},
                                   "Spike perf": {"issue_type": "decision", "dependencies": blocks(spike, cache, store)},
                                   "Loose item": {"issue_type": "decision", "dependencies": blocks(loose, ready)}})
            fake = Fake(answering)
            code, output, errors = invoke(["ruling", "release", store, "--closes", f"{spike}={store}", f"{cache}={store}", f"{loose}={store}"],
                                          fake, "lead0001")
            closes = [args for args in fake.writes() if args[0] == "close"]
            if code != 1 or closes != [["close", cache, "--reason", f"Answered by released {store}", "--force"],
                                       ["close", spike, "--reason", f"Answered by released {store}", "--force"]] \
                    or fake.writes()[0][0] != "batch" or f"{loose}: left open, blocked by {ready}" not in errors \
                    or f"closed {cache}: answered by released {store}" not in output:
                raise ValueError(f"board ruling release --closes: {fake.writes()}\n{output}\n{errors}")
            # A released ruling outside the release does not leave the answered question open; bd still needs the force.
            fake = Fake(variant(**{"Open cache question": {"dependencies": blocks(cache, store, ids["Released ruling"])}}))
            code, _, errors = invoke(["ruling", "release", store, "--closes", f"{cache}={store}"], fake, "lead0001")
            if code or [args for args in fake.writes() if args[0] == "close"] != [["close", cache, "--reason", f"Answered by released {store}", "--force"]]:
                raise ValueError(f"a released blocker must not leave an answered question open: {fake.writes()}\n{errors}")
            # A bare id (no board prefix) is taken in --closes, both sides of the pair.
            fake = Fake(answering)
            fake.settings["issue_prefix"] = "fx"
            board._prefix.clear()
            code, _, errors = invoke(["ruling", "release", store.removeprefix("fx-"), "--closes", f"{cache.removeprefix('fx-')}={store.removeprefix('fx-')}"], fake, "lead0001")
            if code or [args for args in fake.writes() if args[0] == "close"] != [["close", cache, "--reason", f"Answered by released {store}", "--force"]]:
                raise ValueError(f"board ruling release --closes with bare ids: {code} {fake.writes()}\n{errors}")
            board._prefix.clear()
            # Refused before any write: a question another session holds, a record the call does not release.
            for closes_arg, needle in ((f"{ids['Held task']}={store}", "not an open question"),
                                       (f"{cache}={ids['Old store ruling']}", "which this call does not release")):
                fake = Fake(answering)
                code, _, errors = invoke(["ruling", "release", store, "--closes", closes_arg], fake, "lead0001")
                if code != 1 or needle not in errors or fake.writes():
                    raise ValueError(f"board ruling release --closes {closes_arg}: {errors}")
            held_question = variant(**{"Open cache question": {"assignee": "solo0001"}})
            fake = Fake(held_question)
            code, _, errors = invoke(["ruling", "release", store, "--closes", f"{cache}={store}"], fake, "lead0001")
            if code != 1 or "hand it off" not in errors or fake.writes():
                raise ValueError(f"board ruling release must not close a question another session holds: {errors}")

            # A full supersede blocks the old record's open items on the new one until it is planned,
            # skipping closed and already linked items; --partial only adds the edge. Both drop the pair's existing link first.
            old, new = ids["Old store ruling"], ids["Store choice"]
            old_issue = next(i for i in fixture if i["id"] == old)
            linked = variant(**{"Old store ruling": {"dependencies": [*(old_issue.get("dependencies") or []), *(
                {"issue_id": old, "depends_on_id": ids[title], "type": "relates-to"}
                for title in ("Ready task", "Closed waiter", "Implement store A"))]}})
            fake = Fake(linked)
            code, output, _ = invoke(["ruling", "supersede", old, "--with", new], fake, "lead0001")
            ready = ids["Ready task"]
            reason = f"Blocked by {new}: supersedes {old}; replan against it (the whole item waits)"
            batches = [stdin for args, stdin in fake.calls if args[0] == "batch"]
            if code or [w[:2] for w in fake.writes()] != [["batch", "-m"], ["batch", "-m"], ["comments", "add"],
                                                          ["supersede", old]] \
                    or batches != [f"dep remove {new} {old}\n", f"dep add {ready} {new} blocks\n"] \
                    or fake.writes()[2] != ["comments", "add", ready, reason] \
                    or f"blocked {ready} on {new}" not in output:
                raise ValueError(f"board ruling supersede must block the old record's open items through board block: "
                                 f"{fake.calls}\n{output}")
            fake = Fake(fixture)
            code, _, _ = invoke(["ruling", "supersede", old, "--with", new, "--partial"], fake, "lead0001")
            if code or fake.writes() != [["batch", "-m", f"board ruling supersede {old} --with {new}", "--json"]] \
                    or fake.calls[-1][1] != f"dep remove {new} {old}\ndep add {old} {new} supersedes\n":
                raise ValueError(f"board ruling supersede --partial: {fake.writes()}")

            # supersede --partial "<rule>" names the rule on the old record.
            fake = Fake(fixture)
            code, output, _ = invoke(["ruling", "supersede", old, "--with", new, "--partial", "Rule 2"], fake, "lead0001")
            if code or fake.writes()[-1] != ["comments", "add", old, f'board ruling supersede: rule "Rule 2" superseded by {new}.'] \
                    or "one rule (Rule 2) superseded" not in output:
                raise ValueError(f"board ruling supersede --partial <rule>: {fake.writes()}\n{output}")

            # board show: rendered from the snapshot within READ_BUDGET; cut sections name the command for the rest.
            big = "## Question\nWhich cache?\n\n## Alternatives Considered\n" + "word " * 9000 + "\n### Detail\nfine print\n" \
                  "## Decision\nUse A.\n## Decision log\nlog\n"
            notes = [{"author": f"a{n}", "created_at": f"2026-10-2{n}T00:00:00Z", "text": f"note {n}"} for n in range(7)]
            notes[6]["text"] = "y" * 2500  # the newest comment is long
            shown = variant(**{"Store choice": {"description": big, "comments": notes, "metadata": {"deep_review": "a wrong cache hides"}},
                               "Ready task": {"dependencies": [{"issue_id": ready, "depends_on_id": new, "type": "blocks"}]}},
                            **{"Old store ruling": {"description": "x" * 34000}})
            shown.append({"id": "fx-rev", "title": "Revise the store", "status": "open", "issue_type": "decision",
                          "priority": 2, "metadata": {"board.revises_rule": "Rule 2"},
                          "dependencies": [{"issue_id": "fx-rev", "depends_on_id": new, "type": "tracks"}]})
            code, text, _ = invoke(["show", new], Fake(shown))
            for expected in (f"{new}  decided  decision  p", "\nStore choice\ndeep-review: a wrong cache hides\nlinks:\n", f"  blocks: {ready}  open  Ready task",
                             f"  relates to: {old}  released  Old store ruling",
                             "  revision pending: fx-rev  open  Revise the store  (partial: Rule 2)",
                             "description:\n## Question\nWhich cache?", f'more chars: board show {new} --section \'Alternatives Considered\'',
                             "### Detail\nfine print", "## Decision\nUse A.", "comments: 7, newest 5\n--- a6 ",
                             f"… 2 older: board show {new} --comments"):
                if expected not in text:
                    raise ValueError(f"board show lacks {expected!r}:\n{text[:3000]}")
            if code or len(text) > board.READ_BUDGET or "--- a1 " in text or text.index("--- a6") > text.index("--- a2"):
                raise ValueError(f"board show broke the budget or the comment order ({len(text)} chars)")
            # A plain read cuts each comment at the comment limit with the --comments pointer (r16-q88, q89); --comments prints whole.
            if "y" * 2001 in text or "y" * 2000 + f"\n… cut at 2000 of 2500 characters: board show {new} --comments" not in text:
                raise ValueError(f"board show must cut a long comment at 2000 with the --comments pointer:\n{text[-1500:]}")
            if "y" * 2500 not in invoke(["show", new, "--comments"], Fake(shown))[1]:
                raise ValueError("board show --comments must print a long comment whole")
            if "  revises: " + new not in invoke(["show", "fx-rev"], Fake(shown))[1]:
                raise ValueError("board show of a revision must name the record it revises")
            _, text, _ = invoke(["show", new, "--section", "alternatives"], Fake(shown))
            if "### Detail" not in text and "--full" not in text:
                raise ValueError(f"board show --section must print the heading with its subheadings or cut to --full:\n{text[-500:]}")
            _, text, _ = invoke(["show", new, "--section", "alternatives", "--full"], Fake(shown))
            if "more chars" in text or "### Detail\nfine print" not in text or "## Decision\n" in text:
                raise ValueError("board show --section --full must print the whole section and only it")
            code, _, errors = invoke(["show", new, "--section", "decision"], Fake(shown))
            if code or "ambiguous" in errors:
                raise ValueError("an exact section name must win over its prefix matches")
            code, _, errors = invoke(["show", new, "--section", "d"], Fake(shown))
            if code != 1 or "ambiguous" not in errors or "--section 'Decision log'" not in errors or "--section description" not in errors:
                raise ValueError(f"board show --section must list ambiguous matches:\n{errors}")
            _, text, _ = invoke(["show", new, "--comments"], Fake(shown))
            if text.count("--- a") != 7 or "older" in text or f"comments only: board show {new} --full prints the whole item" not in text:
                raise ValueError(f"board show --comments must print every comment and say the rest is left out:\n{text}")
            _, text, _ = invoke(["show", new], Fake(shown))
            if "comments only" in text:
                raise ValueError(f"board show without --comments prints the whole item, so no note:\n{text}")
            _, text, _ = invoke(["show", new, "--json", "--field", "comments", "--field", "status"], Fake(shown))
            if json.loads(text) != {new: {"comments": shift_dates(notes), "status": "decided"}}:
                raise ValueError(f"board show --json --field: {text[:500]}")
            code, text, errors = invoke(["show", old, "--json", "--field", "metadata"], Fake(shown))  # a field no shown item sets
            if code or json.loads(text) != {old: {"metadata": None}}:
                raise ValueError(f"board show --json --field metadata must answer null for an item without metadata: {text} {errors}")
            for omitted in ("labels", "parent"):  # bd omits these when empty, like metadata
                code, text, errors = invoke(["show", old, "--json", "--field", omitted], Fake(shown))
                if code or json.loads(text) != {old: {omitted: None}}:
                    raise ValueError(f"board show --json --field {omitted} must answer null for an item without it: {text} {errors}")
            if invoke(["show", new, "--json"], Fake(shown))[0] != 1 or invoke(["show", "fx-nope"], Fake(shown))[0] != 1 \
                    or invoke(["show", new, "--field", "desc"], Fake(shown))[0] != 1:
                raise ValueError("board show must refuse --json without --field, unknown ids and unknown fields")
            _, text, _ = invoke(["show", new, old], Fake(shown))
            if len(text) > board.READ_BUDGET or f"\n{old}  released" not in text or f"board show {old} --section description" not in text:
                raise ValueError(f"several ids must share one budget:\n{text[-1500:]}")
            if "more chars" in invoke(["show", new, old, "--full"], Fake(shown))[1]:
                raise ValueError("board show --full must not cut")

            # board ruling record: refuses a file missing a record section; writes the record without comments.
            question = ids["Open cache question"]
            with tempfile.TemporaryDirectory() as directory:
                draft = Path(directory, "record.md")
                draft.write_text("## Question\nq\n## Decision\nd\n## Rationale\nr (user, 2026-10-31)\n", encoding="utf-8")
                fake = Fake(fixture)
                code, _, errors = invoke(["ruling", "record", question, str(draft)], fake, "lead0001")
                if code != 1 or "## Alternatives Considered" not in errors or "## Rule owner" not in errors or fake.writes():
                    raise ValueError(f"board ruling record accepted a file missing sections: {errors}")
                draft.write_text("## Question\nq\n## Alternatives Considered\n- b: rejected\n## Decision\nd\n"
                                 "## Rationale\nr (user, 2026-10-31)\n## Rule owner\ndocs/x.md\n", encoding="utf-8")
                fake = Fake(fixture)
                code, output, _ = invoke(["ruling", "record", question, str(draft)], fake, "lead0001", now="2026-10-31T10:00:00+00:00")
                if code or [w[:2] for w in fake.writes()] != [["update", question]] \
                        or fake.writes()[0][4:] != ["--status", "decided", "--json"] \
                        or not any(args[:2] == ["lint", question] for args, _ in fake.calls) \
                        or output != f"recorded {question} (decided): Open cache question\n":
                    raise ValueError(f"board ruling record: {fake.calls}\n{output}")
                # The board's history keeps earlier versions (r16-q95): a record writes no packet or previous-Decision comment,
                # whether it replaces a packet description or rewrites a Decision; lint failures are loud.
                recorded = variant(**{"Open cache question": {"status": "decided", "description": draft.read_text(encoding="utf-8")}})
                fake = Fake(recorded, lint={"results": [{"id": question, "missing": ["## Extra"]}]})
                code, _, errors = invoke(["ruling", "record", question, str(draft)], fake, "lead0001")
                if code != 1 or "## Extra" not in errors or [w[0] for w in fake.writes()] != ["update"]:
                    raise ValueError(f"board ruling record revised in place wrongly: {fake.writes()} {errors}")
                rewrite = Path(directory, "rewrite.md")
                rewrite.write_text(draft.read_text(encoding="utf-8").replace("## Decision\nd\n", "## Decision\nnew decision\n"), encoding="utf-8")
                fake = Fake(recorded)
                code, output, _ = invoke(["ruling", "record", question, str(rewrite)], fake, "lead0001", now="2026-10-31T10:00:00+00:00")
                if code or [w[0] for w in fake.writes()] != ["update"] or "Decision kept" in output:
                    raise ValueError(f"board ruling record must not copy a replaced Decision into a comment: {fake.writes()} {output}")
                for refused, actor in ((ids["Ready task"], "lead0001"), (question, "aaaa1111")):
                    fake = Fake(fixture)
                    if invoke(["ruling", "record", refused, str(draft)], fake, actor)[0] != 1 or fake.writes():
                        raise ValueError(f"board ruling record wrote {refused} for {actor}")
                # Autopilot: needs_ratification requires ## Reversal and frees the hold.
                fake = Fake(fixture)
                if invoke(["ruling", "record", question, str(draft), "--status", "needs_ratification"], fake, "lead0001")[0] != 1 \
                        or fake.writes():
                    raise ValueError("board ruling record --status needs_ratification accepted a record without ## Reversal")
                draft.write_text(draft.read_text(encoding="utf-8") + "## Reversal\nrevert x\n", encoding="utf-8")
                fake = Fake(fixture)
                code, _, _ = invoke(["ruling", "record", question, str(draft), "--status", "needs_ratification"], fake, "lead0001")
                if code or fake.writes()[-1][4:] != ["--status", "needs_ratification", "--assignee", "", "--json"]:
                    raise ValueError(f"board ruling record --status needs_ratification: {fake.writes()}")

            # board block: relates-to gives way, the reason is a comment (no field rewrite); a review is not returned (an item has none).
            handed = ids["Handed task"]
            blocking = variant(**{"Handed task": {"design": "Plan.", "dependencies": [
                {"issue_id": handed, "depends_on_id": "fx-ovo", "type": "parent-child"},
                {"issue_id": question, "depends_on_id": handed, "type": "relates-to"}]}})
            fake = Fake(blocking)
            code, output, _ = invoke(["block", handed, ready, "--on", question, "--reason", "waits for the cache"], fake, "lead0001")
            batches = [stdin for args, stdin in fake.calls if args[0] == "batch"]
            line_text = f"Blocked by {question}: waits for the cache (the whole item waits)"
            if code or batches != [f'dep remove {question} {handed}\ndep add {handed} {question} blocks\n', f"dep add {ready} {question} blocks\n"] \
                    or any(w[0] == "update" for w in fake.writes()) or ["comments", "add", handed, line_text] not in fake.writes() \
                    or output != f"blocked {handed} on {question}\nblocked {ready} on {question}\n":
                raise ValueError(f"board block: {fake.calls}\n{output}")
            fake = Fake(fixture)
            code, output, errors = invoke(["block", ids["Done child"], ready, "--on", question, "--reason", "r"], fake, "lead0001")
            if code != 1 or ids["Done child"] not in errors or f"blocked {ready} on {question}" not in output:
                raise ValueError(f"board block must report a failed item and continue: {errors}")
            if invoke(["block", ready, "--on", "fx-nope", "--reason", "r"], Fake(fixture), "lead0001")[0] != 1:
                raise ValueError("board block accepted an unknown blocker")
            # A blocks edge already there is no new edge; a reverse one is refused (one edge per pair).
            fake = Fake(fixture)
            invoke(["block", ids["Implement store A"], "--on", new, "--reason", "r"], fake, "lead0001")
            if any(args[0] == "batch" for args, _ in fake.calls):
                raise ValueError(f"board block re-added an existing edge: {fake.calls}")
            if invoke(["block", new, "--on", ids["Implement store A"], "--reason", "r"], Fake(fixture), "lead0001")[0] != 1:
                raise ValueError("board block accepted a pair already linked the other way")

            # r21 steps: a released ruling waits for planning only (q139, q140), step counts split ready and waiting
            # (q141, q146), the claim order (q145), a holder's own block hands back (q144), --part splits (q150-q154).
            ruling, held_task = ids["Released ruling"], ids["Held task"]
            task_wait = {ruling: [{"issue_id": ruling, "depends_on_id": ids["Ready task"], "type": "blocks"}]}

            def with_edges(extra, **changes):
                """The fixture with these extra edges (id -> edges) and field changes by title."""
                rows = variant(**changes)
                return [{**row, "dependencies": [*(row.get("dependencies") or []), *extra.get(row["id"], [])]} for row in rows]

            def wait_on(item_id, blocker):
                return {item_id: [{"issue_id": item_id, "depends_on_id": blocker, "type": "blocks"}]}

            for blocker, allowed in (("Ready task", False), ("Goal", False), ("Design cache", True), ("Spike perf", True),
                                     ("Open cache question", True)):
                fake = Fake(fixture)
                code, _, errors = invoke(["block", ruling, "--on", ids[blocker], "--reason", "r"], fake, "lead0001")
                if (code == 0) != allowed or (not allowed and (fake.writes() or "planning only" not in errors)):
                    raise ValueError(f"board block of a released ruling on a {blocker}: {code} {errors} {fake.writes()}")
            fake = Fake(fixture)
            if invoke(["block", ids["Wire caller"], "--on", ids["Ready task"], "--reason", "r"], fake, "lead0001")[0] != 0:
                raise ValueError("board block refused a task waiting on a task")
            # Only a live decision, a `user <date>` gate, a design or a spike is a planning wait (q139).
            def stub(item_id, kind, status, title):
                return {"id": item_id, "title": title, "issue_type": kind, "status": status, "priority": 2,
                        "created_at": "2026-10-20T10:00:00Z", "dependencies": []}

            waits = [stub("w-user", "gate", "open", "user 2026-11-12: my go"), stub("w-gate", "gate", "open", "ci pipeline"),
                     stub("w-ratify", "decision", "needs_ratification", "revision"), stub("w-decided", "decision", "decided", "revision"),
                     stub("w-released", "decision", "released", "settled"), stub("w-deferred", "decision", "deferred", "later")]
            for blocker, allowed in (("w-user", True), ("w-gate", False), ("w-ratify", True), ("w-decided", True),
                                     ("w-released", False), ("w-deferred", False)):
                fake = Fake([*fixture, *waits])
                code, _, errors = invoke(["block", ruling, "--on", blocker, "--reason", "r"], fake, "lead0001")
                if (code == 0) != allowed or (not allowed and (fake.writes() or "planning only" not in errors)):
                    raise ValueError(f"board block of a released ruling on {blocker}: {code} {errors} {fake.writes()}")
            for blocker, ignored in (("w-user", False), ("w-gate", True), ("w-decided", False), ("w-released", True), ("w-deferred", True)):
                rows = [*fixture, *waits]
                rows = [{**row, "dependencies": [*(row.get("dependencies") or []), *([{"issue_id": ruling, "depends_on_id": blocker, "type": "blocks"}]
                                                                                  if row["id"] == ruling else [])]} for row in rows]
                deck = bare_deck([r for r in rows if r["status"] != "closed"], complete=False)
                if bool(deck.foreign_waits(deck.by_id[ruling])) != ignored or (deck.claimable(deck.by_id[ruling]) == "plan") != ignored:
                    raise ValueError(f"a released ruling waiting on {blocker}: ignored should be {ignored}")

            # A ruling already waiting on work is claimable for plan; the claim names the fix. Design waits still hold it.
            stuck = with_edges(task_wait)
            snapshot = bare_deck([i for i in stuck if i["status"] != "closed"], complete=False)
            ruling_issue = snapshot.by_id[ruling]
            if snapshot.claimable(ruling_issue) != "plan" or snapshot.foreign_waits(ruling_issue) != [ids["Ready task"]]:
                raise ValueError("a released ruling waiting only on work must be claimable for plan")
            designed = with_edges(wait_on(ruling, ids["Design cache"]))
            designed_board = bare_deck([i for i in designed if i["status"] != "closed"], complete=False)
            if designed_board.claimable(designed_board.by_id[ruling]) is not None or designed_board.foreign_waits(designed_board.by_id[ruling]):
                raise ValueError("a released ruling waiting on a design must stay unclaimable")
            code, output, _ = invoke(["claim", ruling], Fake(stuck), "solo0001")
            if f"  fix: {ruling} waits on {ids['Ready task']}" not in output or f"board bd dep remove {ruling} {ids['Ready task']}" not in output:
                raise ValueError(f"board claim must print the fix for a ruling's work wait:\n{output}")
            code, report, _ = invoke(["check"], Fake(stuck))
            if f"  {ruling}  ruling-blocked  board-core.md#statuses-and-labels  released ruling waits on {ids['Ready task']}" not in report \
                    or f"board bd dep remove {ruling} {ids['Ready task']}" not in report:
                raise ValueError(f"board check lacks ruling-blocked:\n{report}")
            if "ruling-blocked" in invoke(["check"], Fake(designed))[1].replace("ruling-blocked (", ""):
                raise ValueError("board check flagged a ruling waiting on a design")
            if "1 ruling waits wrongly: board check" not in invoke(["health"], Fake(stuck))[1]:
                raise ValueError("board health lacks the hint for command-fixed deviations")

            # Counts: ready = can be taken now, waiting = the rest of the step.
            _, text, _ = invoke(["health", "--json"], Fake(designed))
            counts = json.loads(text)["counts"]
            if counts["toPlan"] != {"ready": 1, "held": 0, "waiting": 1} or {k: v for k, v in json.loads(invoke(["console"], Fake(designed), "aaaa1111")[1])["counts"].items() if k not in ("toDesign", "toImplement")} != counts:
                raise ValueError(f"toPlan must split claimable and waiting rulings, console equal to health: {counts}")
            if "released rulings to plan: 1 (1 wait)\n" not in invoke(["health"], Fake(designed))[1] \
                    or "plan: 1 ready (1 wait), " not in invoke(["position"], Fake(designed))[1] \
                    or json.loads(invoke(["position", "--json"], Fake(designed))[1])["ready"]["plan"]["waiting"] != 1:
                raise ValueError("board health and position must print '(k wait)' beside the ready count")
            accepting = variant(**{"CR design": {"status": "needs_acceptance"},
                                   "CR ready": {"status": "in_review", "assignee": "cccc3333", "metadata": {}}})
            counts = json.loads(invoke(["health", "--json", "--items", "accept"], Fake(accepting))[1])
            if counts["counts"]["toAccept"] != {"ready": 1, "held": 0, "waiting": 0} or counts["counts"]["toReview"] != {"ready": 1, "held": 1, "waiting": 0} \
                    or [row["id"] for row in counts["items"]["toAccept"]] != ["fx-ovo.c4"] or "inReview" in counts["counts"]:
                raise ValueError(f"change requests waiting for the user count as to accept, the ones in agent review as to review (a held one is held): {counts}")
            accept_view = invoke(["health", "--items", "accept"], Fake(accepting))[1]
            if "to accept (change requests waiting for the user): 1\n" not in accept_view or "fx-ovo.c4" not in accept_view:
                raise ValueError(f"board health lacks the to-accept view:\n{accept_view}")
            topical = variant(**{"Loose item": {"labels": ["topic:store"]}})
            if "outside any epic, no topic: label: 0\n" not in invoke(["health"], Fake(topical))[1]:
                raise ValueError("an item with a topic: label stands alone without being outside any epic")

            # Held and waiting split a step's rest: waiting = blocked (held or not), held = holder and not blocked.
            rows = [{**row, "dependencies": [*(row.get("dependencies") or []), *([{"issue_id": row["id"], "depends_on_id": question, "type": "blocks"}]
                                                                                 if row["title"] in ("CR design", "CR ready") else [])]}
                    for row in variant(**{"CR design": {"status": "needs_acceptance", "assignee": "cccc3333"},
                                          "CR ready": {"status": "in_review", "assignee": "cccc3333", "metadata": {}},
                                          "Handed task": {"assignee": "dddd4444"}})]
            held_view = json.loads(invoke(["health", "--json"], Fake(rows))[1])["counts"]
            if held_view["toAccept"] != {"ready": 0, "held": 0, "waiting": 1} or held_view["toReview"] != {"ready": 0, "held": 1, "waiting": 1}:
                raise ValueError(f"a blocked item waits whoever holds it, a held unblocked one is held: {held_view}")
            if "to accept (change requests waiting for the user): 0 (1 wait)\n" not in invoke(["health"], Fake(rows))[1] \
                    or "to review (change requests in agent review): 0 (1 held, 1 wait)\n" not in invoke(["health"], Fake(rows))[1]:
                raise ValueError("health text prints '(h held, k wait)' with zero parts left out")
            user_held = variant(**{"Ready task": {"assignee": "user"}, "Loose item": {"assignee": "user"}})
            if json.loads(invoke(["health", "--json"], Fake(user_held))[1])["counts"]["forUser"] != {"ready": 2, "held": 0, "waiting": 0}:
                raise ValueError("the user view's own holds are not held")
            # board console forYou: the user view's ready items (a blocked one only counts as waiting), for the pane's list.
            blocked_user = [{**row, "dependencies": [*(row.get("dependencies") or []), {"issue_id": row["id"], "depends_on_id": question, "type": "blocks"}]}
                            if row["title"] == "Loose item" else row for row in user_held]
            for_you = json.loads(invoke(["console"], Fake(blocked_user), "aaaa1111")[1])["forYou"]
            if [row["id"] for row in for_you] != [next(r["id"] for r in user_held if r["title"] == "Ready task")] \
                    or set(for_you[0]) != {"id", "type", "status", "priority", "holder", "title", "labels", "blockedBy"}:
                raise ValueError(f"board console forYou must list the ready items assigned to the user, not the blocked one: {for_you}")
            # r22-q171: an item assigned to the user is never held, in any view; a session's hold still is.
            mixed = variant(**{"Store choice": {"status": "open", "assignee": "user"}, "Ready task": {"assignee": "user"}})
            unassigned = variant(**{"Store choice": {"status": "open", "assignee": None}, "Ready task": {"assignee": None}})
            shown_views = ["--json", "--items", "held,questions"]
            mixed_health, plain_health = (json.loads(invoke(["health", *shown_views], Fake(issues))[1]) for issues in (mixed, unassigned))
            if mixed_health["counts"]["held"] != plain_health["counts"]["held"] or mixed_health["items"]["held"] != plain_health["items"]["held"] \
                    or mixed_health["counts"]["questions"]["held"] != plain_health["counts"]["questions"]["held"] \
                    or mixed_health["counts"]["held"] == 0:
                raise ValueError(f"an item assigned to the user must not count as held: {mixed_health['counts']} {plain_health['counts']}")
            if any(h["holder"] == "user" for h in json.loads(invoke(["position", "--json"], Fake(mixed))[1])["held"]):
                raise ValueError("board position lists the user's item among the held")
            if '"held"' not in invoke(["position", "--json"], Fake(rows))[1]:
                raise ValueError("position JSON lacks held")

            # Claim order: P0, milestone, then finishing work and planning linked to running work, then priority and kind.
            def entry(item_id, kind, status, priority, **more):
                return {"id": item_id, "title": item_id, "issue_type": kind, "status": status, "priority": priority,
                        "created_at": "2026-10-20T10:00:00Z", "dependencies": [], **more}

            def unit(item_id, kind, status, priority, **more):
                """What a claim finds for work: a change request with one open item (a pull's kind comes from the item's)."""
                if kind not in ("task", "design"):
                    return [entry(item_id, kind, status, priority, **more)]
                item = entry(f"{item_id}.i", kind, "open", priority, dependencies=[{"issue_id": f"{item_id}.i", "depends_on_id": item_id, "type": "parent-child"}])
                return [entry(item_id, "change-request", status, priority, **more), item]

            def order_of(*groups):
                issues = [issue for group in groups for issue in group]
                deck = bare_deck(issues, complete=False)
                return [i["id"] for i in sorted((i for i in issues if deck.claimable(i) and i["issue_type"] != "task"), key=lambda i: board.claim_order(deck, i))]

            link = {"issue_id": "ruling-linked", "depends_on_id": "running", "type": "relates-to"}
            back = {"issue_id": "running", "depends_on_id": "ruling-back", "type": "blocks"}
            waiting_review = {}
            sequence = order_of(
                unit("impl-p1", "task", "open", 1), unit("design-p2", "design", "open", 2), unit("ruling-free", "decision", "released", 3),
                unit("ruling-linked", "decision", "released", 3, dependencies=[link]), unit("ruling-back", "decision", "released", 3),
                unit("running", "task", "in_progress", 2, assignee="aaaa1111", dependencies=[back]),
                unit("review-p3", "change-request", "in_review", 3, **waiting_review),
                unit("accept-p3", "change-request", "needs_acceptance", 3),
                unit("ratify-p3", "decision", "needs_ratification", 3), unit("question-p1", "decision", "open", 1),
                unit("zero", "task", "open", 0), unit("impl-p2", "task", "open", 2))
            if sequence != ["zero", "ruling-back", "ruling-free", "ruling-linked", "review-p3", "accept-p3", "ratify-p3", "question-p1",
                            "impl-p1", "design-p2", "impl-p2"]:
                raise ValueError(f"board claim order: {sequence}")
            equal = order_of(unit("a-impl", "task", "open", 2), unit("b-question", "decision", "open", 2), unit("c-design", "design", "open", 2),
                             unit("d-plan", "decision", "released", 2))
            if equal != ["d-plan", "c-design", "b-question", "a-impl"]:
                raise ValueError(f"at equal priority plan > design > question > implement: {equal}")

            def waits_on(item_id, blocker):
                return {"issue_id": item_id, "depends_on_id": blocker, "type": "blocks"}

            # r23-q180, r22-q176: planning of any released ruling comes after P0 and before milestone work, review and the rest.
            in_milestone = order_of(
                unit("m", "milestone", "open", 1, dependencies=[waits_on("m", "ms-work")]), unit("ms-work", "task", "open", 3),
                unit("out-plan", "decision", "released", 4), unit("out-review", "change-request", "in_review", 0 + 3, **waiting_review),
                unit("out-impl", "task", "open", 1), unit("p0", "task", "open", 0))
            if in_milestone != ["p0", "out-plan", "ms-work", "out-review", "out-impl"]:
                raise ValueError(f"claim order tiers are P0, planning, milestone work, review/ratify/accept, the rest: {in_milestone}")
            # r22-q179: an item counts at the highest priority waiting on it, transitively; closed waiters, milestones and
            # the item's own lower urgency confer nothing; the claim line names why.
            chain = [*unit("low", "task", "open", 3), *unit("mid", "task", "open", 2, dependencies=[waits_on("mid", "low")]),
                     entry("top", "decision", "open", 0, dependencies=[waits_on("top", "mid")]),
                     *unit("shut", "task", "closed", 0, dependencies=[waits_on("shut", "calm")]), *unit("calm", "task", "open", 3),
                     entry("ms", "milestone", "open", 0, dependencies=[waits_on("ms", "calm")]), *unit("plain", "task", "open", 1)]
            deck = bare_deck(chain, complete=False)
            if [board.effective_priority(deck, deck.by_id[name]) for name in ("low", "mid", "calm", "plain")] \
                    != [(0, "top", False), (0, "top", False), (3, None, False), (1, None, False)]:
                raise ValueError("effective priority is the highest among the item and what waits on it, transitively, open items only")
            if order_of(chain) != ["low", "calm", "plain"]:  # mid waits on low; calm is milestone work, which goes before plain P1
                raise ValueError(f"claim order by effective priority: {order_of(chain)}")
            fake = Fake(chain)
            _, out, err_out = invoke(["claim", "low"], fake, "solo0001")
            if "claimed low (implement; P3, counts as P0: blocks top)" not in out:
                raise ValueError(f"the claim line must name an inherited priority: {out} {err_out}")
            _, out, _ = invoke(["claim", "plain"], Fake(chain), "solo0001")
            if "claimed plain (implement):" not in out:
                raise ValueError(f"a claim at its own priority names nothing: {out}")

            # A holder's own block hands the item back; another session's block leaves the hold (q144, only the holder's own).
            held_rows = variant(**{"Held task": {"notes": "Waits on the cache."}})
            for actor, handed_back in (("aaaa1111/build-12345678", True), ("lead0001", False)):
                fake = Fake(held_rows)
                code, output, errors = invoke(["block", held_task, "--on", question, "--reason", "needs the cache"], fake, actor)
                unclaims = [w for w in fake.writes() if w[0] == "unclaim"]
                if code or bool(unclaims) != handed_back or (handed_back and (unclaims[0][1] != held_task or "handed back" not in output)):
                    raise ValueError(f"board block by {actor} on a held item: {fake.calls} {errors}")
            whole = Fake(fixture)
            invoke(["block", ready, "--on", question, "--reason", "waits"], whole, "lead0001")
            if ["comments", "add", ready, f"Blocked by {question}: waits (the whole item waits)"] not in whole.writes():
                raise ValueError("a block must say the whole item waits")

            # board ruling revise: a linked open decision, parent and topic labels from the old record; prints the new id.
            topical = variant(**{"Released ruling": {"labels": ["topic:store", "area"]}})
            fake = Fake(topical)
            code, output, _ = invoke(["ruling", "revise", ids["Released ruling"], "--title", "May B replace A?", "--body-file", "p.md",
                                      "--partial", "Rule 2"], fake, "lead0001")
            if code or output != "fx-new\n" or fake.writes() != [[
                    "create", "--type", "decision", "--title", "May B replace A?", "--body-file", "p.md", "--priority", "2",
                    "--deps", f"tracks:{ids['Released ruling']}", "--labels", "topic:store",
                    "--metadata", '{"board.revises_rule": "Rule 2"}', "--deps", "parent-child:fx-ovo", "--json"]]:
                raise ValueError(f"board ruling revise: {fake.writes()}\n{output}")
            fake = Fake(topical)
            invoke(["ruling", "revise", ids["Released ruling"], "--title", "t", "--body-file", "p.md", "-p", "1", "--parent", goal,
                    "-l", "topic:a,topic:b"], fake, "lead0001")
            if fake.writes()[0][8:] != ["1", "--deps", f"tracks:{ids['Released ruling']}", "--labels",
                                        "topic:a,topic:b", "--deps", f"parent-child:{goal}", "--json"]:
                raise ValueError(f"board ruling revise ignored -p/--parent/-l or set metadata without --partial: {fake.writes()}")
            fake = Fake(topical)
            fake.settings["issue_prefix"] = "fx"
            board._prefix.clear()
            invoke(["ruling", "revise", ids["Released ruling"], "--title", "t", "--body-file", "p.md", "--parent", goal.removeprefix("fx-")], fake, "lead0001")
            if not fake.writes() or fake.writes()[0][-2:] != [f"parent-child:{goal}", "--json"]:
                raise ValueError(f"board ruling revise --parent takes a bare id: {fake.writes()}")
            board._prefix.clear()
            fake = Fake(topical)
            invoke(["ruling", "revise", ids["Released ruling"], "--title", "t", "--body-file", "p.md", "--external-ref", "protocol:s1:r2:q3"], fake, "lead0001")
            written = fake.writes()[0] if fake.writes() else []
            if "--external-ref" not in written or written[written.index("--external-ref") + 1] != "protocol:s1:r2:q3":
                raise ValueError(f"board ruling revise must pass --external-ref to bd create: {fake.writes()}")
            for refused in (question, ready):
                fake = Fake(fixture)
                if invoke(["ruling", "revise", refused, "--title", "t", "--body-file", "p.md"], fake, "lead0001")[0] != 1 or fake.writes():
                    raise ValueError(f"board ruling revise accepted {refused}")

            # board ruling release supersedes the records its rulings revise and lists the reviews that went back.
            revising = variant(**{"Store choice": {"dependencies": [{"issue_id": new, "depends_on_id": old, "type": "tracks"}]},
                                  "Handed task": {"dependencies": [{"issue_id": handed, "depends_on_id": old, "type": "relates-to"}]}})
            fake = Fake(revising)
            code, output, _ = invoke(["ruling", "release", new], fake, "lead0001")
            batches = [stdin for args, stdin in fake.calls if args[0] == "batch"]
            if code or batches[:2] != [f'update {new} status=released assignee=""\n', f"dep remove {new} {old}\n"] \
                    or ["supersede", old, "--with", new] not in fake.writes() \
                    or f"superseded {old} by {new}" not in output or "returned from review" in output:
                raise ValueError(f"board ruling release must supersede revised records: {fake.calls}\n{output}")
            partial = [{**issue, "metadata": {"board.revises_rule": "Rule 2"}} if issue["id"] == new else issue for issue in revising]
            fake = Fake(partial)
            code, output, _ = invoke(["ruling", "release", new], fake, "lead0001")
            if code or [stdin for args, stdin in fake.calls if args[0] == "batch"][1] != f"dep remove {new} {old}\ndep add {old} {new} supersedes\n" \
                    or any(args[0] == "supersede" for args in fake.writes()) or "one rule (Rule 2)" not in output:
                raise ValueError(f"board ruling release of a partial revision: {fake.calls}\n{output}")

            # Replaced records (r12-q44): a decided record a live question revises is not released alone; a chain of
            # revisions is followed to the first released record; supersede carries a pending revision to its replacement.
            def record(rid, status, *links, **extra):
                return {"id": rid, "title": rid, "status": status, "issue_type": "decision", "priority": 2,
                        "dependencies": [{"issue_id": rid, "depends_on_id": target, "type": kind} for target, kind in links], **extra}

            chain = [record("fx-a", "released"), record("fx-b", "decided", ("fx-a", "tracks")),
                     record("fx-c", "decided", ("fx-b", "tracks"))]
            fake = Fake(chain)
            code, output, errors = invoke(["ruling", "release", "fx-c"], fake, "lead0001")
            if code or [args for args in fake.writes() if args[0] == "supersede"] != [["supersede", "fx-b", "--with", "fx-c"],
                                                                                   ["supersede", "fx-a", "--with", "fx-c"]] \
                    or "superseded fx-a by fx-c" not in output:
                raise ValueError(f"board ruling release must follow a chain of revisions to the first released record: {fake.writes()}\n{output}{errors}")
            partly = [{**issue, "metadata": {"board.revises_rule": "Rule 2"}} if issue["id"] == "fx-b" else issue for issue in chain]
            fake = Fake(partly)
            code, output, _ = invoke(["ruling", "release", "fx-c"], fake, "lead0001")
            if code or [args for args in fake.writes() if args[0] == "supersede"] != [["supersede", "fx-b", "--with", "fx-c"]] \
                    or "dep add fx-a fx-c supersedes\n" not in [stdin for args, stdin in fake.calls if args[0] == "batch"] or "fx-a: one rule (Rule 2)" not in output:
                raise ValueError(f"a chain carries the replaced record's own rule: {fake.writes()}\n{output}")
            fake = Fake(chain)
            code, _, errors = invoke(["ruling", "release", "fx-b"], fake, "lead0001")
            if code != 1 or "fx-b: revised by fx-c" not in errors or fake.writes():
                raise ValueError(f"board ruling release must refuse a decided record a live question revises: {errors}\n{fake.writes()}")
            for allowed, args in ((chain, ["fx-b", "fx-c"]), ([*chain[:2], {**chain[2], "status": "closed"}], ["fx-b"])):
                fake = Fake(allowed)
                if invoke(["ruling", "release", *args], fake, "lead0001")[0] or not fake.writes():
                    raise ValueError(f"board ruling release {args}: a revision released together or closed is no refusal")
            # supersede carries the revision the old record still has pending, with its rule, to the new one.
            carried = [record("fx-a", "released"), record("fx-b", "decided", ("fx-a", "tracks"), metadata={"board.revises_rule": "Rule 2"}),
                       record("fx-d", "decided", ("fx-b", "tracks"))]
            fake = Fake(carried)
            code, output, _ = invoke(["ruling", "supersede", "fx-b", "--with", "fx-d"], fake, "lead0001")
            if code or fake.writes() != [["update", "fx-d", "--set-metadata", "board.revises_rule=Rule 2", "--json"],
                                         ["batch", "-m", "board ruling supersede fx-b --with fx-d", "--json"], ["supersede", "fx-b", "--with", "fx-d"]] \
                    or [stdin for args, stdin in fake.calls if args[0] == "batch"] != ["dep remove fx-d fx-b\ndep remove fx-b fx-a\ndep add fx-d fx-a tracks\n"] \
                    or "revision of fx-a now pending on fx-d" not in output:
                raise ValueError(f"board ruling supersede must move the pending revision and its rule: {fake.writes()}\n{output}")
            busy = [*carried[:2], record("fx-d", "decided", ("fx-b", "tracks"), ("fx-z", "tracks")), record("fx-z", "released")]
            fake = Fake(busy)
            code, _, errors = invoke(["ruling", "supersede", "fx-b", "--with", "fx-d"], fake, "lead0001")
            if code != 1 or "keeps one revision rule" not in errors or fake.writes():
                raise ValueError(f"board ruling supersede must refuse a carry onto a record that revises another: {errors}\n{fake.writes()}")
            # board check --json: the rows a Release Board check reads (no text parsing).
            unlinked = [record("fx-a", "released"), record("fx-b", "decided", notes="This revises fx-a for the cache.")]
            code, text, _ = invoke(["check", "--json"], Fake(unlinked))
            found = json.loads(text)
            if code or found["unlinkedRevisions"] != [{"id": "fx-b", "other": "fx-a", "word": "revises", "old": "fx-a", "new": "fx-b"}] \
                    or set(found) != {"deviations", "squashed", "unnamedBlockers", "unlinkedRevisions", "staleHolds", "forcedHolds"}:
                raise ValueError(f"board check --json: {text}")

            # board check: an unlinked revision is a flag; a standalone review waiting on a blocker deviates no more (reviews do not wait).
            stuck = variant(**{"Handed task": {"dependencies": [{"issue_id": handed, "depends_on_id": question, "type": "blocks"}]},
                               "Store choice": {"notes": f"This revises {old} for the cache."}})
            code, report, _ = invoke(["check"], Fake(stuck))
            if "review-blocked" in report or f"  {new}  unlinked-revision  revises {old}" not in report:
                raise ValueError(f"board check dropped an unlinked revision or kept review-blocked:\n{report}")
            # Rejected alternatives are no revision; a passive "revised by <id>" flags the reverse pair.
            for notes, expected in ((f"## Alternatives Considered\n- Rejected: this revises {old}.\n## Decision\nx", None),
                                    (f"(Revised by the superseding rulings: per {old} the cache stays.)",
                                     f"  {new}  unlinked-revision  revised by {old} without a supersedes or revise link: "
                                     f"board ruling supersede {new} --with {old}")):
                report = invoke(["check"], Fake(variant(**{"Store choice": {"notes": notes}})))[1]
                if ("unlinked-revision" in report) if expected is None else (expected not in report):
                    raise ValueError(f"board check misread {notes!r}:\n{report}")
            # A partial supersede by a closed record still adds the edge; a full one needs an open record.
            closed_new = variant(**{"Store choice": {"status": "closed"}})
            if invoke(["ruling", "supersede", old, "--with", new, "--partial", "Rule 2"], Fake(closed_new), "lead0001")[0] \
                    or invoke(["ruling", "supersede", old, "--with", new], Fake(closed_new), "lead0001")[0] != 1:
                raise ValueError("board ruling supersede must take a closed new record for --partial only")
            # A wait named only in a comment (board block's reason) is named.
            wire, cache = ids["Wire caller"], ids["Open cache question"]
            if f"  {wire}  unnamed-blocker" not in invoke(["check"], Fake(fixture))[1] or f"  {wire}  unnamed-blocker" in invoke(
                    ["check"], Fake(variant(**{"Wire caller": {"comments": [{"text": f"Blocked by {cache}: r"}]}})))[1]:
                raise ValueError("board check must read a wait's reason from the item's comments")
            linked_revision = [{**issue, "dependencies": [*issue["dependencies"], {"issue_id": old, "depends_on_id": new,
                                                                                    "type": "supersedes"}]}
                               if issue["id"] == old else issue for issue in stuck]
            if "unlinked-revision" in invoke(["check"], Fake(linked_revision))[1]:
                raise ValueError("board check flagged a revision with its supersedes link")

            # Views: --limit everywhere (--all is --limit 0), a READ_BUDGET cut names a --limit that fits.
            many = fixture + [{**next(i for i in fixture if i["title"] == "CR ready"), "id": f"fx-wide{n:03}",
                               "title": "t" * 300} for n in range(200)]
            for view in (["queue"], ["holders"], ["health", "--items", "ready"], ["position"], ["check"], ["mine"],
                         ["related", "ready"]):
                if invoke([*view, "--limit", "2"], Fake(many), "aaaa1111")[0] not in (0, 1):
                    raise ValueError(f"board {view[0]} must take --limit")
            code, text, _ = invoke(["queue", "--limit", "0"], Fake(many))
            page = re.search(r"… (\d+) more rows: board queue --limit 0 --offset (\d+)\n$", text)
            if len(text) > board.READ_BUDGET or not page:
                raise ValueError(f"board queue must cut at READ_BUDGET and name the --offset of the next rows:\n{text[-400:]}")
            shown = [r for r in text.splitlines() if r.startswith("  ")]
            follow = invoke(["queue", "--limit", "0", "--offset", page.group(2)], Fake(many))[1]
            rest = [r for r in follow.splitlines() if r.startswith("  ")]
            if len(follow) > board.READ_BUDGET or "more rows" in follow or int(page.group(2)) != len(shown) \
                    or len(rest) != int(page.group(1)) or not follow.startswith("plan: ") or rest[0] in shown:
                raise ValueError(f"board queue --offset must print the next rows under their section heading:\n{follow[:400]}")
            if "... 195 more" not in invoke(["health", "--items", "ready", "--limit", "10"], Fake(many))[1]:
                raise ValueError("board health --items must respect --limit")
            for argv, hint in ((["queue", "review"], "board health --items review"), (["queue", "accept"], "board health --items accept"), (["queue", "ratify"], "board health --items ratify"), (["queue", "nonsense"], None)):
                errors = io.StringIO()
                with contextlib.redirect_stderr(errors):
                    try:
                        board.main(argv)
                    except SystemExit as error:
                        if error.code != 2:
                            raise ValueError(f"board {argv} exited {error.code}") from None
                if (hint not in errors.getvalue()) if hint else ("health --items" in errors.getvalue()):
                    raise ValueError(f"board {argv} hint: {errors.getvalue()}")

            # board related: rarest shared words first; --like picks distinctive draft words; --root scopes.
            ranked = fixture + [
                {"id": "fx-r1", "title": "common common", "status": "open", "issue_type": "task", "priority": 0, "dependencies": []},
                {"id": "fx-r2", "title": "zebracache", "status": "open", "issue_type": "task", "priority": 3, "dependencies": []}]
            ranked = [issue if issue["id"] == "fx-r2" else {**issue, "description": f"{issue.get('description', '')} common often"}
                      for issue in ranked]
            _, text, _ = invoke(["related", "common", "often", "zebracache"], Fake(ranked))
            rows = [r for r in text.splitlines() if r.startswith("  fx-")]
            # One rare match outranks two template words; equal scores go by priority.
            if not rows[0].startswith("  fx-r2 ") or "1/3 terms" not in rows[0] or not rows[1].startswith("  fx-r1 "):
                raise ValueError(f"board related must rank the rare match first:\n{text}")
            with tempfile.TemporaryDirectory() as directory:
                like = Path(directory, "draft.md")
                like.write_text("The zebracache and the common store, tenancy too, plus unseenword.", encoding="utf-8")
                _, text, _ = invoke(["related", "--like", str(like)], Fake(ranked))
            header = text.splitlines()[0]
            if "from --like: tenancy, zebracache" not in header and "from --like: zebracache, tenancy" not in header \
                    or "common" in header.split("from --like")[1] or "unseenword" in header or "the" in header.split(": ")[-1].split(", "):
                raise ValueError(f"board related --like chose the wrong terms:\n{header}")
            _, text, _ = invoke(["related", "store", "--root", ids["Finished outcome"]], Fake(ranked))
            if any(r.startswith("  fx-ovo.1 ") for r in text.splitlines()) or "items matching store" not in text:
                raise ValueError(f"board related ignored --root:\n{text}")
            with tempfile.TemporaryDirectory() as docs:
                Path(docs, "a.md").write_text("tenancy a\n", encoding="utf-8")
                Path(docs, "b.md").write_text("tenancy b\n", encoding="utf-8")
                text = invoke(["related", "tenancy", "--docs", f"{docs}/a.md,{docs}/b.md"], Fake(fixture))[1]
            if "a.md:1" not in text or "b.md:1" not in text:
                raise ValueError(f"board related --docs must accept commas:\n{text}")

            # board help: every command with an example; <cmd> --help ends with it.
            help_output = io.StringIO()
            with contextlib.redirect_stdout(help_output):
                board.main(["help"])
            for name in ("show", "cr", "ruling", "block", "related", "handover"):
                if f"usage: board {name}" not in help_output.getvalue() or board.EXAMPLES[name] not in help_output.getvalue():
                    raise ValueError(f"board help lacks {name} or its example")
            with contextlib.redirect_stdout(io.StringIO()) as sub_help:
                try:
                    board.main(["block", "--help"])
                except SystemExit:
                    pass
            if not sub_help.getvalue().rstrip().endswith(f"example: {board.EXAMPLES['block']}"):
                raise ValueError(f"board block --help must end with its example:\n{sub_help.getvalue()}")

            # r15-q80/q90: the old flat names are unknown verbs; board names the group command, asking bd nothing. A verb bd knows
            # points to `board bd`; one bd rejects keeps argparse's error. Nothing is forwarded or run either way.
            def refusal(argv):
                asked = Fake(fixture)
                with patch.object(board.subprocess, "run", asked), contextlib.redirect_stdout(io.StringIO()), \
                        contextlib.redirect_stderr(io.StringIO()) as refused:
                    try:
                        code = board.main(argv)
                    except SystemExit as stop:
                        code = stop.code
                return code, refused.getvalue(), [call[0] for call in asked.calls]

            for old, group in (("land", "cr"), ("refresh", "cr"), ("reject", "cr"), ("record", "ruling"), ("revise", "ruling"),
                               ("release", "ruling"), ("supersede", "ruling")):
                result = refusal([old, "x-1", "two words"])
                if result != (2, f"board: no verb '{old}'; run: board {group} {old} x-1 'two words'\n", []):
                    raise ValueError(f"board {old} refusal: {result}")
            for argv, message in ((["comment", "fx-1", "a note", "-m"], "board: no verb 'comment'; run: board bd comment fx-1 'a note' -m\n"),
                                  (["comment"], "board: no verb 'comment'; run: board bd comment\n")):
                result = refusal(argv)
                if result != (2, message, [["comment", "--help"]]):
                    raise ValueError(f"board {argv} refusal: {result}")
            code, message, asked = refusal(["nonsense", "x"])
            if code != 2 or "invalid choice: 'nonsense'" not in message or "run:" in message or asked != [["nonsense", "--help"]]:
                raise ValueError(f"board must keep argparse's error for a verb bd rejects: {code} {message} {asked}")
            # a bare call prints the help and exits 0, reading nothing
            bare_fake, bare_output = Fake(fixture), io.StringIO()
            with patch.object(board.subprocess, "run", bare_fake), contextlib.redirect_stdout(bare_output):
                bare_code = board.main([])
            if bare_code != 0 or bare_output.getvalue() != help_output.getvalue() or bare_fake.calls:
                raise ValueError(f"bare board must print the help and exit 0:\n{bare_output.getvalue()}")
            with contextlib.redirect_stdout(io.StringIO()) as land_help:
                try:
                    board.main(["cr", "land", "--help"])
                except SystemExit as stop:
                    if stop.code:
                        raise ValueError(f"board cr land --help: {stop.code}") from None
            if "usage: board cr land" not in land_help.getvalue() or not land_help.getvalue().rstrip().endswith(f"example: {board.EXAMPLES['cr land']}"):
                raise ValueError(f"board cr land must parse and end its help with its example:\n{land_help.getvalue()}")
            for group, verbs in (("cr", ("land", "refresh", "reject")), ("ruling", ("record", "revise", "release", "supersede"))):
                with contextlib.redirect_stdout(io.StringIO()) as listing:
                    code = board.main([group])
                for verb in verbs:
                    if code or f"usage: board {group} {verb}" not in listing.getvalue() or board.EXAMPLES[f"{group} {verb}"] not in listing.getvalue():
                        raise ValueError(f"board {group} must list {verb} with its example:\n{listing.getvalue()}")
            if "board cr" not in help_output.getvalue() or "board ruling" not in help_output.getvalue():
                raise ValueError("board help must list the groups cr and ruling")

            fake = Fake(fixture)
            invoke(["take", ids["Held task"]], fake, "lead0001")
            if fake.writes()[0] != ["update", ids["Held task"], "--assignee", "lead0001", "--force", "--json"] \
                    or fake.writes()[1][:3] != ["comments", "add", ids["Held task"]]:
                raise ValueError(f"board take: {fake.writes()}")

            fake = Fake(variant(**{"Released ruling": {"assignee": "cccc3333"}}))
            invoke(["unclaim", ids["Held task"], ids["Released ruling"]], fake, "lead0001")
            writes = fake.writes()
            if writes[0][:2] != ["unclaim", ids["Held task"]] or "--force" not in writes[0] or "--reason" not in writes[0] \
                    or writes[1] != ["update", ids["Released ruling"], "--assignee", "", "--json"] \
                    or writes[2][:3] != ["comments", "add", ids["Released ruling"]]:
                raise ValueError(f"board unclaim: {writes}")

            # handover (change request): the holding session only; refuses open items, uncommitted changes and failing checks; then a
            # compare-and-set to in_review at its stage, the stage metadata and the evidence comment.
            cwd = Path(os.getcwd())
            wt = cwd / ".worktrees" / "fx-ovo.c2"
            if not wt.exists():
                subprocess.run(["git", "worktree", "add", "-q", "-b", "cr/fx-ovo.c2", str(wt), "main"], check=True, capture_output=True)
            main_tip = subprocess.run(["git", "rev-parse", "main"], capture_output=True, text=True, check=True).stdout.strip()
            if not (wt / "pass.txt").exists():
                (wt / "pass.txt").write_text("pass\n", encoding="utf-8")
                subprocess.run(["git", "-C", str(wt), "add", "pass.txt"], check=True, capture_output=True)
                subprocess.run(["git", "-C", str(wt), "commit", "-q", "-m", "a pass"], check=True, capture_output=True)
            cr_tip = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
            ready_cr = {"CR held": {"metadata": {"base": "main", "base_sha": main_tip, "setup_sha": main_tip}}}
            done_item = {"Held task": {"status": "closed", "assignee": None}}
            fake = Fake(variant(**ready_cr))
            code, _, errors = invoke(["handover", "fx-ovo.c2", "done"], fake, "aaaa1111")
            if code != 1 or fake.writes() or "items still open" not in errors or ids["Held task"] not in errors:
                raise ValueError(f"board handover took a change request with open items: {code} {fake.writes()} {errors}")
            code, _, errors = invoke(["handover", ids["Held task"], "done"], Fake(variant(**ready_cr)), "aaaa1111")
            if code != 1 or "its change request is fx-ovo.c2" not in errors:
                raise ValueError(f"board handover of an item must name its change request: {errors}")
            fake = Fake(variant(**ready_cr, **done_item))
            if invoke(["handover", "fx-ovo.c2", "done"], fake, "bbbb2222")[0] != 1 or fake.writes():
                raise ValueError("board handover accepted a change request the caller does not hold")
            (wt / "dirty.txt").write_text("x\n", encoding="utf-8")
            fake = Fake(variant(**ready_cr, **done_item))
            code, _, errors = invoke(["handover", "fx-ovo.c2", "done"], fake, "aaaa1111")
            if code != 1 or fake.writes() or "uncommitted changes" not in errors or "dirty.txt" not in errors:
                raise ValueError(f"board handover took a dirty worktree: {code} {fake.writes()} {errors}")
            (wt / "dirty.txt").unlink()
            fake = Fake(variant(**ready_cr, **done_item))
            fake.settings["custom.board.checks"] = "echo broken; false"
            code, _, errors = invoke(["handover", "fx-ovo.c2", "done"], fake, "aaaa1111")
            if code != 1 or "checks failed" not in errors or "broken" not in errors \
                    or "check_result=fail" not in fake.writes()[-1] or any(args[:1] == ["comments"] for args in fake.writes()):
                raise ValueError(f"board handover with failing checks must store the failed check and refuse: {code} {fake.writes()} {errors}")
            fake = Fake(variant(**ready_cr, **done_item))
            code, output, errors = invoke(["handover", "fx-ovo.c2", "pnpm test: 0 failures"], fake, "aaaa1111")
            if code or ["update", "fx-ovo.c2", "--status", "in_review", "--assignee", "", "--if-assignee", "aaaa1111", "--json"] not in fake.writes() \
                    or ["comments", "add", "fx-ovo.c2", "board handover: pnpm test: 0 failures"] not in fake.writes() \
                    or not any("check_result=pass" in args and f"check_base_tip={main_tip}" in args and f"check_tip={cr_tip}" in args for args in fake.writes()):
                raise ValueError(f"board handover: {code} {fake.writes()} {errors}")
            # A checkpoint set to the agent sends the hand-over to the checkpoint stage, a user checkpoint through review.
            for checkpoint, status in (("agent", "in_review"), ("user", "needs_acceptance")):
                fake = Fake(variant(**{"CR held": {"metadata": {**ready_cr["CR held"]["metadata"], "checkpoint": checkpoint}}, **done_item}))
                invoke(["handover", "fx-ovo.c2", "ok"], fake, "aaaa1111")
                if not any(args[:4] == ["update", "fx-ovo.c2", "--status", status] for args in fake.writes()):
                    raise ValueError(f"board handover with checkpoint {checkpoint} must go to {status}: {fake.writes()}")
            # The reviewer's pass: look before goes to accept (the user's Accept), the holder released; a returned item goes back to open.
            reviewing = {"CR held": {"status": "in_review", "assignee": "bbbb2222", "metadata": {**ready_cr["CR held"]["metadata"], "reviewing_tip": cr_tip}}}
            fake = Fake(variant(**reviewing, **done_item))
            code, output, errors = invoke(["handover", "fx-ovo.c2", "reviewed: fine"], fake, "bbbb2222")
            if code or ["update", "fx-ovo.c2", "--status", "needs_acceptance", "--assignee", "", "--if-assignee", "bbbb2222", "--json"] not in fake.writes() \
                    or not any(args[:4] == ["update", "fx-ovo.c2", "--status", "needs_acceptance"] for args in fake.writes()) or "waiting for your Accept" not in output:
                raise ValueError(f"board handover by a reviewer must pass the change request to accept: {code} {fake.writes()} {errors}")
            if not any(any(a.startswith("review_tip=") for a in args) and any(a.startswith("review_base_tip=") for a in args) for args in fake.writes()):
                raise ValueError(f"a reviewer's pass must record the (tip, base tip) it reviewed: {fake.writes()}")

            # return: back to the queue, open and unassigned, with the findings; the worktree and branch stay.
            fake = Fake(variant(**{"CR ready": {"status": "in_review", "assignee": "lead0001", "metadata": {}}}))
            invoke(["return", "fx-ovo.c1", "test x fails"], fake, "lead0001")
            if fake.plain_writes() != [["update", "fx-ovo.c1", "--status", "open", "--assignee", "", "--json"],
                                       ["comments", "add", "fx-ovo.c1", "board return: test x fails"]]:
                raise ValueError(f"board return: {fake.writes()}")
            fake = Fake(variant(**{"CR ready": {"status": "in_review", "assignee": "aaaa1111", "metadata": {}}}))
            if invoke(["return", "fx-ovo.c1", "x"], fake, "lead0001")[0] != 1 or fake.writes():
                raise ValueError("board return accepted a review the caller does not hold")
            # The Accept's own return (stage accept): the lead needs no hold; an agent session cannot.
            accepted = variant(**{"CR ready": {"status": "needs_acceptance"}})
            if invoke(["return", "fx-ovo.c1", "changes"], Fake(accepted), "lead0001")[0] != 0 or invoke(["return", "fx-ovo.c1", "changes"], Fake(accepted), "aaaa1111")[0] != 1:
                raise ValueError("a lead returns a change request waiting for its Accept; an agent session does not")

            # Change requests (r24, r25): readiness, check state, landing, refresh, rejection, console rows; real git in a second
            # scratch repository, bd writes recorded.
            def cr_issue(item_id, status="open", assignee=None, priority=2, blocks=(), **metadata):
                row = {"id": item_id, "title": f"CR {item_id}", "issue_type": "change-request", "status": status, "priority": priority,
                       "description": "d", "created_at": "2026-10-22T15:29:00Z", "updated_at": "2026-10-22T15:29:00Z", "metadata": dict(metadata),
                       "dependencies": [{"issue_id": item_id, "depends_on_id": b, "type": "blocks"} for b in blocks]}
                return {**row, **({"assignee": assignee} if assignee else {})}

            def cr_item(item_id, cr, status="open", kind="task", blocks=()):
                return {"id": item_id, "title": f"item {item_id}", "issue_type": kind, "status": status, "priority": 2, "description": "d",
                        "created_at": "2026-10-22T15:29:00Z", "updated_at": "2026-10-22T15:29:00Z",
                        "dependencies": [{"issue_id": item_id, "depends_on_id": cr, "type": "parent-child"},
                                         *({"issue_id": item_id, "depends_on_id": b, "type": "blocks"} for b in blocks)]}

            def readiness(*issues, complete=False):
                deck = bare_deck(list(issues), complete)
                return {i["id"]: (deck.claimable(i), deck.cr_waits(i)) for i in issues if i["issue_type"] == "change-request" and i["status"] != "closed"}

            # A2/A10: a CR waits while its blocker CR is open, in work or returned; in review (not at a checkpoint) or past its design
            # checkpoint it is the base; two bases are one too many; closed is landed.
            item_of = lambda cr, *, blocks=(): [cr_item(f"{cr['id']}.i", cr["id"], blocks=blocks)]
            for blocker, expect in ((cr_issue("b", "needs_acceptance"), ("implement", [], ["b"])),
                                    (cr_issue("b", "in_review"), (None, ["b"], [])),
                                    (cr_issue("b", "in_progress", assignee="x"), (None, ["b"], [])),
                                    (cr_issue("b", "open"), (None, ["b"], [])),
                                    (cr_issue("b", "in_review", checkpoint="agent"), (None, ["b"], [])),
                                    (cr_issue("b", "needs_acceptance", checkpoint="user"), (None, ["b"], [])),
                                    (cr_issue("b", "open", designed="1"), (None, ["b"], []))):
                waiting = cr_issue("w", blocks=("b",))
                kind, (waits, bases) = readiness(blocker, waiting, *item_of(waiting))["w"]
                if (kind, waits, bases) != expect:
                    raise ValueError(f"change request waiting on {blocker['status']} {blocker['metadata']}: {(kind, waits, bases)}, expected {expect}")
            two = readiness(cr_issue("b", "needs_acceptance"), cr_issue("c", "needs_acceptance"),
                            cr_issue("w", blocks=("b", "c")), *item_of(cr_issue("w")))["w"]
            if two[0] is not None or sorted(two[1][0]) != ["b", "c"]:
                raise ValueError(f"a CR waiting on two unlanded bases must wait for both: {two}")
            gone = readiness(cr_issue("b", "closed"), cr_issue("w", blocks=("b",)), *item_of(cr_issue("w")), complete=True)["w"]
            if gone[0] != "implement" or gone[1] != ([], []):
                raise ValueError(f"a landed (closed) blocker holds nothing: {gone}")
            # Item edges lift to their CRs; edges inside a CR order its own work only; a plain open blocker waits.
            lifted = readiness(cr_issue("b", "needs_acceptance"), cr_item("b.i", "b"),
                               cr_issue("w"), cr_item("w.i", "w", blocks=("b.i",)), cr_item("w.j", "w", blocks=("w.i",)))["w"]
            if lifted != ("implement", ([], ["b"])):
                raise ValueError(f"an item blocked by an item of another CR must stack its CR on that CR: {lifted}")
            inside = readiness(cr_issue("w"), cr_item("w.i", "w"), cr_item("w.j", "w", blocks=("w.i",)))["w"]
            if inside != ("implement", ([], [])):
                raise ValueError(f"edges between the items of one CR must not hold the CR: {inside}")
            plain = readiness(cr_issue("w"), cr_item("w.i", "w", blocks=("q",)), {**entry("q", "decision", "open", 2)})["w"]
            if plain[0] is not None or plain[1][0] != ["q"]:
                raise ValueError(f"an open decision before an item must hold its CR: {plain}")
            # Blockers outside the status snapshot (closed items) are read in one list of the closed items for all change requests, not
            # one show each; an id that list lacks (deleted) is asked of bd show and, absent there too, counts as closed.
            shows, lists = [], []

            def show_outside(ids, *flags, comments=True):
                shows.append(list(ids))
                return [{"id": i, "labels": [], "dependencies": [], "issue_type": "task"} for i in ids if i != "gone"]

            def closed_list():
                lists.append(1)
                return [{"id": f"ext{n}", "labels": [], "dependencies": [], "issue_type": "task", "status": "closed"} for n in range(10)]

            batch = [cr_issue(f"w{n}", blocks=(f"ext{n}",)) for n in range(3)] + [cr_issue("wg", blocks=("gone",))]
            with patch.object(board, "bd_show", show_outside), patch.object(board, "bd_closed", closed_list):
                waits = readiness(*batch, *(item for cr in batch for item in item_of(cr)))
            if shows != [["gone"]] or len(lists) != 1 or list(waits.values()) != [("implement", ([], []))] * 4:
                raise ValueError(f"the outside blockers of every change request must be read in one list: {shows} {lists} {waits}")
            # A closed item of a live request lifts to it, from the list's parent edges alone.
            lifting = [cr_issue("lb", "needs_acceptance"), cr_issue("lw", blocks=("done",))]
            lifting += item_of(lifting[1])
            closed_child = {"id": "done", "labels": [], "issue_type": "task", "status": "closed",
                            "dependencies": [{"issue_id": "done", "depends_on_id": "lb", "type": "parent-child"}]}
            with patch.object(board, "bd_show", show_outside), patch.object(board, "bd_closed", lambda: [closed_child]):
                if readiness(*lifting)["lw"] != ("implement", ([], ["lb"])):
                    raise ValueError("a closed blocker that is an item of a live request must stack its CR on that request")
            # A failed read of the outside blockers is not remembered: the next ask reads them again, not treats them as closed.
            def failing_once():
                lists.append(1)
                if len(lists) == 1:
                    raise board.BoardError("bd down")
                return closed_list()

            lists.clear()
            retry_deck = bare_deck([cr_issue("rw", blocks=("ext9",)), *item_of(cr_issue("rw"))], complete=False)
            with patch.object(board, "bd_show", show_outside), patch.object(board, "bd_closed", failing_once):
                try:
                    retry_deck.fetch_cr_blockers()
                except board.BoardError:
                    pass
                if retry_deck._cr_blockers_read:
                    raise ValueError("a failed read of the outside blockers must not be remembered as done")
                retry_deck.fetch_cr_blockers()
            if not retry_deck._cr_blockers_read or len(lists) != 3:
                raise ValueError(f"the next ask must read the outside blockers again: {lists}")
            # A review waits while its base was returned (q206).
            for base_status, expect in (("open", None), ("in_review", None), ("needs_acceptance", "review")):
                child = cr_issue("w", "in_review", blocks=("b",), base="b")
                got = readiness(cr_issue("b", base_status), child)["w"][0]
                if got != expect:
                    raise ValueError(f"the review of a CR whose base is {base_status}: {got}, expected {expect}")

            scratch_cr = tempfile.TemporaryDirectory()
            git = lambda *args, cwd=None: subprocess.run(["git", *args], cwd=cwd or os.getcwd(), capture_output=True, text=True, check=True).stdout.strip()
            crs_cwd = os.getcwd()
            os.chdir(scratch_cr.name)
            try:
                git("init", "-q", "-b", "main")
                Path("a.txt").write_text("1\n2\n3\n", encoding="utf-8")
                Path("b.txt").write_text("b\n", encoding="utf-8")
                git("add", "-A")
                git("commit", "-q", "-m", "init")
                repo_root = os.getcwd()

                def commit(cwd, name, text, message):
                    Path(cwd, name).write_text(text, encoding="utf-8")
                    git("add", name, cwd=cwd)
                    git("commit", "-q", "-m", message, cwd=cwd)
                    return git("rev-parse", "HEAD", cwd=cwd)

                def make_cr(name, filename="c.txt", text="c\n", base="main"):
                    """A CR branch with a worktree and one commit past its base, and the issues of a CR waiting for its Accept."""
                    base_tip = git("rev-parse", f"refs/heads/{base}" if base == "main" else f"refs/heads/cr/{base}")
                    wt = Path(repo_root, ".worktrees", name)
                    git("worktree", "add", "-q", "-b", f"cr/{name}", str(wt), base_tip)
                    tip = commit(wt, filename, text, f"{name}: pass")
                    metadata = {"look": "before", "base": base, "base_sha": base_tip, "setup_sha": base_tip,
                                "check_tip": tip, "check_base_tip": base_tip, "check_result": "pass", "check_at": "2026-10-22T15:00:00Z",
                                "review_tip": tip, "review_base_tip": base_tip}
                    return [cr_issue(name, "needs_acceptance", **metadata), cr_item(f"{name}.i", name, "closed")], tip, wt

                def at_main():
                    return git("rev-parse", "main")

                # Landing: fast-forwards the target where it is checked out (merge --ff-only), else by update-ref; closes the CR, removes
                # the worktree and the branch.
                issues, tip, wt = make_cr("land1")
                old = at_main()
                fake = Fake(issues)
                code, output, errors = invoke(["cr", "land", "land1", "--tip", tip[:8]], fake, "lead0001")
                if code or at_main() != tip or Path(repo_root, "c.txt").read_text() != "c\n" or wt.exists() or git("branch", "--list", "cr/land1") \
                        or not any(w[:2] == ["close", "land1"] for w in fake.writes()) or "landed land1 on main" not in output:
                    raise ValueError(f"board cr land must fast-forward main, close the CR and remove its worktree and branch: {code} {errors} {fake.writes()}")
                git("checkout", "-q", "-b", "elsewhere")
                issues, tip, wt = make_cr("land2", "d.txt", "d\n")
                before = git("rev-parse", "HEAD")
                code, output, errors = invoke(["cr", "land", "land2"], Fake(issues), "lead0001")
                if code or at_main() != tip or git("rev-parse", "HEAD") != before or git("symbolic-ref", "HEAD") != "refs/heads/elsewhere" \
                        or Path(repo_root, "d.txt").exists():
                    raise ValueError(f"board cr land must advance the target ref by update-ref where another branch is checked out: {code} {errors}")
                git("checkout", "-q", "main")
                # Refusals change nothing: a CR on a CR, an open item, a moved branch, a stale or failed check, an Accept not yet reached,
                # a caller who may not land, edits in the target's worktree that the landing would overwrite.
                issues, tip, wt = make_cr("refused", "e.txt", "e\n")
                main_now = at_main()
                stack = [cr_issue("lower", "needs_acceptance"), cr_issue("upper", "needs_acceptance", **{**issues[0]["metadata"], "base": "lower"})]
                other_main = commit(repo_root, "other.txt", "o\n", "main moves")
                cases = (("a CR stacked on a CR", [stack[0], stack[1], issues[1]], "upper", "lead0001", ["--tip", tip], "has not landed"),
                         ("an open item", [issues[0], cr_item("refused.i", "refused", "open")], "refused", "lead0001", [], "items still open"),
                         ("a moved branch", issues, "refused", "lead0001", ["--tip", main_now[:8]], "branch moved"),
                         ("a stale check (main moved)", issues, "refused", "lead0001", [], "check is stale"),
                         ("a caller who may not land", issues, "refused", "aaaa1111", [], "only a lead or solo"),
                         ("an unreached Accept", [{**issues[0], "status": "in_review"}, issues[1]], "refused", "lead0001", [], "waiting for its Accept"))
                for what, rows, target, actor, extra, needle in cases:
                    fake = Fake(rows)
                    code, _, errors = invoke(["cr", "land", target, *extra], fake, actor)
                    if code != 1 or needle not in errors or at_main() != other_main or any(w[0] == "close" for w in fake.writes()):
                        raise ValueError(f"board cr land accepted {what}: {code} {errors}")
                # A landing with a current check but edits in the target's worktree on a file the CR changes is blocked, not forced.
                git("worktree", "remove", "--force", str(wt))
                git("branch", "-D", "cr/refused")
                issues, tip, wt = make_cr("blocked", "a.txt", "1\n2\nchanged\n")
                Path(repo_root, "a.txt").write_text("1\nlocal edit\n3\n", encoding="utf-8")
                fake = Fake(issues)
                code, _, errors = invoke(["cr", "land", "blocked"], fake, "lead0001")
                _, queued, _ = invoke(["queue"], Fake(issues), "lead0001")
                if code != 1 or "land blocked" not in errors or "a.txt" not in errors or at_main() != other_main \
                        or "land blocked: a.txt" not in queued:
                    raise ValueError(f"board cr land over uncommitted edits must refuse and the queue must say so: {code} {errors}\n{queued}")
                git("checkout", "-q", "--", "a.txt")

                # Check state: current, stale (base or branch moved), conflict (dry-run merge fails), failed, unchecked.
                issues, tip, wt = make_cr("states", "s.txt", "s\n")
                states = lambda rows: json.loads(invoke(["console"], Fake(rows), "lead0001")[1])["crs"]
                base_now = at_main()
                issues[0]["metadata"].update(check_base_tip=base_now, base_sha=base_now)
                for what, change, expected in (
                        ("current", {}, "current"), ("unchecked", {"check_tip": ""}, "unchecked"), ("failed", {"check_result": "fail"}, "failed"),
                        ("branch moved", {"check_tip": base_now}, "stale"), ("base moved", {"check_base_tip": "f" * 40}, "stale")):
                    rows = [{**issues[0], "metadata": {**issues[0]["metadata"], **change}}, issues[1]]
                    found = next(c for c in states(rows) if c["id"] == "states")["check"]["state"]
                    if found != expected:
                        raise ValueError(f"check state {what}: {found}, expected {expected}")
                # conflict: the base moved onto the same lines the branch changed
                commit(repo_root, "s.txt", "main side\n", "conflicting main commit")
                moved = [{**issues[0], "metadata": {**issues[0]["metadata"]}}, issues[1]]
                if next(c for c in states(moved) if c["id"] == "states")["check"]["state"] != "conflict":
                    raise ValueError("a base that moved onto the branch's changes must show conflict")

                # The console's git reads do not grow with the number of change requests: the main checkout, the target branch and
                # the branch tips are each read once for all of them.
                class GitCounting(Fake):
                    def __call__(self, command, **kwargs):
                        if command[0] == "git":
                            key = " ".join(command[3:5] if command[1] == "-C" else command[1:3])
                            self.git_calls[key] = self.git_calls.get(key, 0) + 1
                        return super().__call__(command, **kwargs)

                def git_reads(rows):
                    counting = GitCounting(rows)
                    counting.git_calls = {}
                    invoke(["console"], counting, "lead0001")
                    return {k: v for k, v in counting.git_calls.items() if k.split()[0] in ("worktree", "rev-parse", "check-ref-format", "for-each-ref")}

                extra_crs = [make_cr(f"gx{n}", f"gx{n}.txt", "g\n") for n in (1, 2, 3)]
                few, many = git_reads(issues), git_reads([*issues, *(row for made in extra_crs for row in made[0])])
                if few != many or sum(many.values()) > 6:
                    raise ValueError(f"board console git reads must not grow with the change requests: {few} vs {many}")
                for _, _, extra_wt in extra_crs:
                    git("worktree", "remove", "--force", str(extra_wt))
                for n in (1, 2, 3):
                    git("branch", "-D", f"cr/gx{n}")

                # A git failure while reading the console's view degrades to the live reads (unchecked per CR), not a failed command.
                with patch.object(board, "worktrees_listing", side_effect=board.BoardError("git failed")):
                    probe = board.Board([])
                    board.read_git_view(probe)
                    if probe.git_view is not None:
                        raise ValueError("read_git_view must leave no view when a git read fails")

                # A landing that settle_landed finishes removes its worktree: a later change request must not read the stale listing
                # (target checked out in a worktree listed after the landed one, with edits the next CR would overwrite).
                landed, landed_tip, landed_wt = make_cr("sl1", "sl1.txt", "1\n")
                git("checkout", "-q", "-b", "elsewhere2")
                target_wt = Path(repo_root, ".worktrees", "zz-target")
                git("worktree", "add", "-q", str(target_wt), "main")
                git("merge", "-q", "--ff-only", "cr/sl1", cwd=target_wt)
                waiting, waiting_tip, waiting_wt = make_cr("sl2", "sl2.txt", "2\n")
                Path(target_wt, "sl2.txt").write_text("local edit\n", encoding="utf-8")
                rows = json.loads(invoke(["console"], Fake([*landed, *waiting]), "lead0001")[1])["crs"]
                if [c["id"] for c in rows] != ["sl2"] or rows[0]["landBlocked"] != ["sl2.txt"] or landed_wt.exists():
                    raise ValueError(f"board console after a settled landing must read the live worktrees: {rows} {landed_wt.exists()}")
                git("worktree", "remove", "--force", str(waiting_wt))
                git("worktree", "remove", "--force", str(target_wt))
                git("branch", "-D", "cr/sl2")
                git("checkout", "-q", "main")
                git("branch", "-D", "elsewhere2")

                # Refresh: rebase `--onto <base tip> <fork point>` after the base was rewritten; its range-diff and incoming files print.
                base_issues, base_tip_old, base_wt = make_cr("pbase", "p.txt", "p\n")
                child_issues, child_tip_old, child_wt = make_cr("pchild", "q.txt", "q\n", base="pbase")
                Path(base_wt, "p.txt").write_text("p reworked\n", encoding="utf-8")  # the rewrite changes the patch, so a plain rebase would replay the old one
                git("add", "p.txt", cwd=base_wt)
                git("commit", "-q", "--amend", "-m", "pbase: reworked", cwd=base_wt)
                new_base = git("rev-parse", "HEAD", cwd=base_wt)
                child_issues[0]["status"] = "in_review"
                fake = Fake([base_issues[0], *base_issues[1:], *child_issues])
                code, output, errors = invoke(["cr", "refresh", "pchild"], fake, "lead0001")
                rebased = git("log", "--format=%s", "-3", cwd=child_wt).split("\n")
                if code or rebased != ["pchild: pass", "pbase: reworked", "main moves"] and rebased[:2] != ["pchild: pass", "pbase: reworked"] \
                        or git("merge-base", "--is-ancestor", new_base, "HEAD", cwd=child_wt) is None \
                        or f"base_sha={new_base}" not in " ".join(" ".join(w) for w in fake.writes()) \
                        or "range-diff old..new" not in output or "incoming files" not in output:
                    raise ValueError(f"board cr refresh must follow a rewritten base with --onto the recorded fork point: {code} {errors} {rebased}\n{output}")
                # A conflict stops the rebase in the worktree and says how to go on; a refresh refuses while another session holds the CR.
                commit(base_wt, "q.txt", "clash\n", "pbase: clash with the child")
                child_issues[0]["metadata"]["base_sha"] = new_base
                code, _, errors = invoke(["cr", "refresh", "pchild"], Fake([base_issues[0], *base_issues[1:], *child_issues]), "lead0001")
                if code != 1 or "stopped on a conflict" not in errors or not Path(git("rev-parse", "--path-format=absolute", "--git-path", "rebase-merge", cwd=child_wt)).exists():
                    raise ValueError(f"board cr refresh must stop on a conflict, leaving the rebase to resolve: {code} {errors}")
                git("rebase", "--abort", cwd=child_wt)
                held_elsewhere = [{**child_issues[0], "assignee": "bbbb2222"}, child_issues[1], base_issues[0], *base_issues[1:]]
                code, _, errors = invoke(["cr", "refresh", "pchild"], Fake(held_elsewhere), "lead0001")
                if code != 1 or "held by bbbb2222" not in errors:
                    raise ValueError(f"board cr refresh took a CR another session holds: {errors}")

                # Reject: the CR closes unlanded, its closed items reopen, a CR stacked on it returns to planning on the target.
                rejected = [cr_issue("rej", "needs_acceptance", look="before"), cr_item("rej.i", "rej", "closed"),
                            cr_issue("kid", "in_progress", assignee="aaaa1111", base="rej", base_sha="0" * 40)]
                fake = Fake(rejected)
                code, output, errors = invoke(["cr", "reject", "rej", "the approach cannot work"], fake, "lead0001")
                written = fake.writes()
                if code or ["update", "rej.i", "--status", "open", "--assignee", "", "--json"] not in written \
                        or not any(w[:2] == ["close", "rej"] and "--force" in w for w in written) \
                        or not any(w[:2] == ["update", "kid"] and "base=main" in w and any(a.startswith("replan=") for a in w) for w in written) \
                        or ["update", "kid", "--status", "open", "--assignee", "", "--json"] not in written or "back to planning: kid" not in output:
                    raise ValueError(f"board cr reject: {code} {errors}\n{written}\n{output}")
                if invoke(["cr", "reject", "rej", "x"], Fake(rejected), "aaaa1111")[0] != 1:
                    raise ValueError("an agent session rejected a change request")

                # A landed base lands the look-after CR waiting on it when its check is current (A1), and opens its ratification.
                x_issues, x_tip, x_wt = make_cr("lx", "lx.txt", "x\n")
                y_issues, y_tip, y_wt = make_cr("ly", "ly.txt", "y\n", base="lx")
                y_issues[0].update(status="in_review")  # passed review, waiting for its parent (q219)
                y_issues[0]["metadata"].update(look="after", review_tip=y_tip, review_base_tip=x_tip)
                fake = Fake([*x_issues, *y_issues])
                code, output, errors = invoke(["cr", "land", "lx", "--tip", x_tip[:8]], fake, "lead0001")
                if code or at_main() != y_tip or not any(w[:2] == ["close", "ly"] for w in fake.writes()) or y_wt.exists() \
                        or not any(w[0] == "create" and "Ratify: CR ly" in w for w in fake.writes()) or "(after lx)" not in output:
                    raise ValueError(f"landing a base must land the look-after CR waiting for it: {code} {errors}\n{output}\n{fake.writes()}")
                # ...and leaves it as refresh work when its check is no longer current.
                x_issues, x_tip, x_wt = make_cr("lx2", "lx2.txt", "x\n")
                y_issues, y_tip, y_wt = make_cr("ly2", "ly2.txt", "y\n", base="lx2")
                y_issues[0].update(status="in_review")
                y_issues[0]["metadata"].update(look="after", check_base_tip="f" * 40, review_tip=y_tip, review_base_tip=x_tip)
                fake = Fake([*x_issues, *y_issues])
                code, output, errors = invoke(["cr", "land", "lx2", "--tip", x_tip[:8]], fake, "lead0001")
                if code or at_main() != x_tip or any(w[:2] == ["close", "ly2"] for w in fake.writes()) or "left as refresh work" not in output:
                    raise ValueError(f"a look-after CR with a stale check must be left as refresh work: {code} {errors}\n{output}")

                # A look-after CR that passed review while its parent waits for the user stays in review, marked after, and is no pull
                # again; a stale review pair (a re-handed-over CR) makes it a pull again (F9).
                p_issues, p_tip, _ = make_cr("ab", "ab.txt", "x\n")
                c_issues, c_tip, _ = make_cr("ac", "ac.txt", "y\n", base="ab")
                c_issues[0].update(status="in_review")
                c_issues[0]["metadata"].update(look="after")
                deck = bare_deck([*p_issues, *c_issues], complete=False)
                if deck.kind(c_issues[0]) is not None or board.after_base(deck, c_issues[0]) != "ab":
                    raise ValueError("a passed look-after CR waiting for its parent must be marked after it and not be claimable for review")
                c_issues[0]["metadata"].update(review_tip="1" * 40)
                deck = bare_deck([*p_issues, *c_issues], complete=False)
                if deck.kind(c_issues[0]) != "review" or board.after_base(deck, c_issues[0]) is not None:
                    raise ValueError("a look-after CR whose review pair is stale (handed over again) must be reviewable")
                # ...or when its review was of another base tip (q236).
                x_issues, x_tip, x_wt = make_cr("lx3", "lx3.txt", "x\n")
                y_issues, y_tip, y_wt = make_cr("ly3", "ly3.txt", "y\n", base="lx3")
                y_issues[0].update(status="in_review")
                y_issues[0]["metadata"].update(look="after", review_tip=y_tip, review_base_tip="e" * 40)
                fake = Fake([*x_issues, *y_issues])
                code, output, errors = invoke(["cr", "land", "lx3", "--tip", x_tip[:8]], fake, "lead0001")
                if code or at_main() != x_tip or any(w[:2] == ["close", "ly3"] for w in fake.writes()) or "(after lx3)" in output:
                    raise ValueError(f"a look-after CR whose review no longer matches must stay behind (a review pull again): {code} {errors}\n{output}")

                # Design checkpoints: the agent's pass opens the CR for planning as a stack base (and a ratification in look-after projects);
                # the user's accept is `land --checkpoint`; nothing lands.
                for look, ratified in (("after", True), ("before", False)):
                    issues, tip, wt = make_cr(f"cp{look}", f"cp{look}.txt", "d\n")
                    issues[0].update(assignee="bbbb2222")
                    issues[0].update(status="in_review")
                    issues[0]["metadata"].update(checkpoint="agent", look=look, reviewing_tip=tip)
                    fake = Fake(issues)
                    code, output, errors = invoke(["handover", f"cp{look}", "design reads well"], fake, "bbbb2222")
                    written = fake.writes()
                    if code or ["update", f"cp{look}", "--status", "open", "--assignee", "", "--if-assignee", "bbbb2222", "--json"] not in written \
                            or not any(w[:2] == ["update", f"cp{look}"] and "checkpoint" in w for w in written) \
                            or any(w[0] == "create" and f"Ratify design: CR cp{look}" in w for w in written) != ratified or "passed the checkpoint" not in output:
                        raise ValueError(f"the agent's checkpoint pass in a look-{look} project: {code} {errors}\n{written}\n{output}")
                # r10-q50: a CR whose branch has no commits of its own lands when its review passes (nothing to merge), in either look,
                # without a ratification and without the Accept; a design checkpoint is the exception.
                def make_empty_cr(name, look, status="in_review", **extra):
                    base_tip = git("rev-parse", "main")
                    wt = Path(repo_root, ".worktrees", name)
                    git("worktree", "add", "-q", "-b", f"cr/{name}", str(wt), base_tip)
                    metadata = {"look": look, "base": "main", "base_sha": base_tip, "setup_sha": base_tip, "reviewing_tip": base_tip, **extra}
                    return [cr_issue(name, status, **({"assignee": "bbbb2222"} if status == "in_review" else {}), **metadata), cr_item(f"{name}.i", name, "closed")], base_tip, wt

                for look in ("before", "after"):
                    issues, tip, wt = make_empty_cr(f"emp{look}", look)
                    fake = Fake(issues)
                    code, output, errors = invoke(["handover", f"emp{look}", "reviewed: verified the baseline"], fake, "bbbb2222")
                    written = fake.writes()
                    if code or not any(w[:2] == ["close", f"emp{look}"] for w in written) or any(w[0] == "create" for w in written) \
                            or any(w[:4] == ["update", f"emp{look}", "--status", "needs_acceptance"] for w in written) \
                            or f"passed and landed emp{look}" not in output or at_main() != tip or wt.exists():
                        raise ValueError(f"a CR with no commits of its own lands on its passed review in a look-{look} project, with no ratification: {code} {errors}\n{written}\n{output}")
                issues, tip, wt = make_empty_cr("empcp", "before", checkpoint="agent")
                fake = Fake(issues)
                code, output, errors = invoke(["handover", "empcp", "design reads well"], fake, "bbbb2222")
                if code or any(w[:2] == ["close", "empcp"] for w in fake.writes()) or "passed the checkpoint" not in output:
                    raise ValueError(f"an empty design checkpoint still goes to planning: {code} {errors}\n{fake.writes()}\n{output}")
                issues, tip, wt = make_empty_cr("emplate", "after", status="needs_acceptance", check_tip=git("rev-parse", "main"), check_base_tip=git("rev-parse", "main"),
                                                check_result="pass", check_at="2026-10-22T15:00:00Z", review_tip=git("rev-parse", "main"), review_base_tip=git("rev-parse", "main"))
                fake = Fake(issues)
                code, output, errors = invoke(["cr", "land", "emplate"], fake, "lead0001")
                if code or not any(w[:2] == ["close", "emplate"] for w in fake.writes()) or any(w[0] == "create" for w in fake.writes()):
                    raise ValueError(f"landing an empty CR from the Accept queue opens no ratification: {code} {errors}\n{fake.writes()}")
                # A stacked CR with nothing to merge, passed in a look-before project, lands with its base (review F5).
                p_issues, p_tip, _ = make_cr("ep", "ep.txt", "x\n")
                c_wt = Path(repo_root, ".worktrees", "ec")
                git("worktree", "add", "-q", "-b", "cr/ec", str(c_wt), "cr/ep")
                c_issues = [cr_issue("ec", "in_review", look="before", base="ep", base_sha=p_tip, setup_sha=p_tip, review_tip=p_tip, review_base_tip=p_tip,
                                       check_tip=p_tip, check_base_tip=p_tip, check_result="pass", check_at="2026-10-22T15:00:00Z"), cr_item("ec.i", "ec", "closed")]
                fake = Fake([*p_issues, *c_issues])
                code, output, errors = invoke(["cr", "land", "ep", "--tip", p_tip[:8]], fake, "lead0001")
                if code or not any(w[:2] == ["close", "ec"] for w in fake.writes()):
                    raise ValueError(f"an empty stacked look-before CR must land with its base: {code} {errors}\n{output}\n{fake.writes()}")
                def design_hash(rows):
                    """The pin of the design items in rows, worked out from the spec: sha256[:12] of their id, description, design, acceptance and notes."""
                    designs = sorted((r for r in rows if r.get("issue_type") == "design"), key=lambda r: r["id"])
                    text = json.dumps([[r["id"], *(r.get(f) or "" for f in ("description", "design", "acceptance_criteria", "notes"))] for r in designs])
                    return hashlib.sha256(text.encode()).hexdigest()[:12]

                issues, tip, wt = make_cr("cpuser", "cpuser.txt", "d\n")
                issues[0]["metadata"].update(checkpoint="user")
                before = at_main()
                code, _, errors = invoke(["cr", "land", "cpuser"], Fake(issues), "lead0001")
                if code != 1 or "--checkpoint" not in errors or at_main() != before:
                    raise ValueError(f"board cr land without --checkpoint must refuse a pending design checkpoint: {errors}")
                fake = Fake(issues)
                code, _, errors = invoke(["cr", "land", "cpuser", "--checkpoint"], fake, "lead0001")
                if code != 1 or "--design" not in errors or "board claim cpuser" not in errors or fake.writes():
                    raise ValueError(f"board cr land --checkpoint without --design must refuse and name board claim: {code} {errors} {fake.writes()}")
                fake = Fake(issues)
                code, output, errors = invoke(["cr", "land", "cpuser", "--checkpoint", "--design", design_hash(issues)], fake, "lead0001")
                if code or at_main() != before or not any(w[:2] == ["update", "cpuser"] and "checkpoint" in w for w in fake.writes()) \
                        or ["update", "cpuser", "--status", "open", "--assignee", "", "--json"] not in fake.writes() or not wt.exists():
                    raise ValueError(f"board cr land --checkpoint must open the CR for planning and land nothing: {code} {errors} {fake.writes()}")
                # The design pin: the claim prints a hash of the design item's text; `--design <hash>` accepts only that text.
                design = {**cr_item("cpuser.d", "cpuser", "closed", kind="design"), "design": "the design", "acceptance_criteria": "ac", "notes": "n"}
                pinned = [*issues, design]
                code, output, errors = invoke(["claim", "cpuser"], Fake(pinned), "lead0001")
                found = re.search(r"design hash (\w+) \(cpuser\.d\)", output)
                if code or found is None:
                    raise ValueError(f"board claim of a user design checkpoint must print the design hash: {code} {errors}\n{output}")
                pin = found.group(1)
                if pin != design_hash(pinned):
                    raise ValueError(f"the claim's design hash differs from the spec's: {pin} vs {design_hash(pinned)}")
                for edit in ({"design": "the design, changed"}, {"notes": "n2"}, {"description": "d2"}, {"acceptance_criteria": "ac2"}):
                    fake = Fake([*issues, {**design, **edit}])
                    code, _, errors = invoke(["cr", "land", "cpuser", "--checkpoint", "--design", pin], fake, "lead0001")
                    if code != 1 or "design changed" not in errors or fake.writes():
                        raise ValueError(f"board cr land --checkpoint --design must refuse a changed design ({edit}): {code} {errors} {fake.writes()}")
                fake = Fake(pinned)
                code, output, errors = invoke(["cr", "land", "cpuser", "--checkpoint", "--design", pin], fake, "lead0001")
                if code or ["update", "cpuser", "--status", "open", "--assignee", "", "--json"] not in fake.writes():
                    raise ValueError(f"board cr land --checkpoint --design with the claimed hash must accept: {code} {errors} {fake.writes()}")
                code, _, errors = invoke(["cr", "land", "cpuser", "--design", pin], Fake(pinned), "lead0001")
                if code != 1 or "--checkpoint" not in errors:
                    raise ValueError(f"--design without --checkpoint must refuse: {code} {errors}")
                # A CR made around an existing design item (waiting in review under the old model) is accepted like a native one.
                legacy = cr_issue("legacycp", "needs_acceptance", checkpoint="user", since="2026-10-22T15:00:00Z")
                legacy_design = cr_item("legacycp.d", "legacycp", "in_review", kind="design")
                fake = Fake([legacy, legacy_design])
                code, output, errors = invoke(["cr", "land", "legacycp", "--checkpoint", "--design", design_hash([legacy, legacy_design])], fake, "lead0001")
                if code or ["update", "legacycp", "--status", "open", "--assignee", "", "--json"] not in fake.writes() or "accepted the design checkpoint" not in output:
                    raise ValueError(f"land --checkpoint of a CR around a legacy design item: {code} {errors} {fake.writes()}")
                if invoke(["cr", "land", "lx2", "--checkpoint", "--design", "0" * 12], Fake([*x_issues]), "lead0001")[0] != 1:
                    raise ValueError("board cr land --checkpoint without a pending user checkpoint must refuse")

                # r26: checks pass when no (file, code) failure count rises from the base to the tip (q241); the base is run once per base commit.
                commit(repo_root, "failures.txt", "a.ts E1\nb.ts E2\n", "baseline failures")
                checks_cmd = "cat failures.txt; test ! -s failures.txt"
                for name, text, passes, compared in (("nf-same", "a.ts E1\nb.ts E2\n# a note\n", True, True), ("nf-fewer", "a.ts E1\n", True, True),
                                                     ("nf-new", "a.ts E1\nb.ts E2\nc.ts E3\n", False, True), ("nf-more", "a.ts E1\na.ts E1\nb.ts E2\n", False, True),
                                                     ("nf-green", "", True, False)):
                    issues, tip, wt = make_cr(name, "failures.txt", text)
                    fake = Fake(issues)
                    fake.settings["custom.board.checks"] = checks_cmd
                    code, output, errors = invoke(["cr", "refresh", name], fake, "lead0001")
                    flat = " ".join(" ".join(w) for w in fake.writes())
                    if code or (f"check_result={'pass' if passes else 'fail'}" not in flat) \
                            or (not passes and ("new failures" not in output or ("c.ts E3" if name == "nf-new" else "a.ts E1") not in output)) \
                            or (compared and "check_new=" not in flat) or (not compared and "check_new" in flat and "unset" not in flat and "check_new=" in flat):
                        raise ValueError(f"check rule {name}: {code} {errors}\n{output}\n{fake.writes()}")
                # The base run is cached per project (in the common git dir) by base commit and settings, and run once for concurrent users.
                cache = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "board-base-checks"
                if len([f for f in cache.iterdir() if not f.name.endswith(".lock")]) != 1:
                    raise ValueError(f"the base result must be cached once for one base commit: {sorted(f.name for f in cache.iterdir())}")
                counter = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "basecount"
                counter.unlink(missing_ok=True)
                import threading
                commit(repo_root, "failures.txt", "a.ts E1\nb.ts E2\nnote\n", "main moves for the cache test")
                results = []

                base_tip_now = git("rev-parse", "main")
                fake_cache = Fake([])
                fake_cache.settings["custom.board.setup"] = 'sleep 0.3; echo run >> "$(git rev-parse --git-common-dir)/basecount"'
                fake_cache.settings["custom.board.checks"] = checks_cmd
                board_obj = bare_deck([], complete=False)
                board_obj.settings.update({"setup": fake_cache.settings["custom.board.setup"], "checks": checks_cmd})
                dummy = {"id": "cache-user", "metadata": {}}
                with patch.object(board, "current_setting", lambda key: board_obj.settings[key.rsplit(".", 1)[1]]):
                    errors_seen = []

                    def ask():
                        try:
                            results.append(board.base_failures(board_obj, dummy, Path(repo_root), base_tip_now))
                        except Exception as error:  # a racing hand-over that collides must fail the test, not vanish
                            errors_seen.append(error)

                    threads = [threading.Thread(target=ask) for _ in range(3)]
                    [t.start() for t in threads]
                    [t.join() for t in threads]
                    if errors_seen or len(results) != 3:
                        raise ValueError(f"concurrent hand-overs onto one base must all get the result: {errors_seen}")
                    first = results[0]
                    board_obj.settings["checks"] = checks_cmd + "; true"
                    board.base_failures(board_obj, dummy, Path(repo_root), base_tip_now)
                if counter.read_text().count("run") != 2 or first != {("a.ts", "E1"): 1, ("b.ts", "E2"): 1} or any(r != first for r in results):
                    raise ValueError(f"the base run must happen once per (base commit, settings) however many hand-overs ask: {counter.read_text()!r} {results}")
                issues, tip, wt = make_cr("nf-silent", "silent.txt", "x\n")
                fake = Fake(issues)
                fake.settings["custom.board.checks"] = "echo oops; false"
                code, output, errors = invoke(["cr", "refresh", "nf-silent"], fake, "lead0001")
                if "check_result=fail" not in " ".join(" ".join(w) for w in fake.writes()):
                    raise ValueError(f"a failing check that names no failure must fail: {fake.writes()}")
                # The console row carries the comparison (newFailures, baseCount, tipCount) once it ran.
                compared_row = {**make_cr("nf-row", "row.txt", "x\n")[0][0]}
                compared_row["metadata"] = {**compared_row["metadata"], "check_new": "c.ts E3", "check_base_count": "2", "check_tip_count": "3"}
                row = next(c for c in json.loads(invoke(["console"], Fake([compared_row]), "lead0001")[1])["crs"] if c["id"] == "nf-row")["check"]
                if (row["newFailures"], row["baseCount"], row["tipCount"]) != (["c.ts E3"], 2, 3):
                    raise ValueError(f"board console check comparison: {row}")

                # Settings through board setup are validated before anything changes (q223, q238).
                for flags, needle in ((["--target", "nope"], "not a local branch"), (["--look", "sometimes"], "not one of"), (["--view", "x"], "not one of"),
                                      (["--setup", "./missing.sh"], "does not exist"), (["--checks", " "], "empty")):
                    fake = Fake([])
                    code, _, errors = invoke(["setup", *flags], fake, "lead0001")
                    if code != 1 or needle not in errors or fake.writes():
                        raise ValueError(f"board setup {flags} must be refused before changing anything: {code} {errors} {fake.writes()}")

                # r10-q52: after a switch of the project's look or view, setup lists the open CRs that keep their own, with their reason line.
                own = [{**cr_issue("own-a", look="after"), "description": "Needs care.\nThe look is after because the work is internal."},
                       cr_issue("own-b", look="before", view="result"), cr_issue("plain-c"), cr_issue("done-d", "closed", look="after")]
                with patch.object(board.subprocess, "run", Fake(own)):
                    look_lines, view_lines = board.own_value_lines("look", "before"), board.own_value_lines("view", "code")
                if look_lines[1:] != ["    own-a  after: The look is after because the work is internal.", "    own-b  before (equals the new default): no reason in its text"] \
                        or "2 open change request(s) keep their own look" not in look_lines[0] or "--unset-metadata look" not in look_lines[0] \
                        or len(view_lines) != 2 or "own-b  result" not in view_lines[1]:
                    raise ValueError(f"board setup lists the open CRs keeping their own look or view: {look_lines} {view_lines}")
                with patch.object(board.subprocess, "run", Fake([cr_issue("plain-c")])):
                    if board.own_value_lines("look", "after"):
                        raise ValueError("board setup lists nothing when no CR keeps its own value")
                beads = Path(repo_root, ".beads")
                beads.mkdir(exist_ok=True)
                (beads / "metadata.json").write_text(json.dumps({"dolt_mode": "server"}), encoding="utf-8")
                out = io.StringIO()
                with patch.object(board.subprocess, "run", Fake(own)), patch.object(board, "beads_dir", lambda *a: beads), patch.object(board, "has_board", lambda: True), \
                        patch.dict(os.environ, {"BEADS_ACTOR": "lead0001"}), contextlib.redirect_stdout(out):
                    previous = Path.cwd()
                    try:
                        code = board.main(["setup", "--look", "after"])
                    finally:
                        os.chdir(previous)
                said = out.getvalue()
                if code or "custom.board.look: before -> after\n  2 open change request(s) keep their own look" not in said or "own-a  after (equals the new default): The look is after" not in said \
                        or "keep their own view" in said:
                    raise ValueError(f"board setup prints the CRs keeping their own look right under the switch of look (not of nothing else): {code}\n{said}")
                # The review verdict is tied to (tip, base tip): a pass records it; a refresh that finds it stale says so; the refreshing
                # session sends it back with a handover, which clears the verdict (q236).
                issues, tip, wt = make_cr("rv", "rv.txt", "x\n")
                issues[0]["metadata"].update(review_tip=tip, review_base_tip="e" * 40, since="2026-10-22T15:00:00Z")
                issues[0]["assignee"] = "bbbb2222"
                fake = Fake(issues)
                code, output, errors = invoke(["cr", "refresh", "rv"], fake, "bbbb2222")
                if code or "its review was of another (tip, base tip)" not in output:
                    raise ValueError(f"a refresh must say when the review no longer matches: {code} {errors}\n{output}")
                fake = Fake(issues)
                code, output, errors = invoke(["handover", "rv", "the new helper replaces its copy"], fake, "bbbb2222")
                flat = " ".join(" ".join(w) for w in fake.writes())
                if code or ["update", "rv", "--status", "in_review", "--assignee", "", "--if-assignee", "bbbb2222", "--json"] not in fake.writes() \
                        or "--unset-metadata review_tip" not in flat or "back to agent review" not in output:
                    raise ValueError(f"a handover of a CR waiting for its Accept must send it back to agent review: {code} {errors}\n{fake.writes()}")
                # The queue: a stack's base first, then priority, then age.
                aq = [cr_issue("q-late", "needs_acceptance", priority=1, since="2026-10-22T15:09:00Z"), cr_issue("q-old", "needs_acceptance", priority=2, since="2026-10-22T15:00:00Z"),
                      cr_issue("q-urgent", "needs_acceptance", priority=0, since="2026-10-22T15:20:00Z"),
                      cr_issue("q-child", "needs_acceptance", priority=0, since="2026-10-22T15:01:00Z", base="q-old")]
                if [i["id"] for i in board.accept_queue(bare_deck(aq, complete=False))] != ["q-old", "q-child", "q-urgent", "q-late"]:  # the child (P0, oldest of the P0s) pulls its base before it
                    raise ValueError(f"accept queue order: {[i['id'] for i in board.accept_queue(bare_deck(aq, complete=False))]}")
                # A failed setup is rerun by claiming the CR again (q222).
                held = [{**cr_issue("rerun", "in_progress", assignee="lead0001", base="main", base_sha=at_main()), }]
                subprocess.run(["git", "worktree", "add", "-q", "-b", "cr/rerun", str(Path(repo_root, ".worktrees", "rerun")), "main"], check=True, capture_output=True)
                fake = Fake(held)
                fake.settings["custom.board.setup"] = "echo not yet >&2; false"
                _, output, errors = invoke(["claim", "rerun"], fake, "lead0001")
                output += errors
                if "already held by lead0001" not in output or "setup failed" not in output or "not yet" not in output:
                    raise ValueError(f"claiming a held CR again must rerun its setup: {output}")

                # ---- deep review findings F1-F10 and risks ----
                # F1: land needs the review pair as it needs the check pair; the triage verdict "the review holds" is recorded by
                # `refresh --review-holds`, only for the reviewed changes with a passing check.
                issues, tip, wt = make_cr("f1stale", "f1.txt", "x\n")
                issues[0]["metadata"]["review_base_tip"] = "e" * 40
                fake = Fake(issues)
                code, _, errors = invoke(["cr", "land", "f1stale"], fake, "lead0001")
                if code != 1 or "its review is of another" not in errors or "--review-holds" not in errors or any(w[0] == "close" for w in fake.writes()):
                    raise ValueError(f"F1: land must refuse a CR whose review is of another (tip, base tip): {code} {errors}")
                commit(repo_root, "f1-main.txt", "m\n", "f1: main moves")
                issues, tip, wt = make_cr("f1hold", "f1h.txt", "x\n")
                old_base_tip = issues[0]["metadata"]["review_base_tip"]
                commit(repo_root, "f1-main2.txt", "m2\n", "f1: main moves again")
                invoke(["cr", "refresh", "f1hold"], Fake(issues), "lead0001")  # the triage input: what the refresh showed
                new_tip = git("rev-parse", "HEAD", cwd=wt)
                # Verdict after a base that moved again since that refresh: refused, untriaged.
                issues[0]["metadata"].update(triaged_tip=new_tip, triaged_base_tip=at_main(), base_sha=at_main())
                commit(repo_root, "f1-main3.txt", "m3\n", "f1: main moves after the triage")
                code, output, errors = invoke(["cr", "refresh", "f1hold", "--review-holds"], Fake(issues), "lead0001")
                if code != 1 or "untriaged" not in errors or "f1-main3.txt" not in output:
                    raise ValueError(f"the base moved after the triage: --review-holds must refuse and show the new incoming list: {code} {errors}\n{output}")
                new_tip = git("rev-parse", "HEAD", cwd=wt)
                issues[0]["metadata"].update(triaged_tip=new_tip, triaged_base_tip=at_main(), base_sha=at_main())
                fake = Fake(issues)
                code, output, errors = invoke(["cr", "refresh", "f1hold", "--review-holds"], fake, "lead0001")
                flat = " ".join(" ".join(w) for w in fake.writes())
                if code or f"review_tip={new_tip}" not in flat or f"review_base_tip={at_main()}" not in flat or "the review holds" not in output:
                    raise ValueError(f"F1: refresh --review-holds must re-stamp the review of the same changes: {code} {errors}\n{output}\n{fake.writes()}")
                # Two refreshes without a verdict: the second still shows what changed since the review, B1..B2 included.
                issues, tip, wt = make_cr("tri", "tri.txt", "x\n")
                commit(repo_root, "tri-b2.txt", "b2\n", "tri: base change one")
                first_fake = Fake(issues)
                invoke(["cr", "refresh", "tri"], first_fake, "lead0001")
                flat_first = " ".join(" ".join(w) for w in first_fake.writes())
                if "triaged_tip=" not in flat_first or f"triaged_base_tip={at_main()}" not in flat_first:
                    raise ValueError(f"a refresh must record what it asked the triage about: {first_fake.writes()}")
                issues[0]["metadata"].update(base_sha=at_main())  # the first refresh moved the fork point to B2
                commit(repo_root, "tri-b3.txt", "b3\n", "tri: base change two")
                _, output, _ = invoke(["cr", "refresh", "tri"], Fake(issues), "lead0001")
                if "tri-b2.txt" not in output or "tri-b3.txt" not in output or "since the review" not in output or "range-diff review..new" not in output:
                    raise ValueError(f"a stale review's refresh must show what changed since the review:\n{output}")
                issues, tip, wt = make_cr("f1new", "f1n.txt", "x\n")
                commit(wt, "f1n2.txt", "unreviewed\n", "f1: unreviewed commit")
                code, _, errors = invoke(["cr", "refresh", "f1new", "--review-holds"], Fake(issues), "lead0001")
                if code != 1 or "no longer the reviewed changes" not in errors:
                    raise ValueError(f"F1: --review-holds must refuse commits that were not reviewed: {code} {errors}")
                issues, tip, wt = make_cr("f1red", "f1r.txt", "x\n")
                fake = Fake(issues)
                fake.settings["custom.board.checks"] = "false"
                code, _, errors = invoke(["cr", "refresh", "f1red", "--review-holds"], fake, "lead0001")
                if code != 1 or "check is not passing" not in errors:
                    raise ValueError(f"F1: --review-holds must refuse while the check fails: {code} {errors}")
                if invoke(["cr", "refresh", "f1red", "--review-holds"], Fake([cr_issue("f1red", "in_review")]), "lead0001")[0] != 1:
                    raise ValueError("F1: --review-holds is for a CR waiting for its Accept")

                # F2: the reviewer's pass records only a tip the reviewer saw.
                issues, tip, wt = make_cr("f2", "f2.txt", "x\n")
                issues[0].update(status="in_review", assignee="bbbb2222")
                issues[0]["metadata"].update(reviewing_tip=tip)
                commit(repo_root, "f2-main.txt", "m\n", "f2: main moves under the review")
                fake = Fake(issues)
                code, _, errors = invoke(["handover", "f2", "reviewed"], fake, "bbbb2222")
                flat = " ".join(" ".join(w) for w in fake.writes())
                if code != 1 or "the tip moved" not in errors or "review_tip=" in flat or "reviewing_tip=" not in flat:
                    raise ValueError(f"F2: a pass over a tip the reviewer did not see must record nothing and say so: {code} {errors}\n{fake.writes()}")
                issues[0]["metadata"]["reviewing_tip"] = git("rev-parse", "HEAD", cwd=wt)
                fake = Fake(issues)
                code, output, errors = invoke(["handover", "f2", "reviewed again"], fake, "bbbb2222")
                if code or "review_tip=" not in " ".join(" ".join(w) for w in fake.writes()):
                    raise ValueError(f"F2: the second pass, over the tip now seen, must record the verdict: {code} {errors}")

                # F3: a failed claim never deletes a branch that existed before.
                issues, tip, wt = make_cr("f3", "f3.txt", "unlanded work\n")
                issues[0].update(status="open")
                issues[0]["metadata"].update(stage=None)
                git("worktree", "remove", "--force", str(wt))
                issues.append(cr_item("f3.open", "f3"))
                with patch.object(board, "claim_one", lambda issue, actor: (False, "lost the race")):
                    invoke(["claim", "f3"], Fake(issues), "aaaa1111")
                if not git("branch", "--list", "cr/f3") or git("log", "-1", "--format=%s", "cr/f3") != "f3: pass":
                    raise ValueError("F3: a failed claim deleted a branch that held unlanded work")

                # F4/F5: every rebase is `--onto <base tip> <fork point>`; a rebase left on a conflict is remembered.
                p_issues, p_tip0, p_wt = make_cr("f4p", "f4a.txt", "a\n")
                p_one = commit(p_wt, "f4b.txt", "b\n", "f4p: second commit")
                c_issues, c_tip, c_wt = make_cr("f4c", "f4c.txt", "c\n", base="f4p")
                git("checkout", "-q", "--detach", cwd=p_wt)
                git("branch", "-f", "cr/f4p", p_tip0)  # the parent drops its trailing commit
                git("checkout", "-q", "cr/f4p", cwd=p_wt)
                c_issues[0]["metadata"].update(base_sha=p_one)
                c_issues[0].update(status="in_review")
                p_issues[0]["status"] = "needs_acceptance"
                code, output, errors = invoke(["cr", "refresh", "f4c"], Fake([*p_issues, *c_issues]), "lead0001")
                if code or p_one in git("log", "--format=%H", cwd=c_wt).split():
                    raise ValueError(f"F4: a commit the base dropped must not become the child's own: {code} {errors}\n{output}")
                # F5: a conflict stops the rebase and leaves a marker; after the hand resolution and a further move of the base, the
                # rerun rebases `--onto` the resolved base, never replaying the base's commits.
                b_issues, b_tip, b_wt = make_cr("f5b", "f5.txt", "base line\n")
                k_issues, k_tip, k_wt = make_cr("f5k", "f5k.txt", "own\n", base="f5b")
                commit(k_wt, "f5.txt", "child edit\n", "f5k: edits the base's line")
                Path(b_wt, "f5.txt").write_text("base rewritten\n", encoding="utf-8")
                git("add", "f5.txt", cwd=b_wt)
                git("commit", "-q", "--amend", "-m", "f5b: rewritten", cwd=b_wt)
                b_issues[0]["status"] = "needs_acceptance"
                k_issues[0].update(status="in_review")
                fake = Fake([*b_issues, *k_issues])
                code, _, errors = invoke(["cr", "refresh", "f5k"], fake, "lead0001")
                marker = next((a.split("=", 1)[1] for w in fake.writes() for a in w if a.startswith("rebase_onto=") and a != "rebase_onto="), None)
                if code != 1 or "stopped on a conflict" not in errors or marker != git("rev-parse", "cr/f5b") \
                        or not any(a.startswith("rebase_from=") for w in fake.writes() for a in w):
                    raise ValueError(f"F5: a conflict must stop the rebase and remember its target: {code} {errors} {marker}")
                Path(k_wt, "f5.txt").write_text("resolved\n", encoding="utf-8")
                git("add", "f5.txt", cwd=k_wt)
                subprocess.run(["git", "-c", "core.editor=true", "rebase", "--continue"], cwd=k_wt, check=True, capture_output=True)
                Path(b_wt, "f5-later.txt").write_text("later\n", encoding="utf-8")  # the base is rewritten again before the rerun
                git("add", "f5-later.txt", cwd=b_wt)
                git("commit", "-q", "--amend", "-m", "f5b: rewritten", cwd=b_wt)
                k_issues[0]["metadata"].update(rebase_onto=marker)
                fake = Fake([*b_issues, *k_issues])
                code, output, errors = invoke(["cr", "refresh", "f5k"], fake, "lead0001")
                if not any(f"base_sha={marker}" in " ".join(w) for w in fake.writes()):
                    raise ValueError(f"F5: a rebase completed by hand must move the fork point to its target before the next rebase: {fake.writes()}")
                subjects = git("log", "--format=%s", cwd=k_wt).split("\n")
                if code or subjects.count("f5b: rewritten") != 1 or "stopped on a conflict" in errors or "f5-later.txt" not in git("ls-files", cwd=k_wt):
                    raise ValueError(f"F5: the rerun after a resolved conflict and a moved base must not replay the base: {code} {errors}\n{subjects}")

                # F6: only a vouched tip is settled; a fast-forward of the branch to the target is not a landing; a failure is a deviation.
                issues, tip, wt = make_cr("f6ff", "f6.txt", "x\n")
                issues[0] = cr_issue("f6ff", "in_progress", assignee="aaaa1111", base="main", base_sha=issues[0]["metadata"]["base_sha"], setup_sha=issues[0]["metadata"]["setup_sha"])
                git("merge", "-q", "--ff-only", "cr/f6ff")
                fake = Fake(issues)
                invoke(["queue"], fake, "lead0001")
                if any(w[:2] == ["close", "f6ff"] for w in fake.writes()) or not wt.exists():
                    raise ValueError("F6: a branch the target merely contains, with no vouching, was taken for landed")
                issues, tip, wt = make_cr("f6bad", "f6b.txt", "x\n")
                git("merge", "-q", "--ff-only", "cr/f6bad")
                with patch.object(board, "finish_landing", lambda *a, **k: (_ for _ in ()).throw(board.BoardError("bd close refused: assignee is x"))):
                    code, _, errors = invoke(["queue"], Fake(issues), "lead0001")
                    _, report, _ = invoke(["check"], Fake(issues), "lead0001")
                if code != 0 or "f6bad  cr-landing" not in report or "bd close refused" not in report:
                    raise ValueError(f"F6: a landing that cannot be finished must be a check deviation and stop nothing: {code} {errors}\n{report}")

                # F7: no landing while a worktree rebases or bisects the target.
                issues, tip, wt = make_cr("f7", "f7.txt", "x\n")
                before = at_main()
                git("checkout", "-q", "--detach")
                gitdir = Path(git("rev-parse", "--absolute-git-dir"))
                (gitdir / "rebase-merge").mkdir()
                (gitdir / "rebase-merge" / "head-name").write_text("refs/heads/main\n", encoding="utf-8")
                code, _, errors = invoke(["cr", "land", "f7"], Fake(issues), "lead0001")
                refused_f7 = code == 1 and "is rebasing main" in errors and at_main() == before
                (gitdir / "rebase-merge" / "head-name").unlink()
                (gitdir / "rebase-merge").rmdir()
                (gitdir / "BISECT_START").write_text("main\n", encoding="utf-8")
                code, _, errors = invoke(["cr", "land", "f7"], Fake(issues), "lead0001")
                refused_f7 = refused_f7 and code == 1 and "is bisecting main" in errors and at_main() == before
                (gitdir / "BISECT_START").unlink()
                git("checkout", "-q", "main")
                if not refused_f7:
                    raise ValueError(f"F7: land must refuse while the target is being rebased or bisected: {errors}")

                # F8: the pair names the tree that was checked.
                for what, command in (("a commit during the checks", "git commit -q --allow-empty -m sneaky; true"), ("a file written by the checks", "echo x > generated.txt; true")):
                    issues, tip, wt = make_cr("f8" + what[:6].strip().replace(" ", ""), "f8.txt", "x\n")
                    fake = Fake(issues)
                    fake.settings["custom.board.checks"] = command
                    code, _, errors = invoke(["cr", "refresh", issues[0]["id"]], fake, "lead0001")
                    if code != 1 or "changed the worktree" not in errors or any("check_result" in " ".join(w) for w in fake.writes()):
                        raise ValueError(f"F8: {what} must record nothing: {code} {errors} {fake.writes()}")

                # F9: the review pair goes with a return and with a new hand-over.
                fake = Fake(variant(**{"CR ready": {"status": "in_review", "assignee": "lead0001", "metadata": {"review_tip": "1" * 40}}}))
                invoke(["return", "fx-ovo.c1", "again"], fake, "lead0001")
                if not any("--unset-metadata" in w and "review_tip" in w for w in fake.writes()):
                    raise ValueError(f"F9: a return must clear the review pair: {fake.writes()}")
                # F10: reject reopens work, never a ratification.
                rej = [cr_issue("rej10", "needs_acceptance"), cr_item("rej10.i", "rej10", "closed"),
                       {**cr_item("rej10.r", "rej10", "closed"), "title": "Ratify design: CR rej10", "metadata": {"ratification": "1"}}]
                fake = Fake(rej)
                invoke(["cr", "reject", "rej10", "no"], fake, "lead0001")
                reopened = [w[1] for w in fake.writes() if w[:1] == ["update"] and "--status" in w and "open" in w]
                if reopened != ["rej10.i"]:
                    raise ValueError(f"F10: reject reopened {reopened}")

                # Risks: the branch is deleted only if it still is at the landed tip; after a partial landing the messages say so;
                # refresh work goes to the first queued CR that is not waiting; land_blocked sees renames; a raw close of a CR is
                # refused; a deciding session can take a passed look-after child by id.
                issues, tip, wt = make_cr("r1", "r1.txt", "x\n")
                commit(wt, "r1b.txt", "more\n", "r1: commit after the landed tip")
                with patch.object(board.subprocess, "run", Fake(issues)):
                    notes = board.finish_landing(bare_deck(issues, complete=False), issues[0], tip, "main", Path(repo_root))
                if not git("branch", "--list", "cr/r1") or not any("kept" in note for note in notes):
                    raise ValueError(f"risk: the branch is deleted only if it still is at the landed tip: {notes}")
                issues, tip, wt = make_cr("r2", "r2.txt", "x\n")
                with patch.object(board, "finish_landing", lambda *a, **k: (_ for _ in ()).throw(board.BoardError("close failed"))):
                    code, _, errors = invoke(["cr", "land", "r2"], Fake(issues), "lead0001")
                if code != 1 or "now holds" not in errors or "not landed" in errors or at_main() != tip:
                    raise ValueError(f"risk: after a fast-forward whose close failed the message must say the target holds the tip: {code} {errors}")
                git("worktree", "remove", "--force", str(wt))
                git("branch", "-D", "cr/r2")
                (Path(repo_root) / "ren_src.txt").write_text("1\n2\n", encoding="utf-8")
                git("add", "ren_src.txt")
                git("commit", "-q", "-m", "ren source")
                issues, tip, wt = make_cr("r3", "r3.txt", "x\n")
                git("mv", "ren_src.txt", "ren_dst.txt", cwd=wt)
                git("commit", "-q", "-am", "r3: rename", cwd=wt)
                tip = git("rev-parse", "HEAD", cwd=wt)
                issues[0]["metadata"].update(check_tip=tip, review_tip=tip)
                Path(repo_root, "ren_src.txt").write_text("1\n2\nlocal\n", encoding="utf-8")
                code, _, errors = invoke(["cr", "land", "r3"], Fake(issues), "lead0001")
                git("checkout", "-q", "--", "ren_src.txt")
                if code != 1 or "land blocked" not in errors or "ren_src.txt" not in errors:
                    raise ValueError(f"risk: land_blocked must list the old path of a renamed file: {code} {errors}")
                waiting_head = [cr_issue("rw1", "needs_acceptance", priority=1, since="2026-10-22T15:00:00Z", blocks=("rw-open",), base="main"),
                                cr_issue("rw-open", "open"), cr_item("rw-open.i", "rw-open"),
                                cr_issue("rw2", "needs_acceptance", priority=2, since="2026-10-22T15:05:00Z", base="main")]
                deck = bare_deck(waiting_head, complete=False)
                if deck.claimable(waiting_head[0]) is not None or deck.claimable(waiting_head[3]) != "refresh":
                    raise ValueError(f"risk: refresh work must go to the first queued CR that is not waiting: {deck.claimable(waiting_head[0])} {deck.claimable(waiting_head[3])}")
                with patch.object(board.os, "execvpe", lambda *call: (_ for _ in ()).throw(AssertionError("bd close was run"))):
                    code = 0
                    errors = io.StringIO()
                    with contextlib.redirect_stderr(errors), patch.object(board.subprocess, "run", Fake([cr_issue("closing", "needs_acceptance")])):
                        code = board.main(["bd", "close", "closing", "--reason", "closing a change request by hand is refused"])
                if code != 2 or "board cr land" not in errors.getvalue():
                    raise ValueError(f"risk: a raw bd close of a change request must be refused: {code} {errors.getvalue()}")
                low_i, _, _ = make_cr("rl", "rl.txt", "x\n")
                up_i, _, _ = make_cr("ru", "ru.txt", "y\n", base="rl")
                up_i[0].update(status="in_review")
                up_i[0]["metadata"].update(look="after")
                fake = Fake([*low_i, *up_i])
                code, output, _ = invoke(["claim", "ru"], fake, "lead0001")
                refused, _, _ = invoke(["claim", "ru"], Fake([*low_i, *up_i]), "aaaa1111")
                if code or ["update", "ru", "--assignee", "lead0001", "--if-assignee", "", "--json"] not in fake.writes() or refused == 0:
                    raise ValueError(f"risk: a deciding session takes a passed look-after child by id, an agent session does not: {code} {fake.writes()}")
                # Check exit status contract: 0 ran, 1 ran with failure lines on stdout, anything else is a broken check. stderr is no
                # failure: a two-word stderr line only at the tip (ex.txt exists there) passes; failure lines on stderr alone with exit 1
                # are a broken check.
                for name, command, result in (("x0", "echo 'a.ts E9'; exit 0", "check_result=pass"), ("x1", "echo 'a.ts E9'; exit 1", "check_result=pass"),
                                              ("xse", "test -f ex.txt && echo 'built 12ms' >&2; exit 0", "check_result=pass"),
                                              ("xs1", "echo 'a.ts E9' >&2; exit 1", "check_result=fail"),
                                              ("x1n", "echo nothing; exit 1", "check_result=fail"), ("x2", "echo 'a.ts E1'; exit 2", "check_result=fail"),
                                              ("x127", "no-such-command-here", "check_result=fail")):
                    issues, tip, wt = make_cr("ex" + name, "ex.txt", "x\n")
                    fake = Fake(issues)
                    fake.settings["custom.board.checks"] = command
                    fake.settings["custom.board.setup"] = "true"
                    invoke(["cr", "refresh", "ex" + name], fake, "lead0001")
                    flat = " ".join(" ".join(w) for w in fake.writes())
                    if result not in flat and not (name in ("x0", "x1") and "check_result=fail" in flat):
                        raise ValueError(f"check exit contract {name}: {flat}")
                    if name == "xse" and "check_result=fail" in flat:
                        raise ValueError(f"check exit contract {name}: stderr lines are no failures: {flat}")
                    if name in ("x2", "x127", "x1n", "xs1") and "check_result=fail" not in flat:
                        raise ValueError(f"check exit contract {name} must fail closed: {flat}")

                # Round 2. N1: a rebase that was aborted is not a completed one; N2: a prunable worktree does not stop a landing; (a): a pass
                # with no tip recorded as seen is refused once; C1/C2: a corrupt cache file and a leftover base worktree heal themselves;
                # a stale review is refresh work too; a failed claim's branch removal uses the tip it was created at.
                p_issues, p_tip0, p_wt = make_cr("n1p", "n1a.txt", "a\n")
                p_one = commit(p_wt, "n1b.txt", "b\n", "n1p: second commit")
                c_issues, c_tip, c_wt = make_cr("n1c", "n1c.txt", "c\n", base="n1p")
                git("checkout", "-q", "--detach", cwd=p_wt)
                git("branch", "-f", "cr/n1p", p_tip0)  # the parent drops its trailing commit; the child still has it
                git("checkout", "-q", "cr/n1p", cwd=p_wt)
                c_issues[0]["metadata"].update(base_sha=p_one, rebase_onto=p_tip0, rebase_from=c_tip)  # a refresh stopped, then was aborted
                c_issues[0]["status"] = "in_review"
                p_issues[0]["status"] = "needs_acceptance"
                code, output, errors = invoke(["cr", "refresh", "n1c"], Fake([*p_issues, *c_issues]), "lead0001")
                if code or p_one in git("log", "--format=%H", cwd=c_wt).split():
                    raise ValueError(f"N1: an aborted rebase must not count as completed, the dropped commit must leave the child: {code} {errors}\n{output}")

                issues, tip, wt = make_cr("n2", "n2.txt", "x\n")
                gone_issues, _, gone_wt = make_cr("n2gone", "n2g.txt", "y\n")
                shutil.rmtree(gone_wt)  # git lists this worktree as prunable
                git("checkout", "-q", "-b", "n2-elsewhere")
                code, _, errors = invoke(["cr", "land", "n2"], Fake(issues), "lead0001")
                git("checkout", "-q", "main")
                git("worktree", "prune")
                if code or at_main() != tip:
                    raise ValueError(f"N2: a prunable worktree must not stop a landing: {code} {errors}")

                issues, tip, wt = make_cr("a1", "a1.txt", "x\n")
                issues[0].update(status="in_review", assignee="bbbb2222")
                issues[0]["metadata"].pop("reviewing_tip", None)
                fake = Fake(issues)
                code, _, errors = invoke(["handover", "a1", "reviewed"], fake, "bbbb2222")
                flat = " ".join(" ".join(w) for w in fake.writes())
                if code != 1 or "no tip is recorded as seen" not in errors or "review_tip=" in flat.replace("reviewing_tip=", "") or "reviewing_tip=" not in flat:
                    raise ValueError(f"(a): a pass with no recorded tip must be refused once, the tip stored as seen: {code} {errors}\n{fake.writes()}")
                issues[0].update(status="in_review", assignee=None)
                fake = Fake(issues)
                invoke(["take", "a1"], fake, "lead0001")
                if not any("--unset-metadata" in w and "reviewing_tip" in w for w in fake.writes()):
                    raise ValueError(f"(a): a taken-over review must start without a seen tip: {fake.writes()}")
                # Independence: the session that handed a CR over cannot take its review; another session can.
                issues[0]["comments"] = [{"author": "cccc3333", "text": "board handover: done", "created_at": "2026-10-22T15:00:00Z"}]
                fake = Fake(issues)
                code, _, errors = invoke(["take", "a1"], fake, "cccc3333")
                if code != 1 or "your own hand-over" not in errors or fake.writes():
                    raise ValueError(f"take of the author's own review must be refused: {code} {errors} {fake.writes()}")
                fake = Fake(issues)
                if invoke(["take", "a1"], fake, "solo0001")[0] != 0 or not fake.writes():
                    raise ValueError("another session must be able to take the review")

                cache_dir = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir")) / "board-base-checks"
                tip_now = git("rev-parse", "main")
                probe = bare_deck([], complete=False)
                probe.settings.update({"setup": "true", "checks": "echo 'z.ts Z1'; exit 1"})
                dummy = {"id": "heal", "metadata": {}}
                with patch.object(board, "current_setting", lambda key: probe.settings[key.rsplit(".", 1)[1]]):
                    first = board.base_failures(probe, dummy, Path(repo_root), tip_now)
                    victim = next(f for f in cache_dir.iterdir() if not f.name.endswith((".lock", ".tmp")) and f.read_text().startswith("z.ts"))
                    victim.write_text("not a result row\n", encoding="utf-8")
                    healed = board.base_failures(probe, dummy, Path(repo_root), tip_now)  # C1
                    leftover = Path(repo_root, ".worktrees") / f".base-{victim.name[:12]}"
                    victim.unlink()
                    leftover.mkdir(parents=True)
                    (leftover / "junk").write_text("x", encoding="utf-8")
                    rebuilt = board.base_failures(probe, dummy, Path(repo_root), tip_now)  # C2
                if not (first == healed == rebuilt == {("z.ts", "Z1"): 1}) or leftover.exists():
                    raise ValueError(f"C1/C2: the cache must heal from a corrupt file and a leftover worktree: {first} {healed} {rebuilt}")
                # C3: a symlink at the base path is dropped, never followed (its target keeps its uncommitted file); a registered
                # base worktree whose folder is gone is taken over without a repo-wide prune (another gone worktree keeps its record).
                other = Path(repo_root, ".worktrees") / "c3-other"
                git("worktree", "add", "--detach", str(other), tip_now)
                (other / "uncommitted.txt").write_text("keep\n", encoding="utf-8")
                gone = Path(repo_root, ".worktrees") / "c3-gone"
                git("worktree", "add", "--detach", str(gone), tip_now)
                shutil.rmtree(gone)
                with patch.object(board, "current_setting", lambda key: probe.settings[key.rsplit(".", 1)[1]]):
                    victim.unlink()
                    leftover.symlink_to(other)
                    linked = board.base_failures(probe, dummy, Path(repo_root), tip_now)
                    victim.unlink()
                    git("worktree", "add", "--detach", str(leftover), tip_now)
                    shutil.rmtree(leftover)
                    taken = board.base_failures(probe, dummy, Path(repo_root), tip_now)
                registered = git("worktree", "list", "--porcelain")
                if (linked != {("z.ts", "Z1"): 1} or taken != linked or not (other / "uncommitted.txt").is_file()
                        or leftover.exists() or str(gone) not in registered):
                    raise ValueError(f"C3: the base path cleanup must drop a symlink unfollowed and prune nothing else: {linked} {taken}")
                git("worktree", "remove", "--force", str(other))

                issues, tip, wt = make_cr("sr", "sr.txt", "x\n")
                issues.append(cr_item("sr.x", "sr", "closed"))
                with patch.object(board, "current_setting", lambda key: "main" if key.endswith("target") else "x"):
                    accept_kind = board.Board([*issues], complete=False).claimable(issues[0])
                    issues[0]["metadata"]["review_base_tip"] = "e" * 40  # the check is current, the review is not
                    stale_kind = board.Board([*issues], complete=False).claimable(issues[0])
                if (accept_kind, stale_kind) != ("accept", "refresh"):
                    raise ValueError(f"a queued CR with a current check and review waits for its Accept; with a stale review it is refresh work: {accept_kind} {stale_kind}")

                # A CR open in the console's review tree (`<main>-review`, its marker at the CR's tip) is not moved under the user: no
                # refresh work, a non-holder's refresh is skipped; the holder's refresh runs, and a tree set to another CR holds nothing.
                issues_rt, tip_rt, wt_rt = make_cr("rt", "rt.txt", "x\n")
                issues_rt2, tip_rt2, wt_rt2 = make_cr("rt2", "rt2.txt", "x\n")
                commit(repo_root, "rt-base.txt", "b\n", "main moves under rt")
                review_main = Path(f"{repo_root}-review")
                git("worktree", "add", "-q", "--detach", str(review_main), tip_rt)
                try:
                    git("update-ref", "refs/worktree/console-review-end", tip_rt, cwd=review_main)
                    with patch.object(board, "current_setting", lambda key: "main" if key.endswith("target") else "x"):
                        held_kind = board.Board([*issues_rt], complete=False).claimable(issues_rt[0])
                    rows_rt = {c["id"]: c for c in json.loads(invoke(["console"], Fake([*issues_rt, *issues_rt2]), "lead0001")[1])["crs"]}
                    if held_kind != "accept" or not rows_rt["rt"]["heldByReviewTree"] or rows_rt["rt"]["refreshWork"] or rows_rt["rt2"]["heldByReviewTree"]:
                        raise ValueError(f"a CR open in the review tree is no refresh work and is marked held: {held_kind} {rows_rt['rt']} {rows_rt['rt2']}")
                    in_work = json.loads(invoke(["console"], Fake([{**issues_rt[0], "status": "in_progress", "assignee": "aaaa1111"}, issues_rt[1]]), "lead0001")[1])["crs"]
                    if any(c["heldByReviewTree"] for c in in_work if c["id"] == "rt"):
                        raise ValueError(f"only a CR waiting for the user is held by the review tree, not one in work at the marker's tip: {in_work}")
                    code, output, errors = invoke(["cr", "refresh", "rt"], Fake(issues_rt), "aaaa1111")
                    if not code or "rt is open in your review tree; it refreshes once a deciding session claims it" not in output + errors or git("rev-parse", "cr/rt") != tip_rt:
                        raise ValueError(f"a refresh by a session not holding the CR must refuse it while the review tree holds it: {code} {output} {errors}")
                    code, output, errors = invoke(["cr", "refresh", "rt"], Fake([{**issues_rt[0], "assignee": "lead0001"}, issues_rt[1]]), "lead0001")
                    if code or git("rev-parse", "cr/rt") == tip_rt:
                        raise ValueError(f"the holder's refresh must run though the review tree holds the CR: {code} {output} {errors}")
                    code, output, errors = invoke(["cr", "refresh", "rt2"], Fake(issues_rt2), "aaaa1111")
                    if code or git("rev-parse", "cr/rt2") == tip_rt2:
                        raise ValueError(f"a review tree set to another CR must not hold this one: {code} {output} {errors}")
                finally:
                    git("worktree", "remove", "--force", str(review_main))

                issues, tip, wt = make_cr("cas", "cas.txt", "unlanded work\n")
                issues[0].update(status="open")
                git("worktree", "remove", "--force", str(wt))
                git("branch", "-D", "cr/cas")
                issues.append(cr_item("cas.open", "cas"))

                def lose_after_work(issue, actor):
                    made = Path(repo_root, ".worktrees", "cas")
                    commit(made, "cas-work.txt", "work\n", "cas: work made while the claim was in flight")
                    return False, "lost the race"

                with patch.object(board, "claim_one", lose_after_work):
                    invoke(["claim", "cas"], Fake(issues), "aaaa1111")
                if not git("branch", "--list", "cr/cas"):
                    raise ValueError("a failed claim removed a branch that moved past the tip it was created at")

                # A landed tip closes its CR on the next read (A6: ff and close are two writes); a fresh branch is not mistaken for landed.
                landed_issues, landed_tip, landed_wt = make_cr("derived", "z.txt", "z\n", base="main")
                git("merge", "-q", "--ff-only", landed_tip)
                fake = Fake(landed_issues)
                code, _, errors = invoke(["queue"], fake, "lead0001")
                if not any(w[:2] == ["close", "derived"] for w in fake.writes()) or landed_wt.exists():
                    raise ValueError(f"a CR whose tip main holds must be closed by the next read: {fake.writes()} {errors}")
                fresh_tip = git("rev-parse", "HEAD")
                git("worktree", "add", "-q", "-b", "cr/freshcr", str(Path(repo_root, ".worktrees", "freshcr")), fresh_tip)
                fresh = [cr_issue("freshcr", "in_progress", assignee="aaaa1111", base="main", base_sha=fresh_tip, setup_sha=fresh_tip), cr_item("freshcr.i", "freshcr")]
                fake = Fake(fresh)
                invoke(["queue"], fake, "lead0001")
                if any(w[0] == "close" for w in fake.writes()):
                    raise ValueError("a CR without a commit past its fork point was taken for landed")

                # Console rows and deviations.
                low_issues, _, _ = make_cr("low", "low.txt", "l\n")
                upr_issues, _, _ = make_cr("upr", "upr.txt", "u\n", base="low")
                upr_issues[0].update(status="in_review")
                upr_issues[0]["metadata"].update(look="after")
                rows = json.loads(invoke(["console"], Fake([*fresh, cr_issue("rtn", "open", base="main"), cr_issue("sf", "in_progress", assignee="aaaa1111", base="main",
                                                                                                                           base_sha=fresh_tip, setup_sha="1" * 40),
                                                            *low_issues, *upr_issues]), "lead0001")[1])["crs"]
                by_id = {c["id"]: c for c in rows}
                if by_id["upr"]["after"] != "low" or by_id["upr"]["parent"] != "low" or by_id["low"]["children"] != ["upr"] or by_id["low"]["after"] is not None \
                        or by_id["sf"]["setupFailed"] is not True or by_id["freshcr"]["setupFailed"] is not False \
                        or by_id["freshcr"]["baseSha"] != fresh_tip or by_id["freshcr"]["branch"] != "cr/freshcr" \
                        or by_id["freshcr"]["worktree"] != str(Path(repo_root, ".worktrees", "freshcr")) \
                        or "items" in by_id["freshcr"] or by_id["freshcr"]["check"]["state"] != "unchecked":
                    raise ValueError(f"board console crs: {json.dumps(rows, indent=1)}")
                loose = {**entry("loose-task", "task", "open", 2), "description": "d"}
                no_worktree = cr_issue("nowt", "in_progress", assignee="aaaa1111", base="main", base_sha=fresh_tip)
                git("branch", "cr/nowt2")
                no_worktree2 = cr_issue("nowt2", "in_review", base="main", base_sha=fresh_tip)
                fake = Fake([loose, no_worktree, no_worktree2, *fresh])
                fake.settings["custom.board.look"] = ""
                _, report, _ = invoke(["check"], fake)
                for needle in ("loose-task  no-cr", "nowt  cr-branch", "nowt2  cr-worktree", "cr-settings", "custom.board.look is not set"):
                    if needle not in report:
                        raise ValueError(f"board check lacks {needle!r}:\n{report}")
                if "freshcr  cr-" in report:
                    raise ValueError(f"board check flagged a change request with its worktree:\n{report}")

                # Review edits (r15-q75..q79): `board cr edits` shows the review tree's edits against the tip, commits exactly them as
                # the user's, moves the review tree's marker to that commit, stores a targeted or no-gate result for that tip only; the review
                # survives only the commits the board recorded (or their exact replays).
                git("config", "user.name", "Pat User")
                git("config", "user.email", "pat@example.com")

                def review_tree(name, tip, edit=True):
                    tree = Path(repo_root, ".worktrees", f"{name}-review")
                    git("worktree", "add", "-q", "--detach", str(tree), tip)
                    git("update-ref", "refs/worktree/console-review-end", tip, cwd=tree)
                    if edit:
                        Path(tree, "e.txt").write_text("edited\n", encoding="utf-8")
                        Path(tree, "new.txt").write_text("new file\n", encoding="utf-8")
                    return tree

                def flat(fake):
                    return [arg for w in fake.writes() for arg in w]

                def edits(cr_id, tree, tip, *extra, issues, actor="lead0001"):
                    fake = Fake(issues)
                    code, output, errors = invoke(["cr", "edits", cr_id, "--from", str(tree), "--tip", tip, *extra], fake, actor)
                    return code, output, errors, fake

                issues, tip, wt = make_cr("ed1", "e.txt", "e\n")
                tree = review_tree("ed1", tip)
                before_files = (Path(tree, "e.txt").read_text(), Path(tree, "new.txt").read_text())
                code, output, errors, fake = edits("ed1", tree, tip, issues=issues)
                if code or "+edited" not in output or "new.txt" not in output or "+new file" not in output or fake.writes() or git("rev-parse", "HEAD", cwd=wt) != tip:
                    raise ValueError(f"board cr edits must print tracked and new-file edits and change nothing: {code} {errors}\n{output}")
                code, _, errors, fake = edits("ed1", tree, "0" * 40, issues=issues)
                git("update-ref", "refs/worktree/console-review-end", at_main(), cwd=tree)  # the tree agrees with the asked tip: only the branch differs
                code_moved, _, errors_moved, _ = edits("ed1", tree, at_main(), issues=issues)
                git("update-ref", "refs/worktree/console-review-end", tip, cwd=tree)
                if code != 1 or code_moved != 1 or "its branch tip is" not in errors_moved or tip[:12] not in errors_moved or at_main()[:12] not in errors_moved:
                    raise ValueError(f"board cr edits must refuse a tip the branch no longer has, naming both: {code_moved} {errors_moved}")
                git("update-ref", "refs/worktree/console-review-end", at_main(), cwd=tree)
                code, _, errors, _ = edits("ed1", tree, tip, issues=issues)
                git("update-ref", "refs/worktree/console-review-end", tip, cwd=tree)
                if code != 1 or "was set to" not in errors:
                    raise ValueError(f"board cr edits must refuse a review tree set to another tip: {code} {errors}")
                clean = review_tree("ed1c", tip, edit=False)
                code, _, errors, _ = edits("ed1", clean, tip, issues=issues)
                if code != 1 or "holds no edits" not in errors:
                    raise ValueError(f"board cr edits must refuse a tree without edits: {code} {errors}")
                code, _, errors, fake = edits("ed1", tree, tip, "--commit", issues=issues)
                if code == 0 or fake.writes():
                    raise ValueError(f"board cr edits --commit needs a message: {code} {errors}")
                code, _, errors, fake = edits("ed1", tree, tip, "--commit", "-m", "Fix e", issues=issues, actor="aaaa1111")
                if code != 1 or "only a lead or solo" not in errors or git("rev-parse", "HEAD", cwd=wt) != tip:
                    raise ValueError(f"board cr edits --commit by an agent session must refuse: {code} {errors}")
                # --commit --no-gate: exactly the tree on disk, author the user, committer the session, no trailer, recorded on the CR, no-check result for the new tip.
                code, output, errors, fake = edits("ed1", tree, tip, "--commit", "-m", "Fix e", "--no-gate", "docs only", issues=issues)
                new = git("rev-parse", "HEAD", cwd=wt)
                tree_tracked = git("rev-parse", f"{new}^{{tree}}")
                fields = git("log", "-1", "--format=%an|%ae|%cn|%P", new).split("|")
                recorded = [json.loads(a.partition("=")[2]) for a in flat(fake) if a.startswith("review_edits=")]
                if code or new == tip or fields[:1] != ["Pat User"] or fields[2] != "lead0001" or fields[3] != tip \
                        or git("show", f"{new}:e.txt") != "edited" or git("show", f"{new}:new.txt") != "new file" \
                        or git("log", "-1", "--format=%B", new) != "Fix e" or git("rev-parse", "refs/heads/cr/ed1") != new \
                        or len(recorded) != 1 or len(recorded[0]) != 1 \
                        or recorded[0] != [{"commit": new}]:
                    raise ValueError(f"board cr edits --commit must commit exactly the edits as the user and record the commit: {code} {errors} {fields} {recorded}")
                if (Path(tree, "e.txt").read_text(), Path(tree, "new.txt").read_text()) != before_files or git("rev-parse", "HEAD", cwd=tree) != tip:
                    raise ValueError("board cr edits must not alter the review tree's files")
                if git("rev-parse", "refs/worktree/console-review-end", cwd=tree) != new or board.review_edits_tree(Path(repo_root), tree, new) != tree_tracked:
                    raise ValueError("board cr edits --commit must move the review tree's marker to the edit commit, whose tree the files then equal")
                # One recipe: the console's clean check (review.ts `snapshotTree`, on real git) builds the board's snapshot tree: modified,
                # deleted, new and tracked-but-ignored files count, an ignored new file does not, and the tree's own index stays as it was.
                issues16, tip16, wt16 = make_cr("ed16", ".gitignore", "*.log\n")
                Path(wt16, "kept.log").write_text("k\n", encoding="utf-8")
                Path(wt16, "gone.txt").write_text("g\n", encoding="utf-8")
                git("add", "-f", "kept.log", "gone.txt", cwd=wt16)
                git("commit", "-q", "-m", "more", cwd=wt16)
                tip16 = git("rev-parse", "HEAD", cwd=wt16)
                tree16 = review_tree("ed16", tip16, edit=False)
                Path(tree16, "kept.log").write_text("k changed\n", encoding="utf-8")
                Path(tree16, "gone.txt").unlink()
                Path(tree16, "new.txt").write_text("n\n", encoding="utf-8")
                Path(tree16, "junk.log").write_text("j\n", encoding="utf-8")
                own_index = Path(git("rev-parse", "--path-format=absolute", "--git-path", "index", cwd=tree16))
                index_before = own_index.read_bytes()
                runtime = shutil.which("bun") or shutil.which("node")
                if runtime is None:
                    raise ValueError("bun or node is needed to run the console's clean check on real git")
                with tempfile.TemporaryDirectory() as driver_dir:
                    driver = Path(driver_dir, "snapshot.mts")
                    review_ts = root / "claude" / "mods" / "console" / "hooks" / "review.ts"
                    driver.write_text(
                        "import { spawnSync } from 'node:child_process'\n"
                        f"import {{ snapshotTree }} from {json.dumps(str(review_ts))}\n"
                        "const run = async (argv, env) => { const p = spawnSync(argv[0], argv.slice(1), { env: { ...process.env, ...(env ?? {}) }, encoding: 'utf8' })\n"
                        "  return { exitCode: p.status ?? 1, stdout: p.stdout ?? '', stderr: p.stderr ?? '' } }\n"
                        "console.log(JSON.stringify(await snapshotTree(run, process.argv[2], process.argv[3])))\n", encoding="utf-8")
                    ran = subprocess.run([runtime, str(driver), str(tree16), tip16], capture_output=True, text=True)
                console16 = json.loads(ran.stdout or "null") if ran.returncode == 0 else ran.stderr
                board16 = board.review_edits_tree(Path(repo_root), tree16, tip16)
                listed16 = set(git("ls-tree", "-r", "--name-only", board16).split())
                if console16 != {"ok": True, "tree": board16} or listed16 != set(git("ls-tree", "-r", "--name-only", tip16).split()) - {"gone.txt"} | {"new.txt"} \
                        or git("show", f"{board16}:kept.log") != "k changed" or own_index.read_bytes() != index_before:
                    raise ValueError(f"the console's clean check must build the board's snapshot tree, leaving the tree's index alone: {console16} {board16} {sorted(listed16)}")
                written = flat(fake)
                if not {"check_kind=none", "check_reason=docs only", "check_result=pass", f"check_tip={new}"} <= set(written) or "--status" in written:
                    raise ValueError(f"--no-gate must store a no-check pass for the new tip and move nothing: {fake.writes()}")
                # The stored result shows as what it is and lands for that tip only; the review survives the recorded commit.
                stored = {**issues[0]["metadata"], "check_tip": new, "check_result": "pass", "check_kind": "none", "check_reason": "docs only",
                          "review_edits": json.dumps(recorded[0])}
                landing = [{**issues[0], "metadata": stored}, issues[1]]
                crow = next(c for c in json.loads(invoke(["console"], Fake(landing), "lead0001")[1])["crs"] if c["id"] == "ed1")
                _, queued, _ = invoke(["queue"], Fake(landing), "lead0001")
                if crow["check"]["kind"] != "none" or crow["check"]["reason"] != "docs only" or crow["check"]["state"] != "current" \
                        or crow["reviewState"] != "current" or "no check: docs only" not in queued:
                    raise ValueError(f"a no-gate result must show as no check, with the review current: {crow['check']} {crow['reviewState']}\n{queued}")
                code, out, errors = invoke(["cr", "land", "ed1", "--tip", tip[:8]], Fake(landing), "lead0001")
                if code != 1 or "branch moved" not in errors:
                    raise ValueError(f"landing must still refuse a tip other than the branch's: {code} {errors}")
                code, out, errors = invoke(["cr", "land", "ed1", "--tip", new[:8]], Fake(landing), "lead0001")
                if code or at_main() != new:
                    raise ValueError(f"board cr land must accept a no-gate result for exactly that tip, the review kept by the recorded commit: {code} {errors}")
                # A new commit that is not recorded after the reviewed tip is still refused, whatever its message says; so is a result for another tip.
                issues2, tip2, wt2 = make_cr("ed2", "e2.txt", "e\n")
                other = commit(wt2, "late.txt", "x\n", "late worker commit\n\nReview-edits: copied@trailer")
                stored2 = {**issues2[0]["metadata"], "check_tip": other, "check_result": "pass", "check_kind": "none", "check_reason": "r",
                           "review_edits": json.dumps(recorded[0])}
                code, _, errors = invoke(["cr", "land", "ed2"], Fake([{**issues2[0], "metadata": stored2}, issues2[1]]), "lead0001")
                if code != 1 or "its review is of another" not in errors or at_main() != new:
                    raise ValueError(f"a commit that is not recorded (a copied trailer included) must void the review: {code} {errors}")
                forged = {**issues2[0]["metadata"], "check_tip": tip2, "check_result": "pass", "check_kind": "none", "check_reason": "r"}
                code, _, errors = invoke(["cr", "land", "ed2"], Fake([{**issues2[0], "metadata": forged}, issues2[1]]), "lead0001")
                if code != 1 or "check is" not in errors:
                    raise ValueError(f"a no-gate result for another tip must not land this tip: {code} {errors}")
                # --gate: a targeted pass stores its command and output; a failing gate keeps the commit, stores the failure, moves nothing.
                issues3, tip3, wt3 = make_cr("ed3", "e.txt", "e\n")
                tree3 = review_tree("ed3", tip3)
                code, output, errors, fake = edits("ed3", tree3, tip3, "--commit", "-m", "Fix", "--gate", "echo targeted-ok", issues=issues3)
                new3 = git("rev-parse", "HEAD", cwd=wt3)
                written = flat(fake)
                if code or new3 == tip3 or not {"check_kind=targeted", "check_command=echo targeted-ok", "check_result=pass", "check_output=targeted-ok", f"check_tip={new3}"} <= set(written):
                    raise ValueError(f"--gate must store a targeted pass with its command and output: {code} {errors} {fake.writes()}")
                crow = next(c for c in json.loads(invoke(["console"], Fake([{**issues3[0], "metadata": {**issues3[0]["metadata"], "check_tip": new3, "check_kind": "targeted",
                                                                                                    "check_command": "echo targeted-ok"}}, issues3[1]]), "lead0001")[1])["crs"] if c["id"] == "ed3")
                if crow["check"]["kind"] != "targeted" or crow["check"]["command"] != "echo targeted-ok":
                    raise ValueError(f"a targeted result must show as targeted: {crow['check']}")
                git("reset", "-q", "--hard", tip3, cwd=wt3)
                tree3b = review_tree("ed3b", tip3)
                code, output, errors, fake = edits("ed3", tree3b, tip3, "--commit", "-m", "Fix", "--gate", "echo broken; exit 3", issues=issues3)
                written = flat(fake)
                if code != 1 or "nothing lands" not in output or "waits for the user" not in output or git("rev-parse", "HEAD", cwd=wt3) == tip3 \
                        or "check_result=fail" not in written or "check_kind=targeted" not in written or "--status" in written:
                    raise ValueError(f"a failing gate must keep the edit commit, store the failure and leave the CR waiting: {code} {output} {errors} {fake.writes()}")
                git("reset", "-q", "--hard", tip3, cwd=wt3)
                tree3c = review_tree("ed3c", tip3)
                code, _, errors, fake = edits("ed3", tree3c, tip3, "--commit", "-m", "Fix", "--gate", "touch stray.txt", issues=issues3)
                if code != 1 or "changed the worktree" not in errors or "check_result=pass" in flat(fake):
                    raise ValueError(f"a gate that leaves files behind must record nothing: {code} {errors} {fake.writes()}")
                Path(wt3, "stray.txt").unlink()
                git("reset", "-q", "--hard", tip3, cwd=wt3)
                # Return: commit only, no check stored.
                tree3d = review_tree("ed3d", tip3)
                code, output, errors, fake = edits("ed3", tree3d, tip3, "--commit", "-m", "Edit", issues=issues3)
                if code or git("rev-parse", "HEAD", cwd=wt3) == tip3 or any("check_" in a for a in flat(fake)):
                    raise ValueError(f"board cr edits --commit without a gate must store no check: {code} {errors} {fake.writes()}")
                # A full check clears a targeted label.
                issues4, tip4, wt4 = make_cr("ed4", "e4.txt", "e\n")
                issues4[0]["metadata"].update(check_kind="targeted", check_command="x")
                fake = Fake(issues4)
                invoke(["cr", "refresh", "ed4"], fake, "lead0001")
                if "check_kind" not in flat(fake) or "--unset-metadata" not in flat(fake):
                    raise ValueError(f"a full check must clear the targeted label: {fake.writes()}")
                # --checks: the project's checks as handover runs them, stored as a normal full check for the new tip; a failure keeps the commit.
                for ok, check_cmd in ((True, "true"), (False, "grep -q changed e9.txt && { echo 'e9.txt X1'; exit 1; }; exit 0")):
                    nm = "ed9" if ok else "ed9f"
                    issues9, tip9, wt9 = make_cr(nm, "e9.txt", "e\n")
                    tree9 = review_tree(nm, tip9)
                    Path(tree9, "e9.txt").write_text("changed\n", encoding="utf-8")
                    fake = Fake(issues9)
                    fake.settings["custom.board.checks"] = check_cmd
                    # fails only with the edit, so it is a new failure against the base
                    code, output, errors = invoke(["cr", "edits", nm, "--from", str(tree9), "--tip", tip9, "--commit", "-m", "Fix", "--checks"], fake, "lead0001")
                    written, new9 = flat(fake), git("rev-parse", "HEAD", cwd=wt9)
                    if new9 == tip9 or "--status" in written or ok != (code == 0) \
                            or (ok and not {"check_result=pass", f"check_tip={new9}"} <= set(written) or any(a.startswith("check_kind=") for a in written)) \
                            or (not ok and ("check_result=fail" not in written or "waits for the user" not in output)):
                        raise ValueError(f"--checks must store a full check for the new tip, or keep the commit and wait: {ok} {code} {output} {errors} {fake.writes()}")
                # --checks that rebased and failed: the marker stays at the edit commit the tree holds, and the session is told to Open again.
                issues17, tip17, wt17 = make_cr("ed17", "e17.txt", "e\n")
                commit(repo_root, "ed17-base.txt", "b\n", "main moves under ed17")
                tree17 = review_tree("ed17", tip17, edit=False)
                Path(tree17, "e17.txt").write_text("changed\n", encoding="utf-8")
                fake = Fake(issues17)
                fake.settings["custom.board.checks"] = "grep -q changed e17.txt && { echo 'e17.txt X1'; exit 1; }; exit 0"
                code, output, errors = invoke(["cr", "edits", "ed17", "--from", str(tree17), "--tip", tip17, "--commit", "-m", "Fix", "--checks"], fake, "lead0001")
                marker17, head17 = git("rev-parse", "refs/worktree/console-review-end", cwd=tree17), git("rev-parse", "HEAD", cwd=wt17)
                if code != 1 or "Open ed17 again before editing" not in output or marker17 == head17 or git("rev-parse", f"{marker17}^") != tip17 \
                        or git("rev-parse", f"{marker17}^{{tree}}") != board.review_edits_tree(Path(repo_root), tree17, marker17):
                    raise ValueError(f"a failed --checks that rebased must leave the marker at the edit commit and say Open again: {code} {output} {errors}")
                # --checks that rebased onto a moved base and passed: the review is of the old base, so it names the triage, not a landing.
                issues18, tip18, wt18 = make_cr("ed18", "e18.txt", "e\n")
                commit(repo_root, "ed18-base.txt", "b\n", "main moves under ed18")
                tree18 = review_tree("ed18", tip18, edit=False)
                Path(tree18, "e18.txt").write_text("changed\n", encoding="utf-8")
                fake = Fake(issues18)
                fake.settings["custom.board.checks"] = "true"
                code, output, errors = invoke(["cr", "edits", "ed18", "--from", str(tree18), "--tip", tip18, "--commit", "-m", "Fix", "--checks"], fake, "lead0001")
                if code or "board cr refresh ed18 --review-holds" not in output or "; land with" in output:
                    raise ValueError(f"a passing --checks that moved the base must name the review triage, not the landing: {code} {output} {errors}")
                # refresh --review-holds compares by patch-id: the reviewed commits plus the recorded edit commits keep the review; a changed
                # edit commit (an amend, a conflict fix) or any other commit stales it.
                issues8, tip8, wt8 = make_cr("ed8", "e8.txt", "e\n")
                edit8 = commit(wt8, "e8.txt", "edited\n", "edit")
                entry8 = json.dumps([{"commit": edit8}])
                triaged = {**issues8[0]["metadata"], "triaged_tip": edit8, "triaged_base_tip": issues8[0]["metadata"]["base_sha"], "review_edits": entry8}
                fake = Fake([{**issues8[0], "metadata": triaged}, issues8[1]])
                code, output, errors = invoke(["cr", "refresh", "ed8", "--review-holds"], fake, "lead0001")
                if code or f"review_tip={edit8}" not in flat(fake) or "the review holds" not in output:
                    raise ValueError(f"--review-holds must keep a review past a recorded edit commit: {code} {output} {errors} {fake.writes()}")
                git("commit", "-q", "--amend", "-m", "edit changed", cwd=wt8)
                Path(wt8, "e8.txt").write_text("edited differently\n", encoding="utf-8")
                git("commit", "-q", "-a", "--amend", "--no-edit", cwd=wt8)
                amended8 = git("rev-parse", "HEAD", cwd=wt8)
                fake = Fake([{**issues8[0], "metadata": {**triaged, "triaged_tip": amended8}}, issues8[1]])
                code, _, errors = invoke(["cr", "refresh", "ed8", "--review-holds"], fake, "lead0001")
                if code != 1 or "no longer the reviewed changes" not in errors:
                    raise ValueError(f"--review-holds must stale the review when a recorded edit commit was changed: {code} {errors}")
                git("reset", "-q", "--hard", edit8, cwd=wt8)
                other8 = commit(wt8, "e8b.txt", "x\n", "late worker commit")
                fake = Fake([{**issues8[0], "metadata": {**triaged, "triaged_tip": other8}}, issues8[1]])
                code, _, errors = invoke(["cr", "refresh", "ed8", "--review-holds"], fake, "lead0001")
                if code != 1 or "no longer the reviewed changes" not in errors:
                    raise ValueError(f"--review-holds must refuse a commit that is not a recorded edit: {code} {errors}")
                # A rebased copy of the recorded edit commit keeps the review; a changed commit is not the recorded one.
                issues10, tip10, wt10 = make_cr("ed10", "e10.txt", "e\n")
                tree10 = review_tree("ed10", tip10)
                Path(tree10, "e10.txt").write_text("edited\n", encoding="utf-8")
                fake = Fake(issues10)
                code, _, errors = invoke(["cr", "edits", "ed10", "--from", str(tree10), "--tip", tip10, "--commit", "-m", "Fix"], fake, "lead0001")
                rec10 = next(a for a in flat(fake) if a.startswith("review_edits=")).partition("=")[2]
                cr10 = {"metadata": {"review_edits": rec10}}
                commit(repo_root, "ed10-base.txt", "b\n", "main moves under ed10")
                git("rebase", "-q", "main", cwd=wt10)
                edit10, reviewed10 = git("rev-parse", "HEAD", cwd=wt10), git("rev-parse", "HEAD~1", cwd=wt10)
                if code or not board.edits_only(Path(repo_root), cr10, reviewed10, edit10):
                    raise ValueError(f"a recorded edit commit must keep the review after a rebase: {code} {errors}")
                Path(wt10, "e10.txt").write_text("edited and fixed\n", encoding="utf-8")
                git("commit", "-q", "-a", "--amend", "--no-edit", cwd=wt10)
                if board.edits_only(Path(repo_root), cr10, reviewed10, git("rev-parse", "HEAD", cwd=wt10)):
                    raise ValueError("a changed edit commit must not keep the review")
                # F4: a whitespace-only change of a recorded edit commit is not the recorded one.
                issues11, tip11, wt11 = make_cr("ed11", "e11.txt", "e\n")
                tree11 = review_tree("ed11", tip11)
                Path(tree11, "e11.txt").write_text("alpha beta\n", encoding="utf-8")
                fake = Fake(issues11)
                invoke(["cr", "edits", "ed11", "--from", str(tree11), "--tip", tip11, "--commit", "-m", "Fix"], fake, "lead0001")
                cr11 = {"metadata": {"review_edits": next(a for a in flat(fake) if a.startswith("review_edits=")).partition("=")[2]}}
                edit11 = git("rev-parse", "HEAD", cwd=wt11)
                if not board.edits_only(Path(repo_root), cr11, tip11, edit11):
                    raise ValueError("a recorded edit commit must keep the review")
                Path(wt11, "e11.txt").write_text("alpha  beta\n", encoding="utf-8")
                git("commit", "-q", "-a", "--amend", "--no-edit", cwd=wt11)
                if board.edits_only(Path(repo_root), cr11, tip11, git("rev-parse", "HEAD", cwd=wt11)):
                    raise ValueError("a whitespace-only change of an edit commit must not keep the review")
                # N5: the same insert at another place (repeated context, so the patch-id is equal) is not the recorded commit.
                issues14, tip14, wt14 = make_cr("ed14", "e14.txt", "0\n1\n2\n3\n4\n5\n6\n9\n1\n2\n3\n4\n5\n6\n9\n")
                tree14 = review_tree("ed14", tip14, edit=False)
                Path(tree14, "e14.txt").write_text("0\n1\n2\n3\nNEW\n4\n5\n6\n9\n1\n2\n3\n4\n5\n6\n9\n", encoding="utf-8")
                fake = Fake(issues14)
                invoke(["cr", "edits", "ed14", "--from", str(tree14), "--tip", tip14, "--commit", "-m", "Fix"], fake, "lead0001")
                cr14 = {"metadata": {"review_edits": next(a for a in flat(fake) if a.startswith("review_edits=")).partition("=")[2]}}
                edit14 = git("rev-parse", "HEAD", cwd=wt14)
                git("reset", "-q", "--hard", tip14, cwd=wt14)
                Path(wt14, "e14.txt").write_text("0\n1\n2\n3\n4\n5\n6\n9\n1\n2\n3\nNEW\n4\n5\n6\n9\n", encoding="utf-8")
                git("commit", "-q", "-a", "-m", "Fix", cwd=wt14)
                moved14 = git("rev-parse", "HEAD", cwd=wt14)
                if board.patch_ids(wt14, tip14, edit14) != board.patch_ids(wt14, tip14, moved14) or not board.edits_only(Path(repo_root), cr14, tip14, edit14) \
                        or board.edits_only(Path(repo_root), cr14, tip14, moved14):
                    raise ValueError("the recorded change at another place (same patch-id) must not keep the review")
                # The review tree's marker moves by compare-and-swap: a tree set to another range meanwhile commits nothing.
                issues15, tip15, wt15 = make_cr("ed15", "e15.txt", "e\n")
                tree15 = review_tree("ed15", tip15, edit=False)
                Path(tree15, "e15.txt").write_text("edited\n", encoding="utf-8")
                real_commit = board.edits_commit
                def racing_commit(*a, **k):
                    git("update-ref", "refs/worktree/console-review-end", at_main(), cwd=tree15)  # the console opens another range
                    return real_commit(*a, **k)
                with patch.object(board, "edits_commit", racing_commit):
                    code, _, errors, fake = edits("ed15", tree15, tip15, "--commit", "-m", "Fix", issues=issues15)
                if code != 1 or "meanwhile" not in errors or git("rev-parse", "HEAD", cwd=wt15) != tip15 or fake.writes() \
                        or git("rev-parse", "refs/worktree/console-review-end", cwd=tree15) != at_main():
                    raise ValueError(f"a review tree set to another range during the commit must leave the branch, marker and metadata as they were: {code} {errors} {fake.writes()}")
                # F7: only the console's review tree, set to --tip, is read for edits.
                issues12, tip12, wt12 = make_cr("ed12", "e12.txt", "e\n")
                loose = Path(repo_root, ".worktrees", "ed12-loose")
                git("worktree", "add", "-q", "--detach", str(loose), tip12)
                Path(loose, "e12.txt").write_text("loose edit\n", encoding="utf-8")
                code, _, errors, fake = edits("ed12", loose, tip12, "--commit", "-m", "Fix", issues=issues12)
                if code != 1 or "review-end marker" not in errors or git("rev-parse", "HEAD", cwd=wt12) != tip12 or fake.writes():
                    raise ValueError(f"a worktree without the review-end marker must not be committed as the user's edits: {code} {errors} {fake.writes()}")
                # F6: a re-reviewed CR whose reviewed range already holds an edit commit keeps its review through a refresh.
                issues13, tip13, wt13 = make_cr("ed13", "e13.txt", "e\n")
                edit13 = commit(wt13, "e13.txt", "edited\n", "edit")
                entry13 = json.dumps([{"commit": edit13}])
                base13 = issues13[0]["metadata"]["base_sha"]
                m13 = {**issues13[0]["metadata"], "review_tip": edit13, "review_base_tip": base13, "triaged_tip": edit13, "triaged_base_tip": base13, "review_edits": entry13}
                fake = Fake([{**issues13[0], "metadata": m13}, issues13[1]])
                code, output, errors = invoke(["cr", "refresh", "ed13", "--review-holds"], fake, "lead0001")
                if code or "the review holds" not in output:
                    raise ValueError(f"a reviewed range holding a recorded edit commit must keep its review: {code} {output} {errors}")
                # A moved base refuses a checked edit (the stored pair would name a base the branch is not on); the plain commit still works.
                issues7, tip7, wt7 = make_cr("ed7", "e7.txt", "e\n")
                commit(repo_root, "base-moves.txt", "b\n", "main moves under ed7")
                tree7 = review_tree("ed7", tip7)
                Path(tree7, "e7.txt").write_text("changed\n", encoding="utf-8")
                code, _, errors, fake = edits("ed7", tree7, tip7, "--commit", "-m", "Fix", "--no-gate", "docs", issues=issues7)
                if code != 1 or "its base moved" not in errors or git("rev-parse", "HEAD", cwd=wt7) != tip7 or fake.writes():
                    raise ValueError(f"a gate on a branch behind its base must be refused before committing anything: {code} {errors} {fake.writes()}")
                # Ratification: the CR landed; the edit starts a follow-up CR forked at the landed tip, linked to the ratification.
                issues5, tip5, wt5 = make_cr("ed5", "r.txt", "r\n")
                code, _, errors = invoke(["cr", "land", "ed5"], Fake(issues5), "lead0001")
                moved = commit(repo_root, "after.txt", "later\n", "main moves on")
                tree5 = review_tree("ed5", tip5)
                Path(tree5, "r.txt").write_text("ratified edit\n", encoding="utf-8")
                landed = {**issues5[0], "status": "closed", "metadata": {**issues5[0]["metadata"], "landing": tip5}}
                rat = {**cr_item("rat5", "ed5", "needs_ratification"), "metadata": {"ratification": "1"}}
                rows = [landed, rat, cr_issue("fx-new", "open")]
                code, output, errors, fake = edits("rat5", tree5, tip5, issues=rows)
                if code or "+ratified edit" not in output:
                    raise ValueError(f"board cr edits on a ratification must show the edits against the landed tip: {code} {errors}")
                code, _, errors, fake = edits("rat5", tree5, moved, issues=rows)
                if code != 1 or tip5[:12] not in errors or moved[:12] not in errors:
                    raise ValueError(f"a ratification edit against another tip must be refused, naming both: {code} {errors}")
                code, _, errors, fake = edits("rat5", tree5, tip5, "--commit", "-m", "Ratify fix", "--gate", "true", issues=rows)
                if code != 1 or "--gate" not in errors or fake.writes():
                    raise ValueError(f"a ratification edit takes no gate: {code} {errors}")
                # The marker's compare-and-swap fails (the tree was set to another range meanwhile): the follow-up is rolled back whole.
                real_commit5 = board.edits_commit
                def racing_commit5(*a, **k):
                    git("update-ref", "refs/worktree/console-review-end", moved, cwd=tree5)
                    return real_commit5(*a, **k)
                with patch.object(board, "edits_commit", racing_commit5):
                    code, _, errors, fake = edits("rat5", tree5, tip5, "--commit", "-m", "Ratify fix", issues=rows)
                left5 = subprocess.run(["git", "rev-parse", "-q", "--verify", "refs/heads/cr/fx-new"], cwd=repo_root, capture_output=True).returncode == 0
                if code != 1 or "meanwhile" not in errors or left5 or Path(repo_root, ".worktrees", "fx-new").exists() \
                        or not any(w[:2] == ["close", "fx-new"] for w in fake.writes()):
                    raise ValueError(f"a failed marker swap must roll the follow-up back: no branch, no worktree, the CR closed: {code} {errors} {left5} {fake.writes()}")
                git("update-ref", "refs/worktree/console-review-end", tip5, cwd=tree5)
                code, output, errors, fake = edits("rat5", tree5, tip5, "--commit", "-m", "Ratify fix", issues=rows)
                created = [w for w in fake.writes() if w[0] == "create"]
                follow = git("rev-parse", "refs/heads/cr/fx-new")
                if code or at_main() != moved or git("rev-parse", f"{follow}^") != tip5 or git("show", f"{follow}:r.txt") != "ratified edit" \
                        or len(created) != 1 or "change-request" not in created[0] or "discovered-from:rat5" not in created[0] \
                        or not Path(repo_root, ".worktrees", "fx-new").is_dir() or "base_sha=" + tip5 not in flat(fake):
                    raise ValueError(f"a ratification edit must start a follow-up CR forked at the landed tip, target untouched: {code} {errors} {fake.writes()}")
                if git("rev-parse", "refs/worktree/console-review-end", cwd=tree5) != follow:
                    raise ValueError("a ratification edit must move the review tree's marker to the follow-up's commit")
            finally:
                os.chdir(crs_cwd)
                subprocess.run(["git", "worktree", "prune"], capture_output=True)
                scratch_cr.cleanup()

    # Liveness in position: a registered process that ended is GONE; a live process or an entry without one
    # keeps the idle hint, judged by the holder's activity (a running worker's marker, else the session's own
    # activity file), else the item's update. A stopped worker (no marker) is marked only for its own session,
    # in board mine.
    ps = shutil.which("ps") or "/bin/ps"
    reaped = subprocess.Popen(["true"])
    reaped.wait()
    with tempfile.TemporaryDirectory() as state_dir, patch.dict(os.environ, session_env(state_dir)):
        own_start = " ".join(real_run([ps, "-o", "lstart=", "-p", str(os.getpid())], capture_output=True, text=True,
                                      env={**os.environ, "LC_ALL": "C", "TZ": "UTC0"}).stdout.split()) if Path(ps).exists() else ""
        holders = {"gone0001": {"pid": reaped.pid, "pid_started": "Thu Jan  1 00:00:00 2026"},
                   "live0001": {"pid": os.getpid(), "pid_started": own_start},
                   "stal0001": {"pid": os.getpid(), "pid_started": "Thu Jan  1 00:00:00 2026"},
                   "idle0001": {}, "actv0001": {}, "work0001": {"pid": os.getpid(), "pid_started": own_start},
                   "noac0001": {}}

        def touched(path, moment):
            path.touch()
            stamp = datetime.fromisoformat(shift_dates(moment)).timestamp()
            os.utime(path, (stamp, stamp))

        Path(state_dir, "0000-work0001.workers").mkdir()
        touched(Path(state_dir, "0000-work0001.workers", "11112222"), "2026-10-22T15:20:00+00:00")
        touched(Path(state_dir, "0000-work0001.workers", "33334444"), "2026-10-22T13:00:00+00:00")  # running, quiet
        touched(Path(state_dir, "0000-actv0001.active"), "2026-10-22T15:29:00+00:00")
        touched(Path(state_dir, "0000-work0001.active"), "2026-10-22T15:25:00+00:00")
        # A session without its activity file (hooks not live): a marker neither ages its worker's hold nor does a
        # missing one mark it stopped.
        Path(state_dir, "0000-noac0001.workers").mkdir()
        touched(Path(state_dir, "0000-noac0001.workers", "77778888"), "2026-10-22T13:00:00+00:00")
        # The same worker id runs in another session: markers are per session.
        Path(state_dir, "0000-live0001.workers").mkdir()
        touched(Path(state_dir, "0000-live0001.workers", "87650000"), "2026-10-22T15:20:00+00:00")
        for actor, fields in holders.items():
            Path(state_dir, f"0000-{actor}.json").write_text(json.dumps(
                {"session": f"0000-{actor}", "role": "lead", "pulls": [], "actor": actor, "tool": "claude",
                 "registered_at": shift_dates("2026-10-22T15:00:00Z"), **fields}), encoding="utf-8")
        held_task = next(issue for issue in fixture if issue["title"] == "Held task")
        holds = {"gone0001": "fx-gone", "live0001": "fx-live", "stal0001": "fx-stale", "idle0001": "fx-idle",
                 "work0001/build-87650000": "fx-ended", "work0001/build-11112222": "fx-running",
                 "work0001/build-33334444": "fx-quiet", "actv0001": "fx-active", "live0001/build-87650000": "fx-other",
                 "noac0001/build-55556666": "fx-nohook", "noac0001/build-77778888": "fx-nohook-marked",
                 "work0001/build-99990000": "fx-late", "work0001/build-99991111": "fx-upd"}
        # Item updates (every claim is one) against work0001's last own activity (15:25): a hold updated after it
        # may belong to a worker whose first tool call is still to come; one updated before it has no running
        # worker. started_at can predate the hold and is ignored.
        claims = {"fx-ended": {"updated_at": "2026-10-22T15:00:00Z"}, "fx-late": {"updated_at": "2026-10-22T15:27:00Z"},
                  "fx-upd": {"started_at": "2026-10-22T09:00:00Z", "updated_at": "2026-10-22T15:28:00Z"}}
        crowd = fixture + [{**held_task, "id": item_id, "assignee": holder, **claims.get(item_id, {})}
                           for holder, item_id in holds.items()]
        _, fresh, _ = invoke(["position"], Fake(crowd))
        _, stale, _ = invoke(["position"], Fake(crowd), now="2026-10-22T17:30:00+00:00")

        def row(text, key):
            return next(r for r in text.splitlines() if r.startswith(f"  {key} "))

        # position --json session state (R-B5): gone from the process, active/idle from the session's own or a running
        # worker's last tool call, null without activity data; idleSince only when idle.
        for now, expected in (("2026-10-22T15:30:00+00:00", {"actv0001": ("active", None), "work0001": ("active", None),
                                                             "idle0001": (None, None)}),
                              ("2026-10-22T17:30:00+00:00", {"actv0001": ("idle", shift_dates("2026-10-22T15:29:00Z")),
                                                             "work0001": ("idle", shift_dates("2026-10-22T15:25:00Z"))})):
            states = {e["actor"]: e for e in json.loads(invoke(["position", "--json"], Fake(crowd), now=now)[1])["sessions"]}
            for actor, (state, since) in expected.items():
                if (states[actor]["state"], states[actor]["idleSince"]) != (state, since):
                    raise ValueError(f"position --json state of {actor} at {now}: {states[actor]}")
            if own_start and states["gone0001"]["state"] != "gone":
                raise ValueError(f"position --json must mark a gone session: {states['gone0001']}")
            if states["work0001"]["workers"] != {"active": 1 if now.startswith("2026-10-22T15") else 0, "cap": 3}:
                raise ValueError(f"position --json workers: {states['work0001']}")

        # item -> (mark at 15:30, IDLE at 17:30)
        expected = {"fx-gone": ("GONE", False), "fx-stale": ("GONE", False), "fx-ended": ("", True),
                    "fx-live": ("", True), "fx-idle": ("", True), "fx-running": ("", True), "fx-quiet": ("IDLE", True),
                    "fx-active": ("", True), "fx-other": ("", True), "fx-nohook": ("", True),
                    "fx-nohook-marked": ("", True), "fx-late": ("", True), "fx-upd": ("", True)} if own_start else {}
        for item_id, (marker, idle_later) in expected.items():
            if not row(fresh, item_id).endswith(f"ago{' ' + marker if marker else ''}  {held_task['title']}"):
                raise ValueError(f"board position marked {item_id} wrongly (expected {marker or 'nothing'}):\n{fresh}")
            if row(stale, item_id).endswith(f"ago IDLE  {held_task['title']}") != idle_later:
                raise ValueError(f"board position idle hint on {item_id} (expected {idle_later}):\n{stale}")
        if own_start and (", active 10 min ago" not in row(fresh, "fx-running") or ", active 1 min ago" not in row(fresh, "fx-active") or "active" in row(fresh, "fx-idle")
                          or ", active 5 min ago" not in row(fresh, "fx-ended")):
            raise ValueError(f"board position activity ages:\n{fresh}")
        if own_start and ("Free fx-gone, fx-stale: board take <id> | board unclaim <id>" not in fresh
                          or not row(fresh, "live0001").endswith("  process alive")
                          or not row(fresh, "gone0001").endswith("  GONE")
                          or "  workers 1/3  " not in row(fresh, "work0001")
                          or "idle = no activity for 1 h." not in fresh):
            raise ValueError(f"board position liveness footer or session rows:\n{fresh}")
        if not own_start and "GONE" in fresh:
            raise ValueError(f"without ps, nothing is marked gone:\n{fresh}")
        if "WORKER" in fresh + stale:
            raise ValueError(f"board position judged another session's worker by its stop:\n{fresh}")

        # Start times compare in UTC whatever the zone; a dead pid is GONE without ps; any ps failure is unknown,
        # and a pid owned by another user (PermissionError) is still checked.
        live, dead = {"pid": os.getpid(), "pid_started": own_start}, {"pid": reaped.pid, "pid_started": "x"}
        with tempfile.TemporaryDirectory() as directory:
            failing = Path(directory) / "ps"
            failing.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
            failing.chmod(0o755)
            for which, kill, expected in ((None, None, ("alive", "GONE")), (str(failing), None, (None, "GONE")),
                                          (str(Path(directory) / "missing"), None, (None, "GONE")),
                                          (None, PermissionError, ("alive", "GONE"))):
                def denied(pid, signal, error=kill, real_kill=os.kill):
                    if error and pid == os.getpid():
                        raise error
                    return real_kill(pid, signal)
                board._processes.clear()
                with patch.dict(os.environ, {"TZ": "Asia/Tokyo"}), \
                        patch.object(board.shutil, "which", (lambda name, path=which: path) if which else shutil.which), \
                        patch.object(board.os, "kill", denied):
                    if own_start and (board.liveness(live), board.liveness(dead)) != expected:
                        raise ValueError(f"liveness with ps {which}, kill error {kill}: "
                                         f"{board.liveness(live), board.liveness(dead)} != {expected}")
            board._processes.clear()

        # board mine: the caller's own stopped workers only.
        for caller_actor in ("work0001", "work0001/build-11112222"):
            _, own, _ = invoke(["mine"], Fake(crowd), caller_actor)
            if not row(own, "fx-ended").endswith("ago WORKER STOPPED  " + held_task["title"]) \
                    or "WORKER STOPPED" in row(own, "fx-running") or "WORKER STOPPED" in row(own, "fx-quiet") \
                    or "WORKER STOPPED" in row(own, "fx-late") or "WORKER STOPPED" in row(own, "fx-upd") \
                    or "WORKER STOPPED = the holding worker finished its last turn (fx-ended): continue the worker, " \
                       "hand the item over, or free it (board unclaim <id>)" not in own:
                raise ValueError(f"board mine did not mark the session's stopped worker:\n{own}")
        _, other, _ = invoke(["mine"], Fake(crowd), "live0001")
        if "fx-other" not in other or "WORKER STOPPED" in other:
            raise ValueError(f"board mine marked a worker stopped in another session's list:\n{other}")
        _, unhooked, _ = invoke(["mine"], Fake(crowd), "noac0001")
        if "fx-nohook " not in unhooked or "WORKER STOPPED" in unhooked or ", active" in unhooked:
            raise ValueError(f"board mine judged workers of a session whose activity hooks are not live:\n{unhooked}")
        if ", active" in row(fresh, "fx-nohook-marked"):
            raise ValueError(f"board position aged a hold by a session without live hooks:\n{fresh}")

    # Capacity line: last, for the session itself in a dispatching role, while fewer than its cap of workers were
    # active in the last 15 min and work it pulls is claimable; a Codex session's agents thread limits lower the cap.
    with tempfile.TemporaryDirectory() as state_dir, tempfile.TemporaryDirectory() as codex_home, \
            patch.dict(os.environ, {**session_env(state_dir), "CODEX_HOME": codex_home,
                                    "AGENT_CODEX_SYSTEM_CONFIG": str(Path(codex_home, "system.toml"))}):
        # Markers carry real mtimes: judge them at the real time.
        real_now = datetime.now(timezone.utc).isoformat()
        registry = root / "bin" / "session"
        capacity_project, capacity_env = fake_board(Path(codex_home).resolve())
        Fake.project = str(capacity_project)
        for args, session, tool in ((("solo",), "0000-solo0001", "claude"), (("lead",), "0000-lead0001", "claude"),
                                    (("autopilot",), "0000-auto0001", "claude"), (("lead", "--pulls", "implement"), "0000-lead0002", "claude"),
                                    (("agent", "--pulls", "implement,review"), "0000-cdx00001", "codex"),
                                    (("agent", "--pulls", "plan,design,review"), "0000-cdx00002", "codex")):
            subprocess.run(["bash", str(registry), "activate", *args, "--workers", "6"], check=True,
                           env={**os.environ, **as_session(session, tool), **capacity_env})
        snapshot = bare_deck([issue for issue in fixture if issue.get("_type", "issue") == "issue"])

        def ready_for(kinds, skip=()):
            counts = [(kind, sum(1 for issue in snapshot.issues if snapshot.claimable(issue) == kind
                                 and issue["id"] not in skip)) for kind in kinds]
            return ", ".join(f"{kind} {count}" for kind, count in sorted((pair for pair in counts if pair[1]),
                                                                          key=lambda pair: -pair[1]))

        def capacity_of(argv, actor, issues=fixture):
            _, out, _ = invoke(argv, Fake(issues), actor, now=real_now)
            last = out.rstrip("\n").splitlines()[-1] if out.strip() else ""
            if sum(1 for text in out.splitlines() if text.startswith("capacity: ")) > 1:
                raise ValueError(f"board {argv[0]} printed more than one capacity line:\n{out}")
            return last if last.startswith("capacity: ") else None

        worker_kinds = ("design", "implement", "review")  # a solo or autopilot session's own kinds never count
        line = f"capacity: 0 of 6 workers active in the last 15 min; ready for your pulls: {ready_for(worker_kinds)} → refill (plan Dispatch)"
        for argv in (["queue"], ["mine"]):
            if capacity_of(argv, "solo0001") != line:
                raise ValueError(f"board {argv[0]} capacity line for a solo session: {capacity_of(argv, 'solo0001')!r}")
        _, mine_out, _ = invoke(["mine", "--json"], Fake(fixture), "solo0001", now=real_now)
        if "capacity" in mine_out or json.loads(mine_out)["session"] != "solo0001":
            raise ValueError(f"board mine --json printed the capacity line: {mine_out}")
        if capacity_of(["queue"], "auto0001") != line:
            raise ValueError(f"autopilot capacity line: {capacity_of(['queue'], 'auto0001')!r}")
        worker_ids = {issue["id"] for issue in snapshot.issues if snapshot.claimable(issue) in worker_kinds}
        own_only = [{**issue, "assignee": "zzzz9999"} if issue["id"] in worker_ids else issue for issue in fixture]
        if ready_for(("plan",)) == "" or capacity_of(["queue"], "solo0001", own_only) is not None:
            raise ValueError("board printed a capacity line for work only the solo session itself takes")
        if not (capacity_of(["queue"], "cdx00002") or "").endswith(
                f"ready for your pulls: {ready_for(('design', 'review'))} → refill (plan Dispatch)"):
            raise ValueError(f"an agent's capacity line counted work outside its pulls: {capacity_of(['queue'], 'cdx00002')!r}")
        if capacity_of(["queue"], "lead0002") != f"capacity: 0 of 6 workers active in the last 15 min; ready for your pulls: " \
                                                 f"{ready_for(('implement',))} → refill (plan Dispatch)":
            raise ValueError(f"a lead with pulls got no capacity line for them: {capacity_of(['queue'], 'lead0002')!r}")
        for actor in ("lead0001", "solo0001/build-1234abcd", "unregistered1"):
            if capacity_of(["queue"], actor) is not None:
                raise ValueError(f"board printed a capacity line for {actor}")
        claimable_ids = {issue["id"] for issue in snapshot.issues if snapshot.claimable(issue)}
        drained = [{**issue, "assignee": "zzzz9999"} if issue["id"] in claimable_ids else issue for issue in fixture]
        if capacity_of(["queue"], "solo0001", drained) is not None:
            raise ValueError("board printed a capacity line without ready work")
        # Active workers count against the cap; a quiet (stale) marker does not.
        workers = Path(state_dir, "0000-solo0001.workers")
        workers.mkdir()
        for index in range(5):
            Path(workers, f"{index:08x}").touch()
        stale = Path(workers, "0000beef")
        stale.touch()
        os.utime(stale, (time.time() - 16 * 60,) * 2)
        if not (capacity_of(["queue"], "solo0001") or "").startswith("capacity: 5 of 6 workers active"):
            raise ValueError(f"capacity line with 5 active workers: {capacity_of(['queue'], 'solo0001')!r}")
        stale.touch()
        if capacity_of(["queue"], "solo0001") is not None:
            raise ValueError("board printed a capacity line at the cap")
        # Codex cap: agents.max_threads or agents.max_concurrent_threads_per_session lower it, never raise it.
        config = Path(codex_home, "config.toml")
        agent = f"ready for your pulls: {ready_for(('implement', 'review'))} → refill (plan Dispatch)"
        for text, cap in (("", 6), ("[agents]\nmax_threads = 4\n", 4), ("[agents]\nmax_threads = 12\n", 6),
                          ("[agents]\nmax_threads = 5\nmax_concurrent_threads_per_session = 3\n", 3),
                          ("[agents]\nmax_threads = true\n", 6), ("not toml = = =\n", 6)):
            config.write_text(text, encoding="utf-8")
            if capacity_of(["queue"], "cdx00001") != f"capacity: 0 of {cap} workers active in the last 15 min; {agent}":
                raise ValueError(f"Codex cap from {text!r}: {capacity_of(['queue'], 'cdx00001')!r}")
        # Codex's layers: the system config, overridden per key by the user's.
        system = Path(codex_home, "system.toml")
        for system_text, user_text, cap in (
                ("[agents]\nmax_concurrent_threads_per_session = 8\n", "", 6),
                ("[agents]\nmax_concurrent_threads_per_session = 3\n", "", 3),
                ("[agents]\nmax_concurrent_threads_per_session = 3\n", "[agents]\nmax_concurrent_threads_per_session = 5\n", 5),
                ("[agents]\nmax_threads = 4\n", "[agents]\nmax_concurrent_threads_per_session = 5\n", 4),
                ("not toml = = =\n", "[agents]\nmax_threads = 2\n", 2)):
            system.write_text(system_text, encoding="utf-8")
            config.write_text(user_text, encoding="utf-8")
            if capacity_of(["queue"], "cdx00001") != f"capacity: 0 of {cap} workers active in the last 15 min; {agent}":
                raise ValueError(f"Codex cap from system {system_text!r} and user {user_text!r}: "
                                 f"{capacity_of(['queue'], 'cdx00001')!r}")
        system.unlink()
        config.write_text("[agents]\nmax_threads = 4\n", encoding="utf-8")
        if not (capacity_of(["queue"], "auto0001") or "").startswith("capacity: 0 of 6 "):
            raise ValueError("a Claude session's cap read the Codex config")
        _, positions, _ = invoke(["position"], Fake(fixture), now=real_now)
        if "  workers 0/4" not in next(text for text in positions.splitlines() if text.startswith("  cdx00001 ")) \
                or "  workers 6/6" not in next(text for text in positions.splitlines() if text.startswith("  solo0001 ")):
            raise ValueError(f"board position workers column:\n{positions}")
        # The default cap is 3; one set at registration survives a role switch and takes only a whole number.
        def registry_call(session, *args):
            return subprocess.run(["bash", str(registry), *args], capture_output=True, text=True,
                                  env={**os.environ, **as_session(session, "claude"), **capacity_env})
        registry_call("0000-dflt0001", "activate", "solo").check_returncode()
        if not (capacity_of(["queue"], "dflt0001") or "").startswith("capacity: 0 of 3 "):
            raise ValueError(f"default worker cap: {capacity_of(['queue'], 'dflt0001')!r}")
        default_workers = Path(state_dir, "0000-dflt0001.workers")
        default_workers.mkdir()
        for index in range(2):
            Path(default_workers, f"{index:08x}").touch()
        if not (capacity_of(["queue"], "dflt0001") or "").startswith("capacity: 2 of 3 "):
            raise ValueError(f"default worker cap with 2 workers: {capacity_of(['queue'], 'dflt0001')!r}")
        Path(default_workers, "0000beef").touch()
        if capacity_of(["queue"], "dflt0001") is not None:
            raise ValueError("board printed a capacity line at the default cap")
        registry_call("0000-dflt0001", "activate", "solo", "--workers", "5").check_returncode()
        registry_call("0000-dflt0001", "activate", "autopilot").check_returncode()
        if not (capacity_of(["queue"], "dflt0001") or "").startswith("capacity: 3 of 5 "):
            raise ValueError(f"a role switch lost the session's worker cap: {capacity_of(['queue'], 'dflt0001')!r}")
        registry_call("0000-none0001", "set-workers", "0000-dflt0001", "--workers", "4").check_returncode()
        if not (capacity_of(["queue"], "dflt0001") or "").startswith("capacity: 3 of 4 "):
            raise ValueError(f"set-workers from another session: {capacity_of(['queue'], 'dflt0001')!r}")
        before_set = Path(state_dir, "0000-cdx00001.json").read_text()
        registry_call("0000-dflt0001", "set-workers", "0000-cdx00001", "--workers", "6").check_returncode()
        kept = json.loads(Path(state_dir, "0000-cdx00001.json").read_text())
        if kept["tool"] != "codex" or {k: v for k, v in kept.items() if k != "worker_cap"} != {k: v for k, v in json.loads(before_set).items() if k != "worker_cap"}:
            raise ValueError(f"set-workers changed more than the count: {kept}")
        for bad in (("set-workers", "0000-dflt0001"), ("set-workers", "--workers", "4"), ("set-workers", "0000-dflt0001", "--workers", "x"),
                    ("set-workers", "0000-gone0001", "--workers", "4")):
            if registry_call("0000-dflt0001", *bad).returncode == 0:
                raise ValueError(f"session accepted {bad}")
        registry_call("0000-none0001", "set-workers", "0000-dflt0001", "--workers", "5").check_returncode()
        for bad in (("activate", "solo", "--workers"), ("activate", "solo", "--workers", "many"),
                    ("activate", "solo", "--workers", "-1"), ("activate", "solo", "--workers", "03"),
                    ("activate", "solo", "--workers", "1.5"), ("alive", "--workers", "4")):
            if registry_call("0000-dflt0001", *bad).returncode == 0:
                raise ValueError(f"session accepted {bad}")
        if not (capacity_of(["queue"], "dflt0001") or "").startswith("capacity: 3 of 5 "):
            raise ValueError("a refused workers call changed the session's worker cap")
        # Writes: the line follows them, without the items the command named or claimed (the snapshot predates them).
        held = [{**issue, "status": "in_review", "assignee": "cdx00001", "metadata": {}} if issue["id"] == "fx-ovo.c1" else issue
                for issue in fixture]
        if capacity_of(["return", "fx-ovo.c1", "done"], "cdx00001", held) != \
                f"capacity: 0 of 4 workers active in the last 15 min; ready for your pulls: {ready_for(('implement', 'review'), {'fx-ovo.c1'})} → refill (plan Dispatch)":
            raise ValueError("board return capacity line")
        fake = Fake(fixture)
        _, out, _ = invoke(["claim"], fake, "cdx00001", now=real_now)
        taken = next(args[1] for args in fake.writes() if args[0] == "update")
        if out.rstrip("\n").splitlines()[-1] != "capacity: 0 of 4 workers active in the last 15 min; " \
                f"ready for your pulls: {ready_for(('implement', 'review'), {taken})} → refill (plan Dispatch)":
            raise ValueError(f"board claim capacity line must leave out the claimed item:\n{out}")

    # The actor comes from BEADS_ACTOR, else the Codex session[/thread], else the Claude session.
    for env, expected in (({"BEADS_ACTOR": "outer123", "CODEX_SESSION_ID": "x" * 8}, "outer123"),
                          ({"CODEX_SESSION_ID": "s-1234abcd", "CODEX_THREAD_ID": "s-1234abcd"}, "1234abcd"),
                          ({"CODEX_SESSION_ID": "s-1234abcd", "CODEX_THREAD_ID": "t-5678ef01"}, "1234abcd/5678ef01"),
                          ({"CLAUDE_CODE_SESSION_ID": "c-9999aaaa"}, "9999aaaa"), ({}, None)):
        clean = {"BEADS_ACTOR": "", "CODEX_SESSION_ID": "", "CODEX_THREAD_ID": "", "CLAUDE_CODE_SESSION_ID": ""}
        with patch.dict(os.environ, {**clean, **env}):
            if board.derived_actor() != expected:
                raise ValueError(f"board derived {board.derived_actor()!r} from {env}, expected {expected!r}")

    # board bd: passthrough with the actor, exit code kept, no snapshot; a stopped server starts first,
    # except inside a Codex sandbox; agent-run starts are refused.
    with tempfile.TemporaryDirectory() as repo:
        fake_bin, calls = Path(repo) / "bin", Path(repo) / "calls"
        fake_bin.mkdir()
        (fake_bin / "bd").write_text(f'#!/bin/sh\necho "$BEADS_ACTOR $*" >> {calls}\n'
                                     'case "$*" in *"config get"*custom.board.look*) echo \'{"value": "before"}\'; exit 0;; '
                                     '*"config get"*custom.board.view*) echo \'{"value": "code"}\'; exit 0;; esac\nexit 7\n', encoding="utf-8")
        (fake_bin / "bd").chmod(0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("CODEX_", "CLAUDE_CODE_SESSION")) and k != "BEADS_ACTOR"}
        env.update(PATH=f"{fake_bin}:{env['PATH']}", CLAUDE_CODE_SESSION_ID="c-9999aaaa")

        def run_board(*args, **extra):
            calls.unlink(missing_ok=True)
            result = subprocess.run([sys.executable, str(root / "bin" / "board"), *args], cwd=repo, text=True,
                                    capture_output=True, env={**env, **extra})
            return result, calls.read_text(encoding="utf-8") if calls.exists() else ""

        result, seen = run_board("bd", "list", "--json")
        if result.returncode != 7 or seen != "9999aaaa list --json\n":
            raise ValueError(f"board bd passthrough: {result.returncode} {seen!r}")
        # A plain raw read by ids runs board show (r9-q35); JSON and the other raw modes pass; global or unknown flags keep
        # the refusal.
        for args, meant in ((("show", "x"), "show x"), (("view", "x", "y"), "show x y"), (("comments", "x"), "show x --comments")):
            result, seen = run_board("bd", *args)
            if f"board: ran board {meant}" not in result.stderr or f"{args[0]} x" in seen:
                raise ValueError(f"board bd {args} must run board {meant}: {result.returncode} {seen!r} {result.stderr!r}")
        for args in (("-C", repo, "show", "x"), ("--actor", "9999aaaa", "comments", "x"), ("show", "x", "--brief-deps")):
            result, seen = run_board("bd", *args)
            if result.returncode != 2 or seen or "use board show <ids>" not in result.stderr:
                raise ValueError(f"board bd {args} must be refused for board show: {result.returncode} {seen!r}")
        for args in (("show", "x", "--json"), ("comments", "x", "--json"), ("show", "x", "--refs"), ("show", "x", "--as-of=abc"),
                     ("show", "--current"), ("comments", "add", "x", "y"), ("show", "--help")):
            result, seen = run_board("bd", *args)
            if result.returncode != 7 or not seen.endswith(" ".join(args) + "\n"):
                raise ValueError(f"board bd {args} must pass through: {result.returncode} {seen!r}")
        for args, meant in ((("list", "--type", "question"), "list --type decision"),
                            (("create", "-t", "question", "--title", "x"), "-t decision --title x"),
                            (("list", "--type=question"), "list --type=decision"),
                            (("query", "type=question AND status=open"), "query type=decision AND status=open")):
            result, seen = run_board("bd", *args)
            if "questions are type decision; ran it with type decision" not in result.stderr or meant not in seen or "question" in seen:
                raise ValueError(f"board bd {args} must run with type decision: {result.returncode} {seen!r} {result.stderr!r}")
        # r9-q42: create, create --graph and update --type refuse a type outside board-core.md's Kinds table; `question` stays an alias.
        bad_graph, good_graph = Path(repo) / "bad-graph.json", Path(repo) / "good-graph.json"
        bad_graph.write_text(json.dumps({"nodes": [{"key": "a", "title": "a", "type": "task"}, {"key": "b", "title": "b", "type": "feature"}]}), encoding="utf-8")
        good_graph.write_text(json.dumps({"nodes": [{"key": "a", "title": "a", "type": "task"}, {"key": "b", "title": "b", "type": "decision"}]}), encoding="utf-8")
        for args in (("create", "--type", "feature", "--title", "x"), ("create", "-t=chore", "--title", "x"), ("update", "x", "--type", "molecule"),
                     ("q", "x", "-t", "feature"), ("create", "--graph", str(bad_graph)), ("create", "--graph", "/nonexistent/plan.json", "-t", "check")):
            result, seen = run_board("bd", *args)
            if result.returncode != 2 or seen or "is not a board type" not in result.stderr or "board-core.md" not in result.stderr:
                raise ValueError(f"board bd {args} must refuse a type outside the Kinds table: {result.returncode} {seen!r} {result.stderr!r}")
        result, seen = run_board("create", "--for", "ben", "-t", "feature", "x")  # review F6: create --for calls bd create itself
        if result.returncode == 0 or seen or "is not a board type" not in result.stderr:
            raise ValueError(f"board create --for must refuse a type outside the Kinds table: {result.returncode} {seen!r} {result.stderr!r}")
        for args, meant in ((("create", "--type", "task", "--title", "x"), "--type task"), (("update", "x", "--type", "design"), "--type design"),
                            (("update", "x", "-t", "question"), "-t decision"), (("create", "--graph", str(good_graph)), "--graph"),
                            (("list", "--type", "feature"), "--type feature")):  # a filter is not a creation
            result, seen = run_board("bd", *args)
            if result.returncode != 7 or meant not in seen:
                raise ValueError(f"board bd {args} must pass a Kinds type: {result.returncode} {seen!r} {result.stderr!r}")
        # r10-q50: the no-code marker is set when the item is created; an existing item is not marked later.
        for args in (("update", "x", "--set-metadata", "no_code=1"),):
            result, seen = run_board("bd", *args)
            if result.returncode != 2 or seen or "when the item is created" not in result.stderr:
                raise ValueError(f"board bd {args} must refuse marking an existing item no-code: {result.returncode} {seen!r} {result.stderr!r}")
        result, seen = run_board("bd", "create", "--title", "t", "--metadata", '{"no_code": "1"}')
        if result.returncode != 7 or "no_code" not in seen:
            raise ValueError(f"board bd create must pass the no-code marker: {result.returncode} {seen!r}")
        # r10-q52: a CR's own look or view equal to the project default is refused (update --set-metadata, create --graph nodes).
        default_graph, own_graph = Path(repo) / "default-look.json", Path(repo) / "own-look.json"
        default_graph.write_text(json.dumps({"nodes": [{"key": "a", "title": "a", "type": "change-request", "metadata": {"look": "before"}}]}), encoding="utf-8")
        own_graph.write_text(json.dumps({"nodes": [{"key": "a", "title": "a", "type": "change-request", "metadata": {"look": "after", "view": "result"}}]}), encoding="utf-8")
        for args, word in ((("update", "x", "--set-metadata", "look=before"), "look before"), (("update", "x", "--set-metadata", "view=code", "--set-metadata", "other=1"), "view code"),
                           (("create", "--graph", str(default_graph)), "look before")):
            result, seen = run_board("bd", *args)
            if result.returncode != 2 or word not in result.stderr or "project default" not in result.stderr or any(not line.endswith(("config get --json custom.board.look", "config get --json custom.board.view")) for line in seen.splitlines()):
                raise ValueError(f"board bd {args} must refuse a look or view equal to the default: {result.returncode} {seen!r} {result.stderr!r}")
        for args in (("update", "x", "--set-metadata", "look=after"), ("update", "x", "--set-metadata", "view=result"), ("create", "--graph", str(own_graph)), ("update", "x", "--set-metadata", "other=before")):
            result, seen = run_board("bd", *args)
            if result.returncode != 7 or not seen.splitlines()[-1].endswith(" ".join(args)):
                raise ValueError(f"board bd {args} must pass a look or view that overrides the default: {result.returncode} {seen!r} {result.stderr!r}")
        kinds_table = (root / "skills" / "shared" / "board-core.md").read_text(encoding="utf-8").split("### Kinds", 1)[1].split("\n\n", 2)[1]
        table_types = [name for row in kinds_table.splitlines()[2:] for name in re.findall(r"`([a-z-]+)`", row.split("|")[1])]
        if sorted(table_types) != sorted(board.ITEM_TYPES):
            raise ValueError(f"bin/board ITEM_TYPES and board-core.md's Kinds table must list the same types: {sorted(board.ITEM_TYPES)} vs {sorted(table_types)}")
        # bd edit blocks on an editor and --readonly is not for agents: the board refuses both and names the way on.
        for args, needle in ((("edit", "x"), "board bd update --title/--description/--design/--acceptance"), (("-C", repo, "edit", "x", "--title"), "bd update"),
                             (("--readonly", "list"), "without it"), (("list", "--readonly"), "without it"), (("list", "--readonly=true"), "without it")):
            result, seen = run_board("bd", *args)
            if result.returncode != 2 or seen or needle not in result.stderr or len(result.stderr.strip().splitlines()) != 1:
                raise ValueError(f"board bd {args} must be refused in one line naming the alternative: {result.returncode} {seen!r} {result.stderr!r}")
        result, seen = run_board("bd", "comments", "add", "x", "never --readonly or edit")
        if result.returncode != 7 or not seen:
            raise ValueError(f"board bd must pass a comment mentioning --readonly: {result.returncode} {seen!r}")
        upstream = Path(repo) / "upstream"
        (upstream / ".beads").mkdir(parents=True)
        (upstream / ".beads" / "metadata.json").write_text(json.dumps({"dolt_mode": "server"}), encoding="utf-8")
        result, seen = run_board("bd", "-C", str(upstream), "ready")
        if seen != f"9999aaaa dolt start\n9999aaaa -C {upstream} ready\n":
            raise ValueError(f"board bd -C did not check the upstream board's server: {seen!r}")
        (Path(repo) / ".beads").mkdir()
        (Path(repo) / ".beads" / "metadata.json").write_text(json.dumps({"dolt_mode": "server"}), encoding="utf-8")
        result, seen = run_board("bd", "ready")
        if seen != "9999aaaa dolt start\n9999aaaa ready\n":
            raise ValueError(f"board bd did not start the stopped server first: {seen!r}")
        result, seen = run_board("bd", "ready", CODEX_SANDBOX="seatbelt")
        if result.returncode != 1 or "elevated" not in result.stderr or seen:
            raise ValueError(f"board bd started a server inside the Codex sandbox: {result.stderr!r} {seen!r}")
        result, seen = run_board("bd", "dolt", "start")
        if result.returncode != 1 or seen:
            raise ValueError("board bd ran an agent's dolt start")
    os.chdir(previous_cwd)
    scratch_repo.cleanup()


def engine_verb(call: dict) -> str:
    """The board verb of a logged call, past its kind group (`ruling record` -> `record`)."""
    args = call["args"]
    return args[1] if args[0] in ("ruling", "cr") else args[0]


def engine_head(call: dict) -> list:
    """The first words of a logged call: a kind group keeps its verb and first argument."""
    args = call["args"]
    return args[:3] if args[0] in ("ruling", "cr") else args[:2]


FAKE_BOARD = r'''#!/usr/bin/env python3
import json, os, sys
config = json.load(open(os.environ["FAKE_BOARD_CONFIG"]))
args = sys.argv[1:]
stdin = "" if sys.stdin.isatty() else sys.stdin.read()
with open(config["log"], "a") as log:
    log.write(json.dumps({"args": args, "stdin": stdin, "actor": os.environ.get("BEADS_ACTOR"), "cwd": os.getcwd()}) + "\n")
if args[:1] == ["ruling"]:
    args = args[1:]  # logged whole; dispatched on the verb
def new_id(default):
    """config "newIds": the ids the next creations print, in order."""
    ids = config.get("newIds") or []
    if not ids:
        return default
    config["newIds"] = ids[1:]
    json.dump(config, open(os.environ["FAKE_BOARD_CONFIG"], "w"))
    return ids[0]
if any(" ".join(args).startswith(prefix) for prefix in config.get("fail", [])):
    print("board: simulated failure", file=sys.stderr)
    sys.exit(1)
if args[:1] == ["health"]:
    root = args[args.index("--root") + 1] if "--root" in args else None
    health = config.get("roots", {}).get(root, {"counts": {}, "items": {}, "milestones": []}) if root else config["health"]
    if not root and args[2:] == ["--items", "decided"] and "decided" not in health.get("items", {}):
        # the board's decided view, from the items (the holder is the item's assignee): what a bare release reads
        health = {**health, "items": {**health.get("items", {}), "decided": [
            {"id": i, "status": "decided", "type": row.get("issue_type"), "priority": 1, "holder": row.get("assignee") or None,
             "title": row.get("title", ""), "blockedBy": []} for i, row in config.get("items", {}).items() if row.get("status") == "decided"]}}
    if "--json" in args:
        # the real board answers every requested view, empty ones as [], and every count (config "omit", "omitItems", "omitCounts": names left out to test the engine's refusal)
        names = {"released": "toPlan", "review": "toReview", "accept": "toAccept", "user": "forUser"}
        wanted = args[args.index("--items") + 1].split(",") if "--items" in args else []
        empty = {"ready": 0, "held": 0, "waiting": 0}
        health = {**health, "items": {**{names.get(view, view): [] for view in wanted}, **health.get("items", {})},
                  "counts": {**{key: dict(empty) for key in ("questions", "decided", "toPlan", "toReview", "toAccept", "forUser")}, **health.get("counts", {})}}
        for name in [*config.get("omit", []), *config.get("omitItems", [])]:
            health["items"].pop(name, None)
        for name in [*config.get("omit", []), *config.get("omitCounts", [])]:
            health["counts"].pop(name, None)
    print(json.dumps(health))
elif args[:1] == ["position"]:
    print(json.dumps(config.get("position", {})))
elif args[:1] == ["related"]:
    hits = next((ids for word, ids in config.get("related", {}).items() if word in stdin), [])
    print(json.dumps({"terms": [], "like": [], "items": [{"id": i, **({"title": "Old ruling"} if i == "fx-old" else {})}
                                                         for i in hits], "docs": []}))
elif args[:1] == ["claim"]:
    for item in args[1:]:
        if item in config.get("held", []):
            print(f"{item}: already held by {os.environ.get('BEADS_ACTOR')}")
    sys.exit(1 if set(args[1:]) & set(config.get("refuse", [])) else 0)
elif args[:1] == ["show"]:
    # config "items": {id: {status, issue_type, title, assignee, description}}; a missing id is an open item
    fields = [args[i + 1] for i, a in enumerate(args) if a == "--field"] or ["status"]
    items = config.get("items", {})
    rows = {i: {**{"status": config.get("statuses", {}).get(i, "open")}, **items.get(i, {})} for i in args[1:args.index("--json")]}
    print(json.dumps({i: {f: row.get(f) for f in fields} for i, row in rows.items()}))
elif args[:1] in (["release"], ["supersede"]):
    # release and supersede change statuses in the config, as the board would; "fail" ids exit 1 after the writes
    items = config.setdefault("items", {})
    closes = args[args.index("--closes") + 1:] if "--closes" in args else []
    named = args[1:args.index("--closes")] if closes else args[1:]
    if args[0] == "release":
        for i in named:
            if items.get(i, {}).get("status") == "decided":
                items[i]["status"] = "released"
        for q in closes:
            q = q.split("=")[0]
            if q not in config.get("blockedOpen", []):
                items.setdefault(q, {})["status"] = "closed"
    elif "--partial" not in args:
        items.setdefault(args[1], {})["status"] = "closed"
    json.dump(config, open(os.environ["FAKE_BOARD_CONFIG"], "w"))
    bad = set(named) & set(config.get(args[0] + "Fail", [])) or set(c.split("=")[0] for c in closes) & set(config.get("blockedOpen", []))
    print(args[0] + " done")
    if bad:
        print(f"board: {args[0]} failed for {sorted(bad)}", file=sys.stderr)
        sys.exit(1)
elif args[:1] == ["check"]:
    print(json.dumps(config.get("check", {})))
elif args[:2] == ["bd", "create"]:
    item = new_id("fx-new1")
    tag = args[args.index("--external-ref") + 1] if "--external-ref" in args else None
    if tag:  # bd keeps the ref without enforcing it unique; config "tags": {ref: [ids]}
        config.setdefault("tags", {}).setdefault(tag, []).append(item)
    config["creates"] = config.get("creates", 0) + 1
    json.dump(config, open(os.environ["FAKE_BOARD_CONFIG"], "w"))
    if config["creates"] > config.get("dieAfterCreates", config["creates"]):
        print("killed after the write")  # the id never reaches the caller: its parse fails like a killed call
    else:
        print(json.dumps({"id": item}))
elif args[:2] == ["bd", "list"] and "--external-ref" in args:
    print(json.dumps([{"id": item, "created_at": "2026-11-07T00:00:00Z"} for item in config.get("tags", {}).get(args[args.index("--external-ref") + 1], [])]))
elif args[:1] == ["revise"]:
    item = new_id("fx-rev1")
    if "--external-ref" in args:
        config.setdefault("tags", {}).setdefault(args[args.index("--external-ref") + 1], []).append(item)
        json.dump(config, open(os.environ["FAKE_BOARD_CONFIG"], "w"))
    print(item)
elif args[:1] == ["record"]:
    with open(config["log"] + ".records", "a") as out:
        out.write(open(args[2]).read())
    print("recorded " + args[1])
else:
    print("[]")
'''


# The checklist a strong recommendation carries.
STRONG_CLAIMS = {"noAssumptions": "true: task-queue.ts:1080 read", "alternativesFail": "true: Drop loses data (integrity)",
                 "notPreference": "true: no value trade", "consumerWalk": "does-not-apply: internal",
                 "rulingsChallenged": "true: no released ruling touched"}
# The round's title and summary every Stage report carries.
ROUND_INFO = {"round": {"title": "Cache policy", "summary": "Which cache the service keeps, and why now."}}
# r38-q213: the dialog's Think more line says what the rerun does; the reruns carry the goal and what fell short.
THINK_MORE_LINE = "No answer yet: its checks redo it aiming for a strong recommendation, with a consumer walk and a probe, then it comes back."

CONSOLE_CONTRACT = Path("claude") / "mods" / "console" / "tests" / "engine-contract.ts"


def console_contract_states(root: Path) -> dict:
    """The real engine's `show --json` in twelve states (no round, a pre-pass, check, batch out, answered, a closed round with a release next, a release, a stopped release, a release with a revised record, a stored proposal, a compact-only proposal, an away round with a parked question), timestamps normalized:
    the console's tests parse exactly these, so a shape change on either side fails a test."""
    states = {}
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "AGENT_SESSION_STATE_DIR": tmp, "CODEX_THREAD_ID": "", "CODEX_SESSION_ID": "", "HOME": tmp}

        def run(*args, stdin=None, cwd=tmp, prepass=True):
            if args[:1] == ("step",) and isinstance(stdin, dict) and isinstance(stdin.get("checked"), list):  # keyed by question (r4-q15, q16)
                note = "; ".join(stdin["checked"])
                stdin = {**stdin, "checked": {"round": note, **{q["id"]: note for q in json.loads(run("show", "--json", cwd=cwd))["questions"]}},
                         **({"rulings": []} if stdin.get("pass") == "challenge-rulings" else {})}
            if args[:1] == ("step",) and isinstance(stdin, dict) and stdin.get("pass"):  # the model's Skill call, recorded by the console
                waiting = json.loads(run("show", "--json", cwd=cwd)).get("pending") or {}  # the run carries the pending pass's arguments
                run("pass", "--origin", "model", stdin={"command": stdin["pass"], "args": waiting.get("args", "") if waiting.get("command") == stdin["pass"] else "",
                                                       "pending": waiting.get("id") if waiting.get("command") == stdin["pass"] else None}, cwd=cwd)
            result = subprocess.run([sys.executable, "-B", str(root / "bin" / "protocol"), "--session", "0000-contract", *args],
                                    input=json.dumps(stdin) if stdin is not None else "", text=True, capture_output=True,
                                    cwd=cwd, env=env)
            if result.returncode != 0:
                raise ValueError(f"protocol {' '.join(args)}: {result.stderr}")
            if prepass and args[:2] == ("start", "round"):  # every round opens with the pre-pass: reported without a change
                return run("step", stdin={"pass": "step-back", "summary": "No change."}, cwd=cwd)
            return result.stdout

        def show(cwd=tmp):
            text = re.sub(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", "2026-01-01T00:00:00Z", run("show", "--json", cwd=cwd))
            return json.loads(re.sub(r'"at": "\d\d:\d\d"', '"at": "00:00"', text))

        states["none"] = show()
        run("start", "round", "--no-board", str(Path(tmp) / "records"), "--subject", "Cache design", stdin={"points": ["Which cache?"]}, prepass=False)
        states["prepass"] = show()
        run("step", stdin={"pass": "step-back", "summary": "The design holds.", "verdict": "Sound.", "points": [{"id": "pt1", "first": True}]})
        run("step", stdin={"classes": {"pt1": "user"}})
        run("step", stdin={"select": ["pt1"]})
        run("step", stdin={**ROUND_INFO, "questions": [{"text": "Which cache?", "title": "Cache", "header": "Cache", "for": "pt1", "problem": "Which cache.", "root": "The cause lies in the fixture; the end state is one kept option.", "cases": "Reads; writes.", "premises": "Both read the cache.", "rulings": [], "options": [
            {"label": "Keep", "description": "keep it", "for": "for it", "against": "against it"}, {"label": "Drop", "description": "drop it", "for": "for it", "against": "against it"}],
            "recommendation": "Keep", "strength": "lean", "leanBecause": {"cause": "preference", "detail": "taste", "flipsIf": "a different taste"}}]})
        states["check"] = show()
        while (view := show())["pending"] is not None:  # the path pass, the options pass, Base, the refine pair, the lean pass, challenge-rulings
                run("step", stdin={"pass": view["pending"]["command"], "updates": [], "checked": ["every question"],
                                   **({"explored": {q["id"]: "no other way" for q in view["questions"]}} if view["pending"]["args"].startswith("options") else {})})
        states["ask"] = show()
        run("answer", "--origin", "dialog", stdin={"marker": states["ask"]["batch"]["marker"], "answers": {"Which cache?": "Keep"}})
        states["answered"] = show()
        # A release run on a fake board: its records with their state, past a contained drop.
        repo, fake, config = Path(tmp) / "repo", Path(tmp) / "board", Path(tmp) / "board.json"
        (repo / ".beads").mkdir(parents=True)
        fake.write_text(FAKE_BOARD, encoding="utf-8")
        fake.chmod(0o755)
        config.write_text(json.dumps({"log": str(Path(tmp) / "calls.jsonl"), "health": {"counts": {}, "items": {}}, "items": {
            rid: {"status": "decided", "issue_type": "decision", "title": title} for rid, title in (("fx-a", "Cache store"), ("fx-b", "Cache size"))}}))
        env.update(PROTOCOL_BOARD=str(fake), FAKE_BOARD_CONFIG=str(config))
        run("abandon")
        # A board round that recorded one decision: closed, the release of its records next.
        config.write_text(json.dumps({"log": str(Path(tmp) / "calls.jsonl"), "health": {"counts": {}, "items": {"questions": [
            {"id": "fx-q", "status": "open", "type": "decision", "title": "Store?", "priority": 1, "blockedBy": []}]}}, "items": {
            **{rid: {"status": "decided", "issue_type": "decision", "title": title, **({"assignee": "contract"} if rid == "fx-a" else {})}
               for rid, title in (("fx-a", "Cache store"), ("fx-b", "Cache size"))},
            "fx-q3": {"status": "open", "issue_type": "decision", "title": "Retry backoff"}}}))
        run("start", "round", cwd=repo)
        run("step", stdin={"classes": {"fx-q": "user"}}, cwd=repo)
        run("step", stdin={"select": ["fx-q"]}, cwd=repo)
        run("step", stdin={**ROUND_INFO, "questions": [{"text": "Which store?", "title": "Store", "header": "Store", "board": "fx-q", "problem": "Which store.", "root": "The cause lies in the fixture; the end state is one kept option.", "cases": "Reads; writes.", "premises": "Both read the store.", "rulings": [], "options": [
            {"label": "Keep", "description": "keep it", "for": "for it", "against": "against it"}, {"label": "Drop", "description": "drop it", "for": "for it", "against": "against it"}],
            "recommendation": "Keep", "strength": "lean", "leanBecause": {"cause": "preference", "detail": "taste", "flipsIf": "a different taste"}}]}, cwd=repo)
        while (waiting := json.loads(run("show", "--json", cwd=repo)))["pending"] is not None:
            run("step", stdin={"pass": waiting["pending"]["command"], "updates": [], "checked": ["every question"],
                               **({"explored": {q["id"]: "no other way" for q in waiting["questions"]}} if waiting["pending"]["args"].startswith("options") else {})}, cwd=repo)
        board_round = json.loads(run("show", "--json", cwd=repo))
        run("answer", "--origin", "dialog", stdin={"marker": board_round["batch"]["marker"], "answers": {"Which store?": "Keep"}}, cwd=repo)
        run("step", stdin={"pass": "challenge-rulings", "updates": [], "checked": ["every question"]}, cwd=repo)  # after the last answer
        run("step", stdin={"records": {board_round["questions"][0]["id"]: {"rationale": "R.", "ruleOwner": "docs/x.md"}}}, cwd=repo)
        states["closed"] = show(cwd=repo)
        run("start", "release", "fx-a", "fx-b", cwd=repo)
        run("step", stdin={"records": {"fx-a": "unchanged", "fx-b": {"change": "size moved", "reach": "contained", "why": "only fx-b", "touches": "decision"}}},
            cwd=repo)
        states["release"] = show(cwd=repo)
        run("abandon", cwd=repo)
        run("start", "release", "fx-a", cwd=repo)
        run("step", stdin={"records": {"fx-a": {"change": "the store moved", "reach": "spreads"}}}, cwd=repo)
        states["stopped"] = show(cwd=repo)
        run("start", "release", "fx-a", "fx-b", cwd=repo)
        (repo / "fixed.md").write_text("## Question\nSize?\n", encoding="utf-8")
        run("step", stdin={"records": {"fx-a": "unchanged", "fx-b": {"change": "the rationale cited a wrong size", "reach": "contained",
                                                                   "why": "only fx-b", "touches": "own", "file": "fixed.md"}}}, cwd=repo)
        states["revised"] = show(cwd=repo)
        # The model's proposal for the next rounds, stored while no round is open: two rounds (the second wants a fresh context), then compact only (a proposal without rounds).
        run("abandon", cwd=repo)
        run("next", "--set", stdin={"rounds": [
            {"title": "Cache questions", "summary": "Which cache store both modules use.", "estimate": {"questions": 3, "unblocks": 8},
             "why": "same module as the context read", "fresh": False},
            {"title": "Queue retry", "summary": "How a failed queue job is retried.", "estimate": {"questions": 1, "unblocks": 5},
             "why": "highest priority left", "fresh": True, "ids": ["fx-q3"]}]}, cwd=repo)
        states["proposed"] = show(cwd=repo)
        run("next", "--set", stdin={"rounds": []}, cwd=repo)
        states["compactOnly"] = show(cwd=repo)
        # An away round (the session's role is autopilot): the question the model parked.
        subprocess.run(["bash", str(root / "bin" / "session"), "activate", "autopilot"], check=True,
                       env={**env, **as_session("0000-contract")})
        config.write_text(json.dumps({"log": str(Path(tmp) / "calls.jsonl"), "health": {"counts": {}, "items": {"questions": [
            {"id": "fx-q", "status": "open", "type": "decision", "title": "Store?", "priority": 1, "blockedBy": []}]}}, "items": {}}))
        run("start", "round", cwd=repo)
        run("step", stdin={"classes": {"fx-q": "user"}}, cwd=repo)
        run("step", stdin={"select": ["fx-q"]}, cwd=repo)
        run("step", stdin={**ROUND_INFO, "questions": [{"text": "Which store?", "title": "Store", "header": "Store", "board": "fx-q", "problem": "Which store.", "root": "The cause lies in the fixture; the end state is one kept option.", "options": [
            {"label": "Keep", "description": "keep it", "for": "for it", "against": "against it"}, {"label": "Drop", "description": "drop it", "for": "for it", "against": "against it"}],
            "recommendation": "Keep", "strength": "lean", "leanBecause": {"cause": "preference", "detail": "taste", "flipsIf": "a different taste"}}]}, cwd=repo)
        while (waiting := json.loads(run("show", "--json", cwd=repo)))["pending"] is not None:
            run("step", stdin={"pass": waiting["pending"]["command"], "updates": [], "checked": ["every question"],
                               **({"explored": {q["id"]: "no other way" for q in waiting["questions"]}} if waiting["pending"]["args"].startswith("options") else {})}, cwd=repo)
        run("step", stdin={"settle": {json.loads(run("show", "--json", cwd=repo))["questions"][0]["id"]: "park"}}, cwd=repo)
        states["parked"] = show(cwd=repo)
    return states


def validate_default_records(root: Path) -> None:
    """r15-q73: `start --no-board` without a folder keeps the records under ${XDG_DATA_HOME:-~/.local/share}/agents/decisions/<repo
    folder name of bin/scratch>, the same from a worktree; an explicit folder is used as given."""
    engine = load_engine(root / "bin")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp).resolve()
        data, state = tmp / "data", tmp / "state"
        env = {**os.environ, "AGENT_SESSION_STATE_DIR": str(tmp / "sessions"), "CODEX_THREAD_ID": "", "CODEX_SESSION_ID": "", "HOME": str(tmp / "home"),
               "XDG_DATA_HOME": str(data), "XDG_STATE_HOME": str(state)}
        repo, worktree, plain = tmp / "proj", tmp / "proj-wt", tmp / "plain"
        plain.mkdir()
        for cmd in (["init", "-q", str(repo)], ["-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x"],
                    ["-C", str(repo), "worktree", "add", "-q", "-b", "wt", str(worktree)]):
            subprocess.run(["git", *cmd], check=True, capture_output=True, env=env)
        name = str(repo).replace("/", "-")
        folder = data / "agents" / "decisions" / name
        record = "## Question\n{q}\n\n## Decision\nKeep it\n\n## Rule owner\ndocs/x.md#a\n"

        def release(*args, cwd):
            code, out, err = engine.cli.run_cli(["--session", "0000-defaultrec", "start", "release", *args], env, cwd, "")
            if code == 0:
                engine.cli.run_cli(["--session", "0000-defaultrec", "abandon"], env, cwd, "")
            return code, out, err

        # r20-q99: `protocol records` prints the folder, from the repo and a worktree, with no session and no round
        for cwd in (repo, worktree):
            code, out, err = engine.cli.run_cli(["records"], {**env, "CLAUDE_CODE_SESSION_ID": ""}, cwd, "")
            if code != 0 or out.strip() != str(folder):
                raise ValueError(f"protocol records prints the records folder in {cwd} (exit {code}, want {folder}): {out}{err}")
        code, out, err = release("--no-board", cwd=repo)
        if code == 0 or f"{folder} is no folder of records" not in err:
            raise ValueError(f"a bare --no-board names the data folder of the repo (exit {code}, want {folder}): {out}{err}")
        folder.mkdir(parents=True)
        (folder / "r1-q1.md").write_text(record.format(q="Default one?"), encoding="utf-8")
        for cwd in (repo, worktree):  # a worktree resolves to the same repository
            code, out, err = release("--no-board", cwd=cwd)
            if code != 0 or "Default one?" not in out:
                raise ValueError(f"a bare --no-board in {cwd} takes the default folder's records (exit {code}): {out}{err}")
        explicit = tmp / "explicit"
        explicit.mkdir()
        (explicit / "r2-q1.md").write_text(record.format(q="Explicit one?"), encoding="utf-8")
        code, out, err = release("--no-board", str(explicit), cwd=repo)
        if code != 0 or "Explicit one?" not in out or "Default one?" in out:
            raise ValueError(f"an explicit --no-board folder is used as given (exit {code}): {out}{err}")
        # ids before the bare option still name records; outside git the resolved folder names the repository
        code, out, err = release("q1", "--no-board", cwd=repo)
        if code != 0 or "Default one?" not in out:
            raise ValueError(f"ids before a bare --no-board name records of the default folder (exit {code}): {out}{err}")
        code, out, err = release("--no-board", cwd=plain)
        if f"{data / 'agents' / 'decisions' / str(plain).replace('/', '-')} is no folder of records" not in err:
            raise ValueError(f"outside git the default folder is named by the resolved current folder: {out}{err}")
        # A relative XDG_DATA_HOME is invalid by the XDG spec: the default under HOME is used.
        code, out, err = engine.cli.run_cli(["--session", "0000-defaultrec", "start", "release", "--no-board"], {**env, "XDG_DATA_HOME": "relative"}, repo, "")
        if f"{tmp / 'home' / '.local' / 'share' / 'agents' / 'decisions' / name} is no folder of records" not in err:
            raise ValueError(f"a relative XDG_DATA_HOME must be ignored: {out}{err}")


def validate_prepass(root: Path) -> None:
    """Every round opens with the pre-pass (decide.md Round 1): one step-back over the point set (and the --subject) before
    Collect; its report corrects the points and marks what to ask first, which Select and Stage carry on."""
    engine = load_engine(root / "bin")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        repo, fake, config = tmp / "repo", tmp / "board", tmp / "board.json"
        (repo / ".beads").mkdir(parents=True)
        fake.write_text(FAKE_BOARD, encoding="utf-8")
        fake.chmod(0o755)
        env = {**os.environ, "AGENT_SESSION_STATE_DIR": str(tmp / "state"), "CODEX_THREAD_ID": "", "CODEX_SESSION_ID": "", "HOME": str(tmp),
               "PROTOCOL_BOARD": str(fake), "FAKE_BOARD_CONFIG": str(config)}

        def call(*args, stdin=None, cwd=tmp, ok=True):
            code, out, err = engine.cli.run_cli(["--session", "0000-prepass", *args], env, cwd, json.dumps(stdin) if stdin is not None else "")
            if (code == 0) != ok:
                raise ValueError(f"protocol {' '.join(args)} exited {code} (expected {'0' if ok else 'non-zero'}): {out}{err}")
            return out if ok else err

        def view(cwd=tmp):
            return json.loads(call("show", "--json", cwd=cwd))

        def report(body, cwd=tmp, ok=True, observe=True):
            waiting = view(cwd)["pending"]
            if observe:  # the model's Skill call, recorded by the console with the pending pass's id
                call("pass", "--origin", "model", stdin={"command": "step-back", "args": waiting["args"], "pending": waiting["id"]}, cwd=cwd)
            return call("step", stdin={"pass": "step-back", "summary": "Looked.", **body}, cwd=cwd, ok=ok)

        def refused(needle, *args, stdin=None, cwd=tmp):
            err = call(*args, stdin=stdin, cwd=cwd, ok=False)
            if needle not in err:
                raise ValueError(f"protocol {' '.join(args)}: stderr lacks {needle!r}: {err}")

        # --subject: stored on the round, in the pending pass's argument and the step text; refused where it makes no sense.
        out = call("start", "round", "--no-board", str(tmp / "records"), "--subject", "Cache design", stdin={"points": ["Which cache?", "Which TTL?", "Naming?"]})
        shown = view()
        if (shown["step"], shown["subject"]) != ("prepass", "Cache design") or shown["pending"]["command"] != "step-back" \
                or not shown["pending"]["args"].startswith("goal decisions; pre-pass on Cache design"):
            raise ValueError(f"the round must open at the pre-pass on its subject: {shown}")
        for needle in ("Pre-pass", "Subject: Cache design", "re-ground it against current source", "verdict", "pt1 [pasted]: Which cache?"):
            if needle not in out:
                raise ValueError(f"the pre-pass text lacks {needle!r}:\n{out}")
        refused("the pre-pass is waiting", "step", stdin={"classes": {"pt1": "user"}})
        refused("`pass` must be step-back: the pre-pass is waiting", "step", stdin={"pass": "options", "summary": "x"})
        refused("restart needs an open round past Stage", "restart", "pt1")  # not "unknown question"
        refused("no /step-back ran", "step", stdin={"pass": "step-back", "summary": "x", "verdict": "ok"})
        waiting = view()["pending"]
        call("pass", "--origin", "model", stdin={"command": "step-back", "args": waiting["args"], "pending": waiting["id"]})
        refused("`verdict`", "step", stdin={"pass": "step-back", "summary": "Looked."})
        refused("pt9 is no pasted point", "step", stdin={"pass": "step-back", "summary": "x", "verdict": "ok", "points": [{"id": "pt9", "first": True}]})
        refused("needs a `reason`", "step", stdin={"pass": "step-back", "summary": "x", "verdict": "ok", "points": [{"id": "pt3", "drop": True}]})
        # The report corrects the set: reword, drop, add a finding that is asked first.
        out = report({"verdict": "Sound, one drift.", "points": [
            {"id": "pt1", "text": "Which cache store?"}, {"id": "pt3", "drop": True, "reason": "settled by the goal"},
            {"text": "The design's files drifted from main", "first": True}]})
        if view()["step"] != "collect" or view()["pending"] is not None or "pt4 [pasted]: The design's files drifted" not in out \
                or "Which cache store?" not in out or "Naming?" in out:
            raise ValueError(f"after the pre-pass Collect lists the corrected set:\n{out}")
        call("step", stdin={"classes": {"pt1": "user", "pt2": "user", "pt4": "user"}})
        selecting = call("show")
        rows = [row for row in selecting.splitlines() if row.startswith("- pt")]
        if [row.split()[1] for row in rows] != ["pt4", "pt1", "pt2"] or "ask first" not in rows[0] or "ask first" in rows[1]:
            raise ValueError(f"Select must lead with the ask-first point:\n{selecting}")
        staging = call("step", stdin={"select": ["pt4", "pt1"]})
        for needle in ("Cut under question-format.md", "Asked first (the pre-pass): pt4"):
            if needle not in staging:
                raise ValueError(f"the Stage text lacks {needle!r}:\n{staging}")
        call("abandon")

        # No subject: no verdict; a pasted point only can be reworded, a split is a reword plus additions.
        pasted = re.search(r"(pt\d+) \[pasted\]", call("start", "round", "--no-board", str(tmp / "records"), stdin={"points": ["A and B?"]}))[1]
        if view()["subject"] is not None or not view()["pending"]["args"].endswith("pre-pass over the round's points"):
            raise ValueError(f"a round without a subject: {view()}")
        waiting = view()["pending"]
        call("pass", "--origin", "model", stdin={"command": "step-back", "args": waiting["args"], "pending": waiting["id"]})
        refused("belongs to a round with a --subject", "step", stdin={"pass": "step-back", "summary": "x", "verdict": "ok"})
        out = call("step", stdin={"pass": "step-back", "summary": "Split.", "points": [{"id": pasted, "text": "A?"}, {"text": "B?"}]})
        if f"{pasted} [pasted]: A?" not in out or "[pasted]: B?" not in out:
            raise ValueError(f"a split is a reword plus an addition:\n{out}")
        call("abandon")

        # --subject beside --topic keeps both; the Codex path has no console to observe the run, so the report alone is accepted.
        call("start", "round", "--no-board", str(tmp / "records"), "--topic", "Cache: pick one", "--subject", "Cache design", stdin={"points": ["Which cache?"]})
        out = report({"verdict": "Sound."})
        if view()["subject"] != "Cache design" or "Topic: Cache: pick one." not in out:
            raise ValueError(f"--subject and --topic must both stay on the round:\n{out}")
        call("abandon")
        codex = {**env, "CLAUDE_CODE_SESSION_ID": "", "CODEX_SESSION_ID": "0000-codexpre", "CODEX_THREAD_ID": "0000-codexpre"}
        code, out, err = engine.cli.run_cli(["start", "round", "--no-board", str(tmp / "records"), "--subject", "Cache design"], codex, tmp,
                                            json.dumps({"points": ["Which cache?"]}))
        if code != 0 or "Run the step-back skill now with the argument `goal decisions; pre-pass on Cache design`" not in out:
            raise ValueError(f"a Codex session runs the step-back skill itself: {out}{err}")
        code, out, err = engine.cli.run_cli(["step"], codex, tmp, json.dumps({"pass": "step-back", "summary": "Looked.", "verdict": "Sound."}))
        if code != 0 or "Collect" not in out:
            raise ValueError(f"a Codex pre-pass report needs no observed run: {out}{err}")
        engine.cli.run_cli(["abandon"], codex, tmp, "")

        # Starts that make no sense.
        refused("--subject is not for --proposal", "start", "round", "--proposal", "1", "--subject", "x")
        refused("--subject names the artifact", "start", "round", "--no-board", str(tmp / "records"), "--subject", "  ")
        refused("start release takes record ids only", "start", "release", "--subject", "x")

        # A board round: the pre-pass shows the open items; an item can be marked first but not dropped or reworded.
        config.write_text(json.dumps({"log": str(tmp / "calls.jsonl"), "health": {"counts": {}, "items": {"questions": [
            {"id": f"fx-{n}", "status": "open", "type": "decision", "title": f"Item {n}?", "priority": 1, "blockedBy": []} for n in (1, 2)]}}, "items": {}}))
        out = call("start", "round", cwd=repo)
        if "- fx-1: Item 1?" not in out or "- fx-2: Item 2?" not in out or view(repo)["step"] != "prepass":
            raise ValueError(f"the pre-pass lists the open board items:\n{out}")
        waiting = view(repo)["pending"]
        call("pass", "--origin", "model", stdin={"command": "step-back", "args": waiting["args"], "pending": waiting["id"]}, cwd=repo)
        out = call("step", stdin={"pass": "step-back", "summary": "Looked."}, cwd=repo)
        if "Open items" in out and "(listed earlier)" not in out or "- fx-1: Item 1?" in out or "(listed earlier)" not in out:
            raise ValueError(f"Collect classifies the items the pre-pass printed without listing them again:\n{out}")
        call("abandon", cwd=repo)
        # Told once per compaction: a later pre-pass names the counts, and a named round shows only its ids.
        out = call("start", "round", "fx-2", cwd=repo)
        if "- fx-1: Item 1?" in out or "- fx-2: Item 2?" not in out or "(listed earlier)" not in out:
            raise ValueError(f"the pre-pass lists by the once-per-compaction rule and the named scope:\n{out}")
        call("abandon", cwd=repo)
        call("compacted", cwd=repo)
        out = call("start", "round", "fx-2", cwd=repo)
        if "Open items (2):" not in out or "Named for this round: fx-2." not in out:
            raise ValueError(f"after a compaction the pre-pass lists the open items whole again:\n{out}")
        call("abandon", cwd=repo)
        out = call("start", "round", "--topic", "Items: decide them", cwd=repo)  # told already, yet a topic round lists whole
        if "Open items (2):" not in out:
            raise ValueError(f"a topic round's pre-pass lists the open items whole every time:\n{out}")
        call("abandon", cwd=repo)
        call("start", "round", cwd=repo)
        waiting = view(repo)["pending"]
        call("pass", "--origin", "model", stdin={"command": "step-back", "args": waiting["args"], "pending": waiting["id"]}, cwd=repo)
        refused("fx-1 is a board item", "step", stdin={"pass": "step-back", "summary": "x", "points": [{"id": "fx-1", "drop": True}]}, cwd=repo)
        call("step", stdin={"pass": "step-back", "summary": "Item 2 first.", "points": [{"id": "fx-2", "first": True}]}, cwd=repo)
        call("step", stdin={"classes": {"fx-1": "user", "fx-2": "user"}}, cwd=repo)
        rows = [row for row in call("show", cwd=repo).splitlines() if row.startswith("- fx-")]
        if [row.split()[1] for row in rows] != ["fx-2", "fx-1"]:
            raise ValueError(f"a board item marked first leads Select: {rows}")


def validate_console_unblocks(root: Path) -> None:
    """What a change request unblocks and the milestone it belongs to, as the console's rows carry them."""
    loader = importlib.machinery.SourceFileLoader("board_unblocks", str(root / "bin" / "board"))
    board = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(board)

    def item(id: str, kind: str, status: str = "open", title: str = "", waits=(), parent: str | None = None) -> dict:
        deps = [{"issue_id": id, "depends_on_id": other, "type": "blocks"} for other in waits]
        if parent:
            deps.append({"issue_id": id, "depends_on_id": parent, "type": "parent-child"})
        return {"id": id, "issue_type": kind, "status": status, "title": title or id, "dependencies": deps}

    deck = board.Board([
        item("cr", "change-request", "needs_acceptance"), item("cr.d", "design", parent="cr"),
        item("t1", "task", waits=["cr"]), item("t2", "bug", waits=["t1"]), item("q", "decision", waits=["cr.d"]),
        item("t5", "spike", waits=["cr", "t1"]),                      # reached twice: counted once
        item("done", "task", "closed", waits=["cr"]),                 # closed: not waiting
        item("gate", "gate", waits=["cr"]), item("after-gate", "task", waits=["gate"]),
        item("epic", "epic", waits=["cr"]), item("after-epic", "task", waits=["epic"]),
        item("ms", "milestone", waits=["cr"]), item("after-ms", "task", waits=["ms"]),
        item("next-cr", "change-request", waits=["t2"]),              # a request waiting through work counts
        item("lone", "change-request"),
        item("m-b", "milestone", title="Second", waits=["epic", "cr.d2"]), item("m-a", "milestone", title="First", waits=["epic"]),
        item("gone", "milestone", "closed", title="Closed", waits=["lone"]),
        item("sub", "change-request", parent="epic"), item("cr2", "change-request"), item("cr2.d", "design", parent="cr2"),
        item("cr.d2", "design", parent="cr3"), item("cr3", "change-request"), item("stack", "change-request", parent="cr3"),
        item("m-c", "milestone", title="Third", waits=["cr2.d"]),
        item("epic2", "epic"), item("epic2.d", "design", parent="epic2"), item("m-d", "milestone", title="Fourth", waits=["epic2.d"]),
        item("sub2", "change-request", parent="epic2"),                # an epic is no member through its design child
        item("wt", "change-request"), item("t-wt", "task", waits=["wt"]),  # a member waits on the request: Board.in_milestone owns that
        item("m-e", "milestone", title="Fifth", waits=["t-wt"]),
        item("cr4", "change-request"), item("cr4.d", "design", "closed", parent="cr4"),  # a closed design child brings no membership
        item("m-f", "milestone", title="Sixth", waits=["cr4.d"]),
    ])
    for cr_id, wanted in (("cr", (5, 3)), ("lone", (0, 0)), ("cr2", (0, 0))):
        got = board.cr_unblocks(deck, cr_id)
        if got != wanted:
            raise ValueError(f"cr_unblocks({cr_id}) = {got}, wanted (all, direct) {wanted}")
    # t1, t2, q, t5 and next-cr are work waiting through blocks edges; the milestone, epic, gate and what waits only on them are not.
    for cr_id, wanted in (("cr", "First"), ("sub", "First"), ("cr2", "Third"), ("cr3", "Second"), ("stack", "Second"), ("lone", None), ("sub2", None),
                           ("wt", "Fifth"), ("cr4", None)):
        got = board.cr_milestone(deck, cr_id)
        if got != wanted:
            raise ValueError(f"cr_milestone({cr_id}) = {got!r}, wanted {wanted!r} (Board.in_milestone for the request, plus the design child of it or of an ancestor request; "
                             "a closed milestone does not count, several pick the lowest id)")


def validate_console_no_board(root: Path) -> None:
    """r3-q18: `board console` outside a board reports that as data (exit 0, the console's shape, empty); inside one a bd failure stays an error."""
    shape = {"noBoard", "prefix", "counts", "forYou", "items", "crs", "waitingOnYou", "queued", "ratifications", "sessions", "held"}
    with tempfile.TemporaryDirectory() as bare, tempfile.TemporaryDirectory() as bad:
        env = {k: v for k, v in os.environ.items() if k != "BEADS_DIR"}
        ran = subprocess.run([sys.executable, "-B", str(root / "bin" / "board"), "console"], cwd=bare, capture_output=True, text=True, env=env)
        found = json.loads(ran.stdout) if ran.returncode == 0 else None
        if found != {"noBoard": True, "prefix": None, "counts": None, "forYou": [], "items": [], "crs": [], "waitingOnYou": 0, "queued": 0, "ratifications": [], "sessions": [], "held": []} \
                or set(found) != shape:
            raise ValueError(f"board console without a board: exit {ran.returncode}, {ran.stdout!r}, {ran.stderr!r}")
        # A board whose bd fails keeps the failure: .beads/metadata.json exists, bd is not installed here.
        (Path(bad) / ".beads").mkdir()
        (Path(bad) / ".beads" / "metadata.json").write_text("{}", encoding="utf-8")
        stub = Path(bad) / "bin"
        stub.mkdir()
        (stub / "bd").write_text("#!/bin/sh\necho 'Error: database broken' >&2\nexit 1\n", encoding="utf-8")
        (stub / "bd").chmod(0o755)
        ran = subprocess.run([sys.executable, "-B", str(root / "bin" / "board"), "console"], cwd=bad, capture_output=True, text=True,
                             env={**env, "PATH": f"{stub}{os.pathsep}{env['PATH']}"})
        if ran.returncode == 0 or "database broken" not in ran.stderr or "noBoard" in ran.stdout:
            raise ValueError(f"board console on a board whose bd fails must keep the error: exit {ran.returncode}, {ran.stdout!r}, {ran.stderr!r}")


def validate_session_prune(root: Path) -> None:
    """r3-q17, r5-q23, q25: activate drops registrations idle for over 7 days whose process ended (or that record none),
    recording their actors in `ended`, under one registry lock, re-reading each before removal; the board shows the holds of an
    ended actor without a registration as gone, shared boards included."""
    from unittest.mock import patch
    registry = root / "bin" / "session"
    live_started = " ".join(subprocess.run(["ps", "-o", "lstart=", "-p", str(os.getpid())], capture_output=True, text=True,
                                           env={**os.environ, "LC_ALL": "C", "TZ": "UTC0"}).stdout.split())
    with tempfile.TemporaryDirectory() as state:
        env = {**os.environ, "AGENT_SESSION_STATE_DIR": state}
        for name in ("CODEX_SESSION_ID", "CODEX_THREAD_ID", "CLAUDE_CODE_SESSION_ID"):
            env.pop(name, None)

        def register(session: str, registered: str, pid: object, started: str | None) -> None:
            entry = {"session": session, "role": "solo", "pulls": [], "actor": session[-8:], "tool": "claude", "registered_at": registered,
                     "pid": pid, "pid_started": started}
            Path(state, f"{session}.json").write_text(json.dumps(entry), encoding="utf-8")

        def run(*args: str) -> subprocess.CompletedProcess:
            return subprocess.run(["bash", str(registry), *args], capture_output=True, text=True, env=env)

        old, recent = "2020-01-01T00:00:00Z", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        register("aaaa0000-gone0001", old, 2_000_000_000, "Mon Jan  1 00:00:00 2018")      # no such process
        register("aaaa0000-reus0002", old, os.getpid(), "Mon Jan 1 00:00:00 2018")          # the pid names another process
        register("aaaa0000-rcnt0003", recent, 2_000_000_000, "Mon Jan 1 00:00:00 2018")   # ended, but registered just now
        register("aaaa0000-actv0004", old, 2_000_000_000, "Mon Jan 1 00:00:00 2018")      # ended, but active just now
        Path(state, "aaaa0000-actv0004.active").touch()
        register("aaaa0000-live0005", old, os.getpid(), live_started)                       # process alive
        register("aaaa0000-cdx00006", old, None, None)                                      # no process recorded, idle: Codex's
        register("aaaa0000-cdxr0007", recent, None, None)                                   # no process recorded, registered just now
        register("aaaa0000-cdxa0008", old, None, None)                                      # no process recorded, active just now
        Path(state, "aaaa0000-cdxa0008.active").touch()
        register("aaaa0000-cdxw0009", old, None, None)                                      # no process recorded, a worker active just now
        Path(state, "aaaa0000-cdxw0009.workers").mkdir()
        Path(state, "aaaa0000-cdxw0009.workers", "w1").touch()
        env["CLAUDE_CODE_SESSION_ID"] = "bbbb0000-first001"
        listed = run("list")
        if len(listed.stdout.splitlines()) != 9 or run("ended").stdout:
            raise ValueError(f"session list is a pure read: {listed.stdout!r} {run('ended').stdout!r}")
        if run("activate", "solo").returncode != 0:
            raise ValueError("activate failed")
        kept = sorted(json.loads(row)["actor"] for row in run("list").stdout.splitlines() if json.loads(row)["actor"] != "first001")
        if kept != ["actv0004", "cdxa0008", "cdxr0007", "cdxw0009", "live0005", "rcnt0003"] \
                or sorted(run("ended").stdout.split()) != ["cdx00006", "gone0001", "reus0002"]:
            raise ValueError(f"session activate must drop the idle ended registrations only: kept {kept}, ended {run('ended').stdout!r}")
        if any(Path(state, f"aaaa0000-{name}.json").exists() for name in ("gone0001", "reus0002")):
            raise ValueError("a pruned registration's file must be removed")
        Path(state, "aaaa0000-actv0004.active").unlink()
        register("aaaa0000-gone0001", old, 2_000_000_000, "Mon Jan 1 00:00:00 2018")      # the same actor ends again: no duplicate
        env.pop("CLAUDE_CODE_SESSION_ID")
        if run("activate", "solo").returncode == 0:  # no agent session in the environment: refused before pruning
            raise ValueError("activate without a session must fail")
        env["CLAUDE_CODE_SESSION_ID"] = "bbbb0000-actv0099"
        if run("activate", "solo").returncode != 0:
            raise ValueError("activate failed")
        ended = sorted(run("ended").stdout.split())
        if ended != ["actv0004", "cdx00006", "gone0001", "reus0002"] or Path(state, "aaaa0000-gone0001.json").exists():
            raise ValueError(f"activate must prune too, one line per actor: {ended}")
        # An unreadable registration is data in `list`'s own output (no stderr warning), beside the readable ones; no second subcommand.
        Path(state, "aaaa0000-brok0010.json").write_text("{bad", encoding="utf-8")
        listed = run("list")
        rows = [json.loads(row) for row in listed.stdout.splitlines()]
        if [row for row in rows if "unreadable" in row] != [{"unreadable": str(Path(state, "aaaa0000-brok0010.json"))}] or listed.stderr \
                or sorted(row["actor"] for row in rows if "unreadable" not in row) != ["actv0099", "cdxa0008", "cdxr0007", "cdxw0009", "first001", "live0005", "rcnt0003"] \
                or run("unreadable").returncode != 2:
            raise ValueError(f"unreadable registrations as data in list: {listed.stdout[:600]!r} {listed.stderr!r}")
        Path(state, "aaaa0000-brok0010.json").unlink()
        # The registry lock is a kernel lock (lockf): a holder killed with SIGKILL frees it, a live holder's lock makes a
        # registration write wait and then go through.
        lockf = "/usr/bin/lockf"
        lock = Path(state, ".lock")

        def hold(seconds: int) -> subprocess.Popen:
            holder = subprocess.Popen([lockf, "-k", str(lock), "sleep", str(seconds)], stderr=subprocess.DEVNULL)
            for _ in range(100):
                if subprocess.run([lockf, "-k", "-t", "0", str(lock), "true"], capture_output=True).returncode == 75:
                    return holder
                time.sleep(0.05)
            raise ValueError("test holder never took the lock")

        env["CLAUDE_CODE_SESSION_ID"] = "aaaa0000-live0005"
        holder = hold(60)
        holder.kill()
        holder.wait()
        if run("set-workers", "aaaa0000-live0005", "--workers", "2").returncode != 0:
            raise ValueError("a lock whose holder was killed must be free")
        holder = hold(2)
        waiting = subprocess.Popen(["bash", str(registry), "set-workers", "aaaa0000-live0005", "--workers", "3"], env=env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.6)
        held = waiting.poll() is None and json.loads(Path(state, "aaaa0000-live0005.json").read_text(encoding="utf-8")).get("worker_cap") == 2
        waiting.communicate(timeout=20)
        holder.wait()
        if not held or waiting.returncode != 0 or json.loads(Path(state, "aaaa0000-live0005.json").read_text(encoding="utf-8")).get("worker_cap") != 3:
            raise ValueError("a registration write must wait for a live holder's lock and then go through")
        # An activity write does not wait for the lock; neither does list.
        holder = hold(5)
        quick = subprocess.run(["bash", str(registry), "session-active"], env=env, capture_output=True, text=True, timeout=3)
        listing = subprocess.run(["bash", str(registry), "list"], env=env, capture_output=True, text=True, timeout=3)
        holder.kill()
        holder.wait()
        if quick.returncode != 0 or listing.returncode != 0 or not listing.stdout:
            raise ValueError(f"session-active and list must not wait for the registry lock: {quick.stderr} {listing.stderr}")
        # list is a pure read: a prunable registration survives it (also in a read-only state dir) and goes on the next registration.
        register("aaaa0000-lstd0014", old, 2_000_000_000, "Mon Jan 1 00:00:00 2018")
        Path(state).chmod(0o555)
        try:
            readonly = subprocess.run(["bash", str(registry), "list"], env=env, capture_output=True, text=True, timeout=3)
        finally:
            Path(state).chmod(0o755)
        if readonly.returncode != 0 or readonly.stderr or "lstd0014" not in readonly.stdout or not Path(state, "aaaa0000-lstd0014.json").exists() \
                or "lstd0014" in run("ended").stdout.split():
            raise ValueError(f"list must not prune: {readonly!r}")
        run("list")
        if not Path(state, "aaaa0000-lstd0014.json").exists():
            raise ValueError("list deleted a registration")
        run("activate", "solo").check_returncode()
        if Path(state, "aaaa0000-lstd0014.json").exists() or "lstd0014" not in run("ended").stdout.split():
            raise ValueError("activate must prune the idle ended registration")
        # An unwritable state dir makes a registration write fail at once, with a message, not spin.
        Path(state).chmod(0o555)
        try:
            started = time.time()
            refused = subprocess.run(["bash", str(registry), "set-workers", "aaaa0000-live0005", "--workers", "4"], env=env,
                                     capture_output=True, text=True, timeout=5)
        finally:
            Path(state).chmod(0o755)
        if refused.returncode == 0 or time.time() - started > 3:
            raise ValueError(f"a registration write in a read-only state dir must fail at once: {refused!r}")
        # The prune judges the registrations under the lock: one that registered again while the activation waited for the lock stays.
        register("aaaa0000-back0011", old, 2_000_000_000, "Mon Jan 1 00:00:00 2018")
        holder = hold(2)
        activating = subprocess.Popen(["bash", str(registry), "activate", "solo"], env={**env, "CLAUDE_CODE_SESSION_ID": "bbbb0000-actv0099"},
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.6)
        register("aaaa0000-back0011", recent, os.getpid(), live_started)  # the session registered again while the lock was held
        activating.communicate(timeout=20)
        holder.wait()
        if activating.returncode != 0 or not Path(state, "aaaa0000-back0011.json").exists() or "back0011" in run("ended").stdout.split():
            raise ValueError("a registration rewritten before the prune took the lock must stay, and its actor stay out of ended")
        # Waiters take turns: none is inside the critical section together with another, none gives up.
        with tempfile.TemporaryDirectory() as stubs:
            real_mktemp = shutil.which("mktemp")
            Path(stubs, "mktemp").write_text(
                f'#!/bin/bash\nmkdir "$AGENT_SESSION_STATE_DIR/.crit" 2>/dev/null || echo overlap >>"$AGENT_SESSION_STATE_DIR/overlaps"\n'
                f'sleep 0.02; rmdir "$AGENT_SESSION_STATE_DIR/.crit" 2>/dev/null\nexec {real_mktemp} "$@"\n', encoding="utf-8")
            Path(stubs, "mktemp").chmod(0o755)
            racing = {**env, "PATH": f"{stubs}{os.pathsep}{env['PATH']}"}
            racers = [subprocess.Popen(["bash", str(registry), "set-workers", "aaaa0000-live0005", "--workers", str(10 + n)], env=racing,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for n in range(8)]
            results = [racer.communicate(timeout=60) + (racer.returncode,) for racer in racers]
            if any(code != 0 for _, _, code in results) or Path(state, "overlaps").exists():
                raise ValueError(f"registration writes must take turns: {results!r} overlaps={Path(state, 'overlaps').exists()}")
    # The board: a holder without a registration whose actor is ended reads gone, before the shared board's elsewhere.
    loader = importlib.machinery.SourceFileLoader("board_pruned", str(root / "bin" / "board"))
    board = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(board)
    with tempfile.TemporaryDirectory() as state:
        Path(state, "ended").write_text("ab12cd34\n0ffe0002\n", encoding="utf-8")
        task = lambda item_id, holder: {"id": item_id, "issue_type": "task", "status": "in_progress", "title": item_id, "assignee": holder,
                                         "updated_at": "2026-11-12T10:00:00Z", "dependencies": []}
        for shared in (None, object()):
            deck = board.Board([task("t-1", "ab12cd34"), task("t-2", "ab12cd34/build-1234abcd"), task("t-3", "0ffe1234")])
            with patch.dict(os.environ, {"AGENT_SESSION_STATE_DIR": state}), patch.object(board, "board_project", lambda: None), \
                    patch.object(board, "shared", shared), patch.object(board, "utcnow", lambda: datetime(2026, 11, 12, 10, 5, tzinfo=timezone.utc)):
                marks = {issue["id"]: mark for issue, _, _, _, mark in board.position_data(deck, types.SimpleNamespace(root=None))["held"]}
            if marks != {"t-1": "gone", "t-2": "gone", "t-3": "elsewhere" if shared else None}:
                raise ValueError(f"ended actors read gone ({'shared' if shared else 'unshared'} board): {marks}")


def validate_cr_rank(root: Path) -> None:
    """r5-q20, q21, q26: a change request ranks with its work unit; the accept queue and the in-work list follow the claim
    order's milestone and priority; the console counts the queued requests that wait on your answers apart."""
    loader = importlib.machinery.SourceFileLoader("board_rank", str(root / "bin" / "board"))
    board = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(board)

    def item(id: str, kind: str, status: str = "open", priority: int = 2, waits=(), parent: str | None = None, **metadata) -> dict:
        deps = [{"issue_id": id, "depends_on_id": other, "type": "blocks"} for other in waits]
        if parent:
            deps.append({"issue_id": id, "depends_on_id": parent, "type": "parent-child"})
        return {"id": id, "issue_type": kind, "status": status, "title": id, "priority": priority, "dependencies": deps,
                "created_at": "2026-10-01T00:00:00Z", "metadata": metadata}

    deck = board.Board([
        item("cr", "change-request", priority=3), item("cr.i", "task", priority=1, parent="cr"),         # its item is urgent
        item("w", "task", priority=0, waits=["cr"]),                                                      # P0 work waits on the request
        item("calm", "change-request", priority=3), item("calm.i", "task", priority=3, parent="calm"),
        item("stack", "change-request", priority=0, parent="cr"),                                        # a request under another
        item("ms", "milestone", waits=["cr.i"]), item("under", "change-request", parent="cr", priority=3),
        item("lone", "change-request", priority=3),
    ])
    unit = board.work_unit(deck, deck.by_id["cr"])
    if unit != ["cr", "cr.i"] or board.work_unit(deck, deck.by_id["w"]) != ["w"]:
        raise ValueError(f"a request's work unit is itself and its open items, any other item alone: {unit}")
    got = {name: board.effective_priority(deck, deck.by_id[name]) for name in ("cr", "calm", "stack", "lone")}
    if got["cr"] != (0, "w", False) or got["calm"] != (3, None, False) or got["lone"] != (3, None, False):
        raise ValueError(f"a request counts at the highest priority of its unit and what waits on it: {got}")
    only_item = board.Board([item("c", "change-request", priority=3), item("c.i", "task", priority=1, parent="c")])
    if board.effective_priority(only_item, only_item.by_id["c"]) != (1, "c.i", True):
        raise ValueError("an item of the unit that sets the priority is named, flagged as the unit's own")
    if board.effective_priority(deck, deck.by_id["under"])[0] != 3:
        raise ValueError("priority does not pass up or down between a request and the request it sits under")
    names = lambda *ids: [deck.by_id[i]["title"] for i in ids]
    if board.milestones_of(deck, deck.by_id["cr"]) != ["ms"] or board.milestones_of(deck, deck.by_id["under"]) != ["ms"] \
            or board.milestones_of(deck, deck.by_id["lone"]) or board.milestones_of(deck, deck.by_id["calm"]):
        raise ValueError("a request is milestone work through its items and through a request it sits under, not otherwise")
    # claim_order's milestone tier covers a request that is milestone work only through an open item or an ancestor request.
    tiers = board.Board([
        item("t", "change-request", "needs_acceptance", 3), item("t.i", "task", priority=3, parent="t"), item("tms", "milestone", waits=["t.i"]),
        item("t.sub", "change-request", "needs_acceptance", 3, parent="t"), item("plain", "change-request", "needs_acceptance", 2),
    ])
    claimed = [i["id"] for i in sorted((i for i in tiers.issues if i["issue_type"] == "change-request"), key=lambda i: board.claim_order(tiers, i))]
    if claimed != ["t", "t.sub", "plain"]:
        raise ValueError(f"claim order: a P3 request that is milestone work through an item or an ancestor beats a P2 one outside: {claimed}")
    # The queue key: base before stacked, milestone work, effective priority, waiting since; claim_order reads the same rank.
    queue = board.Board([
        item("a", "change-request", "needs_acceptance", 2, since="2026-10-02T00:00:00Z"),
        item("b", "change-request", "needs_acceptance", 1, since="2026-10-03T00:00:00Z"),
        item("c", "change-request", "needs_acceptance", 3, since="2026-10-01T00:00:00Z"), item("c.i", "task", priority=3, parent="c"),
        item("m", "milestone", waits=["c.i"]),
        item("d", "change-request", "needs_acceptance", 0, since="2026-10-04T00:00:00Z", base="e"),
        item("e", "change-request", "needs_acceptance", 3, since="2026-10-05T00:00:00Z"),
        item("f", "change-request", "needs_acceptance", 2, since="2026-10-01T12:00:00Z"),
    ])
    order = [i["id"] for i in board.accept_queue(queue)]
    if order != ["e", "d", "c", "b", "f", "a"]:
        raise ValueError(f"accept queue: P0 (a base before the request on it), then milestone work, a base before the request on it, then priority, then waiting since: {order}")
    # P0 is the claim order's first tier: a P0 request outside any milestone lists ahead of a P2 request that is milestone work.
    urgent = board.Board([
        item("p2m", "change-request", "needs_acceptance", 2, since="2026-10-01T00:00:00Z"), item("p2m.i", "task", priority=2, parent="p2m"),
        item("um", "milestone", waits=["p2m.i"]), item("p0", "change-request", "needs_acceptance", 0, since="2026-10-02T00:00:00Z"),
    ])
    if [i["id"] for i in board.accept_queue(urgent)] != ["p0", "p2m"]:
        raise ValueError(f"accept queue: a P0 request lists before milestone work: {[i['id'] for i in board.accept_queue(urgent)]}")
    if board.work_rank(queue, queue.by_id["c"]) != (True, 3) or board.work_rank(queue, queue.by_id["b"]) != (False, 1):
        raise ValueError("work_rank is (milestone work, effective priority)")
    work = board.Board([
        item("x", "change-request", "in_progress", 2, assignee="s"), item("y", "change-request", "in_review", 1),
        item("z", "change-request", "in_progress", 1, base="x", assignee="s"), item("o", "change-request", "open", 0),
    ])
    work.by_id["y"]["created_at"] = "2026-10-03T00:00:00Z"
    work.by_id["z"]["created_at"] = "2026-10-02T00:00:00Z"
    if [i["id"] for i in board.in_work_crs(work)] != ["x", "z", "y"]:  # z (P1, created first) leads, its base x before it, then y (P1, created later)
        raise ValueError(f"in-work list: a base before the request on it, then effective priority, then created: {[i['id'] for i in board.in_work_crs(work)]}")
    # Waiting on your answers: a question not yet released, on the request or an open item; a released ruling stays queued.
    waits = board.Board([
        item("open-q", "decision", "open"), item("run-q", "decision", "in_progress"), item("dec-q", "decision", "decided"),
        item("rel-q", "decision", "released"), item("task-w", "task"),
        item("c-open", "change-request", waits=["open-q"]), item("c-run", "change-request", waits=["run-q"]),
        item("c-item", "change-request"), item("c-item.i", "task", parent="c-item", waits=["dec-q"]),
        item("c-nest", "change-request"), item("c-nest.sub", "change-request", parent="c-nest", waits=["open-q"]),  # a nested request's own wait
        item("c-rel", "change-request", waits=["rel-q"]), item("c-task", "change-request", waits=["task-w"]), item("c-none", "change-request"),
    ])
    answering = sorted(i["id"] for i in board.live_crs(waits) if board.waits_on_answers(waits, i))
    if answering != ["c-item", "c-nest.sub", "c-open", "c-run"]:
        raise ValueError(f"requests waiting on a question not yet released: {answering}")
    listed, wait_count, queued = board.console_crs(waits, board.accept_queue(waits))
    if (listed, wait_count, queued) != ([], 4, 4):
        raise ValueError(f"console_crs lists none of the queued requests and counts them apart: {(listed, wait_count, queued)}")


def validate_console_contract(root: Path) -> None:
    """CONSOLE_CONTRACT holds console_contract_states; regenerate it with WRITE_CONSOLE_CONTRACT=1 after a deliberate
    engine change, then update the console's parser and tests."""
    text = "// Generated by bin/test-agent-configs.py (WRITE_CONSOLE_CONTRACT=1): the real engine's show --json.\n" \
           f"export const ENGINE_CONTRACT = {json.dumps(console_contract_states(root), indent=2, ensure_ascii=False)} as const\n"
    path = root / CONSOLE_CONTRACT
    if os.environ.get("WRITE_CONSOLE_CONTRACT") == "1":
        path.write_text(text, encoding="utf-8")
    elif not path.is_file() or path.read_text(encoding="utf-8") != text:
        raise ValueError(f"{CONSOLE_CONTRACT} differs from the engine's show --json: regenerate it with WRITE_CONSOLE_CONTRACT=1 "
                         "and update the console's parser and tests")


def lens_problems(engine: dict, step_back_md: str, ground_md: str, words_ts: str) -> list[str]:
    """The engine's lens lists against the skills' bullets (which own the names) and the console's words.ts lists."""
    def bullets(markdown: str, *headings: str) -> list[str]:
        names = []
        for heading in headings:
            section = markdown.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]
            names += re.findall(r"^- \*\*([\w-]+):\*\*", section, re.M)
        return names

    def listed(name: str) -> list[str]:
        block = words_ts.split(f"export const {name}: readonly Lens[] = [", 1)[1].split("\n]", 1)[0]
        return re.findall(r"name: '([\w-]+)'", block)

    expected = {"step-back": list(engine["step-back"]), "ground": list(engine["ground"])}
    found = {"skill step-back": bullets(step_back_md, "Where", "What"), "skill ground": bullets(ground_md, "Lenses"),
             "words.ts step-back": listed("WHERE") + listed("WHAT"), "words.ts ground": listed("GROUND")}
    return [f"{where}: {names} differs from the engine's {expected[where.split(' ', 1)[1]]}" for where, names in found.items()
            if names != expected[where.split(" ", 1)[1]]]


def check_sets_problems(engine, words_ts: str) -> list[str]:
    """The engine's path and refine sets against the console's PATH_LENSES / REFINE_LENSES (the pane's Path and Refine)."""
    def listed(name: str) -> list[str]:
        found = re.search(rf"export const {name}: readonly string\[\] = \[(.*?)\]", words_ts, re.S)
        return re.findall(r"'([\w-]+)'", found.group(1)) if found else []

    problems = [f"words.ts {name} {listed(name)} differs from the engine's {list(expected)}" for name, expected in
                (("PATH_LENSES", engine.PATH_LENSES), ("REFINE_LENSES", engine.REFINE_LENSES["step-back"])) if listed(name) != list(expected)]
    sets = [*engine.PATH_LENSES, *engine.OPTIONS_LENSES, *engine.REFINE_LENSES["step-back"]]
    if len(sets) != len(set(sets)) or not set(sets) <= set(engine.ALL_LENSES["step-back"]) \
            or tuple(engine.REFINE_LENSES["ground"]) != tuple(engine.ALL_LENSES["ground"]) \
            or not set(engine.LEAN_LENSES) <= set(engine.ALL_LENSES["ground"]):
        problems.append("the engine's path, refine and lean sets must be disjoint lenses the skills own (refine ground = every ground lens)")
    return problems


def load_engine(bin_dir: Path, name: str = "protocol_engine"):
    """bin/protocol's engine, the protocol_engine package beside it, under the module name `name` (a copied install
    loads its own copy under another) with every module imported (cli imports them all)."""
    folder = bin_dir / "protocol_engine"
    loaded = sys.modules.get(name)
    if loaded is not None and list(loaded.__path__) == [str(folder)]:
        return loaded
    spec = importlib.util.spec_from_file_location(name, folder / "__init__.py", submodule_search_locations=[str(folder)])
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    sys.dont_write_bytecode = True  # as bin/protocol: the engine runs from the git tree, no __pycache__ beside it
    spec.loader.exec_module(package)
    importlib.import_module(f"{name}.cli")
    return package


def validate_engine_counts(root: Path) -> None:
    """r21-q141, q146: the board line prints each count's ready number and `(k wait)`; r21-q143: after the last answer the
    challenge re-derives only the strong marks of questions still unanswered."""
    engine = load_engine(root / "bin")
    words, check, boards = sys.modules[f"{engine.__name__}.words"], sys.modules[f"{engine.__name__}.check"], sys.modules[f"{engine.__name__}.boards"]
    if boards.COUNT_KEYS != ("questions", "decided", "toPlan", "toReview", "toAccept", "forUser"):
        raise ValueError(f"the engine reads the counts keys of r21-q141/q146: {boards.COUNT_KEYS}")
    counts = {key: {"ready": n, "waiting": 0} for n, key in enumerate(boards.COUNT_KEYS)}
    counts["toPlan"] = {"ready": 0, "waiting": 57}
    counts["toReview"] = {"ready": 3, "held": 2, "waiting": 0}
    counts["toAccept"] = {"ready": 4, "held": 1, "waiting": 2}
    line = words.board_line(counts, True)
    if line != ("Board: 0 open questions, 1 decided awaiting release, 0 released to plan (57 wait), 3 to review (2 held), "
                "4 to accept (1 held, 2 wait), 5 waiting on the user."):
        raise ValueError(f"board line from the {{ready, held, waiting}} counts: {line}")
    if words.board_line(None, True) != "No board counts." or words.board_line(None, False) != "":
        raise ValueError("board line without counts")

    def ctx(kind):
        questions = [{"id": "q1", "strength": "strong", "status": "answered"}, {"id": "q2", "strength": "strong", "status": "asked"},
                     {"id": "q3", "strength": "lean", "status": "asked"}]
        return types.SimpleNamespace(round={"questions": questions, "check": {"challenge": {"kind": kind, "ids": ["q1", "q2", "q3"]}}})
    ids = ["q1", "q2", "q3"]
    if check.strong_ids(ctx("answers"), ids) != ["q2"]:
        raise ValueError(f"after the last answer only unanswered strong questions need a verdict: {check.strong_ids(ctx('answers'), ids)}")
    if check.strong_ids(ctx("raised"), ids) != ["q1", "q2"]:
        raise ValueError("a raised-strong challenge keeps every strong verdict")
    errors = check.challenge_errors(ctx("answers"), {"verdicts": {}, "rulings": []}, ids, [])
    if len(errors) != 1 or "verdicts.q2" not in errors[0]:
        raise ValueError(f"after-answers challenge errors: {errors}")


def engine_text(root: Path) -> str:
    """The engine's source, every module of bin/protocol_engine, for the checks that read it as text."""
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted((root / "bin" / "protocol_engine").glob("*.py")))


def validate_lens_names(root: Path) -> None:
    """The engine's ALL_LENSES, skills/step-back and skills/ground (the owners) and the console's words.ts list the same lenses."""
    engine = load_engine(root / "bin").base
    step_back = (root / "skills" / "step-back" / "SKILL.md").read_text(encoding="utf-8")
    ground = (root / "skills" / "ground" / "SKILL.md").read_text(encoding="utf-8")
    words = (root / "claude" / "mods" / "console" / "hooks" / "words.ts").read_text(encoding="utf-8")
    problems = lens_problems(engine.ALL_LENSES, step_back, ground, words)
    problems += check_sets_problems(engine, words)
    if problems:
        raise ValueError("lens names drifted: " + "; ".join(problems))
    if not check_sets_problems(engine, words.replace("'foundations']", "'foundation']")) \
            or not check_sets_problems(engine, words.replace("'overfit', 'mechanics']", "'overfit']")):
        raise ValueError("the path/refine drift check missed a changed set")
    # The check itself must see a mismatch in each of the three places.
    for broken in ((step_back.replace("- **overfit:**", "- **overfitted:**"), ground, words), (step_back, ground.replace("- **probe:**", "- **run:**"), words),
                   (step_back, ground, words.replace("name: 'mechanics'", "name: 'mechanic'"))):
        if not lens_problems(engine.ALL_LENSES, *broken):
            raise ValueError("the lens drift check missed a renamed lens")


def validate_strength_rules(root: Path) -> None:
    """decision-protocol.md Recommendation strength owns the criteria and lean causes the engine enforces."""
    section = (root / "skills" / "shared" / "decision-protocol.md").read_text(encoding="utf-8").split("### Recommendation strength", 1)[1]
    section = section.split("\n### ", 1)[0]
    engine = engine_text(root)
    criteria = re.findall(r"^    '(\w+)': '", engine.split("STRONG_CRITERIA = {", 1)[1].split("}", 1)[0], re.M)
    causes = re.findall(r"'(\w+)'", engine.split("LEAN_CAUSES = (", 1)[1].split(")", 1)[0])
    named = re.findall(r"`(\w+)`", section)
    if not criteria or [name for name in named if name in criteria] != criteria or not all(cause in named for cause in causes):
        raise ValueError(f"decision-protocol Recommendation strength names {named}; the engine enforces {criteria} and causes {causes}")
    flat = " ".join(section.split())
    merge = re.search(r"MERGE_TEST = \((.*?)\)  #", engine, re.S)[1]
    merge = " ".join(re.findall(r"'([^']*)'", merge))
    merge = re.sub(r"\s+", " ", merge)
    owner = " ".join((root / "skills" / "shared" / "question-format.md").read_text(encoding="utf-8").split())
    if merge not in owner:
        raise ValueError(f"question-format.md owns the merge test the engine repeats: {merge}")
    if "listed or not" not in flat or "strongest unlisted" not in flat or "listed or not" not in engine or "strongest unlisted" not in engine:
        raise ValueError("alternativesFail covers every realistic option, listed or not, and names the strongest unlisted one (engine and decision-protocol.md)")
    if "shown by a fact" not in flat or "shown by a fact" not in engine:
        raise ValueError("alternativesFail lets a simpler option fail only on a failure shown by a fact (r4-q13, engine and decision-protocol.md)")
    # r38-q213: the lean pass aims for strong (from scratch, a consumer walk, a probe); a lean still resting on values asks the
    # value question as its text. decision-protocol.md owns the rule; the engine's LEAN_JOB points to it.
    for needle in ("from scratch", "consumer", "probe", "value question", "options unchanged", "`flipsIf`"):
        if needle not in flat:
            raise ValueError(f"decision-protocol.md's lean rule says {needle!r}:\n{flat}")
    if "decision-protocol.md Recommendation strength" not in re.search(r"LEAN_JOB = (.*)\n", engine)[1]:
        raise ValueError("the engine's LEAN_JOB points to decision-protocol.md Recommendation strength")
    if "walks one real case" in flat:
        raise ValueError("the lean pass no longer offers 'stays a preference' as an equal exit")


def validate_console_programs(root: Path) -> None:
    """The console runs ~/.agents/bin programs either directly (their bin/ file must be executable) or through bash;
    its test kit has no processes, so only this check sees a missing execute bit. A bin/ file carries its installed
    name (validate_copied_install)."""
    calls = []
    for source in (root / "claude" / "mods" / "console" / "hooks").glob("*.ts*"):
        text = source.read_text(encoding="utf-8")
        calls += [(source.name, "direct", name) for name in re.findall(r"process\.run\(\[binary\([^,]+, '([\w-]+)'\)", text)]
        calls += [(source.name, "bash", name) for name in re.findall(r"process\.run\(\['bash', binary\([^,]+, '([\w-]+)'\)", text)]
    if not calls:
        raise ValueError("console: found no ~/.agents/bin calls; the pattern for validate_console_programs no longer matches")
    for file, how, name in calls:
        target = root / "bin" / name
        if not target.is_file():
            raise ValueError(f"console {file} runs ~/.agents/bin/{name}, but bin/{name} does not exist")
        if how == "direct" and not os.access(target, os.X_OK):
            raise ValueError(f"console {file} runs {name} directly, but bin/{name} is not executable: run it through bash")


def validate_engine_board_fields(root: Path) -> None:
    """`board show --field` refuses a field no shown item carries, unless it is listed (ITEM_FIELDS): the fake board accepts
    anything, so a field the engine asks for but the real board can refuse would only show on a real run."""
    engine, board = engine_text(root), (root / "bin" / "board").read_text()
    asked = set(re.findall(r"'--field',\s*'(\w+)'", engine))
    listed = set(re.findall(r"'(\w+)'", re.search(r"^TEXT_FIELDS = .*$", board, re.M).group(0))) \
        | set(re.findall(r"'(\w+)'", re.search(r"^ITEM_FIELDS = \{.*?\}", board, re.M | re.S).group(0)))
    always = {"status", "issue_type", "dependencies"}  # bd shows these on every item, unlinked ones included
    if not asked or asked - listed - always:
        raise ValueError(f"the engine asks board show for fields it can refuse: {sorted(asked - listed - always)}")


def validate_copied_install(root: Path) -> None:
    """~/.agents/bin may hold copies rather than links into this tree; the tools then find their siblings only when
    source and installed names agree."""
    with tempfile.TemporaryDirectory() as directory:
        installed = Path(directory)
        for name in ("board", "protocol", "session"):
            shutil.copy2(root / "bin" / name, installed / name)
        shutil.copytree(root / "bin" / "protocol_engine", installed / "protocol_engine", ignore=shutil.ignore_patterns("__pycache__"))
        loader = importlib.machinery.SourceFileLoader("copied_board", str(installed / "board"))
        board = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(board)
        engine = load_engine(installed, "copied_protocol_engine").base
        for name, siblings in (("board", [board.REGISTRY]), ("protocol", [engine.REGISTRY, engine.BOARD])):
            missing = [path.name for path in siblings if not path.is_file()]
            if missing:
                raise ValueError(f"a copied {name} looks for siblings {missing} that a copied install lacks")
        # The entry imports the package beside its own file, not one on the caller's path, and writes no bytecode.
        ran = subprocess.run([sys.executable, str(installed / "protocol"), "--help"], capture_output=True, text=True)
        if ran.returncode != 0 or not ran.stdout.startswith("usage: protocol"):
            raise ValueError(f"a copied protocol does not run: {ran.stderr.strip()}")
        if any(installed.rglob("__pycache__")):
            raise ValueError("a copied protocol left __pycache__ in the install")


def validate_console_lenses(root: Path) -> None:
    """The console pane's lens buttons follow the lens lists the step-back and ground skills own."""
    words = (root / "claude" / "mods" / "console" / "hooks" / "words.ts").read_text(encoding="utf-8")

    def pane(*lists: str) -> list[str]:
        names = []
        for name in lists:
            body = re.search(rf"export const {name}: readonly Lens\[\] = \[(.*?)\n\]", words, re.S)
            if body is None:
                raise ValueError(f"console words.ts lacks the {name} lens list")
            names += re.findall(r"\{ name: '([a-z-]+)'", body.group(1))
        return names

    def skill(name: str) -> list[str]:
        return re.findall(r"^- \*\*([a-z-]+):\*\*", (root / "skills" / name / "SKILL.md").read_text(encoding="utf-8"), re.M)

    for lists, name in ((("WHERE", "WHAT"), "step-back"), (("GROUND",), "ground")):
        if not skill(name) or pane(*lists) != skill(name):
            raise ValueError(f"console lenses {pane(*lists)} differ from the {name} skill's {skill(name)}")


PROTOCOL_PARTS = ("rounds", "release", "answers", "texts", "rules", "context", "away", "coverage")


def validate_start_round(root: Path) -> None:
    """The console's Start press runs /start-round <row>; the skill of that name starts the stored proposal's row (a bare
    command starts row 1, the recommended one) through the engine's `start round --proposal`."""
    engine = (root / "claude" / "mods" / "console" / "hooks" / "engine.ts").read_text(encoding="utf-8")
    command = re.search(r"export const START_COMMAND = '([\w-]+)'", engine)
    if command is None or not (root / "skills" / command[1] / "SKILL.md").is_file():
        raise ValueError("the console's START_COMMAND must name a skill")
    body = (root / "skills" / command[1] / "SKILL.md").read_text(encoding="utf-8").split("---", 2)[2]
    for needle in ("protocol start round --proposal", "the argument's number, else row 1"):
        if needle not in body:
            raise ValueError(f"skills/{command[1]}/SKILL.md must say {needle!r}")
    if "--proposal" not in (root / "bin" / "protocol_engine" / "cli.py").read_text(encoding="utf-8"):
        raise ValueError("the engine's start must take --proposal")


def validate_protocol(root: Path, part: str) -> None:
    """bin/protocol, the round engine, against a fake board CLI (PROTOCOL_BOARD) and once through the real board
    with a fake bd; every origin rule of the contract rulings. Each part runs its sections on a fresh fixture, in
    its own process (GROUPS), so the parts run side by side; sections within a part share state in order."""
    if part not in PROTOCOL_PARTS:
        raise SystemExit(f"unknown protocol part {part}")
    engine = root / "bin" / "protocol"
    if not os.access(engine, os.X_OK):
        raise ValueError("bin/protocol must be executable")
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        state, repo, plain = tmp / "state", tmp / "repo", tmp / "plain"
        for path in (state, repo / ".beads", plain):
            path.mkdir(parents=True)
        log, config = tmp / "board-calls.jsonl", tmp / "board.json"
        fake = tmp / "board"
        fake.write_text(FAKE_BOARD, encoding="utf-8")
        fake.chmod(0o755)
        registry = root / "bin" / "session"
        for args, session, tool in ((("lead",), "0000-lead0001", "claude"), (("solo",), "0000-cdx00001", "codex")):
            subprocess.run(["bash", str(registry), "activate", *args], check=True,
                           env={**os.environ, **session_env(str(state)), **as_session(session, tool)})
        base = {**os.environ, **session_env(str(state)), "PROTOCOL_BOARD": str(fake), "FAKE_BOARD_CONFIG": str(config),
                "BEADS_ACTOR": ""}
        counts = {"questions": {"ready": 3, "waiting": 0}, "decided": {"ready": 1, "waiting": 0}, "toPlan": {"ready": 0, "waiting": 2},
                  "toReview": {"ready": 0, "waiting": 0}, "toAccept": {"ready": 1, "waiting": 0}, "forUser": {"ready": 1, "waiting": 0}}

        def configure(**extra):
            config.write_text(json.dumps({"log": str(log), "health": {"counts": counts, "items": {}}, **extra}), encoding="utf-8")

        def calls():
            rows = [json.loads(row) for row in log.read_text(encoding="utf-8").splitlines()] if log.exists() else []
            log.unlink(missing_ok=True)
            return rows

        engine_module = load_engine(root / "bin")
        cap_cycles = engine_module.base.CHECK_CAP  # check cycles before the cap dialog
        if cap_cycles != 10:
            raise ValueError(f"the check-loop cap is 10 cycles (r2-q8): {cap_cycles}")

        def proto(*args, stdin=None, cwd=plain, session="0000-lead0001", ok=True, env=None, process=False, observe=True, explore=True, cover=True, prepass=True):
            """The engine's `run_cli` in this process; `process=True` runs the real executable (the end-to-end path).
            A Claude session's pass report needs an observed run of its pass (the model's Skill call, which the console
            records as `pass --origin model`): unless `observe=False`, a report without one is preceded by it. The options
            pass (r30-q142) also reports `explored`: unless `explore=False`, a report of the pending options pass without it gets
            the reason no other way exists, for each question the pass covers. A pass report keys `checked` by question for its
            scope (r4-q15, q16): unless `cover=False`, a `checked` list, or none beside updates, becomes a `round` note plus that note
            for every question of the round (covering any scope), and a challenge-rulings report without `rulings` gets an empty
            list and, without `verdicts`, the stored strongBecause of each strong question it does not lower or remove."""
            if cover and args[:1] == ("step",) and isinstance(stdin, dict) and "checked" not in stdin and stdin.get("updates"):
                stdin = {**stdin, "checked": ["the updated questions"]}
            if cover and args[:1] == ("step",) and isinstance(stdin, dict) and stdin.get("pass") and (isinstance(stdin.get("checked"), list) or stdin.get("pass") == "challenge-rulings"):
                saved = state / f"{session or (env or {}).get('CODEX_THREAD_ID')}.protocol" / "state.json"
                current = (json.loads(saved.read_text(encoding="utf-8")).get("round") or {}) if saved.is_file() else {}
                listed = current.get("questions") or []
                if isinstance(stdin.get("checked"), list):
                    note = "; ".join(stdin["checked"]) or "every question"
                    stdin = {**stdin, "checked": {"round": note, **{q["id"]: note for q in listed}}}
                if stdin["pass"] == "challenge-rulings":
                    lowered = {u.get("id") for u in stdin.get("updates") or [] if isinstance(u, dict) and (u.get("strength") == "lean" or u.get("remove"))}
                    stdin = {"rulings": [], "verdicts": {q["id"]: {"strongBecause": q["strongBecause"]} for q in listed
                                                         if q.get("strength") == "strong" and q["id"] not in lowered}, **stdin}
            if explore and args[:1] == ("step",) and isinstance(stdin, dict) and stdin.get("pass") == "step-back" and "explored" not in stdin:
                saved = state / f"{session or (env or {}).get('CODEX_THREAD_ID')}.protocol" / "state.json"
                current = (json.loads(saved.read_text(encoding="utf-8")).get("round") or {}) if saved.is_file() else {}
                words = ((current.get("pending") or {}).get("args") or "").split()
                if words[:1] == ["options"]:
                    ids = [w.rstrip(";") for w in itertools.takewhile(lambda w: re.fullmatch(r"q\d+;?", w), words[2:] if words[1:2] == ["on"] else [])] or [q["id"] for q in current["questions"] if q["kind"] == "decision" and q["status"] in ("draft", "held", "ready")]
                    stdin = {**stdin, "explored": {qid: "no other mechanism fits the fixture's one question" for qid in ids}}
            if observe and args[:1] == ("step",) and isinstance(stdin, dict) and stdin.get("pass") and session not in ("0000-cdx00001", "0000-cdxauto1"):
                saved = state / f"{session}.protocol" / "state.json"
                current = (json.loads(saved.read_text(encoding="utf-8")).get("round") or {}) if saved.is_file() else {}
                seen = current.get("observed") or {}
                waiting = current.get("pending") or {}
                stamp = waiting.get("id") if waiting.get("command") == stdin["pass"] else None
                if stdin["pass"] not in seen or seen[stdin["pass"]].get("pending") != stamp:  # a run left from an earlier pending pass is stale
                    # the run is the pending pass with its arguments and id, like the console's
                    args_run = waiting.get("args", "") if waiting.get("command") == stdin["pass"] else ""
                    proto("pass", "--origin", "model", stdin={"command": stdin["pass"], "args": args_run, "pending": stamp}, cwd=cwd,
                          session=session, ok=None, env=env, process=process, observe=False)
            if observe and args[:1] == ("step",) and isinstance(stdin, dict) and "records" in stdin:
                # The pass after the last answer (r13 q49) comes before Record: tests not about it run it without a change.
                saved = state / f"{session}.protocol" / "state.json"
                current = (json.loads(saved.read_text(encoding="utf-8")).get("round") or {}) if saved.is_file() else {}
                if current.get("step") == "check" and (current.get("check") or {}).get("challenge", {}).get("kind") == "answers":
                    proto("step", stdin={"pass": "challenge-rulings", "updates": [], "checked": ["the answers"]}, cwd=cwd, session=session,
                          env=env, process=process)
            argv = [*(["--session", session] if session else []), *args]
            text = json.dumps(stdin) if isinstance(stdin, dict) else (stdin or "")
            if process:
                result = subprocess.run([sys.executable, "-B", str(engine), *argv], input=text, text=True,
                                        capture_output=True, cwd=cwd, env={**base, **(env or {})})
            else:
                code, out, err = engine_module.cli.run_cli(argv, {**base, **(env or {})}, Path(cwd), text)
                result = subprocess.CompletedProcess(argv, code, out, err)
            if ok is not None and (result.returncode == 0) != ok:
                raise ValueError(f"protocol {' '.join(args)} exited {result.returncode} (expected {'0' if ok else 'non-zero'}):"
                                 f"\n{result.stdout[-1500:]}\n{result.stderr}")
            if prepass and args[:2] == ("start", "round") and result.returncode == 0 and "Pre-pass" in result.stdout:
                # Every round opens with the pre-pass: tests not about it report it without a change and go on from Collect.
                return proto("step", stdin={"pass": "step-back", "summary": "No change."}, cwd=cwd, session=session, env=env, process=process)
            return result

        def shown(**kwargs):
            return json.loads(proto("show", "--json", **kwargs).stdout)

        def refused(*args, stdin=None, needle, **kwargs):
            result = proto(*args, stdin=stdin, ok=False, **kwargs)
            if needle not in result.stderr:
                raise ValueError(f"protocol {' '.join(args)}: stderr lacks {needle!r}: {result.stderr}")

        def question(text, **extra):
            """A staged question."""
            return {"text": text, "title": text.rstrip("?"), "header": "Q", "problem": "Which one, and why now.", "root": "The cause lies in the fixture; the end state is one kept option.", "cases": "A caller who keeps it; one who drops it.", "premises": "Read in the fixture.", "rulings": [], "options": [
                {"label": "Keep", "description": "keep it", "for": "for it", "against": "against it"}, {"label": "Drop", "description": "drop it", "for": "for it", "against": "against it"}],
                "recommendation": "Keep", "strength": "lean", "leanBecause": {"cause": "preference", "detail": "taste", "flipsIf": "a different taste"}, **extra}

        def converge(**kwargs):
            """Every pending pass without changes (the path pass, a Base cycle, the refine pair, the lean pass, challenge-rulings) before the batch."""
            out = ""
            for _ in range(12):
                view = json.loads(proto("show", "--json", **kwargs).stdout)
                if view["step"] != "check" or not view["pending"] or view["batch"]:
                    break
                out = proto("step", stdin={"pass": view["pending"]["command"], "updates": [], "checked": ["every question"]}, **kwargs).stdout
            return out

        def after_answers(**kwargs):
            """The pass after the last answer (r13 q49), reported without a change: the round then stands at Record."""
            view = json.loads(proto("show", "--json", **kwargs).stdout)
            if view["step"] != "check" or (view["pending"] or {}).get("command") != "challenge-rulings":
                raise ValueError(f"the challenge after the last answer must be pending: {view}")
            proto("step", stdin={"pass": "challenge-rulings", "updates": [], "checked": ["the answers"]}, **kwargs)

        def patch_config(**changes):
            config.write_text(json.dumps({**json.loads(config.read_text(encoding="utf-8")), **changes}), encoding="utf-8")

        notes = state / "notes"
        nones = {name: "none" for name in ("revises", "answers", "premise", "assumes", "deferred", "held", "doc")}
        configure()
        session_dir = state / "0000-lead0001.protocol"
        decided = {"status": "decided", "issue_type": "decision", "assignee": "lead0001"}
        released_record = {"status": "released", "issue_type": "decision"}

        def edit_state(change):
            document = json.loads((session_dir / "state.json").read_text(encoding="utf-8"))
            change(document)
            (session_dir / "state.json").write_text(json.dumps(document), encoding="utf-8")

        def replacing(point, hits, outcomes, **cfg):
            """A one-question board round on a pasted point, up to the batch: `hits` are the board items its text resembles,
            `outcomes` the Related report (None: stop at Related). Returns the question's id."""
            configure(related={point.split()[0]: hits}, **cfg)
            out = proto("start", "round", stdin={"points": [point]}, cwd=repo).stdout
            pasted = re.search(r"(pt\d+) \[pasted\]", out).group(1)
            proto("step", stdin={"classes": {pasted: "user"}}, cwd=repo)
            proto("step", stdin={"select": [pasted]}, cwd=repo)
            proto("step", stdin={**ROUND_INFO, "questions": [question(f"{point}?", **{"for": pasted})]}, cwd=repo)
            qid = shown(cwd=repo)["questions"][0]["id"]
            if outcomes is not None:
                proto("step", stdin={"outcomes": {qid: outcomes}}, cwd=repo)
                converge(cwd=repo)
            return qid

        def answered(answer="Keep"):
            """Answers the batch out in the dialog; returns the dialog question text."""
            batch = shown(cwd=repo)["batch"]
            text = batch["questions"][0]["question"]
            proto("answer", "--origin", "dialog", stdin={"marker": batch["marker"], "answers": {text: answer}}, cwd=repo)
            return text

        def board_round(*ids):
            """A board round answering and recording the questions on `ids`; returns its id."""
            patch_config(health={"counts": counts, "items": {"questions": [
                {"id": rid, "status": "open", "type": "decision", "title": f"{rid}?", "priority": 1, "blockedBy": []} for rid in ids]}})
            proto("start", "round", cwd=repo)
            proto("step", stdin={"classes": {rid: "user" for rid in ids}}, cwd=repo)
            proto("step", stdin={"select": list(ids)}, cwd=repo)
            proto("step", stdin={**ROUND_INFO, "questions": [question(f"{rid}?", board=rid) for rid in ids]}, cwd=repo)
            converge(cwd=repo)
            batch = shown(cwd=repo)["batch"]
            proto("answer", "--origin", "dialog", stdin={"marker": batch["marker"], "answers": {q["question"]: "Keep" for q in batch["questions"]}}, cwd=repo)
            view = shown(cwd=repo)
            proto("step", stdin={"records": {q["id"]: {"rationale": "R.", "ruleOwner": "docs/x.md"} for q in view["questions"]}}, cwd=repo)
            return view["round"]

        def item_status(rid):
            return json.loads(config.read_text(encoding="utf-8"))["items"][rid]["status"]

        if part == "rounds":
            # No open round (R-B3): the null shape, `pending` null, exit 0.
            empty = shown()
            if empty != {"version": 1, "session": "0000-lead0001", "protocol": None, "round": None, "title": None, "summary": None, "subject": None,
                         "step": None, "check": None,
                         "pending": None, "questions": [], "batch": None, "counts": None, "progress": None, "log": [],
                         "records": [], "stopped": None, "next": None} \
                    or proto("pending").stdout.strip() != "null" or proto("status", "--line").stdout.strip() != "protocol: no open round":
                raise ValueError(f"protocol without a round: {empty}")
            refused("step", stdin={}, needle="no open round")

            # r22-q158: a view or count the board's health JSON lacks is named, not read as no items or a zero count.
            for key, omitted, needle in (("omitItems", "ratification", "no items view `ratification`"), ("omitItems", "toAccept", "no items view `toAccept`"),
                                         ("omitItems", "forUser", "no items view `forUser`"), ("omitCounts", "toPlan", "no count `toPlan`"),
                                         ("omitCounts", "questions", "no count `questions`")):
                patch_config(**{key: [omitted]})
                refused("start", "round", needle=needle, cwd=repo)
                if shown(cwd=repo)["round"] is not None:
                    proto("abandon", cwd=repo)
            patch_config(omitItems=["questions"])
            refused("next", needle="no items view `questions`", cwd=repo)  # the seeds read the same view
            patch_config(omitItems=[], omitCounts=[])
            calls()  # the log of these refusals

            # A: a round without a board, Claude: Collect → Record writes a file in the named folder and makes no board call.
            refused("start", "round", stdin={"points": ["Which cache?"]}, needle="name the records folder")
            out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Which cache?"]}).stdout
            if "Round r1 · Collect" not in out or "pt1 [pasted]: Which cache?" not in out:
                raise ValueError(f"protocol start: {out}")
            refused("start", "round", needle="round r1 is open")
            if "Unclassified pasted points: pt1." not in proto("show").stdout:
                raise ValueError("protocol show at Collect must list the unclassified points")
            refused("step", stdin={"classes": {}}, needle="unclassified: pt1")
            refused("step", stdin={"classes": {"pt1": "ruled"}}, needle="cites its owner")
            proto("step", stdin={"classes": {"pt1": "user"}})
            stage_text = proto("step", stdin={"select": ["pt1"]}).stdout
            # r29-q136, r30-q141: one rule for every printed part, no evidence asked of the premises, no length check on them.
            if "with evidence" in stage_text or "with its evidence" in stage_text or "what it rests on)" not in stage_text \
                    or "Printed parts say what is decided and what each option means for the person (what they would see, what it costs), each thing once, in plain words" not in stage_text \
                    or "go to the record" not in stage_text or "which only the record keeps" not in stage_text:
                raise ValueError(f"the Stage text states the printed-text rule once and asks no evidence of the premises:\n{stage_text}")
            refused("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", header="Much too long")]}, needle="over the limit of 12")
            refused("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", options=[{"label": "Only", "description": "", "for": "for it", "against": "against it"}])]},
                    needle="2-4 objects")
            refused("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", **{"for": "pt1"}), question("Which cache?")]}, needle="unique")
            refused("step", stdin={**ROUND_INFO, "questions": [question("Which cache?")]}, needle="no question covers pt1")
            refused("step", stdin={"questions": [question("Which cache?", **{"for": "pt1"})]}, needle="`round` needs a plain-words")
            refused("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", strength=None, **{"for": "pt1"})]},
                    needle="`strength` is lean or strong")
            refused("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", recommendation="Maybe", **{"for": "pt1"})]},
                    needle="`recommendation` names one option")
            refused("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", leanBecause=None, **{"for": "pt1"})]},
                    needle="a lean names its cause")
            # r27-q123: Stage requires the problem and each option's for and against; cases, premises, rulings and note are
            # optional, printed only when present; a part that is present must be well formed; `overview` is optional too.
            bare = question("Which cache?", **{"for": "pt1"})
            refused("step", stdin={**ROUND_INFO, "questions": [{k: v for k, v in bare.items() if k != "problem"}]},
                    needle="`problem` must be a non-empty string (what is decided and why now)")
            # r9-q44: Stage requires a record-only `root` (cause; end state, or "does not apply: <why>").
            refused("step", stdin={**ROUND_INFO, "questions": [{k: v for k, v in bare.items() if k != "root"}]}, needle="`root` must be a non-empty string")
            refused("step", stdin={**ROUND_INFO, "questions": [{**bare, "root": ["cause"]}]}, needle="`root` must be a non-empty string")
            for part, value, needle in (("cases", 3, "`cases` must be a string or left out"), ("premises", ["x"], "`premises` must be a string or left out"),
                                        ("note", 3, "`note` must be a string or left out"), ("rulings", "none", "`rulings`, when given, lists your own rulings")):
                refused("step", stdin={**ROUND_INFO, "questions": [{**bare, part: value}]}, needle=needle)
            refused("step", stdin={**ROUND_INFO, "questions": [{**bare, "options": [{"label": "Keep", "description": "d", "for": "f"},
                                                                                       {"label": "Drop", "description": "d", "against": " "}]}]},
                    needle="option 'Keep' needs `for` and `against`")
            refused("step", stdin={**ROUND_INFO, "questions": [{**bare, "rulings": [{"ruling": "r", "alternative": "a"}]}]}, needle="`rulings`, when given, lists your own rulings")
            refused("step", stdin={**ROUND_INFO, "questions": [{**bare, "rulings": [{"ruling": "r", "alternative": "a", "fails": "f", "evidence": "e"}]}]},
                    needle="each with ruling, why, alternative, fails, evidence")  # Stage: a ruling without its why
            refused("step", stdin={"round": {**ROUND_INFO["round"], "overview": " "}, "questions": [bare]}, needle="round `overview` is one line")
            refused("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", strength="strong", **{"for": "pt1"})]},
                    needle="strong is a claim: `strongBecause.noAssumptions`")
            refused("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", strength="strong", strongBecause={
                **STRONG_CLAIMS, "notPreference": "does-not-apply: x"}, **{"for": "pt1"})]}, needle="`strongBecause.notPreference` is \"true: …\"")
            refused("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", title="x" * 76, **{"for": "pt1"})]},
                    needle="76 characters, over the limit of 75")
            out = proto("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", premises="A premise of any length. " * 120, cases="c " * 900, **{"for": "pt1"})]}).stdout
            if len(shown(cwd=plain)["questions"][0]["text"]) < 1 or len(json.loads((state / "0000-lead0001.protocol" / "state.json").read_text())["round"]["questions"][0]["premises"]) < 3000:
                raise ValueError("printed parts have no length check")
            if (shown()["title"], shown()["summary"]) != ("Cache policy", "Which cache the service keeps, and why now."):
                raise ValueError(f"protocol show --json must carry the round title and summary: {shown()}")
            first = shown()
            if first["step"] != "check" or (first["pending"]["command"], first["pending"]["args"]) != ("step-back", "goal foundations") \
                    or first["check"]["cycle"] != 1 \
                    or first["questions"][0]["status"] != "draft" or first["questions"][0]["overlaps"] != []:
                raise ValueError(f"protocol stage → check: {first}")
            body = out.split("\n", 1)[1]
            if 'End your turn with one short line: what changed, or "No change." The console runs the next pass, not you.' not in out or "model-reported" in out \
                    or "step-back" in body.replace("report_hint", "").split("After the pass")[0] \
                    or "cycle" in out.split("After the pass")[0] or "next:" in out.splitlines()[0] or "Round r1 · Check." not in out:
                raise ValueError(f"protocol Claude check output (hand-off names no pass and no cycle, r34-q165): {out}")
            if "After the pass, report each change" not in out or '"pass": "step-back"' not in out:
                raise ValueError(f"protocol: the first pass of a round carries the report format: {out}")
            # pass: origins enforced; the pending pass stays until its report, which then counts the observed origin.
            refused("pass", "--origin", "dialog", stdin={"command": "step-back"}, needle="origin 'dialog' is not accepted")
            pending = first["pending"]["id"]
            after = json.loads(proto("pass", "--origin", "plugin", stdin={"command": "step-back", "args": "goal foundations", "pending": pending}).stdout)
            if after["pending"] != first["pending"] or after["note"] is not None:
                raise ValueError(f"protocol pass must keep the pending pass until its report: {after}")
            # A pass covers its scope (r4-q15, q16: every question on its first run); the refusal lands in the history and the pane's log.
            refused("step", stdin={"pass": "step-back", "updates": []}, needle="no `checked` entry or update for q1")
            if not any(line["text"].startswith("refused step: `checked` is an object") for line in shown()["log"]):
                raise ValueError(f"protocol log must show the refused call: {shown()['log']}")
            # An extra pass (asked for in chat) without changes leaves the sequence alone.
            proto("step", stdin={"pass": "ground", "updates": [], "checked": ["every question"]})
            if shown()["pending"]["command"] != "step-back":
                raise ValueError(f"protocol: an extra pass without changes must keep the expected pass: {shown()['pending']}")
            # The path pass first (once per round), then the options pass (r30-q142), then the Base loop.
            out = proto("step", stdin={"pass": "step-back", "updates": [], "checked": ["every question"]}).stdout
            if (shown()["pending"]["command"], shown()["pending"]["args"], shown()["check"]["cycle"]) != ("step-back", "options", 1) \
                    or 'The options pass also reports `explored`' not in out:
                raise ValueError(f"protocol: the path pass is followed by the options pass in cycle 1, with the explored format: {out}")
            # The options pass reports `explored` for every question it covers: refused without it, for an unknown question, or malformed.
            nothing = {"pass": "step-back", "updates": [], "checked": ["every question"]}
            refused("step", stdin=nothing, explore=False, needle="an options pass reports `explored`")
            refused("step", stdin={**nothing, "explored": {}}, needle="explored: no entry for q1")
            refused("step", stdin={**nothing, "explored": {"q1": "none fits", "q9": "x"}}, needle="explored: q9 is not covered by this pass")
            refused("step", stdin={**nothing, "explored": {"q1": []}}, needle="explored.q1: a non-empty list")
            refused("step", stdin={**nothing, "explored": {"q1": [{"idea": "a file", "verdict": "maybe", "why": "x"}]}}, needle="explored.q1: a non-empty list")
            refused("step", stdin={**nothing, "explored": {"q1": [{"idea": "a file", "verdict": "dropped", "why": " "}]}}, needle="explored.q1: a non-empty list")
            result = proto("step", stdin={**nothing, "explored": {"q1": [
                {"idea": "no cache at all", "verdict": "dropped", "why": "the reads need it (task-queue.ts:12)"},
                {"idea": "an owner-side cache", "verdict": "kept", "why": "the option Keep"}]}})
            if (shown()["pending"]["command"], shown()["pending"]["args"], shown()["check"]["cycle"]) != ("step-back", "", 1) \
                    or "step-back (options): no change" not in result.stdout.splitlines()[0]:
                raise ValueError(f"protocol: the options pass is followed by the Base loop in cycle 1: {result.stdout}")
            proto("step", stdin={"pass": "step-back", "updates": [], "checked": ["every question"]})
            ground_pending = shown()["pending"]["id"]
            proto("step", stdin={"pass": "ground", "updates": [], "checked": ["every question"]})
            # The Base loop converged: the refine pair (round-wide), then the lean pass (a preference lean counts), once each.
            for command, args in (("step-back", "decisions clean overfit mechanics"),
                                  ("ground", "assumptions board sources probe"), ("ground", "assumptions sources probe on q1")):
                if (shown()["pending"]["command"], shown()["pending"]["args"]) != (command, args):
                    raise ValueError(f"protocol must run {command} {args} before challenge-rulings: {shown()['pending']}")
                out = proto("step", stdin={"pass": command, "updates": [], "checked": ["every question"]}).stdout
            # Every round runs challenge-rulings last before its first batch (user, 2026-10-31).
            if shown()["pending"]["command"] != "challenge-rulings" \
                    or "After the pass" in out or "Report with `protocol step`" in out:
                raise ValueError(f"protocol must run challenge-rulings before the first batch:\n{out}")
            out = proto("step", stdin={"pass": "challenge-rulings", "updates": [], "checked": ["every question"]}).stdout
            asked = shown()
            if asked["check"]["last"] != {"step-back": {"changes": 0, "origin": "model"}, "ground": {"changes": 0, "origin": "model"},
                                          "challenge-rulings": {"changes": 0, "origin": "model"}} \
                    or asked["step"] != "ask" or asked["batch"]["marker"] != "round:r1:1" or asked["pending"] is not None \
                    or asked["batch"]["questions"] != [{"question": "Which cache?", "header": "Q", "options": [
                        {"label": "Keep (recommended, lean)", "description": "Your call: taste — keep it"}, {"label": "Drop", "description": "drop it"},
                        {"label": "Think more", "description": THINK_MORE_LINE}],
                        "multiSelect": False}]:
                raise ValueError(f"protocol ask: {asked}")
            if '"metadata"' in out or "Record an answer the user types in chat" not in out or "model-reported" in out \
                    or '"metadata": {"source": "round:r1:1"}' not in proto("show", cwd=repo).stdout:
                raise ValueError(f"protocol Claude ask output: {out}")
            # The options pass's dropped ideas print as one line each under the options; a kept idea and a stated reason print nothing.
            if "\n\n- Dropped: no cache at all - the reads need it (task-queue.ts:12)" not in asked["batch"]["notice"] \
                    or "an owner-side cache" in asked["batch"]["notice"] or asked["batch"]["notice"].count("Dropped:") != 1:
                raise ValueError(f"the dropped ideas print under the options:\n{asked['batch']['notice']}")
            # r32-q149: the Ask text tells the model to print nothing and end its turn: the console prints, opens the dialog and records.
            if "write one short line that questions are coming, nothing about their content, and end your turn" not in out or "a message tells you when you have something to do" not in out \
                    or "Ask message" in out or "Later call" in out or "the turn's last text and end the turn" not in out or '"questions"' in out:
                raise ValueError(f"the Claude Ask text ends the turn and leaves the dialog to the console:\n{out}")
            # Recovery: `show` repeats the current step's instructions; `status --line` points to it.
            if '"metadata": {"source": "round:r1:1"}' not in proto("show").stdout.split("## Next step")[1] \
                    or "`protocol show` repeats" not in proto("status", "--line").stdout:
                raise ValueError(f"protocol show must repeat the step's instructions:\n{proto('show').stdout}")
            if not (re.fullmatch(r"p\d+", pending) and re.fullmatch(r"p\d+", ground_pending)) \
                    or int(ground_pending[1:]) <= int(pending[1:]):
                raise ValueError(f"pending ids must be unique and never reused: {pending}, {ground_pending}")
            # The dialog answers with the marked label; the record names the option's own label.
            answers = {"marker": "round:r1:1", "answers": {"Which cache?": "Keep (recommended, lean)"}}
            for origin in ("composer", "bridge", "press", "plugin", "model"):
                refused("answer", "--origin", origin, stdin=answers, needle=f"origin '{origin}' is not accepted")
            refused("answer", "--origin", "model-reported", stdin=answers, needle="Codex path only")
            refused("decline", "--origin", "chat", stdin={"marker": "round:r1:1"}, needle="not accepted")
            refused("answer", "--origin", "dialog", stdin={**answers, "marker": "round:r1:9"}, needle="not the issued batch")
            refused("answer", "--origin", "dialog", stdin={"marker": "round:r1:1", "answers": {"Other?": "x"}}, needle="not a question")
            refused("step", "--origin", "dialog", stdin={}, needle="not accepted")
            proto("show", "--json", "--origin", "model")  # the model's tool stamps model on every verb but answer (R-B11)
            refused("restart", "q1", "--origin", "press", needle="not accepted")
            refused("answer", stdin=answers, needle="needs --origin")
            # No abbreviated flags, global or per verb: `--orig dialog` must not pass as a person origin.
            for spelled in (["answer", "--orig", "dialog"], ["answer", "--orig=dialog"], ["answer", "--sess", "0000-lead0001"],
                            ["--orig", "dialog", "answer"]):
                refused(*spelled, stdin=answers, needle="protocol: error:")
            result = json.loads(proto("--origin", "dialog", "answer", stdin=answers).stdout)
            if result["step"] != "check" or result["questions"][0]["answer"] != "Keep" or "· Check.\n" not in result["note"] or "after the last answer" in result["note"] \
                    or result["pending"] != {"id": result["pending"]["id"], "command": "challenge-rulings", "args": "q1"} \
                    or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", result["questions"][0]["answeredAt"] or ""):
                raise ValueError(f"protocol answer: {result}")
            if not result["echo"].startswith("Your answers:\n") or not result["echo"].endswith(": Keep (recommended)") or "1. " in result["echo"]:
                raise ValueError(f"protocol answer's line: {result['echo']!r}")
            refused("answer", "--origin", "dialog", stdin=answers, needle="no batch is out")
            # A run without the pending id (typed, other args) is an extra pass: the challenge after answers stays pending.
            proto("pass", "--origin", "press", stdin={"command": "challenge-rulings", "args": "", "pending": None})
            proto("step", stdin={"pass": "challenge-rulings", "updates": [], "checked": ["the answer"]}, observe=False)
            if shown()["step"] != "check" or (shown()["pending"]["command"], shown()["pending"]["args"]) != ("challenge-rulings", "q1"):
                raise ValueError(f"protocol: an unstamped challenge-rulings run must not settle the pending challenge: {shown()}")
            out = proto("step", stdin={"pass": "challenge-rulings", "updates": [], "checked": ["the answer"]}).stdout  # C: nothing found
            if "challenge-rulings (after answers): no change" not in out.splitlines()[0] or shown()["step"] != "record":
                raise ValueError(f"a challenge after the last answer that changes nothing goes to Record:\n{out}")
            refused("step", stdin={"records": {}}, needle="records missing for q1")
            # r9-q47: a `ruleOwner` that is not a string (a JSON list) is a usage error, not a crash.
            refused("step", stdin={"records": {"q1": {"rationale": "Simpler.", "ruleOwner": ["docs/cache.md#cache"]}}}, needle="rationale and ruleOwner, each a non-empty string")
            out = proto("step", stdin={"records": {"q1": {"rationale": "Simpler.", "ruleOwner": "docs/cache.md#cache"}}}).stdout
            record = (notes / "r1-q1.md").read_text(encoding="utf-8")
            if "## Root\nThe cause lies in the fixture; the end state is one kept option.\n" not in record:
                raise ValueError(f"a record keeps the question's root: {record}")
            if "Round r1 closed." not in out or "Board:" in out or calls() \
                    or "## Alternatives Considered\n- Drop: drop it\n\n## Decision\nKeep\n" not in record \
                    or 'User (dialog), ' not in record or "## Rule owner\ndocs/cache.md#cache" not in record:
                raise ValueError(f"protocol no-board record:\n{out}\n{record}")
            if shown()["round"] is not None or proto("pending").stdout.strip() != "null":
                raise ValueError("a closed round must show as no open round")

            # C: the check cap, its batch answers, pause/resume, decline kinds, restart.
            proto("start", "round", "--no-board", str(notes), stdin={"points": ["Cap?"]})
            proto("step", stdin={"classes": {"pt2": "user"}})
            proto("step", stdin={"select": ["pt2"]})
            proto("step", stdin={**ROUND_INFO, "questions": [question("Cap?", **{"for": "pt2"})]})

            def changing_cycles(cycles):
                for cycle in cycles:
                    proto("step", stdin={"pass": "step-back", "updates": [{"id": "q2", "premises": f"premise {cycle}"}]})
                    proto("step", stdin={"pass": "ground", "updates": [], "checked": ["every question"]})

            proto("step", stdin={"pass": "step-back", "updates": [], "checked": ["every question"]})  # the path pass
            proto("step", stdin={"pass": "step-back", "updates": [], "checked": ["every question"]})  # the options pass
            changing_cycles(range(1, cap_cycles + 1))
            capped = shown()
            if capped["check"]["cycle"] != cap_cycles or capped["pending"] is not None or capped["batch"]["marker"] != "round:r2:1" \
                    or [o["label"] for o in capped["batch"]["questions"][0]["options"]] != ["Continue", "Ask now", "Pause"]:
                raise ValueError(f"protocol cap batch: {capped}")
            # The cap decision comes from the dialog only; a chat answer goes to a question that is out or ready.
            refused("answer", "--origin", "chat", stdin={"question": "q2", "answer": "Ask now", "quote": "ask now"},
                    needle="q2 is draft, not ready or asked")
            cap_text = capped["batch"]["questions"][0]["question"]
            proto("answer", "--origin", "dialog", stdin={"marker": "round:r2:1", "answers": {cap_text: "Continue"}})
            resumed = shown()
            if resumed["check"]["cap"] != 2 * cap_cycles or resumed["check"]["cycle"] != cap_cycles + 1 or resumed["pending"]["command"] != "step-back":
                raise ValueError(f"protocol cap Continue: {resumed}")
            # A stale console action reports its drop (r3-q10): the log gets an entry; the pass's observed run goes only when it
            # is that pass's, so a newer run of the same command stays.
            waiting = resumed["pending"]
            held = state / "0000-lead0001.protocol"
            observed_runs = lambda: json.loads((held / "state.json").read_text(encoding="utf-8"))["round"]["observed"]
            proto("pass", "--origin", "plugin", stdin={"command": waiting["command"], "args": waiting["args"], "pending": waiting["id"]})
            for origin in ("dialog", "model", "composer", "press"):
                refused("dropped", "--origin", origin, stdin={"kind": "pass", "id": waiting["id"]}, needle="not accepted")
            refused("dropped", "--origin", "plugin", stdin={"kind": "dialog", "id": "x"}, needle="`kind` must be")
            refused("dropped", "--origin", "plugin", stdin={"kind": "pass"}, needle="`id`")
            refused("dropped", "--origin", "plugin", stdin={"kind": "batch", "id": "x"}, needle="`marker`")
            proto("dropped", "--origin", "plugin", stdin={"kind": "pass", "id": "an-older-pass"})
            if waiting["command"] not in observed_runs():
                raise ValueError("a dropped older pass must leave the newer observed run alone")
            proto("dropped", "--origin", "plugin", stdin={"kind": "pass", "id": waiting["id"]})
            proto("dropped", "--origin", "plugin", stdin={"kind": "batch", "marker": "round:r2:9"})
            drops = [e for e in map(json.loads, (held / "history.jsonl").read_text(encoding="utf-8").splitlines()) if e["event"] == "dropped"]
            if waiting["command"] in observed_runs() or [(d["kind"], d.get("id"), d.get("marker")) for d in drops] != [
                    ("pass", "an-older-pass", None), ("pass", waiting["id"], None), ("batch", None, "round:r2:9")]:
                raise ValueError(f"dropped: its own pass's run goes, the log carries each report: {observed_runs()} {drops}")
            # r7-q24: each /console-continue or Continue press is logged under its own event, with what it did; plugin only.
            for origin in ("dialog", "model", "composer", "press"):
                refused("nudged", "--origin", origin, stdin={"pass": waiting["id"]}, needle="not accepted")
            refused("nudged", "--origin", "plugin", stdin={"kind": "pass"}, needle="unknown key")
            refused("nudged", "--origin", "plugin", stdin={"pass": ""}, needle="`pass`")
            refused("nudged", "--origin", "plugin", stdin={"step": "record", "pass": waiting["id"]}, needle="`step` stands alone")
            before = observed_runs()
            for nudge in ({"pass": waiting["id"]}, {"batch": "round:r2:9"}, {"pass": waiting["id"], "batch": "round:r2:9"}, {"step": "record"}, {}):
                proto("nudged", "--origin", "plugin", stdin=nudge)
            nudges = [{k: v for k, v in e.items() if k in ("pass", "batch", "step")}
                      for e in map(json.loads, (held / "history.jsonl").read_text(encoding="utf-8").splitlines()) if e["event"] == "nudged"]
            if observed_runs() != before or nudges != [{"pass": waiting["id"]}, {"batch": "round:r2:9"}, {"pass": waiting["id"], "batch": "round:r2:9"}, {"step": "record"}, {}]:
                raise ValueError(f"nudged: logged with what it did, the round untouched: {nudges} {observed_runs()}")
            changing_cycles(range(cap_cycles + 1, 2 * cap_cycles + 1))
            proto("decline", "--origin", "dialog", stdin={"marker": "round:r2:2", "partial": None})
            refused("step", stdin={"pass": "step-back", "updates": [], "checked": ["every question"]}, needle="paused")
            proto("resume")
            changing_cycles(range(2 * cap_cycles + 1, 3 * cap_cycles + 1))
            third = shown()
            if third["batch"]["marker"] != "round:r2:3" or third["check"]["cap"] != 3 * cap_cycles:
                raise ValueError(f"protocol resume must extend the cap: {third}")
            proto("answer", "--origin", "dialog", stdin={"marker": "round:r2:3", "answers": {third["batch"]["questions"][0]["question"]: "Ask now"}})
            # Ask now ends the loop; challenge-rulings still runs once before the batch, and its changes do not loop.
            if shown()["pending"]["command"] != "challenge-rulings":
                raise ValueError(f"protocol cap Ask now must run challenge-rulings once: {shown()}")
            proto("step", stdin={"pass": "challenge-rulings", "updates": [{"id": "q2", "premises": "revised"}]})
            ask_now = shown()
            if ask_now["step"] != "ask" or ask_now["batch"]["questions"][0]["question"] != "Cap?":
                raise ValueError(f"protocol cap Ask now: {ask_now}")
            # A dialog that resolved itself is a decline (R-B7); a follow-up records the answers given (user, 2026-10-31).
            timed = json.loads(proto("answer", "--origin", "dialog", stdin={"marker": "round:r2:4", "answers": {"Cap?": "Keep"},
                                                                             "afkTimeoutMs": 60000}).stdout)
            if timed["questions"][0]["status"] != "ready" or timed["questions"][0]["answer"] is not None or timed["batch"] is not None:
                raise ValueError(f"protocol afkTimeoutMs must decline: {timed}")
            proto("step", stdin={})
            follow = json.loads(proto("answer", "--origin", "dialog", stdin={"marker": "round:r2:5", "answers": {"Cap?": "Keep"},
                                                                              "followUp": "why?"}).stdout)
            if follow["questions"][0]["answer"] != "Keep" or "another round of questions" not in follow["note"]:
                raise ValueError(f"protocol followUp must record the given answers and ask what to add: {follow}")
            # A restart takes the answer back with its words: a later answer's record must not quote them (r22-q88).
            saved_answer = state / "0000-lead0001.protocol" / "state.json"
            document = json.loads(saved_answer.read_text(encoding="utf-8"))
            next(q for q in document["round"]["questions"] if q["id"] == "q2").update(quote="the reversed words", annotations={"notes": "the reversed note"})
            saved_answer.write_text(json.dumps(document), encoding="utf-8")
            out = proto("restart", "q2", "--reason", "criterion: only reversible caches").stdout
            taken_back = next(q for q in json.loads(saved_answer.read_text(encoding="utf-8"))["round"]["questions"] if q["id"] == "q2")
            if "quote" in taken_back or "annotations" in taken_back:
                raise ValueError(f"a restart clears the answer's quote and note: {taken_back}")
            restarted = shown()
            if restarted["step"] != "check" or restarted["questions"][0]["status"] != "draft" or restarted["questions"][0]["answer"] \
                    or restarted["check"]["cycle"] != 1 or restarted["pending"]["command"] != "step-back":
                raise ValueError(f"protocol restart: {restarted}")
            history = proto("history").stdout
            if "0000-lead0001 r2:" not in history or "restarts q2 (criterion: only reversible caches)" not in history \
                    or "cap Continue, Ask now" not in history or "declines 2" not in history \
                    or "0000-lead0001 r1: passes model 10, plugin 1" not in history:
                raise ValueError(f"protocol history:\n{history}")
            line = proto("status", "--line").stdout.strip()
            if not line.startswith(f"protocol: round r2 · check 1/{cap_cycles} · pending /step-back (p") or "1 draft" not in line:
                raise ValueError(f"protocol status --line: {line}")
            if "| q2 | draft | draft | decision | Cap? |" not in proto("show").stdout:
                raise ValueError(f"protocol show markdown:\n{proto('show').stdout}")
            proto("abandon")

            # B: a board round: Collect from health, Select in dependency order with claims, held decisions, Related
            # outcomes, challenge-rulings before confirming own rulings, chat answers by quote, Record through the board.
            configure(health={"counts": counts, "items": {
                "questions": [{"id": "fx-a", "status": "open", "type": "decision", "title": "A?", "priority": 1, "blockedBy": []},
                              {"id": "fx-b", "status": "open", "type": "decision", "title": "B?", "priority": 0, "blockedBy": ["fx-a"]}],
                "decided": [{"id": "fx-d", "status": "decided", "type": "decision", "title": "D", "priority": 2, "blockedBy": []}]}},
                      related={"Pasted": ["fx-old", "fx-rel"]},
                      position={"readyMilestones": [{"id": "fx-m", "status": "open", "type": "milestone", "title": "Beta",
                                                     "priority": 1, "blockedBy": []}], "finishedEpics": []})
            out = proto("start", "round", stdin={"points": ["Pasted point"]}, cwd=repo, prepass=False).stdout
            first_calls = calls()
            if [c["args"] for c in first_calls] != [["health", "--json", "--items", "decided,questions,ratification,accept,review,user"],
                                                    ["position", "--json"]] \
                    or first_calls[0]["actor"] != "lead0001" or Path(first_calls[0]["cwd"]).resolve() != repo.resolve() \
                    or "decided, awaiting release · decided (1):\n- fx-d: D" not in out \
                    or out.index("- fx-d: D") > out.index("- fx-a: A?") or "ready milestones · open (1):\n- fx-m [milestone]: Beta" not in out:
                raise ValueError(f"protocol pre-pass from board health and position: {first_calls}\n{out}")
            proto("step", stdin={"pass": "step-back", "summary": "No change."}, cwd=repo)
            # Scoped (user, 2026-10-31): every pasted point needs a class; board items outside the scope stay out.
            refused("step", stdin={"classes": {"fx-a": "user"}}, needle="every pasted point needs a class; unclassified: pt3", cwd=repo)
            out = proto("step", stdin={"classes": {"fx-a": "user", "fx-b": "user", "fx-d": {"class": "ruled", "owner": "docs/d.md"},
                                                   "pt3": "user"}}, cwd=repo).stdout
            if "fx-m" in out:
                raise ValueError(f"protocol Select must leave unclassified board items out:\n{out}")
            if not out.index("- fx-a") < out.index("- fx-b") < out.index("- pt3"):
                raise ValueError(f"protocol Select must order prerequisites first:\n{out}")
            refused("step", stdin={"select": ["fx-b"]}, needle="waits on fx-a", cwd=repo)
            configure(related={"Pasted": ["fx-old", "fx-rel"]}, refuse=["fx-a"])
            refused("step", stdin={"select": ["fx-a", "fx-b", "pt3"]}, needle="`board claim fx-a fx-b` failed", cwd=repo)
            configure(related={"Pasted": ["fx-old", "fx-rel"]}, items={"fx-old": {"status": "released", "issue_type": "decision"}})
            calls()
            proto("step", stdin={"select": ["fx-a", "fx-b", "pt3"]}, cwd=repo)
            if [c["args"] for c in calls()] != [["claim", "fx-a", "fx-b"]]:
                raise ValueError("protocol Select must claim the selected board items")
            staging = shown(cwd=repo)["progress"]
            if staging["selected"] != ["fx-a", "fx-b", "pt3"] or staging["items"] != 4 or staging["points"] != 1:
                raise ValueError(f"protocol show --json progress at Stage: {staging}")
            proto("step", cwd=repo, stdin={**ROUND_INFO, "questions": [
                question("A?", key="a", board="fx-a"), question("B?", board="fx-b", waitsOn=["a"]),
                question("Pasted point?", **{"for": "pt3"})]})
            related_state = shown(cwd=repo)
            held_q = next(q for q in related_state["questions"] if q["board"] == "fx-b")
            draft_q = next(q for q in related_state["questions"] if q["board"] is None)
            if related_state["step"] != "related" or held_q["status"] != "held" or held_q["waitsOn"] != ["q3"] \
                    or draft_q["overlaps"] != [{"id": "fx-old", "title": "Old ruling", "outcome": None},
                                               {"id": "fx-rel", "title": "", "outcome": None}] \
                    or [c["args"][:4] for c in calls() if c["args"][0] != "show"] != [["related", "--like", "-", "--json"]]:
                raise ValueError(f"protocol Related: {related_state}")
            refused("step", cwd=repo, stdin={"outcomes": {draft_q["id"]: {"fx-old": "supersedes"}}}, needle="outcomes missing")
            refused("step", cwd=repo, stdin={"outcomes": {draft_q["id"]: {"fx-old": "maybe"}}}, needle="outcome must be one of")
            proto("step", cwd=repo, stdin={"outcomes": {draft_q["id"]: {"fx-old": "supersedes", "fx-rel": "relate"}}})
            # A person's push between passes counts with its origin; it changes the sequence only when it changes something.
            proto("pass", "--origin", "press", stdin={"command": "ground", "args": "q3 A", "pending": None}, cwd=repo)
            proto("step", stdin={"pass": "ground", "updates": [], "checked": ["every question"]}, cwd=repo)
            if shown(cwd=repo)["pending"]["command"] != "step-back" or shown(cwd=repo)["check"]["last"]["ground"]["origin"] != "press":
                raise ValueError("an unchanged pushed pass must keep the expected step-back and count its origin")
            refused("step", cwd=repo, stdin={"pass": "step-back", "updates": [{"id": "q3", "status": "ready"}]}, needle="unknown fields")
            # agents r11-q48: `explored` inside an update says where it goes.
            refused("step", cwd=repo, stdin={"pass": "step-back", "updates": [{"id": "q3", "explored": []}]},
                    needle="unknown fields explored; `explored` goes at the report's top level, keyed by question id")
            proto("step", cwd=repo, stdin={"pass": "step-back", "updates": [], "checked": ["every question"]})  # the path pass
            proto("step", cwd=repo, stdin={"pass": "step-back", "updates": [], "checked": ["every question"]})  # the options pass: not the confirm-own-rulings question
            if shown(cwd=repo)["check"]["last"]["step-back"]["changes"] != 0 or shown(cwd=repo)["pending"]["args"] != "":
                raise ValueError("the options pass must be followed by the Base loop")
            proto("step", cwd=repo, stdin={"pass": "step-back", "updates": [{"id": "q3", "premises": "grounded in docs/a.md"}]})
            proto("step", cwd=repo, stdin={"pass": "ground", "updates": [], "checked": ["every question"]})
            # A draft a pass adds is searched before asking, and its hits need outcomes.
            proto("step", cwd=repo, stdin={"pass": "step-back", "updates": [question("Pasted extra?", **{"for": "pt3"})]})
            proto("step", cwd=repo, stdin={"pass": "ground", "updates": [], "checked": ["every question"]})
            for cycle in range(4, cap_cycles + 1):
                proto("step", cwd=repo, stdin={"pass": "step-back", "updates": [{"id": "q3", "premises": f"grounded in docs/a.md, pass {cycle}"}]})
                proto("step", cwd=repo, stdin={"pass": "ground", "updates": [], "checked": ["every question"]})
            converge(cwd=repo)
            extra = shown(cwd=repo)
            added = next(q for q in extra["questions"] if q["text"] == "Pasted extra?")
            if extra["step"] != "related" or [h["id"] for h in added["overlaps"]] != ["fx-old", "fx-rel"]:
                raise ValueError(f"protocol must search a draft added in Check before asking: {extra}")
            refused("step", cwd=repo, stdin={"pass": "step-back", "updates": [], "checked": ["every question"]}, needle="`outcomes` must map")
            proto("step", cwd=repo, stdin={"outcomes": {added["id"]: {"fx-old": "unrelated", "fx-rel": "unrelated"}}})
            while shown(cwd=repo)["pending"]["command"] != "challenge-rulings":  # the refine pair and the lean pass come first
                proto("step", cwd=repo, stdin={"pass": shown(cwd=repo)["pending"]["command"], "updates": [], "checked": ["every question"]})
            challenge = shown(cwd=repo)
            if challenge["step"] != "check" or challenge["pending"]["command"] != "challenge-rulings" or challenge["batch"] is not None:
                raise ValueError(f"protocol must queue challenge-rulings before confirming own rulings: {challenge}")
            # A change by challenge-rulings loops again; at the last cycle that is the cap; "Ask now" then asks (it ran already).
            proto("step", cwd=repo, stdin={"pass": "challenge-rulings", "updates": [{"id": added["id"], "remove": True,
                                                                                    "reason": "merged into the point"}]})
            cap = shown(cwd=repo)["batch"]
            if cap["marker"] != "round:r3:1" or cap["questions"][0]["header"] != "Check cap":
                raise ValueError(f"a challenge change at the last cycle must reach the cap: {cap}")
            proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": "round:r3:1", "answers": {cap["questions"][0]["question"]: "Ask now"}})
            batch = shown(cwd=repo)["batch"]
            if batch["marker"] != "round:r3:2" or [q["question"] for q in batch["questions"]] != ["1. A?", "2. Pasted point? fx-old (Old ruling) is replaced at release."]:
                raise ValueError(f"protocol batch must leave held questions out: {batch}")
            result = json.loads(proto("answer", "--origin", "dialog", cwd=repo, stdin={
                "marker": "round:r3:2", "answers": {"1. A?": "Keep"}, "annotations": {}, "response": "And mind the tenancy."}).stdout)
            # A free reply holds the next batch for the model's reading (lead 6aa2ec33, 2026-11-06); the step issues it.
            if "And mind the tenancy." not in result["note"] or "tied to no question" not in result["note"] or result["batch"] is not None \
                    or "The next batch waits for your reading" not in result["note"]:
                raise ValueError(f"protocol answer with a response: {result}")
            proto("step", stdin={}, cwd=repo)
            result = {"batch": shown(cwd=repo)["batch"]}
            if result["batch"]["marker"] != "round:r3:3" or [q["question"] for q in result["batch"]["questions"]] != ["Pasted point? fx-old (Old ruling) is replaced at release."]:
                raise ValueError(f"protocol step after the reading must issue the held batch: {result}")
            declined = json.loads(proto("decline", "--origin", "dialog", cwd=repo,
                                        stdin={"marker": "round:r3:3", "partial": {"Pasted point? fx-old (Old ruling) is replaced at release.": "Keep"}}).stdout)
            if declined["batch"] is not None or draft_q["id"] not in [q["id"] for q in declined["questions"] if q["status"] == "ready"] \
                    or "'Pasted point? fx-old (Old ruling) is replaced at release.': 'Keep'" not in declined["note"]:
                raise ValueError(f"protocol decline: {declined}")
            # Chat answers (R-B9): only with a quote the console relayed from the person this round.
            chat = {"question": draft_q["id"], "answer": "Keep", "quote": "keep   it,\nfinal"}
            refused("answer", "--origin", "chat", stdin=chat, needle="quote check failed", cwd=repo)
            for origin in ("dialog", "model", "press"):
                refused("say", "--origin", origin, stdin={"text": "x"}, needle="not accepted", cwd=repo)
            proto("say", "--origin", "composer", stdin={"text": "I say: keep it, final."}, cwd=repo)
            refused("answer", "--origin", "chat", stdin={**chat, "quote": "drop it"}, needle="quote check failed", cwd=repo)
            refused("answer", "--origin", "chat", stdin={"question": draft_q["id"], "answer": "Keep"}, needle="quote", cwd=repo)
            refused("answer", "--origin", "chat", stdin={**chat, "question": held_q["id"]}, needle="is held", cwd=repo)
            # The chat answer releases the held q4 (its premise q3 is answered): the round continues with it, a scoped rerun on q4,
            # not a Record that carries it over.
            note = proto("answer", "--origin", "chat", stdin=chat, cwd=repo).stdout  # the note alone (r18-q70), not the state
            recording = shown(cwd=repo)
            if note.startswith("{") or '"questions"' in note:
                raise ValueError(f"a chat answer prints the note only:\n{note}")
            released = next(q for q in recording["questions"] if q["id"] == held_q["id"])
            if recording["step"] != "check" or next(q for q in recording["questions"] if q["id"] == draft_q["id"])["answer"] != "Keep" \
                    or released["status"] != "draft" or (recording["pending"]["command"], recording["pending"]["args"]) != ("step-back", f"goal foundations on {held_q['id']}") \
                    or f"released {held_q['id']} from held" not in note.splitlines()[0]:
                raise ValueError(f"protocol chat answer must release the held question into a scoped rerun: {recording}")
            for _ in range(12):  # the scoped path pass, the Base loop, the scoped refine pair, the lean pass, challenge-rulings
                pending = shown(cwd=repo)["pending"]
                if pending is None:
                    break
                proto("step", stdin={"pass": pending["command"], "updates": [], "checked": ["every question"]}, cwd=repo)
            scoped_batch = shown(cwd=repo)["batch"]
            scoped_texts = [line["text"] for line in shown(cwd=repo)["log"]]
            if scoped_batch["marker"] != "round:r3:4" or [q["question"] for q in scoped_batch["questions"]] != ["B?"] \
                    or not any(text.startswith("step-back (path " + held_q["id"]) for text in scoped_texts) \
                    or not any(text.startswith("step-back (refine " + held_q["id"]) for text in scoped_texts) \
                    or not any(text.startswith("ground (refine " + held_q["id"]) for text in scoped_texts) \
                    or not any(text.startswith("ground (lean " + held_q["id"]) for text in scoped_texts):
                raise ValueError(f"protocol scoped rerun on the released question: {scoped_batch}\n{scoped_texts}")
            proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": "round:r3:4", "answers": {"B?": "Keep"}})
            after = shown(cwd=repo)
            if after["step"] != "check" or after["pending"]["command"] != "challenge-rulings" or after["pending"]["args"] != "q3 q4 q5":
                raise ValueError(f"protocol: the challenge over the answered set follows the last answer: {after}")
            proto("step", cwd=repo, stdin={"pass": "challenge-rulings", "updates": [], "checked": ["the answers"]})
            if shown(cwd=repo)["step"] != "record":
                raise ValueError(f"protocol: Record follows once nothing is left to ask: {shown(cwd=repo)}")
            calls()
            out = proto("step", cwd=repo, stdin={"records": {
                "q3": {"rationale": "A rationale.", "ruleOwner": "docs/a.md#a"},
                held_q["id"]: {"rationale": "B rationale.", "ruleOwner": "docs/b.md#b"},
                draft_q["id"]: {"rationale": "P rationale.", "ruleOwner": "docs/p.md#p", "decision": "Keep the point."}}}).stdout
            board_calls = calls()
            records = Path(str(log) + ".records").read_text(encoding="utf-8")
            expected = [["claim", "fx-a"], ["ruling", "record", "fx-a"], ["claim", "fx-b"], ["ruling", "record", "fx-b"],
                        ["bd", "list", "--external-ref"], ["ruling", "revise", "fx-old", "--title", "Pasted point", "--body-file"],
                        ["bd", "batch", "-m", "protocol: link fx-rev1", "--json"], ["claim", "fx-rev1"], ["ruling", "record", "fx-rev1"],
                        ["health", "--json", "--items", "decided"]]  # one Record writes all three
            if [c["args"][:len(want)] for c, want in zip(board_calls, expected)] != expected or len(board_calls) != len(expected) \
                    or board_calls[6]["stdin"] != "dep add fx-rev1 fx-rel relates-to\n" \
                    or 'User (chat), ' not in records or '"keep   it,\nfinal"' not in records or "## Decision\nKeep the point." not in records \
                    or "Board: 3 open questions, 1 decided awaiting release, 0 released to plan (2 wait), 0 to review, 1 to accept, 1 waiting on the user." not in out \
                    or "Held for a later round" in out:
                raise ValueError(f"protocol board Record: {board_calls}\n{out}\n{records}")
            history_events = [json.loads(row) for row in (state / "0000-lead0001.protocol" / "history.jsonl").read_text().splitlines()]
            if [e["event"] for e in history_events if e.get("round") == "r3"].count("continued") != 1:
                raise ValueError("protocol: the hand-over logs one continued event")
            # A question waits only within its round (r23-q91): abandoning keeps no held question, and the board item comes back
            # with the same text accepted.
            configure(health={"counts": counts, "items": {"questions": [
                {"id": "fx-a", "status": "open", "type": "decision", "title": "A?", "priority": 1, "blockedBy": []},
                {"id": "fx-b", "status": "open", "type": "decision", "title": "B?", "priority": 0, "blockedBy": ["fx-a"]}]}})
            def waiting_round():
                proto("start", "round", cwd=repo)
                proto("step", stdin={"classes": {"fx-a": "user", "fx-b": "user"}}, cwd=repo)
                proto("step", stdin={"select": ["fx-a", "fx-b"]}, cwd=repo)
                proto("step", cwd=repo, stdin={**ROUND_INFO, "questions": [question("A?", key="a", board="fx-a"),
                                                                          question("B?", board="fx-b", waitsOn=["a"])]})
                converge(cwd=repo)
                return shown(cwd=repo)
            waiting = waiting_round()
            held_id = next(q["id"] for q in waiting["questions"] if q["board"] == "fx-b")
            if [q["question"] for q in waiting["batch"]["questions"]] != ["A?"] or waiting["questions"][1]["status"] != "held":
                raise ValueError(f"protocol: a held question waits for its premise: {waiting}")
            declined = json.loads(proto("decline", "--origin", "dialog", cwd=repo,
                                        stdin={"marker": waiting["batch"]["marker"], "partial": None}).stdout)
            if next(q for q in declined["questions"] if q["id"] == held_id)["status"] != "held":
                raise ValueError(f"protocol: a held question waiting on a declined premise stays held: {declined}")
            proto("abandon", cwd=repo)
            again = waiting_round()  # the same texts: no ghost refuses them
            if [q["question"] for q in again["batch"]["questions"]] != ["A?"]:
                raise ValueError(f"protocol: after an abandon the same questions stage again: {again}")
            proto("abandon", cwd=repo)
            # Collect leaves out another live session's holds (named in one line) and marks a gone session's; selecting the
            # gone one takes it over (board take) and the round releases it like its own claims.
            saved = {name: (session_dir / name).read_text() for name in ("state.json", "history.jsonl")}
            row = {"status": "open", "type": "decision", "priority": 1, "blockedBy": []}
            configure(health={"counts": counts, "items": {"questions": [
                {**row, "id": "fx-mine", "title": "Mine?"}, {**row, "id": "fx-live", "title": "Live?", "holder": "other001"},
                {**row, "id": "fx-gone", "title": "Gone?", "holder": "gone0001"}]}},
                position={"held": [{"id": "fx-live", "holder": "other001", "mark": None}, {"id": "fx-gone", "holder": "gone0001", "mark": "gone"}]})
            proto("compacted", cwd=repo)  # the open-item list prints whole once between compactions
            out = proto("start", "round", cwd=repo, prepass=False).stdout
            if "Held by live session other001, not offered: fx-live" not in out or "- fx-live" in out \
                    or "- fx-gone, held by gone0001 (gone): Gone?" not in out:
                raise ValueError(f"protocol pre-pass must leave out live foreign holds and mark gone ones:\n{out}")
            proto("step", stdin={"pass": "step-back", "summary": "No change."}, cwd=repo)
            proto("step", stdin={"classes": {"fx-mine": "user", "fx-gone": "user"}}, cwd=repo)
            calls()
            proto("step", stdin={"select": ["fx-mine", "fx-gone"]}, cwd=repo)
            made = [c["args"] for c in calls()]
            proto("abandon", cwd=repo)
            released = [c["args"] for c in calls() if c["args"][0] == "unclaim"]
            if made != [["take", "fx-gone"], ["claim", "fx-mine"]] or released != [["unclaim", "fx-gone", "fx-mine"]]:
                raise ValueError(f"protocol Select must take a gone session's hold and release it with the round: {made} {released}")
            for name, text in saved.items():
                (session_dir / name).write_text(text)
            configure()

            # F: Record survives partial board failures: a failed relate is retried on the rerun without a second create;
            # a failing count read at close neither fails the call nor loses the writes.
            configure(related={"Retry": ["fx-rel"]})
            proto("start", "round", stdin={"points": ["Retry point"]}, cwd=repo)
            proto("step", stdin={"classes": {"pt4": "user"}}, cwd=repo)
            proto("step", stdin={"select": ["pt4"]}, cwd=repo)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Retry point?", **{"for": "pt4"})]}, cwd=repo)
            retry = next(q for q in shown(cwd=repo)["questions"])
            proto("step", stdin={"outcomes": {retry["id"]: {"fx-rel": "relate"}}}, cwd=repo)
            converge(cwd=repo)
            proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": "round:r6:1", "answers": {"Retry point?": "Keep"}})
            configure(related={"Retry": ["fx-rel"]}, fail=["bd batch"])
            calls()
            report = {"records": {retry["id"]: {"rationale": "R.", "ruleOwner": "o"}}}
            out = proto("step", stdin=report, cwd=repo).stdout
            if "Not recorded" not in out or "simulated failure" not in out or shown(cwd=repo)["step"] != "record":
                raise ValueError(f"protocol Record must report a failed relate and stay at Record:\n{out}")
            configure(related={"Retry": ["fx-rel"]}, fail=["health"])
            out = proto("step", stdin=report, cwd=repo).stdout
            made = [c["args"][:2] for c in calls()]
            if made.count(["bd", "create"]) != 1 or made.count(["bd", "batch"]) != 2 or "Board counts unavailable" not in out \
                    or "Round r6 closed." not in out or shown(cwd=repo)["round"] is not None:
                raise ValueError(f"protocol Record rerun: {made}\n{out}")
            configure()

            # F2 (r4-q11): Record is safe to run again. A call dies after the create of the second record was written (its id
            # never arrived): the first record's progress is saved, the rerun with the same report skips it, finds the second by
            # its tag instead of creating it again and creates only the third.
            points = ["Tag one", "Tag two", "Tag three"]
            configure(tags={}, dieAfterCreates=1, newIds=["fx-m1", "fx-m2", "fx-m3"])
            out = proto("start", "round", stdin={"points": points}, cwd=repo).stdout
            pasted = re.findall(r"(pt\d+) \[pasted\]", out)
            proto("step", stdin={"classes": {pt: "user" for pt in pasted}}, cwd=repo)
            proto("step", stdin={"select": pasted}, cwd=repo)
            proto("step", stdin={**ROUND_INFO, "questions": [question(f"{text}?", **{"for": pt}) for text, pt in zip(points, pasted)]}, cwd=repo)
            converge(cwd=repo)
            batch = shown(cwd=repo)["batch"]
            proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": batch["marker"], "answers": {q["question"]: "Keep" for q in batch["questions"]}})
            view = shown(cwd=repo)
            round_id, ids = view["round"], [q["id"] for q in view["questions"]]
            report = {"records": {qid: {"rationale": "R.", "ruleOwner": "o"} for qid in ids}}
            calls()
            out = proto("step", stdin=report, cwd=repo, ok=False).stderr
            first = calls()
            if "nothing was saved" not in out or [q.get("recorded") for q in json.loads((session_dir / "state.json").read_text())["round"]["questions"]] != ["fx-m1", None, None]:
                raise ValueError(f"protocol Record must save each question's progress when the call dies: {out}")
            if not any(row["event"] == "recorded" and row["question"] == ids[0] for row in (json.loads(l) for l in (session_dir / "history.jsonl").read_text().splitlines())):
                raise ValueError("protocol Record must flush the history of the questions it saved")
            config.write_text(json.dumps({k: v for k, v in json.loads(config.read_text(encoding="utf-8")).items() if k != "dieAfterCreates"}), encoding="utf-8")
            out = proto("step", stdin=report, cwd=repo).stdout
            second = calls()
            tags = json.loads(config.read_text(encoding="utf-8"))["tags"]
            if tags != {f"protocol:0000-lead0001:{round_id}:{qid}": [f"fx-m{n}"] for n, qid in enumerate(ids, 1)} \
                    or [c["args"][:2] for c in first + second].count(["bd", "create"]) != 3 \
                    or any(engine_head(c) in (["claim", "fx-m1"], ["ruling", "record", "fx-m1"]) for c in second) \
                    or ["ruling", "record", "fx-m2"] not in [engine_head(c) for c in second] or ["ruling", "record", "fx-m3"] not in [engine_head(c) for c in second] \
                    or f"Round {round_id} closed." not in out or shown(cwd=repo)["round"] is not None:
                raise ValueError(f"protocol Record rerun must reuse the tagged record and skip the recorded one: {tags}\n{[c['args'] for c in first + second]}\n{out}")
            configure()

            # G: a question that replaces records (r12-q44): a decided record closes at Record, a released one is revised.
            # Alpha: the dialog names the record, a record not naming it is refused, Record closes it and reports it.
            qid = replacing("Alpha point", ["fx-u1"], {"fx-u1": "supersedes"}, items={"fx-u1": {**decided, "title": "Alpha store"}}, newIds=["fx-n1"])
            if answered() != "Alpha point? Recording it closes fx-u1 (Alpha store).":
                raise ValueError("the dialog must name the record the question closes")
            calls()
            refused("step", stdin={"records": {qid: {"rationale": "R.", "ruleOwner": "o"}}}, needle="recording closes fx-u1; name each", cwd=repo)
            if [c for c in calls() if engine_verb(c) in ("revise", "claim", "supersede")] or shown(cwd=repo)["step"] != "record":
                raise ValueError("a record that does not name the closed record must be refused before any board write")
            out = proto("step", stdin={"records": {qid: {"rationale": "Replaces fx-u1: the same store, now with a TTL.", "ruleOwner": "o"}}},
                        cwd=repo).stdout
            rows = calls()
            made = [engine_head(c) for c in rows if engine_verb(c) in ("revise", "claim", "record", "supersede")]
            revise_args = next(c["args"] for c in rows if engine_verb(c) == "revise")
            if not re.fullmatch(rf"protocol:0000-lead0001:r\d+:{qid}", revise_args[revise_args.index("--external-ref") + 1] if "--external-ref" in revise_args else ""):
                raise ValueError(f"Record must tag a revision with its session, round and question: {revise_args}")
            history = [json.loads(row) for row in (session_dir / "history.jsonl").read_text().splitlines()]
            if made != [["ruling", "revise", "fx-u1"], ["claim", "fx-n1"], ["ruling", "record", "fx-n1"], ["ruling", "supersede", "fx-u1"]] \
                    or item_status("fx-u1") != "closed" or "- " + qid + " → fx-n1, closed fx-u1" not in out \
                    or "recorded " + qid + " · superseded fx-u1 by fx-n1 · round closed" not in out.splitlines()[0] \
                    or not any(e["event"] == "superseded" and (e["question"], e["old"], e["new"]) == (qid, "fx-u1", "fx-n1") for e in history):
                raise ValueError(f"Record must close the replaced decided record and report it: {made}\n{out}")
            # Beta: a deferred question closes nothing and leaves the old record alone.
            qid = replacing("Beta point", ["fx-u2"], {"fx-u2": "supersedes"}, items={"fx-u2": decided})
            answered()
            calls()
            proto("say", "--origin", "composer", stdin={"text": "put the beta point off"}, cwd=repo)
            proto("defer", stdin={"question": qid, "quote": "put the beta point off"}, cwd=repo)
            proto("step", stdin={"records": {}}, cwd=repo)
            if [c for c in calls() if engine_verb(c) in ("revise", "claim", "record", "supersede")] or item_status("fx-u2") != "decided":
                raise ValueError("a deferred question must close nothing")
            # Beta2 (review F1): a deferred question that would take over a decided record (extend) defers a new item, never the record.
            qid = replacing("Betatwo point", ["fx-u5"], {"fx-u5": "extend"}, items={"fx-u5": decided}, newIds=["fx-n5"])
            answered()
            calls()
            proto("say", "--origin", "composer", stdin={"text": "put the betatwo point off"}, cwd=repo)
            proto("defer", stdin={"question": qid, "quote": "put the betatwo point off"}, cwd=repo)
            proto("step", stdin={"records": {}}, cwd=repo)
            rows = [c["args"] for c in calls()]
            if any(a[:2] == ["bd", "defer"] and a[2] == "fx-u5" for a in rows) or ["bd", "defer", "fx-n5"] != next((a[:3] for a in rows if a[:2] == ["bd", "defer"]), None) \
                    or item_status("fx-u5") != "decided":
                raise ValueError(f"a deferred question must defer a new item, not the decided record it would extend: {rows}")
            # Beta3 (review round 2): the same for a released record, which a deferral must not move either.
            qid = replacing("Betathree point", ["fx-u12"], {"fx-u12": "extend"}, items={"fx-u12": released_record}, newIds=["fx-n12"])
            answered()
            calls()
            proto("say", "--origin", "composer", stdin={"text": "put the betathree point off"}, cwd=repo)
            proto("defer", stdin={"question": qid, "quote": "put the betathree point off"}, cwd=repo)
            proto("step", stdin={"records": {}}, cwd=repo)
            rows = [c["args"] for c in calls()]
            if any(a[:2] == ["bd", "defer"] and a[2] == "fx-u12" for a in rows) or ["bd", "defer", "fx-n12"] != next((a[:3] for a in rows if a[:2] == ["bd", "defer"]), None) \
                    or item_status("fx-u12") != "released":
                raise ValueError(f"a deferred question must defer a new item, not the released record it would extend: {rows}")
            # Gamma: several records close; the first is revised (parent and labels), the others stay linked until closed; the
            # items a closed record settles move to the new record.
            qid = replacing("Gamma point", ["fx-u3", "fx-u4"], {"fx-u3": "supersedes", "fx-u4": "supersedes"},
                            items={"fx-u3": {**decided, "title": "Gamma three"}, "fx-u4": {**decided, "title": "Gamma four"}}, newIds=["fx-n3"])
            edit_state(lambda document: document.setdefault("settles", {}).update({"fx-u4": ["fx-set1"]}))
            if answered() != "Gamma point? Recording it closes fx-u3 (Gamma three), fx-u4 (Gamma four).":
                raise ValueError("the dialog must name every record the question closes")
            calls()
            proto("step", stdin={"records": {qid: {"rationale": "Replaces fx-u3 and fx-u4.", "ruleOwner": "o"}}}, cwd=repo)
            rows = calls()
            settles = json.loads((session_dir / "state.json").read_text())["settles"]
            if [engine_head(c) for c in rows if engine_verb(c) in ("revise", "supersede")] != [["ruling", "revise", "fx-u3"], ["ruling", "supersede", "fx-u3"], ["ruling", "supersede", "fx-u4"]] \
                    or [c["stdin"] for c in rows if c["args"][:2] == ["bd", "batch"]] != ["dep add fx-n3 fx-u4 tracks\n"] \
                    or item_status("fx-u3") != "closed" or item_status("fx-u4") != "closed" \
                    or settles.get("fx-n3") != ["fx-set1"] or "fx-u4" in settles:
                raise ValueError(f"Record must close several records and move their settled items: {rows}\n{settles}")
            # Delta: one released record (revised, replaced at its release) and one decided record (closed).
            qid = replacing("Delta point", ["fx-r0", "fx-u5"], {"fx-r0": "supersedes", "fx-u5": "supersedes"},
                            items={"fx-r0": {**released_record, "title": "Delta old"}, "fx-u5": {**decided, "title": "Delta five"}}, newIds=["fx-n4"])
            if answered() != "Delta point? Recording it closes fx-u5 (Delta five); fx-r0 (Delta old) is replaced at release.":
                raise ValueError("the dialog must name the closed and the revised record")
            calls()
            proto("step", stdin={"records": {qid: {"rationale": "Replaces fx-u5.", "ruleOwner": "o"}}}, cwd=repo)
            rows = calls()
            if [engine_head(c) for c in rows if engine_verb(c) in ("revise", "supersede")] != [["ruling", "revise", "fx-r0"], ["ruling", "supersede", "fx-u5"]] \
                    or [c["stdin"] for c in rows if c["args"][:2] == ["bd", "batch"]] != ["dep add fx-n4 fx-u5 tracks\n"] \
                    or item_status("fx-r0") != "released":
                raise ValueError(f"a released record is revised and a decided one closed: {rows}")
            # Two released records, or a revision to carry besides a released one, are refused at Related.
            released_tracked = {**decided, "dependencies": [{"issue_id": "fx-u7", "depends_on_id": "fx-r2", "type": "tracks"}]}
            for hits, items, needle in ((["fx-r0", "fx-r1"], {"fx-r0": released_record, "fx-r1": released_record}, "at most one released record"),
                                        (["fx-r1", "fx-u7"], {"fx-r1": released_record, "fx-u7": released_tracked}, "more than one record or rule"),
                                        (["fx-open"], {"fx-open": {"status": "open", "issue_type": "decision"}}, "supersedes needs a recorded ruling")):
                qid = replacing("Epsilon point", hits, None, items=items)
                refused("step", stdin={"outcomes": {qid: {hit: "supersedes" for hit in hits}}}, needle=needle, cwd=repo)
                proto("abandon", cwd=repo)
            # Zeta: a record another live session holds is refused at Related (board ruling supersede has no holder check); a gone
            # session's hold is taken at Record, just before the close.
            held = {"position": {"held": [{"id": "fx-live", "holder": "other001", "mark": "idle"}, {"id": "fx-gone", "holder": "gone0001", "mark": "gone"}]}}
            qid = replacing("Zeta point", ["fx-live"], None, items={"fx-live": {**decided, "assignee": "other001"}}, **held)
            refused("step", stdin={"outcomes": {qid: {"fx-live": "supersedes"}}}, needle="another live session holds it", cwd=repo)
            proto("abandon", cwd=repo)
            qid = replacing("Zeta point", ["fx-gone"], {"fx-gone": "supersedes"}, items={"fx-gone": {**decided, "assignee": "gone0001"}}, newIds=["fx-n5"], **held)
            answered()
            calls()
            proto("step", stdin={"records": {qid: {"rationale": "Replaces fx-gone.", "ruleOwner": "o"}}}, cwd=repo)
            made = [engine_head(c) for c in calls() if engine_verb(c) in ("take", "supersede")]
            if made != [["take", "fx-gone"], ["ruling", "supersede", "fx-gone"]]:
                raise ValueError(f"a gone session's hold must be taken before the close: {made}")
            # A hold taken by another live session after Related is refused at Record too.
            qid = replacing("Eta point", ["fx-u8"], {"fx-u8": "supersedes"}, items={"fx-u8": decided}, newIds=["fx-n6"], **held)
            answered()
            patch_config(items={"fx-u8": {**decided, "assignee": "other001"}}, position={"held": [{"id": "fx-u8", "holder": "other001", "mark": "idle"}]})
            calls()
            out = proto("step", stdin={"records": {qid: {"rationale": "Replaces fx-u8.", "ruleOwner": "o"}}}, cwd=repo).stdout
            if "Not recorded" not in out or "another live session holds it" not in out or item_status("fx-u8") != "decided":
                raise ValueError(f"Record must refuse a close of a record another live session holds:\n{out}")
            proto("abandon", cwd=repo)
            # Nu (r13 q51): a decided record the search missed is marked `supersedes` by id: the dialog names it by title, Record
            # closes it. Only a recorded ruling qualifies and a live foreign hold stays refused; other outcomes name hits only.
            nu_items = {"fx-u11": {**decided, "title": "Nu old"}, "fx-open2": {"status": "open", "issue_type": "decision"},
                        "fx-live2": {**decided, "assignee": "other001"}}
            held_live = {"position": {"held": [{"id": "fx-live2", "holder": "other001", "mark": "idle"}]}}
            qid = replacing("Nu point", ["fx-o1"], None, items=nu_items, newIds=["fx-n11"], **held_live)
            for outcomes, needle in (({"fx-o1": "unrelated", "fx-u11": "relate"}, "only `supersedes` may name a decided record"),
                                     ({"fx-o1": "unrelated", "fx-open2": "supersedes"}, "supersedes needs a recorded ruling"),
                                     ({"fx-o1": "unrelated", "fx-live2": "supersedes"}, "another live session holds it")):
                refused("step", stdin={"outcomes": {qid: outcomes}}, needle=needle, cwd=repo)
            if [h["id"] for h in shown(cwd=repo)["questions"][0]["overlaps"]] != ["fx-o1"]:
                raise ValueError("a refused outcome must add no overlap")
            proto("step", stdin={"outcomes": {qid: {"fx-o1": "unrelated", "fx-u11": "supersedes"}}}, cwd=repo)
            converge(cwd=repo)
            if answered() != "Nu point? Recording it closes fx-u11 (Nu old)." \
                    or [h["id"] for h in shown(cwd=repo)["questions"][0]["overlaps"]] != ["fx-o1", "fx-u11"]:
                raise ValueError("the dialog must name the missed record by title")
            calls()
            proto("step", stdin={"records": {qid: {"rationale": "Replaces fx-u11.", "ruleOwner": "o"}}}, cwd=repo)
            made = [engine_head(c) for c in calls() if engine_verb(c) in ("revise", "claim", "record", "supersede")]
            if made != [["ruling", "revise", "fx-u11"], ["claim", "fx-n11"], ["ruling", "record", "fx-n11"], ["ruling", "supersede", "fx-u11"]] or item_status("fx-u11") != "closed":
                raise ValueError(f"Record must close the missed record: {made}")
            configure()
            # Theta: a close that failed is retried on the rerun without a second record; a close that bd made before it
            # exited 1 counts as done and says so.
            qid = replacing("Theta point", ["fx-u9"], {"fx-u9": "supersedes"}, items={"fx-u9": decided}, newIds=["fx-n7"], fail=["supersede"])
            answered()
            calls()
            report = {"records": {qid: {"rationale": "Replaces fx-u9.", "ruleOwner": "o"}}}
            out = proto("step", stdin=report, cwd=repo).stdout
            if "Not recorded" not in out or "board ruling supersede fx-u9 --with fx-n7" not in out or shown(cwd=repo)["step"] != "record" or item_status("fx-u9") != "decided":
                raise ValueError(f"a failed close must leave the question unrecorded:\n{out}")
            patch_config(fail=[])
            out = proto("step", stdin=report, cwd=repo).stdout
            made = [engine_head(c) for c in calls() if engine_verb(c) in ("revise", "supersede")]
            if made != [["ruling", "revise", "fx-u9"], ["ruling", "supersede", "fx-u9"], ["ruling", "supersede", "fx-u9"]] or item_status("fx-u9") != "closed" or "Round r" not in out or shown(cwd=repo)["round"] is not None:
                raise ValueError(f"a failed close must be retried on the rerun without a second record: {made}\n{out}")
            qid = replacing("Iota point", ["fx-u10"], {"fx-u10": "supersedes"}, items={"fx-u10": decided}, newIds=["fx-n8"], supersedeFail=["fx-u10"])
            answered()
            out = proto("step", stdin={"records": {qid: {"rationale": "Replaces fx-u10.", "ruleOwner": "o"}}}, cwd=repo).stdout
            if "closed fx-u10 but exited 1" not in out or item_status("fx-u10") != "closed" or shown(cwd=repo)["round"] is not None:
                raise ValueError(f"a close bd made before exiting 1 counts as done:\n{out}")
            configure()

            # F: evidence leans get one focused ground pass before challenge-rulings; a lean left unverified is flagged.
            out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Order?", "Batch?"]}, cwd=repo).stdout
            points = re.findall(r"(pt\d+) \[pasted\]", out)
            proto("step", stdin={"classes": {point: "user" for point in points}}, cwd=repo)
            proto("step", stdin={"select": points}, cwd=repo)
            evidence = {"cause": "evidence", "detail": "bd batch order"}
            proto("step", cwd=repo, stdin={**ROUND_INFO, "questions": [
                question("Order?", leanBecause=evidence, **{"for": points[0]}), question("Batch?", leanBecause=evidence, **{"for": points[1]})]})
            for command in ("step-back", "step-back", "step-back", "ground"):  # the path pass, the options pass, then one Base cycle
                proto("step", stdin={"pass": command, "updates": [], "checked": ["every question"]}, cwd=repo)
            # The refine pair: round-wide, once; then the targeted lean pass.
            pair = shown(cwd=repo)["pending"]
            if (pair["command"], pair["args"]) != ("step-back", "decisions clean overfit mechanics"):
                raise ValueError(f"protocol must run the refine step-back pass after the Base loop: {pair}")
            proto("step", stdin={"pass": "step-back", "updates": [], "checked": ["every question"]}, cwd=repo)
            pair = shown(cwd=repo)["pending"]
            if (pair["command"], pair["args"]) != ("ground", "assumptions board sources probe"):
                raise ValueError(f"protocol must run the refine ground pass next: {pair}")
            proto("step", stdin={"pass": "ground", "updates": [], "checked": ["every question"]}, cwd=repo)
            focused = shown(cwd=repo)
            ids = [q["id"] for q in focused["questions"]]
            if focused["pending"]["command"] != "ground" or focused["pending"]["args"] != f"assumptions sources probe on {ids[0]} {ids[1]}":
                raise ValueError(f"protocol must run one focused ground pass on evidence leans: {focused['pending']}")
            proto("step", stdin={"pass": "ground", "updates": [{"id": ids[0], "strength": "strong", "leanBecause": None, "strongBecause": STRONG_CLAIMS}],
                                 "checked": ["bd batch order (probe)"]}, cwd=repo)
            if shown(cwd=repo)["pending"]["command"] != "challenge-rulings":
                raise ValueError("protocol: the focused pass runs once, then challenge-rulings")
            proto("step", stdin={"pass": "challenge-rulings", "updates": [], "checked": ["every question"]}, cwd=repo)
            descriptions = [q["options"][0]["description"] for q in shown(cwd=repo)["batch"]["questions"]]
            if descriptions != ["keep it", "Unverified: bd batch order — keep it"]:
                raise ValueError(f"protocol dialog marks after the focused pass: {descriptions}")
            # r24-q99: the engine renders the text printed before the dialog from the question data; the dialog carries no for/against.
            notice = shown(cwd=repo)["batch"]["notice"]
            # r30-q141: the recommended option first with its reason, + and - lines, a blank line between parts, no trailing Recommended line.
            if not notice.startswith("**1. Order**\n\nProblem: Which one, and why now.\n\nCases: A caller who keeps it; one who drops it.\n\nPremises: Read in the fixture.\n\n"
                                     "**Recommended (strong): Keep**\n- For: for it\n- Against: against it\n\n**Drop**\n- For: for it\n- Against: against it\n\n---\n\n**2. Batch**\n") \
                    or "**Recommended (lean): Keep**\nUnverified: bd batch order\n- For: for it\n- Against: against it\n\n**Drop**\n- For: for it\n- Against: against it" not in notice \
                    or "Options:" in notice or "Recommended: Keep" in notice or notice.rstrip().endswith("(lean)") \
                    or any("for" in o or "against" in o for q in shown(cwd=repo)["batch"]["questions"] for o in q["options"]):
                raise ValueError(f"protocol must render the parts before the dialog, numbered like it, and keep them out of the dialog:\n{notice}")
            # An extra pass while the batch is out (before answers) withdraws it. Strength is presentation: the batch goes
            # out again at once; a substantive change (premises) reruns the loop first.
            out_marker = shown(cwd=repo)["batch"]["marker"]
            proto("step", stdin={"pass": "ground", "updates": [{"id": ids[1], "strength": "strong", "leanBecause": None,
                                                                  "strongBecause": STRONG_CLAIMS}], "checked": ["bd batch order"]}, cwd=repo)
            reissued = shown(cwd=repo)["batch"]
            if reissued is None or reissued["marker"] == out_marker or shown(cwd=repo)["step"] != "ask":
                raise ValueError(f"protocol: a presentation-only pass must re-issue the batch without a loop: {shown(cwd=repo)}")
            # That batch's dialog never opened: nobody saw its text, so the new batch prints whole, not as a change.
            if not reissued["notice"].startswith("**1. Order**\n\nProblem:") or "**2. Batch**\n\nProblem:" not in reissued["notice"] or "(changed)" in reissued["notice"]:
                raise ValueError(f"a batch withdrawn before its dialog must print whole again:\n{reissued['notice']}")
            proto("decline", "--origin", "dialog", stdin={"marker": reissued["marker"], "partial": None}, cwd=repo)  # the person saw this one
            refused("step", stdin={"pass": "ground", "updates": [{"id": ids[1], "rulings": [{"ruling": "One batch.", "alternative": "Two.", "fails": "order", "evidence": "probe"}]}]},
                    needle="each with ruling, why, alternative, fails, evidence", cwd=repo)  # a pass update: a ruling without its why
            proto("step", stdin={"pass": "ground", "updates": [{"id": ids[1], "premises": "bd batch keeps order (probe)",
                                                                  "rulings": [{"ruling": "One batch.", "why": "meets the order goal", "alternative": "Two.", "fails": "order", "evidence": "probe"}]}]}, cwd=repo)
            if shown(cwd=repo)["pending"]["command"] != "step-back":
                raise ValueError("protocol: a substantive change with a batch out must rerun the loop")
            issued = converge(cwd=repo).splitlines()[0]
            if not re.fullmatch(r"r\d+ · .*asked q\d+, q\d+ · next: the console to print, then your answers \(batch \d+\)", issued):
                raise ValueError(f"protocol output must open with the call's events and the next step: {issued!r}")
            reissued = shown(cwd=repo)["batch"]
            if reissued["marker"] == out_marker or [q["options"][0]["description"] for q in reissued["questions"]] != ["keep it"] * 2:
                raise ValueError(f"protocol must issue the updated batch anew: {reissued}")
            # r36-q195, q196: a re-ask prints whole, an unchanged question with no mark, a changed one naming what moved.
            if not reissued["notice"].startswith("**1. Order**\n\nProblem:") \
                    or "**2. Batch (changed: premises, rulings)**\n\nProblem: Which one, and why now." not in reissued["notice"] \
                    or "Premises: bd batch keeps order (probe)" not in reissued["notice"] or "**My ruling:** One batch." not in reissued["notice"]:
                raise ValueError(f"a re-ask must print whole and name what changed:\n{reissued['notice']}")
            # A report applies whole (r23-q95): an invalid strong claim refuses the valid title beside it, with every error listed.
            refused("step", stdin={"pass": "ground", "checked": ["titles"], "updates": [
                {"id": ids[0], "title": "Does bd batch keep order"}, {"id": ids[1], "strength": "strong", "strongBecause": {}}]},
                needle="strong is a claim", cwd=repo)
            if next(q for q in shown(cwd=repo)["questions"] if q["id"] == ids[0])["title"] == "Does bd batch keep order":
                raise ValueError("protocol must not apply part of a refused report")
            # Sent alone, the title needs no marks.
            proto("step", stdin={"pass": "ground", "checked": ["titles"], "updates": [{"id": ids[0], "title": "Does bd batch keep order"}]}, cwd=repo)
            refused("step", stdin={"pass": "ground", "checked": ["x"], "updates": [{"id": ids[1], "strength": "strong", "strongBecause": {}}]},
                    needle="strong is a claim", cwd=repo)
            # A refused call leaves only its refusal in the history: no event of the work it did not save.
            tail = [json.loads(line)["event"] for line in (state / "0000-lead0001.protocol" / "history.jsonl").read_text().splitlines()][-2:]
            if tail[-1] != "refused" or "batch-withdrawn" in tail:
                raise ValueError(f"protocol history must not keep events of a failed call: {tail}")
            # r36-q197: the engine's line keeps the dialog's numbers and says what became of each question.
            before_echo = shown(cwd=repo)["batch"]
            echoed = json.loads(proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": before_echo["marker"], "answers": {before_echo["questions"][1]["question"]: "my own words"}}).stdout)["echo"]
            if echoed != "Your answers:\n1. Does bd batch keep order: no answer, asked again\n2. Batch: typed, not an answer yet: my own words":
                raise ValueError(f"the line after a dialog must keep numbers and name outcomes: {echoed!r}")
            # The typed reply holds the next batch until the model reads it: here it records the reply as a chat answer.
            proto("answer", "--origin", "chat", cwd=repo, stdin={"question": ids[1], "answer": "my own words", "quote": "my own words"})
            if shown(cwd=repo)["batch"] is None:
                proto("step", stdin={}, cwd=repo)
            alone = shown(cwd=repo)["batch"]
            echoed = json.loads(proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": alone["marker"], "answers": {alone["questions"][0]["question"]: "Drop"}}).stdout)["echo"]
            if echoed != "Your answers:\nDoes bd batch keep order: Drop (not recommended)":
                raise ValueError(f"a one-question batch has no number, and a pick says whether it was the recommended one: {echoed!r}")
            proto("abandon", cwd=repo)

            # G: a hold ends with its work: abandon releases the round's unrecorded claims; Select and searches are logged.
            configure(health={"counts": counts, "items": {"questions": [
                {"id": "fx-g", "status": "open", "type": "decision", "title": "G?", "priority": 1, "blockedBy": []}]}})
            proto("start", "round", cwd=repo)
            proto("step", stdin={"classes": {"fx-g": "user"}}, cwd=repo)
            proto("step", stdin={"select": ["fx-g"]}, cwd=repo)
            calls()
            proto("abandon", cwd=repo)
            events = [json.loads(line)["event"] for line in (state / "0000-lead0001.protocol" / "history.jsonl").read_text().splitlines()]
            if [c["args"] for c in calls()] != [["unclaim", "fx-g"]] or "selected" not in events or "released" not in events:
                raise ValueError(f"protocol abandon must release the round's claims and log selection: {events[-5:]}")

            # r24-q100: a question tied to an item that is no decision is refused at Stage and by an update, naming the draft;
            # its point stays selectable and nothing is claimed for the item.
            configure(items={"fx-bug": {"status": "open", "issue_type": "bug", "title": "A bug"},
                             "fx-dec": {"status": "open", "issue_type": "decision", "title": "A decision"}})
            out = proto("start", "round", stdin={"points": ["Place the bug?"]}, cwd=repo).stdout
            pasted = re.search(r"(pt\d+) \[pasted\]", out).group(1)
            proto("step", stdin={"classes": {pasted: "user"}}, cwd=repo)
            proto("step", stdin={"select": [pasted]}, cwd=repo)
            refused("step", stdin={**ROUND_INFO, "questions": [question("Place?", board="fx-bug", **{"for": pasted})]},
                    needle="fx-bug is a bug, not a decision: stage a draft", cwd=repo)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Place?", board=None, **{"for": pasted})]}, cwd=repo)
            proto("abandon", cwd=repo)
            # agents r11-q41: Record writes each question onto its board item, so a second live question on one item is refused
            # at Stage and by an update, naming the draft route.
            out = proto("start", "round", stdin={"points": ["Split the decision?"]}, cwd=repo).stdout
            pasted = re.search(r"(pt\d+) \[pasted\]", out).group(1)
            proto("step", stdin={"classes": {pasted: "user"}}, cwd=repo)
            proto("step", stdin={"select": [pasted]}, cwd=repo)
            refused("step", stdin={**ROUND_INFO, "questions": [question("Split A?", board="fx-dec", **{"for": pasted}),
                                                                 question("Split B?", board="fx-dec", **{"for": pasted})]},
                    needle='board fx-dec is already q', cwd=repo)
            refused("step", stdin={**ROUND_INFO, "questions": [question("Split A?", board="fx-dec", **{"for": pasted}),
                                                                 question("Split B?", board="fx-dec", **{"for": pasted})]},
                    needle='stage it as a draft (`board`: null, `for`: "fx-dec")', cwd=repo)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Split A?", board="fx-dec", **{"for": pasted}),
                                                             question("Split B?", board=None, **{"for": pasted})]}, cwd=repo)
            split = [q["id"] for q in shown(cwd=repo)["questions"]]
            refused("step", stdin={"pass": "step-back", "updates": [{"id": split[1], "board": "fx-dec"}], "checked": ["every question"]},
                    needle=f"{split[1]}: board fx-dec is already {split[0]}'s item", cwd=repo)
            proto("abandon", cwd=repo)

            # G2: a decided record the session already held before the round stays held when the round ends without
            # recording it: its hold is the release's, not the round's to end.
            configure(health={"counts": counts, "items": {"decided": [
                {"id": "fx-d", "status": "decided", "type": "decision", "title": "D", "priority": 1, "blockedBy": []}],
                "questions": [{"id": "fx-g", "status": "open", "type": "decision", "title": "G?", "priority": 1, "blockedBy": []}]}},
                      held=["fx-d"])
            proto("start", "round", cwd=repo)
            proto("step", stdin={"classes": {"fx-d": "user", "fx-g": "user"}}, cwd=repo)
            proto("step", stdin={"select": ["fx-d", "fx-g"]}, cwd=repo)
            calls()
            proto("abandon", cwd=repo)
            if [c["args"] for c in calls()] != [["unclaim", "fx-g"]]:
                raise ValueError("protocol must not release a hold the session had before the round")
            configure()

        if part == "release":
            # N: `protocol next` ranks seeds (open milestone members, priority, work held; unblocked; no live foreign hold), `next
            # --set` stores a validated proposal, a round start clears it, `show --json` carries it while no round is open.
            row = {"status": "open", "type": "decision", "blockedBy": []}
            configure(health={"counts": counts, "milestones": [{"id": "fx-m1"}, {"id": "fx-m2"}], "items": {"questions": [
                {**row, "id": "fx-n1", "title": "Plain p0?", "priority": 0},
                {**row, "id": "fx-n2", "title": "Member p2?", "priority": 2, "labels": ["topic:store", "topic:cache"]},
                {**row, "id": "fx-n3", "title": "Member p1 holds 1?", "priority": 1, "labels": ["area", "topic:store"]},
                {**row, "id": "fx-n4", "title": "Member p1 holds 5?", "priority": 1},
                {**row, "id": "fx-n5", "title": "Live held?", "priority": 0, "holder": "other001"},
                {**row, "id": "fx-n6", "title": "Blocked?", "priority": 0, "blockedBy": ["fx-n1"]},
                {**row, "id": "fx-n7", "title": "Gone held p0?", "priority": 0, "holder": "gone0001"},
                {**row, "id": "fx-n8", "title": "Plain p1 holds 9?", "priority": 1}]}},
                      position={"held": [{"id": "fx-n5", "holder": "other001", "mark": None}, {"id": "fx-n7", "holder": "gone0001", "mark": "gone"}],
                                "questionsHoldingWork": [{"id": "fx-n3", "holds": 1, "holdsAll": 51}, {"id": "fx-n4", "holds": 5, "holdsAll": 55}, {"id": "fx-n8", "holds": 9, "holdsAll": 9}]},
                      roots={"fx-m1": {"items": {"questions": [{"id": "fx-n2"}, {"id": "fx-n3"}]}},
                             "fx-m2": {"items": {"questions": [{"id": "fx-n4"}, {"id": "fx-n3"}]}}},
                      items={"fx-n1": {"status": "open", "issue_type": "decision", "title": "Plain p0?"},
                             "fx-n2": {"status": "open", "issue_type": "decision", "title": "Member p2?"}},
                      fail=["show fx-gone", "show step-back", "show follow-up"])
            calls()
            out = proto("next", cwd=repo).stdout
            seeds_only = out.split("Open items (")[0]
            seeded = re.findall(r"^- (fx-n\d) · p(\d) · holds (\d+/\d+) · (milestone fx-m\d|no milestone) · ", out, re.M)
            made = [c["args"] for c in calls()]
            if seeded != [("fx-n4", "1", "5/55", "milestone fx-m2"), ("fx-n3", "1", "1/51", "milestone fx-m1"), ("fx-n2", "2", "0/0", "milestone fx-m1"),
                          ("fx-n1", "0", "0/0", "no milestone"), ("fx-n7", "0", "0/0", "no milestone")] \
                    or "fx-n5" in seeds_only or "fx-n6" in seeds_only or "fx-n8" in seeds_only or "No proposal stored." not in out \
                    or ["health", "--json", "--root", "fx-m1", "--items", "questions"] not in made or made[0][:3] != ["health", "--json", "--items"]:
                raise ValueError(f"protocol next must rank the seeds (milestone, priority, holds; no blocked or live-held):\n{out}\n{made}")
            if "Seeds for the next round" in proto("next", cwd=plain).stdout or calls():
                raise ValueError("protocol next without a board lists no seeds and reads no board")
            # r24-q104/q105: the open questions by topic label and priority print every time, and the lead ranks topics itself.
            if "Open questions by topic" not in out or "- store 1 p1, 1 p2" not in out or "- cache 1 p2" not in out or "- (no topic) 3 p0, 2 p1" not in out \
                    or "Propose topics, not question sets" not in out or "how many questions each settles" not in out or "--set" not in out \
                    or "the other next step by priority" not in out or "start round --proposal <n>" not in out \
                    or "`summary`" not in out or "`estimate`" not in out or "asking.md's Question format" not in out \
                    or "start round --topic" in out:
                raise ValueError(f"protocol next must count the open questions by topic and priority and tell the lead to weigh them:\n{out}")
            if "`title` about 60, `summary` 240, `why` 240" not in out:  # r9-q34: the target lengths, not the refusal threshold
                raise ValueError(f"protocol next names the proposal rows' target lengths:\n{out}")
            if "Open questions by topic" not in proto("next", cwd=repo).stdout:
                raise ValueError("the topic counts print every time, not once between compactions")
            # The printed example passes the check it describes (r28, r30, r34: quoted "<n>" estimates were copied and refused).
            example = json.loads(re.search(r'\{"rounds": .*?\}\]\}', out).group(0))
            proto("next", "--set", stdin={"rounds": [{k: v for k, v in one.items() if k != "ids"} for one in example["rounds"]]}, cwd=repo)
            good = {"rounds": [{"title": "Member questions", "summary": "How the members share one cache, and what that leaves open.",
                                "estimate": {"questions": 2, "unblocks": 6}, "why": "same module as the context read; p1 first", "fresh": False},
                               {"title": "Plain question", "summary": "A question no member covers, the highest priority outside a milestone.",
                                "estimate": {"questions": 1, "unblocks": 3}, "why": "highest priority outside a milestone", "fresh": True,
                                "ids": ["fx-n1"]}]}
            stored = {"rounds": [good["rounds"][0], {**good["rounds"][1], "idTitles": {"fx-n1": "Plain p0?"}}]}  # the board's title of each leading id
            refused("next", "--set", stdin={"rounds": [{**good["rounds"][0], "extra": 1}]}, needle="unknown fields extra", cwd=repo)
            refused("next", "--set", stdin={**good, "compact": {"keep": "x"}}, needle="unknown fields compact", cwd=repo)
            refused("next", "--set", stdin={"rounds": [{**good["rounds"][0], "premise": "old field"}]}, needle="unknown fields premise", cwd=repo)
            errors = proto("next", "--set", stdin={"rounds": [{"ids": [], "title": "x" * 76, "why": "", "fresh": "yes", "estimate": {"questions": "many"}}] * 4, "extra": 1},
                           ok=False, cwd=repo).stderr
            for needle in ("unknown fields extra", "`rounds` holds at most 3, not 4", "rounds[0]: `ids`, when given, lists the question ids that must lead",
                           "rounds[0]: `title` is 76 characters, over the limit of 75", "rounds[0]: `summary` must be a non-empty string",
                           "rounds[0]: `estimate` is your estimate as whole numbers", "rounds[0]: `why` must be a non-empty string",
                           "rounds[0]: `fresh` must be true or false", "rounds[3]: `fresh` must be true or false"):
                if needle not in errors:
                    raise ValueError(f"protocol next --set must list every error in one refusal, missing {needle!r}:\n{errors}")
            # Plain words: no question id and no board id in a title or summary (a hyphenated word is no id unless the board knows it).
            for field in ("title", "summary"):
                for text, needle in (("Settle q12 first", "names q12"), ("Settle fx-n1 first", "names fx-n1"), ("Why q7 and fx-n2", "names q7, fx-n2")):
                    refused("next", "--set", stdin={"rounds": [{**good["rounds"][0], field: text}]}, needle=f"rounds[0]: `{field}` {needle}", cwd=repo)
            proto("next", "--set", stdin={"rounds": [{**good["rounds"][0], "title": "The step-back follow-up", "summary": "A follow-up on the step-back pass."}]}, cwd=repo)
            refused("next", "--set", stdin={"rounds": [{**good["rounds"][1], "ids": ["fx-n1", "fx-gone"]}]}, needle="rounds[0]: `ids` names fx-gone, which the board does not know", cwd=repo)
            refused("next", "--set", stdin={"rounds": [{**good["rounds"][1], "ids": ["fx-n1"]}]}, needle="`ids` need a board", cwd=plain)
            # A title above 60 and within 75 is stored with one warning line for its row; at 60 it gets none.
            band = proto("next", "--set", stdin={"rounds": [{**good["rounds"][0], "title": "t" * 61}, good["rounds"][1]]}, cwd=repo).stdout
            if band.count("keep it to about") != 1 or "rounds[0]: title is 61 characters; keep it to about 60 (refused over 75)" not in band:
                raise ValueError(f"a proposal title in the band is stored with one warning:\n{band}")
            if "keep it to about" in proto("next", "--set", stdin={"rounds": [{**good["rounds"][0], "title": "t" * 60}]}, cwd=repo).stdout:
                raise ValueError("a proposal title at the target gets no warning")
            proto("next", "--set", stdin={"rounds": [good["rounds"][0]]}, cwd=repo)
            proto("next", "--set", stdin=good, cwd=repo)
            out = proto("next", cwd=repo).stdout
            if "1. Member questions · ~2 questions · unblocks ~6 items · How the members share one cache, and what that leaves open. · keeps the context · same module" not in out \
                    or "2. Plain question · ~1 question · unblocks ~3 items · A question no member covers, the highest priority outside a milestone. · leads with fx-n1 · wants a fresh context" not in out \
                    or "compaction keeps" in out:
                raise ValueError(f"protocol next must print the stored proposal:\n{out}")
            if shown(cwd=repo)["next"] != stored:
                raise ValueError(f"show --json next carries the stored proposal while no round is open: {shown(cwd=repo)['next']}")
            proto("next", "--set", stdin={"rounds": []}, cwd=repo)  # nothing proposed: the console offers a compaction
            if shown(cwd=repo)["next"] != {"rounds": []} or "no rounds" not in proto("next", cwd=repo).stdout:
                raise ValueError(f"a proposal without rounds shows an empty list: {shown(cwd=repo)['next']}")
            # A stored row without a title shows and starts nowhere: show --json and `--proposal` number the same rows.
            edit_state(lambda document: document.__setitem__("proposal", {"rounds": [{"why": "untitled", "fresh": False}, {"title": "Second", "why": "w", "fresh": False}]}))
            if [row["title"] for row in shown(cwd=repo)["next"]["rounds"]] != ["Second"] or "1. Second" not in proto("next", cwd=repo).stdout:
                raise ValueError("a stored row without a title must show nowhere")
            # A stored proposal an older engine wrote (ids, a premise, no summary or estimate, a compact field) reads without a crash and
            # shows with its title alone.
            edit_state(lambda document: document.__setitem__("proposal", {"rounds": [{"ids": ["fx-n1"], "title": "Old row", "premise": "an old premise", "why": "older", "fresh": True}],
                                                                           "compact": {"keep": "old"}}))
            out = proto("next", cwd=repo).stdout
            if "1. Old row · leads with fx-n1 · wants a fresh context · older" not in out or "an old premise" in out or shown(cwd=repo)["next"]["rounds"][0]["title"] != "Old row":
                raise ValueError(f"an older stored proposal must read without a crash:\n{out}")
            # r37-q207: the lead's inbox step: finds held for its person and its person's inbox, from the board's queue lists.
            find = {"id": "fx-f1", "status": "open", "type": "bug", "priority": 2, "holder": "user", "title": "Find for ben",
                    "labels": ["for:ben", "queue:anna"], "blockedBy": []}
            sent = {**find, "id": "fx-i1", "holder": None, "title": "Sent to anna", "labels": ["for:anna"]}
            before_inbox = config.read_text(encoding="utf-8")
            configure(health={"counts": counts, "items": {"forUser": [find]},
                              "queues": {"view": "anna", "others": {}, "unrouted": [sent], "blocking": [], "toSend": [find], "inbox": [sent]}})
            out = proto("next", cwd=repo).stdout
            held, _, mailbox = out.partition("Your inbox")
            if "Finds held for you to check" not in held or "fx-f1" not in held.split("Finds held for you to check")[1] or "for ben" not in held \
                    or "fx-i1" not in mailbox or "send, keep or close" not in out or "take, pass on or close with a reason" not in out \
                    or "Keep or take: board route <you> <id>; send or pass on: board send <person> <id>" not in out \
                    or "waiting on the user" in out.split("Finds held for you to check")[0] and "fx-f1" in out.split("Finds held for you to check")[0]:
                raise ValueError(f"protocol next must list the finds held for the person and the inbox, apart from the open items:\n{out}")
            config.write_text(before_inbox, encoding="utf-8")
            if "Your inbox" in proto("next", cwd=repo).stdout:
                raise ValueError("an unshared board's protocol next has no inbox step")
            proto("next", "--set", stdin=good, cwd=repo)
            proto("start", "round", cwd=repo)
            if shown(cwd=repo)["next"] is not None or "No proposal stored." not in proto("next", cwd=repo).stdout:
                raise ValueError("start round must clear the stored proposal")
            refused("next", "--set", stdin=good, needle="is open: propose the next rounds once it closes", cwd=repo)
            proto("abandon", cwd=repo)
            # `start round --proposal <n>` starts the stored row: its topic (`<title>: <summary>`), its leading ids, and its title and
            # summary as the round's own; the proposal is spent, and a refusal spends nothing.
            proto("next", "--set", stdin=good, cwd=repo)
            refused("start", "round", "--proposal", "3", needle="no proposal row 3: the stored proposal has 2", cwd=repo)
            refused("start", "round", "--proposal", "0", needle="no proposal row 0", cwd=repo)
            refused("start", "round", "--proposal", "2", "--topic", "x", needle="--proposal takes the row's topic", cwd=repo)
            refused("start", "round", "--proposal", "2", "fx-n2", needle="--proposal takes the row's ids", cwd=repo)
            refused("start", "release", "--proposal", "1", needle="start release takes record ids only", cwd=repo)
            if shown(cwd=repo)["next"] != stored:
                raise ValueError("a refused start must leave the proposal stored")
            out = proto("start", "round", "--proposal", "2", cwd=repo, prepass=False).stdout
            topic = "Plain question: A question no member covers, the highest priority outside a milestone."
            if "Named for this round: fx-n1." not in out or "Open items (" not in out:
                raise ValueError(f"--proposal starts the row's topic round on its leading ids:\n{out}")
            if f"Topic: {topic}" not in proto("step", stdin={"pass": "step-back", "summary": "No change."}, cwd=repo).stdout:
                raise ValueError("--proposal's topic reaches the round's Collect")
            refused("start", "round", "--proposal", "1", needle="is open at collect", cwd=repo)  # the open run is named, not a missing proposal
            started = shown(cwd=repo)
            if (started["title"], started["summary"], started["next"]) != ("Plain question", good["rounds"][1]["summary"], None) \
                    or json.loads((session_dir / "state.json").read_text())["round"]["topic"] != topic:
                raise ValueError(f"the round takes the proposal's title and summary at once, and the proposal is spent: {started}")
            # Stage keeps them: a report without `round` is accepted and its text says to replace them where the questions differ.
            proto("step", stdin={"classes": {"fx-n1": "user"}}, cwd=repo)
            staged = proto("step", stdin={"select": ["fx-n1"]}, cwd=repo).stdout
            if "keeps the proposal's `title` and `summary`" not in staged or "where the selected questions differ from the proposal" not in staged \
                    or "with a round `title` and `summary`" in staged:
                raise ValueError(f"Stage names the proposal's title and summary and says when to replace them:\n{staged}")
            proto("step", stdin={"questions": [question("Plain?", board="fx-n1")]}, cwd=repo)
            if (shown(cwd=repo)["title"], shown(cwd=repo)["summary"]) != ("Plain question", good["rounds"][1]["summary"]):
                raise ValueError("a Stage report without `round` keeps the proposal's title and summary")
            proto("abandon", cwd=repo)
            refused("start", "round", "--proposal", "1", needle="no proposal stored", cwd=repo)
            proto("next", "--set", stdin=good, cwd=repo)
            proto("start", "round", "--proposal", "2", cwd=repo)
            proto("step", stdin={"classes": {"fx-n1": "user"}}, cwd=repo)
            proto("step", stdin={"select": ["fx-n1"]}, cwd=repo)
            proto("step", stdin={"round": {"title": "Narrower", "summary": "Only the fallback of the plain question."}, "questions": [question("Plain?", board="fx-n1")]}, cwd=repo)
            if (shown(cwd=repo)["title"], shown(cwd=repo)["summary"]) != ("Narrower", "Only the fallback of the plain question."):
                raise ValueError("a Stage report with `round` replaces the proposal's title and summary")
            proto("abandon", cwd=repo)
            # A row stored before the swap starts with its title alone and Stage asks for the rest.
            edit_state(lambda document: document.__setitem__("proposal", {"rounds": [{"ids": ["fx-n1"], "title": "Old row", "premise": "an old premise", "why": "older", "fresh": True}]}))
            out = proto("start", "round", "--proposal", "1", cwd=repo).stdout
            if "Topic: Old row." not in out or (shown(cwd=repo)["title"], shown(cwd=repo)["summary"]) != ("Old row", None):
                raise ValueError(f"an old row starts with its title as the topic:\n{out}")
            proto("step", stdin={"classes": {"fx-n1": "user"}}, cwd=repo)
            staged = proto("step", stdin={"select": ["fx-n1"]}, cwd=repo).stdout
            if "with a round `title` and `summary`" not in staged:
                raise ValueError(f"a round without a stored summary asks Stage for its title and summary:\n{staged}")
            refused("step", stdin={"questions": [question("Plain?", board="fx-n1")]}, needle="`round` needs a plain-words", cwd=repo)
            proto("abandon", cwd=repo)
            # r24-q104: a topic round's pre-pass prints the whole open list every time and its Collect carries the grouping steer;
            # a bare or named round prints the list once between compactions.
            topic = "Member questions: members share one cache"
            for named in ([], ["fx-n1"]):
                out = proto("start", "round", "--topic", topic, *named, cwd=repo, prepass=False).stdout
                if "Open items (" not in out or "listed earlier" in out or (named and "Named for this round: fx-n1." not in out):
                    raise ValueError(f"a topic round's pre-pass prints the whole list:\n{out}")
                out = proto("step", stdin={"pass": "step-back", "summary": "No change."}, cwd=repo).stdout
                if f"Topic: {topic}." not in out or "Group by default" not in out or "a round of a single question names why no other shares one" not in out \
                        or "Open items (" in out or "- fx-a" in out:
                    raise ValueError(f"a topic round's Collect carries the grouping steer and does not list again:\n{out}")
                if f'"topic": "{topic}"' not in json.dumps(json.loads((session_dir / "state.json").read_text())["round"]):
                    raise ValueError("the round keeps its topic")
                proto("abandon", cwd=repo)
            out = proto("start", "round", cwd=repo).stdout
            if "listed earlier" not in out or "Topic:" in out or "Group by default" in out:
                raise ValueError(f"a round without a topic prints the list once between compactions:\n{out}")
            proto("abandon", cwd=repo)
            refused("start", "release", "--topic", "x", needle="start release takes record ids only", cwd=repo)
            configure()

            # H: answers that release held questions continue the round (r11 q42): a chain releases batch by batch, each with a
            # scoped rerun (path pass and refine pair on its ids, fresh Base loop, lean pass, challenge-rulings), one Record at the end.
            out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Chain A?", "Chain B?", "Chain C?"]}, cwd=repo).stdout
            points = re.findall(r"(pt\d+) \[pasted\]", out)
            proto("step", stdin={"classes": {point: "user" for point in points}}, cwd=repo)
            proto("step", stdin={"select": points}, cwd=repo)
            proto("step", cwd=repo, stdin={**ROUND_INFO, "questions": [
                question("Chain A?", key="a", **{"for": points[0]}), question("Chain B?", key="b", waitsOn=["a"], **{"for": points[1]}),
                question("Chain C?", key="c", waitsOn=["b"], **{"for": points[2]})]})
            chain = [q["id"] for q in shown(cwd=repo)["questions"]]
            converge(cwd=repo)
            first = shown(cwd=repo)
            if [q["question"] for q in first["batch"]["questions"]] != ["Chain A?"] \
                    or [q["status"] for q in first["questions"]] != ["asked", "held", "held"]:
                raise ValueError(f"protocol chain: only the unheld question goes out first: {first}")
            for position, (asked_text, next_id_) in enumerate((("Chain A?", chain[1]), ("Chain B?", chain[2])), 1):
                released = json.loads(proto("answer", "--origin", "dialog", cwd=repo, stdin={
                    "marker": shown(cwd=repo)["batch"]["marker"], "answers": {asked_text: "Keep"}}).stdout)
                if released["step"] != "check" or released["check"]["cycle"] != 1 or released["batch"] is not None \
                        or (released["pending"]["command"], released["pending"]["args"]) != ("step-back", f"goal foundations on {next_id_}") \
                        or f"released {next_id_} from held" not in released["note"].splitlines()[0] \
                        or {q["id"]: q["status"] for q in released["questions"]}[chain[0]] != "answered":
                    raise ValueError(f"protocol chain step {position}: the answer releases {next_id_} into a scoped rerun: {released}")
                seen = []
                while True:  # the scoped path and options passes, a fresh Base loop, the scoped refine pair, the lean pass, challenge-rulings
                    view = shown(cwd=repo)
                    if view["step"] != "check" or not view["pending"] or view["batch"]:
                        break
                    seen.append((view["pending"]["command"], view["pending"]["args"]))
                    proto("step", stdin={"pass": view["pending"]["command"], "updates": [], "checked": ["every question"]}, cwd=repo)
                lenses = ("goal foundations", "decisions clean overfit mechanics", "assumptions board sources probe", "assumptions sources probe")
                if not (seen[0] == ("step-back", f"goal foundations on {next_id_}") and seen[1] == ("step-back", f"options on {next_id_}")
                        and seen[2] == ("step-back", "") and seen[3] == ("ground", "")
                        and seen[4] == ("step-back", f"{lenses[1]} on {next_id_}") and seen[5] == ("ground", f"{lenses[2]} on {next_id_}")
                        and seen[6][1] == f"{lenses[3]} on {next_id_}" and seen[-1] == ("challenge-rulings", "")):
                    raise ValueError(f"protocol chain step {position}: the scoped rerun runs the full sequence on the released id: {seen}")
                batch = shown(cwd=repo)["batch"]
                if [q["question"] for q in batch["questions"]] != [f"Chain {'BC'[position - 1]}?"]:
                    raise ValueError(f"protocol chain step {position}: the next batch asks the released question: {batch}")
            proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": shown(cwd=repo)["batch"]["marker"], "answers": {"Chain C?": "Keep"}})
            after_answers(cwd=repo)
            if shown(cwd=repo)["step"] != "record":
                raise ValueError(f"protocol chain: Record follows once the last released question is answered: {shown(cwd=repo)}")
            # Record takes no `defer` (r9-q40): a deferral is the verb, which takes the dependents along.
            refused("step", cwd=repo, needle="Record takes no `defer`", stdin={
                "records": {qid: {"rationale": "R.", "ruleOwner": "docs/c.md#c"} for qid in chain}, "defer": {chain[0]: "later"}})
            out = proto("step", cwd=repo, stdin={"records": {qid: {"rationale": "R.", "ruleOwner": "docs/c.md#c"} for qid in chain}}).stdout
            round_events = [e["event"] for e in (json.loads(row) for row in (state / "0000-lead0001.protocol" / "history.jsonl").read_text().splitlines())
                            if e.get("round") == out.split()[0]]
            if not re.search(rf"recorded {', '.join(chain)} · round closed", out.splitlines()[0]) or round_events.count("continued") != 2 \
                    or round_events.count("recorded") != 3 or round_events.count("closed") != 1 or round_events.count("asked") != 3 \
                    or len(list(notes.glob(f"{out.split()[0]}-q*.md"))) != 3:
                raise ValueError(f"protocol chain: one Record writes all three: {round_events}\n{out}")

            # Log lines (r11 q43), as the pane's Log reads them.
            log_line = engine_module.words.log_text
            if log_line({"event": "pass", "command": "ground", "changes": 0, "summary": "No change: premises hold"}) != "ground: no change: premises hold" \
                    or log_line({"event": "pass", "command": "ground", "changes": 0, "summary": "no changes."}) != "ground: no change" \
                    or log_line({"event": "pass", "command": "ground", "changes": 0, "summary": "Nothing moved"}) != "ground: no change: Nothing moved" \
                    or log_line({"event": "pass", "command": "step-back", "kind": "path", "scoped": ["q5"], "questions": ["q5"]}) != "step-back (path q5): q5 changed" \
                    or log_line({"event": "pass", "command": "step-back", "kind": "refine"}) != "step-back (refine): no change" \
                    or log_line({"event": "pass", "command": "ground", "kind": "lean", "scoped": ["q39", "q40"]}) != "ground (lean q39 q40): no change" \
                    or log_line({"event": "classified", "classes": {}}) != "classified 0 points" \
                    or log_line({"event": "classified", "classes": {"user": 2}}) != "classified 2 points: 2 user" \
                    or engine_module.words.recorded_line([{"question": "q39", "board": "fx-1"}, {"question": "q40", "board": "fx-2"}]) != "recorded q39, q40 → fx-1, fx-2" \
                    or engine_module.words.recorded_line([{"question": "q39", "board": None}, {"question": "q40"}]) != "recorded q39, q40 → files":
                raise ValueError("protocol log lines: strip a leading 'no change', name the pass kind, 'classified 0 points', merge recorded lines")
            configure()

            # agents r11-q42: a question recording onto an item that already holds a decision record revises it in place: the
            # Record step prints the old record, a report without `decision` is refused, and the record keeps the old Question
            # and Alternatives with the reported Decision.
            prior = ("## Question\nAccept the grid design with six choices?\n\n## Alternatives Considered\n- Hold it\n\n"
                     "## Decision\nAccept, six choices.\n\n## Rationale\nReviewed.\n\n## Rule owner\ndocs/x.md\n")
            configure(health={"counts": counts, "items": {"ratification": [
                {"id": "fx-p", "status": "needs_ratification", "type": "decision", "title": "Grid design", "priority": 1, "blockedBy": []}]}},
                      items={"fx-p": {"status": "needs_ratification", "issue_type": "decision", "title": "Grid design", "description": prior}})
            proto("start", "round", cwd=repo)
            proto("step", stdin={"classes": {"fx-p": "user"}}, cwd=repo)
            proto("step", stdin={"select": ["fx-p"]}, cwd=repo)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Ratify the grid design?", board="fx-p")]}, cwd=repo)
            converge(cwd=repo)
            asked = shown(cwd=repo)
            proto("answer", "--origin", "dialog", stdin={"marker": asked["batch"]["marker"], "answers": {"Ratify the grid design?": "Keep"}}, cwd=repo)
            qid = asked["questions"][0]["id"]
            if shown(cwd=repo)["step"] != "record":
                proto("step", stdin={"pass": "challenge-rulings", "updates": [], "checked": {qid: "held"}, "rulings": []}, cwd=repo)
            step_text = proto("show", cwd=repo).stdout
            if "revises the record on its item in place" not in step_text or "    Accept, six choices." not in step_text:
                raise ValueError(f"the Record step must print the record a question revises in place:\n{step_text}")
            refused("step", stdin={"records": {qid: {"rationale": "Ratified.", "ruleOwner": "docs/x.md"}}},
                    needle="fx-p already holds a decision record, which this one revises in place: give `decision`", cwd=repo)
            calls()
            proto("step", stdin={"records": {qid: {"decision": "Accept, six choices; ratified.", "rationale": "Ratified.", "ruleOwner": "docs/x.md"}}}, cwd=repo)
            written = next(Path(c["args"][3]).read_text() for c in calls() if c["args"][:3] == ["ruling", "record", "fx-p"])
            if not written.startswith("## Question\nAccept the grid design with six choices?\n\n## Alternatives Considered\n- Hold it\n\n"
                                      "## Decision\nAccept, six choices; ratified.\n"):
                raise ValueError(f"a record revised in place keeps the old Question and Alternatives:\n{written}")
            configure()

            # R: a release run (r3-q7, r4-q12..q19): the default set (the session's held decided records), refusals, a contained
            # drop that lapses the typed approval into a dialog, owner checks, a resumable release, spreads, Codex.
            docs = repo / "docs"
            docs.mkdir(exist_ok=True)
            (docs / "x.md").write_text("# X\n\n## Approved dependencies, settlement and retry — implementation pending\n\n"
                                       "```\n## Not a heading\n```\n<a id=\"explicit-one\"></a>\n", encoding="utf-8")
            (docs / "y.md").write_text("# Y\n", encoding="utf-8")
            (docs / "flat.md").write_text("Plain text, no headings.\n", encoding="utf-8")
            anchor = "approved-dependencies-settlement-and-retry--implementation-pending"
            # A session holding no decided record has no default set; a cwd without a board refuses a release outright.
            refused("start", "release", needle="a release needs a board", cwd=plain)
            out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["File only?"]}, cwd=repo).stdout
            point = re.search(r"(pt\d+) \[pasted\]", out).group(1)
            proto("step", stdin={"classes": {point: "user"}}, cwd=repo)
            proto("step", stdin={"select": [point]}, cwd=repo)
            proto("step", stdin={**ROUND_INFO, "questions": [question("File only?", **{"for": point})]}, cwd=repo)
            converge(cwd=repo)
            asked = shown(cwd=repo)
            proto("answer", "--origin", "dialog", stdin={"marker": asked["batch"]["marker"], "answers": {"File only?": "Keep"}}, cwd=repo)
            closed = proto("step", stdin={"records": {asked["questions"][0]["id"]: {"rationale": "R.", "ruleOwner": "o"}}}, cwd=repo).stdout
            if "next: release" in closed.splitlines()[0]:
                raise ValueError(f"a round without board records must not name the release: {closed}")
            refused("start", "release", needle="this session holds no decided records; name the ids", cwd=repo)
            # A board round recording two records closes naming the release (r4-q15); nothing starts by itself.
            configure(health={"counts": counts, "items": {"questions": [
                {"id": "fx-r1", "status": "open", "type": "decision", "title": "R1?", "priority": 1, "blockedBy": []},
                {"id": "fx-r2", "status": "open", "type": "decision", "title": "R2?", "priority": 1, "blockedBy": []}]}},
                      items={rid: {"status": "decided", "issue_type": "decision", "title": rid.upper(), "assignee": "lead0001"}
                             for rid in ("fx-r1", "fx-r2")})
            proto("start", "round", cwd=repo)
            proto("step", stdin={"classes": {"fx-r1": "user", "fx-r2": "user"}}, cwd=repo)
            proto("step", stdin={"select": ["fx-r1", "fx-r2"]}, cwd=repo)
            proto("step", stdin={**ROUND_INFO, "questions": [question("R1?", board="fx-r1"), question("R2?", board="fx-r2")]}, cwd=repo)
            converge(cwd=repo)
            asked = shown(cwd=repo)
            # The numbered batch round-trips: answers are keyed by the issued text, the number included.
            if [q["question"] for q in asked["batch"]["questions"]] != ["1. R1?", "2. R2?"]:
                raise ValueError(f"a batch of two numbers its dialog questions: {asked['batch']}")
            proto("answer", "--origin", "dialog", stdin={"marker": asked["batch"]["marker"], "answers": {"1. R1?": "Keep", "2. R2?": "Keep"}}, cwd=repo)
            if [q["status"] for q in shown(cwd=repo)["questions"]] != ["answered", "answered"]:
                raise ValueError(f"a numbered batch answered through the dialog path records both: {shown(cwd=repo)['questions']}")
            round_id = asked["round"]
            if shown(cwd=repo)["next"] is not None:
                raise ValueError("an open round has no next run")
            closed = proto("step", stdin={"records": {q["id"]: {"rationale": "R.", "ruleOwner": "docs/x.md"} for q in asked["questions"]}},
                           cwd=repo).stdout
            if not re.fullmatch(r"r\d+ · recorded q\d+, q\d+ · round closed · next: release \(/release-round or ask\)", closed.splitlines()[0]) \
                    or shown(cwd=repo)["round"] is not None or shown(cwd=repo)["next"] != {"release": {"count": 2}}:
                raise ValueError(f"a round with board records must close naming the release:\n{closed}")
            rule_owner = f"## Question\nR1?\n\n## Rule owner\ndocs/x.md#{anchor}; fx-pend\n"
            configure(items={"fx-r1": {"status": "decided", "issue_type": "decision", "title": "R1", "assignee": "lead0001",
                                       "description": rule_owner},
                             "fx-r2": {"status": "decided", "issue_type": "decision", "title": "R2", "assignee": "lead0001"},
                             "fx-old": {"status": "released", "issue_type": "decision"},
                             "fx-q1": {"status": "open", "issue_type": "decision"},
                             "fx-hq": {"status": "in_progress", "issue_type": "decision", "assignee": "other001"},
                             "fx-done": {"status": "closed"},
                             "fx-x": {"status": "decided", "issue_type": "decision", "title": "X", "assignee": "other001"},
                             "fx-g": {"status": "decided", "issue_type": "decision", "title": "G", "assignee": "gone0001"}},
                      position={"held": [{"id": "fx-x", "holder": "other001", "mark": "idle"},
                                         {"id": "fx-g", "holder": "gone0001", "mark": "gone"}]})
            # Ids another live (idle included) session holds are refused; a gone session's hold is taken.
            refused("start", "release", "fx-x", needle="held by another live session: fx-x (other001)", cwd=repo)
            refused("start", "release", "fx-done", needle="not decided records: fx-done", cwd=repo)
            refused("start", "release", "--no-board", str(tmp / "no-such-folder"), needle="is no folder of records", cwd=repo)
            calls()
            proto("start", "release", "fx-g", cwd=repo)
            if ["take", "fx-g"] not in [c["args"] for c in calls()]:
                raise ValueError("start release must take a gone session's hold")
            refused("restart", "q1", needle="restart is a round verb", cwd=repo)
            refused("pass", "--origin", "plugin", stdin={"command": "release-round"}, needle="only the person approves", cwd=repo)
            refused("pass", "--origin", "composer", stdin={"command": "release-round", "args": "fx-x"},
                    needle="is open on fx-g: finish it", cwd=repo)
            if not proto("status", "--line", cwd=repo).stdout.startswith("protocol: release r") or "| fx-g | set |" not in proto("show", cwd=repo).stdout:
                raise ValueError(f"protocol status/show of a release: {proto('show', cwd=repo).stdout}")
            proto("abandon", cwd=repo)
            # A typed /release-round with no open run starts the release on the default set and stamps it (r4-q16).
            calls()
            started = json.loads(proto("pass", "--origin", "composer", stdin={"command": "release-round", "args": "", "pending": None},
                                       cwd=repo).stdout)
            if started["protocol"] != "release" or started["step"] != "recheck" or started["title"] != "the session's records" \
                    or [r["id"] for r in started["records"]] != ["fx-r1", "fx-r2"] \
                    or not started["note"].startswith(f"r{int(round_id[1:]) + 2} release · the session's records · release started") \
                    or ["claim", "fx-r1", "fx-r2"] in [c["args"] for c in calls()]:
                raise ValueError(f"a typed /release-round must start the default release and stamp it: {started}")
            refused("step", stdin={"records": {"fx-r1": "unchanged"}}, needle="no line for fx-r2", cwd=repo)
            refused("step", stdin={"records": {"fx-r1": "unchanged", "fx-r2": {"change": "c", "reach": "unsure"}}},
                    needle="unsure is spreads", cwd=repo)
            refused("step", stdin={"records": {"fx-r1": "unchanged", "fx-r2": {"change": "c", "reach": "contained"}}},
                    needle="names `why`", cwd=repo)
            # Contained: fx-r2 leaves the set, the rest continue; the stamp lapses with the changed set.
            refused("step", stdin={"records": {"fx-r1": "unchanged", "fx-r2": {"change": "c", "reach": "contained", "why": "w"}}},
                    needle='touches: "own"', cwd=repo)
            refused("step", stdin={"records": {"fx-r1": "unchanged", "fx-r2": {"change": "c", "reach": "contained", "why": "w", "touches": "unsure"}}},
                    needle="unsure is decision", cwd=repo)
            proto("step", stdin={"records": {"fx-r1": "unchanged", "fx-r2": {"change": "the store moved", "reach": "contained",
                                                                           "why": "no other record reads the store",
                                                                           "touches": "decision"}}}, cwd=repo)
            refused("step", stdin={"checks": {"fx-r1": {**nones, "doc": None}}}, needle="checks.fx-r1.doc", cwd=repo)
            refused("step", stdin={"checks": {"fx-r1": nones}, "closes": {"fx-q1": ["fx-r1"]}}, needle="no `answers` hit of fx-r1", cwd=repo)
            board_check = {"checks": {"fx-r1": {**nones, "revises": [{"item": "fx-old", "action": "supersede rule 2"}],
                                                "answers": [{"item": "fx-q1", "action": "answered: close"}]}},
                           "supersedes": [{"old": "fx-old", "new": "fx-r1", "partial": "Rule 2"}], "closes": {"fx-q1": ["fx-r1"]}}
            # A close board ruling release would refuse is refused here, while the report can change (not after the approval).
            refused("step", stdin={**board_check, "checks": {"fx-r1": {**board_check["checks"]["fx-r1"], "answers": [
                {"item": "fx-q1", "action": "close"}, {"item": "fx-hq", "action": "close"}]}}, "closes": {"fx-q1": ["fx-r1"], "fx-hq": ["fx-r1"]}},
                    needle="closes.fx-hq: held by other001", cwd=repo)
            proto("step", stdin=board_check, cwd=repo)
            refused("step", stdin={"rulings": [{"record": "fx-r1", "ruling": "x", "sure": True}]}, needle="needs why, alternative", cwd=repo)
            refused("step", stdin={"rulings": [{"record": "fx-r1", "ruling": "bundled", "alternative": "split", "fails": "nothing", "evidence": "decide.md", "sure": True}]},
                    needle="needs why", cwd=repo)  # an own ruling without its why is refused
            proto("step", stdin={"rulings": [{"record": "fx-r1", "ruling": "bundled", "why": "one record, no trade-off", "alternative": "split", "fails": "nothing",
                                              "evidence": "decide.md", "sure": True}]}, cwd=repo)
            dialog = shown(cwd=repo)
            records = {r["id"]: r["state"] for r in dialog["records"]}
            if dialog["step"] != "ask" or dialog["batch"] is None or dialog["batch"]["questions"][0]["header"] != "Release" \
                    or dialog["batch"]["questions"][0]["question"] != "Release the session's 1 record?" \
                    or "left the set: fx-r2" in json.dumps(dialog["batch"]) or records != {"fx-r1": "set", "fx-r2": "dropped"} \
                    or "left the set: fx-r2" not in proto("show", cwd=repo).stdout \
                    or not any("approval asked: left the set: fx-r2" in line["text"] for line in dialog["log"]):
                raise ValueError(f"a dropped record must lapse the typed approval into the dialog: {dialog}")
            result = json.loads(proto("answer", "--origin", "dialog", cwd=repo, stdin={
                "marker": dialog["batch"]["marker"], "answers": {dialog["batch"]["questions"][0]["question"]: "Release"}}).stdout)
            if result["step"] != "owners" or result["pending"] is not None or any("after answers" in line["text"] for line in result["log"]):
                raise ValueError(f"the dialog approval must lead to Owner writes, with no challenge after the answer: {result}")
            # Owner writes: each path exists, each anchor is a heading slug or an explicit anchor, each pending item is open,
            # and the record's Rule owner names each written path.
            for entry, needle in (({"written": {"path": "docs/missing.md"}}, "docs/missing.md does not exist"),
                                  ({"written": {"path": "docs/x.md", "anchor": "not-a-heading"}}, "has no heading or anchor #not-a-heading"),
                                  ({"written": {"path": "docs/x.md", "anchor": "x"}, "none": {"reason": "r"}}, "one of"),
                                  ({"written": {"path": "docs/flat.md", "anchor": "a"}}, "docs/flat.md has no headings: give the path without an anchor"),
                                  ({"written": {"path": "docs/y.md"}}, "does not name docs/y.md; fix the record text and run `board ruling record fx-r1 <file>`"),
                                  ({"pending": {"item": "fx-done"}}, "pending item fx-done is closed, not open")):
                refused("step", stdin={"owners": {"fx-r1": [entry]}}, needle=needle, cwd=repo)
            # Owner paths git ignores are refused; untracked (docs/x.md below) and installed paths are not.
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / ".gitignore").write_text(".scratch/\n", encoding="utf-8")
            (repo / ".scratch").mkdir(exist_ok=True)
            (repo / ".scratch" / "rule.md").write_text("# Rule\n", encoding="utf-8")
            refused("step", stdin={"owners": {"fx-r1": [{"written": {"path": ".scratch/rule.md"}}]}},
                    needle=".scratch/rule.md is ignored by git (e.g. .scratch): write the rule into a tracked or trackable owner", cwd=repo)
            # The release: board ruling release runs with the answered closes; it exits 1 (a revise supersede failed) and the other
            # supersede fails: the step stays and reruns only what remains.
            patch_config(releaseFail=["fx-r1"], supersedeFail=["fx-old"])
            calls()
            out = proto("step", stdin={"owners": {"fx-r1": [{"written": {"path": "docs/x.md", "anchor": anchor}},
                                                            {"written": {"path": "docs/x.md", "anchor": "explicit-one"}},
                                                            {"pending": {"item": "fx-pend"}}]}}, cwd=repo).stdout
            made = [c["args"] for c in calls() if engine_verb(c) in ("release", "supersede")]
            if made != [["ruling", "release", "fx-r1", "--closes", "fx-q1=fx-r1"], ["ruling", "supersede", "fx-old", "--with", "fx-r1", "--partial", "Rule 2"]] \
                    or shown(cwd=repo)["step"] != "release" or "exited 1" not in out or "reruns only what remains" not in out \
                    or "board ruling release fx-r1 closing fx-q1: exit 1" not in out.splitlines()[0]:
                raise ValueError(f"protocol release must report a partial failure and stay: {made}\n{out}")
            patch_config(releaseFail=[], supersedeFail=[])
            out = proto("step", stdin={}, cwd=repo).stdout
            made = [c["args"] for c in calls() if engine_verb(c) in ("release", "supersede")]
            if made != [["ruling", "release", "fx-r1"], ["ruling", "supersede", "fx-old", "--with", "fx-r1", "--partial", "Rule 2"]] \
                    or not re.match(r"r\d+ release · the session's records · .*superseded fx-old by fx-r1 · released fx-r1", out) \
                    or "- released fx-r1: R1" not in out or "- closed fx-q1: answered by released fx-r1" not in out \
                    or "- superseded fx-old by fx-r1 (rule: Rule 2)" not in out or "- dropped fx-r2" not in out \
                    or "decide.md Release 7" not in out or "`protocol next`" not in out or '"fresh": false' in out \
                    or shown(cwd=repo)["round"] is not None \
                    or "board ruling release" in out.splitlines()[0]:
                raise ValueError(f"protocol release rerun: {made}\n{out}")
            if "fresh false" not in proto("next", cwd=repo).stdout:
                raise ValueError("`protocol next` prints the proposal's format, which the release's close text leaves to it")
            # Nothing is left to take: a bare /release-round must not offer the dropped fx-r2 again (it goes to a round).
            refused("pass", "--origin", "composer", stdin={"command": "release-round", "args": "", "pending": None},
                    needle="was dropped or stopped by a release", cwd=repo)
            # Spreads: the run stops, nothing releases, and the close names the next round on the ids.
            patch_config(items={**json.loads(config.read_text())["items"],
                                "fx-s1": {"status": "decided", "issue_type": "decision", "title": "S1", "assignee": "lead0001"}})
            proto("start", "release", "fx-s1", cwd=repo)
            calls()
            out = proto("step", stdin={"records": {"fx-s1": {"change": "the premise moved", "reach": "spreads"}}}, cwd=repo).stdout
            if any(engine_verb(c) in ("release", "supersede", "unclaim") for c in calls()) \
                    or "Nothing released; fx-s1 stay decided and held" not in out or "opens with step-back" not in out \
                    or not out.splitlines()[0].endswith("next: a round on fx-s1") \
                    or shown(cwd=repo)["stopped"] != {"run": shown(cwd=repo)["stopped"]["run"], "reason": "fx-s1 changed: the premise moved", "ids": ["fx-s1"]}:
                raise ValueError(f"a spreading change must stop the release:\n{out}")
            # A typed /release-round on an open release approves it without a dialog when every ruling is sure and the set
            # is unchanged; during an open round it is refused.
            # A record waiting on an open item outside the set leaves it at the board check (board ruling release would refuse).
            patch_config(items={**json.loads(config.read_text())["items"],
                                "fx-s2": {"status": "decided", "issue_type": "decision", "title": "S2", "assignee": "lead0001"},
                                "fx-open": {"status": "in_review", "issue_type": "task", "title": "Open"}},
                         health={"counts": counts, "items": {"decided": [{"id": "fx-s2", "blockedBy": ["fx-open"]}]}})
            proto("start", "release", "fx-s1", "fx-s2", cwd=repo)
            proto("step", stdin={"records": {"fx-s1": "unchanged", "fx-s2": "unchanged"}}, cwd=repo)
            proto("step", stdin={"checks": {"fx-s1": nones, "fx-s2": nones}}, cwd=repo)
            if {r["id"]: (r["state"], r["reason"]) for r in shown(cwd=repo)["records"]}["fx-s2"] != ("dropped", "waits on fx-open (in_review)"):
                raise ValueError(f"a blocked record must leave the set at the board check: {shown(cwd=repo)['records']}")
            proto("abandon", cwd=repo)
            proto("start", "release", "fx-s1", cwd=repo)
            proto("pass", "--origin", "press", stdin={"command": "release-round", "args": "fx-s1", "pending": None}, cwd=repo)
            proto("step", stdin={"records": {"fx-s1": "unchanged"}}, cwd=repo)
            proto("step", stdin={"checks": {"fx-s1": nones}}, cwd=repo)
            proto("step", stdin={"rulings": []}, cwd=repo)
            approved = shown(cwd=repo)
            if approved["step"] != "owners" or approved["batch"] is not None \
                    or not any(line["text"] == "approved (press, /release-round)" for line in approved["log"]):
                raise ValueError(f"a pressed /release-round with sure rulings must approve without a dialog: {approved}")
            proto("abandon", cwd=repo)
            # Own contained change (r8-q36): the record stays, revised, with its corrected text written by board ruling record; a
            # typed /release-round lapses; the scoped step-back then ground run on it before the approval, which names it.
            patch_config(items={**json.loads(config.read_text())["items"],
                                "fx-s3": {"status": "decided", "issue_type": "decision", "title": "S3"}},
                         health={"counts": counts, "items": {}})
            fixed = repo / "fixed-s2.md"
            fixed.write_text("## Question\nS2?\n\n## Rule owner\ndocs/x.md\n", encoding="utf-8")
            own = {"change": "the rationale cited the wrong file", "reach": "contained", "why": "no other ruling reads it",
                   "touches": "own", "file": "fixed-s2.md"}
            # r24-q102: a correction that leaves the Decision text alone runs no scoped pass; the dialog still asks.
            kept_decision = "## Question\nS2?\n\n## Decision\nKeep it\n\n## Rationale\nOld.\n"
            patch_config(items={**json.loads(config.read_text())["items"],
                                "fx-s2": {**json.loads(config.read_text())["items"]["fx-s2"], "description": kept_decision}})
            (repo / "same-s2.md").write_text(kept_decision.replace("Old.", "New."), encoding="utf-8")
            proto("start", "release", "fx-s1", "fx-s2", cwd=repo)
            proto("step", stdin={"records": {"fx-s1": "unchanged", "fx-s2": {**own, "file": "same-s2.md"}}}, cwd=repo)
            proto("step", stdin={"checks": {"fx-s1": nones, "fx-s2": nones}}, cwd=repo)
            proto("step", stdin={"rulings": []}, cwd=repo)
            view = shown(cwd=repo)
            if view["step"] != "ask" or view["pending"] is not None or "Revised: fx-s2" not in view["batch"]["questions"][0]["question"]:
                raise ValueError(f"an unchanged Decision skips the scoped passes and still asks: {view['step']} {view['pending']}")
            proto("abandon", cwd=repo)
            patch_config(items={rid: {k: v for k, v in item.items() if k != "description"} for rid, item in json.loads(config.read_text())["items"].items()})
            proto("start", "release", "fx-s1", "fx-s2", cwd=repo)
            proto("pass", "--origin", "press", stdin={"command": "release-round", "args": "fx-s1 fx-s2", "pending": None}, cwd=repo)
            refused("step", stdin={"records": {"fx-s1": "unchanged", "fx-s2": {**own, "file": None}}}, needle="gives `file`", cwd=repo)
            calls()
            refused("step", stdin={"records": {"fx-s1": "unchanged", "fx-s2": {**own, "file": "missing-s2.md"}}},
                    needle="`board ruling record fx-s2 missing-s2.md` exited", cwd=repo)
            if shown(cwd=repo)["step"] != "recheck":
                raise ValueError("a failed board ruling record must leave the re-check where it was")
            calls()
            proto("step", stdin={"records": {"fx-s1": "unchanged", "fx-s2": own}}, cwd=repo)
            view = shown(cwd=repo)
            if ["ruling", "record", "fx-s2", "fixed-s2.md"] not in [c["args"] for c in calls()] \
                    or {r["id"]: r["state"] for r in view["records"]} != {"fx-s1": "set", "fx-s2": "revised"} \
                    or view["records"][1]["reason"] != f"changed (contained, own): {own['change']}" \
                    or not any(line["text"].startswith("revised fx-s2:") for line in view["log"]):
                raise ValueError(f"an own contained change must keep the record revised and write its text: {view}")
            proto("step", stdin={"checks": {"fx-s1": nones, "fx-s2": nones}}, cwd=repo)
            out = proto("step", stdin={"rulings": []}, cwd=repo).stdout
            view = shown(cwd=repo)
            if view["step"] != "scoped" or view["pending"] is None or view["pending"]["command"] != "step-back" \
                    or view["pending"]["args"] != "fx-s2" or "next: step-back pass on the revised fx-s2" not in out.splitlines()[0] \
                    or 'one short line' not in out:
                raise ValueError(f"the scoped step-back must wait on the revised ids before the approval: {view['step']} {view['pending']}\n{out}")
            refused("step", stdin={"pass": "ground", "records": {"fx-s2": "unchanged"}}, needle="`pass` is step-back", observe=False, cwd=repo)
            refused("step", stdin={"pass": "step-back", "records": {"fx-s2": "unchanged"}}, needle="no /step-back ran", observe=False, cwd=repo)
            proto("pass", "--origin", "model", stdin={"command": "step-back", "args": "", "pending": None}, cwd=repo)
            refused("step", stdin={"pass": "step-back", "records": {"fx-s2": "unchanged"}}, needle="ran without the revised records", observe=False, cwd=repo)
            proto("pass", "--origin", "model", stdin={"command": "step-back", "args": "fx-s2", "pending": view["pending"]["id"]}, cwd=repo)
            refused("step", stdin={"pass": "step-back", "records": {"fx-s1": "unchanged"}}, needle="not in the revised records: fx-s1", cwd=repo)
            refused("step", stdin={"pass": "step-back", "records": {}}, needle="no line for fx-s2", cwd=repo)
            out = proto("step", stdin={"pass": "step-back", "records": {"fx-s2": "unchanged"}, "summary": "holds"}, cwd=repo).stdout
            view = shown(cwd=repo)
            if view["step"] != "scoped" or view["pending"]["command"] != "ground" or view["pending"]["args"] != "fx-s2" \
                    or "step-back (scoped fx-s2): no change: holds" not in out.splitlines()[0]:
                raise ValueError(f"the scoped ground must follow the scoped step-back: {view['pending']}\n{out}")
            proto("step", stdin={"pass": "ground", "records": {"fx-s2": "unchanged"}}, cwd=repo)
            dialog = shown(cwd=repo)
            question_text = dialog["batch"]["questions"][0]["question"] if dialog["batch"] else ""
            if dialog["step"] != "ask" or "Revised: fx-s2 (the rationale cited the wrong file)" not in question_text \
                    or "revised: fx-s2 (the rationale cited the wrong file)" not in proto("show", cwd=repo).stdout \
                    or not any("approval asked: revised: fx-s2" in line["text"] for line in dialog["log"]) \
                    or any(line["text"].startswith("approved") for line in dialog["log"]):
                raise ValueError(f"a revised record must lapse the typed approval into a dialog that names it: {dialog}")
            proto("abandon", cwd=repo)
            # A pass that finds the user's decision touched drops the record; the pair runs once and the approval follows.
            proto("start", "release", "fx-s1", "fx-s2", cwd=repo)
            proto("step", stdin={"records": {"fx-s1": "unchanged", "fx-s2": own}}, cwd=repo)
            proto("step", stdin={"checks": {"fx-s1": nones, "fx-s2": nones}}, cwd=repo)
            proto("step", stdin={"rulings": []}, cwd=repo)
            proto("step", stdin={"pass": "step-back", "records": {"fx-s2": "unchanged"}}, cwd=repo)
            proto("step", stdin={"pass": "ground", "records": {"fx-s2": {"change": "the user chose the other store", "reach": "contained",
                                                                         "why": "only fx-s2", "touches": "decision"}}}, cwd=repo)
            dropped = {r["id"]: (r["state"], r["reason"]) for r in shown(cwd=repo)["records"]}
            if dropped["fx-s2"] != ("dropped", "changed (contained): the user chose the other store") or shown(cwd=repo)["step"] != "ask":
                raise ValueError(f"a scoped pass with a decision change must drop the record: {dropped}")
            proto("abandon", cwd=repo)
            if json.loads((session_dir / "state.json").read_text()).get("dropReasons", {}).get("fx-s2"):
                raise ValueError("a drop of an abandoned release must not leave a reason")
            # A stop's reason shows at the next round's Stage.
            proto("start", "release", "fx-s2", cwd=repo)
            proto("step", stdin={"records": {"fx-s2": {"change": "the user chose the other store", "reach": "spreads"}}}, cwd=repo)
            patch_config(health={"counts": counts, "items": {"decided": [
                {"id": "fx-s2", "status": "decided", "type": "decision", "title": "S2", "priority": 1, "blockedBy": []}]}})
            proto("start", "round", cwd=repo)
            proto("step", stdin={"classes": {"fx-s2": "user"}}, cwd=repo)
            out = proto("step", stdin={"select": ["fx-s2"]}, cwd=repo).stdout
            if "- fx-s2: fx-s2 changed: the user chose the other store" not in out:
                raise ValueError(f"a dropped record's reason must show at the next round's Stage:\n{out}")
            proto("abandon", cwd=repo)
            patch_config(health={"counts": counts, "items": {}})
            # A spread found by a scoped pass stops the run.
            proto("start", "release", "fx-s1", "fx-s2", cwd=repo)
            proto("step", stdin={"records": {"fx-s1": "unchanged", "fx-s2": own}}, cwd=repo)
            proto("step", stdin={"checks": {"fx-s1": nones, "fx-s2": nones}}, cwd=repo)
            proto("step", stdin={"rulings": []}, cwd=repo)
            proto("step", stdin={"pass": "step-back", "records": {"fx-s2": {"change": "other rulings read it", "reach": "spreads"}}}, cwd=repo)
            if shown(cwd=repo)["stopped"] is None or shown(cwd=repo)["stopped"]["ids"] != ["fx-s1", "fx-s2"]:
                raise ValueError(f"a spread in a scoped pass must stop the release: {shown(cwd=repo)}")
            stopped_reasons = json.loads((session_dir / "state.json").read_text())["dropReasons"]  # the revised fx-s2 gets the stop's reason
            if stopped_reasons.get("fx-s2") != "fx-s2 changed: other rulings read it" or stopped_reasons.get("fx-s1") != stopped_reasons["fx-s2"]:
                raise ValueError(f"every record of a stop gets the stop's reason, a revised one too: {stopped_reasons}")
            # Codex has no console to observe its runs: the text tells it to run the skill and report.
            subprocess.run(["bash", str(registry), "activate", "solo"], check=True,
                           env={**os.environ, **session_env(str(state)), **as_session("0000-cdx00002", "codex")})
            proto("start", "release", "fx-s3", cwd=repo, session="0000-cdx00002")
            proto("step", stdin={"records": {"fx-s3": {**own, "file": "fixed-s2.md"}}}, cwd=repo, session="0000-cdx00002")
            proto("step", stdin={"checks": {"fx-s3": nones}}, cwd=repo, session="0000-cdx00002")
            out = proto("step", stdin={"rulings": []}, cwd=repo, session="0000-cdx00002").stdout
            if "Run the step-back skill now with the argument `fx-s3`" not in out:
                raise ValueError(f"Codex must be told to run the scoped pass and report it:\n{out}")
            proto("step", stdin={"pass": "step-back", "records": {"fx-s3": "unchanged"}}, cwd=repo, session="0000-cdx00002", observe=False)
            proto("abandon", cwd=repo, session="0000-cdx00002")
            # Leading ids after the command name the set; the rest stays the skill's focus.
            named = json.loads(proto("pass", "--origin", "bridge", stdin={"command": "release-round", "args": "fx-s1 check the docs", "pending": None},
                                     cwd=repo).stdout)
            if [r["id"] for r in named["records"]] != ["fx-s1"] or named["title"] != "fx-s1":
                raise ValueError(f"/release-round <ids> must release those ids: {named}")
            proto("abandon", cwd=repo)

            # A release of a --no-board round's record files (r27-q243): same re-check, own rulings and approval; the board check is
            # skipped; the release appends the Released line to each file; no board call, though this session sits in a board repo.
            recs = tmp / "release-records"
            recs.mkdir()
            record_text = "## Question\n{q}\n\n## Decision\nKeep it\n\n## Rule owner\ndocs/x.md#{a}\n"
            for stem in ("r3-q3", "r5-q1", "r5-q2", "r12-q3", "r12-q4", "r12-q5"):
                (recs / f"{stem}.md").write_text(record_text.format(q=f"Title of {stem}?", a=anchor), encoding="utf-8")
            released_text = (recs / "r12-q4.md").read_text(encoding="utf-8") + "\n## Released\n2026-11-11, user in chat: \"Release all and go\".\n"
            (recs / "r12-q4.md").write_text(released_text, encoding="utf-8")
            calls()
            refused("start", "release", "q99", "--no-board", str(recs), needle="unknown record q99", cwd=repo)
            refused("start", "release", "q4", "--no-board", str(recs), needle="already released: r12-q4", cwd=repo)
            refused("start", "release", "q3", "--no-board", str(recs), needle="q3 names several records (r12-q3, r3-q3)", cwd=repo)
            # The default set is the newest round (numerically: r12 after r5) without a Released section.
            out = proto("start", "release", "--no-board", str(recs), cwd=repo).stdout
            started = shown(cwd=repo)
            if [r["id"] for r in started["records"]] != ["r12-q3", "r12-q5"] or started["title"] != "r12-q3, r12-q5" \
                    or "A bare release takes" in out or "Title of r12-q3?" not in out:
                raise ValueError(f"a bare no-board release takes the newest round's unreleased records: {started['records']}\n{out}")
            out = proto("abandon", cwd=repo).stdout
            if "decided, without a Released line" not in out or "held" in out.split("abandoned at its step")[-1]:
                raise ValueError(f"an abandoned no-board release says the files stay unreleased, not held:\n{out}")
            # Ids start it too (the id after the option as well); a release needs no board and uses none.
            proto("start", "release", "--no-board", str(recs), "q5", cwd=repo)
            if [r["id"] for r in shown(cwd=repo)["records"]] != ["r12-q5"]:
                raise ValueError(f"the id after --no-board names the record: {shown(cwd=repo)['records']}")
            proto("abandon", cwd=repo)
            proto("start", "release", "r12-q3", "q5", "--no-board", str(recs), cwd=repo)
            out = proto("step", stdin={"records": {"r12-q3": "unchanged", "r12-q5": "unchanged"}}, cwd=repo).stdout
            if out.count("Board check skipped: record files of a --no-board round have no board.") != 1 or shown(cwd=repo)["step"] != "own-rulings":
                raise ValueError(f"the board check is skipped in one line:\n{out}")
            proto("step", stdin={"rulings": []}, cwd=repo)
            dialog = shown(cwd=repo)
            option = dialog["batch"]["questions"][0]["options"][0]
            if dialog["step"] != "ask" or option["label"] != "Release" or "uncommitted" not in option["description"]:
                raise ValueError(f"the approval dialog names the uncommitted owner writes: {dialog['batch']}")
            proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": dialog["batch"]["marker"], "answers": {dialog["batch"]["questions"][0]["question"]: "Release"}})
            owners_text = proto("show", cwd=repo).stdout
            if "no commit by the engine or the session" not in owners_text:
                raise ValueError(f"the owner step says the writes stay uncommitted:\n{owners_text}")
            refused("step", stdin={"owners": {"r12-q3": [{"pending": {"item": "fx-pend"}}], "r12-q5": [{"none": {"reason": "r"}}]}},
                    needle="pending items need a board", cwd=repo)
            refused("step", stdin={"owners": {"r12-q3": [{"written": {"path": "docs/y.md"}}], "r12-q5": [{"none": {"reason": "r"}}]}},
                    needle="does not name docs/y.md; fix the record text and run edit ", cwd=repo)
            # r12-q5 already carries its block (a rerun's leftover): the release leaves it as it is and never adds a second.
            kept = (recs / "r12-q5.md").read_text(encoding="utf-8") + "\n## Released\n2026-01-01, user in chat: \"earlier\".\n"
            (recs / "r12-q5.md").write_text(kept, encoding="utf-8")
            out = proto("step", stdin={"owners": {"r12-q3": [{"written": {"path": "docs/x.md", "anchor": anchor}}],
                                                 "r12-q5": [{"none": {"reason": "covered"}}]}}, cwd=repo).stdout
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if (recs / "r12-q3.md").read_text(encoding="utf-8") != record_text.format(q="Title of r12-q3?", a=anchor) \
                    + f'\n## Released\n{today}, user in the question dialog: "Release".\n' \
                    or (recs / "r12-q5.md").read_text(encoding="utf-8") != kept \
                    or (recs / "r12-q4.md").read_text(encoding="utf-8") != released_text \
                    or shown(cwd=repo)["round"] is not None or "- released r12-q3: Title of r12-q3? (" not in out \
                    or "- released r12-q5: Title of r12-q5? (" not in out or "uncommitted" not in out or "Board" in out:
                raise ValueError(f"the release appends one Released block per file:\n{out}")
            if any(path.name.startswith(".") for path in recs.iterdir()) or calls():
                raise ValueError(f"a no-board release leaves no temp file and makes no board call: {calls()}")
            # The same ids are released now; the old round is next, and a write failure leaves the step to rerun.
            refused("start", "release", "r12-q3", "--no-board", str(recs), needle="already released: r12-q3", cwd=repo)
            fixed_file = repo / "fixed-r5.md"
            fixed_file.write_text(record_text.format(q="Title of r5-q1 corrected?", a=anchor), encoding="utf-8")
            proto("start", "release", "r5-q1", "r5-q2", "--no-board", str(recs), cwd=repo)
            proto("step", stdin={"records": {"r5-q1": {"change": "title", "reach": "contained", "why": "no other ruling reads it",
                                                       "touches": "own", "file": "fixed-r5.md"}, "r5-q2": "unchanged"}}, cwd=repo)
            if (recs / "r5-q1.md").read_text(encoding="utf-8") != fixed_file.read_text(encoding="utf-8") \
                    or {r["id"]: r["state"] for r in shown(cwd=repo)["records"]} != {"r5-q1": "revised", "r5-q2": "set"}:
                raise ValueError(f"an own change replaces the record file: {shown(cwd=repo)['records']}")
            proto("step", stdin={"rulings": []}, cwd=repo)
            dialog = shown(cwd=repo)
            if dialog["step"] != "ask" or "Revised: r5-q1" not in dialog["batch"]["questions"][0]["question"]:
                raise ValueError(f"an own correction with an unchanged Decision goes to the approval: {dialog['step']}")
            proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": dialog["batch"]["marker"], "answers": {dialog["batch"]["questions"][0]["question"]: "Release"}})
            recs.chmod(0o555)
            try:
                out = proto("step", stdin={"owners": {"r5-q1": [{"none": {"reason": "r"}}], "r5-q2": [{"none": {"reason": "r"}}]}}, cwd=repo).stdout
            finally:
                recs.chmod(0o755)
            if shown(cwd=repo)["step"] != "release" or "Released block not written" not in out \
                    or any("## Released" in (recs / f"r5-q{n}.md").read_text(encoding="utf-8") for n in (1, 2)):
                raise ValueError(f"a failed write must leave the release to rerun, files untouched:\n{out}")
            out = proto("step", stdin={}, cwd=repo).stdout
            out_again = [(recs / f"r5-q{n}.md").read_text(encoding="utf-8").count("## Released") for n in (1, 2)]
            if out_again != [1, 1] or shown(cwd=repo)["round"] is not None or "- released r5-q1" not in out:
                raise ValueError(f"the rerun writes each file's block once: {out_again}\n{out}")
            if calls():
                raise ValueError("the no-board release must make no board call")
            proto("start", "round", "--no-board", str(notes), stdin={"points": ["Busy?"]}, cwd=repo)
            refused("pass", "--origin", "composer", stdin={"command": "release-round"}, needle="the release starts once it closes", cwd=repo)
            proto("abandon", cwd=repo)

            # D: the default set (r13 q50): the decided records this session holds, a worker's holds included, read from the
            # board and counted at a close and at `protocol next`; `show` makes no board call. A stop gives each stopped record a
            # reason a bare release leaves out; a re-recording or a release clears it; an abandoned release changes nothing.
            leftover = {"rounds": [{"round": "r9", "ids": ["fx-gone"]}], "last": "r9", "consumedBy": "r9"}
            edit_state(lambda document: document.update(dropReasons={}, recorded=leftover, lastRecorded="r9"))  # old keys are ignored
            items = {rid: {"status": "decided", "issue_type": "decision", "title": rid.upper(), "assignee": holder}
                     for rid, holder in (("fx-d1", "lead0001"), ("fx-d2", "lead0001/worker01"), ("fx-d3", "lead0001"), ("fx-d4", "other001"))}
            patch_config(items=items)
            calls()
            if shown(cwd=repo)["next"] is not None or calls():
                raise ValueError("show makes no board call and offers nothing before the board was read")
            first = board_round("fx-d1", "fx-d2")
            board_round("fx-d3")
            calls()
            if shown(cwd=repo)["next"] != {"release": {"count": 3}} or calls():
                raise ValueError(f"the count is the decided records held here, a worker's included, another session's out: {shown(cwd=repo)['next']}")
            patch_config(items={**items, "fx-d5": {**items["fx-d3"], "title": "FX-D5"}})  # decided outside any round, held here
            if shown(cwd=repo)["next"] != {"release": {"count": 3}} or "count 4" in proto("next", cwd=repo).stdout:
                raise ValueError("show reads the saved count; `protocol next` reads the board")
            if shown(cwd=repo)["next"] != {"release": {"count": 4}}:
                raise ValueError(f"protocol next saves the count: {shown(cwd=repo)['next']}")
            bare = json.loads(proto("pass", "--origin", "composer", stdin={"command": "release-round", "args": "", "pending": None}, cwd=repo).stdout)
            if [r["id"] for r in bare["records"]] != ["fx-d1", "fx-d2", "fx-d3", "fx-d5"] or bare["title"] != "the session's records":
                raise ValueError(f"a bare release takes every decided record this session holds: {bare}")
            if "A bare release takes the decided records this session holds" not in proto("show", cwd=repo).stdout:
                raise ValueError("the release's first step must say what a bare release takes")
            patch_config(items=items)
            proto("abandon", cwd=repo)  # an abandoned release leaves everything as it was
            before = json.loads((session_dir / "state.json").read_text())
            proto("start", "release", "fx-d1", "fx-d2", cwd=repo)
            proto("step", stdin={"records": {"fx-d1": "unchanged", "fx-d2": {"change": "c", "reach": "contained", "why": "w", "touches": "decision"}}}, cwd=repo)
            proto("abandon", cwd=repo)
            after = json.loads((session_dir / "state.json").read_text())
            if after.get("dropReasons") != before.get("dropReasons") or after.get("releasable") != before.get("releasable") or shown(cwd=repo)["next"] != {"release": {"count": 4}}:
                raise ValueError("an abandoned release must change no drop reason and no count")
            # A named release that runs to its close: the released record clears, the dropped one is out of the default set.
            proto("start", "release", "fx-d1", "fx-d2", cwd=repo)
            proto("pass", "--origin", "press", stdin={"command": "release-round", "args": "fx-d1 fx-d2", "pending": None}, cwd=repo)
            proto("step", stdin={"records": {"fx-d1": "unchanged", "fx-d2": {"change": "c", "reach": "contained", "why": "w", "touches": "decision"}}}, cwd=repo)
            proto("step", stdin={"checks": {"fx-d1": nones}}, cwd=repo)
            proto("step", stdin={"rulings": []}, cwd=repo)
            dialog = shown(cwd=repo)["batch"]  # the drop lapses the typed approval into a dialog
            if "Corrections:\n- fx-d2 left the set: changed (contained): c" not in dialog["notice"]:
                raise ValueError(f"the approval prints the release's corrections:\n{dialog['notice']}")
            proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": dialog["marker"], "answers": {dialog["questions"][0]["question"]: "Release"}})
            proto("step", stdin={"owners": {"fx-d1": [{"none": {"reason": "covered by the rule"}}]}}, cwd=repo)
            dropped = json.loads((session_dir / "state.json").read_text())["dropReasons"]
            if list(dropped) != ["fx-d2"] or "changed (contained)" not in dropped["fx-d2"] or shown(cwd=repo)["next"] != {"release": {"count": 1}}:
                raise ValueError(f"a closed release records the dropped record's reason and counts the rest: {dropped} {shown(cwd=repo)['next']}")
            # A stop gives each stopped record a reason, named or bare; a bare release then leaves them out.
            proto("start", "release", cwd=repo)
            proto("step", stdin={"records": {"fx-d3": {"change": "the premise moved", "reach": "spreads"}}}, cwd=repo)
            reasons = json.loads((session_dir / "state.json").read_text())["dropReasons"]
            if sorted(reasons) != ["fx-d2", "fx-d3"] or "premise moved" not in reasons["fx-d3"] or shown(cwd=repo)["next"] is not None:
                raise ValueError(f"a stop must give each stopped record a reason and leave the default set empty: {reasons}")
            refused("start", "release", needle="was dropped or stopped by a release", cwd=repo)
            # A re-recording clears the reason: the record is in the default set again.
            board_round("fx-d3")
            again = json.loads((session_dir / "state.json").read_text())["dropReasons"]
            if "fx-d3" in again or shown(cwd=repo)["next"] != {"release": {"count": 1}}:
                raise ValueError(f"a re-recording must clear the drop reason: {again} {shown(cwd=repo)['next']}")
            edit_state(lambda document: document.update(dropReasons={}))
            # A named stop gives its reasons too.
            proto("start", "release", "fx-d3", cwd=repo)
            proto("step", stdin={"records": {"fx-d3": {"change": "moved", "reach": "spreads"}}}, cwd=repo)
            if list(json.loads((session_dir / "state.json").read_text())["dropReasons"]) != ["fx-d3"]:
                raise ValueError("a named stop must give its record a reason")
            edit_state(lambda document: document.update(dropReasons={}))
            # An unsure ruling leads the dialog, in full in the notice, the dialog without previews (r10-q37); a question during the release is told to abandon; a
            # person's Hold drops nothing, so a bare release takes the records again (r14 q52, q56).
            proto("start", "release", "fx-d3", cwd=repo)
            proto("step", stdin={"records": {"fx-d3": "unchanged"}}, cwd=repo)
            proto("step", stdin={"checks": {"fx-d3": nones}}, cwd=repo)
            long_ruling = "reveal issues a fresh secret after a breach " * 6
            proto("step", stdin={"rulings": [{"record": "fx-d3", "ruling": long_ruling, "why": "meets the secret rule", "alternative": "reveal refuses",
                                              "fails": "nothing", "evidence": "x", "sure": False}]}, cwd=repo)
            dialog = shown(cwd=repo)["batch"]["questions"][0]
            release_option = dialog["options"][0]
            approval_notice = shown(cwd=repo)["batch"]["notice"]
            if not approval_notice.startswith("**Release fx-d3**\n\n**My ruling:** ") or f"**My ruling:** {long_ruling.strip()} (fx-d3, unsure)\n- Why: meets the secret rule\n- Instead: reveal refuses\n- Why not: nothing" not in approval_notice \
                    or "Evidence" in approval_notice:
                raise ValueError(f"the approval prints the own rulings in full:\n{approval_notice}")
            if not dialog["question"].startswith("Release 1 record? Unsure: fx-d3 (reveal") or len(dialog["question"]) > 160 \
                    or any("preview" in option for option in dialog["options"]):
                raise ValueError(f"the dialog must lead with the unsure ruling and carry no preview: {dialog}")
            # The approval text is built from the release's reports: corrections, the board check (supersedes, closes, other hit rows).
            approval_ctx = type("Ctx", (), {})()
            approval_ctx.round = {"set": [{"id": "fx-a", "state": "revised", "change": "size"}, {"id": "fx-b", "state": "dropped", "reason": "premise"}],
                                  "supersedes": [{"old": "fx-o", "new": "fx-a", "partial": "Rule 2"}], "closes": {"fx-q": ["fx-a"]},
                                  "checks": {"fx-a": {"answers": [{"item": "fx-q", "action": "answered: close"}], "doc": [{"item": "README.md", "action": "owner write"}],
                                                      "revises": "none"}}, "rulings": []}
            if engine_module.render.approval_parts(approval_ctx) != {
                    "corrections": "- fx-a revised: size\n- fx-b left the set: premise",
                    "boardCheck": "- fx-o superseded by fx-a (rule: Rule 2)\n- fx-q closes, answered by fx-a\n- fx-a doc: README.md: owner write"}:
                raise ValueError(f"approval parts: {engine_module.render.approval_parts(approval_ctx)}")
            refused("start", "round", "--discussion", stdin={"points": [{"text": "x"}]}, needle="takes the same records again", cwd=repo)
            out = proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": shown(cwd=repo)["batch"]["marker"], "answers": {dialog["question"]: "Hold"}}).stdout
            reasons = json.loads((session_dir / "state.json").read_text()).get("dropReasons")
            closed_text = proto("show", cwd=repo).stdout
            if reasons or "ask what it was held for" not in out + closed_text or shown(cwd=repo)["next"] != {"release": {"count": 2}}:
                raise ValueError(f"a Hold must drop nothing and leave the records to a bare release: {reasons} {shown(cwd=repo)['next']}\n{out}\n{closed_text}")
            bare = json.loads(proto("pass", "--origin", "composer", stdin={"command": "release-round", "args": "", "pending": None}, cwd=repo).stdout)
            if "fx-d3" not in [r["id"] for r in bare["records"]]:
                raise ValueError(f"a bare release takes a held record again: {bare['records']}")
            proto("abandon", cwd=repo)
            edit_state(lambda document: document.update(dropReasons={}))
            patch_config(items={rid: row for rid, row in items.items() if rid != "fx-d3"})
            calls()
            proto("next", cwd=repo)
            if ["health", "--json", "--items", "decided"] not in [c["args"] for c in calls()] or shown(cwd=repo)["next"] != {"release": {"count": 2}}:
                raise ValueError("protocol next must read the board and save the count")
            patch_config(items=items)
            # Board check: a revision the set's texts name without a link is listed (board check --json), once, in the step's text.
            patch_config(check={"unlinkedRevisions": [
                {"id": "fx-d1", "other": "fx-old", "word": "revises", "old": "fx-old", "new": "fx-d1"},
                {"id": "fx-elsewhere", "other": "fx-else", "word": "replaces", "old": "fx-else", "new": "fx-elsewhere"}]})
            proto("start", "release", "fx-d1", cwd=repo)
            calls()
            out = proto("step", stdin={"records": {"fx-d1": "unchanged"}}, cwd=repo).stdout
            if ["check", "--json"] not in [c["args"] for c in calls()] \
                    or "fx-d1 revises fx-old: `board ruling supersede fx-old --with fx-d1`" not in out or "fx-elsewhere" in out:
                raise ValueError(f"the Board check must list the set's unlinked revisions:\n{out}")
            proto("abandon", cwd=repo)
            patch_config(check={})
            # Carried settled items: a rule record that closes another takes over the items it settled, and its release closes them.
            qid = replacing("Kappa point", ["fx-d5"], {"fx-d5": "supersedes"}, items={**items, "fx-d5": {**items["fx-d1"], "title": "D5"},
                                                                                     "fx-set1": {"status": "open", "issue_type": "decision"},
                                                                                     "fx-set2": {"status": "decided", "issue_type": "decision"}}, newIds=["fx-n9"])
            edit_state(lambda document: document.setdefault("settles", {}).update({"fx-d5": ["fx-set1", "fx-set2"]}))
            answered()
            proto("step", stdin={"records": {qid: {"rationale": "Replaces fx-d5.", "ruleOwner": "docs/x.md"}}}, cwd=repo)
            patch_config(items={**json.loads(config.read_text())["items"], "fx-n9": {**items["fx-d1"], "title": "N9"}})
            proto("start", "release", "fx-n9", cwd=repo)
            out = proto("step", stdin={"records": {"fx-n9": "unchanged"}}, cwd=repo).stdout
            if "Pre-filled: fx-n9 answers fx-set1 " not in out:
                raise ValueError(f"the items a closed record settled must belong to the new record's release:\n{out}")
            if "Not closed: fx-n9 marks fx-set2 (decided)" not in out or "answers fx-set1, fx-set2" in out:
                raise ValueError(f"a settled item that is no open question must be named, not closed:\n{out}")
            proto("abandon", cwd=repo)
            configure()


        if part == "answers":
            # H: a chat answer quotes only what the user wrote after the question went out (an earlier "yes" fails).
            out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Quote?"]}, cwd=repo).stdout
            point = re.search(r"(pt\d+) \[pasted\]", out).group(1)
            proto("say", "--origin", "composer", stdin={"text": "yes"}, cwd=repo)
            proto("step", stdin={"classes": {point: "user"}}, cwd=repo)
            proto("step", stdin={"select": [point]}, cwd=repo)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Quote?", **{"for": point})]}, cwd=repo)
            converge(cwd=repo)
            qid = shown(cwd=repo)["questions"][0]["id"]
            chat_yes = {"question": qid, "answer": "Keep", "quote": "yes"}
            refused("answer", "--origin", "chat", stdin=chat_yes, needle="since the question went out", cwd=repo)
            proto("say", "--origin", "composer", stdin={"text": "yes"}, cwd=repo)
            proto("answer", "--origin", "chat", stdin=chat_yes, cwd=repo)
            proto("abandon", cwd=repo)

            # I: typed dialog text is no answer: its question waits for the model's reading, and a note on a pick reaches
            # the model (user, 2026-10-31: the console had recorded "explain" as two answers).
            out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Typed?", "Picked?"]}, cwd=repo).stdout
            points = re.findall(r"(pt\d+) \[pasted\]", out)
            proto("step", stdin={"classes": {point: "user" for point in points}}, cwd=repo)
            proto("step", stdin={"select": points}, cwd=repo)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Typed?", **{"for": points[0]}),
                                                             question("Picked?", **{"for": points[1]})]}, cwd=repo)
            converge(cwd=repo)
            result = json.loads(proto("answer", "--origin", "dialog", cwd=repo, stdin={
                "marker": shown(cwd=repo)["batch"]["marker"], "answers": {"1. Typed?": "explain this", "2. Picked?": "Keep (recommended, lean)"},
                "annotations": {"2. Picked?": {"notes": "but log it"}}, "response": "and ground it first"}).stdout)
            typed = next(q for q in result["questions"] if q["text"] == "Typed?")
            if typed["status"] != "ready" or typed["answer"] is not None or result["batch"] is not None \
                    or '"explain this" instead of picking' not in result["note"] or 'with the note "but log it"' not in result["note"] \
                    or not result["note"].startswith(f"{result['round']} · answered q") or "; typed " + typed["id"] not in result["note"] \
                    or "Restate a part in one line when it could be read more than one way." not in result["note"] \
                    or "a reply that changes a question (its recommendation included) → call a pass's skill on it, then report that pass" not in result["note"] \
                    or 'The user also wrote: "and ground it first", tied to no question.' not in result["note"] \
                    or result["note"].count("a change to the questions → `protocol edit` (updates + the quote)") != 1 \
                    or result["note"].count("→ call a pass's skill on it, then report that pass") != 1 \
                    or result["note"].count("Count a pick as the answer when the rest of the reply or note questions only a detail") != 1:
                raise ValueError(f"protocol must hold a typed dialog answer for the model and pass on a pick's note, with the restate "
                                 f"line and the pick-and-detail rule once: {result}")
            proto("step", stdin={}, cwd=repo)
            again = shown(cwd=repo)["batch"]
            if again is None or [q["question"] for q in again["questions"]] != ["Typed?"]:
                raise ValueError(f"protocol step must send a read typed question out again: {again}")
            # A note written with no pick (the console sends no answer) is the person's typed reply, not lost (vitrass, 2026-11-06).
            noted = json.loads(proto("answer", "--origin", "dialog", cwd=repo, stdin={
                "marker": again["marker"], "answers": {"Typed?": ""}, "annotations": {"Typed?": {"notes": "group them by risk"}}}).stdout)
            if next(q for q in noted["questions"] if q["text"] == "Typed?")["status"] != "ready" \
                    or '"group them by risk" instead of picking' not in noted["note"] \
                    or noted.get("echo") != "Your answers:\nTyped: typed, not an answer yet: group them by risk":
                raise ValueError(f"protocol must take a note without a pick as the typed reply, echo included: {noted}")
            proto("step", stdin={}, cwd=repo)
            again = shown(cwd=repo)["batch"]
            proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": again["marker"], "answers": {"Typed?": "Drop, but keep the log"}})
            proto("answer", "--origin", "chat", cwd=repo, stdin={"question": typed["id"], "answer": "Drop", "quote": "Drop, but keep the log"})
            mapped = shown(cwd=repo)
            if mapped["step"] != "check" or mapped["pending"]["command"] != "challenge-rulings":
                raise ValueError(f"the last answer, typed then read, leads to the challenge after the answers: {mapped}")
            if "note: but log it" not in proto("step", stdin={"pass": "challenge-rulings", "updates": [], "checked": ["the answers"]}, cwd=repo).stdout:
                raise ValueError("protocol must show notes at Record")
            closed = proto("step", stdin={"records": {q["id"]: {"rationale": "r", "ruleOwner": "o"} for q in mapped["questions"]}},
                           cwd=repo).stdout.splitlines()[0]
            if not re.fullmatch(r"r\d+ · recorded q\d+, q\d+ · round closed", closed):
                raise ValueError(f"protocol's closing headline must name the file records: {closed!r}")
            # One shared route list for the person's own words: a note on a pick and words tied to no question carry it too (r1-q2).
            # r13-q79: the full note goes out once per compaction window, then a one-line pointer.
            for extra, full in (({"annotations": {"Solo?": {"notes": "log it"}}}, False), ({"response": "rethink the lead"}, True)):
                if full:
                    proto("compacted", cwd=repo)
                solo = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Solo?"]}, cwd=repo).stdout
                solo_point = re.search(r"(pt\d+) \[pasted\]", solo).group(1)
                proto("step", stdin={"classes": {solo_point: "user"}}, cwd=repo)
                proto("step", stdin={"select": [solo_point]}, cwd=repo)
                proto("step", stdin={**ROUND_INFO, "questions": [question("Solo?", **{"for": solo_point})]}, cwd=repo)
                converge(cwd=repo)
                solo_note = json.loads(proto("answer", "--origin", "dialog", cwd=repo, stdin={
                    "marker": shown(cwd=repo)["batch"]["marker"], "answers": {"Solo?": "Keep (recommended, lean)"}, **extra}).stdout)["note"]
                routes = "a change to the questions → `protocol edit` (updates + the quote)" in solo_note and "call a pass's skill on it, then report that pass" in solo_note \
                    and "a deferral of a question → `protocol defer` (question, the quote, until?)" in solo_note \
                    and "another request (explain, step back, ground, …) → run it (a pass: its skill with the Skill tool, then its report); a reply" in solo_note \
                    and "a question → answer it as this turn's last text, correcting a wrong premise; restart only for a criterion that still holds after the answer" in solo_note  # r10-q51
                pointer = "by the routes you were given" in solo_note
                if routes != full or pointer == full:
                    raise ValueError(f"the routes of the person's own words go out in full once per compaction window, then as a pointer (full={full}): {solo_note}")
                proto("abandon", cwd=repo)

            # H2: a question can wait on a named outside result (r8-q31, `waitsFor`): held out of the batches like a `waitsOn` one,
            # its dependents held with it; freeing it is a change the scoped check re-checks; still waiting at Record, it is
            # deferred with its reason, and its dependents with it.
            spike = "the cache spike, in .scratch/cache/spike.md"
            out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Hold A?", "Hold B?", "Hold C?"]}, cwd=repo).stdout
            points = re.findall(r"(pt\d+) \[pasted\]", out)
            proto("step", stdin={"classes": {point: "user" for point in points}}, cwd=repo)
            proto("step", stdin={"select": points}, cwd=repo)
            refused("step", cwd=repo, needle="`waitsFor` must be a non-empty string", stdin={**ROUND_INFO, "questions": [
                question("Hold A?", **{"for": points[0]}), question("Hold B?", waitsFor=" ", **{"for": points[1]}),
                question("Hold C?", **{"for": points[2]})]})
            proto("step", cwd=repo, stdin={**ROUND_INFO, "questions": [
                question("Hold A?", **{"for": points[0]}), question("Hold B?", key="b", **{"for": points[1]}),
                question("Hold C?", waitsOn=["b"], **{"for": points[2]})]})
            hold = [q["id"] for q in shown(cwd=repo)["questions"]]
            converge(cwd=repo)
            if [q["question"] for q in shown(cwd=repo)["batch"]["questions"]] != ["1. Hold A?", "2. Hold B?"]:
                raise ValueError(f"protocol hold: both unheld questions go out first: {shown(cwd=repo)['batch']}")
            # The person's hold goes through `edit` with their words: the batch comes back without B, C stays held with it.
            proto("say", "--origin", "composer", stdin={"text": "skip B until the spike reports"}, cwd=repo)
            proto("edit", cwd=repo, stdin={"updates": [{"id": hold[1], "waitsFor": spike}], "quote": "skip B until the spike reports"})
            view = shown(cwd=repo)
            if [q["question"] for q in view["batch"]["questions"]] != ["Hold A?"] \
                    or [(q["status"], q["waitsFor"]) for q in view["questions"]] != [("asked", None), ("held", spike), ("held", None)]:
                raise ValueError(f"protocol hold: a question held on an outside result stays out of the batch, its dependent with it: {view}")
            listed = proto("show", cwd=repo).stdout
            if f"| {hold[1]} | draft | held, waits for {spike} |" not in listed or f"| {hold[2]} | draft | held on {hold[1]} |" not in listed:
                raise ValueError(f"protocol show names the outside result a question waits for:\n{listed}")
            check_row = engine_module.words.check_row
            if check_row({"id": "q5", "status": "held", "kind": "decision", "text": "B?", "waitsOn": [], "waitsFor": spike}) != f"- q5 held: B? — waits for {spike}" \
                    or check_row({"id": "q6", "status": "held", "kind": "decision", "text": "C?", "waitsOn": ["q5"]}) != "- q6 held: C? — waits on q5":
                raise ValueError("protocol hold: the Check list names the outside result a question waits for")
            proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": view["batch"]["marker"], "answers": {"Hold A?": "Keep"}})
            # The spike landed: the model frees B in a pass report (its own result); B takes the scoped check before it goes out.
            proto("step", cwd=repo, stdin={"pass": "challenge-rulings", "updates": [{"id": hold[1], "waitsFor": None}],
                                           "checked": ["the answers"]})
            freed = shown(cwd=repo)
            if freed["step"] != "check" or (freed["pending"]["command"], freed["pending"]["args"]) != ("step-back", f"goal foundations on {hold[1]}") \
                    or [q["status"] for q in freed["questions"]] != ["answered", "draft", "held"]:
                raise ValueError(f"protocol hold: freeing a question rescopes the check on it: {freed}")
            converge(cwd=repo)
            if [q["question"] for q in shown(cwd=repo)["batch"]["questions"]] != ["Hold B?"]:
                raise ValueError(f"protocol hold: the freed question goes out after its check: {shown(cwd=repo)}")
            proto("abandon", cwd=repo)
            # Still waiting at Record: deferred with its reason, and its dependent with it; the Record step names both.
            out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Wait A?", "Wait B?", "Wait C?"]}, cwd=repo).stdout
            points = re.findall(r"(pt\d+) \[pasted\]", out)
            proto("step", stdin={"classes": {point: "user" for point in points}}, cwd=repo)
            proto("step", stdin={"select": points}, cwd=repo)
            proto("step", cwd=repo, stdin={**ROUND_INFO, "questions": [
                question("Wait A?", **{"for": points[0]}), question("Wait B?", key="b", waitsFor=spike, **{"for": points[1]}),
                question("Wait C?", waitsOn=["b"], **{"for": points[2]})]})
            wait = [q["id"] for q in shown(cwd=repo)["questions"]]
            converge(cwd=repo)
            if [q["question"] for q in shown(cwd=repo)["batch"]["questions"]] != ["Wait A?"]:
                raise ValueError(f"protocol hold: a question staged held on a result skips the batch: {shown(cwd=repo)}")
            proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": shown(cwd=repo)["batch"]["marker"], "answers": {"Wait A?": "Keep"}})
            after_answers(cwd=repo)
            record_view = proto("show", cwd=repo).stdout
            if shown(cwd=repo)["step"] != "record" or f"- {wait[1]}: deferred at Record, it waits for {spike}" not in record_view \
                    or f"- {wait[2]}: deferred at Record, it waits on {wait[1]}, which waits for {spike}" not in record_view:
                raise ValueError(f"protocol hold: Record names the questions it defers for an outside result:\n{record_view}")
            out = proto("step", cwd=repo, stdin={"records": {wait[0]: {"rationale": "R.", "ruleOwner": "docs/c.md#c"}}}).stdout
            events = [e for e in (json.loads(row) for row in (state / "0000-lead0001.protocol" / "history.jsonl").read_text().splitlines())
                      if e.get("round") == out.split()[0]]
            reasons = {e["question"]: e["reason"] for e in events if e["event"] == "deferred"}
            if "round closed" not in out.splitlines()[0] or reasons != {wait[1]: spike, wait[2]: f"waits on {wait[1]}, which waits for {spike}"}:
                raise ValueError(f"protocol hold: Record defers the held question and its dependent with the reason: {reasons}\n{out}")
            # A hold is scheduling, not content (r9-q33): a pass that only sets one changes nothing the loop reruns for; a hold
            # with another change counts through that change.
            out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Sched A?", "Sched B?"]}, cwd=repo).stdout
            points = re.findall(r"(pt\d+) \[pasted\]", out)
            proto("step", stdin={"classes": {point: "user" for point in points}}, cwd=repo)
            proto("step", stdin={"select": points}, cwd=repo)
            proto("step", cwd=repo, stdin={**ROUND_INFO, "questions": [question("Sched A?", **{"for": points[0]}),
                                                                       question("Sched B?", **{"for": points[1]})]})
            sched = [q["id"] for q in shown(cwd=repo)["questions"]]
            pass_name = shown(cwd=repo)["pending"]["command"]
            proto("step", cwd=repo, stdin={"pass": pass_name, "updates": [{"id": sched[0], "waitsFor": spike}],
                                           "checked": {sched[1]: "read it"}})
            view = shown(cwd=repo)
            if view["check"]["last"][pass_name]["changes"] != 0 or [q["status"] for q in view["questions"]] != ["held", "draft"]:
                raise ValueError(f"protocol hold: a pass that only sets a hold holds the question and counts no change: {view}")
            pass_name = view["pending"]["command"]
            proto("step", cwd=repo, stdin={"pass": pass_name, "updates": [{"id": sched[1], "waitsFor": spike, "problem": "Reworded."}],
                                           "checked": {sched[0]: "read it"}})
            if shown(cwd=repo)["check"]["last"][pass_name]["changes"] != 1:
                raise ValueError(f"protocol hold: a hold set with another change counts that change: {shown(cwd=repo)['check']}")
            proto("abandon", cwd=repo)

            # I1: a typed pick that questions a detail is recorded, then the detail is added as its own question (lead be3935d4,
            # 2026-11-06: "Lifetime, but more then 1 hour max wait?" was folded into q161 and asked again). Answer first: an
            # edit would send the typed question out again.
            out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Span?"]}, cwd=repo).stdout
            points = re.findall(r"(pt\d+) \[pasted\]", out)
            proto("step", stdin={"classes": {point: "user" for point in points}}, cwd=repo)
            proto("step", stdin={"select": points}, cwd=repo)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Span?", **{"for": points[0]})]}, cwd=repo)
            converge(cwd=repo)
            reply = "Keep, but how long between tries?"
            result = json.loads(proto("answer", "--origin", "dialog", cwd=repo, stdin={
                "marker": shown(cwd=repo)["batch"]["marker"], "answers": {"Span?": reply}}).stdout)
            if "Record the pick (typed: the [\"answer\"] call with the option's label), then add the detail" not in result["note"]:
                raise ValueError(f"a typed reply's note must say to record the pick, then add the detail: {result['note']}")
            proto("answer", "--origin", "chat", cwd=repo, stdin={"question": result["questions"][0]["id"], "answer": "Keep", "quote": reply})
            proto("edit", cwd=repo, stdin={"updates": [question("Wait?", **{"for": points[0]})], "quote": reply})
            view = shown(cwd=repo)
            if {q["text"]: q["status"] for q in view["questions"]} != {"Span?": "answered", "Wait?": "draft"} \
                    or view["batch"] is not None or view["step"] != "check":
                raise ValueError(f"the pick stays answered and the detail waits for its check, nothing asked again: {view}")
            proto("abandon", cwd=repo)

            # I2: a reply the model must read first holds the next batch, so the typed question goes out again with the rest
            # (lead 6aa2ec33, 2026-11-06: batch 6 went out while q139's typed question waited).
            out = proto("start", "round", "--no-board", str(notes), stdin={"points": [f"Held {n}?" for n in range(1, 6)]}, cwd=repo).stdout
            points = re.findall(r"(pt\d+) \[pasted\]", out)
            proto("step", stdin={"classes": {point: "user" for point in points}}, cwd=repo)
            proto("step", stdin={"select": points}, cwd=repo)
            proto("step", stdin={**ROUND_INFO, "questions": [question(f"Held {n}?", **{"for": point}) for n, point in enumerate(points, 1)]}, cwd=repo)
            converge(cwd=repo)
            first = shown(cwd=repo)["batch"]
            texts = [one["question"] for one in first["questions"]]
            held = json.loads(proto("answer", "--origin", "dialog", cwd=repo, stdin={
                "marker": first["marker"], "answers": {texts[0]: "why this one?", **{text: "Keep (recommended, lean)" for text in texts[1:]}}}).stdout)
            if held["batch"] is not None or "The next batch waits for your reading" not in held["note"]:
                raise ValueError(f"protocol must hold the next batch while a typed reply waits for the model's reading: {held['batch']} {held['note']}")
            proto("step", stdin={}, cwd=repo)
            second = shown(cwd=repo)["batch"]
            if second is None or [one["question"].split(". ", 1)[-1] for one in second["questions"]] != ["Held 1?", "Held 5?"]:
                raise ValueError(f"protocol step must send the read question out again with the rest: {second}")
            proto("abandon", cwd=repo)

            # J: a pass that adds a question says so ("added", not "changed").
            out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Base?"]}, cwd=repo).stdout
            point = re.search(r"(pt\d+) \[pasted\]", out).group(1)
            proto("step", stdin={"classes": {point: "user"}}, cwd=repo)
            proto("step", stdin={"select": [point]}, cwd=repo)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Base?", **{"for": point})]}, cwd=repo)
            added = proto("step", stdin={"pass": "step-back", "updates": [question("Extra?", **{"for": point})]}, cwd=repo)
            if not re.match(r"r\d+ · step-back \(path\): q\d+ added", added.stdout):
                raise ValueError(f"protocol headline must call a new question added: {added.stdout.splitlines()[0]!r}")
            proto("abandon", cwd=repo)

            # E: --discussion skips the board list (Related still searches); --no-board <dir> touches no board and records
            # to the named folder (user, 2026-10-31).
            calls()
            proto("start", "round", "--discussion", stdin={"points": ["Discussion point"]}, cwd=repo)
            if calls():
                raise ValueError("protocol --discussion must not read the board list at Collect")
            proto("abandon", cwd=repo)
            folder = Path(state) / "no-board-records"
            out = proto("start", "round", "--no-board", str(folder), stdin={"points": ["Elsewhere?"]}, cwd=repo).stdout
            point = re.search(r"(pt\d+) \[pasted\]: Elsewhere\?", out).group(1)
            proto("step", stdin={"classes": {point: "user"}}, cwd=repo)
            proto("step", stdin={"select": [point]}, cwd=repo)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Elsewhere?", **{"for": point})]}, cwd=repo)
            converge(cwd=repo)
            asked = shown(cwd=repo)
            qid = asked["questions"][0]["id"]
            proto("answer", "--origin", "dialog", stdin={"marker": asked["batch"]["marker"], "answers": {"Elsewhere?": "Keep"}}, cwd=repo)
            proto("step", stdin={"records": {qid: {"rationale": "R.", "ruleOwner": "o"}}}, cwd=repo)
            if calls() or not list(folder.glob(f"r*-{qid}.md")):
                raise ValueError(f"protocol --no-board: board calls or no record in {folder}")
            # D: Codex (CODEX_THREAD_ID, registry tool codex): passes run by the model, answers model-reported.
            codex = {"CODEX_THREAD_ID": "0000-cdx00001", "CODEX_SESSION_ID": "0000-cdx00001"}
            proto("start", "round", "--no-board", str(notes), stdin={"points": ["Codex?"]}, session=None, env=codex)
            proto("step", stdin={"classes": {"pt1": "user"}}, session=None, env=codex)
            proto("step", stdin={"select": ["pt1"]}, session=None, env=codex)
            out = proto("step", stdin={**ROUND_INFO, "questions": [question("Codex?", **{"for": "pt1"})]}, session=None, env=codex).stdout
            if "Run the step-back skill now" not in out or "console" in out:
                raise ValueError(f"protocol Codex check output:\n{out}")
            out = converge(session=None, env=codex)
            if "protocol answer --origin model-reported" not in out or "quoted verbatim" not in out or "AskUserQuestion" in out:
                raise ValueError(f"protocol Codex ask output:\n{out}")
            note = proto("answer", "--origin", "model-reported", session=None, env=codex,
                         stdin={"marker": "round:r1:1", "answers": {"Codex?": "keep it, as I said"}}).stdout
            result = json.loads(proto("show", "--json", session=None, env=codex).stdout)
            if note.startswith("{") or "challenge-rulings" not in note or result["session"] != "0000-cdx00001" or result["step"] != "check" or result["pending"]["command"] != "challenge-rulings":
                raise ValueError(f"protocol Codex answer: {result}")
            proto("step", session=None, env=codex, stdin={"pass": "challenge-rulings", "updates": [], "checked": ["the answer"]})
            proto("step", session=None, env=codex, stdin={"records": {"q1": {"rationale": "R.", "ruleOwner": "o"}}})
            if 'User (model-reported), ' not in (notes / "r1-q1.md").read_text(encoding="utf-8"):
                raise ValueError("a Codex record must flag the answer model-reported")
            # Codex: the approval question is asked and recorded model-reported; the user's own words pick no option.
            codex_repo = {"session": None, "env": {"CODEX_THREAD_ID": "0000-cdx00001", "CODEX_SESSION_ID": "0000-cdx00001"}, "cwd": repo}
            configure(items={"fx-s1": {"status": "decided", "issue_type": "decision", "title": "S1", "assignee": "lead0001"},
                                "fx-c1": {"status": "decided", "issue_type": "decision", "title": "C1"}})
            refused("start", "release", "fx-s1", needle="held by another live session: fx-s1 (lead0001)", **codex_repo)
            calls()
            proto("start", "release", "fx-c1", **codex_repo)
            if ["claim", "fx-c1"] not in [c["args"] for c in calls()]:
                raise ValueError("start release must claim an unheld record")
            proto("step", stdin={"records": {"fx-c1": "unchanged"}}, **codex_repo)
            proto("step", stdin={"checks": {"fx-c1": nones}}, **codex_repo)
            out = proto("step", stdin={"rulings": [{"record": "fx-c1", "ruling": "r", "why": "w", "alternative": "a", "fails": "f",
                                                    "evidence": "e", "sure": False}]}, **codex_repo).stdout
            batch = json.loads(proto("show", "--json", **codex_repo).stdout)["batch"]
            if "protocol answer --origin model-reported" not in out or "unsure: fx-c1 r" not in out \
                    or batch["questions"][0]["question"] != "Release 1 record? Unsure: fx-c1 (r)":
                raise ValueError(f"protocol Codex approval: {out}")
            text = batch["questions"][0]["question"]
            note = proto("answer", "--origin", "model-reported", stdin={"marker": batch["marker"], "answers": {text: "sounds fine"}},
                         **codex_repo).stdout
            result = json.loads(proto("show", "--json", **codex_repo).stdout)
            if result["step"] != "ask" or "needs the user's pick" not in note:
                raise ValueError(f"protocol: free words must not approve a release: {note}")
            proto("step", stdin={}, **codex_repo)
            batch = json.loads(proto("show", "--json", **codex_repo).stdout)["batch"]
            proto("answer", "--origin", "model-reported", stdin={"marker": batch["marker"], "answers": {text: "Release"}}, **codex_repo)
            result = json.loads(proto("show", "--json", **codex_repo).stdout)
            if result["step"] != "owners":
                raise ValueError(f"protocol Codex model-reported approval: {result}")
            proto("abandon", **codex_repo)
            # Pruning at start: other sessions' folders without an open round go after 30 days without changes.
            old = time.time() - 31 * 86400
            for name, step in (("0000-stale001", "closed"), ("0000-stale002", "check")):
                folder = state / f"{name}.protocol"
                folder.mkdir()
                (folder / "state.json").write_text(json.dumps({"version": 1, "round": {"step": step}}), encoding="utf-8")
                for path in (folder / "state.json", folder):
                    os.utime(path, (old, old))
            proto("start", "round", "--no-board", str(notes), stdin={"points": ["Prune?"]})
            proto("abandon")
            if (state / "0000-stale001.protocol").exists() or not (state / "0000-stale002.protocol").exists() \
                    or not (state / "0000-lead0001.protocol").exists():
                raise ValueError("protocol start must prune only stale folders without an open round")
            # Session resolution: the registry's for Claude Bash calls; none resolves → non-zero with the reason.
            if not proto("status", "--line", session=None, env={"CLAUDE_CODE_SESSION_ID": "0000-lead0001"}).stdout.startswith("protocol:"):
                raise ValueError("protocol must resolve a registered Claude session from the environment")
            refused("show", "--json", session=None, needle="no session")
            refused("show", "--json", session=None, env={"CLAUDE_CODE_SESSION_ID": "0000-unreg001"}, needle="no registered session")
            if "0000-cdx00001 r1" not in proto("history", "--all").stdout:
                raise ValueError("protocol history --all must read every session")
            # A state of another version is refused, never rewritten.
            stale = state / "0000-lead0001.protocol" / "state.json"
            stale.write_text(json.dumps({"version": 99}), encoding="utf-8")
            refused("show", "--json", needle="version 99")
            refused("start", "round", needle="version 99")
            if json.loads(stale.read_text(encoding="utf-8")) != {"version": 99}:
                raise ValueError("protocol rewrote a state of another version")

            # E: the real board path: bin/board with a fake bd (the board fixture) gives Collect its items and Related its hits.
            real = tmp / "real"
            (real / ".beads").mkdir(parents=True)
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            fixture_path = root / "bin" / "fixtures" / "board-export.jsonl"
            (fake_bin / "bd").write_text(
                f'#!{sys.executable}\nimport json, sys\nrows = [json.loads(l) for l in open({str(fixture_path)!r})]\n'
                'if sys.argv[1] == "export":\n    print(*map(json.dumps, rows), sep="\\n")\n'
                'elif sys.argv[1] == "list":\n'
                '    print(json.dumps([{k: v for k, v in r.items() if k not in ("comments", "_type")} for r in rows if r["status"] != "closed"]))\n'
                'else:\n    print("[]")\n', encoding="utf-8")
            (fake_bin / "bd").chmod(0o755)
            env = {"PROTOCOL_BOARD": "", "PATH": f"{fake_bin}:{os.environ['PATH']}"}
            real_session = {"cwd": real, "session": "0000-real0001", "env": env, "process": True}
            out = proto("start", "round", prepass=False, **real_session).stdout
            # fx-ovo.3 is held by the live lead0001: left out of this session's candidates, still a Related hit below.
            if "Held by live session lead0001, not offered: fx-ovo.3" not in out or "- fx-ovo.3" in out or "- fx-ovo.1: Store choice" not in out:
                raise ValueError(f"protocol pre-pass through bin/board:\n{out}")
            proto("step", stdin={"pass": "step-back", "summary": "No change."}, **real_session)
            proto("step", stdin={"classes": {"fx-ovo.1": "user", "fx-ovo.9": "planning"}}, **real_session)
            proto("step", stdin={"select": ["fx-ovo.1"]}, **real_session)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Store choice?", board="fx-ovo.1"),
                                               question("Which store backs the cache?")]}, **real_session)
            overlaps = next(q for q in shown(**real_session)["questions"] if q["board"] is None)["overlaps"]
            if overlaps != [{"id": "fx-ovo.6", "title": "Design cache", "outcome": None},
                            {"id": "fx-ovo.3", "title": "Open cache question", "outcome": None},
                            {"id": "fx-ovo.1", "title": "Store choice", "outcome": None},
                            {"id": "fx-ovo.2", "title": "Old store ruling", "outcome": None},
                            {"id": "fx-ovo.4", "title": "Implement store A", "outcome": None}]:  # four change requests more in the fixture: "store" is no longer a template word
                raise ValueError(f"protocol Related through board related --json: {overlaps}")

        if part == "texts":
            # r15-q88: `help` and a bare call print every verb with an example; the engine's audience table (base.VERBS) owns the
            # sections, the origin check reads the same table. No session is needed.
            helped = proto("help", session=None)
            bare = engine_module.cli.run_cli([], base, Path(plain), "")
            if helped.stderr or bare != (0, helped.stdout, ""):
                raise ValueError(f"protocol help and a bare call must print the same and exit 0: {helped} {bare}")
            head, _, console_part = helped.stdout.partition("console only:")
            if not console_part:
                raise ValueError(f"protocol help lacks the console only section:\n{helped.stdout}")
            table = engine_module.base.VERBS
            listed = lambda part: re.findall(r"^  protocol ([a-z]+)\b", part, re.M)
            console_only = sorted(verb for verb, (audience, _) in table.items() if audience == "console")
            if console_only != ["dropped", "nudged", "pending", "say", "scope"] or sorted(listed(console_part)) != console_only:
                raise ValueError(f"help's console only section must be the table's console verbs: {listed(console_part)} {console_only}")
            if set(listed(head)) & set(console_only) or not {"start", "step", "show", "next", "help", "defer", "edit"} <= set(listed(head)):
                raise ValueError(f"help's session verbs: {listed(head)}")
            marked = sorted(re.findall(r"^  protocol ([a-z]+)\b.*\*\s*$", head, re.M))
            if marked != sorted(verb for verb, (audience, _) in table.items() if audience == "origin") or marked != ["answer", "decline", "pass"] \
                    or "* origin-dependent" not in head:
                raise ValueError(f"help marks answer, decline and pass as origin-dependent: {marked}\n{head}")
            # the origin check reads the table: a verb the table keeps console-only refuses a model origin, one with origins lists them
            for verb, (audience, origins) in table.items():
                if origins:
                    refused(verb, "--origin", "model-nowhere", stdin={}, needle=f"accepted: {', '.join(origins)}")
            # F: round texts: every error at once, the limits, examples, the report format once, hand-offs, the release dialog.
            texts = {"session": "0000-texts001"}
            proto("start", "round", "--no-board", str(notes), stdin={"points": ["Limits?"]}, **texts)
            proto("step", stdin={"classes": {"pt1": "user"}}, **texts)
            stage_text = proto("step", stdin={"select": ["pt1"]}, **texts).stdout
            # r10-q38: the Stage text asks for an example on every option of a code choice, and its sample shows one on each option.
            if "on every option of a code, API, naming or shape choice, an `example`" not in stage_text \
                    or "'<code under A>'" not in stage_text.replace('"', "'") or "'<code under B>'" not in stage_text.replace('"', "'") or "preview" in stage_text:
                raise ValueError(f"the Stage text asks for an example on every option of a code choice: {stage_text}")
            if "`overview` 160" not in stage_text:  # r9-q47: the Stage text states the overview target
                raise ValueError(f"the Stage text states the overview length: {stage_text}")
            if "`root` (record-only, never printed:" not in stage_text or '"root": "<cause>; <end state>"' not in stage_text.replace("'", '"'):
                raise ValueError(f"the Stage text asks for the record-only root, with it in the sample: {stage_text}")
            long_round = {"round": {"title": "t" * 76, "summary": "s" * 241}}
            result = proto("step", ok=False, **texts, stdin={**long_round, "questions": [
                question("Limits?", title="x" * 76, header="Much too long", **{"for": "pt1"}),
                question("y" * 241, options=[{"label": "A", "description": "d" * 201, "for": "for it", "against": "against it"}, {"label": "B", "description": "", "for": "for it", "against": "against it"}])]})
            for needle in ("round title is 76 characters, over the limit of 75", "round summary is 241 characters, over the limit of 240",
                           "questions[0]: title", "questions[0]: header", "questions[1]: text",
                           "questions[1]: the description of option 'A' is 201 characters, over the limit of 200"):
                if needle not in result.stderr:
                    raise ValueError(f"a staging refusal lists every error at once ({needle!r} missing): {result.stderr}")
            refused("step", **texts, stdin={**ROUND_INFO, "questions": [question("2. Numbered?", **{"for": "pt1"})]}, needle="carries no number")
            proto("step", **texts, stdin={**ROUND_INFO, "questions": [question("y" * 160, title="Long", options=[
                {"label": "Keep", "description": "d" * 150, "for": "for it", "against": "against it", "example": "x = 1  # ```"}, {"label": "B", "description": "", "for": "for it", "against": "against it", "example": "y = 2"}], **{"for": "pt1"})]})
            # r10-q37: a preview is refused with a pointer to example, multi-select or not.
            refused("step", **texts, stdin={"pass": "step-back", "updates": [question("Multi?", multiSelect=True, options=[
                {"label": "Keep", "description": "", "for": "for it", "against": "against it", "preview": "x"}, {"label": "B", "description": "", "for": "for it", "against": "against it"}])]}, needle="rename `preview` to `example`")
            # A refused pass report points at `protocol show` for the report format this session was told (the check step printed it).
            for stdin in ({"pass": "nope"}, {}, {"pass": "step-back", "updates": []}):
                refused("step", **texts, stdin=stdin, needle="The report format: `protocol show` prints it again.")
            out = proto("step", **texts, stdin={"pass": "step-back", "updates": [], "checked": ["q1"]}).stdout
            if "After the pass" in out or "Report with `protocol step`" in out:
                raise ValueError(f"the report format goes out with the first pass only: {out}")
            # A two-question dialog is numbered; one question is not. Examples print in the notice, never in the dialog (r10-q37); the lean mark is not counted.
            proto("step", **texts, stdin={"pass": "ground", "updates": [question("Second?", **{"for": "pt1"})], "checked": ["q1"]})
            for command in ("step-back", "ground"):
                proto("step", **texts, stdin={"pass": command, "updates": [], "checked": ["q1"]})
            converge(**texts)
            batch = shown(**texts)["batch"]
            if "end state is one kept option" in json.dumps(batch):
                raise ValueError(f"the root is record-only: the dialog and its notice do not carry it: {batch}")
            if [q["question"] for q in batch["questions"]] != ["1. " + "y" * 160, "2. Second?"] \
                    or any(key in option for q in batch["questions"] for option in q["options"] for key in ("example", "preview")) \
                    or "- Against: against it\n````\nx = 1  # ```\n````" not in batch["notice"] or "```\ny = 2\n```" not in batch["notice"] \
                    or len(batch["questions"][0]["options"][0]["description"]) <= 150 \
                    or "in this order, numbered like the dialog" not in proto("show", **texts).stdout:
                raise ValueError(f"the dialog numbers a batch of two; examples print fenced in the notice, not in the dialog: {batch}")
            claude_ask = proto("show", **texts).stdout
            if "write one short line that questions are coming, nothing about their content, and end your turn; a message tells you when you have something to do" not in claude_ask \
                    or "call AskUserQuestion with the input `protocol show` gives" not in claude_ask \
                    or "After a reply the person typed instead of picking: answer it as the turn's last text and end the turn." not in claude_ask \
                    or "AskUserQuestion input, in this order, numbered like the dialog:" not in claude_ask or '"source": "round:r1:1"' not in claude_ask or "Ask message" in claude_ask \
                    or "before the dialog" in claude_ask or "walk through first" in claude_ask or "Text to show first" in claude_ask:
                raise ValueError(f"a Claude ask with text to print tells the lead to end its turn and keeps the dialog:\n{claude_ask}")
            # A dialog that came back and a batch with nothing new to print: the lead still ends its turn; the console's message opens the dialog (r30-q140).
            proto("decline", "--origin", "dialog", stdin={"marker": batch["marker"], "partial": None}, **texts)
            proto("step", stdin={}, **texts)
            again = shown(**texts)["batch"]
            ask_again = proto("show", **texts).stdout
            # r36-q195: a re-ask with nothing changed still prints its whole text, with no changed mark.
            if again is None or again["marker"] == batch["marker"] or "Problem:" not in again["notice"] or "(changed" in again["notice"] \
                    or "end your turn; a message tells you" not in ask_again \
                    or "AskUserQuestion input" not in ask_again or "next: the console to print, then your answers (batch 2)" not in ask_again:
                raise ValueError(f"a re-ask with nothing changed prints whole and ends the turn for the console's message:\n{ask_again}")
            proto("abandon", **texts)
            # The headline cuts a long pass summary at a word boundary and says so.
            proto("start", "round", "--no-board", str(notes), stdin={"points": ["Cut?"]}, **texts)
            proto("step", stdin={"classes": {"pt2": "user"}}, **texts)
            proto("step", stdin={"select": ["pt2"]}, **texts)
            proto("step", **texts, stdin={**ROUND_INFO, "questions": [question("Cut?", **{"for": "pt2"})]})
            out = proto("step", **texts, stdin={"pass": "step-back", "updates": [], "checked": ["q"],
                                                 "summary": "word " * 30}).stdout.splitlines()[0]
            if not out.rstrip().find("word…") > 0 or "word wo…" in out or "  " in out:
                raise ValueError(f"a headline summary cuts at a word boundary with an ellipsis: {out}")
            proto("abandon", **texts)
            # Only the required parts (r27-q123): no Cases, Premises or Own rulings lines print.
            point = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": ["Lean?"]}, **texts).stdout)[1]
            proto("step", stdin={"classes": {point: "user"}}, **texts)
            proto("step", stdin={"select": [point]}, **texts)
            required = {k: v for k, v in question("Lean?", **{"for": point}).items() if k not in ("cases", "premises", "rulings")}
            proto("step", **texts, stdin={**ROUND_INFO, "questions": [required]})
            converge(**texts)
            notice = shown(**texts)["batch"]["notice"]
            if "Problem: Which one, and why now." not in notice or "- For: for it\n- Against: against it" not in notice \
                    or any(word in notice for word in ("Cases:", "Premises:", "My ruling:", "Note:")):
                raise ValueError(f"a question with the required parts only prints no optional part:\n{notice}")
            proto("abandon", **texts)
            # Codex keeps its run line and gets the format with the round's first pass, as Claude does.
            codex = {"session": "0000-cdx00001"}
            point = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": ["Codex?"]}, **codex).stdout)[1]
            proto("step", stdin={"classes": {point: "user"}}, **codex)
            proto("step", stdin={"select": [point]}, **codex)
            out = proto("step", **codex, stdin={**ROUND_INFO, "questions": [question("Codex?", **{"for": point})]}).stdout
            if "Run the step-back skill now with the argument `goal foundations` (lenses, the questions to strengthen, then any focus) (read its SKILL.md), then report the pass." not in out \
                    or "After the pass, report each change" not in out or f"Check cycle 1/{cap_cycles} (the round's path pass" not in out:
                raise ValueError(f"protocol Codex check output: {out}")
            out = proto("step", **codex, stdin={"pass": "step-back", "updates": [], "checked": ["q"]}).stdout  # the path pass
            if "Run the step-back skill now with the argument `options` (lenses, the questions to strengthen, then any focus)" not in out \
                    or "The options pass also reports `explored`" not in out or f"Check cycle 1/{cap_cycles} (the round's options pass" not in out:
                raise ValueError(f"Codex runs the options pass after the path pass, with the explored format: {out}")
            refused("step", **codex, explore=False, stdin={"pass": "step-back", "updates": [], "checked": ["q"]}, needle="an options pass reports `explored`")
            out = proto("step", **codex, stdin={"pass": "step-back", "updates": [], "checked": ["q"]}).stdout  # the options pass
            out = proto("step", **codex, stdin={"pass": "step-back", "updates": [], "checked": ["q"]}).stdout
            if "Run the ground skill now" not in out or "After the pass" in out:
                raise ValueError(f"protocol Codex later passes carry no format: {out}")
            # Codex has no observation: it reports the scoped path pass it was told to run, with the ids in the run line.
            out = proto("step", **codex, stdin={"pass": "step-back", "updates": [], "checked": ["q"]}).stdout
            outs = []
            while json.loads(proto("show", "--json", **codex).stdout)["step"] == "check":
                out = proto("step", **codex, stdin={"pass": json.loads(proto("show", "--json", **codex).stdout)["pending"]["command"], "updates": [], "checked": ["q"]}).stdout
                outs.append(out)
            if not any("(the lean pass: aim each lean named in the argument at strong, decision-protocol.md Recommendation strength)." in o for o in outs):
                raise ValueError(f"Codex's lean pass points to its rule's owner: {outs}")
            scoped_id = json.loads(proto("show", "--json", **codex).stdout)["questions"][0]["id"]
            out = proto("restart", scoped_id, "--reason", "criterion", **codex).stdout
            if f"with the argument `goal foundations on {scoped_id}`" not in out or f"the path pass on the restarted questions {scoped_id}" not in out:
                raise ValueError(f"Codex scoped path pass:\n{out}")
            out = proto("step", **codex, stdin={"pass": "step-back", "updates": [], "checked": ["q"]}).stdout
            if f"with the argument `options on {scoped_id}`" not in out or f"the options pass on the restarted questions {scoped_id}" not in out:
                raise ValueError(f"Codex: the scoped path pass leads into the scoped options pass:\n{out}")
            out = proto("step", **codex, stdin={"pass": "step-back", "updates": [], "checked": ["q"]}).stdout
            if "path pass" in out.splitlines()[0] or "options pass" in out.splitlines()[0] or f"Check cycle 1/{cap_cycles}." not in out:
                raise ValueError(f"Codex: the scoped options pass leads into the Base loop:\n{out}")
            proto("abandon", **codex)
            # The most recent pass report marks the questions it changed (`changedBy`); the next pass report replaces the mark.
            point = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": ["Marked?"]}, **texts).stdout)[1]
            proto("step", stdin={"classes": {point: "user"}}, **texts)
            proto("step", stdin={"select": [point]}, **texts)
            proto("step", **texts, stdin={**ROUND_INFO, "questions": [question("Marked?", **{"for": point}), question("Other?", **{"for": point})]})
            if any(q["changedBy"] is not None for q in shown(**texts)["questions"]):
                raise ValueError("no pass report yet: no question is marked as changed")
            proto("step", **texts, stdin={"pass": "step-back", "updates": [{"id": shown(**texts)["questions"][0]["id"], "premises": "moved"}]})
            marks = [q["changedBy"] for q in shown(**texts)["questions"]]
            if marks != ["step-back", None]:
                raise ValueError(f"the last pass report marks the questions it changed: {marks}")
            proto("step", **texts, stdin={"pass": "ground", "updates": [{"id": shown(**texts)["questions"][1]["id"], "premises": "moved"}]})
            marks = [q["changedBy"] for q in shown(**texts)["questions"]]
            if marks != [None, "ground"]:
                raise ValueError(f"the next pass report replaces the mark: {marks}")
            proto("step", **texts, stdin={"pass": "challenge-rulings", "updates": [], "checked": ["q"]})
            if any(q["changedBy"] is not None for q in shown(**texts)["questions"]):
                raise ValueError("a pass that changed nothing clears the marks")
            proto("abandon", **texts)
            # Pass guard (Claude sessions): a report needs an observed run of its pass since its last report; a run stays
            # open while part of a report was not applied; Codex has no console and reports freely.
            def texts_round(word):
                found = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": [word]}, **texts).stdout)[1]
                proto("step", stdin={"classes": {found: "user"}}, **texts)
                proto("step", stdin={"select": [found]}, **texts)
                proto("step", **texts, stdin={**ROUND_INFO, "questions": [question(word, **{"for": found})]})
                return shown(**texts)["questions"][0]["id"]

            qid = texts_round("Guard?")
            unobserved = {"pass": "step-back", "updates": [], "checked": ["q"]}
            refused("step", **texts, observe=False, stdin=unobserved, needle="no /step-back ran since its last report")
            # r5-q17: the refusal names the pending pass with its arguments; a report of another command ends the turn.
            refused("step", **texts, observe=False, stdin=unobserved, needle="run `/step-back goal foundations` with the Skill tool")
            refused("step", **texts, observe=False, stdin={**unobserved, "pass": "ground"}, needle="no /ground ran since its last report: end your turn")
            refused("step", **texts, observe=False, stdin=unobserved, needle="The report format: `protocol show` prints it again.")
            proto("pass", "--origin", "plugin", stdin={"command": "step-back", "args": "", "pending": None}, **texts)
            # A refused report changes nothing and lists every error (r23-q95); the run stays open for the resend.
            partly = {"pass": "step-back", "updates": [{"id": qid, "title": "Moved"}, {"id": "q99", "premises": "x"}, {"id": qid, "header": "Much too long"}]}
            result = proto("step", **texts, observe=False, stdin=partly, ok=False)
            if "unknown question q99" not in result.stderr or "over the limit of 12" not in result.stderr or shown(**texts)["questions"][0]["title"] == "Moved":
                raise ValueError(f"a report with an invalid update is refused whole and lists every error: {result.stderr}")
            proto("step", **texts, observe=False, stdin={"pass": "step-back", "updates": [{"id": qid, "premises": "moved again"}]})  # the run stayed open
            refused("step", **texts, observe=False, stdin=unobserved, needle="no /step-back ran")
            proto("abandon", **texts)
            # A refused report in Ask leaves the batch out as it was.
            qid = texts_round("Whole?")
            converge(**texts)
            out_batch = shown(**texts)["batch"]["marker"]
            refused("step", **texts, stdin={"pass": "ground", "checked": ["q"], "updates": [{"id": qid, "title": "Ask title"}, {"id": qid, "header": "Much too long"}]},
                    needle="over the limit of 12")
            if shown(**texts)["batch"]["marker"] != out_batch or shown(**texts)["questions"][0]["title"] == "Ask title":
                raise ValueError(f"a refused report changes nothing in Ask: {shown(**texts)}")
            proto("abandon", **texts)
            # Lengths (r23-q95): the targets are stated, the limits refuse; a few characters over pass.
            found = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": ["Soft?"]}, **texts).stdout)[1]
            proto("step", stdin={"classes": {found: "user"}}, **texts)
            stage_text = proto("step", stdin={"select": [found]}, **texts).stdout
            for needle in ("`title` 60", "`text` 160", "`description` 150", "listed order"):
                if needle not in stage_text:
                    raise ValueError(f"Stage states the targets and the order, missing {needle!r}: {stage_text}")
            if "`title` 75" in stage_text or "`description` 200" in stage_text or "`text` 240" in stage_text:
                raise ValueError("Stage states only the targets")
            proto("step", **texts, stdin={**ROUND_INFO, "questions": [question("y" * 240, title="t" * 75, options=[
                {"label": "Keep", "description": "d" * 200, "for": "for it", "against": "against it"}, {"label": "B", "description": "", "for": "for it", "against": "against it"}], **{"for": found})]})
            proto("abandon", **texts)
            # Read back (r23-q89): show <ids> prints a question whole, plain show stays short.
            found = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": ["Read?"]}, **texts).stdout)[1]
            proto("step", stdin={"classes": {found: "user"}}, **texts)
            proto("step", stdin={"select": [found]}, **texts)
            proto("step", **texts, stdin={**ROUND_INFO, "questions": [question("Read?", premises="the grounded premise", rulings=[{"ruling": "One.", "why": "no trade-off", "alternative": "Two.", "fails": "order", "evidence": "probe"}], options=[
                {"label": "Keep", "description": "keep it", "for": "for it", "against": "against it", "example": "x = 1"}, {"label": "Drop", "description": "", "for": "for it", "against": "against it"}], **{"for": found})]})
            qid = shown(**texts)["questions"][0]["id"]
            whole = proto("show", qid, **texts).stdout
            if "the grounded premise" not in whole or "x = 1" not in whole or "the grounded premise" in proto("show", **texts).stdout \
                    or "the grounded premise" in proto("show", "--json", **texts).stdout:
                raise ValueError(f"show <ids> prints the question whole, the other forms stay short: {whole}")
            refused("show", "q9999", **texts, needle="unknown question q9999")
            # Premises in the record (r23-q90).
            converge(**texts)
            batch = shown(**texts)["batch"]
            proto("answer", "--origin", "dialog", **texts, stdin={"marker": batch["marker"], "answers": {batch["questions"][0]["question"]: batch["questions"][0]["options"][0]["label"]}})
            out = proto("step", **texts, stdin={"records": {qid: {"rationale": "why", "ruleOwner": "docs/x.md#x"}}}).stdout
            written = next((notes / name).read_text(encoding="utf-8") for name in sorted(p.name for p in notes.iterdir()) if name.endswith(f"-{qid}.md"))
            if "## Premises\nthe grounded premise" not in written or "## Own rulings\n- One. Why: no trade-off Alternative: Two. Fails: order Evidence: probe\n" not in written or "## Rule owner\ndocs/x.md#x" not in written:
                raise ValueError(f"the record carries the premises: {written}")
            # Dependencies: a circle and bad references are refused and say why (r23-q91, q93).
            def two_points(first, second, stage=None):
                out = proto("start", "round", "--no-board", str(notes), stdin={"points": [first, second]}, **texts).stdout
                keys = re.findall(r"(pt\d+) \[pasted\]", out)
                proto("step", stdin={"classes": {key: "user" for key in keys}}, **texts)
                proto("step", stdin={"select": keys}, **texts)
                return keys
            keys = two_points("Circle one?", "Circle two?")
            refused("step", **texts, needle="waitsOn runs in a circle", stdin={**ROUND_INFO, "questions": [
                question("Circle one?", key="a", waitsOn=["b"], **{"for": keys[0]}), question("Circle two?", key="b", waitsOn=["a"], **{"for": keys[1]})]})
            refused("step", **texts, needle="names itself", stdin={**ROUND_INFO, "questions": [
                question("Circle one?", key="a", waitsOn=["a"], **{"for": keys[0]}), question("Circle two?", **{"for": keys[1]})]})
            proto("step", **texts, stdin={**ROUND_INFO, "questions": [
                question("Circle one?", key="a", **{"for": keys[0]}), question("Circle two?", key="b", waitsOn=["a"], **{"for": keys[1]})]})
            first, second = [q["id"] for q in shown(**texts)["questions"]]
            bad = lambda *updates: {"pass": "step-back", "checked": ["q"], "updates": list(updates)}
            refused("step", **texts, needle="waitsOn runs in a circle", stdin=bad({"id": first, "waitsOn": [second]}))
            refused("step", **texts, needle="a `key` holds only inside the report", stdin=bad({"id": first, "waitsOn": ["a"]}))
            refused("step", **texts, needle="a removed question goes from `waitsOn`", stdin=bad({"id": first, "remove": True, "reason": "moot"}))
            # Position of a late question (r23-q98): `before` on a new question only; the batch follows it.
            late = lambda text, **extra: question(text, **extra)
            refused("step", **texts, needle="unknown fields before", stdin=bad({"id": first, "before": second}))
            refused("step", **texts, needle="`before` names no question", stdin=bad(late("Nowhere?", before="q9999")))
            proto("step", **texts, stdin=bad(late("Late?", before=first)))
            if [q["text"] for q in shown(**texts)["questions"]][:2] != ["Late?", "Circle one?"]:
                raise ValueError(f"`before` puts a new question ahead: {shown(**texts)['questions']}")
            converge(**texts)
            batch = shown(**texts)["batch"]
            if batch["questions"][0]["question"] != "1. Late?":
                raise ValueError(f"the batch follows the listed order: {batch}")
            # A dialog note counts as the user's words (r23-q97); restart takes answered dependents along (r23-q92).
            texts_of = {one["question"]: one["options"][0]["label"] for one in batch["questions"]}
            noted = next(text for text in texts_of if "Circle one" in text)
            proto("answer", "--origin", "dialog", **texts, stdin={"marker": batch["marker"], "answers": texts_of,
                                                                  "annotations": {noted: {"notes": "also ask about caches"}}})
            refused("edit", **texts, needle="quote check failed", stdin={"quote": "not the user's", "updates": [question("Caches?")]})
            proto("edit", **texts, stdin={"quote": "also ask about caches", "updates": [question("Caches?")]})
            converge(**texts)
            view = shown(**texts)
            if view["batch"] is not None:
                batch = view["batch"]
                proto("answer", "--origin", "dialog", **texts, stdin={"marker": batch["marker"], "answers": {one["question"]: one["options"][0]["label"] for one in batch["questions"]}})
                converge(**texts)
            view = shown(**texts)
            batch = view["batch"]
            if batch is not None:
                proto("answer", "--origin", "dialog", **texts, stdin={"marker": batch["marker"], "answers": {one["question"]: one["options"][0]["label"] for one in batch["questions"]}})
            statuses_now = {q["id"]: q["status"] for q in shown(**texts)["questions"]}
            if statuses_now[first] != "answered" or statuses_now[second] != "answered":
                raise ValueError(f"both answered before the restart: {shown(**texts)['questions']}")
            out = proto("restart", first, "--reason", "criterion", **texts).stdout
            after = {q["id"]: (q["status"], q["answer"]) for q in shown(**texts)["questions"]}
            if f"Restarted with it, their answers rested on it: {second}." not in out or after[first][1] is not None or after[second][1] is not None:
                raise ValueError(f"restart takes answered dependents along: {out}\n{after}")
            proto("abandon", **texts)
            # A question too long to ask (only a pre-limit one can be): a plain message naming the error, no automatic pass; the
            # model shortens it in a pass of its own, whose Skill call counts as the observed run.
            def long_at_ask(qid_, session_state):
                path = state / f"{texts['session']}.protocol" / "state.json"
                data = json.loads(path.read_text(encoding="utf-8"))
                data["round"]["questions"][0]["text"] = "z" * 250
                path.write_text(json.dumps(data), encoding="utf-8")

            qid = texts_round("Fix?")
            long_at_ask(qid, None)
            out = converge(**texts)
            if "Not asked yet" not in out or "over the limit of 240" not in out or "in a pass of its own" not in out \
                    or shown(**texts)["pending"] is not None or shown(**texts)["batch"] is not None:
                raise ValueError(f"a question too long to ask gets a plain message and no pending pass:\n{out}\n{shown(**texts)['pending']}")
            proto("pass", "--origin", "model", stdin={"command": "ground", "args": "", "pending": None}, **texts)
            proto("step", **texts, stdin={"pass": "ground", "updates": [{"id": qid, "text": "Short?", "title": "Short"}]})
            after = shown(**texts)
            if after["batch"] is not None or after["step"] != "check":  # its change reruns the loop, then it goes out
                raise ValueError(f"the pass that shortens the question reruns the loop: {after}")
            converge(**texts)
            if shown(**texts)["batch"]["questions"][0]["question"] != "Short?":
                raise ValueError(f"the shortened question goes out: {shown(**texts)}")
            proto("abandon", **texts)
            # The check sequence per round: path pass, options pass, Base loop, refine pair, lean pass, challenge-rulings; the path pass,
            # the options pass and the refine pair run once (a rebuilt check does not repeat them); a pressed pass naming their lenses counts.
            def pending_now():
                return (lambda p: (p["command"], p["args"]) if p else None)(shown(**texts)["pending"])

            def report(command="", updates=None, observe=True):
                command = command or shown(**texts)["pending"]["command"]
                return proto("step", **texts, observe=observe, stdin={"pass": command, "updates": updates or [], "checked": ["q"]})

            qid = texts_round("Seq?")
            order, outs = [], []
            while shown(**texts)["step"] == "check":
                order.append(pending_now())
                outs.append(report().stdout)
            # Claude's hand-over names no pass (r34-q165): the console runs it, and its skill and argument say what it is.
            if "· Check.\n" not in outs[5] or "lean pass" in outs[5]:
                raise ValueError(f"the hand-over before the lean pass is the plain Check title: {outs[5]}")
            expected = [("step-back", "goal foundations"), ("step-back", "options"), ("step-back", ""), ("ground", ""),
                        ("step-back", "decisions clean overfit mechanics"), ("ground", "assumptions board sources probe"),
                        ("ground", f"assumptions sources probe on {qid}"), ("challenge-rulings", "")]
            if order != expected:
                raise ValueError(f"the check sequence: {order}")
            # A check rebuilt while asking (a pass with changes) repeats neither the path pass nor the refine pair.
            proto("pass", "--origin", "press", stdin={"command": "ground", "args": "", "pending": None}, **texts)
            report("ground", [{"id": qid, "premises": "moved while asking"}])
            again = []
            while shown(**texts)["step"] == "check":
                again.append(pending_now())
                report()
            if again != [("step-back", ""), ("ground", ""), ("ground", f"assumptions sources probe on {qid}"), ("challenge-rulings", "")]:
                raise ValueError(f"a rebuilt check repeats neither path nor refine: {again}")
            proto("abandon", **texts)
            # A pressed pass is an extra pass whatever lenses it names: the pending pass settles by its run's id only.
            qid = texts_round("Pressed?")
            proto("pass", "--origin", "press", stdin={"command": "step-back", "args": "goal decisions foundations consumer root-fix bloat gaps clean overfit mechanics options the gate", "pending": None}, **texts)
            report("step-back", observe=False)
            if pending_now() != ("step-back", "goal foundations"):
                raise ValueError(f"a pressed All pass is an extra pass; the path pass stays pending: {pending_now()}")
            proto("abandon", **texts)
            qid = texts_round("Refined?")
            report()  # the path pass
            report()  # the options pass
            report()
            report()
            proto("pass", "--origin", "press", stdin={"command": "ground", "args": "assumptions board sources probe", "pending": None}, **texts)
            report("ground")  # a pressed ground All, with the refine step-back still pending
            if pending_now() != ("step-back", "decisions clean overfit mechanics"):
                raise ValueError(f"an extra pass leaves the pending refine pass: {pending_now()}")
            proto("pass", "--origin", "press", stdin={"command": "step-back", "args": "clean decisions mechanics overfit", "pending": None}, **texts)
            report("step-back", [{"id": qid, "premises": "moved by Refine"}], observe=False)
            if pending_now() != ("step-back", "") or shown(**texts)["check"]["cycle"] != 1:
                raise ValueError(f"a pressed Refine is an extra pass: its change reruns Base without counting as the refine pass: {pending_now()}")
            report()
            report()
            if pending_now() != ("step-back", "decisions clean overfit mechanics"):
                raise ValueError(f"the refine pair runs after the rerun Base loop: {pending_now()}")
            report()
            report()
            if pending_now() != ("ground", f"assumptions sources probe on {qid}"):
                raise ValueError(f"the refine pair ran once; the lean pass follows with the fixed trio: {pending_now()}")
            proto("abandon", **texts)
            # A Base-only run reported while the path pass is pending does not count as it.
            qid = texts_round("Base only?")
            proto("pass", "--origin", "press", stdin={"command": "step-back", "args": "", "pending": None}, **texts)
            report("step-back", observe=False)
            if pending_now() != ("step-back", "goal foundations"):
                raise ValueError(f"a Base run does not count as the path pass: {pending_now()}")
            proto("abandon", **texts)
            # A path pass that adds a draft goes through Related before the Base loop.
            qid = texts_round("Path adds?")
            report("step-back", [question("Added by path?", **{"for": shown(**texts)["questions"][0].get("for") or "pt1"})])
            view = shown(**texts)
            if view["step"] != "check" or pending_now() != ("step-back", "options") or view["check"]["cycle"] != 1:
                raise ValueError(f"after the path pass the options pass runs (nothing to search without a board): {view['step']} {pending_now()}")
            proto("abandon", **texts)
            # The refine pair's change reruns Base once; nothing repeats the pair.
            qid = texts_round("Pair?")
            for _ in range(4):
                report()
            report("step-back", [{"id": qid, "premises": "moved by the pair"}])
            report("ground")
            if pending_now() != ("step-back", "") or shown(**texts)["check"]["cycle"] != 2:
                raise ValueError(f"a change in the refine pair reruns the Base loop: {pending_now()}")
            report()
            report()
            if pending_now() != ("ground", f"assumptions sources probe on {qid}"):
                raise ValueError(f"the pair runs once; the lean pass follows: {pending_now()}")
            report()
            if pending_now() != ("challenge-rulings", ""):
                raise ValueError(f"the lean pass runs once, then challenge-rulings: {pending_now()}")
            proto("abandon", **texts)
            # Scoped reruns after restart (user, 2026-10-31): the round's once-per-round flags stay set; the restarted ids get
            # their own path pass, then Base round-wide, then their own refine pair, then the lean pass.
            found = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": ["Re?"]}, **texts).stdout)[1]
            proto("step", stdin={"classes": {found: "user"}}, **texts)
            proto("step", stdin={"select": [found]}, **texts)
            proto("step", **texts, stdin={**ROUND_INFO, "questions": [question("Re one?", **{"for": found}), question("Re two?", **{"for": found}),
                                                                       question("Re three?", **{"for": found})]})
            one, two, three = [q["id"] for q in shown(**texts)["questions"]]
            while shown(**texts)["step"] == "check":
                report()
            flags = lambda: {key: value for key, value in json.loads((state / f"{texts['session']}.protocol" / "state.json").read_text())["round"].items()
                             if key in ("pathRun", "refineRun")}
            before = flags()
            out = proto("restart", one, "--reason", "criterion: new goal", **texts).stdout
            if pending_now() != ("step-back", f"goal foundations on {one}"):
                raise ValueError(f"a restart runs a scoped path pass first:\n{out}\n{pending_now()}")
            proto("restart", two, "--reason", "same criterion", **texts)  # a second restart before the loop settles adds its ids
            if pending_now() != ("step-back", f"goal foundations on {one} {two}"):
                raise ValueError(f"a second restart adds its ids: {pending_now()}")
            report()  # the scoped path pass
            if pending_now() != ("step-back", f"options on {one} {two}"):
                raise ValueError(f"the scoped options pass follows the scoped path pass: {pending_now()}")
            report()  # the scoped options pass
            if pending_now() != ("step-back", "") or shown(**texts)["check"]["cycle"] != 1:
                raise ValueError(f"the Base loop runs round-wide after the scoped options pass: {pending_now()}")
            report()
            out = report().stdout
            if pending_now() != ("step-back", f"decisions clean overfit mechanics on {one} {two}"):
                raise ValueError(f"the scoped refine step-back follows the Base loop:\n{out}")
            report()
            if pending_now() != ("ground", f"assumptions board sources probe on {one} {two}"):
                raise ValueError(f"the scoped refine ground follows: {pending_now()}")
            report("ground", [{"id": one, "premises": "moved by the scoped pair"}])
            if pending_now() != ("step-back", "") or shown(**texts)["check"]["cycle"] != 2:
                raise ValueError(f"a change in the scoped pair reruns Base once: {pending_now()}")
            report()
            report()
            if pending_now()[0] != "ground" or not pending_now()[1].startswith("assumptions sources probe "):
                raise ValueError(f"no second scoped pair; the lean pass follows: {pending_now()}")
            if flags() != before:
                raise ValueError(f"the round's once-per-round flags stay untouched by a restart: {before} {flags()}")
            while shown(**texts)["step"] == "check":
                report()
            # A variant of the pending scoped pass (other arguments, the ids without `on`, a focus text) is an extra pass: only the stamped run settles it.
            proto("restart", three, "--reason", "again", **texts)
            for variant in ("goal foundations", f"goal foundations {three}"):
                proto("pass", "--origin", "press", stdin={"command": "step-back", "args": variant, "pending": None}, **texts)
                report("step-back", observe=False)
                if pending_now() != ("step-back", f"goal foundations on {three}"):
                    raise ValueError(f"`{variant}` is an extra pass, not the scoped path pass: {pending_now()}")
            report()
            if pending_now() != ("step-back", f"options on {three}"):
                raise ValueError(f"the stamped run settles the scoped path pass: {pending_now()}")
            for variant in ("options", f"options on {three}; with a focus"):
                proto("pass", "--origin", "press", stdin={"command": "step-back", "args": variant, "pending": None}, **texts)
                report("step-back", observe=False)
                if pending_now() != ("step-back", f"options on {three}"):
                    raise ValueError(f"`{variant}` is an extra pass, not the scoped options pass: {pending_now()}")
            report()
            if pending_now() != ("step-back", ""):
                raise ValueError(f"the stamped run settles the scoped options pass: {pending_now()}")
            proto("abandon", **texts)
            # r22-q168: a round stages no confirm-own-rulings question (a ruling of the lead's is an ordinary question; the engine
            # asks the release approval itself), and the stage instructions no longer offer the kind.
            found = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": ["Mixed?"]}, **texts).stdout)[1]
            proto("step", stdin={"classes": {found: "user"}}, **texts)
            proto("step", stdin={"select": [found]}, **texts)
            if "confirm-own-rulings" in proto("show", **texts).stdout:
                raise ValueError("the stage instructions must not offer the confirm-own-rulings kind")
            refused("step", **texts, stdin={**ROUND_INFO, "questions": [question("Mix confirmation?", kind="confirm-own-rulings", **{"for": found})]},
                    needle="`kind` must be one of decision: a ruling of yours is an ordinary question")
            refused("step", **texts, stdin={**ROUND_INFO, "questions": [question("Mix weird?", kind="weird", **{"for": found})]},
                    needle="`kind` must be one of decision, confirm-own-rulings")
            proto("abandon", **texts)
            # Pass identity (plan engine-refactor): a run counts only when it carried the pending pass's id; any other report is an extra pass.
            def ident_round(*words):
                found = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": [words[0]]}, **texts).stdout)[1]
                proto("step", stdin={"classes": {found: "user"}}, **texts)
                proto("step", stdin={"select": [found]}, **texts)
                proto("step", **texts, stdin={**ROUND_INFO, "questions": [question(word, **{"for": found}) for word in words]})
                return [q["id"] for q in shown(**texts)["questions"]]

            def ran_unstamped(command, args):
                proto("pass", "--origin", "press", stdin={"command": command, "args": args, "pending": None}, **texts)
                return proto("step", **texts, observe=False, stdin={"pass": command, "updates": [], "checked": ["q"]})

            # Restart two questions, remove the first, run the pending pass: its stamped run settles it although the argument names a gone id (the argument parse stopped there).
            one, two = ident_round("Ident one?", "Ident two?")
            while shown(**texts)["step"] == "check":
                report()
            proto("restart", one, two, "--reason", "criterion", **texts)
            if pending_now() != ("step-back", f"goal foundations on {one} {two}"):
                raise ValueError(f"a restart queues the scoped path pass: {pending_now()}")
            proto("say", "--origin", "composer", stdin={"text": "drop the first one"}, **texts)
            proto("edit", stdin={"updates": [{"id": one, "remove": True, "reason": "no need"}], "quote": "drop the first one"}, **texts)
            report()  # the run carries the pending id, whatever the argument names
            if pending_now() != ("step-back", f"options on {two}"):
                raise ValueError(f"the stamped run settled the scoped path pass although {one} left: {pending_now()}")
            proto("abandon", **texts)
            # A plain /step-back reported while the path pass is pending does not settle it (the guard); the stamped run does.
            ident_round("Guarded?")
            ran_unstamped("step-back", "")
            if pending_now() != ("step-back", "goal foundations") or shown(**texts)["check"]["cycle"] != 1:
                raise ValueError(f"a plain step-back run is not the pending path pass: {pending_now()}")
            report()
            if pending_now() != ("step-back", "options"):
                raise ValueError(f"the stamped run settles the path pass: {pending_now()}")
            proto("abandon", **texts)
            # A lens-selected step-back during the pending Base pass is an extra pass, labelled so; the pending pass stays.
            ident_round("Lensed?")
            report()
            report()
            if pending_now() != ("step-back", ""):
                raise ValueError(f"the Base step-back is pending: {pending_now()}")
            ran_unstamped("step-back", "clean overfit")
            if pending_now() != ("step-back", "") or shown(**texts)["check"]["cycle"] != 1 \
                    or not any(line["text"].startswith("step-back (extra):") for line in shown(**texts)["log"]):
                raise ValueError(f"a lens-selected step-back is an extra pass, not the Base pass: {shown(**texts)['check']} {[line['text'] for line in shown(**texts)['log']]}")
            report()
            if pending_now() != ("ground", ""):
                raise ValueError(f"the stamped Base run settles the Base pass: {pending_now()}")
            proto("abandon", **texts)
            # r33-q157, r34-q162, q163: identical options get one hint, a preference lean says what would flip it, earlier rulings print and record.
            found = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": ["Same?"]}, **texts).stdout)[1]
            proto("step", stdin={"classes": {found: "user"}}, **texts)
            proto("step", stdin={"select": [found]}, **texts)
            refused("step", **texts, stdin={**ROUND_INFO, "questions": [question("Same one?", leanBecause={"cause": "preference", "detail": "taste"}, **{"for": found})]},
                    needle="`leanBecause.flipsIf`")
            refused("step", **texts, stdin={**ROUND_INFO, "questions": [question("Same one?", priorRulings=[{"ruling": "r1"}], **{"for": found})]}, needle="`priorRulings` lists")
            hinted = proto("step", **texts, stdin={**ROUND_INFO, "questions": [
                question("Same one?", priorRulings=[{"ruling": "r9-q1", "verdict": "holds", "why": "still the cheapest"}, {"ruling": "r9-q2", "verdict": "fails", "why": "no caller left"}], **{"for": found}),
                question("Same two?", **{"for": found})]}).stdout
            one, two = [q["id"] for q in shown(**texts)["questions"]]
            hint = f"{one} and {two} offer identical options. Merge them only if no sensible answer would treat them differently."
            if hint not in hinted:
                raise ValueError(f"identical options get the merge hint:\n{hinted}")
            if hint in report().stdout:
                raise ValueError("the merge hint prints once per group")
            while shown(**texts)["step"] == "check":
                report()
            batch = shown(**texts)["batch"]
            if "Earlier rulings: 1 held.\n- Fails: r9-q2 - no caller left" not in batch["notice"] or "What would change it: a different taste" not in batch["notice"]:
                raise ValueError(f"the batch prints how many earlier rulings held, each that fails, and what flips a lean:\n{batch['notice']}")
            # r34-q171: Think more is no answer: that question's checks rerun with no model reading, the other answer stays.
            first, second = batch["questions"]
            if first["options"][-1]["label"] != "Think more":
                raise ValueError(f"a lean question with room offers Think more: {first}")
            out = proto("answer", "--origin", "dialog", **texts, stdin={"marker": batch["marker"], "answers": {first["question"]: "Think more", second["question"]: "Keep (recommended, lean)"}}).stdout
            if "Think more: its checks rerun" not in json.loads(out)["echo"] or ": Keep (recommended)" not in json.loads(out)["echo"]:
                raise ValueError(f"the line after a dialog must say Think more reruns and mark the pick: {out}")
            view = shown(**texts)
            answers = {q["id"]: q["answer"] for q in view["questions"]}
            if answers != {one: None, two: "Keep"} or view["step"] != "check" or pending_now() != ("step-back", f"goal foundations on {one}; Think more on {one}: the lean fell short, try to get a reasoned strong recommendation"):
                raise ValueError(f"Think more reruns that question's checks and records the other answer: {answers} {pending_now()}\n{out}")
            report()
            report()
            # A recommendation changed after the person saw it is logged (r34-q164).
            report("step-back", [{"id": one, "recommendation": "Drop"}])
            late_log = (state / f"{texts['session']}.protocol" / "history.jsonl").read_text()
            if '"event": "late-change"' not in late_log or '"was": "Keep", "now": "Drop"' not in late_log:
                raise ValueError("a late recommendation change is logged")
            proto("dropped", "--origin", "plugin", stdin={"kind": "batch", "marker": "round:x:1"}, **texts)
            for nudge in ({"pass": "p1"}, {"batch": "round:x:1"}, {"step": "record"}, {}):
                proto("nudged", "--origin", "plugin", stdin=nudge, **texts)
            printed = subprocess.run([str(root / "bin" / "round-report")], env={**os.environ, "AGENT_SESSION_STATE_DIR": str(state)}, capture_output=True, text=True)
            if printed.returncode != 0 or "late changes (a recommendation changed after the person saw it): 1" not in printed.stdout or "think more 1" not in printed.stdout \
                    or "stale console actions dropped: 1" not in printed.stdout \
                    or "console continues (/console-continue, Continue): 4; queued a pass 1, reopened a batch 1, woke the model 1, none of these 1" not in printed.stdout:
                raise ValueError(f"round-report counts late changes, Think more, drops and continues:\n{printed.stdout}\n{printed.stderr}")
            # Removing the only open question ends the check: no pass runs on nothing (r34).
            proto("say", "--origin", "composer", stdin={"text": "drop it"}, **texts)
            proto("edit", stdin={"updates": [{"id": one, "remove": True, "reason": "no need"}], "quote": "drop it"}, **texts)
            view = shown(**texts)
            if view["pending"] and view["pending"]["command"] != "challenge-rulings":
                raise ValueError(f"nothing left to check, so only the challenge over the answers runs: {view['pending']}")
            proto("abandon", **texts)
            # r38-q213: a Think more rerun carries its goal: every pass on that question says its lean fell short and asks for a
            # reasoned strong recommendation; the lean pass runs again; the goal goes once it is asked.
            qid = texts_round("Deeper?")
            proto("step", **texts, stdin={"pass": "step-back", "updates": [{"id": qid, "leanBecause": {
                "cause": "preference", "detail": "taste between `options` and \"speed\"", "flipsIf": "a different taste"}}], "checked": ["q"]})
            converge(**texts)
            batch = shown(**texts)["batch"]
            proto("answer", "--origin", "dialog", **texts, stdin={"marker": batch["marker"], "answers": {batch["questions"][0]["question"]: "Think more"}})
            focus = f"Think more on {qid}: the lean fell short, try to get a reasoned strong recommendation"
            rerun = []
            while shown(**texts)["step"] == "check":
                rerun.append(pending_now())
                report()
            expected = [("step-back", f"goal foundations on {qid}; {focus}"), ("step-back", f"options on {qid}; {focus}"), ("step-back", ""), ("ground", ""),
                        ("step-back", f"decisions clean overfit mechanics on {qid}; {focus}"), ("ground", f"assumptions board sources probe on {qid}; {focus}"),
                        ("ground", f"assumptions sources probe on {qid}; {focus}"), ("challenge-rulings", "")]
            if rerun != expected:
                raise ValueError(f"a Think more rerun carries its goal on every pass naming the question:\n{rerun}\n{expected}")
            labels = [line["text"] for line in shown(**texts)["log"]]
            if f"ground (lean {qid}): no change" not in labels or not any(text.startswith(f"step-back (path {qid}):") for text in labels):
                raise ValueError(f"the goal's words are focus, not question ids or lenses: {labels}")
            # Asked again, the goal is spent: a later criterion restart reruns without it.
            proto("restart", qid, "--reason", "criterion", **texts)
            if pending_now() != ("step-back", f"goal foundations on {qid}"):
                raise ValueError(f"the Think more goal ends when the question goes out again: {pending_now()}")
            proto("abandon", **texts)
            def lens_round(word):
                """A round whose path pass and Base loop ran: the refine pair is pending."""
                found = texts_round(word)
                for _ in range(4):
                    report()
                return found

            # The edit verb: the user's requested change, quoted from a relayed message, applied without a pass or a check rerun.
            qid = lens_round("Edit?")
            before = shown(**texts)
            edit_stdin = {"updates": [{"id": qid, "title": "Edited title"}], "quote": "please retitle it"}
            refused("edit", **texts, stdin=edit_stdin, needle="quote check failed")
            proto("say", "--origin", "composer", stdin={"text": "Please retitle it, thanks"}, **texts)
            refused("edit", **texts, stdin=edit_stdin, needle="quote check failed")  # case matters like for answers
            proto("say", "--origin", "composer", stdin={"text": "please retitle it, thanks"}, **texts)
            out = proto("edit", **texts, stdin=edit_stdin).stdout
            after = shown(**texts)
            if after["questions"][0]["title"] != "Edited title" or after["questions"][0]["changedBy"] != "edit" \
                    or after["check"] != before["check"] or after["pending"] != before["pending"] \
                    or not out.splitlines()[0].count("edited " + qid + " (your words)") \
                    or not any(line["text"] == f"edited {qid} (your words)" for line in after["log"]):
                raise ValueError(f"edit applies the change without rerunning the check loop or counting a pass:\n{out}\n{after}")
            refused("edit", **texts, stdin={"updates": [{"id": qid, "title": "t" * 61, "header": "Much too long"}], "quote": "please retitle it"},
                    needle="header")
            refused("edit", **texts, stdin={"updates": [{"id": qid, "rulings": [{"ruling": "r", "alternative": "a", "fails": "f", "evidence": "e"}]}], "quote": "please retitle it"},
                    needle="each with ruling, why, alternative, fails, evidence")  # an edit: a ruling without its why
            # With a batch out, edit withdraws and re-issues it; an examples-only change is presentation: no loop rerun; it prints in the options part, so a seen question shows it as changed (r10-q37).
            while shown(**texts)["step"] == "check":
                proto("step", **texts, stdin={"pass": shown(**texts)["pending"]["command"], "updates": [], "checked": ["q"]})
            first = shown(**texts)["batch"]["marker"]
            proto("say", "--origin", "composer", stdin={"text": "change the example of Keep"}, **texts)
            proto("edit", **texts, stdin={"updates": [{"id": qid, "options": [{"label": "Keep", "description": "keep it", "for": "for it", "against": "against it", "example": "x = 2"},
                                                                              {"label": "Drop", "description": "drop it", "for": "for it", "against": "against it"}]}], "quote": "change the example of Keep"})
            again = shown(**texts)
            if again["batch"]["marker"] == first or "```\nx = 2\n```" not in again["batch"]["notice"] or again["step"] != "ask" \
                    or "example" in again["batch"]["questions"][0]["options"][0]:
                raise ValueError(f"edit re-issues a batch that is out: {again}")
            proto("step", **texts, stdin={"pass": "ground", "updates": [{"id": qid, "options": [{"label": "Keep", "description": "keep it", "for": "for it", "against": "against it", "example": "x = 3"},
                                                                                                  {"label": "Drop", "description": "drop it", "for": "for it", "against": "against it"}]}], "checked": ["q"]})
            presented = shown(**texts)
            if presented["step"] != "ask" or "```\nx = 3\n```" not in presented["batch"]["notice"]:
                raise ValueError(f"an examples-only pass update re-issues the batch without rerunning the loop: {presented}")
            proto("step", **texts, stdin={"pass": "ground", "updates": [{"id": qid, "options": [{"label": "Keep", "description": "keep it, changed", "for": "for it", "against": "against it"},
                                                                                                  {"label": "Drop", "description": "drop it", "for": "for it", "against": "against it"}]}]})
            if shown(**texts)["step"] != "check":
                raise ValueError("an option description change is content: it reruns the check loop")
            proto("abandon", **texts)
            # r13: an edit that adds a question or changes a recommendation gets the scoped check, one that raises to strong a
            # challenge, before the question is asked; the others go out. A pass after the last answer follows the same path.
            def multi_round(*words):
                """A round of one question per word up to the batch (check converged); returns (the point, the question ids)."""
                found = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": [words[0]]}, **texts).stdout)[1]
                proto("step", stdin={"classes": {found: "user"}}, **texts)
                proto("step", stdin={"select": [found]}, **texts)
                proto("step", **texts, stdin={**ROUND_INFO, "questions": [question(word, **{"for": found}) for word in words]})
                ids_ = [q["id"] for q in shown(**texts)["questions"]]
                converge(**texts)
                return found, ids_

            def said(words):
                proto("say", "--origin", "composer", stdin={"text": words}, **texts)
                return words

            def log_texts():
                return [line["text"] for line in shown(**texts)["log"]]

            # An edit quote comes from the whole round: words the person sent while the question was a draft authorize its edit once the
            # batch is out, and the edit pulls the batch back; a chat answer still needs words sent after the question went out.
            found = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": ["Early?"]}, **texts).stdout)[1]
            proto("step", stdin={"classes": {found: "user"}}, **texts)
            proto("step", stdin={"select": [found]}, **texts)
            proto("step", **texts, stdin={**ROUND_INFO, "questions": [question("Early?", **{"for": found})]})
            qid = shown(**texts)["questions"][0]["id"]
            said("retitle the early one")  # sent while the question is a draft
            converge(**texts)
            first = shown(**texts)["batch"]["marker"]
            proto("edit", **texts, stdin={"updates": [{"id": qid, "title": "Retitled early"}], "quote": "retitle the early one"})
            view = shown(**texts)
            if view["questions"][0]["title"] != "Retitled early" or view["batch"] is None or view["batch"]["marker"] == first:
                raise ValueError(f"a message sent before the batch went out authorizes its edit, which pulls the batch back: {view}")
            refused("answer", "--origin", "chat", **texts, stdin={"question": qid, "answer": "Keep", "quote": "retitle the early one"}, needle="since the question went out")
            proto("abandon", **texts)
            # A: an added question waits while the batch is out (it stays out), is checked at the hand-over, then asked.
            point, (q1, q2) = multi_round("Add one?", "Add two?")
            first = shown(**texts)["batch"]
            proto("edit", **texts, stdin={"updates": [question("Third?", **{"for": point})], "quote": said("also ask Third?")})
            view = shown(**texts)
            third = view["questions"][2]
            if view["batch"] != first or third["status"] != "draft" or view["pending"] is not None:
                raise ValueError(f"an edit that only adds leaves the batch out and the question unasked: {view}")
            proto("answer", "--origin", "dialog", **texts, stdin={"marker": first["marker"], "answers": {"1. Add one?": "Keep", "2. Add two?": "Keep"}})
            view = shown(**texts)
            if view["step"] != "check" or (view["pending"]["command"], view["pending"]["args"]) != ("step-back", f"goal foundations on {third['id']}") \
                    or not any(text.startswith(f"{third['id']}: checked before they are asked") for text in log_texts()):
                raise ValueError(f"the added question gets the scoped check at the hand-over, before the challenge after the answers: {view['pending']}\n{log_texts()}")
            proto("step", **texts, stdin={"pass": "step-back", "updates": [], "checked": ["every question"]})  # r30-q142: the edited question's options pass follows its path pass
            if (shown(**texts)["pending"]["command"], shown(**texts)["pending"]["args"]) != ("step-back", f"options on {third['id']}"):
                raise ValueError(f"an edited (added) question gets a scoped options pass after its path pass: {shown(**texts)['pending']}")
            converge(**texts)
            view = shown(**texts)
            if [q["question"] for q in view["batch"]["questions"]] != ["Third?"]:
                raise ValueError(f"the checked question is asked in the next batch: {view['batch']}")
            proto("answer", "--origin", "dialog", **texts, stdin={"marker": view["batch"]["marker"], "answers": {"Third?": "Keep"}})
            if shown(**texts)["pending"]["args"] != f"{q1} {q2} {third['id']}":
                raise ValueError("the challenge after the last answer covers the whole answered set")
            after_answers(**texts)
            proto("abandon", **texts)
            # r1-q1: an edit while recording joins the round: the added question gets the scoped check, is asked, and the challenge
            # over the answered set runs again.
            point, (q1, q2) = multi_round("Late one?", "Late two?")
            first = shown(**texts)["batch"]
            proto("answer", "--origin", "dialog", **texts, stdin={"marker": first["marker"], "answers": {"1. Late one?": "Keep", "2. Late two?": "Keep"}})
            after_answers(**texts)
            if shown(**texts)["step"] != "record":
                raise ValueError(f"the round stands at Record: {shown(**texts)['step']}")
            proto("edit", **texts, stdin={"updates": [question("Helper?", **{"for": point})], "quote": said("also ask Helper?")})
            view = shown(**texts)
            helper = view["questions"][2]["id"]
            if view["step"] != "check" or (view["pending"]["command"], view["pending"]["args"]) != ("step-back", f"goal foundations on {helper}"):
                raise ValueError(f"an edit while recording hands the round back to the scoped check: {view['step']} {view['pending']}")
            converge(**texts)
            view = shown(**texts)
            if [q["question"] for q in view["batch"]["questions"]] != ["Helper?"]:
                raise ValueError(f"only the added question is asked: {view['batch']}")
            proto("answer", "--origin", "dialog", **texts, stdin={"marker": view["batch"]["marker"], "answers": {"Helper?": "Keep"}})
            view = shown(**texts)
            if (view["pending"]["command"], view["pending"]["args"]) != ("challenge-rulings", f"{q1} {q2} {helper}"):
                raise ValueError(f"the challenge over the whole answered set runs again: {view['pending']}")
            after_answers(**texts)
            if shown(**texts)["step"] != "record":
                raise ValueError("the round records after the second challenge")
            proto("abandon", **texts)
            # A changed recommendation takes the question out of the batch and the others go out; wording, options and a mark
            # lowered to lean stay free.
            point, (q1, q2) = multi_round("Rec one?", "Rec two?")
            first = shown(**texts)["batch"]
            proto("edit", **texts, stdin={"updates": [{"id": q1, "recommendation": "Drop"}], "quote": said("recommend Drop for the first")})
            view = shown(**texts)
            if view["batch"]["marker"] == first["marker"] or [q["question"] for q in view["batch"]["questions"]] != ["Rec two?"] \
                    or view["questions"][0]["status"] != "draft":
                raise ValueError(f"a changed recommendation leaves the batch and the others go out: {view}")
            proto("edit", **texts, stdin={"updates": [{"id": q2, "text": "Rec two, reworded?", "title": "Reworded", "header": "Rec",
                                                       "options": [{"label": "Keep", "description": "keep it, said again", "for": "for it", "against": "against it"}, {"label": "Drop", "description": "drop it", "for": "for it", "against": "against it"}],
                                                       "premises": "a new premise"}], "quote": said("reword the second")})
            view = shown(**texts)
            if [q["question"] for q in view["batch"]["questions"]] != ["Rec two, reworded?"] or view["pending"] is not None:
                raise ValueError(f"wording, options and premises are free: the batch goes out again at once: {view}")
            renamed = [{"label": "Keep it", "description": "keep it", "for": "for it", "against": "against it"}, {"label": "Drop", "description": "drop it", "for": "for it", "against": "against it"}]
            proto("edit", **texts, stdin={"updates": [{"id": q2, "options": renamed, "recommendation": "Keep it"}], "quote": said("call the first option Keep it")})
            view = shown(**texts)  # the recommended option keeps its place: wording, not a changed recommendation
            if [q["question"] for q in view["batch"]["questions"]] != ["Rec two, reworded?"] or view["pending"] is not None:
                raise ValueError(f"renaming the recommended option's label is wording: {view}")
            proto("answer", "--origin", "dialog", **texts, stdin={"marker": view["batch"]["marker"], "answers": {"Rec two, reworded?": "Keep it"}})
            view = shown(**texts)
            if (view["pending"]["command"], view["pending"]["args"]) != ("step-back", f"goal foundations on {q1}"):
                raise ValueError(f"the re-recommended question gets the scoped check at the hand-over: {view['pending']}")
            converge(**texts)
            asked = shown(**texts)["batch"]["questions"][0]
            if asked["question"] != "Rec one?" or asked["options"][0]["label"] != "Drop (recommended, lean)":
                raise ValueError(f"the checked question is asked with its new recommendation: {asked}")
            proto("abandon", **texts)
            # With nothing else to ask, the check starts at once; an edit that only adds does not take the only question out.
            point, (q1,) = multi_round("Solo?")
            first = shown(**texts)["batch"]
            proto("edit", **texts, stdin={"updates": [{"id": q1, "recommendation": "Drop"}], "quote": said("recommend Drop")})
            view = shown(**texts)
            if view["batch"] is not None or view["step"] != "check" or view["pending"]["command"] != "step-back" or view["pending"]["args"] != f"goal foundations on {q1}":
                raise ValueError(f"with nothing left to ask the scoped check starts at once: {view}")
            proto("abandon", **texts)
            # Before Ask the running check takes an added question: no extra hand-over check, both go out together.
            found = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": ["Early one?"]}, **texts).stdout)[1]
            proto("step", stdin={"classes": {found: "user"}}, **texts)
            proto("step", stdin={"select": [found]}, **texts)
            proto("step", **texts, stdin={**ROUND_INFO, "questions": [question("Early one?", **{"for": found})]})
            proto("edit", **texts, stdin={"updates": [question("Early two?", **{"for": found})], "quote": said("and ask Early two?")})
            converge(**texts)
            view = shown(**texts)
            if [q["question"] for q in view["batch"]["questions"]] != ["1. Early one?", "2. Early two?"]:
                raise ValueError(f"a question added while the check runs goes out with the others: {view['batch']}")
            proto("abandon", **texts)
            # B: a raise to strong takes the question out of the batch and runs one challenge on it; its lowered mark is what shows.
            point, (q1, q2) = multi_round("Raise one?", "Raise two?")
            first = shown(**texts)["batch"]
            raise_strong = {"strength": "strong", "leanBecause": None, "strongBecause": STRONG_CLAIMS}
            proto("edit", **texts, stdin={"updates": [{"id": q1, **raise_strong}], "quote": said("make the first strong")})
            view = shown(**texts)
            if [q["question"] for q in view["batch"]["questions"]] != ["Raise two?"] or view["questions"][0]["status"] != "draft":
                raise ValueError(f"a raise to strong leaves the batch and the others go out: {view}")
            proto("answer", "--origin", "dialog", **texts, stdin={"marker": view["batch"]["marker"], "answers": {"Raise two?": "Keep"}})
            view = shown(**texts)
            if (view["pending"]["command"], view["pending"]["args"]) != ("challenge-rulings", q1) or view["step"] != "check":
                raise ValueError(f"a raise runs one challenge on that question: {view['pending']}")
            proto("step", **texts, stdin={"pass": "challenge-rulings", "checked": ["its checklist"], "updates": [
                {"id": q1, "strength": "lean", "strongBecause": None, "leanBecause": {"cause": "evidence", "detail": "the probe was not run"}}]})
            view = shown(**texts)
            if [q["question"] for q in view["batch"]["questions"]] != ["Raise one?"] \
                    or view["batch"]["questions"][0]["options"][0]["description"] != "Unverified: the probe was not run — keep it" \
                    or f"challenge-rulings (raised {q1}): {q1} changed" not in log_texts()[-2]:
                raise ValueError(f"the challenge's lowered mark is what shows:\n{view['batch']}\n{log_texts()}")
            proto("abandon", **texts)
            # A raise with nothing else to ask runs its challenge at once; lowering to lean is free.
            point, (q1,) = multi_round("Solo raise?")
            proto("edit", **texts, stdin={"updates": [{"id": q1, **raise_strong}], "quote": said("make it strong")})
            view = shown(**texts)
            if view["batch"] is not None or (view["pending"] or {}).get("command") != "challenge-rulings" or view["pending"]["args"] != q1:
                raise ValueError(f"a raise with nothing else to ask runs its challenge at once: {view}")
            proto("step", **texts, stdin={"pass": "challenge-rulings", "checked": ["its checklist"], "updates": []})
            view = shown(**texts)
            if view["questions"][0]["strength"] != "strong" or view["batch"]["questions"][0]["options"][0]["label"] != "Keep (recommended, strong)":
                raise ValueError(f"a raise the challenge leaves stands: {view}")
            proto("edit", **texts, stdin={"updates": [{"id": q1, "strength": "lean", "strongBecause": None,
                                                       "leanBecause": {"cause": "preference", "detail": "taste", "flipsIf": "a different taste"}}], "quote": said("make it lean again")})
            view = shown(**texts)
            if view["batch"]["questions"][0]["options"][0]["label"] != "Keep (recommended, lean)" or view["pending"] is not None:
                raise ValueError(f"lowering to lean is free: {view}")
            proto("abandon", **texts)
            # C: the pass after the last answer: a finding is a new question that takes the scoped check, then the pass runs
            # again; a round with nothing answered skips it.
            point, (q1,) = multi_round("Final?")
            note = json.loads(proto("answer", "--origin", "dialog", **texts, stdin={"marker": shown(**texts)["batch"]["marker"],
                                                                                        "answers": {"Final?": "Keep"}}).stdout)["note"]
            view = shown(**texts)
            if (view["pending"]["command"], view["pending"]["args"]) != ("challenge-rulings", q1) \
                    or view["step"] != "check":
                raise ValueError(f"the last answer is followed by the challenge over the answered set: {view['pending']}")
            out = proto("step", **texts, stdin={"pass": "challenge-rulings", "checked": ["the answer"], "updates": [question("Found?", **{"for": point})]}).stdout
            view = shown(**texts)
            found_id = view["questions"][1]["id"]
            if f"challenge-rulings (after answers): {found_id} added" not in out.splitlines()[0] or view["step"] != "check" \
                    or (view["pending"]["command"], view["pending"]["args"]) != ("step-back", f"goal foundations on {found_id}"):
                raise ValueError(f"a finding is a new question that takes the scoped check:\n{out}")
            converge(**texts)
            view = shown(**texts)
            proto("answer", "--origin", "dialog", **texts, stdin={"marker": view["batch"]["marker"], "answers": {"Found?": "Keep"}})
            if (shown(**texts)["pending"]["command"], shown(**texts)["pending"]["args"]) != ("challenge-rulings", f"{q1} {found_id}"):
                raise ValueError("the pass runs once more after the finding's answer")
            after_answers(**texts)
            proto("abandon", **texts)
            point, (q1,) = multi_round("Gone?")
            saved = state / f"{texts['session']}.protocol" / "state.json"  # nothing answered: the only question went away
            document = json.loads(saved.read_text(encoding="utf-8"))
            document["round"].update(questions=[], batch=None)
            saved.write_text(json.dumps(document), encoding="utf-8")
            proto("step", **texts, stdin={})
            view = shown(**texts)
            if view["step"] != "record" or view["pending"] is not None:
                raise ValueError(f"a round with nothing answered skips the pass: {view}")
            proto("abandon", **texts)
            # Codex: the same verb, the quote taken verbatim (no console relays messages there).
            point = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": ["CEdit?"]}, **codex).stdout)[1]
            proto("step", stdin={"classes": {point: "user"}}, **codex)
            proto("step", stdin={"select": [point]}, **codex)
            proto("step", **codex, stdin={**ROUND_INFO, "questions": [question("CEdit?", **{"for": point})]})
            cq = shown(**codex)["questions"][0]["id"]
            refused("edit", **codex, stdin={"updates": [{"id": cq, "title": "Codex title"}]}, needle="needs \"updates\"")
            proto("edit", **codex, stdin={"updates": [{"id": cq, "title": "Codex title"}], "quote": "retitle it"})
            if shown(**codex)["questions"][0]["title"] != "Codex title":
                raise ValueError("Codex edit applies with a verbatim quote")
            proto("abandon", **codex)
            # A release of eight long ids with three unsure rulings still issues a dialog within every limit.
            ids = [f"fx-long-record-identifier-number-{n}" for n in range(8)]
            configure(items={rid: {"status": "decided", "issue_type": "decision", "title": f"T{n}"} for n, rid in enumerate(ids)})
            proto("start", "release", *ids, cwd=repo, **texts)
            proto("step", cwd=repo, **texts, stdin={"records": {rid: "unchanged" for rid in ids}})
            proto("step", cwd=repo, **texts, stdin={"checks": {rid: nones for rid in ids}})
            proto("step", cwd=repo, **texts, stdin={"rulings": [
                {"record": rid, "ruling": "a fairly long ruling text " * 6, "why": "w", "alternative": "a", "fails": "f", "evidence": "e", "sure": n >= 3}
                for n, rid in enumerate(ids[:6])]})
            dialog = shown(cwd=repo, **texts)["batch"]["questions"][0]
            if len(dialog["question"]) > 160 or len(dialog["header"]) > 12 or any(len(o["description"]) > 150 for o in dialog["options"]) \
                    or "unsure:" not in proto("show", cwd=repo, **texts).stdout or " Unsure: " not in dialog["question"]:
                raise ValueError(f"a release approval dialog stays within the limits by construction: {dialog}")
            title = next(q for q in shown(cwd=repo, **texts)["questions"])["title"]
            if len(title) > 60:
                raise ValueError(f"a release approval question title stays within 60 characters: {title}")
            proto("abandon", cwd=repo, **texts)

        if part == "rules":
            # The engine reads a pending revision's link type and rule key from the board's own constants.
            board_loader = importlib.machinery.SourceFileLoader("board_constants", str(root / "bin" / "board"))
            board_module = importlib.util.module_from_spec(importlib.util.spec_from_loader("board_constants", board_loader))
            board_loader.exec_module(board_module)
            if (engine_module.base.REVISES, engine_module.base.REVISES_RULE) != (board_module.REVISES, board_module.REVISES_RULE):
                raise ValueError("bin/protocol REVISES and REVISES_RULE must equal bin/board's")
            # G: rule questions. One question settles the selected items one answer settles the same way: `settles` is checked at
            # Stage and again after every update set (pass report, edit); the record names each settled item, inherits their
            # blocks, and the release closes them by it.
            rules = {"session": "0000-rules001", "cwd": repo}
            board_items = {
                "fx-a": {"status": "open", "issue_type": "decision", "title": "A", "assignee": "rules001", "dependencies": [
                    {"issue_id": "fx-w", "depends_on_id": "fx-a", "type": "blocks"},      # open: waits on the record
                    {"issue_id": "fx-k", "depends_on_id": "fx-a", "type": "blocks"},      # closed: left
                    {"issue_id": "fx-b", "depends_on_id": "fx-a", "type": "blocks"}]},    # a settled item: left
                "fx-b": {"status": "open", "issue_type": "decision", "title": "B", "assignee": "rules001", "dependencies": [
                    {"issue_id": "fx-b", "depends_on_id": "fx-y", "type": "blocks"},      # open: blocks the record
                    {"issue_id": "fx-b", "depends_on_id": "fx-a", "type": "blocks"}]},
                "fx-c": {"status": "open", "issue_type": "decision", "title": "C", "assignee": "rules001"},
                "fx-k": {"status": "closed"},
                "fx-dd": {"status": "decided", "issue_type": "decision", "title": "DD", "assignee": "rules001"}}
            open_questions = [{"id": i, "status": "open", "type": "decision", "title": f"{i}?", "priority": 1, "blockedBy": []}
                              for i in ("fx-a", "fx-b", "fx-c")]
            rule_config = {"health": {"counts": counts, "items": {"questions": open_questions}}, "items": board_items,
                           "related": {"Rule": ["fx-rel", "fx-w"]}}
            configure(**rule_config)
            proto("start", "round", **rules)
            proto("step", stdin={"classes": {"fx-a": "user", "fx-b": "user", "fx-c": "user"}}, **rules)
            proto("step", stdin={"select": ["fx-a", "fx-b", "fx-c"]}, **rules)
            calls()

            def stage(*items):
                return {**ROUND_INFO, "questions": list(items)}

            def store(name, **extra):
                return question(f"Store {name}?", key=name, board=f"fx-{name}", **extra)

            rule = question("Rule: close both stores?", key="r", settles=["fx-a", "fx-b"])
            refused("step", stdin=stage(question("Rule: close both stores?", settles=["fx-k"]), store("a"), store("b"), store("c")),
                    needle="fx-k is unknown or closed", **rules)
            refused("step", stdin=stage(question("Rule: refine a record?", settles=["fx-dd"]), store("a"), store("b"), store("c")),
                    needle="settles fx-dd, which is decided", **rules)  # r12 in be3935d4: a refined record is related, not settled
            # The same for a decided record picked at Select: settling it would have the release close a decision.
            picked = {"session": "0000-rules002", "cwd": repo}
            decided_row = {"id": "fx-de", "status": "decided", "type": "decision", "title": "DE", "priority": 1, "blockedBy": []}
            configure(**{**rule_config, "items": {**board_items, "fx-de": {"status": "decided", "issue_type": "decision", "title": "DE"}},
                         "health": {"counts": counts, "items": {"questions": open_questions, "decided": [decided_row]}}})
            proto("start", "round", **picked)
            proto("step", stdin={"classes": {"fx-a": "user", "fx-de": "user"}}, **picked)
            proto("step", stdin={"select": ["fx-a", "fx-de"]}, **picked)
            refused("step", stdin=stage(question("Rule: refine it?", settles=["fx-de"]), store("a")),
                    needle="settles fx-de, which is decided", **picked)
            configure(**rule_config)
            calls()
            refused("step", stdin=stage(rule, store("a"), store("b"), store("c")),
                    needle="settles fx-a, which is the `board`/`for` of q2: remove q2 or drop fx-a from `settles`", **rules)
            refused("step", stdin=stage(rule, question("Rule: and the other?", settles=["fx-b"]), store("c")),
                    needle="settles fx-b, which q1 settles already", **rules)
            refused("step", stdin=stage(question("Rule: only a?", settles=["fx-a"]), store("c")), needle="no question covers fx-b", **rules)
            refused("step", stdin=stage(question("Rule: bad?", settles="fx-a"), store("c")), needle="`settles` must be a list", **rules)
            proto("step", stdin=stage(rule, store("c")), **rules)
            staged = shown(**rules)
            rule_q = next(q for q in staged["questions"] if q["settles"])
            store_c = next(q for q in staged["questions"] if q["board"] == "fx-c")
            if staged["step"] != "related" or rule_q["settles"] != ["fx-a", "fx-b"] or store_c["settles"] != [] \
                    or [c["args"][0] for c in calls() if c["args"][0] != "show"] != ["related"]:
                raise ValueError(f"a rule question settling two selected items stages: {staged}")
            proto("step", stdin={"outcomes": {rule_q["id"]: {"fx-rel": "relate", "fx-w": "relate"}}}, **rules)
            # Coverage after every update set: a remove that leaves a selected key uncovered is refused, all keys named, and
            # nothing of the report applies.
            before = shown(**rules)["questions"]
            pending = shown(**rules)["pending"]["command"]
            refused("step", stdin={"pass": pending, "updates": [{"id": store_c["id"], "remove": True, "reason": "x"}]},
                    needle="no question covers fx-c", **rules)
            refused("step", stdin={"pass": pending, "updates": [{"id": rule_q["id"], "remove": True, "reason": "x"}]},
                    needle="no question covers fx-a, fx-b", **rules)
            refused("step", stdin={"pass": pending, "updates": [{"id": rule_q["id"], "settles": ["fx-a"]}]},
                    needle="no question covers fx-b", **rules)
            if shown(**rules)["questions"] != before:
                raise ValueError("a refused update set must leave the questions untouched")
            # Split through `protocol edit`: the rule keeps fx-a, fx-b gets its own question (one change set).
            proto("say", "--origin", "composer", stdin={"text": "Please take fx-b out of the rule."}, **rules)
            proto("edit", stdin={"updates": [{"id": rule_q["id"], "settles": ["fx-a"]}, store("b")], "quote": "take fx-b out of the rule"}, **rules)
            split = shown(**rules)
            store_b = next(q for q in split["questions"] if q["board"] == "fx-b")
            if next(q for q in split["questions"] if q["id"] == rule_q["id"])["settles"] != ["fx-a"] or split["pending"]["command"] != pending:
                raise ValueError(f"a split through edit: {split}")
            refused("edit", stdin={"updates": [{"id": store_b["id"], "remove": True, "reason": "x"}], "quote": "take fx-b out of the rule"},
                    needle="no question covers fx-b", **rules)
            # Merge through a pass report: the rule settles fx-b again and the instance question goes.
            proto("step", stdin={"pass": pending, "updates": [{"id": rule_q["id"], "settles": ["fx-a", "fx-b"]},
                                                               {"id": store_b["id"], "remove": True, "reason": "merged into the rule"}]}, **rules)
            merged = shown(**rules)
            if [q["settles"] for q in merged["questions"] if q["id"] == rule_q["id"]] != [["fx-a", "fx-b"]] \
                    or [q["board"] for q in merged["questions"]] != [None, "fx-c"] or merged["pending"]["command"] != "step-back" \
                    or merged["check"]["cycle"] != 1:
                raise ValueError(f"a merge through a pass report counts as a change for the Base loop: {merged}")
            converge(**rules)
            asked = shown(**rules)["batch"]
            if "**1. Rule: close both stores**\n\nProblem:" not in asked["notice"] or "Settles:\n- fx-a: fx-a?\n- fx-b: fx-b?\n" not in asked["notice"]:
                raise ValueError(f"a rule question prints one line per item it settles:\n{asked['notice']}")
            # Only an unanswered question may change: the answered one is refused.
            marker = asked["marker"]
            proto("answer", "--origin", "dialog", stdin={"marker": marker, "answers": {
                next(q["question"] for q in asked["questions"] if q["question"].endswith("Store c?")): "Keep"}}, **rules)
            refused("step", stdin={"pass": "ground", "updates": [{"id": store_c["id"], "settles": ["fx-b"]}], "checked": ["x"]},
                    needle=f"{store_c['id']} is answered; restart it first", **rules)
            refused("step", stdin={"pass": "ground", "updates": [{"id": store_c["id"], "remove": True, "reason": "x"}], "checked": ["x"]},
                    needle="is answered; restart it first", **rules)
            batch = shown(**rules)["batch"]
            if "Problem:" not in batch["notice"] or "(changed" in batch["notice"]:
                raise ValueError(f"the rule question's re-ask prints whole, unmarked (r36-q195):\n{batch['notice']}")
            proto("answer", "--origin", "dialog", stdin={"marker": batch["marker"], "answers": {batch["questions"][0]["question"]: "Keep"}}, **rules)
            after_answers(**rules)
            if shown(**rules)["step"] != "record":
                raise ValueError(f"both questions answered: {shown(**rules)}")
            # Record: the rule's record names each settled item (checked before any board write).
            calls()
            unnamed = {"records": {rule_q["id"]: {"rationale": "fx-a closes with the rule.", "ruleOwner": "docs/x.md"},
                                   store_c["id"]: {"rationale": "R.", "ruleOwner": "docs/x.md"}}}
            refused("step", stdin=unnamed, needle=f"records.{rule_q['id']}: the rule question settles fx-b; name each", **rules)
            refused("step", stdin={"records": {**unnamed["records"], rule_q["id"]: {"rationale": "fx-a and fx-b2 follow the rule.",
                                                                                     "ruleOwner": "docs/x.md"}}},
                    needle="settles fx-b;", **rules)  # a longer id is no mention of fx-b
            if any(engine_verb(c) in ("claim", "record", "revise") or c["args"][:2] == ["bd", "create"] for c in calls()):
                raise ValueError("a refused Record must write nothing")
            named = {"records": {**unnamed["records"], rule_q["id"]: {"rationale": "Both stores close: fx-a (the old store) and fx-b (the "
                                                                                  "cache) follow the rule.", "ruleOwner": "docs/x.md"}}}
            calls()
            out = proto("step", stdin=named, **rules).stdout
            made = calls()
            recorded = Path(str(log) + ".records").read_text(encoding="utf-8")
            link = next((c for c in made if c["args"][:2] == ["bd", "batch"]), None)
            if [engine_verb(c) for c in made if c["args"][0] != "bd" and c["args"][0] != "show"] != ["claim", "record", "claim", "record", "health"] \
                    or link is None or link["args"][3] != "protocol: link fx-new1" \
                    or link["stdin"] != "dep add fx-new1 fx-rel relates-to\ndep add fx-w fx-new1 blocks\ndep add fx-new1 fx-y blocks\n" \
                    or ["show", "fx-a", "fx-b", "fx-new1", "--json", "--field", "dependencies"] not in [c["args"] for c in made] \
                    or any(c["args"][0] == "unclaim" for c in made) \
                    or "fx-a (the old store)" not in recorded or "Round " not in out:
                raise ValueError(f"protocol Record of a rule question: inherited blocks in one batch, settled items stay held:\n{made}\n{out}")
            # The release closes the settled items by the rule record, pre-filled into the answers check.
            patch_config(items={**board_items, "fx-new1": {"status": "decided", "issue_type": "decision", "title": "Rule record"}})
            calls()
            proto("start", "release", "fx-new1", **rules)
            if "Pre-filled: fx-new1 answers fx-a, fx-b" not in proto("step", stdin={"records": {"fx-new1": "unchanged"}}, **rules).stdout:
                raise ValueError("the board check names the pre-filled answers")
            no_hits = {name: "none" for name in ("revises", "answers", "premise", "assumes", "deferred", "held", "doc")}
            proto("step", stdin={"checks": {"fx-new1": no_hits}}, **rules)
            proto("pass", "--origin", "composer", stdin={"command": "release-round", "args": "", "pending": None}, **rules)
            proto("step", stdin={"rulings": []}, **rules)
            if shown(**rules)["batch"] is not None:
                raise ValueError("a press approval opens no dialog, so nothing is printed")
            calls()
            out = proto("step", stdin={"owners": {"fx-new1": [{"none": {"reason": "covered by the rule"}}]}}, **rules).stdout
            made = [c["args"] for c in calls() if engine_verb(c) == "release"]
            if made != [["ruling", "release", "fx-new1", "--closes", "fx-a=fx-new1", "fx-b=fx-new1"]] \
                    or "- closed fx-a: answered by released fx-new1" not in out or "- closed fx-b: answered by released fx-new1" not in out \
                    or "run `protocol next`" not in out:
                raise ValueError(f"the release closes the settled items by the rule record: {made}\n{out}")
            # A deferred rule question releases its settled items as today.
            configure(**rule_config)
            proto("start", "round", **rules)
            proto("step", stdin={"classes": {"fx-a": "user", "fx-b": "user"}}, **rules)
            proto("step", stdin={"select": ["fx-a", "fx-b"]}, **rules)
            proto("step", stdin=stage(question("Defer both?", settles=["fx-a", "fx-b"])), **rules)
            converge(**rules)
            batch = shown(**rules)["batch"]
            proto("answer", "--origin", "dialog", stdin={"marker": batch["marker"], "answers": {batch["questions"][0]["question"]: "Keep"}}, **rules)
            calls()
            proto("say", "--origin", "composer", stdin={"text": "not yet"}, **rules)
            proto("defer", stdin={"question": shown(**rules)["questions"][0]["id"], "quote": "not yet"}, **rules)
            proto("step", stdin={"records": {}}, **rules)
            if ["unclaim", "fx-a", "fx-b"] not in [c["args"] for c in calls()]:
                raise ValueError("a deferred rule question must release its settled items")
            # A no-board round names the settled points in the record file and closes nothing.
            out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Cache one?", "Cache two?"]}, **rules).stdout
            one, two = re.findall(r"(pt\d+) \[pasted\]", out)
            proto("step", stdin={"classes": {one: "user", two: "user"}}, **rules)
            proto("step", stdin={"select": [one, two]}, **rules)
            proto("step", stdin=stage(question("Keep both caches?", settles=[two], **{"for": one})), **rules)
            converge(**rules)
            batch = shown(**rules)["batch"]
            proto("answer", "--origin", "dialog", stdin={"marker": batch["marker"], "answers": {batch["questions"][0]["question"]: "Keep"}}, **rules)
            calls()
            no_board_q, no_board_round = shown(**rules)["questions"][0]["id"], shown(**rules)["round"]
            refused("step", stdin={"records": {no_board_q: {"rationale": f"{one} keeps.", "ruleOwner": "o"}}}, needle=f"settles {two};", **rules)
            out = proto("step", stdin={"records": {no_board_q: {"rationale": f"{one} and {two} keep.", "ruleOwner": "o"}}}, **rules).stdout
            file = notes / f"{no_board_round}-{no_board_q}.md"
            if two not in file.read_text(encoding="utf-8") or calls() or shown(**rules)["round"] is not None:
                raise ValueError(f"a no-board rule record names the settled point and makes no board call:\n{out}")

            # challenge-rulings reruns whenever a pass changed questions since its last run (r7 q30): its own change reruns the
            # Base loop and then it runs again; a run that changes nothing ends it and the batch goes out.
            out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Rerun?"]}, **rules).stdout
            point = re.search(r"(pt\d+) \[pasted\]", out)[1]
            proto("step", stdin={"classes": {point: "user"}}, **rules)
            proto("step", stdin={"select": [point]}, **rules)
            proto("step", stdin=stage(question("Rerun?", **{"for": point})), **rules)
            while shown(**rules)["pending"]["command"] != "challenge-rulings":
                proto("step", stdin={"pass": shown(**rules)["pending"]["command"], "updates": [], "checked": ["q"]}, **rules)
            challenged = shown(**rules)["questions"][0]["id"]
            proto("step", stdin={"pass": "challenge-rulings", "updates": [{"id": challenged, "premises": "an unsure ruling, now a premise"}]}, **rules)
            while shown(**rules)["pending"] and shown(**rules)["pending"]["command"] != "challenge-rulings":
                proto("step", stdin={"pass": shown(**rules)["pending"]["command"], "updates": [], "checked": ["q"]}, **rules)
            if shown(**rules)["batch"] is not None or shown(**rules)["pending"]["command"] != "challenge-rulings":
                raise ValueError(f"challenge-rulings must run again after its own change: {shown(**rules)}")
            proto("step", stdin={"pass": "challenge-rulings", "updates": [], "checked": ["q"]}, **rules)
            if shown(**rules)["batch"] is None or shown(**rules)["pending"] is not None:
                raise ValueError(f"a challenge-rulings run that changes nothing asks: {shown(**rules)}")
            proto("abandon", **rules)
            configure(**rule_config)
            proto("start", "round", **rules)
            proto("step", stdin={"classes": {"fx-a": "user", "fx-b": "user", "fx-c": "user"}}, **rules)
            proto("step", stdin={"select": ["fx-a", "fx-b", "fx-c"]}, **rules)
            # r33-q156: an open outside decision named in `settles` joins and is claimed; a live hold is refused; a gone one is taken over.
            configure(**{**rule_config, "items": {**board_items, "fx-out": {"status": "open", "issue_type": "decision", "title": "Out"},
                                                  "fx-task": {"status": "open", "issue_type": "task", "title": "Task"},
                                                  "fx-live": {"status": "open", "issue_type": "decision", "title": "Live", "assignee": "other001"},
                                                  "fx-gone": {"status": "open", "issue_type": "decision", "title": "Gone", "assignee": "gone0001"}},
                         "position": {"held": [{"id": "fx-gone", "mark": "gone"}]}})
            refused("step", stdin=stage(question("Rule: join?", settles=["fx-task"]), store("a"), store("b"), store("c")), needle="fx-task is a task, not a decision", **rules)
            refused("step", stdin=stage(question("Rule: join?", settles=["fx-live"]), store("a"), store("b"), store("c")), needle="fx-live is held by other001", **rules)
            calls()
            proto("step", stdin=stage(question("Rule: join?", settles=["fx-out", "fx-gone"]), store("a"), store("b"), store("c")), **rules)
            made = [c["args"] for c in calls() if c["args"][0] in ("claim", "take")]
            if made != [["take", "fx-gone"], ["claim", "fx-out"]] or not {"fx-out", "fx-gone"} <= set(json.loads((state / f"{rules['session']}.protocol" / "state.json").read_text())["round"]["selected"]):
                raise ValueError(f"outside items join the round and are claimed: {made}")
            proto("abandon", **rules)
            configure(**rule_config)
            proto("start", "round", **rules)
            proto("step", stdin={"classes": {"fx-a": "user", "fx-b": "user", "fx-c": "user"}}, **rules)
            proto("step", stdin={"select": ["fx-a", "fx-b", "fx-c"]}, **rules)
            calls()
            # r33-q154: a confirmation may settle several items too.
            proto("step", stdin=stage(question("Rule: confirm?", settles=["fx-a", "fx-b"]), store("c")), **rules)
            proto("abandon", **rules)

            # r9-q40, q41: `protocol defer` defers a question and the questions waiting on it; Record files every deferral on the board
            # through one writer (an outside wait too), and in a round without a board only notes it.
            spike_wait = "the cache spike, in .scratch/cache/spike.md"
            configure(**rule_config, newIds=["fx-d1", "fx-d2", "fx-d3"])
            out = proto("start", "round", stdin={"points": ["Defer one?", "Defer two?", "Wait on a spike?"]}, **rules).stdout
            points = re.findall(r"(pt\d+) \[pasted\]", out)
            proto("step", stdin={"classes": {**{p: "user" for p in points}, "fx-c": "user"}}, **rules)
            proto("step", stdin={"select": [*points, "fx-c"]}, **rules)
            proto("step", stdin=stage(question("Defer one?", key="one", **{"for": points[0]}), question("Defer two?", waitsOn=["one"], **{"for": points[1]}),
                                      question("Wait on a spike?", waitsFor=spike_wait, **{"for": points[2]}), question("Old store?", board="fx-c")), **rules)
            ids = [q["id"] for q in shown(**rules)["questions"]]
            refused("defer", stdin={"question": ids[0], "quote": "later please"}, needle="quote check failed", **rules)
            proto("say", "--origin", "composer", stdin={"text": "defer the first one to December; the old store can wait"}, **rules)
            refused("defer", stdin={"question": "q99", "quote": "defer the first one"}, needle="unknown question q99", **rules)
            refused("defer", stdin={"question": ids[0]}, needle='needs "question" and "quote"', **rules)
            refused("defer", stdin={"question": ids[0], "quote": "defer the first one", "until": " "}, needle="`until`", **rules)
            refused("defer", stdin={"question": ids[0], "quote": "defer the first one", "until": "in a few weeks"}, needle="2026-12-01", **rules)
            proto("defer", stdin={"question": ids[0], "quote": "defer the first one", "until": "2026-12-01"}, **rules)
            proto("defer", stdin={"question": ids[3], "quote": "the old store can wait"}, **rules)
            states = [q["status"] for q in shown(**rules)["questions"]]
            if states != ["deferred", "deferred", "held", "deferred"]:
                raise ValueError(f"protocol defer: the question and its dependent are deferred, the spike hold stays: {states}")
            converge(**rules)
            record_view = proto("show", **rules).stdout
            if shown(**rules)["step"] != "record" or f'- {ids[0]}: deferred (until 2026-12-01): "defer the first one"' not in record_view \
                    or f"- {ids[1]}: deferred with {ids[0]}" not in record_view or f"- {ids[2]}: deferred at Record, it waits for {spike_wait}" not in record_view \
                    or f'- {ids[3]}: deferred: "the old store can wait"' not in record_view:
                raise ValueError(f"protocol defer: Record names every deferral:\n{record_view}")
            refused("step", stdin={"records": {}, "defer": {ids[0]: "later"}}, needle="Record takes no `defer`", **rules)
            calls()
            patch_config(fail=["bd defer"])
            out = proto("step", stdin={"records": {}}, **rules).stdout
            made = calls()
            patch_config(fail=[])
            if "Not recorded" not in out or shown(**rules)["step"] != "record" or sum(c["args"][:2] == ["bd", "create"] for c in made) != 3:
                raise ValueError(f"protocol defer: a failing bd defer leaves Record open after the creates:\n{out}\n{made}")
            out = proto("step", stdin={"records": {}}, **rules).stdout
            rerun = calls()
            made += rerun
            if "round closed" not in out.splitlines()[0] or shown(**rules)["round"] is not None:
                raise ValueError(f"protocol defer: the rerun closes the round:\n{out}")
            if sum(c["args"][:2] == ["bd", "create"] for c in made) != 3:
                raise ValueError(f"protocol defer: a rerun after a failed bd defer creates nothing twice: {[c['args'] for c in made]}")
            ok_defers = [c["args"] for c in rerun if c["args"][:2] == ["bd", "defer"]]
            if ok_defers != [["bd", "defer", "fx-d1", "--reason", "defer the first one", "--until", "2026-12-01"],
                             ["bd", "defer", "fx-d2", "--reason", f"waits on {ids[0]}, which was deferred: defer the first one", "--until", "2026-12-01"],
                             ["bd", "defer", "fx-d3", "--reason", spike_wait],
                             ["bd", "defer", "fx-c", "--reason", "the old store can wait"]]:
                raise ValueError(f"protocol defer: Record files each deferral with its reason, a date only where given: {ok_defers}")
            sequence = [c["args"] for c in made if c["args"] in (["unclaim", "fx-c"], ["bd", "defer", "fx-c", "--reason", "the old store can wait"])]
            if sequence[:2] != [["unclaim", "fx-c"], ["bd", "defer", "fx-c", "--reason", "the old store can wait"]]:
                raise ValueError(f"protocol defer: a deferred item the round claimed is unclaimed before it is deferred: {sequence}")
            # q41: without a board nothing is filed; the deferral is noted in the history and the Closed text, and the
            # batch that was out comes back without the deferred questions.
            configure(**rule_config)
            out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Nb A?", "Nb B?", "Nb C?"]}, **rules).stdout
            points = re.findall(r"(pt\d+) \[pasted\]", out)
            proto("step", stdin={"classes": {p: "user" for p in points}}, **rules)
            proto("step", stdin={"select": points}, **rules)
            proto("step", stdin=stage(question("Nb A?", key="a", **{"for": points[0]}), question("Nb B?", waitsOn=["a"], **{"for": points[1]}),
                                      question("Nb C?", **{"for": points[2]})), **rules)
            ids = [q["id"] for q in shown(**rules)["questions"]]
            converge(**rules)
            if [q["question"] for q in shown(**rules)["batch"]["questions"]] != ["1. Nb A?", "2. Nb C?"]:
                raise ValueError(f"protocol defer: the batch before the deferral: {shown(**rules)['batch']}")
            proto("say", "--origin", "composer", stdin={"text": "skip A for now"}, **rules)
            proto("defer", stdin={"question": ids[0], "quote": "skip A for now"}, **rules)
            if [q["question"] for q in shown(**rules)["batch"]["questions"]] != ["Nb C?"] or [q["status"] for q in shown(**rules)["questions"]] != ["deferred", "deferred", "asked"]:
                raise ValueError(f"protocol defer: a batch holding a deferred question comes back without it: {shown(**rules)}")
            proto("restart", ids[0], **rules)  # withdrawing a deferral takes back the questions deferred with it
            if [q["status"] for q in shown(**rules)["questions"]][:2] != ["draft", "held"]:
                raise ValueError(f"protocol restart of a deferred question revives the questions deferred with it: {shown(**rules)['questions']}")
            proto("defer", stdin={"question": ids[0], "quote": "skip A for now"}, **rules)
            converge(**rules)
            proto("answer", "--origin", "dialog", stdin={"marker": shown(**rules)["batch"]["marker"], "answers": {"Nb C?": "Keep"}}, **rules)
            after_answers(**rules)
            calls()
            out = proto("step", stdin={"records": {ids[2]: {"rationale": "R.", "ruleOwner": "o"}}}, **rules).stdout
            events = [e for e in (json.loads(row) for row in (state / "0000-rules001.protocol" / "history.jsonl").read_text().splitlines()) if e.get("round") == out.split()[0]]
            reasons = {e["question"]: e["reason"] for e in events if e["event"] == "deferred"}
            if calls() or reasons != {ids[0]: "skip A for now", ids[1]: f"waits on {ids[0]}, which was deferred: skip A for now"} \
                    or f"- {ids[0]} deferred (no board: noted here only)" not in out or f"- {ids[1]} deferred (no board: noted here only)" not in out:
                raise ValueError(f"protocol defer: a boardless deferral is noted and files nothing:\n{out}\n{reasons}")

        if part == "context":
            # r17/r18: what a session was told is one record (`state['told']`), cleared by `protocol compacted`: the question list of a check pass once per check cycle, the open-item list once, the report formats once per
            # step kind, the Durable owners once, the ask instructions once.
            expander = load_skill_expander(root)
            installed = tmp / "home"
            for source in ("shared/project-memory.md",):
                target = installed / ".agents" / "skills" / source
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(expander.expand_markdown(root / "skills" / source, (root / "skills").resolve()), encoding="utf-8")
            home = {"env": {"HOME": str(installed)}}
            ctx_notes = tmp / "ctx-notes"

            def history(**kwargs):
                return [json.loads(row) for row in proto("history", "--json", **kwargs).stdout.splitlines()]

            def run_pass(origin="plugin", updates=None, **kwargs):
                """The pending pass as the console runs it (origin plugin), then its report; returns (the pass, the report's output)."""
                waiting = shown(**kwargs)["pending"]
                proto("pass", "--origin", origin, stdin={"command": waiting["command"], "args": waiting["args"], "pending": waiting["id"]}, **kwargs)
                out = proto("step", stdin={"pass": waiting["command"], "updates": updates or [], "checked": ["every question"]}, **kwargs).stdout
                return waiting, out

            staged = {}

            def to_check(point, **kwargs):
                """A no-board round to its first check pass; `staged['q']` is its question's id."""
                pasted = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(ctx_notes), stdin={"points": [point]}, **kwargs).stdout).group(1)
                proto("step", stdin={"classes": {pasted: "user"}}, **kwargs)
                proto("step", stdin={"select": [pasted]}, **kwargs)
                out = proto("step", stdin={**ROUND_INFO, "questions": [question(f"{point}?", **{"for": pasted})]}, **kwargs).stdout
                staged["q"] = shown(**kwargs)["questions"][0]["id"]
                return out

            # A: the question list prints in full on the first check pass; later passes print only rows changed since the last output (r13-q66); every pass is the skill's own full text
            # (nothing in the engine cuts it), so a pass log has no `told` and the pending pass has no `reminder`.
            first = to_check("Cadence?", **home)
            qid = staged["q"]
            if f"- {qid} draft: Cadence?" not in first:
                raise ValueError(f"the cycle's first check pass lists the questions:\n{first}")
            seen, outputs = [], []
            for _ in range(11):
                view = shown(**home)
                if view["step"] != "check" or view["pending"] is None:
                    break
                if set(view["pending"]) != {"id", "command", "args"}:
                    raise ValueError(f"the pending pass is the engine's fields only: {view['pending']}")
                seen.append((view["pending"]["command"], view["pending"]["args"]))
                outputs.append(run_pass(**home)[1])
            expected = [("step-back", "goal foundations"), ("step-back", "options"), ("step-back", ""), ("ground", ""), ("step-back", "decisions clean overfit mechanics"),
                        ("ground", "assumptions board sources probe"), ("ground", f"assumptions sources probe on {qid}"), ("challenge-rulings", "")]
            if seen != expected:
                raise ValueError(f"the check sequence changed under the cadence test: {seen}")
            if any("told" in e for e in history(**home) if e["event"] in ("pass", "pass-start")):
                raise ValueError(f"a pass log carries no told: {history(**home)}")
            # B: later check passes list no unchanged row, only the count.
            if "1 question, none changed (protocol show lists them)" not in outputs[0] or f"- {qid} draft" in outputs[0] or f"- {qid} draft" in outputs[1]:
                raise ValueError(f"later check passes count the unchanged questions:\n{outputs[0]}")
            proto("abandon", **home)

            # A2: a changed question's row prints again in the next output; the unchanged ones stay out.
            to_check("Cycles?", **home)
            qid = staged["q"]
            run_pass(**home)                                                                       # path pass
            run_pass(**home)                                                                       # options pass
            run_pass(**home)                                                                       # Base step-back
            _, out = run_pass(updates=[{"id": qid, "text": "Cycles now?"}], **home)               # the cycle's ground, with a change
            nxt = shown(**home)
            if (nxt["check"]["cycle"], nxt["pending"]["command"]) != (2, "step-back") \
                    or f"- {qid} draft: Cycles now?" not in out or "1 listed above as new or changed" not in out:
                raise ValueError(f"the output after a changed row lists that row:\n{nxt}\n{out}")
            _, out = run_pass(**home)
            if "none changed (protocol show lists them)" not in out or f"- {qid} draft" in out:
                raise ValueError(f"cycle 2: the unchanged row was listed again:\n{out}")
            if f"- {qid} draft: Cycles now?" not in proto("show", **home).stdout:
                raise ValueError("protocol show lists the questions whatever the record says")
            proto("restart", qid, **home)
            run_pass(**home)                                                                       # the scoped path pass
            run_pass(**home)                                                                       # the scoped options pass
            # C: a compaction lists the questions again.
            proto("compacted", **home)
            _, out = run_pass(origin="composer", **home)
            if f"- {qid} draft: Cycles now?" not in out or shown(**home)["pending"]["command"] != "ground":
                raise ValueError(f"the questions list again after a compaction:\n{out}")
            proto("abandon", **home)
            if "Compaction recorded" not in proto("compacted", **home).stdout or history(**home)[-1]["event"] != "compacted":
                raise ValueError("protocol compacted works without an open round and logs it")

            # r24-q108: abandon says which records stay decided, not "nothing recorded".
            kept = engine_module.record.abandon_note([{"id": "q1", "board": "fx-a", "recorded": "fx-a"}, {"id": "q2", "board": None, "recorded": "file"},
                                               {"id": "q3", "board": "fx-c", "recorded": None}, {"id": "q4", "board": "fx-d", "recorded": "deferred"}])
            if kept != "recorded fx-a, q2 stay decided" or engine_module.record.abandon_note([{"id": "q3", "board": "fx-c", "recorded": None}]) != "nothing recorded":
                raise ValueError(f"abandon must name what stays decided: {kept}")

            def sequence(limit=14, **kwargs):
                """The passes a check runs without changes, as (command, args), until the batch."""
                found = []
                for _ in range(limit):
                    view = shown(**kwargs)
                    if view["step"] != "check" or view["pending"] is None:
                        break
                    found.append((view["pending"]["command"], view["pending"]["args"]))
                    run_pass(**kwargs)
                return found

            # r13-q66: a `checked` line is one line of about 120 characters; above that and within 250 (the limit) the report is accepted with
            # one warning line per entry, over 250 it is refused, and a refused report prints no warning.
            to_check("Wordy?", **home)
            qid = staged["q"]
            wordy = {"pass": "step-back", "updates": [], "checked": {qid: "x" * 251, "round": "short"}}
            refused("step", stdin=wordy, needle="checked." + qid + ": 251 characters", **home)
            if "keep it to about" in proto("step", stdin=wordy, ok=False, **home).stderr:
                raise ValueError("a refused report prints no warnings")
            out = proto("step", stdin={**wordy, "checked": {qid: "x" * 250, "round": "y" * 121}}, **home).stdout
            for needle in (f"checked.{qid} is 250 characters; keep it to about 120 (refused over 250)", "checked.round is 121 characters; keep it to about 120 (refused over 250)"):
                if needle not in out:
                    raise ValueError(f"a checked line in the band is accepted with a warning ({needle!r} missing):\n{out}")
            if "keep it to about" in proto("step", stdin={**wordy, "checked": {qid: "x" * 120, "round": "short"}}, **home).stdout:
                raise ValueError("a checked line at the target gets no warning")

            # An update warns only for the fields it carries: an untouched long field is not warned again.
            def update_out(**fields):
                return proto("step", stdin={"pass": "step-back", "updates": [{"id": qid, **fields}], "checked": {"round": "short"}}, **home).stdout

            def warned(out):
                return [re.sub(r"^q\d+: ", "", line) for line in out.splitlines() if "keep it to about" in line]

            long_options = [{"label": "Keep", "description": "d" * 151, "for": "for it", "against": "against it"}, {"label": "Drop", "description": "drop it", "for": "for it", "against": "against it"}]
            got = warned(update_out(title="t" * 61, text="x" * 161, options=long_options))
            if got != ["title is 61 characters; keep it to about 60 (refused over 75)", "text is 161 characters; keep it to about 160 (refused over 240)",
                       "the description of option 'Keep' is 151 characters; keep it to about 150 (refused over 200)"]:
                raise ValueError(f"an update in the band warns once per field it sets: {got}")
            if warned(update_out(premises="Another premise.")):
                raise ValueError("an update that leaves the long fields alone must not warn about them again")
            if len(warned(update_out(title="t" * 62))) != 1:
                raise ValueError("an update warns only for the field it sets")
            # r9-q44: the goal check updates the root; it is presentation (the batch stays, no loop reruns).
            update_out(root="A deeper cause; the end state without the guard.")
            now = shown(**home)
            stored = next(q for q in json.loads((session_dir / "state.json").read_text(encoding="utf-8"))["round"]["questions"] if q["id"] == qid)
            if stored["root"] != "A deeper cause; the end state without the guard." or now["check"]["last"]["step-back"]["changes"] != 0:
                raise ValueError(f"a pass may update a question's root, which counts no change: {now}")
            refused("step", stdin={"pass": "step-back", "updates": [{"id": qid, "root": " "}], "checked": {"round": "short"}}, needle="`root` must be a non-empty string", **home)
            proto("abandon", **home)

            # Above the target and within the limit a new question (Stage) is accepted with one warning line per field; at the target it gets none.
            point = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(ctx_notes), stdin={"points": ["Banded?"]}, **home).stdout).group(1)
            proto("step", stdin={"classes": {point: "user"}}, **home)
            proto("step", stdin={"select": [point]}, **home)
            banded = proto("step", stdin={**ROUND_INFO, "questions": [question("y" * 161, title="t" * 61, options=[
                {"label": "Keep", "description": "d" * 151, "for": "for it", "against": "against it"}, {"label": "B", "description": "d" * 150, "for": "for it", "against": "against it"}], **{"for": point})]}, **home).stdout
            got = [re.sub(r"^q\d+: ", "", line) for line in banded.splitlines() if "keep it to about" in line]
            if got != ["title is 61 characters; keep it to about 60 (refused over 75)", "text is 161 characters; keep it to about 160 (refused over 240)",
                       "the description of option 'Keep' is 151 characters; keep it to about 150 (refused over 200)"]:
                raise ValueError(f"a staged question in the band gets one warning per field, none at the target:\n{banded}")
            proto("abandon", **home)

            # r9-q47: the round's title warns over 60 and its overview over 160 (refused over 75 and 240), like a question's fields.
            def round_band(title, overview):
                point = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(ctx_notes), stdin={"points": ["Banded?"]}, **home).stdout).group(1)
                proto("step", stdin={"classes": {point: "user"}}, **home)
                proto("step", stdin={"select": [point]}, **home)
                out = proto("step", stdin={"round": {**ROUND_INFO["round"], "title": title, "overview": overview}, "questions": [question("Rounded?", **{"for": point})]}, **home).stdout
                proto("abandon", **home)
                return [line for line in out.splitlines() if line.startswith("round ") and "keep it to about" in line]

            if round_band("t" * 61, "o" * 161) != ["round title is 61 characters; keep it to about 60 (refused over 75)", "round overview is 161 characters; keep it to about 160 (refused over 240)"]:
                raise ValueError("a staged round in the band warns on its title and overview")
            if round_band("t" * 60, "o" * 160):
                raise ValueError("a round title and overview at the target get no warning")

            # r18-q120: every question gets the full set; the `stakes` field is gone.
            to_check("Full?", **home)
            qid = staged["q"]
            refused("step", stdin={"pass": "ground", "updates": [{"id": qid, "stakes": "x"}], "checked": {qid: "ok"}}, needle="stakes", **home)
            proto("abandon", **home)

            # r18-q121: a ground that would repeat the last one (same scope, nothing changed since) is skipped after a step-back that updated nothing; any update, a presentation one included, keeps it.
            def cycle_two(second_updates, **kwargs):
                """A check whose cycle-1 ground changed the question, then cycle 2's step-back with `second_updates`: the pass pending after it."""
                to_check("Repeats?", **kwargs)
                qid = staged["q"]
                for _ in range(3):                                                                 # path, options, Base step-back
                    run_pass(**kwargs)
                run_pass(updates=[{"id": qid, "text": "Repeats now?"}], **kwargs)                 # the cycle's ground, with a change
                run_pass(updates=[{"id": qid, **update} for update in second_updates], **kwargs)  # cycle 2's step-back
                return shown(**kwargs)["pending"], qid

            nxt, qid = cycle_two([], **home)
            if (nxt["command"], nxt["args"]) != ("step-back", "decisions clean overfit mechanics") or shown(**home)["check"]["cycle"] != 2:
                raise ValueError(f"a quiet step-back skips the repeated ground and goes on to the refine pair: {nxt}")
            proto("abandon", **home)
            nxt, qid = cycle_two([{"note": "a presentation edit"}], **home)
            if nxt["command"] != "ground":
                raise ValueError(f"a step-back whose update changed only the presentation still runs its ground: {nxt}")
            proto("abandon", **home)

            # A restart on the question: the scoped passes run again (Think more).
            to_check("Rethinks?", **home)
            qid = staged["q"]
            run_pass(**home)                                                                       # the round-wide path pass
            proto("restart", qid, **home)
            if shown(**home)["pending"]["args"] != f"goal foundations on {qid}":
                raise ValueError(f"a restarted question gets the scoped path pass: {shown(**home)['pending']}")
            proto("abandon", **home)

            # A4: Codex has no console: its pass text names the skill to read, in full every time (r24-q103).
            codex = {"session": None, "env": {"CODEX_THREAD_ID": "0000-cdx00001", "CODEX_SESSION_ID": "0000-cdx00001", "HOME": str(installed)}}
            full = to_check("Codex cadence?", **codex)
            if "Run the step-back skill now" not in full or "(read its SKILL.md)" not in full or "Reminder" in full:
                raise ValueError(f"a Codex pass reads SKILL.md:\n{full}")
            again = proto("step", stdin={"pass": "step-back", "updates": [], "checked": ["x"]}, observe=False, **codex).stdout  # Codex runs are not observed
            if "Run the step-back skill now" not in again or "(read its SKILL.md)" not in again or "Reminder" in again:
                raise ValueError(f"the Codex Base step-back reads SKILL.md too:\n{again}")
            proto("abandon", **codex)

            # G: the open-item list, once between compactions (protocol next or a round's Collect, whichever is first), grouped.
            listing_session = {"session": "0000-ctxlist01", "cwd": repo}
            row = {"status": "open", "type": "decision", "priority": 1, "blockedBy": []}
            configure(health={"counts": counts, "items": {
                "questions": [{**row, "id": "fx-a", "title": "A?"}, {**row, "id": "fx-b", "title": "B?"},
                              {**row, "id": "fx-live", "title": "Live?", "holder": "other001"}],
                "decided": [{**row, "id": "fx-d", "status": "decided", "title": "D"}],
                "forUser": [{**row, "id": "fx-u", "type": "task", "title": "Needs you", "holder": "user"}]}},
                position={"held": [{"id": "fx-live", "holder": "other001", "mark": None}, {"id": "fx-u", "holder": "user", "mark": None}],
                          "readyMilestones": [{**row, "id": "fx-m", "type": "milestone", "title": "Beta"}],
                          "finishedEpics": [{**row, "id": "fx-e", "type": "epic", "title": "Cache"}]},
                items={"fx-closed": {"status": "closed"}, "fx-rel": {"status": "released"}, "fx-null": {"status": None}})
            out = proto("next", **listing_session).stdout
            for needle in ("Open items (6):", "open questions · open (2):\n- fx-a: A?\n- fx-b: B?", "decided, awaiting release · decided (1):\n- fx-d: D",
                           "ready milestones · open (1):\n- fx-m [milestone]: Beta", "finished epics (close one whose acceptance names the user) · open (1):\n- fx-e [epic]: Cache",
                           "waiting on the user · held by the user, not offered (1):\n- fx-u [task]: Needs you",
                           "Held by live session other001, not offered: fx-live", "Seeds for the next round"):
                if needle not in out:
                    raise ValueError(f"protocol next prints the whole list, grouped, the first time ({needle!r} missing):\n{out}")
            if out.count("open decision") or out.count("[questions]"):
                raise ValueError("the rows no longer repeat their view and status")
            again = proto("next", **listing_session).stdout
            if "Open items (" in again or "- fx-a: A?" in again or "open questions · open" in again \
                    or "Open items: 1 decided, 2 open questions, 1 waiting on the user, 1 ready milestones, 1 finished epics" not in again \
                    or f"`{engine_module.base.LIST_COMMAND}`" not in again or "board position" not in again or "Seeds for the next round" not in again:
                raise ValueError(f"protocol next lists nothing the second time between compactions: counts and the command:\n{again}")
            calls()
            bare = proto("start", "round", prepass=False, **listing_session).stdout
            if "- fx-b" in bare or "Open items: 1 decided, 2 open questions, 1 waiting on the user" not in bare or "List them before you select." not in bare:
                raise ValueError(f"a bare round after the list was printed counts and tells the model to list first:\n{bare}")
            if "The point set is empty" in bare or "The point set: the open items below" not in bare:
                raise ValueError(f"a pre-pass that lists open items must not call the point set empty:\n{bare}")
            collecting = proto("step", stdin={"pass": "step-back", "summary": "No change."}, **listing_session).stdout
            if "Open items:" not in collecting or "List them before you select" in collecting:
                raise ValueError(f"Collect after the pre-pass lists nothing and does not tell the model to list first:\n{collecting}")
            proto("step", stdin={"classes": {"fx-b": "user"}}, **listing_session)  # an item not printed is classified all the same
            if "fx-b" not in proto("show", **listing_session).stdout:
                raise ValueError("the engine keeps every item: an unprinted id classifies")
            proto("abandon", **listing_session)
            proto("compacted", **listing_session)
            bare = proto("start", "round", prepass=False, **listing_session).stdout
            if "Open items (6):" not in bare or "List them before you select." in bare:
                raise ValueError(f"after a compaction the pre-pass prints the whole list:\n{bare}")
            proto("abandon", **listing_session)
            if "Open items (" in proto("next", **listing_session).stdout:
                raise ValueError("a round's Collect counts as the list printed: protocol next after it does not print it again")
            # A named round: start round <ids>; the whole list the first time, the named ids with counts afterwards.
            proto("compacted", **listing_session)
            named = proto("start", "round", "fx-a", "fx-b", prepass=False, **listing_session).stdout
            if "Open items (6):" not in named or "Named for this round: fx-a, fx-b." not in named:
                raise ValueError(f"a named round prints the whole list the first time:\n{named}")
            proto("abandon", **listing_session)
            named = proto("start", "round", "fx-a", prepass=False, **listing_session).stdout
            if "Named:\n- fx-a: A?\n" not in named or "Open items: 1 decided, 2 open questions, 1 waiting on the user" not in named or "- fx-b" in named \
                    or "List them before you select." in named or "Open items (" in named:
                raise ValueError(f"a named round afterwards prints its ids, the counts and the command:\n{named}")
            if shown(**listing_session)["round"] is None:
                raise ValueError("the named round started")
            proto("step", stdin={"pass": "step-back", "summary": "No change."}, **listing_session)
            proto("step", stdin={"classes": {"fx-a": "user", "fx-b": "user"}}, **listing_session)  # the scope widens: fx-b was not named
            proto("abandon", **listing_session)
            for ids, needle in ((["fx-closed"], "fx-closed is closed"), (["fx-live"], "fx-live is held by live session other001"),
                                (["fx-u"], "fx-u is held by the user"),
                                (["fx-rel"], "fx-rel is released, an item no round offers"), (["fx-null"], "fx-null is unknown"),
                                (["fx-a", "fx-closed", "fx-live"], "fx-closed is closed; fx-live is held by live session other001")):
                refused("start", "round", *ids, needle=needle, **listing_session)
            if shown(**listing_session)["round"] is not None:
                raise ValueError("a refused named round starts nothing")
            refused("start", "round", "fx-a", "--discussion", needle="not with --discussion or --no-board", **listing_session)
            refused("start", "round", "fx-a", "--no-board", str(ctx_notes), needle="not with --discussion or --no-board", **listing_session)
            configure()

            # H: report formats once per step kind between compactions; a refused report reprints only the formats the session was not told since its last compaction,
            # and points at `protocol show` for the rest. The ask instructions
            # once; the dialog itself always.
            fmt = {"session": "0000-ctxfmt001", **home}
            again = "The report format: `protocol show` prints it again."

            def refused_told(stdin):
                err = proto("step", stdin=stdin, ok=False, **fmt).stderr
                if again not in err or "Report with `protocol step`" in err:
                    raise ValueError(f"a refused report for a format the session was told points at `protocol show` and reprints nothing:\n{err}")

            first = proto("start", "round", "--no-board", str(ctx_notes), stdin={"points": ["Formats?"]}, **fmt).stdout
            if "Report with `protocol step`" not in first or '"classes"' not in first:
                raise ValueError(f"the first Collect carries its report format:\n{first}")
            refused_told(stdin={"classes": {"nope": "user"}})
            proto("abandon", **fmt)
            second = proto("start", "round", "--no-board", str(ctx_notes), stdin={"points": ["Again?"]}, **fmt).stdout
            if "Report with" in second:
                raise ValueError(f"the report format of a step kind prints once between compactions:\n{second}")
            refused_told(stdin={"classes": {"nope": "user"}})
            proto("step", stdin={"classes": {"pt2": "user"}}, **fmt)
            refused_told(stdin={"select": ["pt9"]})
            proto("step", stdin={"select": ["pt2"]}, **fmt)
            refused_told(stdin={"questions": []})
            proto("step", stdin={**ROUND_INFO, "questions": [question("Again?", **{"for": "pt2"})]}, **fmt)
            refused_told(stdin={"pass": "step-back", "updates": []})
            ask = converge(**fmt)
            if "Record an answer the user types in chat" not in ask or "open the dialog" not in ask:
                raise ValueError(f"the first ask prints the instructions and the dialog:\n{ask}")
            proto("answer", "--origin", "dialog", stdin={"marker": "round:r2:1", "answers": {"Again?": "Keep"}}, **fmt)
            proto("step", stdin={"pass": "challenge-rulings", "updates": [], "checked": ["the answer"]}, **fmt)
            refused_told(stdin={"records": {}})
            proto("step", stdin={"records": {"q1": {"rationale": "R.", "ruleOwner": "o"}}}, **fmt)
            to_check("Third?", **fmt)
            ask = converge(**fmt)
            if "AskUserQuestion input" in ask or "Record an answer the user types in chat" in ask or "protocol edit" in ask \
                    or "After a reply the person typed instead of picking: answer it as the turn's last text" not in ask:  # every Ask carries it: it matters after a typed reply
                raise ValueError(f"a later ask prints the dialog without the instructions:\n{ask}")
            refused("edit", stdin={"updates": [{"id": staged["q"], "premises": "x"}], "quote": "never said"}, needle='Edit format: `protocol edit` with stdin {"updates"', **fmt)
            refused("answer", "--origin", "chat", stdin={"question": staged["q"], "answer": "Keep", "quote": "never said"}, needle='Chat answer format: stdin {"question"', **fmt)
            proto("abandon", **fmt)
            proto("compacted", **fmt)
            if "Report with" not in proto("start", "round", "--no-board", str(ctx_notes), stdin={"points": ["After?"]}, **fmt).stdout:
                raise ValueError("a compaction brings the report formats back")
            proto("compacted", **fmt)
            err = proto("step", stdin={"classes": {"nope": "user"}}, ok=False, **fmt).stderr
            if 'Report with `protocol step` (stdin JSON), e.g. {"classes"' not in err or again in err:
                raise ValueError(f"after a compaction a refused report reprints the format and does not point at `protocol show`:\n{err}")
            proto("abandon", **fmt)
            # Codex: the ask instructions once; later batches say how to answer in a clause with the marker.
            cdx = {"session": None, "env": {"CODEX_THREAD_ID": "0000-cdx00001", "CODEX_SESSION_ID": "0000-cdx00001", "HOME": str(installed)}}
            to_check("Codex ask?", **cdx)
            ask = converge(**cdx)
            if "Then record the reply: `protocol answer --origin model-reported`" not in ask or "round:r" not in ask:
                raise ValueError(f"the first Codex ask carries the answer instructions:\n{ask}")
            if "Text to show first:\n**Codex ask**\n\nProblem: Which one, and why now.\n\nCases:" not in ask or "show the user the text below first" not in ask:
                raise ValueError(f"the Codex ask carries the rendered text for the model to show:\n{ask}")
            proto("abandon", **cdx)
            to_check("Codex again?", **cdx)
            ask = converge(**cdx)
            marker = shown(**cdx)["batch"]["marker"]
            if "Then record the reply" in ask or f"Record the reply as before: `protocol answer --origin model-reported` (or `decline`), marker {marker}." not in ask \
                    or "Ask the user exactly these questions" not in ask:
                raise ValueError(f"a later Codex ask names the marker and the verb in a clause:\n{ask}")
            proto("abandon", **cdx)

            # D: the Durable owners of project-memory.md print at Owner writes once between compactions, from the installed file.
            own = {"session": "0000-own00001", "cwd": repo, "env": {"HOME": str(installed)}}
            configure(items={"fx-s1": {"status": "decided", "issue_type": "decision", "title": "S1"}})

            def to_owners(**kwargs):
                proto("start", "release", "fx-s1", **kwargs)
                proto("pass", "--origin", "press", stdin={"command": "release-round", "args": "fx-s1", "pending": None}, **kwargs)
                proto("step", stdin={"records": {"fx-s1": "unchanged"}}, **kwargs)
                proto("step", stdin={"checks": {"fx-s1": nones}}, **kwargs)
                return proto("step", stdin={"rulings": []}, **kwargs).stdout

            out = to_owners(**own)
            durable = (installed / ".agents" / "skills" / "shared" / "project-memory.md").read_text(encoding="utf-8").split("## Durable owners", 1)[1].split("\n## ", 1)[0]
            if "## Durable owners (project-memory.md)" not in out or " ".join(durable.split()) not in " ".join(out.split()) \
                    or "## Outstanding work" in out:
                raise ValueError(f"Owner writes prints project-memory.md's Durable owners section, read from the installed file:\n{out}")
            closure = (installed / ".agents" / "skills" / "shared" / "project-memory.md").read_text(encoding="utf-8").split("## Closure", 1)[1].split("\n## ", 1)[0]
            if "## Closure (project-memory.md)" not in out or " ".join(closure.split()) not in " ".join(out.split()):
                raise ValueError(f"Owner writes prints project-memory.md's Closure section with the Durable owners:\n{out}")
            proto("abandon", **own)
            later_owners = to_owners(**own)
            if "Durable owners" in later_owners or "## Closure" in later_owners:
                raise ValueError("the Durable owners print once between compactions")
            proto("abandon", **own)
            proto("compacted", **own)
            if "## Durable owners (project-memory.md)" not in to_owners(**own):
                raise ValueError("a compaction brings the Durable owners back")
            proto("abandon", **own)
            proto("compacted", **own)
            missing = to_owners(**{**own, "env": {"HOME": str(tmp / "no-home")}})
            if "Durable owners: the `## Durable owners` section of" not in missing or "is missing" not in missing or "| Content | Owner |" in missing:
                raise ValueError(f"a missing project-memory.md gives one line naming it:\n{missing}")
            proto("abandon", **own)
            configure()

        if part == "coverage":
            # r4-q15, q16: every pass report keys `checked` by question for its scope; challenge-rulings also re-sends the
            # strongBecause of each strong question in scope (`verdicts`) and lists its own rulings (`rulings`). Each check
            # records its failure and goes on, so one run names every failing case.
            cover = {"session": "0000-cover001", "cover": False}
            failures = []

            def label_fail(label, detail):
                failures.append(f"{label}: {detail}")

            def report(command, checked, updates=None, **extra):
                return {"pass": command, "updates": updates or [], "checked": checked, **extra}

            def expect_refused(label, stdin, *needles, **kwargs):
                result = proto("step", stdin=stdin, ok=None, **{**cover, **kwargs})
                if result.returncode == 0:
                    label_fail(label, f"accepted, expected a refusal naming {needles}")
                    return
                for needle in needles:
                    if needle not in result.stderr:
                        label_fail(label, f"refusal lacks {needle!r}: {result.stderr.strip()[:400]}")

            def expect_ok(label, stdin, **kwargs):
                result = proto("step", stdin=stdin, ok=None, **{**cover, **kwargs})
                if result.returncode != 0:
                    label_fail(label, f"refused: {result.stderr.strip()[:400]}")
                return result.stdout

            def expect_scope(label, out, ids):
                line = ("This pass covers " + " ".join(ids) + ": a `checked` entry (what you examined in it this run, one line of about 120 characters)"
                        if ids else "Nothing changed since this pass last ran")  # the scope line names the target length
                if line not in out:
                    label_fail(label, f"step text lacks {line!r}: {out[-600:]}")

            def pending(**kwargs):
                return (shown(**{"session": cover["session"], **kwargs})["pending"] or {})

            def start_scope(command, stamp=..., **kwargs):
                """`protocol scope` (r9-q36) for a run of `command` starting now; `stamp` left out: the observed run's."""
                stdin = {"command": command, **({} if stamp is ... else {"pending": stamp})}
                return json.loads(proto("scope", "--origin", "plugin", stdin=stdin, **{**cover, **kwargs}).stdout)

            def expect_start_scope(label, command, ids, explored=None, stamp=..., **kwargs):
                """The scope a pass starting now must cover, as the console names it in the expanded skill text; then its report
                without entries is refused naming exactly those ids (the same pass_kind/pass_scope path)."""
                got = start_scope(command, pending(**kwargs).get("id") if stamp is ... else stamp, **kwargs)
                if got["covers"] != ids or got["explored"] != explored:
                    label_fail(label, f"scope verb: {got}, expected covers {ids} explored {explored}")
                if ids and f"This pass covers {' '.join(ids)}: a `checked` entry (what you examined in it this run, one line of about 120 characters)" not in got["text"] or explored and f"Give `explored` an entry for each of {' '.join(explored)} and no other." not in got["text"]:
                    label_fail(label, f"scope verb text: {got['text']!r}")
                if ids and ("`root`" in got["text"]) != (command == "step-back"):
                    label_fail(label, f"scope verb text: only a step-back pass names the `root` check: {got['text']!r}")
                if stamp is ... and ids and explored is None:  # the pending pass's run (stamped as the console does): its report is checked against the same ids
                    expect_refused(f"{label}: the report check", report(command, {"round": "x"}), f"covers {' '.join(ids)}: no `checked` entry or update for {' '.join(ids)}", **kwargs)
                return got

            strong = {"strength": "strong", "strongBecause": STRONG_CLAIMS, "leanBecause": None}
            lean = {"strength": "lean", "leanBecause": {"cause": "evidence", "detail": "bd order, probe it"}}
            proto("start", "round", "--no-board", str(notes), stdin={"points": ["Cover?"]}, **cover)
            proto("step", stdin={"classes": {"pt1": "user"}}, **cover)
            proto("step", stdin={"select": ["pt1"]}, **cover)
            out = proto("step", stdin={**ROUND_INFO, "questions": [question("One?", **{"for": "pt1"}), question("Two?", **{"for": "pt1"}, **strong),
                                                                  question("Three?", **{"for": "pt1"}), question("Four?", **{"for": "pt1"}, **strong)]}, **cover).stdout
            every = ["q1", "q2", "q3", "q4"]
            # The path pass's first run covers every question; the step names them and the keyed shape.
            expect_scope("first-run scope named in the step text", out, every)
            saved = state / f"{cover['session']}.protocol"
            before = [(saved / name).read_bytes() for name in ("state.json", "history.jsonl")]
            if not start_scope("step-back", pending().get("id"))["text"].startswith("Use this scope, not one printed earlier. This pass covers"):
                label_fail("scope verb: the path pass", "the line names that it is the scope as the run starts")
            if [(saved / name).read_bytes() for name in ("state.json", "history.jsonl")] != before:
                label_fail("scope verb changes nothing", "state.json or history.jsonl changed")
            expect_start_scope("scope verb: the path pass", "step-back", every)
            for origin in ("model", "press", "dialog"):
                if proto("scope", "--origin", origin, stdin={"command": "step-back"}, ok=None, **cover).returncode == 0:
                    label_fail("scope verb is the console's", f"origin {origin} accepted")
            if "`command` must be one of" not in proto("scope", "--origin", "plugin", stdin={"command": "commit"}, ok=None, **cover).stderr:
                label_fail("scope verb refuses another command", "accepted")
            if '"checked": {"q2"' not in out:
                label_fail("pass format shows keyed checked", out[-800:])
            expect_refused("checked as a list is refused", report("step-back", ["every question"]), "`checked` is an object")
            expect_refused("unknown checked key is refused", report("step-back", {q: "read" for q in [*every, "q9"]}), "checked.q9")
            expect_refused("refusal names the missing ids", report("step-back", {"q1": "read", "q2": "read"}),
                           "no `checked` entry or update for q3 q4")
            # Coverage by update: q4's update covers it.
            out = expect_ok("coverage by an update", report("step-back", {"q1": "goal read", "q2": "goal read", "q3": "goal read"},
                                                            [{"id": "q4", "premises": "Read again in the fixture."}]))
            # The options pass: `explored` covers its questions.
            expect_start_scope("scope verb: the options pass names explored", "step-back", every, every)
            if start_scope("step-back", "an-older-pass")["explored"] is not None:
                label_fail("scope verb: a run that does not settle the options pass", "names explored ids")
            out = expect_ok("options pass covered by explored", report("step-back", {}, explored={q: "no other mechanism" for q in every}))
            # Base step-back, first run: every question; q1's change is its own.
            expect_scope("base step-back first run = all", out, every)
            out = expect_ok("base step-back first run", report("step-back", {q: "read" for q in every[1:]}, [{"id": "q1", "premises": "Changed by step-back."}]))
            expect_scope("ground first run = all", out, every)
            out = expect_ok("ground first run", report("ground", {q: "read" for q in every[:2] + every[3:]}, [{"id": "q3", "premises": "Changed by ground."}]))
            # Cycle 2: step-back covers what others changed (q3, ground's), not its own q1.
            expect_scope("rerun scope = changed by others", out, ["q3"])
            # Without a stamp the observed run counts, as at report time: none yet reads as an extra pass (its own scope).
            if start_scope("step-back")["covers"] != every:
                label_fail("scope verb: no observed run reads as an extra pass", start_scope("step-back"))
            # A run that is not the pending pass (another stamp) reports as an extra pass too.
            expect_start_scope("scope verb: an extra run", "step-back", every, stamp="an-older-pass")
            expect_start_scope("scope verb: the pending run", "step-back", ["q3"])  # its report check observes the run, stamped
            if start_scope("step-back")["covers"] != ["q3"]:
                label_fail("scope verb: the observed run's stamp", start_scope("step-back"))
            expect_refused("own changes excluded, others' required", report("step-back", {"q1": "read"}), "no `checked` entry or update for q3")
            out = expect_ok("rerun covering the others' change", report("step-back", {"q3": "the ground premise"}))
            # r18-q121: the quiet step-back leaves ground's rerun empty (its own q3 change is covered), so the ground is skipped and the refine pair follows.
            if pending().get("command") != "step-back" or pending().get("args") != "decisions clean overfit mechanics":
                label_fail("a quiet step-back skips the repeated ground", pending())
            # The refine pair runs round-wide: every question.
            expect_scope("refine round-wide scope", out, every)
            expect_refused("refine pass names every missing id", report("step-back", {"round": "x"}), "no `checked` entry or update for q1 q2 q3 q4")
            out = expect_ok("refine step-back", report("step-back", {q: "read" for q in every}))
            out = expect_ok("refine ground", report("ground", {q: "read" for q in every}))
            # The lean pass's first run covers every question too.
            expect_scope("lean pass first run = all", out, every)
            out = expect_ok("lean pass", report("ground", {q: "read" for q in every}))
            # challenge-rulings: every question on its first run; each strong one needs its verdict, and `rulings` its shape.
            expect_scope("challenge first run = all", out, every)
            if "re-send the `strongBecause` of each of q2 q4" not in expect_start_scope("scope verb: challenge-rulings", "challenge-rulings", every)["text"]:
                label_fail("scope verb: challenge-rulings names the strong ids", start_scope("challenge-rulings", pending().get("id")))
            if "verdicts" not in out or "q2 q4" not in out:
                label_fail("challenge step names the strong ids and verdicts", out[-800:])
            allc = {q: "read" for q in every}
            expect_refused("verdict required for a strong question", report("challenge-rulings", allc, rulings=[]),
                           "verdicts.q2", "verdicts.q4")
            expect_refused("verdict strongBecause validated", report("challenge-rulings", allc, rulings=[],
                           verdicts={"q2": {"strongBecause": {}}, "q4": {"strongBecause": STRONG_CLAIMS}}), "verdicts.q2: strong is a claim")
            verdicts = {"q2": {"strongBecause": STRONG_CLAIMS}, "q4": {"strongBecause": STRONG_CLAIMS}}
            expect_refused("verdict on a lean question refused", report("challenge-rulings", allc, rulings=[], verdicts={**verdicts, "q1": {"strongBecause": STRONG_CLAIMS}}),
                           "verdicts.q1")
            expect_refused("rulings required", report("challenge-rulings", allc, verdicts=verdicts), "`rulings` lists")
            ruling = {"question": "q1", "ruling": "one cache", "why": "meets the goal", "alternative": "two caches", "fails": "clear ownership",
                      "evidence": "task-queue.ts:12", "sure": True}
            expect_refused("ruling fields validated", report("challenge-rulings", allc, verdicts=verdicts, rulings=[{**ruling, "why": ""}]),
                           "rulings[0]: needs why")
            expect_refused("ruling sure validated", report("challenge-rulings", allc, verdicts=verdicts, rulings=[{**ruling, "sure": "yes"}]),
                           "rulings[0]: needs")
            expect_refused("ruling question validated", report("challenge-rulings", allc, verdicts=verdicts, rulings=[{**ruling, "question": "q9"}]),
                           "rulings[0]: `question`")
            # A valid challenge that changes q1: the loop reruns; ground then changes q2 (still strong).
            out = expect_ok("valid verdicts and rulings", report("challenge-rulings", {q: "read" for q in every[1:]}, [{"id": "q1", "premises": "Changed by the challenge."}],
                                                                 verdicts=verdicts, rulings=[ruling]))
            expect_scope("step-back after the challenge covers its change", out, ["q1"])
            out = expect_ok("step-back cycle 3", report("step-back", {"q1": "read"}))
            out = expect_ok("ground cycle 3", report("ground", {"q1": "read"}, [{"id": "q2", "premises": "Changed by ground again."}]))
            out = expect_ok("step-back cycle 4", report("step-back", {"q2": "read"}))
            # The quiet cycle-4 step-back skips the ground (q2 is ground's own change); the challenge follows.
            # The challenge rerun covers what changed since it ran (q2), not its own q1; q2 is strong: lowering it covers it.
            expect_scope("challenge rerun = changed since the last challenge", out, ["q2"])
            expect_refused("challenge rerun needs q2's verdict", report("challenge-rulings", {"q2": "read"}, rulings=[]), "verdicts.q2")
            out = expect_ok("a lowering update satisfies the verdict", report("challenge-rulings", {}, [
                {"id": "q2", **lean}, {"id": "q3", "premises": "Changed by the second challenge."}], rulings=[]))
            expect_scope("step-back covers the challenge's changes", out, ["q2", "q3"])
            out = expect_ok("step-back cycle 5", report("step-back", {"q2": "read", "q3": "read"}))
            out = expect_ok("ground cycle 5", report("ground", {"q2": "read", "q3": "read"}))  # the challenge's changes are new to ground: no skip
            expect_scope("challenge scope empty after its own change", out, [])
            if start_scope("challenge-rulings", pending().get("id")) != {"covers": [], "explored": None, "text": ""}:
                label_fail("scope verb: an empty scope names nothing", start_scope("challenge-rulings", pending().get("id")))
            expect_ok("empty challenge with a round note", report("challenge-rulings", {"round": "nothing changed since the last challenge"}, rulings=[]))
            view = shown(session=cover["session"])
            if view["step"] != "ask" or not view["batch"]:
                label_fail("the round reaches Ask", f"{view['step']} {view['pending']}")
            else:
                # After the last answer (r21-q143): the challenge covers the answered set; q4 stays strong but answered, so no verdict.
                proto("answer", "--origin", "dialog", session=cover["session"], stdin={"marker": view["batch"]["marker"], "answers": {
                    q["question"]: "Keep" for q in view["batch"]["questions"]}})
                if pending().get("command") != "challenge-rulings":
                    label_fail("the after-answers challenge is pending", pending())
                expect_refused("after-answers scope = the answered set", report("challenge-rulings", {"round": "x"}, rulings=[]),
                               "no `checked` entry or update for q1 q2 q3 q4")
                expect_ok("after-answers challenge needs no verdict of an answered strong question",
                          report("challenge-rulings", {q: "the answer" for q in every}, rulings=[]))
                # A restart: the scoped path pass covers the restarted id only.
                proto("restart", "q1", "--reason", "fixture", session=cover["session"])
                if pending().get("args", "").split()[:3] != ["goal", "foundations", "on"]:
                    label_fail("a restart queues the scoped path pass", pending())
                expect_refused("scoped path pass covers the restarted id", report("step-back", {"round": "x"}), "no `checked` entry or update for q1")
                expect_ok("scoped path pass", report("step-back", {"q1": "goal read"}))
            # Codex shares the shape: a Codex pass report with a list is refused the same way.
            codex_cover = {"session": "0000-cdx00001", "cover": False}
            proto("start", "round", "--no-board", str(notes), stdin={"points": ["Codex cover?"]}, **codex_cover)
            proto("step", stdin={"classes": {"pt1": "user"}}, **codex_cover)
            proto("step", stdin={"select": ["pt1"]}, **codex_cover)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Codex one?", **{"for": "pt1"})]}, **codex_cover)
            expect_refused("Codex: a list is refused", report("step-back", ["every question"]), "`checked` is an object", **{"session": "0000-cdx00001"})
            expect_ok("Codex: keyed checked accepted", report("step-back", {"q1": "goal read"}), **{"session": "0000-cdx00001"})
            proto("abandon", **codex_cover)
            proto("abandon", **cover)
            # Scoped passes after a restart while the other questions are still open: path, options and refine cover the
            # restarted id only; the Base loop covers it as a change.
            session = {"session": cover["session"]}
            try:
                point = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": ["Scoped?"]}, **session).stdout).group(1)
                proto("step", stdin={"classes": {point: "user"}}, **session)
                proto("step", stdin={"select": [point]}, **session)
                proto("step", stdin={**ROUND_INFO, "questions": [question(f"Scoped {n}?", **{"for": point}) for n in ("A", "B", "C")]}, **session)
                converge(**session)
                a, b, c = [q["id"] for q in shown(**session)["questions"]]
                proto("restart", b, "--reason", "fixture", **session)
                out = proto("show", **session).stdout
                expect_scope("scoped path pass named", out, [b])
                expect_start_scope("scope verb: the scoped path pass", "step-back", [b])
                expect_refused("scoped path pass covers the restarted id only", report("step-back", {"round": "x"}), f"covers {b}: no `checked` entry or update for {b}")
                expect_ok("scoped path pass with the restarted id alone", report("step-back", {b: "goal read"}))
                expect_start_scope("scope verb: the scoped options pass", "step-back", [b], [b])
                expect_refused("scoped options pass refuses another id", report("step-back", {}, explored={b: "no other way", a: "x"}), f"explored: {a} is not covered by this pass")
                out = expect_ok("scoped options pass", report("step-back", {}, explored={b: "no other way"}))
                expect_scope("base step-back covers the restart", out, [b])
                out = expect_ok("base step-back after the restart", report("step-back", {b: "read"}))
                out = expect_ok("base ground after the restart", report("ground", {b: "read"}))
                expect_scope("scoped refine step-back named", out, [b])
                expect_refused("scoped refine step-back covers the restarted id only", report("step-back", {"round": "x"}), f"covers {b}: no `checked` entry or update for {b}")
                out = expect_ok("scoped refine step-back", report("step-back", {b: "read"}))
                expect_refused("scoped refine ground covers the restarted id only", report("ground", {"round": "x"}), f"covers {b}: no `checked` entry or update for {b}")
                expect_ok("scoped refine ground", report("ground", {b: "read"}))
                if c == b:
                    label_fail("three questions staged", [a, b, c])
            except ValueError as error:  # a setup step refused: the scoped cases cannot run
                label_fail("scoped round setup", str(error).strip()[:300])
            proto("abandon", **session)
            if start_scope("ground") != {"covers": [], "explored": None, "text": ""}:
                label_fail("scope verb: no round open names nothing", start_scope("ground"))
            if failures:
                raise ValueError("scoped coverage (r4-q15, q16, r9-q36):\n" + "\n".join(failures))

        if part == "away":
            # r28-q126..q128, r29: the registered role autopilot means away. Ask opens no batch, dialog or print: the model reports
            # `act` (the recommendation is the answer; Record writes needs_ratification with a reversal) or `park` per question.
            def activate(role, session, tool):
                subprocess.run(["bash", str(registry), "activate", role], check=True,
                               env={**os.environ, **session_env(str(state)), **as_session(session, tool)})

            activate("autopilot", "0000-auto0001", "claude")
            activate("autopilot", "0000-cdxauto1", "codex")
            activate("solo", "0000-flip0001", "claude")
            away = {"cwd": repo, "session": "0000-auto0001"}
            records_file = Path(str(log) + ".records")

            def away_round(kwargs, *ids, **extra):
                """A board round on `ids` through its check loop, up to Ask; returns the question ids."""
                patch_config(health={"counts": counts, "items": {"questions": [
                    {"id": rid, "status": "open", "type": "decision", "title": f"{rid}?", "priority": 1, "blockedBy": []} for rid in ids]}})
                proto("start", "round", **kwargs)
                proto("step", stdin={"classes": {rid: "user" for rid in ids}}, **kwargs)
                proto("step", stdin={"select": list(ids)}, **kwargs)
                proto("step", stdin={**ROUND_INFO, "questions": [question(f"{rid}?", board=rid, **extra.get(rid, {})) for rid in ids]}, **kwargs)
                converge(**kwargs)
                return [q["id"] for q in shown(**kwargs)["questions"]]

            # A: no batch, no dialog, no print; the text asks for act or park and names the way back to solo.
            records_file.unlink(missing_ok=True)
            q1, q2 = away_round(away, "fx-a", "fx-b")
            view = shown(**away)
            ask = proto("step", stdin={}, **away).stdout
            if view["step"] != "ask" or view["batch"] is not None or view["pending"] is not None \
                    or "no dialog opens, nothing prints and the person is not asked" not in ask or "AskUserQuestion" in ask \
                    or "run `session activate solo` first" not in ask \
                    or f"- {q1}: fx-a? Recommendation: Keep (lean)" not in ask or "Text to show first" in ask:
                raise ValueError(f"an away Ask opens no batch and asks for act or park per question:\n{ask}\n{view}")
            refused("step", stdin={"settle": {}}, needle=f"settle: no entry for {q1}", **away)
            refused("step", stdin={"settle": {}}, needle="The report format: `protocol show` prints it again.", **away)  # the ask text just printed the format
            refused("step", stdin={"settle": {q1: "act", q2: "later"}}, needle=f'settle.{q2}: "act" or "park"', **away)
            refused("step", stdin={"settle": {q1: "act", q2: "park", "q9": "act"}}, needle="settle: q9 is not waiting to be settled", **away)
            refused("answer", "--origin", "away", stdin={"marker": "round:r1:1", "answers": {}}, needle="origin 'away' is not accepted", **away)
            calls()
            out = proto("step", stdin={"settle": {q1: "act", q2: "park"}}, **away).stdout
            made = [c["args"] for c in calls()]
            parked_rows = {q["id"]: q for q in shown(**away)["questions"]}
            if parked_rows[q1]["status"] != "answered" or parked_rows[q1]["answer"] != "Keep" or parked_rows[q2]["status"] != "parked" \
                    or not any(args[:4] == ["bd", "comments", "add", "fx-b"] and "--board-packet" in args for args in made) or ["unclaim", "fx-b"] not in made \
                    or "away: acted q1, parked q2" not in "\n".join(line["text"] for line in shown(**away)["log"]):
                raise ValueError(f"act answers with the recommendation, park comments the parts on the item and unclaims it:\n{out}\n{made}")
            comment = next(Path(args[args.index("-f") + 1]) for args in made if args[:4] == ["bd", "comments", "add", "fx-b"])
            text = comment.read_text(encoding="utf-8")
            if "## Question\nfx-b?" not in text or "Recommended (" not in text or "- For: for it" not in text or "while the person was away" not in text:
                raise ValueError(f"a parked item carries the question's parts and recommendation:\n{text}")
            if shown(**away)["pending"]["command"] != "challenge-rulings":
                raise ValueError(f"the acted answer gets the pass after the last answer: {shown(**away)['pending']}")
            after_answers(**away)
            if shown(**away)["step"] != "record":
                raise ValueError(f"Record follows the acted answer: {shown(**away)}")
            asking = proto("show", **away).stdout
            if "answer (away): Keep" not in asking or "away answer: the record also needs `reversal`" not in asking:
                raise ValueError(f"Record asks the reversal of an away answer:\n{asking}")
            refused("step", stdin={"records": {q1: {"rationale": "Took fx-a.", "ruleOwner": "docs/x.md"}}}, needle="an away answer needs a `reversal`", **away)
            refused("step", stdin={"records": {q1: {"rationale": "Took fx-a.", "ruleOwner": "docs/x.md", "reversal": ["undo it"]}}}, needle="`reversal` and `decision` are text", **away)
            calls()
            out = proto("step", stdin={"records": {q1: {"rationale": "Took fx-a.", "ruleOwner": "docs/x.md", "reversal": "board bd reopen fx-a"}}}, **away).stdout
            recorded = records_file.read_text(encoding="utf-8")
            made = [c["args"] for c in calls()]
            if not any(args[:3] == ["ruling", "record", "fx-a"] and args[4:] == ["--status", "needs_ratification"] for args in made) \
                    or "\n## Reversal\nboard bd reopen fx-a\n" not in recorded or "\nAway round (autopilot took the recommendation; no person answered), " not in recorded \
                    or "User (" in recorded or "Round r" not in out or f"- {q2} parked → fx-b: open and unassigned for the person" not in out:
                raise ValueError(f"an away answer is recorded as needs_ratification with its reversal, from an away round:\n{recorded}\n{made}\n{out}")

            # B: a draft (no board item) becomes an open decision carrying its parts; nothing waits for the dialog.
            configure(related={}, newIds=["fx-park1"])
            out = proto("start", "round", stdin={"points": [{"text": "Park point"}]}, **away).stdout
            if "{'text'" in out or "[pasted]: Park point" not in out:
                raise ValueError(f"a pasted point given as an object keeps its text: {out}")
            pasted = re.search(r"(pt\d+) \[pasted\]", out).group(1)
            proto("step", stdin={"classes": {pasted: "user"}}, **away)
            proto("step", stdin={"select": [pasted]}, **away)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Park point?", **{"for": pasted})]}, **away)
            converge(**away)
            calls()
            out = proto("step", stdin={"settle": {shown(**away)["questions"][0]["id"]: "park"}}, **away).stdout
            created = [c["args"] for c in calls() if c["args"][:3] == ["bd", "create", "--type"]]
            body = Path(created[0][created[0].index("--body-file") + 1]).read_text(encoding="utf-8") if created else ""
            if len(created) != 1 or "Park point?" not in body or "Problem: Which one, and why now." not in body or "Recommended (" not in body \
                    or shown(**away)["step"] != "record":
                raise ValueError(f"a parked draft becomes an open decision with its parts: {created}\n{body}\n{out}")
            out = proto("step", stdin={"records": {}}, **away).stdout
            if "parked → fx-park1" not in out:
                raise ValueError(f"the close names the parked item:\n{out}")
            configure()

            # C: a question waiting on a parked one parks too.
            patch_config(health={"counts": counts, "items": {"questions": [
                {"id": rid, "status": "open", "type": "decision", "title": f"{rid}?", "priority": 1, "blockedBy": []} for rid in ("fx-a", "fx-b")]}})
            proto("start", "round", **away)
            proto("step", stdin={"classes": {"fx-a": "user", "fx-b": "user"}}, **away)
            proto("step", stdin={"select": ["fx-a", "fx-b"]}, **away)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Chain a?", key="a", board="fx-a"), question("Chain b?", key="b", waitsOn=["a"], board="fx-b")]}, **away)
            converge(**away)
            first, second = [q["id"] for q in shown(**away)["questions"]]
            if proto("step", stdin={}, **away).stdout.count(f"- {second}:"):
                raise ValueError("a held question is not offered for settling")
            # A later pass corrects what the options pass reported; what it dropped shows in the parked text.
            proto("step", stdin={"pass": "ground", "updates": [], "checked": ["x"], "explored": {first: [{"idea": "no store", "verdict": "dropped", "why": "reads need it"}]}}, **away)
            calls()
            proto("step", stdin={"settle": {first: "park"}}, **away)
            if {q["id"]: q["status"] for q in shown(**away)["questions"]} != {first: "parked", second: "parked"} or shown(**away)["step"] != "record":
                raise ValueError(f"a question waiting on a parked one parks with it: {shown(**away)}")
            parked_calls = [c["args"] for c in calls()]
            comments = {args[3]: Path(args[5]).read_text(encoding="utf-8") for args in parked_calls if args[:3] == ["bd", "comments", "add"]}
            # A plain link between them, not a block: a block would outlast the answer (r31-q145).
            if ["bd", "dep", "add", "fx-b", "fx-a", "-t", "relates-to"] not in parked_calls or any(args[:1] == ["block"] for args in parked_calls) \
                    or "Waits on: " not in comments.get("fx-b", ""):
                raise ValueError(f"the wait between parked questions shows as a link and in the text: {parked_calls}\n{comments}")
            if "- Dropped: no store - reads need it" not in comments.get("fx-a", ""):
                raise ValueError(f"a later pass corrects the explored ideas: {comments}")
            proto("step", stdin={"records": {}}, **away)

            # An acted rule question closes what it settles at once, and its reversal reopens them (r31-q143); they are not unclaimed afterwards.
            configure(related={}, newIds=["fx-rule"])
            patch_config(health={"counts": counts, "items": {"questions": [
                {"id": rid, "status": "open", "type": "decision", "title": f"{rid}?", "priority": 1, "blockedBy": []} for rid in ("fx-a", "fx-b")]}})
            proto("start", "round", **away)
            proto("step", stdin={"classes": {"fx-a": "user", "fx-b": "user"}}, **away)
            proto("step", stdin={"select": ["fx-a", "fx-b"]}, **away)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Rule both?", key="r", settles=["fx-a", "fx-b"], premises="applies to both")]}, **away)
            converge(**away)
            rule = shown(**away)["questions"][0]["id"]
            proto("step", stdin={"settle": {rule: "act"}}, **away)
            calls()
            records_file.unlink(missing_ok=True)
            proto("step", stdin={"records": {rule: {"rationale": "Took it, for fx-a and fx-b.", "ruleOwner": "docs/x.md", "reversal": "Revise the ruling."}}}, **away)
            acted = [c["args"] for c in calls()]
            reversal = records_file.read_text(encoding="utf-8")
            closes = [args[2] for args in acted if args[:2] == ["bd", "close"]]
            if closes != ["fx-a", "fx-b"] or "`board bd reopen fx-a fx-b`" not in reversal \
                    or any(args[0] == "unclaim" and ("fx-a" in args or "fx-b" in args) for args in acted):
                raise ValueError(f"an away ruling closes what it settles, and its reversal reopens them:\n{acted}\n{reversal}")

            # D: the check cap while away: no cap dialog, the unsettled questions park.
            patch_config(health={"counts": counts, "items": {"questions": [
                {"id": "fx-a", "status": "open", "type": "decision", "title": "fx-a?", "priority": 1, "blockedBy": []}]}})
            proto("start", "round", **away)
            proto("step", stdin={"classes": {"fx-a": "user"}}, **away)
            proto("step", stdin={"select": ["fx-a"]}, **away)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Cap?", board="fx-a")]}, **away)
            qid = shown(**away)["questions"][0]["id"]
            proto("step", stdin={"pass": "step-back", "updates": [], "checked": ["every question"]}, **away)  # the path pass
            proto("step", stdin={"pass": "step-back", "updates": [], "checked": ["every question"]}, **away)  # the options pass
            for cycle in range(1, cap_cycles + 1):
                proto("step", stdin={"pass": "step-back", "updates": [{"id": qid, "premises": f"premise {cycle}"}]}, **away)
                proto("step", stdin={"pass": "ground", "updates": [], "checked": ["every question"]}, **away)
            capped = shown(**away)
            log_lines = [line["text"] for line in capped["log"]]
            if capped["batch"] is not None or capped["pending"] is not None or capped["step"] != "record" \
                    or capped["questions"][0]["status"] != "parked" or f"cycle cap at {cap_cycles}: the questions park" not in log_lines:
                raise ValueError(f"the cap while away parks the round's questions without a cap dialog: {capped}")
            proto("step", stdin={"records": {}}, **away)

            # E: a release and a round without a board are refused, naming the way back to solo.
            for args, needle in ((("start", "release"), "only the person approves a release"),
                                 (("start", "round", "--no-board", str(notes)), "--no-board is refused on autopilot")):
                result = proto(*args, stdin={"points": ["x"]} if args[1] == "round" else None, ok=False, **away)
                if needle not in result.stderr or "run `" + "session activate solo` first" not in result.stderr:
                    raise ValueError(f"{args} under autopilot is refused, naming the switch to solo: {result.stderr}")
            refused("pass", "--origin", "composer", stdin={"command": "release-round", "args": "", "pending": None},
                    needle="only the person approves a release", **away)

            # F: a batch still out when the role becomes autopilot is withdrawn; its questions settle as away at the next step.
            flip = {"cwd": repo, "session": "0000-flip0001"}
            away_round(flip, "fx-a", "fx-b")
            if shown(**flip)["batch"] is None:
                raise ValueError("a solo round asks with a batch")
            activate("autopilot", "0000-flip0001", "claude")
            out = proto("step", stdin={}, **flip).stdout
            after = shown(**flip)
            if after["batch"] is not None or after["step"] != "ask" or "no dialog opens" not in out \
                    or not any(line["text"] == "batch 1 withdrawn for updates" for line in after["log"]) \
                    or sorted(q["status"] for q in after["questions"]) != ["ready", "ready"]:
                raise ValueError(f"a batch out when the role became autopilot is withdrawn and settles as away:\n{out}\n{after}")
            activate("solo", "0000-flip0001", "claude")
            proto("step", stdin={}, **flip)
            if shown(**flip)["batch"] is None:
                raise ValueError("back in solo the questions go out in a batch again")
            proto("abandon", **flip)
            # A cap batch out under solo parks the questions once the role is autopilot.
            patch_config(health={"counts": counts, "items": {"questions": [
                {"id": "fx-a", "status": "open", "type": "decision", "title": "fx-a?", "priority": 1, "blockedBy": []}]}})
            proto("start", "round", **flip)
            proto("step", stdin={"classes": {"fx-a": "user"}}, **flip)
            proto("step", stdin={"select": ["fx-a"]}, **flip)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Cap?", board="fx-a")]}, **flip)
            qid = shown(**flip)["questions"][0]["id"]
            proto("step", stdin={"pass": "step-back", "updates": [], "checked": ["every question"]}, **flip)
            proto("step", stdin={"pass": "step-back", "updates": [], "checked": ["every question"]}, **flip)
            for cycle in range(1, cap_cycles + 1):
                proto("step", stdin={"pass": "step-back", "updates": [{"id": qid, "premises": f"premise {cycle}"}]}, **flip)
                proto("step", stdin={"pass": "ground", "updates": [], "checked": ["every question"]}, **flip)
            if (shown(**flip)["batch"] or {}).get("questions", [{}])[0].get("header") != "Check cap":
                raise ValueError(f"a solo round at the cap asks the cap question: {shown(**flip)}")
            activate("autopilot", "0000-flip0001", "claude")
            proto("step", stdin={}, **flip)
            if shown(**flip)["batch"] is not None or shown(**flip)["questions"][0]["status"] != "parked" or shown(**flip)["step"] != "record":
                raise ValueError(f"a cap batch out when the role became autopilot parks the questions: {shown(**flip)}")
            proto("abandon", **flip)
            activate("solo", "0000-flip0001", "claude")

            # A release approval out when the role becomes autopilot: only the person approves, so nothing settles away.
            configure(items={"fx-r1": {"status": "decided", "issue_type": "decision", "assignee": "flip0001", "title": "R1"}})
            proto("start", "release", "fx-r1", **flip)
            proto("step", stdin={"records": {"fx-r1": "unchanged"}}, **flip)
            proto("step", stdin={"checks": {"fx-r1": nones}}, **flip)
            proto("step", stdin={"rulings": [{"record": "fx-r1", "ruling": "r", "why": "w", "alternative": "a", "fails": "f", "evidence": "e", "sure": False}]}, **flip)
            if shown(**flip)["batch"] is None:
                raise ValueError(f"an unsure ruling sends the approval to a dialog: {shown(**flip)}")
            activate("autopilot", "0000-flip0001", "claude")
            refused("step", stdin={}, needle="only the person approves a release", **flip)
            if shown(**flip)["batch"] is None:
                raise ValueError("the approval stays out: nothing settles away")
            activate("solo", "0000-flip0001", "claude")
            proto("abandon", **flip)
            configure()

            # G: Codex runs the same away Ask: the model runs the passes, the text carries no print.
            codex_away = {"cwd": repo, "session": "0000-cdxauto1"}
            c1, c2 = away_round(codex_away, "fx-a", "fx-b")
            out = proto("step", stdin={}, **codex_away).stdout
            if "no dialog opens" not in out or "Text to show first" in out or "model-reported" in out or shown(**codex_away)["batch"] is not None:
                raise ValueError(f"the Codex away Ask is the same report:\n{out}")
            proto("step", stdin={"settle": {c1: "park", c2: "act"}}, **codex_away)
            if {q["id"]: q["status"] for q in shown(**codex_away)["questions"]} != {c1: "parked", c2: "answered"}:
                raise ValueError(f"Codex settles an away Ask: {shown(**codex_away)}")
            proto("abandon", **codex_away)
            configure()


def validate_worker_last_use(root: Path) -> None:
    """Exercise only synthetic transcripts, never the invoking session's workers."""
    from datetime import datetime, timedelta, timezone

    helper = root / "bin" / "worker-last-use"
    bootstrap = """import os, runpy, sys
from unittest.mock import patch
fixture_root, helper, *arguments = sys.argv[1:]
with patch('os.path.expanduser', lambda path: os.path.join(fixture_root, path[2:]) if path.startswith('~/') else path):
    sys.argv = [helper, *arguments]
    runpy.run_path(helper, run_name='__main__')
"""
    parent = "00000000-0000-0000-0000-000000000001"
    worker = "00000000-0000-0000-0000-000000000002"
    expired = "00000000-0000-0000-0000-000000000003"
    unknown = "00000000-0000-0000-0000-000000000004"
    claude_parent = "00000000-0000-0000-0000-000000000005"
    failures = []

    def check(condition, label, result):
        if not condition:
            failures.append(f"{label}: exit={result.returncode}, stdout={result.stdout!r}, stderr={result.stderr!r}")

    with tempfile.TemporaryDirectory() as directory:
        fixture_root = Path(directory)
        sessions = fixture_root / ".codex" / "sessions" / "2026" / "10" / "25"
        sessions.mkdir(parents=True)

        def transcript(identity, age=0, **metadata):
            moment = datetime.now(timezone.utc) - timedelta(minutes=age)
            path = sessions / f"rollout-2026-10-25T00-00-00-{identity}.jsonl"
            rows = [{"type": "session_meta", "payload": {"id": identity, **metadata}},
                    {"type": "event_msg", "timestamp": moment.isoformat()}]
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            os.utime(path, (moment.timestamp(), moment.timestamp()))
            return path

        transcript(parent)
        warm_path = transcript(worker, age=5, parent_thread_id=parent, agent_role="verify", agent_nickname="Warm fixture")
        transcript(expired, age=35, parent_thread_id=parent, agent_role="review", agent_nickname="Expired fixture")
        env = {**os.environ, "CLAUDE_CODE_SESSION_ID": "", "CODEX_THREAD_ID": parent, "CODEX_SESSION_ID": ""}

        def invoke(*arguments, **overrides):
            return subprocess.run([sys.executable, "-B", "-c", bootstrap, str(fixture_root), str(helper), *arguments],
                                  text=True, capture_output=True, env={**env, **overrides})

        result = invoke("--help")
        check(result.returncode == 0 and "usage:" in result.stdout.lower() and "parent" in result.stdout.lower()
              and "no worker active" not in result.stdout, "--help displays usage", result)
        result = invoke(parent)
        check(result.returncode == 0 and "Warm fixture" in result.stdout and worker in result.stdout
              and "Expired fixture" not in result.stdout, "recognized parent lists only warm workers", result)
        result = invoke()
        check(result.returncode == 0 and "Warm fixture" in result.stdout, "environment parent default", result)
        for identity in (worker, expired):
            result = invoke(identity)
            check(result.returncode != 0 and parent in result.stderr and "parent session" in result.stderr.lower()
                  and "no worker active" not in result.stdout, "worker ID cannot masquerade as an empty parent", result)
        result = invoke(unknown)
        check(result.returncode != 0 and unknown in result.stderr and "no worker active" not in result.stdout,
              "unknown parent is not a cold-worker result", result)
        for arguments in (("--invalid-option",), (parent, "extra")):
            result = invoke(*arguments)
            check(result.returncode != 0 and "usage:" in result.stderr.lower(), "invalid CLI arguments", result)
        result = invoke(CODEX_THREAD_ID="")
        check(result.returncode != 0 and "parent session" in result.stderr.lower(), "missing parent argument", result)
        old = (datetime.now(timezone.utc) - timedelta(minutes=35)).timestamp()
        os.utime(warm_path, (old, old))
        result = invoke(parent)
        check(result.returncode == 0 and "no worker active within 30 min" in result.stdout and parent in result.stdout,
              "recognized parent with no warm workers is explicit", result)

        project = fixture_root / ".claude" / "projects" / "fixture-project"
        workers = project / claude_parent / "subagents"
        workers.mkdir(parents=True)
        (project / f"{claude_parent}.jsonl").write_text("{}\n", encoding="utf-8")
        child = workers / "agent-child-fixture.jsonl"
        child.write_text(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat()}) + "\n", encoding="utf-8")
        result = invoke(claude_parent)
        check(result.returncode == 0 and "child-fixture" in result.stdout, "Claude parent listing", result)
        result = invoke("*")
        check(result.returncode != 0 and "no worker active" not in result.stdout and "child-fixture" not in result.stdout,
              "unknown glob-like ID cannot select another parent's workers", result)
        result = invoke("child-fixture")
        check(result.returncode != 0 and claude_parent in result.stderr and "no worker active" not in result.stdout,
              "Claude worker ID points to its parent", result)
        result = invoke(CLAUDE_CODE_SESSION_ID=claude_parent)
        check(result.returncode == 0 and "child-fixture" in result.stdout, "Claude environment precedence", result)
        # A matching child records its parent even when that parent's transcript was removed.
        (project / f"{claude_parent}.jsonl").unlink()
        result = invoke(claude_parent)
        check(result.returncode == 0 and "child-fixture" in result.stdout, "child metadata can identify a parent", result)

    if failures:
        raise ValueError("worker-last-use regressions:\n" + "\n".join(failures))


READ_LIMIT = 35_000  # characters; Codex cuts a call's output above ~40,000 from the middle


def validate_read_sizes(root: Path, expander) -> None:
    skills = root / "skills"
    sizes = {path.relative_to(root): len(expander.expand_markdown(path, skills))
             for path in sorted(skills.rglob("*.md"))}
    sizes |= {path.relative_to(root): len(path.read_text(encoding="utf-8"))
              for path in [root / "AGENTS.md", *sorted((root / "definitions").glob("*.md"))]}
    over = {str(path): size for path, size in sizes.items() if size > READ_LIMIT}
    if over:
        raise ValueError(f"files above {READ_LIMIT} characters lose their middle in one Codex read: {over}")
    largest = sorted(sizes.items(), key=lambda item: -item[1])[:5]
    print("largest instruction files (characters): " + ", ".join(f"{path} {size}" for path, size in largest))


def run_group(name: str, root: Path) -> None:
    generator = load_generator(root)
    expander = load_skill_expander(root)
    if name == "core":
        validate_skills(root)
        validate_policy_semantics()
        validate_skill_expander(root, expander)
        validate_rendered_skills(root, expander)
        validate_skill_loading(root, expander)
        validate_read_sizes(root, expander)
        validate_generated_agents(root, generator)
        validate_multiline_and_optional_names(generator)
        validate_agent_includes(generator)
        validate_effort_overrides(generator)
        validate_worker_last_use(root)
        validate_copied_install(root)
        validate_engine_board_fields(root)
        validate_console_lenses(root)
        validate_start_round(root)
        validate_console_programs(root)
        validate_strength_rules(root)
        validate_engine_counts(root)
        validate_lens_names(root)
        validate_shebang_modes(root)
        validate_review_tiers(root)
    elif name == "hooks":
        validate_hooks(root)
    elif name == "board":
        validate_board(root)  # patches os.environ and stdout in-process: nothing else shares this process
        validate_shared_board(root)
        validate_console_unblocks(root)
        validate_console_no_board(root)
        validate_session_prune(root)
        validate_cr_rank(root)
    elif name == "contract":
        validate_console_contract(root)
    elif name == "prepass":
        validate_prepass(root)
        validate_default_records(root)
    elif name.startswith("engine-"):
        validate_protocol(root, name.removeprefix("engine-"))
    else:
        raise SystemExit(f"unknown group {name}")


GROUPS = ("core", "hooks", "board", "contract", "prepass", *(f"engine-{part}" for part in PROTOCOL_PARTS))


def main() -> int:
    args = sys.argv[1:]
    group = args.pop(args.index("--group") + 1) if "--group" in args else None
    if group:
        args.remove("--group")
    root = Path(args[0]).resolve() if args else Path(__file__).resolve().parents[1]
    if group:
        run_group(group, root)
        return 0
    # The groups are independent: each runs as a child of this script, beside the others.
    children = []
    for name in GROUPS:
        output = tempfile.TemporaryFile("w+", encoding="utf-8")
        children.append((name, output, subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), str(root), "--group", name],
                                                        stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT, text=True)))
    failed = []
    for name, output, child in children:
        code = child.wait()
        output.seek(0)
        text = output.read()
        output.close()
        if code != 0:
            failed.append(name)
            print(f"--- group {name} failed (exit {code}) ---\n{text}", file=sys.stderr)
        elif text.strip():
            print(text, end="" if text.endswith("\n") else "\n")
    if failed:
        print(f"agent-config validation failed: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("shared agent and skill validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())