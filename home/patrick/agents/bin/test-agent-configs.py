#!/usr/bin/env python3
"""Validate shared skills and both generated custom-agent formats."""

from __future__ import annotations

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
from datetime import datetime, timezone
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
            ".scratch/<topic-slug>/<arc-slug>/",
        ),
        skills_dir / "shared" / "project-memory.md": (
            ".scratch/<topic-slug>/<arc-slug>/",
            "<topic-slug>/<arc-slug>",
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
        "explorer.toml",
        "option-explorer.toml",
        "plan.toml",
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
        "Explore.md",
        "option-explorer.md",
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

    # Source comparison catches omissions shared by both adapters.
    for path in sorted(source.glob("*.md")):
        _, frontmatter, body = path.read_text(encoding="utf-8").split("---", 2)
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

    specialists = {
        "architect": "architect",
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
        if "readonly-guard.sh" not in document:
            raise ValueError(f"Claude {claude_name} lost its readonly Bash hook")

    for codex_name, claude_name in {"scout": "scout", "explorer": "Explore"}.items():
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
    script = root / "bin" / "session-lead-mode"

    def run(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(script), *args], text=True, capture_output=True,
                              env={**os.environ, **env})

    with tempfile.TemporaryDirectory() as state_dir:
        env = session_env(state_dir)
        run("activate", "lead", env={**env, **as_session(SESSION)}).check_returncode()
        if run("get", SESSION, env=env).stdout.strip() != "lead":
            raise ValueError("session-lead-mode lost a registered lead")
        shown = json.loads(run("show", SESSION, env=env).stdout)
        if (shown["role"], shown["pulls"], shown["actor"], shown["tool"]) != ("lead", [], SESSION_ACTOR, "claude"):
            raise ValueError(f"session-lead-mode show: {shown}")

        other = "0a1b2c3d-0000-4000-8000-00000000beef"
        run("activate", "agent", "--pulls", "review,plan", env={**env, **as_session(other, "codex")}).check_returncode()
        if (json.loads(run("show", other, env=env).stdout)["pulls"], json.loads(run("show", other, env=env).stdout)["tool"]) \
                != (["plan", "review"], "codex"):
            raise ValueError("session-lead-mode did not store the Codex agent's pulls in canonical order")

        run("activate", "solo", env={**env, **as_session(SESSION)}).check_returncode()
        changed = json.loads(run("show", SESSION, env=env).stdout)
        if changed["role"] != "solo" or changed["actor"] != SESSION_ACTOR:
            raise ValueError("a role change must keep the session's actor")

        rejected = (
            (("activate", "agent"), as_session("abcdefgh-1")),
            (("activate", "lead", "--pulls", "plan"), as_session("abcdefgh-1")),
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
                raise ValueError(f"session-lead-mode accepted {args} as {identity}")

        # actor: the session's, plus a Codex worker's own thread; Codex wins when both are set.
        for identity, expected in ((as_session(SESSION), SESSION_ACTOR),
                                   ({**as_session(SESSION, "codex"), "CODEX_THREAD_ID": other}, f"{SESSION_ACTOR}/{other[-8:]}"),
                                   ({**as_session(SESSION, "codex"), "CLAUDE_CODE_SESSION_ID": other}, SESSION_ACTOR)):
            if run("actor", env={**env, **identity}).stdout.strip() != expected:
                raise ValueError(f"session-lead-mode actor for {identity}: expected {expected}")
        if run("actor", env=env).returncode == 0:
            raise ValueError("session-lead-mode actor invented an actor outside an agent session")
        if sorted(path.name for path in Path(state_dir).iterdir()) != sorted([f"{SESSION}.json", f"{other}.json"]):
            raise ValueError("a rejected activation wrote the registry")

        if run("get", "abcdefgh-unknown", env=env).stdout.strip():
            raise ValueError("session-lead-mode invented a role")
        unknown = json.loads(run("show", "abcdefgh-unknown", env=env).stdout)
        if unknown["role"] is not None or unknown["actor"] != "-unknown"[-8:]:
            raise ValueError(f"show of an unregistered session: {unknown}")
        if run("get", env={**env, "CLAUDE_CODE_SESSION_ID": other}).returncode == 0:
            raise ValueError("get must not take the session id from the environment")
        listed = [json.loads(line) for line in run("list", env=env).stdout.splitlines()]
        if sorted(entry["actor"] for entry in listed) != sorted([SESSION_ACTOR, other[-8:]]):
            raise ValueError(f"session-lead-mode list: {listed}")

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
                raise ValueError(f"session-lead-mode {command[0]} must be a silent no-op for an unregistered session")
            if run(*command, env=env).returncode != 0 or any(Path(state_dir).iterdir()):
                raise ValueError(f"session-lead-mode {command[0]} must be a silent no-op outside an agent session")
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
        if any(path.name.startswith(".") for path in Path(state_dir).iterdir() if path.name != f"{SESSION}.json"):
            raise ValueError("session-lead-mode left temporary files")
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
            raise ValueError(f"session-lead-mode list lacks the liveness and activity fields: {listed}")
        unregistered = json.loads(run("show", "abcdefgh-unknown", env=env).stdout)
        if (unregistered["active_at"], unregistered["workers"]) != (None, {}):
            raise ValueError(f"show of an unregistered session: {unregistered}")

        # session-activity hook: SubagentStart and a worker's tool call (agent_id) create or touch the worker's
        # marker, SubagentStop deletes it, the session's own tool call touches its activity file; it never fails.
        hook = root / "hooks" / "session-activity.sh"
        hook_env = {**env, "AGENT_SESSION_LEAD_COMMAND": str(script)}
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
                 {**hook_env, "AGENT_SESSION_LEAD_COMMAND": str(Path(bin_dir) / "missing")})
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
        if sorted(path.name for path in Path(state_dir).iterdir()) != [f"{SESSION}.active", f"{SESSION}.json", f"{SESSION}.workers"]:
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
            raise ValueError(f"session-lead-mode list lacks the project: {listed}")
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
                raise ValueError(f"session-lead-mode state-dir printed {named!r}, expected {expected!r}")


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
    for command in ("session-lead-mode activate lead", "~/.agents/bin/session-lead-mode activate agent --pulls plan",
                    'bash "$HOME/.agents/bin/session-lead-mode" activate solo', "cd x && session-lead-mode activate lead"):
        for extra in (worker, {**worker, "turn_id": "t"}):
            result = run_hook(hook, pre_tool_use(command, session_id=SESSION, **extra))
            if not result or result["hookSpecificOutput"].get("permissionDecision") != "deny":
                raise ValueError(f"session-register let a worker register: {command!r}")
        if run_hook(hook, pre_tool_use(command, session_id=SESSION)) is not None:
            raise ValueError(f"session-register touched a session's {command!r}")
    for command in ("session-lead-mode show", "rg 'session-lead-mode activate' skills", "echo session-lead-mode activate"):
        if run_hook(hook, pre_tool_use(command, session_id=SESSION, **worker)) is not None:
            raise ValueError(f"session-register denied {command!r}")


def validate_compact_reorient(root: Path) -> None:
    hook = root / "hooks" / "compact-reorient.sh"
    env_base = {"AGENT_SESSION_LEAD_COMMAND": str(root / "bin" / "session-lead-mode")}
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
        "checkpoint file",
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
        subprocess.run(["bash", str(root / "bin" / "session-lead-mode"), "activate", "agent", "--pulls",
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
        subprocess.run(["bash", str(root / "bin" / "session-lead-mode"), "activate", "lead"], check=True,
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
                'bash "$HOME/.agents/bin/board" claim x', "~/.agents/bin/board release a b",
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
    shipped = [root / "setup" / "install.sh", root / "bin" / "session-lead-mode", *sorted((root / "hooks").glob("*.sh")),
               *sorted((root.parent / "claude" / "hooks").glob("*.sh"))]
    for path in shipped:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.lstrip().startswith("#") and SETUP_BASH4.search(line):
                raise ValueError(f"{path}:{number} needs a newer bash than 3.2: {line.strip()}")


def validate_setup_installer(root: Path) -> None:
    """setup/install.sh in a fake home: keeps the user's files, upgrades by its own state, stops before any change."""
    installer = root / "setup" / "install.sh"
    board_version = re.search(r"\(bd (\d+\.\d+\.\d+)\)", (root / "bin" / "board").read_text(encoding="utf-8"))
    if board_version is None or f"bd_tested={board_version.group(1)}\n" not in installer.read_text(encoding="utf-8"):
        raise ValueError("setup/install.sh bd_tested differs from the bd version bin/board names")

    def hook(command: str) -> dict:
        return {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": command}]}]}}

    def bundle(base: Path, name: str, version: str, shipped: dict[str, str], claude: str, codex: str) -> Path:
        folder = base / name
        for rel, text in shipped.items():
            target = folder / "files" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        (folder / "settings").mkdir()
        (folder / "settings" / "claude-hooks.json").write_text(json.dumps(hook(claude)), encoding="utf-8")
        (folder / "settings" / "codex-hooks.json").write_text(json.dumps(hook(codex)), encoding="utf-8")
        (folder / "VERSION").write_text(f"{version}\n", encoding="utf-8")
        shutil.copy2(installer, folder / "install.sh")
        return folder

    def tree(base: Path) -> dict[str, str]:
        return {str(path.relative_to(base)): path.read_text(encoding="utf-8") for path in sorted(base.rglob("*")) if path.is_file()}

    with tempfile.TemporaryDirectory() as directory:
        base = Path(directory)
        tools = base / "tools"
        tools.mkdir()
        for name in ("bash", "env", "jq", "python3", "cat", "cmp", "comm", "cp", "date", "dirname", "find", "grep", "head", "mkdir",
                     "mktemp", "mv", "rm", "rmdir", "sed", "sort"):
            located = shutil.which(name)
            if located is None:
                raise ValueError(f"the installer test needs {name} on PATH")
            (tools / name).symlink_to(located)
        fake_bd = tools / "bd"
        fake_bd.write_text(f"#!/bin/sh\necho 'bd version {board_version.group(1)} (test)'\n", encoding="utf-8")
        fake_bd.chmod(0o755)
        home = base / "home"
        home.mkdir()

        def run(folder: Path, *flags: str, path: Path = tools):
            return subprocess.run([str(tools / "bash"), str(folder / "install.sh"), *flags], capture_output=True, text=True, check=False,
                                  stdin=subprocess.DEVNULL, env={"HOME": str(home), "PATH": str(path)})

        def ok(folder: Path, *flags: str):
            result = run(folder, *flags)
            if result.returncode != 0:
                raise ValueError(f"install.sh {flags} failed: {result.stdout}{result.stderr}")
            return result

        def refuses(what: str, folder: Path, fragment: str, path: Path = tools) -> None:
            before = tree(home)
            result = run(folder, path=path)
            if result.returncode == 0 or fragment not in result.stderr or tree(home) != before:
                raise ValueError(f"install.sh must stop on {what} before any change: {result.returncode} {result.stderr} {result.stdout}")

        def commands(rel: str) -> list[str]:
            config = json.loads((home / rel).read_text(encoding="utf-8"))
            return [entry["command"] for groups in config.get("hooks", {}).values() for group in groups for entry in group["hooks"]]

        v1 = bundle(base, "v1", "one", {
            ".claude/CLAUDE.md": "setup rules\n",
            ".codex/AGENTS.md": "setup rules\n",
            ".claude/skills/kept/SKILL.md": "kept\n",
            ".claude/skills/kept/dropped.md": "dropped\n",
            ".claude/skills/gone/SKILL.md": "gone\n",
            ".agents/bin/tool": "#!/bin/sh\n",
            ".claude/mods/console/.claude-plugin/plugin.json": "{}\n",
        }, 'bash "$HOME/.claude/hooks/one.sh"', 'bash "$HOME/.codex/hooks/one.sh"')
        (v1 / "files" / ".agents" / "bin" / "tool").chmod(0o755)

        own_hook = {"matcher": "Edit", "hooks": [{"type": "command", "command": "mine.sh"}]}
        (home / ".claude" / "skills" / "mine").mkdir(parents=True)
        (home / ".claude" / "skills" / "mine" / "SKILL.md").write_text("mine\n", encoding="utf-8")
        (home / ".claude" / "CLAUDE.md").write_text("my rules\n", encoding="utf-8")
        settings = home / ".claude" / "settings.json"
        settings.write_text(json.dumps({"model": "mine", "env": {"KEEP": "1"}, "hooks": {"PreToolUse": [own_hook]}}), encoding="utf-8")
        settings.chmod(0o640)

        # Stops before any change.
        without_bd = base / "without-bd"
        without_bd.mkdir()
        for tool in tools.iterdir():
            if tool.name != "bd":
                (without_bd / tool.name).symlink_to(tool.resolve())
        refuses("a missing bd", v1, "missing required tool: bd", without_bd)
        old_python = base / "old-python"
        old_python.mkdir()
        for tool in tools.iterdir():
            if tool.name != "python3":
                (old_python / tool.name).symlink_to(tool.resolve())
        fake_python = old_python / "python3"
        fake_python.write_text("#!/bin/sh\n[ \"$1\" = --version ] && echo 'Python 3.9.6'\nexit 1\n", encoding="utf-8")
        fake_python.chmod(0o755)
        refuses("an old python3", v1, "Python 3.9.6", old_python)
        (home / ".codex").mkdir()
        (home / ".codex" / "hooks.json").write_text("{broken", encoding="utf-8")
        refuses("broken settings", v1, ".codex/hooks.json is not a JSON object", tools)
        (home / ".codex" / "hooks.json").unlink()
        # A JSON object whose hooks the merge can't read stops before the payload is replaced (install review, 2026-11-05).
        kept_settings = settings.read_text(encoding="utf-8")
        settings.write_text(json.dumps({"hooks": {"PreToolUse": "invalid"}}), encoding="utf-8")
        refuses("unmergeable hooks", v1, ".claude/settings.json has hooks the installer cannot merge", tools)
        settings.write_text(kept_settings, encoding="utf-8")
        (home / ".agents").mkdir()
        (base / "elsewhere").mkdir()
        (home / ".agents" / "bin").symlink_to(base / "elsewhere")
        refuses("a symlinked folder", v1, "~/.agents/bin is a symlink", tools)
        (home / ".agents" / "bin").unlink()
        (home / ".agents").rmdir()

        before = tree(home)
        dry = ok(v1, "--dry-run")
        if tree(home) != before or "install .claude/CLAUDE.md" not in dry.stdout:
            raise ValueError(f"install.sh --dry-run changed files or said nothing: {dry.stdout}")

        # First install: instructions replaced with a backup, the user's files and settings kept.
        first = ok(v1)
        backups = sorted((home / ".agent-config-backup").iterdir())
        if len(backups) != 1 or (backups[0] / ".claude" / "CLAUDE.md").read_text(encoding="utf-8") != "my rules\n":
            raise ValueError(f"install.sh must back up replaced instructions: {first.stdout}")
        if (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8") != "setup rules\n":
            raise ValueError("install.sh must replace the global instructions")
        if not (home / ".claude" / "skills" / "mine" / "SKILL.md").is_file():
            raise ValueError("install.sh removed the user's own skill")
        if not os.access(home / ".agents" / "bin" / "tool", os.X_OK):
            raise ValueError("install.sh lost a tool's executable bit")
        merged = json.loads(settings.read_text(encoding="utf-8"))
        if merged["model"] != "mine" or merged["env"] != {"KEEP": "1", "CLAUDE_CODE_PLUGIN_DIRS": "~/.claude/mods/console"}:
            raise ValueError(f"install.sh mangled settings: {merged}")
        if commands(".claude/settings.json") != ["mine.sh", 'bash "$HOME/.claude/hooks/one.sh"']:
            raise ValueError(f"install.sh merged hooks wrongly: {commands('.claude/settings.json')}")
        if commands(".codex/hooks.json") != ['bash "$HOME/.codex/hooks/one.sh"']:
            raise ValueError("install.sh must create the Codex hooks file")
        if settings.stat().st_mode & 0o777 != 0o640:
            raise ValueError("install.sh changed the settings file's mode")

        # A rerun of the same bundle changes nothing, not even a backup.
        again = ok(v1)
        if "already up to date (one)" not in again.stdout or len(list((home / ".agent-config-backup").iterdir())) != 1:
            raise ValueError(f"a rerun of the same bundle must change nothing: {again.stdout}")
        if commands(".claude/settings.json").count('bash "$HOME/.claude/hooks/one.sh"') != 1:
            raise ValueError("a rerun duplicated a hook registration")

        # Upgrade: what the last install shipped and this one doesn't goes; the user's additions stay.
        (home / ".claude" / "skills" / "kept" / "note.md").write_text("my note\n", encoding="utf-8")
        v2 = bundle(base, "v2", "two", {
            ".claude/CLAUDE.md": "new rules\n",
            ".codex/AGENTS.md": "new rules\n",
            ".claude/skills/kept/SKILL.md": "kept\n",
            ".agents/bin/tool": "#!/bin/sh\n",
            ".claude/mods/console/.claude-plugin/plugin.json": "{}\n",
        }, 'bash "$HOME/.claude/hooks/two.sh"', 'bash "$HOME/.codex/hooks/two.sh"')
        # A leftover or planted `<file>.new` never redirects the settings or state write (install review, 2026-11-05).
        outside = base / "outside"
        outside.write_text("keep\n", encoding="utf-8")
        planted = [home / ".claude" / "settings.json.new", home / ".agents" / "setup-state.json.new"]
        for link in planted:
            link.symlink_to(outside)
        ok(v2)
        if outside.read_text(encoding="utf-8") != "keep\n" or settings.is_symlink() or (home / ".agents" / "setup-state.json").is_symlink():
            raise ValueError("install.sh must write settings and state through files of its own, not a planted .new")
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
            raise ValueError(f"install.sh must leave another plugin folder setting alone: {note.stderr}")
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

        # An unusable HOME stops at once.
        for value in ("", "/", "//", "/.", "relative", str(base / "no-such-home")):
            result = subprocess.run([str(tools / "bash"), str(v2 / "install.sh"), "--dry-run"], capture_output=True, text=True, check=False,
                                    stdin=subprocess.DEVNULL, env={"HOME": value, "PATH": str(tools)})
            if result.returncode == 0 or "HOME is" not in result.stderr:
                raise ValueError(f"install.sh must stop on HOME={value!r}: {result.returncode} {result.stderr}")

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


def validate_hooks(root: Path) -> None:
    hooks = root / "hooks"
    validate_hook_registrations(root)
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
    with patch.object(board, "registrations", lambda: entries):
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
    fixture = [json.loads(line) for line in
               (root / "bin" / "fixtures" / "board-export.jsonl").read_text(encoding="utf-8").splitlines()]
    goal = next(issue["id"] for issue in fixture if issue["title"] == "Goal")
    ids = {issue["title"]: issue["id"] for issue in fixture}
    real_run = subprocess.run

    class Fake:
        def __init__(self, issues, lint=None, refuse=(), history=None):
            self.issues, self.lint, self.refuse, self.calls = issues, lint or {"results": []}, set(refuse), []
            self.history, self.files = history or {}, {}

        project = None  # the folder `bd where` names (its .beads); None: not in a board

        def __call__(self, command, **kwargs):
            if command[0] != "bd":
                return real_run(command, **kwargs)
            if command[1] == "where":
                return subprocess.CompletedProcess(command, *((0, f"{self.project}/.beads\n  database: x\n", "") if self.project
                                                              else (1, "", "No active beads workspace found.")))
            self.calls.append((command[1:], kwargs.get("input")))
            # board hands long text over in temporary files: keep their content for the assertions.
            for flag, path in zip(command, command[1:]):
                if flag in ("--design-file", "--body-file", "-f") and Path(path).is_file():
                    self.files[(command[1], command[2] if command[1] != "comments" else command[3], flag)] = \
                        Path(path).read_text(encoding="utf-8")
            if command[1] == "create":
                return subprocess.CompletedProcess(command, 0, json.dumps({"id": "fx-new"}), "")
            if command[1] == "export":
                return subprocess.CompletedProcess(command, 0, "\n".join(map(json.dumps, self.issues)) + "\n", "")
            if command[1] == "list":
                # bd list: non-closed items with dependencies, without comments, edges ordered unlike the export's.
                rows = [{**{k: v for k, v in issue.items() if k not in ("comments", "_type")},
                         "dependencies": list(reversed(issue.get("dependencies") or []))}
                        for issue in self.issues if issue["status"] != "closed"]
                return subprocess.CompletedProcess(command, 0, json.dumps(rows), "")
            if command[1] == "show":
                wanted = command[command.index("--") + 1:]
                return subprocess.CompletedProcess(command, 0, json.dumps(self.show_records(wanted, "--include-dependents" in command)), "")
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
            return [args[0] for args, _ in self.calls if args[0] in ("export", "list", "show")]

        def writes(self):
            return [args for args, _ in self.calls if args[0] not in ("export", "list", "show", "lint", "history")]

    def invoke(argv, fake, actor="", now="2026-10-22T15:30:00+00:00"):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(board.subprocess, "run", fake), \
                patch.object(board, "utcnow", lambda: datetime.fromisoformat(now)), \
                patch.dict(os.environ, {"BEADS_ACTOR": actor, "CODEX_SESSION_ID": "", "CLAUDE_CODE_SESSION_ID": ""}), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = board.main(argv)
        # Each view makes the read it needs: status views one list (plus one show of the held items and the epics
        # without an open child, when there are any), the full-read views one export, show one show.
        live = [issue for issue in fake.issues if issue["status"] != "closed"]
        held = any(issue.get("assignee") for issue in live)
        parents = {d["depends_on_id"] for issue in live for d in issue.get("dependencies") or [] if d["type"] == "parent-child"}
        childless = any(issue.get("issue_type") == "epic" and issue["id"] not in parents for issue in live)
        if argv[0] == "show":
            # a second show only fetches the metadata of a pending revision's new record
            expected = fake.reads() if fake.reads() in (["show"], ["show", "show"]) else ["show"]
        elif argv[0] in ("related", "check", "block", "revise", "release", "supersede"):
            expected = ["export"]
        elif argv[0] == "record" or argv[0] == "claim" and any(issue["status"] == "in_review" for issue in live) \
                and fake.reads() == ["list", "show"]:  # claim reads hand-over comments of in_review items
            expected = ["list", "show"]
        elif argv[0] in ("position", "console") and (held or childless) or argv[0] == "mine" and held:
            expected = ["list", "show"]
        else:
            expected = ["list"]
        # A command refused before its last read (unknown id, wrong holder) stops early.
        if fake.reads() != expected and not (code != 0 and fake.reads() == expected[:len(fake.reads())]):
            raise ValueError(f"board {argv[0]} must read {expected}, read {fake.reads()}: {fake.calls}")
        return code, output.getvalue(), errors.getvalue()

    def variant(**changes):
        return [{**issue, **changes.get(issue["title"], {})} for issue in fixture]

    with tempfile.TemporaryDirectory() as state_dir, tempfile.TemporaryDirectory() as raw_base:
        registry = root / "bin" / "session-lead-mode"
        project, project_env = fake_board(Path(raw_base).resolve())
        Fake.project = str(project)
        for args, identity in ((("agent", "--pulls", "implement,review"), as_session("0000-aaaa1111", "codex")),
                               (("lead",), as_session("0000-lead0001")), (("solo",), as_session("0000-solo0001")),
                               (("autopilot",), as_session("0000-auto0001"))):
            subprocess.run(["bash", str(registry), "activate", *args], check=True,
                           env={**os.environ, **session_env(state_dir), **identity, **project_env})
        with patch.dict(os.environ, session_env(state_dir)):
            _, health, _ = invoke(["health", "--items", "ready"], Fake(fixture))
            for expected in ("claimable now (unassigned, unblocked): 7\n",
                             "by kind: plan 2, design 1, implement 3, review 1, question 0, accept 0, ratify 0",
                             "released rulings to plan: 2\n", "outside any epic: 1\n"):
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
                if ("Ready task" in gated) != claimable:
                    raise ValueError(f"board queue misjudged a blocker outside the snapshot: {blocker}")
                gated_issues = [{**i, "dependencies": [*i["dependencies"], {"issue_id": i["id"], "depends_on_id": blocker,
                                                                           "type": "blocks"}]} if i["id"] == ready_task["id"] else i
                                for i in fixture]
                if bool(board.Board(gated_issues).open_blockers(ready_task["id"])) != (blocker == "fx-missing"):
                    raise ValueError(f"a complete snapshot must fail closed on a blocker outside it: {blocker}")
                if board.Board(gated_issues, complete=False).open_blockers(ready_task["id"]):
                    raise ValueError(f"a status snapshot must count a blocker outside it as closed: {blocker}")
            _, queue, _ = invoke(["queue", "--root", goal], Fake(fixture))
            if "implement: 2\n" not in queue or "Loose item" in queue or "review: 1\n" not in queue:
                raise ValueError(f"board queue ignored --root or routing:\n{queue}")

            _, recent, _ = invoke(["position"], Fake(fixture))
            _, later, _ = invoke(["position"], Fake(fixture), now="2026-10-22T17:30:00+00:00")
            # Sessions count by the kinds a role handles, not only its bare-claim kinds.
            for expected in ("implement: 3 ready, 1 sessions", "question: 0 ready, 3 sessions",
                             "accept: 0 ready, 3 sessions", "ratify: 0 ready, 2 sessions",
                             "aaaa1111/build-12345678 (agent implement+review, codex)", "lead0001 (lead, claude)",
                             "open questions holding work: 2", f"finished epics not closed: 1\n  {ids['Finished outcome']}"):
                if expected not in recent:
                    raise ValueError(f"board position lacks {expected!r}:\n{recent}")
            if "IDLE" in recent or "board take <id> | board unclaim <id>" in recent:
                raise ValueError("board position flagged fresh holds as idle")
            if later.count("IDLE") != 2 or "If that session is gone: board take <id> | board unclaim <id>" not in later:
                raise ValueError(f"board position missed idle holds:\n{later}")

            # Session scope (r26-q115/q116/q120): a session lists when it holds items here, or when its project is this
            # board's and the later of its registration and last activity is within 24 h.
            registered = {"othr0001": ("/another/project", "2026-10-22T15:00:00Z"), "same0001": (str(project), "2026-10-22T15:00:00Z"),
                          "samo0001": (str(project), "2026-10-01T00:00:00Z"), "oldx0001": (str(project), "2026-10-01T00:00:00Z"),
                          "nopr0001": (None, "2026-10-22T15:00:00Z"), "hold0001": ("/another/project", "2026-10-01T00:00:00Z"),
                          "nhld0001": (None, "2026-10-01T00:00:00Z")}
            for actor, (home, at) in registered.items():
                Path(state_dir, f"0000-{actor}.json").write_text(json.dumps(
                    {"session": f"0000-{actor}", "role": "lead", "pulls": [], "actor": actor, "tool": "claude", "registered_at": at,
                     **({"project": home} if home else {})}), encoding="utf-8")
            for actor in ("samo0001", "oldx0001"):  # registered long ago; samo0001 works now (activity hooks live)
                stamp = datetime.fromisoformat("2026-10-22T15:25:00+00:00").timestamp() if actor == "samo0001" \
                    else datetime.fromisoformat("2026-10-02T00:00:00+00:00").timestamp()
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

            # feature and chore are retired: live ones are flagged and never routed.
            retired = [{**issue, "issue_type": "feature"} if issue["title"] == "Clean task"
                       else {**issue, "issue_type": "chore"} if issue["title"] == "Waits on ruling" else issue
                       for issue in checked]
            report = invoke(["check"], Fake(retired))[1]
            if f"  {cid['Clean task']}  retired-type" not in report or f"  {cid['Waits on ruling']}  retired-type" not in report:
                raise ValueError(f"board check did not flag live feature and chore items:\n{report}")
            checks = [{**issue, "issue_type": "check"} if issue["title"] in ("Clean task", "Closed waiter") else issue
                      for issue in checked]
            report = invoke(["check"], Fake(checks))[1]
            if f"  {cid['Clean task']}  retired-type" not in report or f"  {cid['Closed waiter']}  retired-type" in report:
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

            conforming = [issue for issue in checked if issue["title"] in ("Goal", "Clean task", "User action")]
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
            if f"this session still holds: 1\n  {ids['Held task']}" not in claimed:
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
            if fake.writes()[-1] != ["update", ids["Spike perf"], "--claim", "--json"]:
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
            # A lead claims acceptance and ratification items by id only.
            accept = variant(**{"Ready task": {"issue_type": "design", "status": "in_review"}})
            fake = Fake(accept)
            invoke(["claim"], fake, "lead0001")
            if fake.writes():
                raise ValueError(f"a lead's bare claim took an in_review design: {fake.writes()}")
            for session in ("solo0001", "auto0001"):
                fake = Fake(variant(**{"Ready task": {"issue_type": "design", "status": "in_review"},
                                       "Released ruling": {"status": "closed"}, "Old store ruling": {"status": "closed"}}))
                invoke(["claim"], fake, session)
                if fake.writes()[:1] != [["update", ids["Ready task"], "--assignee", session, "--if-assignee", "", "--json"]]:
                    raise ValueError(f"{session}'s bare claim did not take the in_review design: {fake.writes()}")
            fake = Fake(accept)
            invoke(["claim", ids["Ready task"]], fake, "lead0001")
            if fake.writes() != [["update", ids["Ready task"], "--assignee", "lead0001", "--if-assignee", "", "--json"]]:
                raise ValueError(f"a lead did not claim the named in_review design: {fake.writes()}")

            fake = Fake(fixture)
            invoke(["claim", ids["Ready task"], ids["Released ruling"]], fake, "lead0001")
            if fake.writes() != [["update", ids["Ready task"], "--claim", "--json"],
                                 ["update", ids["Released ruling"], "--assignee", "lead0001", "--if-assignee", "", "--json"]]:
                raise ValueError(f"board claim <ids> chose the wrong claim forms: {fake.writes()}")

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
                synthetic("ms-ready", "Ready member", parent=goal),
                synthetic("ms-member", "Blocked member", blocks=("ms-blocker", "ms-closed"), parent=goal),
                synthetic("ms-blocker", "Member's blocker", priority=3, parent=goal),
                synthetic("ms-closed", "Closed blocker", priority=3, status="closed", blocks=("ms-closed-blocker",)),
                synthetic("ms-closed-blocker", "Behind a closed blocker", priority=3),
                synthetic("ms-epic", "Member outcome", "epic", parent=goal),
                synthetic("ms-sub", "Task with a subtask", parent="ms-epic"),
                synthetic("ms-child", "Epic child", priority=3, blocks=("ms-child-blocker",), parent="ms-sub"),
                synthetic("ms-done-child", "Closed epic child", priority=3, status="closed", parent="ms-epic"),
                synthetic("ms-child-blocker", "Child's blocker", priority=3),
                synthetic("ms-p1", "P1 outsider", priority=1, parent=goal),
            ]
            milestone_board = fixture + [beta, *members]
            work = board.Board(milestone_board).milestone_work("ms-1")
            if work != {"ms-ready", "ms-member", "ms-blocker", "ms-epic", "ms-sub", "ms-child", "ms-child-blocker"}:
                raise ValueError(f"milestone work misses the closure or takes closed items and what they wait on: {sorted(work)}")
            # A descendant reached first as a blocker still brings its own descendants, whatever the edge order.
            for order in (("ord-e", "ord-m"), ("ord-m", "ord-e")):
                shape = [synthetic("ord-w", "W", "milestone", blocks=order), synthetic("ord-e", "E", "epic"),
                         synthetic("ord-m", "M", blocks=("ord-t",)), synthetic("ord-t", "T", parent="ord-e"),
                         synthetic("ord-s", "S", parent="ord-t")]
                if board.Board(shape).milestone_work("ord-w") != {"ord-e", "ord-m", "ord-t", "ord-s"}:
                    raise ValueError(f"milestone work depends on edge order {order}: {sorted(board.Board(shape).milestone_work(shape[0]['id']))}")
            # r24-q109: holds stops at a milestone (which counts as one), and also gives everything downstream.
            shape = [synthetic("h-q", "Q", "decision"), synthetic("h-w", "W", blocks=("h-q",)), synthetic("h-x", "X", blocks=("h-w",)),
                     synthetic("h-m", "M", "milestone", blocks=("h-q",)), synthetic("h-r", "R", blocks=("h-m",)), synthetic("h-s", "S", blocks=("h-m",))]
            if board.Board(shape).holds("h-q") != (3, 5):
                raise ValueError(f"holds must stop at the milestone, then count everything: {board.Board(shape).holds('h-q')}")
            built = board.Board(milestone_board)
            if built.kind(beta) != "milestone" or built.claimable(beta) is not None:
                raise ValueError("a milestone with open work must not be claimable")

            fake = Fake(milestone_board)
            invoke(["claim"], fake, worker)
            if fake.writes() != [["update", "ms-ready", "--claim", "--json"]]:
                raise ValueError(f"board claim did not take the P2 milestone member before P1 outsiders: {fake.writes()}")
            fake = Fake(milestone_board + [synthetic("ms-p0", "P0 outsider", priority=0, parent=goal)])
            invoke(["claim"], fake, worker)
            if fake.writes() != [["update", "ms-p0", "--claim", "--json"]]:
                raise ValueError(f"board claim did not take the P0 outsider before milestone work: {fake.writes()}")

            _, queued, _ = invoke(["queue"], Fake(milestone_board))
            implement_rows = queued.split("implement:")[1].split("review:")[0].splitlines()[1:]
            if not implement_rows[0].startswith("  ms-ready ") or "m:ms-1" not in implement_rows[0] \
                    or any("m:" in row for row in implement_rows if "ms-p1" in row) or "milestone: 0\n" not in queued:
                raise ValueError(f"board queue must order and mark milestone work and hide the unready milestone:\n{queued}")
            _, scoped_queue, _ = invoke(["queue", "--root", "ms-1"], Fake(milestone_board))
            if "implement: 4\n" not in scoped_queue or "ms-p1" in scoped_queue or ids["Ready task"] in scoped_queue:
                raise ValueError(f"board queue --root <milestone> must scope to its work:\n{scoped_queue}")
            _, milestone_health, _ = invoke(["health"], Fake(milestone_board))
            if "milestone ms-1 (Beta): open work 6, ready 4, held 0, blocked 2; milestone not ready\n" not in milestone_health \
                    or "milestone ms-1 (Beta)" not in invoke(["health", "--root", "ms-1"], Fake(milestone_board))[1]:
                raise ValueError(f"board health lacks the milestone line:\n{milestone_health}")
            if json.loads(invoke(["health", "--json"], Fake(milestone_board))[1])["milestones"] != [
                    {"id": "ms-1", "title": "Beta", "openWork": 6, "ready": 4, "held": 0, "blocked": 2, "milestoneReady": False}]:
                raise ValueError("board health --json milestones")

            # A ready milestone is claimed by id only: no bare claim takes it.
            done = [beta, *({**m, "status": "closed"} if m["id"] in work else m for m in members)]
            ready_board = fixture + done
            if board.Board(ready_board).claimable(beta) != "milestone":
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

            crowded = fixture + [{**next(i for i in fixture if i["title"] == "Held task"), "id": f"fx-extra{n}"}
                                 for n in range(60)]
            _, capped, _ = invoke(["position"], Fake(crowded))
            _, full, _ = invoke(["position", "--all"], Fake(crowded))
            if "held items: 62\n" not in capped or "... 12 more" not in capped or "more" in full:
                raise ValueError("board position must cap sections at 50 rows unless --all")

            _, mine, _ = invoke(["mine"], Fake(fixture), "aaaa1111")
            _, lead_mine, _ = invoke(["mine"], Fake(fixture), "lead0001/review-00000000")
            if ids["Held task"] not in mine or ids["Open cache question"] in mine \
                    or ids["Open cache question"] not in lead_mine or ids["Held task"] in lead_mine:
                raise ValueError(f"board mine matched the wrong holders:\n{mine}\n{lead_mine}")

            # --json views (contract-rulings R-A1, R-B5): unbudgeted JSON, every row, no capacity line after it.
            code, text, _ = invoke(["health", "--json", "--items", "questions,ready", "--limit", "1"], Fake(fixture))
            health_json = json.loads(text)
            if code or health_json["counts"] != {"questions": 1, "decided": 1, "ratification": 0, "toPlan": 2, "inReview": 1,
                                                 "forUser": 0, "ready": 7, "held": 2, "blocked": 3, "outside": 1, "labels": 0} \
                    or health_json["claimable"] != {"plan": 2, "design": 1, "implement": 3, "review": 1, "question": 0,
                                                    "accept": 0, "ratify": 0, "milestone": 0} \
                    or len(health_json["items"]["ready"]) != 7 or set(health_json["items"]) != {"questions", "ready"} \
                    or set(health_json["items"]["questions"][0]) != {"id", "type", "status", "priority", "holder", "title", "labels", "blockedBy"} \
                    or health_json["deviations"] != {"count": 1, "reviewBlocked": 0}:
                raise ValueError(f"board health --json: {text[:1500]}")
            blocked = json.loads(invoke(["health", "--json", "--items", "blocked"], Fake(fixture))[1])["items"]["blocked"]
            if not all(row["blockedBy"] for row in blocked) or len(blocked) != 3:
                raise ValueError(f"board health --json rows must name their open blockers: {blocked}")
            _, text, _ = invoke(["mine", "--json"], Fake(fixture), "aaaa1111")
            mine_json = json.loads(text)
            if mine_json["session"] != "aaaa1111" or [(i["id"], i["type"], i["holder"], i["workerStopped"]) for i in mine_json["items"]] \
                    != [(ids["Held task"], "task", "aaaa1111/build-12345678", False)]:
                raise ValueError(f"board mine --json: {text}")
            _, text, _ = invoke(["position", "--json"], Fake(fixture))
            position_json = json.loads(text)
            sessions = {s["actor"]: s for s in position_json["sessions"]}
            lead = sessions.get("lead0001") or {}
            if set(lead) != {"session", "role", "actor", "pulls", "tool", "handles", "registeredAt", "holds", "workers",
                             "process", "state", "idleSince", "claimable"} \
                    or lead["role"] != "lead" or lead["holds"] != 1 or lead["workers"] is not None or lead["state"] is not None \
                    or sessions["aaaa1111"]["claimable"] != 4 or sessions["aaaa1111"]["pulls"] != ["implement", "review"] \
                    or position_json["ready"]["implement"] != {"ready": 3, "sessions": 2} \
                    or {h["id"] for h in position_json["held"]} != {ids["Held task"], ids["Open cache question"]} \
                    or len(position_json["questionsHoldingWork"]) != 2 or len(position_json["finishedEpics"]) != 1:
                raise ValueError(f"board position --json: {text[:2000]}")
            # board console: the three views the pane draws, from one snapshot.
            _, text, _ = invoke(["console"], Fake(fixture), "aaaa1111")
            console_json = json.loads(text)
            _, health_text, _ = invoke(["health", "--json"], Fake(fixture))
            _, position_text, _ = invoke(["position", "--json"], Fake(fixture), "aaaa1111")
            position_view = json.loads(position_text)
            if console_json != {"counts": json.loads(health_text)["counts"], "items": mine_json["items"],
                                "sessions": position_view["sessions"],
                                "held": [{"id": h["id"], "holder": h["holder"], "mark": h["mark"]} for h in position_view["held"]]}:
                raise ValueError(f"board console must equal the health counts, mine items and position sessions: {text[:1500]}")
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
            code, _, errors = invoke(["release", store], fake, "lead0001")
            if code == 0 or "## Rule owner" not in errors or fake.writes():
                raise ValueError("board release accepted a record failing bd lint")
            fake = Fake(fixture)
            if invoke(["release", ids["Ready task"]], fake, "lead0001")[0] == 0 or fake.writes():
                raise ValueError("board release accepted a task")
            # Resumable: an already released ruling is done, nothing is written again.
            fake = Fake(fixture)
            code, output, _ = invoke(["release", ids["Released ruling"]], fake, "lead0001")
            if code or fake.writes() or f"already released {ids['Released ruling']}" not in output:
                raise ValueError(f"board release must take an already released ruling as done: {fake.calls}\n{output}")
            fake = Fake(variant(**{"Store choice": {"dependencies": [
                *next(i for i in fixture if i["id"] == store)["dependencies"],
                {"issue_id": store, "depends_on_id": ids["Ready task"], "type": "blocks"}]}}))
            if invoke(["release", store], fake, "lead0001")[0] == 0 or fake.writes():
                raise ValueError("board release accepted a ruling with an open blocker")
            # A released ruling is a settled premise: it holds no decided record resting on it (health's blockedBy, which the
            # release's drop step reads, and board release agree), an unsettled blocker is refused with its real status, and an
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
            code, _, errors = invoke(["release", store], fake, "lead0001")
            if code or not fake.writes() or decided_blocked(with_blockers(released_ruling)):
                raise ValueError(f"a released blocker must not hold a decided record: {errors}")
            fake = Fake(with_blockers(released_ruling, ready_task))
            code, _, errors = invoke(["release", store], fake, "lead0001")
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
                code, _, errors = invoke(["release", store], fake, "lead0001")
                if code == 0 or f"{status}, not decided" not in errors or fake.writes():
                    raise ValueError(f"board release accepted a {status} record")
            fake = Fake(variant(**{"Open cache question": {"status": "decided"}}))
            code, _, _ = invoke(["release", store, ids["Open cache question"]], fake, "lead0001")
            batch = [(args, stdin) for args, stdin in fake.calls if args[0] == "batch"]
            question = ids["Open cache question"]
            # A released ruling keeps blocking the items it changes: release only sets the status.
            expected_ops = [f'update {store} status=released assignee=""',
                            f'update {question} status=released assignee=""']
            if code or len(batch) != 1 or len(fake.writes()) != 1 or batch[0][1].splitlines() != expected_ops:
                raise ValueError(f"board release must write one batch of status updates: {fake.calls}")

            # --closes: answered questions close after the release in dependency order, forced only past rulings of
            # this release and questions closed before them here (the gjfh4 case); another open blocker leaves one open.
            cache, spike, loose, ready = ids["Open cache question"], ids["Spike perf"], ids["Loose item"], ids["Ready task"]

            def blocks(item, *blockers):
                return [{"issue_id": item, "depends_on_id": b, "type": "blocks"} for b in blockers]

            answering = variant(**{"Open cache question": {"dependencies": blocks(cache, store)},
                                   "Spike perf": {"issue_type": "decision", "dependencies": blocks(spike, cache, store)},
                                   "Loose item": {"issue_type": "decision", "dependencies": blocks(loose, ready)}})
            fake = Fake(answering)
            code, output, errors = invoke(["release", store, "--closes", f"{spike}={store}", f"{cache}={store}", f"{loose}={store}"],
                                          fake, "lead0001")
            closes = [args for args in fake.writes() if args[0] == "close"]
            if code != 1 or closes != [["close", cache, "--reason", f"Answered by released {store}", "--force"],
                                       ["close", spike, "--reason", f"Answered by released {store}", "--force"]] \
                    or fake.writes()[0][0] != "batch" or f"{loose}: left open, blocked by {ready}" not in errors \
                    or f"closed {cache}: answered by released {store}" not in output:
                raise ValueError(f"board release --closes: {fake.writes()}\n{output}\n{errors}")
            # A released ruling outside the release does not leave the answered question open; bd still needs the force.
            fake = Fake(variant(**{"Open cache question": {"dependencies": blocks(cache, store, ids["Released ruling"])}}))
            code, _, errors = invoke(["release", store, "--closes", f"{cache}={store}"], fake, "lead0001")
            if code or [args for args in fake.writes() if args[0] == "close"] != [["close", cache, "--reason", f"Answered by released {store}", "--force"]]:
                raise ValueError(f"a released blocker must not leave an answered question open: {fake.writes()}\n{errors}")
            # Refused before any write: a question another session holds, a record the call does not release.
            for closes_arg, needle in ((f"{ids['Held task']}={store}", "not an open question"),
                                       (f"{cache}={ids['Old store ruling']}", "which this call does not release")):
                fake = Fake(answering)
                code, _, errors = invoke(["release", store, "--closes", closes_arg], fake, "lead0001")
                if code != 1 or needle not in errors or fake.writes():
                    raise ValueError(f"board release --closes {closes_arg}: {errors}")
            held_question = variant(**{"Open cache question": {"assignee": "solo0001"}})
            fake = Fake(held_question)
            code, _, errors = invoke(["release", store, "--closes", f"{cache}={store}"], fake, "lead0001")
            if code != 1 or "hand it off" not in errors or fake.writes():
                raise ValueError(f"board release must not close a question another session holds: {errors}")

            # A full supersede blocks the old record's open items on the new one until it is planned,
            # skipping closed and already linked items; --partial only adds the edge. Both drop the pair's existing link first.
            old, new = ids["Old store ruling"], ids["Store choice"]
            old_issue = next(i for i in fixture if i["id"] == old)
            linked = variant(**{"Old store ruling": {"dependencies": [*(old_issue.get("dependencies") or []), *(
                {"issue_id": old, "depends_on_id": ids[title], "type": "relates-to"}
                for title in ("Ready task", "Closed waiter", "Implement store A"))]}})
            fake = Fake(linked)
            code, output, _ = invoke(["supersede", old, "--with", new], fake, "lead0001")
            ready = ids["Ready task"]
            reason = f"Blocked by {new}: supersedes {old}; replan against it"
            batches = [stdin for args, stdin in fake.calls if args[0] == "batch"]
            if code or [w[:2] for w in fake.writes()] != [["batch", "-m"], ["batch", "-m"], ["comments", "add"],
                                                          ["supersede", old]] \
                    or batches != [f"dep remove {new} {old}\n", f"dep add {ready} {new} blocks\n"] \
                    or fake.writes()[2] != ["comments", "add", ready, reason] \
                    or f"blocked {ready} on {new}" not in output:
                raise ValueError(f"board supersede must block the old record's open items through board block: "
                                 f"{fake.calls}\n{output}")
            fake = Fake(fixture)
            code, _, _ = invoke(["supersede", old, "--with", new, "--partial"], fake, "lead0001")
            if code or fake.writes() != [["batch", "-m", f"board supersede {old} --with {new}", "--json"]] \
                    or fake.calls[-1][1] != f"dep remove {new} {old}\ndep add {old} {new} supersedes\n":
                raise ValueError(f"board supersede --partial: {fake.writes()}")

            # supersede --partial "<rule>" names the rule on the old record.
            fake = Fake(fixture)
            code, output, _ = invoke(["supersede", old, "--with", new, "--partial", "Rule 2"], fake, "lead0001")
            if code or fake.writes()[-1] != ["comments", "add", old, f'board supersede: rule "Rule 2" superseded by {new}.'] \
                    or "one rule (Rule 2) superseded" not in output:
                raise ValueError(f"board supersede --partial <rule>: {fake.writes()}\n{output}")

            # board show: rendered from the snapshot within READ_BUDGET; cut sections name the command for the rest.
            big = "## Question\nWhich cache?\n\n## Alternatives Considered\n" + "word " * 9000 + "\n### Detail\nfine print\n" \
                  "## Decision\nUse A.\n## Decision log\nlog\n"
            notes = [{"author": f"a{n}", "created_at": f"2026-10-2{n}T00:00:00Z", "text": f"note {n}"} for n in range(5)]
            shown = variant(**{"Store choice": {"description": big, "comments": notes},
                               "Ready task": {"dependencies": [{"issue_id": ready, "depends_on_id": new, "type": "blocks"}]}},
                            **{"Old store ruling": {"description": "x" * 34000}})
            shown.append({"id": "fx-rev", "title": "Revise the store", "status": "open", "issue_type": "decision",
                          "priority": 2, "metadata": {"board.revises_rule": "Rule 2"},
                          "dependencies": [{"issue_id": "fx-rev", "depends_on_id": new, "type": "tracks"}]})
            code, text, _ = invoke(["show", new], Fake(shown))
            for expected in (f"{new}  decided  decision  p", "\nStore choice\nlinks:\n", f"  blocks: {ready}  open  Ready task",
                             f"  relates to: {old}  released  Old store ruling",
                             "  revision pending: fx-rev  open  Revise the store  (partial: Rule 2)",
                             "description:\n## Question\nWhich cache?", f'more chars: board show {new} --section \'Alternatives Considered\'',
                             "### Detail\nfine print", "## Decision\nUse A.", "comments: 5, newest 3\n--- a4 ",
                             f"… 2 older: board show {new} --comments"):
                if expected not in text:
                    raise ValueError(f"board show lacks {expected!r}:\n{text[:3000]}")
            if code or len(text) > board.READ_BUDGET or "--- a1 " in text or text.index("--- a4") > text.index("--- a2"):
                raise ValueError(f"board show broke the budget or the comment order ({len(text)} chars)")
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
            if text.count("--- a") != 5 or "older" in text or f"comments only: board show {new} --full prints the whole item" not in text:
                raise ValueError(f"board show --comments must print every comment and say the rest is left out:\n{text}")
            _, text, _ = invoke(["show", new], Fake(shown))
            if "comments only" in text:
                raise ValueError(f"board show without --comments prints the whole item, so no note:\n{text}")
            _, text, _ = invoke(["show", new, "--json", "--field", "comments", "--field", "status"], Fake(shown))
            if json.loads(text) != {new: {"comments": notes, "status": "decided"}}:
                raise ValueError(f"board show --json --field: {text[:500]}")
            code, text, errors = invoke(["show", old, "--json", "--field", "metadata"], Fake(shown))  # a field no shown item sets
            if code or json.loads(text) != {old: {"metadata": None}}:
                raise ValueError(f"board show --json --field metadata must answer null for an item without metadata: {text} {errors}")
            if invoke(["show", new, "--json"], Fake(shown))[0] != 1 or invoke(["show", "fx-nope"], Fake(shown))[0] != 1 \
                    or invoke(["show", new, "--field", "desc"], Fake(shown))[0] != 1:
                raise ValueError("board show must refuse --json without --field, unknown ids and unknown fields")
            _, text, _ = invoke(["show", new, old], Fake(shown))
            if len(text) > board.READ_BUDGET or f"\n{old}  released" not in text or f"board show {old} --section description" not in text:
                raise ValueError(f"several ids must share one budget:\n{text[-1500:]}")
            if "more chars" in invoke(["show", new, old, "--full"], Fake(shown))[1]:
                raise ValueError("board show --full must not cut")

            # board record: refuses a file missing a record section; moves a packet description into a comment.
            question = ids["Open cache question"]
            with tempfile.TemporaryDirectory() as directory:
                draft = Path(directory, "record.md")
                draft.write_text("## Question\nq\n## Decision\nd\n## Rationale\nr (user, 2026-10-31)\n", encoding="utf-8")
                fake = Fake(fixture)
                code, _, errors = invoke(["record", question, str(draft)], fake, "lead0001")
                if code != 1 or "## Alternatives Considered" not in errors or "## Rule owner" not in errors or fake.writes():
                    raise ValueError(f"board record accepted a file missing sections: {errors}")
                draft.write_text("## Question\nq\n## Alternatives Considered\n- b: rejected\n## Decision\nd\n"
                                 "## Rationale\nr (user, 2026-10-31)\n## Rule owner\ndocs/x.md\n", encoding="utf-8")
                fake = Fake(fixture)
                code, output, _ = invoke(["record", question, str(draft)], fake, "lead0001", now="2026-10-31T10:00:00+00:00")
                if code or [w[:2] for w in fake.writes()] != [["comments", "add"], ["update", question]] \
                        or fake.files[("comments", question, "-f")] != \
                        "Decision packet (moved from the description at decision time, 2026-10-31):\n\nPacket only." \
                        or fake.writes()[1][4:] != ["--status", "decided", "--json"] \
                        or not any(args[:2] == ["lint", question] for args, _ in fake.calls) \
                        or output != f"recorded {question} (decided; packet moved to a comment): Open cache question\n":
                    raise ValueError(f"board record: {fake.calls}\n{output}")
                # A record already in place is replaced without another packet comment; lint failures are loud.
                recorded = variant(**{"Open cache question": {"status": "decided", "description": draft.read_text(encoding="utf-8")}})
                fake = Fake(recorded, lint={"results": [{"id": question, "missing": ["## Extra"]}]})
                code, _, errors = invoke(["record", question, str(draft)], fake, "lead0001")
                if code != 1 or "## Extra" not in errors or [w[0] for w in fake.writes()] != ["update"]:
                    raise ValueError(f"board record revised in place wrongly: {fake.writes()} {errors}")
                # A rewrite keeps the Decision it replaces in a comment when the Decision section changes, not when only other
                # sections do (r13 q51); a rerun after a failed update finds the comment already there.
                text = draft.read_text(encoding="utf-8")
                rewrite = Path(directory, "rewrite.md")
                for changed, comments in ((text.replace("## Decision\nd\n", "## Decision\nnew decision\n"), 1),
                                          (text.replace("## Rationale\nr (user", "## Rationale\nrevised (user"), 0)):
                    rewrite.write_text(changed, encoding="utf-8")
                    fake = Fake(recorded)
                    code, output, _ = invoke(["record", question, str(rewrite)], fake, "lead0001", now="2026-10-31T10:00:00+00:00")
                    kept = fake.files.get(("comments", question, "-f"))
                    if code or [w[0] for w in fake.writes()] != ["comments", "update"][1 - comments:] \
                            or (kept or "") != ("Previous Decision (replaced 2026-10-31):\n\nd" if comments else "") \
                            or ("previous Decision kept in a comment" in output) != bool(comments):
                        raise ValueError(f"board record must comment the old Decision exactly when the section changes ({comments}): "
                                         f"{fake.writes()} {kept!r} {output}")
                for refused, actor in ((ids["Ready task"], "lead0001"), (question, "aaaa1111")):
                    fake = Fake(fixture)
                    if invoke(["record", refused, str(draft)], fake, actor)[0] != 1 or fake.writes():
                        raise ValueError(f"board record wrote {refused} for {actor}")
                # Autopilot: needs_ratification requires ## Reversal and frees the hold.
                fake = Fake(fixture)
                if invoke(["record", question, str(draft), "--status", "needs_ratification"], fake, "lead0001")[0] != 1 \
                        or fake.writes():
                    raise ValueError("board record --status needs_ratification accepted a record without ## Reversal")
                draft.write_text(draft.read_text(encoding="utf-8") + "## Reversal\nrevert x\n", encoding="utf-8")
                fake = Fake(fixture)
                code, _, _ = invoke(["record", question, str(draft), "--status", "needs_ratification"], fake, "lead0001")
                if code or fake.writes()[-1][4:] != ["--status", "needs_ratification", "--assignee", "", "--json"]:
                    raise ValueError(f"board record --status needs_ratification: {fake.writes()}")

            # board block: relates-to gives way, the reason is a comment (no field rewrite); an unheld review returns to open.
            handed = ids["Handed task"]
            blocking = variant(**{"Handed task": {"design": "Plan.", "dependencies": [
                {"issue_id": handed, "depends_on_id": "fx-ovo", "type": "parent-child"},
                {"issue_id": question, "depends_on_id": handed, "type": "relates-to"}]}})
            fake = Fake(blocking)
            code, output, _ = invoke(["block", handed, ready, "--on", question, "--reason", "waits for the cache"], fake, "lead0001")
            batches = [stdin for args, stdin in fake.calls if args[0] == "batch"]
            line_text = f"Blocked by {question}: waits for the cache"
            if code or batches != [f'dep remove {question} {handed}\ndep add {handed} {question} blocks\nupdate {handed} status=open assignee=""\n',
                                   f"dep add {ready} {question} blocks\n"] \
                    or any(w[0] == "update" for w in fake.writes()) \
                    or ["comments", "add", handed, line_text] not in fake.writes() \
                    or ["comments", "add", handed, f"board block: returned from review; amend to {question}: waits for the cache"] \
                    not in fake.writes() or output != f"blocked {handed} on {question}; returned from review to open\n" \
                                                      f"blocked {ready} on {question}\n":
                raise ValueError(f"board block: {fake.calls}\n{output}")
            # Held reviews stay: the caller's silently, another doer's with a warning; failures are loud and per item.
            for holder, warned in (("lead0001", False), ("cccc3333", True)):
                fake = Fake(variant(**{"Handed task": {"assignee": holder}}))
                code, output, errors = invoke(["block", handed, "--on", question, "--reason", "r"], fake, "lead0001")
                if code or "status=open" in "".join(s or "" for _, s in fake.calls) or ("cccc3333" in errors) != warned:
                    raise ValueError(f"board block moved or misreported a held review ({holder}): {fake.calls} {errors}")
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

            # board revise: a linked open decision, parent and topic labels from the old record; prints the new id.
            topical = variant(**{"Released ruling": {"labels": ["topic:store", "area"]}})
            fake = Fake(topical)
            code, output, _ = invoke(["revise", ids["Released ruling"], "--title", "May B replace A?", "--body-file", "p.md",
                                      "--partial", "Rule 2"], fake, "lead0001")
            if code or output != "fx-new\n" or fake.writes() != [[
                    "create", "--type", "decision", "--title", "May B replace A?", "--body-file", "p.md", "--priority", "2",
                    "--deps", f"tracks:{ids['Released ruling']}", "--labels", "topic:store",
                    "--metadata", '{"board.revises_rule": "Rule 2"}', "--deps", "parent-child:fx-ovo", "--json"]]:
                raise ValueError(f"board revise: {fake.writes()}\n{output}")
            fake = Fake(topical)
            invoke(["revise", ids["Released ruling"], "--title", "t", "--body-file", "p.md", "-p", "1", "--parent", goal,
                    "-l", "topic:a,topic:b"], fake, "lead0001")
            if fake.writes()[0][8:] != ["1", "--deps", f"tracks:{ids['Released ruling']}", "--labels",
                                        "topic:a,topic:b", "--deps", f"parent-child:{goal}", "--json"]:
                raise ValueError(f"board revise ignored -p/--parent/-l or set metadata without --partial: {fake.writes()}")
            fake = Fake(topical)
            invoke(["revise", ids["Released ruling"], "--title", "t", "--body-file", "p.md", "--external-ref", "protocol:s1:r2:q3"], fake, "lead0001")
            written = fake.writes()[0] if fake.writes() else []
            if "--external-ref" not in written or written[written.index("--external-ref") + 1] != "protocol:s1:r2:q3":
                raise ValueError(f"board revise must pass --external-ref to bd create: {fake.writes()}")
            for refused in (question, ready):
                fake = Fake(fixture)
                if invoke(["revise", refused, "--title", "t", "--body-file", "p.md"], fake, "lead0001")[0] != 1 or fake.writes():
                    raise ValueError(f"board revise accepted {refused}")

            # board release supersedes the records its rulings revise and lists the reviews that went back.
            revising = variant(**{"Store choice": {"dependencies": [{"issue_id": new, "depends_on_id": old, "type": "tracks"}]},
                                  "Handed task": {"dependencies": [{"issue_id": handed, "depends_on_id": old, "type": "relates-to"}]}})
            fake = Fake(revising)
            code, output, _ = invoke(["release", new], fake, "lead0001")
            batches = [stdin for args, stdin in fake.calls if args[0] == "batch"]
            if code or batches[:2] != [f'update {new} status=released assignee=""\n', f"dep remove {new} {old}\n"] \
                    or ["supersede", old, "--with", new] not in fake.writes() \
                    or f"superseded {old} by {new}" not in output or f"returned from review: {handed}\n" not in output:
                raise ValueError(f"board release must supersede revised records: {fake.calls}\n{output}")
            partial = [{**issue, "metadata": {"board.revises_rule": "Rule 2"}} if issue["id"] == new else issue for issue in revising]
            fake = Fake(partial)
            code, output, _ = invoke(["release", new], fake, "lead0001")
            if code or [stdin for args, stdin in fake.calls if args[0] == "batch"][1] != f"dep remove {new} {old}\ndep add {old} {new} supersedes\n" \
                    or any(args[0] == "supersede" for args in fake.writes()) or "one rule (Rule 2)" not in output:
                raise ValueError(f"board release of a partial revision: {fake.calls}\n{output}")

            # Replaced records (r12-q44): a decided record a live question revises is not released alone; a chain of
            # revisions is followed to the first released record; supersede carries a pending revision to its replacement.
            def record(rid, status, *links, **extra):
                return {"id": rid, "title": rid, "status": status, "issue_type": "decision", "priority": 2,
                        "dependencies": [{"issue_id": rid, "depends_on_id": target, "type": kind} for target, kind in links], **extra}

            chain = [record("fx-a", "released"), record("fx-b", "decided", ("fx-a", "tracks")),
                     record("fx-c", "decided", ("fx-b", "tracks"))]
            fake = Fake(chain)
            code, output, errors = invoke(["release", "fx-c"], fake, "lead0001")
            if code or [args for args in fake.writes() if args[0] == "supersede"] != [["supersede", "fx-b", "--with", "fx-c"],
                                                                                   ["supersede", "fx-a", "--with", "fx-c"]] \
                    or "superseded fx-a by fx-c" not in output:
                raise ValueError(f"board release must follow a chain of revisions to the first released record: {fake.writes()}\n{output}{errors}")
            partly = [{**issue, "metadata": {"board.revises_rule": "Rule 2"}} if issue["id"] == "fx-b" else issue for issue in chain]
            fake = Fake(partly)
            code, output, _ = invoke(["release", "fx-c"], fake, "lead0001")
            if code or [args for args in fake.writes() if args[0] == "supersede"] != [["supersede", "fx-b", "--with", "fx-c"]] \
                    or "dep add fx-a fx-c supersedes\n" not in [stdin for args, stdin in fake.calls if args[0] == "batch"] or "fx-a: one rule (Rule 2)" not in output:
                raise ValueError(f"a chain carries the replaced record's own rule: {fake.writes()}\n{output}")
            fake = Fake(chain)
            code, _, errors = invoke(["release", "fx-b"], fake, "lead0001")
            if code != 1 or "fx-b: revised by fx-c" not in errors or fake.writes():
                raise ValueError(f"board release must refuse a decided record a live question revises: {errors}\n{fake.writes()}")
            for allowed, args in ((chain, ["fx-b", "fx-c"]), ([*chain[:2], {**chain[2], "status": "closed"}], ["fx-b"])):
                fake = Fake(allowed)
                if invoke(["release", *args], fake, "lead0001")[0] or not fake.writes():
                    raise ValueError(f"board release {args}: a revision released together or closed is no refusal")
            # supersede carries the revision the old record still has pending, with its rule, to the new one.
            carried = [record("fx-a", "released"), record("fx-b", "decided", ("fx-a", "tracks"), metadata={"board.revises_rule": "Rule 2"}),
                       record("fx-d", "decided", ("fx-b", "tracks"))]
            fake = Fake(carried)
            code, output, _ = invoke(["supersede", "fx-b", "--with", "fx-d"], fake, "lead0001")
            if code or fake.writes() != [["update", "fx-d", "--set-metadata", "board.revises_rule=Rule 2", "--json"],
                                         ["batch", "-m", "board supersede fx-b --with fx-d", "--json"], ["supersede", "fx-b", "--with", "fx-d"]] \
                    or [stdin for args, stdin in fake.calls if args[0] == "batch"] != ["dep remove fx-d fx-b\ndep remove fx-b fx-a\ndep add fx-d fx-a tracks\n"] \
                    or "revision of fx-a now pending on fx-d" not in output:
                raise ValueError(f"board supersede must move the pending revision and its rule: {fake.writes()}\n{output}")
            busy = [*carried[:2], record("fx-d", "decided", ("fx-b", "tracks"), ("fx-z", "tracks")), record("fx-z", "released")]
            fake = Fake(busy)
            code, _, errors = invoke(["supersede", "fx-b", "--with", "fx-d"], fake, "lead0001")
            if code != 1 or "keeps one revision rule" not in errors or fake.writes():
                raise ValueError(f"board supersede must refuse a carry onto a record that revises another: {errors}\n{fake.writes()}")
            # board check --json: the rows a Release Board check reads (no text parsing).
            unlinked = [record("fx-a", "released"), record("fx-b", "decided", notes="This revises fx-a for the cache.")]
            code, text, _ = invoke(["check", "--json"], Fake(unlinked))
            found = json.loads(text)
            if code or found["unlinkedRevisions"] != [{"id": "fx-b", "other": "fx-a", "word": "revises", "old": "fx-a", "new": "fx-b"}] \
                    or set(found) != {"deviations", "squashed", "unnamedBlockers", "unlinkedRevisions"}:
                raise ValueError(f"board check --json: {text}")

            # board check: an in_review item waiting on an open blocker deviates; an unlinked revision is a flag.
            stuck = variant(**{"Handed task": {"dependencies": [{"issue_id": handed, "depends_on_id": question, "type": "blocks"}]},
                               "Store choice": {"notes": f"This revises {old} for the cache."}})
            code, report, _ = invoke(["check"], Fake(stuck))
            if "convention deviations: 2 — run /board-migrate; 1 in review while blocked: board check\n" not in invoke(["health"], Fake(stuck))[1]:
                raise ValueError("board health must point review-blocked items to board check, not /board-migrate")
            if code != 1 or f"  {handed}  review-blocked  board-core.md#hand-over-and-acceptance  in review while waiting on {question}" \
                    not in report or f"  {new}  unlinked-revision  revises {old}" not in report:
                raise ValueError(f"board check missed review-blocked or an unlinked revision:\n{report}")
            # Rejected alternatives are no revision; a passive "revised by <id>" flags the reverse pair.
            for notes, expected in ((f"## Alternatives Considered\n- Rejected: this revises {old}.\n## Decision\nx", None),
                                    (f"(Revised by the superseding rulings: per {old} the cache stays.)",
                                     f"  {new}  unlinked-revision  revised by {old} without a supersedes or revise link: "
                                     f"board supersede {new} --with {old}")):
                report = invoke(["check"], Fake(variant(**{"Store choice": {"notes": notes}})))[1]
                if ("unlinked-revision" in report) if expected is None else (expected not in report):
                    raise ValueError(f"board check misread {notes!r}:\n{report}")
            # A partial supersede by a closed record still adds the edge; a full one needs an open record.
            closed_new = variant(**{"Store choice": {"status": "closed"}})
            if invoke(["supersede", old, "--with", new, "--partial", "Rule 2"], Fake(closed_new), "lead0001")[0] \
                    or invoke(["supersede", old, "--with", new], Fake(closed_new), "lead0001")[0] != 1:
                raise ValueError("board supersede must take a closed new record for --partial only")
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
            many = fixture + [{**next(i for i in fixture if i["title"] == "Ready task"), "id": f"fx-wide{n:03}",
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
                    or len(rest) != int(page.group(1)) or not follow.startswith("implement: ") or rest[0] in shown:
                raise ValueError(f"board queue --offset must print the next rows under their section heading:\n{follow[:400]}")
            if "... 197 more" not in invoke(["health", "--items", "ready", "--limit", "10"], Fake(many))[1]:
                raise ValueError("board health --items must respect --limit")
            for argv, hint in ((["queue", "review"], "board health --items review"), (["queue", "accept"], None)):
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
            for name in ("show", "record", "block", "revise", "related", "release", "supersede", "handover"):
                if f"usage: board {name}" not in help_output.getvalue() or board.EXAMPLES[name] not in help_output.getvalue():
                    raise ValueError(f"board help lacks {name} or its example")
            with contextlib.redirect_stdout(io.StringIO()) as sub_help:
                try:
                    board.main(["block", "--help"])
                except SystemExit:
                    pass
            if not sub_help.getvalue().rstrip().endswith(f"example: {board.EXAMPLES['block']}"):
                raise ValueError(f"board block --help must end with its example:\n{sub_help.getvalue()}")

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

            # handover: holder only, a compare-and-set to in_review, then the evidence comment.
            fake = Fake(variant(**{"Held task": {"assignee": "aaaa1111", "status": "in_progress"}}))
            invoke(["handover", ids["Held task"], "pnpm test: 0 failures"], fake, "aaaa1111")
            if fake.writes() != [["update", ids["Held task"], "--status", "in_review", "--assignee", "", "--if-assignee",
                                  "aaaa1111", "--json"],
                                 ["comments", "add", ids["Held task"], "board handover: pnpm test: 0 failures"]]:
                raise ValueError(f"board handover: {fake.writes()}")
            fake = Fake(variant(**{"Held task": {"assignee": "aaaa1111", "status": "in_progress"}}))
            if invoke(["handover", ids["Held task"], "done"], fake, "bbbb2222")[0] != 1 or fake.writes():
                raise ValueError("board handover accepted an item the caller does not hold")

            # return: back to the queue, open and unassigned, with the findings.
            fake = Fake(variant(**{"Handed task": {"assignee": "lead0001"}}))
            invoke(["return", ids["Handed task"], "test x fails"], fake, "lead0001")
            if fake.writes() != [["update", ids["Handed task"], "--status", "open", "--assignee", "", "--if-assignee",
                                  "lead0001", "--json"],
                                 ["comments", "add", ids["Handed task"], "board return: test x fails"]]:
                raise ValueError(f"board return: {fake.writes()}")
            fake = Fake(variant(**{"Handed task": {"assignee": "aaaa1111"}}))
            if invoke(["return", ids["Handed task"], "x"], fake, "lead0001")[0] != 1 or fake.writes():
                raise ValueError("board return accepted a review the caller does not hold")

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
            stamp = datetime.fromisoformat(moment).timestamp()
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
                 "registered_at": "2026-10-22T15:00:00Z", **fields}), encoding="utf-8")
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
                              ("2026-10-22T17:30:00+00:00", {"actv0001": ("idle", "2026-10-22T15:29:00Z"),
                                                             "work0001": ("idle", "2026-10-22T15:25:00Z")})):
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
        registry = root / "bin" / "session-lead-mode"
        capacity_project, capacity_env = fake_board(Path(codex_home).resolve())
        Fake.project = str(capacity_project)
        for args, session, tool in ((("solo",), "0000-solo0001", "claude"), (("lead",), "0000-lead0001", "claude"),
                                    (("autopilot",), "0000-auto0001", "claude"),
                                    (("agent", "--pulls", "implement,review"), "0000-cdx00001", "codex"),
                                    (("agent", "--pulls", "plan,design,review"), "0000-cdx00002", "codex")):
            subprocess.run(["bash", str(registry), "activate", *args, "--workers", "6"], check=True,
                           env={**os.environ, **as_session(session, tool), **capacity_env})
        snapshot = board.Board([issue for issue in fixture if issue.get("_type", "issue") == "issue"])

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
                raise ValueError(f"session-lead-mode accepted {bad}")
        registry_call("0000-none0001", "set-workers", "0000-dflt0001", "--workers", "5").check_returncode()
        for bad in (("activate", "solo", "--workers"), ("activate", "solo", "--workers", "many"),
                    ("activate", "solo", "--workers", "-1"), ("activate", "solo", "--workers", "03"),
                    ("activate", "solo", "--workers", "1.5"), ("alive", "--workers", "4")):
            if registry_call("0000-dflt0001", *bad).returncode == 0:
                raise ValueError(f"session-lead-mode accepted {bad}")
        if not (capacity_of(["queue"], "dflt0001") or "").startswith("capacity: 3 of 5 "):
            raise ValueError("a refused workers call changed the session's worker cap")
        # Writes: the line follows them, without the items the command named or claimed (the snapshot predates them).
        handed = ids["Held task"]
        held = [{**issue, "assignee": "cdx00001"} if issue["id"] == handed else issue for issue in fixture]
        if capacity_of(["handover", handed, "done"], "cdx00001", held) != \
                f"capacity: 0 of 4 workers active in the last 15 min; {agent}":
            raise ValueError("board handover capacity line")
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
        (fake_bin / "bd").write_text(f'#!/bin/sh\necho "$BEADS_ACTOR $*" >> {calls}\nexit 7\n', encoding="utf-8")
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


FAKE_BOARD = r'''#!/usr/bin/env python3
import json, os, sys
config = json.load(open(os.environ["FAKE_BOARD_CONFIG"]))
args = sys.argv[1:]
stdin = "" if sys.stdin.isatty() else sys.stdin.read()
with open(config["log"], "a") as log:
    log.write(json.dumps({"args": args, "stdin": stdin, "actor": os.environ.get("BEADS_ACTOR"), "cwd": os.getcwd()}) + "\n")
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
    """The real engine's `show --json` in eleven states (no round, check, batch out, answered, a closed round with a release next, a release, a stopped release, a release with a revised record, a stored proposal, a compact-only proposal, an away round with a parked question), timestamps normalized:
    the console's tests parse exactly these, so a shape change on either side fails a test."""
    states = {}
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "AGENT_SESSION_STATE_DIR": tmp, "CODEX_THREAD_ID": "", "CODEX_SESSION_ID": "", "HOME": tmp}

        def run(*args, stdin=None, cwd=tmp):
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
            return result.stdout

        def show(cwd=tmp):
            text = re.sub(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", "2026-01-01T00:00:00Z", run("show", "--json", cwd=cwd))
            return json.loads(re.sub(r'"at": "\d\d:\d\d"', '"at": "00:00"', text))

        states["none"] = show()
        run("start", "round", "--no-board", str(Path(tmp) / "records"), stdin={"points": ["Which cache?"]})
        run("step", stdin={"classes": {"pt1": "user"}})
        run("step", stdin={"select": ["pt1"]})
        run("step", stdin={**ROUND_INFO, "questions": [{"text": "Which cache?", "title": "Cache", "header": "Cache", "for": "pt1", "problem": "Which cache.", "cases": "Reads; writes.", "premises": "Both read the cache.", "rulings": [], "options": [
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
        run("step", stdin={**ROUND_INFO, "questions": [{"text": "Which store?", "title": "Store", "header": "Store", "board": "fx-q", "problem": "Which store.", "cases": "Reads; writes.", "premises": "Both read the store.", "rulings": [], "options": [
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
        subprocess.run(["bash", str(root / "bin" / "session-lead-mode"), "activate", "autopilot"], check=True,
                       env={**env, **as_session("0000-contract")})
        config.write_text(json.dumps({"log": str(Path(tmp) / "calls.jsonl"), "health": {"counts": {}, "items": {"questions": [
            {"id": "fx-q", "status": "open", "type": "decision", "title": "Store?", "priority": 1, "blockedBy": []}]}}, "items": {}}))
        run("start", "round", cwd=repo)
        run("step", stdin={"classes": {"fx-q": "user"}}, cwd=repo)
        run("step", stdin={"select": ["fx-q"]}, cwd=repo)
        run("step", stdin={**ROUND_INFO, "questions": [{"text": "Which store?", "title": "Store", "header": "Store", "board": "fx-q", "problem": "Which store.", "options": [
            {"label": "Keep", "description": "keep it", "for": "for it", "against": "against it"}, {"label": "Drop", "description": "drop it", "for": "for it", "against": "against it"}],
            "recommendation": "Keep", "strength": "lean", "leanBecause": {"cause": "preference", "detail": "taste", "flipsIf": "a different taste"}}]}, cwd=repo)
        while (waiting := json.loads(run("show", "--json", cwd=repo)))["pending"] is not None:
            run("step", stdin={"pass": waiting["pending"]["command"], "updates": [], "checked": ["every question"],
                               **({"explored": {q["id"]: "no other way" for q in waiting["questions"]}} if waiting["pending"]["args"].startswith("options") else {})}, cwd=repo)
        run("step", stdin={"settle": {json.loads(run("show", "--json", cwd=repo))["questions"][0]["id"]: "park"}}, cwd=repo)
        states["parked"] = show(cwd=repo)
    return states


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
        for name in ("board", "protocol", "session-lead-mode"):
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
        registry = root / "bin" / "session-lead-mode"
        for args, session, tool in ((("lead",), "0000-lead0001", "claude"), (("solo",), "0000-cdx00001", "codex")):
            subprocess.run(["bash", str(registry), "activate", *args], check=True,
                           env={**os.environ, **session_env(str(state)), **as_session(session, tool)})
        base = {**os.environ, **session_env(str(state)), "PROTOCOL_BOARD": str(fake), "FAKE_BOARD_CONFIG": str(config),
                "BEADS_ACTOR": ""}
        counts = {"questions": 3, "decided": 1, "toPlan": 2, "inReview": 0, "forUser": 1}

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

        def proto(*args, stdin=None, cwd=plain, session="0000-lead0001", ok=True, env=None, process=False, observe=True, explore=True, cover=True):
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
            if observe and args[:1] == ("step",) and isinstance(stdin, dict) and ({"records", "defer"} & set(stdin)):
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
            return result

        def shown(**kwargs):
            return json.loads(proto("show", "--json", **kwargs).stdout)

        def refused(*args, stdin=None, needle, **kwargs):
            result = proto(*args, stdin=stdin, ok=False, **kwargs)
            if needle not in result.stderr:
                raise ValueError(f"protocol {' '.join(args)}: stderr lacks {needle!r}: {result.stderr}")

        def question(text, **extra):
            return {"text": text, "title": text.rstrip("?"), "header": "Q", "problem": "Which one, and why now.", "cases": "A caller who keeps it; one who drops it.", "premises": "Read in the fixture.", "rulings": [], "options": [
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
            if empty != {"version": 1, "session": "0000-lead0001", "protocol": None, "round": None, "title": None, "summary": None,
                         "step": None, "check": None,
                         "pending": None, "questions": [], "batch": None, "counts": None, "progress": None, "log": [],
                         "records": [], "stopped": None, "next": None} \
                    or proto("pending").stdout.strip() != "null" or proto("status", "--line").stdout.strip() != "protocol: no open round":
                raise ValueError(f"protocol without a round: {empty}")
            refused("step", stdin={}, needle="no open round")

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
            out = proto("step", stdin={"records": {"q1": {"rationale": "Simpler.", "ruleOwner": "docs/cache.md#cache"}}}).stdout
            record = (notes / "r1-q1.md").read_text(encoding="utf-8")
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
                    or "0000-lead0001 r1: passes model 9, plugin 1" not in history:
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
            out = proto("start", "round", stdin={"points": ["Pasted point"]}, cwd=repo).stdout
            first_calls = calls()
            if [c["args"] for c in first_calls] != [["health", "--json", "--items", "decided,questions,ratification,review,user"],
                                                    ["position", "--json"]] \
                    or first_calls[0]["actor"] != "lead0001" or Path(first_calls[0]["cwd"]).resolve() != repo.resolve() \
                    or "decided, awaiting release · decided (1):\n- fx-d: D" not in out \
                    or out.index("- fx-d: D") > out.index("- fx-a: A?") or "ready milestones · open (1):\n- fx-m [milestone]: Beta" not in out:
                raise ValueError(f"protocol Collect from board health and position: {first_calls}\n{out}")
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
                question("Pasted point?", kind="confirm-own-rulings", **{"for": "pt3"})]})
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
            expected = [["claim", "fx-a"], ["record", "fx-a"], ["claim", "fx-b"], ["record", "fx-b"],
                        ["bd", "list", "--external-ref"], ["revise", "fx-old", "--title", "Pasted point", "--body-file"],
                        ["bd", "batch", "-m", "protocol: link fx-rev1", "--json"], ["claim", "fx-rev1"], ["record", "fx-rev1"],
                        ["health", "--json", "--items", "decided"]]  # one Record writes all three
            if [c["args"][:len(want)] for c, want in zip(board_calls, expected)] != expected or len(board_calls) != len(expected) \
                    or board_calls[6]["stdin"] != "dep add fx-rev1 fx-rel relates-to\n" \
                    or 'User (chat), ' not in records or '"keep   it,\nfinal"' not in records or "## Decision\nKeep the point." not in records \
                    or "Board: 3 open questions, 1 decided awaiting release, 2 released to plan, 0 in review, 1 waiting on the user." not in out \
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
            out = proto("start", "round", cwd=repo).stdout
            if "Held by live session other001, not offered: fx-live" not in out or "- fx-live" in out \
                    or "- fx-gone, held by gone0001 (gone): Gone?" not in out:
                raise ValueError(f"protocol Collect must leave out live foreign holds and mark gone ones:\n{out}")
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
                    or any(c["args"][:2] in (["claim", "fx-m1"], ["record", "fx-m1"]) for c in second) \
                    or ["record", "fx-m2"] not in [c["args"][:2] for c in second] or ["record", "fx-m3"] not in [c["args"][:2] for c in second] \
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
            if [c for c in calls() if c["args"][0] in ("revise", "claim", "supersede")] or shown(cwd=repo)["step"] != "record":
                raise ValueError("a record that does not name the closed record must be refused before any board write")
            out = proto("step", stdin={"records": {qid: {"rationale": "Replaces fx-u1: the same store, now with a TTL.", "ruleOwner": "o"}}},
                        cwd=repo).stdout
            rows = calls()
            made = [c["args"][:2] for c in rows if c["args"][0] in ("revise", "claim", "record", "supersede")]
            revise_args = next(c["args"] for c in rows if c["args"][0] == "revise")
            if not re.fullmatch(rf"protocol:0000-lead0001:r\d+:{qid}", revise_args[revise_args.index("--external-ref") + 1] if "--external-ref" in revise_args else ""):
                raise ValueError(f"Record must tag a revision with its session, round and question: {revise_args}")
            history = [json.loads(row) for row in (session_dir / "history.jsonl").read_text().splitlines()]
            if made != [["revise", "fx-u1"], ["claim", "fx-n1"], ["record", "fx-n1"], ["supersede", "fx-u1"]] \
                    or item_status("fx-u1") != "closed" or "- " + qid + " → fx-n1, closed fx-u1" not in out \
                    or "recorded " + qid + " · superseded fx-u1 by fx-n1 · round closed" not in out.splitlines()[0] \
                    or not any(e["event"] == "superseded" and (e["question"], e["old"], e["new"]) == (qid, "fx-u1", "fx-n1") for e in history):
                raise ValueError(f"Record must close the replaced decided record and report it: {made}\n{out}")
            # Beta: a deferred question closes nothing and leaves the old record alone.
            qid = replacing("Beta point", ["fx-u2"], {"fx-u2": "supersedes"}, items={"fx-u2": decided})
            answered()
            calls()
            proto("step", stdin={"records": {}, "defer": {qid: "later"}}, cwd=repo)
            if [c for c in calls() if c["args"][0] in ("revise", "claim", "record", "supersede")] or item_status("fx-u2") != "decided":
                raise ValueError("a deferred question must close nothing")
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
            if [c["args"][:2] for c in rows if c["args"][0] in ("revise", "supersede")] != [["revise", "fx-u3"], ["supersede", "fx-u3"], ["supersede", "fx-u4"]] \
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
            if [c["args"][:2] for c in rows if c["args"][0] in ("revise", "supersede")] != [["revise", "fx-r0"], ["supersede", "fx-u5"]] \
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
            # Zeta: a record another live session holds is refused at Related (board supersede has no holder check); a gone
            # session's hold is taken at Record, just before the close.
            held = {"position": {"held": [{"id": "fx-live", "holder": "other001", "mark": "idle"}, {"id": "fx-gone", "holder": "gone0001", "mark": "gone"}]}}
            qid = replacing("Zeta point", ["fx-live"], None, items={"fx-live": {**decided, "assignee": "other001"}}, **held)
            refused("step", stdin={"outcomes": {qid: {"fx-live": "supersedes"}}}, needle="another live session holds it", cwd=repo)
            proto("abandon", cwd=repo)
            qid = replacing("Zeta point", ["fx-gone"], {"fx-gone": "supersedes"}, items={"fx-gone": {**decided, "assignee": "gone0001"}}, newIds=["fx-n5"], **held)
            answered()
            calls()
            proto("step", stdin={"records": {qid: {"rationale": "Replaces fx-gone.", "ruleOwner": "o"}}}, cwd=repo)
            made = [c["args"][:2] for c in calls() if c["args"][0] in ("take", "supersede")]
            if made != [["take", "fx-gone"], ["supersede", "fx-gone"]]:
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
            made = [c["args"][:2] for c in calls() if c["args"][0] in ("revise", "claim", "record", "supersede")]
            if made != [["revise", "fx-u11"], ["claim", "fx-n11"], ["record", "fx-n11"], ["supersede", "fx-u11"]] or item_status("fx-u11") != "closed":
                raise ValueError(f"Record must close the missed record: {made}")
            configure()
            # Theta: a close that failed is retried on the rerun without a second record; a close that bd made before it
            # exited 1 counts as done and says so.
            qid = replacing("Theta point", ["fx-u9"], {"fx-u9": "supersedes"}, items={"fx-u9": decided}, newIds=["fx-n7"], fail=["supersede"])
            answered()
            calls()
            report = {"records": {qid: {"rationale": "Replaces fx-u9.", "ruleOwner": "o"}}}
            out = proto("step", stdin=report, cwd=repo).stdout
            if "Not recorded" not in out or "board supersede fx-u9 --with fx-n7" not in out or shown(cwd=repo)["step"] != "record" or item_status("fx-u9") != "decided":
                raise ValueError(f"a failed close must leave the question unrecorded:\n{out}")
            patch_config(fail=[])
            out = proto("step", stdin=report, cwd=repo).stdout
            made = [c["args"][:2] for c in calls() if c["args"][0] in ("revise", "supersede")]
            if made != [["revise", "fx-u9"], ["supersede", "fx-u9"], ["supersede", "fx-u9"]] or item_status("fx-u9") != "closed" or "Round r" not in out or shown(cwd=repo)["round"] is not None:
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
            out = proto("start", "round", "--proposal", "2", cwd=repo).stdout
            topic = "Plain question: A question no member covers, the highest priority outside a milestone."
            if f"Topic: {topic}" not in out or "Named for this round: fx-n1." not in out or "Open items (" not in out:
                raise ValueError(f"--proposal starts the row's topic round on its leading ids:\n{out}")
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
            # r24-q104: a topic round's Collect prints the whole open list every time, with the grouping steer; a bare or named
            # round prints it once between compactions.
            topic = "Member questions: members share one cache"
            for named in ([], ["fx-n1"]):
                out = proto("start", "round", "--topic", topic, *named, cwd=repo).stdout
                if f"Topic: {topic}." not in out or "Group by default" not in out or "a round of a single question names why no other shares one" not in out \
                        or "Open items (" not in out or "listed earlier" in out or (named and "Named for this round: fx-n1." not in out):
                    raise ValueError(f"a topic round's Collect prints the whole list and the grouping steer:\n{out}")
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
            # A premise deferred at Record leaves its dependents without a settled premise: they cannot be recorded as decided.
            refused("step", cwd=repo, needle=f"{chain[1]} rests on deferred {chain[0]}", stdin={
                "records": {qid: {"rationale": "R.", "ruleOwner": "docs/c.md#c"} for qid in chain[1:]}, "defer": {chain[0]: "later"}})
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

            # R: a release run (r3-q7, r4-q12..q19): the default set (the session's held decided records), refusals, a contained
            # drop that lapses the typed approval into a dialog, owner checks, a resumable release, spreads, Codex.
            docs = repo / "docs"
            docs.mkdir(exist_ok=True)
            (docs / "x.md").write_text("# X\n\n## Approved dependencies, settlement and retry — implementation pending\n\n"
                                       "```\n## Not a heading\n```\n<a id=\"explicit-one\"></a>\n", encoding="utf-8")
            (docs / "y.md").write_text("# Y\n", encoding="utf-8")
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
            refused("start", "release", "--no-board", str(notes), needle="record ids only", cwd=repo)
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
                    needle='touches is "own"', cwd=repo)
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
            # A close board release would refuse is refused here, while the report can change (not after the approval).
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
                                  ({"written": {"path": "docs/y.md"}}, "does not name docs/y.md; fix the record text and run `board record fx-r1 <file>`"),
                                  ({"pending": {"item": "fx-done"}}, "pending item fx-done is closed, not open")):
                refused("step", stdin={"owners": {"fx-r1": [entry]}}, needle=needle, cwd=repo)
            # Owner paths git ignores are refused; untracked (docs/x.md below) and installed paths are not.
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            (repo / ".gitignore").write_text(".scratch/\n", encoding="utf-8")
            (repo / ".scratch").mkdir(exist_ok=True)
            (repo / ".scratch" / "rule.md").write_text("# Rule\n", encoding="utf-8")
            refused("step", stdin={"owners": {"fx-r1": [{"written": {"path": ".scratch/rule.md"}}]}},
                    needle=".scratch/rule.md is ignored by git (e.g. .scratch): write the rule into a tracked or trackable owner", cwd=repo)
            # The release: board release runs with the answered closes; it exits 1 (a revise supersede failed) and the other
            # supersede fails: the step stays and reruns only what remains.
            patch_config(releaseFail=["fx-r1"], supersedeFail=["fx-old"])
            calls()
            out = proto("step", stdin={"owners": {"fx-r1": [{"written": {"path": "docs/x.md", "anchor": anchor}},
                                                            {"written": {"path": "docs/x.md", "anchor": "explicit-one"}},
                                                            {"pending": {"item": "fx-pend"}}]}}, cwd=repo).stdout
            made = [c["args"] for c in calls() if c["args"][0] in ("release", "supersede")]
            if made != [["release", "fx-r1", "--closes", "fx-q1=fx-r1"], ["supersede", "fx-old", "--with", "fx-r1", "--partial", "Rule 2"]] \
                    or shown(cwd=repo)["step"] != "release" or "exited 1" not in out or "reruns only what remains" not in out \
                    or "board release fx-r1 closing fx-q1: exit 1" not in out.splitlines()[0]:
                raise ValueError(f"protocol release must report a partial failure and stay: {made}\n{out}")
            patch_config(releaseFail=[], supersedeFail=[])
            out = proto("step", stdin={}, cwd=repo).stdout
            made = [c["args"] for c in calls() if c["args"][0] in ("release", "supersede")]
            if made != [["release", "fx-r1"], ["supersede", "fx-old", "--with", "fx-r1", "--partial", "Rule 2"]] \
                    or not re.match(r"r\d+ release · the session's records · .*superseded fx-old by fx-r1 · released fx-r1", out) \
                    or "- released fx-r1: R1" not in out or "- closed fx-q1: answered by released fx-r1" not in out \
                    or "- superseded fx-old by fx-r1 (rule: Rule 2)" not in out or "- dropped fx-r2" not in out \
                    or "decide.md Release 7" not in out or "`protocol next`" not in out or '"fresh": false' in out \
                    or shown(cwd=repo)["round"] is not None \
                    or "board release" in out.splitlines()[0]:
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
            if any(c["args"][0] in ("release", "supersede", "unclaim") for c in calls()) \
                    or "Nothing released; fx-s1 stay decided and held" not in out or "opens with step-back" not in out \
                    or not out.splitlines()[0].endswith("next: a round on fx-s1") \
                    or shown(cwd=repo)["stopped"] != {"run": shown(cwd=repo)["stopped"]["run"], "reason": "fx-s1 changed: the premise moved", "ids": ["fx-s1"]}:
                raise ValueError(f"a spreading change must stop the release:\n{out}")
            # A typed /release-round on an open release approves it without a dialog when every ruling is sure and the set
            # is unchanged; during an open round it is refused.
            # A record waiting on an open item outside the set leaves it at the board check (board release would refuse).
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
            # Own contained change (r8-q36): the record stays, revised, with its corrected text written by board record; a
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
                    needle="`board record fx-s2 missing-s2.md` exited", cwd=repo)
            if shown(cwd=repo)["step"] != "recheck":
                raise ValueError("a failed board record must leave the re-check where it was")
            calls()
            proto("step", stdin={"records": {"fx-s1": "unchanged", "fx-s2": own}}, cwd=repo)
            view = shown(cwd=repo)
            if ["record", "fx-s2", "fixed-s2.md"] not in [c["args"] for c in calls()] \
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
            # An unsure ruling leads the dialog, in full in the preview; a question during the release is told to abandon; a
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
                    or long_ruling not in release_option.get("preview", "") or "reveal refuses" not in release_option["preview"]:
                raise ValueError(f"the dialog must lead with the unsure ruling and show it in full in the preview: {dialog}")
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
                    or "fx-d1 revises fx-old: `board supersede fx-old --with fx-d1`" not in out or "fx-elsewhere" in out:
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
            for extra in ({"annotations": {"Solo?": {"notes": "log it"}}}, {"response": "rethink the lead"}):
                solo = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Solo?"]}, cwd=repo).stdout
                solo_point = re.search(r"(pt\d+) \[pasted\]", solo).group(1)
                proto("step", stdin={"classes": {solo_point: "user"}}, cwd=repo)
                proto("step", stdin={"select": [solo_point]}, cwd=repo)
                proto("step", stdin={**ROUND_INFO, "questions": [question("Solo?", **{"for": solo_point})]}, cwd=repo)
                converge(cwd=repo)
                solo_note = json.loads(proto("answer", "--origin", "dialog", cwd=repo, stdin={
                    "marker": shown(cwd=repo)["batch"]["marker"], "answers": {"Solo?": "Keep (recommended, lean)"}, **extra}).stdout)["note"]
                if "a change to the questions → `protocol edit` (updates + the quote)" not in solo_note \
                        or "call a pass's skill on it, then report that pass" not in solo_note:
                    raise ValueError(f"a note or a response carries the shared routes of the person's own words: {solo_note}")
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
            out = proto("start", "round", **real_session).stdout
            # fx-ovo.3 is held by the live lead0001: left out of this session's candidates, still a Related hit below.
            if "Held by live session lead0001, not offered: fx-ovo.3" not in out or "- fx-ovo.3" in out or "- fx-ovo.1: Store choice" not in out:
                raise ValueError(f"protocol Collect through bin/board:\n{out}")
            proto("step", stdin={"classes": {"fx-ovo.1": "user", "fx-ovo.9": "planning"}}, **real_session)
            proto("step", stdin={"select": ["fx-ovo.1"]}, **real_session)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Store choice?", board="fx-ovo.1"),
                                               question("Which store backs the cache?")]}, **real_session)
            overlaps = next(q for q in shown(**real_session)["questions"] if q["board"] is None)["overlaps"]
            if overlaps != [{"id": "fx-ovo.6", "title": "Design cache", "outcome": None},
                            {"id": "fx-ovo.3", "title": "Open cache question", "outcome": None}]:
                raise ValueError(f"protocol Related through board related --json: {overlaps}")

        if part == "texts":
            # F: round texts: every error at once, the limits, previews, the report format once, hand-offs, the release dialog.
            texts = {"session": "0000-texts001"}
            proto("start", "round", "--no-board", str(notes), stdin={"points": ["Limits?"]}, **texts)
            proto("step", stdin={"classes": {"pt1": "user"}}, **texts)
            proto("step", stdin={"select": ["pt1"]}, **texts)
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
                {"label": "Keep", "description": "d" * 150, "for": "for it", "against": "against it", "preview": "x = 1"}, {"label": "B", "description": "", "for": "for it", "against": "against it"}], **{"for": "pt1"})]})
            refused("step", **texts, stdin={"pass": "step-back", "updates": [question("Multi?", multiSelect=True, options=[
                {"label": "Keep", "description": "", "for": "for it", "against": "against it", "preview": "x"}, {"label": "B", "description": "", "for": "for it", "against": "against it"}])]}, needle="`preview` is for single-select")
            # A refused pass report repeats the report format; the first pass of a round carries it, later passes do not.
            refused("step", **texts, stdin={"pass": "nope"}, needle="After the pass, report each change")
            refused("step", **texts, stdin={}, needle="Report with `protocol step`")
            refused("step", **texts, stdin={"pass": "step-back", "updates": []}, needle="After the pass, report each change")
            out = proto("step", **texts, stdin={"pass": "step-back", "updates": [], "checked": ["q1"]}).stdout
            if "After the pass" in out or "Report with `protocol step`" in out:
                raise ValueError(f"the report format goes out with the first pass only: {out}")
            # A two-question dialog is numbered; one question is not. Previews pass through; the lean mark is not counted.
            proto("step", **texts, stdin={"pass": "ground", "updates": [question("Second?", **{"for": "pt1"})], "checked": ["q1"]})
            for command in ("step-back", "ground"):
                proto("step", **texts, stdin={"pass": command, "updates": [], "checked": ["q1"]})
            converge(**texts)
            batch = shown(**texts)["batch"]
            if [q["question"] for q in batch["questions"]] != ["1. " + "y" * 160, "2. Second?"] \
                    or batch["questions"][0]["options"][0]["preview"] != "x = 1" \
                    or len(batch["questions"][0]["options"][0]["description"]) <= 150 \
                    or "in this order, numbered like the dialog" not in proto("show", **texts).stdout:
                raise ValueError(f"the dialog numbers a batch of two and passes previews through: {batch}")
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
            refused("step", **texts, observe=False, stdin=unobserved, needle="Report with `protocol step`")
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
                {"label": "Keep", "description": "keep it", "for": "for it", "against": "against it", "preview": "x = 1"}, {"label": "Drop", "description": "", "for": "for it", "against": "against it"}], **{"for": found})]})
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
            # A scoped options pass leaves out a restarted confirmation (r30-q142), so it counts without that id.
            found = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": ["Mixed?"]}, **texts).stdout)[1]
            proto("step", stdin={"classes": {found: "user"}}, **texts)
            proto("step", stdin={"select": [found]}, **texts)
            proto("step", **texts, stdin={**ROUND_INFO, "questions": [question("Mix decision?", **{"for": found}),
                                                                       question("Mix confirmation?", kind="confirm-own-rulings", **{"for": found})]})
            decision, confirmation = [q["id"] for q in shown(**texts)["questions"]]
            while shown(**texts)["step"] == "check":
                report()
            proto("restart", decision, confirmation, "--reason", "criterion", **texts)
            report()  # the scoped path pass
            if pending_now() != ("step-back", f"options on {decision}"):
                raise ValueError(f"the scoped options pass names the decision only: {pending_now()}")
            report()  # the scoped options pass
            if pending_now() != ("step-back", ""):
                raise ValueError(f"a scoped options pass without the restarted confirmation counts: {pending_now()}")
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
            # With a batch out, edit withdraws and re-issues it; a previews-only change is presentation (no loop rerun).
            while shown(**texts)["step"] == "check":
                proto("step", **texts, stdin={"pass": shown(**texts)["pending"]["command"], "updates": [], "checked": ["q"]})
            first = shown(**texts)["batch"]["marker"]
            proto("say", "--origin", "composer", stdin={"text": "add a preview to Keep"}, **texts)
            proto("edit", **texts, stdin={"updates": [{"id": qid, "options": [{"label": "Keep", "description": "keep it", "for": "for it", "against": "against it", "preview": "x = 1"},
                                                                              {"label": "Drop", "description": "drop it", "for": "for it", "against": "against it"}]}], "quote": "add a preview to Keep"})
            again = shown(**texts)
            if again["batch"]["marker"] == first or again["batch"]["questions"][0]["options"][0].get("preview") != "x = 1" or again["step"] != "ask":
                raise ValueError(f"edit re-issues a batch that is out: {again}")
            proto("step", **texts, stdin={"pass": "ground", "updates": [{"id": qid, "options": [{"label": "Keep", "description": "keep it", "for": "for it", "against": "against it", "preview": "x = 2"},
                                                                                                  {"label": "Drop", "description": "drop it", "for": "for it", "against": "against it"}]}], "checked": ["q"]})
            presented = shown(**texts)
            if presented["step"] != "ask" or presented["batch"]["questions"][0]["options"][0].get("preview") != "x = 2":
                raise ValueError(f"a previews-only pass update re-issues the batch without rerunning the loop: {presented}")
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
            if any(c["args"][0] in ("claim", "record", "revise") or c["args"][:2] == ["bd", "create"] for c in calls()):
                raise ValueError("a refused Record must write nothing")
            named = {"records": {**unnamed["records"], rule_q["id"]: {"rationale": "Both stores close: fx-a (the old store) and fx-b (the "
                                                                                  "cache) follow the rule.", "ruleOwner": "docs/x.md"}}}
            calls()
            out = proto("step", stdin=named, **rules).stdout
            made = calls()
            recorded = Path(str(log) + ".records").read_text(encoding="utf-8")
            link = next((c for c in made if c["args"][:2] == ["bd", "batch"]), None)
            if [c["args"][0] for c in made if c["args"][0] != "bd" and c["args"][0] != "show"] != ["claim", "record", "claim", "record", "health"] \
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
            made = [c["args"] for c in calls() if c["args"][0] == "release"]
            if made != [["release", "fx-new1", "--closes", "fx-a=fx-new1", "fx-b=fx-new1"]] \
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
            proto("step", stdin={"records": {}, "defer": {shown(**rules)["questions"][0]["id"]: "not yet"}}, **rules)
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
            proto("step", stdin=stage(question("Rule: confirm?", kind="confirm-own-rulings", settles=["fx-a", "fx-b"]), store("c")), **rules)
            proto("abandon", **rules)

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

            # A: the question list prints in a cycle's first check pass and is counted after; every pass is the skill's own full text
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
            # B: the cycle's first check pass lists the questions, the others count them.
            if "(protocol show lists them)" not in outputs[0] or f"- {qid} draft" in outputs[0] or f"- {qid} draft" in outputs[1]:
                raise ValueError(f"later check passes of a cycle count the questions:\n{outputs[0]}")
            proto("abandon", **home)

            # A2: a change opens the next cycle: its first check pass lists the questions again.
            to_check("Cycles?", **home)
            qid = staged["q"]
            run_pass(**home)                                                                       # path pass
            run_pass(**home)                                                                       # options pass
            run_pass(**home)                                                                       # Base step-back
            _, out = run_pass(updates=[{"id": qid, "premises": "a changed premise"}], **home)     # the cycle's ground, with a change
            nxt = shown(**home)
            if (nxt["check"]["cycle"], nxt["pending"]["command"]) != (2, "step-back") \
                    or f"- {qid} draft: Cycles?" not in out:
                raise ValueError(f"the next cycle's first check pass lists the questions:\n{nxt}\n{out}")
            _, out = run_pass(**home)
            if "(protocol show lists them)" not in out:
                raise ValueError(f"cycle 2: the question list was told:\n{out}")
            if f"- {qid} draft: Cycles?" not in proto("show", **home).stdout:
                raise ValueError("protocol show lists the questions whatever the record says")
            # A restart is a new check run: its first check pass lists them again.
            proto("restart", qid, **home)
            run_pass(**home)                                                                       # the scoped path pass
            run_pass(**home)                                                                       # the scoped options pass
            # C: a compaction lists the questions again.
            proto("compacted", **home)
            _, out = run_pass(origin="composer", **home)
            if f"- {qid} draft: Cycles?" not in out or shown(**home)["pending"]["command"] != "ground":
                raise ValueError(f"the questions list again after a compaction:\n{out}")
            proto("abandon", **home)
            if "Compaction recorded" not in proto("compacted", **home).stdout or history(**home)[-1]["event"] != "compacted":
                raise ValueError("protocol compacted works without an open round and logs it")

            # r24-q108: abandon says which records stay decided, not "nothing recorded".
            kept = engine_module.record.abandon_note([{"id": "q1", "board": "fx-a", "recorded": "fx-a"}, {"id": "q2", "board": None, "recorded": "file"},
                                               {"id": "q3", "board": "fx-c", "recorded": None}, {"id": "q4", "board": "fx-d", "recorded": "deferred"}])
            if kept != "recorded fx-a, q2 stay decided" or engine_module.record.abandon_note([{"id": "q3", "board": "fx-c", "recorded": None}]) != "nothing recorded":
                raise ValueError(f"abandon must name what stays decided: {kept}")

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
            bare = proto("start", "round", **listing_session).stdout
            if "- fx-b" in bare or "Open items: 1 decided, 2 open questions, 1 waiting on the user" not in bare or "List them before you select." not in bare:
                raise ValueError(f"a bare round after the list was printed counts and tells the model to list first:\n{bare}")
            proto("step", stdin={"classes": {"fx-b": "user"}}, **listing_session)  # an item not printed is classified all the same
            if "fx-b" not in proto("show", **listing_session).stdout:
                raise ValueError("the engine keeps every item: an unprinted id classifies")
            proto("abandon", **listing_session)
            proto("compacted", **listing_session)
            bare = proto("start", "round", **listing_session).stdout
            if "Open items (6):" not in bare or "List them before you select." in bare:
                raise ValueError(f"after a compaction the first Collect prints the whole list:\n{bare}")
            proto("abandon", **listing_session)
            if "Open items (" in proto("next", **listing_session).stdout:
                raise ValueError("a round's Collect counts as the list printed: protocol next after it does not print it again")
            # A named round: start round <ids>; the whole list the first time, the named ids with counts afterwards.
            proto("compacted", **listing_session)
            named = proto("start", "round", "fx-a", "fx-b", **listing_session).stdout
            if "Open items (6):" not in named or "Named for this round: fx-a, fx-b." not in named:
                raise ValueError(f"a named round prints the whole list the first time:\n{named}")
            proto("abandon", **listing_session)
            named = proto("start", "round", "fx-a", **listing_session).stdout
            if "Named:\n- fx-a: A?\n" not in named or "Open items: 1 decided, 2 open questions, 1 waiting on the user" not in named or "- fx-b" in named \
                    or "List them before you select." in named or "Open items (" in named:
                raise ValueError(f"a named round afterwards prints its ids, the counts and the command:\n{named}")
            if shown(**listing_session)["round"] is None:
                raise ValueError("the named round started")
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

            # H: report formats once per step kind between compactions; a refused report repeats its format. The ask instructions
            # once; the dialog itself always.
            fmt = {"session": "0000-ctxfmt001", **home}
            first = proto("start", "round", "--no-board", str(ctx_notes), stdin={"points": ["Formats?"]}, **fmt).stdout
            if "Report with `protocol step`" not in first or '"classes"' not in first:
                raise ValueError(f"the first Collect carries its report format:\n{first}")
            refused("step", stdin={"classes": {"nope": "user"}}, needle='Report with `protocol step` (stdin JSON), e.g. {"classes"', **fmt)
            proto("abandon", **fmt)
            second = proto("start", "round", "--no-board", str(ctx_notes), stdin={"points": ["Again?"]}, **fmt).stdout
            if "Report with" in second:
                raise ValueError(f"the report format of a step kind prints once between compactions:\n{second}")
            refused("step", stdin={"classes": {"nope": "user"}}, needle='Report with `protocol step` (stdin JSON), e.g. {"classes"', **fmt)
            proto("step", stdin={"classes": {"pt2": "user"}}, **fmt)
            refused("step", stdin={"select": ["pt9"]}, needle='Report with `protocol step` (stdin JSON), e.g. {"select"', **fmt)
            proto("step", stdin={"select": ["pt2"]}, **fmt)
            refused("step", stdin={"questions": []}, needle='Report with `protocol step` (stdin JSON), e.g. {"round"', **fmt)
            proto("step", stdin={**ROUND_INFO, "questions": [question("Again?", **{"for": "pt2"})]}, **fmt)
            refused("step", stdin={"pass": "step-back", "updates": []}, needle="After the pass, report each change", **fmt)
            ask = converge(**fmt)
            if "Record an answer the user types in chat" not in ask or "open the dialog" not in ask:
                raise ValueError(f"the first ask prints the instructions and the dialog:\n{ask}")
            proto("answer", "--origin", "dialog", stdin={"marker": "round:r2:1", "answers": {"Again?": "Keep"}}, **fmt)
            proto("step", stdin={"pass": "challenge-rulings", "updates": [], "checked": ["the answer"]}, **fmt)
            refused("step", stdin={"records": {}}, needle='Report with `protocol step` (stdin JSON), e.g. {"records"', **fmt)
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
                line = "This pass covers " + " ".join(ids) + ":" if ids else "Nothing changed since this pass last ran"
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
                if ids and f"This pass covers {' '.join(ids)}:" not in got["text"] or explored and f"Give `explored` an entry for each of {' '.join(explored)} and no other." not in got["text"]:
                    label_fail(label, f"scope verb text: {got['text']!r}")
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
            # Ground's own q3 change leaves its rerun empty: one round note passes, nothing at all is refused.
            expect_scope("empty scope named", out, [])
            expect_refused("an empty report on an empty scope is refused", report("ground", {}), "names what it checked")
            out = expect_ok("empty scope passes with a round note", report("ground", {"round": "nothing changed since the last ground"}))
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
            out = expect_ok("ground cycle 4", report("ground", {"round": "nothing new"}))
            # The challenge rerun covers what changed since it ran (q2), not its own q1; q2 is strong: lowering it covers it.
            expect_scope("challenge rerun = changed since the last challenge", out, ["q2"])
            expect_refused("challenge rerun needs q2's verdict", report("challenge-rulings", {"q2": "read"}, rulings=[]), "verdicts.q2")
            out = expect_ok("a lowering update satisfies the verdict", report("challenge-rulings", {}, [
                {"id": "q2", **lean}, {"id": "q3", "premises": "Changed by the second challenge."}], rulings=[]))
            expect_scope("step-back covers the challenge's changes", out, ["q2", "q3"])
            out = expect_ok("step-back cycle 5", report("step-back", {"q2": "read", "q3": "read"}))
            out = expect_ok("ground cycle 5", report("ground", {"q2": "read", "q3": "read"}))
            expect_scope("challenge scope empty after its own change", out, [])
            if start_scope("challenge-rulings", pending().get("id")) != {"covers": [], "explored": None, "text": ""}:
                label_fail("scope verb: an empty scope names nothing", start_scope("challenge-rulings", pending().get("id")))
            expect_ok("empty challenge with a round note", report("challenge-rulings", {"round": "nothing changed since the last challenge"}, rulings=[]))
            view = shown(session=cover["session"])
            if view["step"] != "ask" or not view["batch"]:
                label_fail("the round reaches Ask", f"{view['step']} {view['pending']}")
            else:
                # After the last answer: the challenge covers the answered set; q4 stays strong and needs its verdict.
                proto("answer", "--origin", "dialog", session=cover["session"], stdin={"marker": view["batch"]["marker"], "answers": {
                    q["question"]: "Keep" for q in view["batch"]["questions"]}})
                if pending().get("command") != "challenge-rulings":
                    label_fail("the after-answers challenge is pending", pending())
                expect_refused("after-answers scope = the answered set", report("challenge-rulings", {"round": "x"}, rulings=[]),
                               "no `checked` entry or update for q1 q2 q3 q4", "verdicts.q4")
                expect_ok("after-answers challenge", report("challenge-rulings", {q: "the answer" for q in every}, rulings=[],
                                                            verdicts={"q4": {"strongBecause": STRONG_CLAIMS}}))
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
                    or "run `session-lead-mode activate solo` first" not in ask \
                    or f"- {q1}: fx-a? Recommendation: Keep (lean)" not in ask or "Text to show first" in ask:
                raise ValueError(f"an away Ask opens no batch and asks for act or park per question:\n{ask}\n{view}")
            refused("step", stdin={"settle": {}}, needle=f"settle: no entry for {q1}", **away)
            refused("step", stdin={"settle": {}}, needle='Report with `protocol step` (stdin JSON), e.g. {"settle": {"q1": "act", "<id>": "park"}}', **away)
            refused("step", stdin={"settle": {q1: "act", q2: "later"}}, needle=f'settle.{q2}: "act" or "park"', **away)
            refused("step", stdin={"settle": {q1: "act", q2: "park", "q9": "act"}}, needle="settle: q9 is not waiting to be settled", **away)
            refused("answer", "--origin", "away", stdin={"marker": "round:r1:1", "answers": {}}, needle="origin 'away' is not accepted", **away)
            calls()
            out = proto("step", stdin={"settle": {q1: "act", q2: "park"}}, **away).stdout
            made = [c["args"] for c in calls()]
            parked_rows = {q["id"]: q for q in shown(**away)["questions"]}
            if parked_rows[q1]["status"] != "answered" or parked_rows[q1]["answer"] != "Keep" or parked_rows[q2]["status"] != "parked" \
                    or not any(args[:4] == ["bd", "comments", "add", "fx-b"] for args in made) or ["unclaim", "fx-b"] not in made \
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
            calls()
            out = proto("step", stdin={"records": {q1: {"rationale": "Took fx-a.", "ruleOwner": "docs/x.md", "reversal": "board bd reopen fx-a"}}}, **away).stdout
            recorded = records_file.read_text(encoding="utf-8")
            made = [c["args"] for c in calls()]
            if not any(args[:2] == ["record", "fx-a"] and args[3:] == ["--status", "needs_ratification"] for args in made) \
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
                if needle not in result.stderr or "run `" + "session-lead-mode activate solo` first" not in result.stderr:
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
        validate_effort_overrides(generator)
        validate_worker_last_use(root)
        validate_copied_install(root)
        validate_engine_board_fields(root)
        validate_console_lenses(root)
        validate_start_round(root)
        validate_console_programs(root)
        validate_strength_rules(root)
        validate_lens_names(root)
    elif name == "hooks":
        validate_hooks(root)
    elif name == "board":
        validate_board(root)  # patches os.environ and stdout in-process: nothing else shares this process
        validate_shared_board(root)
    elif name == "contract":
        validate_console_contract(root)
    elif name.startswith("engine-"):
        validate_protocol(root, name.removeprefix("engine-"))
    else:
        raise SystemExit(f"unknown group {name}")


GROUPS = ("core", "hooks", "board", "contract", *(f"engine-{part}" for part in PROTOCOL_PARTS))


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