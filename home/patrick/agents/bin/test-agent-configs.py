#!/usr/bin/env python3
"""Validate shared skills and both generated custom-agent formats."""

from __future__ import annotations

import importlib.machinery
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
USER_ONLY_SKILLS = {"ask-advisor", "board-migrate", "question-me", "release-round", "retro", "role", "explain"}
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


def validate_session_registry(root: Path) -> None:
    script = root / "bin" / "session-lead-mode.sh"

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
    env_base = {"AGENT_SESSION_LEAD_COMMAND": str(root / "bin" / "session-lead-mode.sh")}
    pointer = "Recover under `$HOME/.agents/skills/shared/project-memory.md` Recovery and closure."
    # The pointer's target must keep the recovery obligations the hook used to restate.
    memory = (root / "skills" / "shared" / "project-memory.md").read_text(encoding="utf-8")
    recovery = " ".join(memory.split("## Recovery and closure", 1)[1].split())
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
        raise ValueError(f"project-memory Recovery and closure lost obligations {missing}")
    with tempfile.TemporaryDirectory() as state_dir:
        env = {**session_env(state_dir), **env_base}
        subprocess.run(["bash", str(root / "bin" / "session-lead-mode.sh"), "activate", "agent", "--pulls",
                        "implement,review"], check=True, env={**os.environ, **env, **as_session(SESSION)})
        for source in ("compact", "resume"):
            for session, registered in ((SESSION, True), ("abcdefgh-unregistered", False)):
                context = hook_context(run_hook(
                    hook, {"hook_event_name": "SessionStart", "source": source, "session_id": session}, env))
                if pointer not in context or "bd ready" in context:
                    raise ValueError(f"{source} recovery must point to project-memory recovery only: {context}")
                markers = ("role `agent` pulling implement, review", f"actor `{SESSION_ACTOR}`",
                           "`$HOME/.agents/skills/role/SKILL.md`", "every protocol file it lists")
                if registered and not all(marker in context for marker in markers):
                    raise ValueError(f"{source} recovery did not restore the registered role: {context}")
                if not registered and ("registered as role" in context or "role/SKILL.md" in context):
                    raise ValueError("recovery invented a role for an unregistered session")
        if run_hook(hook, {"hook_event_name": "SessionStart", "source": "startup", "session_id": SESSION}, env):
            raise ValueError("session recovery ran for a new session")
        generic = hook_context(run_hook(hook, {"hook_event_name": "SessionStart", "source": "compact"}, env))
        if "re-orient" not in generic or pointer not in generic or "registered as role" in generic:
            raise ValueError("recovery without a session id must stay generic")
        # Codex sessions get the open protocol round's line; Claude's console owns that recovery.
        fake = Path(state_dir) / "protocol"
        fake.write_text('#!/usr/bin/env bash\n[[ "$1 $3 $4" == "--session status --line" ]] && echo "protocol: round r2 · check 1/3"\n')
        fake.chmod(0o755)
        codex = "cdx-recovery-0001"
        subprocess.run(["bash", str(root / "bin" / "session-lead-mode.sh"), "activate", "lead"], check=True,
                       env={**os.environ, **env, **as_session(codex, "codex")})
        for session, expected in ((codex, True), (SESSION, False)):
            context = hook_context(run_hook(hook, {"hook_event_name": "SessionStart", "source": "compact",
                                                   "session_id": session}, {**env, "AGENT_PROTOCOL_COMMAND": str(fake)}))
            if ("protocol: round r2" in context) != expected:
                raise ValueError(f"compact-reorient protocol line for {session} (expected {expected}): {context}")


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


def validate_board(root: Path) -> None:
    """The board CLI against a fixture from `bd export` of a throwaway db
    (bd 1.3.1); bd writes are recorded, not run."""
    import contextlib
    import io
    from datetime import datetime, timezone
    from unittest.mock import patch

    spec = importlib.util.spec_from_file_location("board", root / "bin" / "board.py")
    if spec is None or spec.loader is None:
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

        def __call__(self, command, **kwargs):
            if command[0] != "bd":
                return real_run(command, **kwargs)
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

    with tempfile.TemporaryDirectory() as state_dir:
        registry = root / "bin" / "session-lead-mode.sh"
        for args, identity in ((("agent", "--pulls", "implement,review"), as_session("0000-aaaa1111", "codex")),
                               (("lead",), as_session("0000-lead0001")), (("solo",), as_session("0000-solo0001")),
                               (("autopilot",), as_session("0000-auto0001"))):
            subprocess.run(["bash", str(registry), "activate", *args], check=True,
                           env={**os.environ, **session_env(state_dir), **identity})
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
                           env={**os.environ, **session_env(state_dir), **as_session("0000-plan0001")})
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
                    or set(health_json["items"]["questions"][0]) != {"id", "type", "status", "priority", "holder", "title", "blockedBy"} \
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
            if text.count("--- a") != 5 or "older" in text:
                raise ValueError(f"board show --comments must print every comment:\n{text}")
            _, text, _ = invoke(["show", new, "--json", "--field", "comments", "--field", "status"], Fake(shown))
            if json.loads(text) != {new: {"comments": notes, "status": "decided"}}:
                raise ValueError(f"board show --json --field: {text[:500]}")
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
                    "--deps", f"tracks:{ids['Released ruling']}", "--parent", "fx-ovo", "--labels", "topic:store",
                    "--metadata", '{"board.revises_rule": "Rule 2"}', "--json"]]:
                raise ValueError(f"board revise: {fake.writes()}\n{output}")
            fake = Fake(topical)
            invoke(["revise", ids["Released ruling"], "--title", "t", "--body-file", "p.md", "-p", "1", "--parent", "fx-x",
                    "-l", "topic:a,topic:b"], fake, "lead0001")
            if fake.writes()[0][8:] != ["1", "--deps", f"tracks:{ids['Released ruling']}", "--parent", "fx-x", "--labels",
                                        "topic:a,topic:b", "--json"]:
                raise ValueError(f"board revise ignored -p/--parent/-l or set metadata without --partial: {fake.writes()}")
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
            if states["work0001"]["workers"] != {"active": 1 if now.startswith("2026-10-22T15") else 0, "cap": 6}:
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
                          or "  workers 1/6  " not in row(fresh, "work0001")
                          or "idle = no activity for 1 h (the holder's last tool call, else the item's last update)" not in fresh):
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
        registry = root / "bin" / "session-lead-mode.sh"
        for args, session, tool in ((("solo",), "0000-solo0001", "claude"), (("lead",), "0000-lead0001", "claude"),
                                    (("autopilot",), "0000-auto0001", "claude"),
                                    (("agent", "--pulls", "implement,review"), "0000-cdx00001", "codex"),
                                    (("agent", "--pulls", "plan,design,review"), "0000-cdx00002", "codex")):
            subprocess.run(["bash", str(registry), "activate", *args], check=True,
                           env={**os.environ, **as_session(session, tool)})
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
            result = subprocess.run([sys.executable, str(root / "bin" / "board.py"), *args], cwd=repo, text=True,
                                    capture_output=True, env={**env, **extra})
            return result, calls.read_text(encoding="utf-8") if calls.exists() else ""

        result, seen = run_board("bd", "list", "--json")
        if result.returncode != 7 or seen != "9999aaaa list --json\n":
            raise ValueError(f"board bd passthrough: {result.returncode} {seen!r}")
        # Raw show and comment listings are refused for board show; their other modes and comment adds pass.
        for args in (("show", "x"), ("show", "x", "--json"), ("view", "x", "y"), ("comments", "x"), ("comments", "x", "--json"),
                     ("-C", repo, "show", "x"), ("--actor", "9999aaaa", "comments", "x")):
            result, seen = run_board("bd", *args)
            if result.returncode != 2 or seen or "use board show <ids>" not in result.stderr:
                raise ValueError(f"board bd {args} must be refused for board show: {result.returncode} {seen!r}")
        for args in (("show", "x", "--refs"), ("show", "x", "--as-of=abc"), ("show", "--current"), ("comments", "add", "x", "y"),
                     ("show", "--help")):
            result, seen = run_board("bd", *args)
            if result.returncode != 7 or not seen.endswith(" ".join(args) + "\n"):
                raise ValueError(f"board bd {args} must pass through: {result.returncode} {seen!r}")
        for args in (("list", "--type", "question"), ("create", "-t", "question", "--title", "x"), ("list", "--type=question"),
                     ("query", "type=question AND status=open")):
            result, seen = run_board("bd", *args)
            if result.returncode != 2 or seen or "questions are type decision" not in result.stderr:
                raise ValueError(f"board bd {args} must hint that questions are decisions: {result.stderr!r}")
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
if any(" ".join(args).startswith(prefix) for prefix in config.get("fail", [])):
    print("board: simulated failure", file=sys.stderr)
    sys.exit(1)
if args[:1] == ["health"]:
    print(json.dumps(config["health"]))
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
elif args[:2] == ["bd", "create"]:
    print(json.dumps({"id": "fx-new1"}))
elif args[:1] == ["revise"]:
    print("fx-rev1")
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
                 "rulingsHold": "true: no released ruling touched"}
# The round's title and summary every Stage report carries.
ROUND_INFO = {"round": {"title": "Cache policy", "summary": "Which cache the service keeps, and why now."}}

CONSOLE_CONTRACT = Path("claude") / "mods" / "console" / "tests" / "engine-contract.ts"


def console_contract_states(root: Path) -> dict:
    """The real engine's `show --json` in seven states (no round, check, batch out, answered, a closed round with a release next, a release, a stopped release), timestamps normalized:
    the console's tests parse exactly these, so a shape change on either side fails a test."""
    states = {}
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "AGENT_SESSION_STATE_DIR": tmp, "CODEX_THREAD_ID": "", "CODEX_SESSION_ID": ""}

        def run(*args, stdin=None, cwd=tmp):
            if args[:1] == ("step",) and isinstance(stdin, dict) and stdin.get("pass"):  # the model's Skill call, recorded by the console
                waiting = json.loads(run("show", "--json", cwd=cwd)).get("pending") or {}  # the run carries the pending pass's arguments
                run("pass", "--origin", "model", stdin={"command": stdin["pass"], "args": waiting.get("args", "") if waiting.get("command") == stdin["pass"] else "",
                                                       "pending": None}, cwd=cwd)
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
        run("step", stdin={**ROUND_INFO, "questions": [{"text": "Which cache?", "title": "Cache", "header": "Cache", "for": "pt1", "options": [
            {"label": "Keep", "description": "keep it"}, {"label": "Drop", "description": "drop it"}],
            "recommendation": "Keep", "strength": "lean", "leanBecause": {"cause": "preference", "detail": "taste"}}]})
        states["check"] = show()
        while show()["pending"] is not None:  # the path pass, Base, the refine pair, the lean pass, challenge-rulings
            run("step", stdin={"pass": show()["pending"]["command"], "updates": [], "checked": ["every question"]})
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
            rid: {"status": "decided", "issue_type": "decision", "title": title} for rid, title in (("fx-a", "Cache store"), ("fx-b", "Cache size"))}}))
        run("start", "round", cwd=repo)
        run("step", stdin={"classes": {"fx-q": "user"}}, cwd=repo)
        run("step", stdin={"select": ["fx-q"]}, cwd=repo)
        run("step", stdin={**ROUND_INFO, "questions": [{"text": "Which store?", "title": "Store", "header": "Store", "board": "fx-q", "options": [
            {"label": "Keep", "description": "keep it"}, {"label": "Drop", "description": "drop it"}],
            "recommendation": "Keep", "strength": "lean", "leanBecause": {"cause": "preference", "detail": "taste"}}]}, cwd=repo)
        while json.loads(run("show", "--json", cwd=repo))["pending"] is not None:
            run("step", stdin={"pass": json.loads(run("show", "--json", cwd=repo))["pending"]["command"], "updates": [], "checked": ["every question"]}, cwd=repo)
        board_round = json.loads(run("show", "--json", cwd=repo))
        run("answer", "--origin", "dialog", stdin={"marker": board_round["batch"]["marker"], "answers": {"Which store?": "Keep"}}, cwd=repo)
        run("step", stdin={"records": {board_round["questions"][0]["id"]: {"rationale": "R.", "ruleOwner": "docs/x.md"}}}, cwd=repo)
        states["closed"] = show(cwd=repo)
        run("start", "release", "fx-a", "fx-b", cwd=repo)
        run("step", stdin={"records": {"fx-a": "unchanged", "fx-b": {"change": "size moved", "reach": "contained", "why": "only fx-b"}}},
            cwd=repo)
        states["release"] = show(cwd=repo)
        run("abandon", cwd=repo)
        run("start", "release", "fx-a", cwd=repo)
        run("step", stdin={"records": {"fx-a": {"change": "the store moved", "reach": "spreads"}}}, cwd=repo)
        states["stopped"] = show(cwd=repo)
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
    sets = [*engine.PATH_LENSES, *engine.REFINE_LENSES["step-back"]]
    if len(sets) != len(set(sets)) or not set(sets) <= set(engine.ALL_LENSES["step-back"]) \
            or tuple(engine.REFINE_LENSES["ground"]) != tuple(engine.ALL_LENSES["ground"]) \
            or not set(engine.LEAN_LENSES) <= set(engine.ALL_LENSES["ground"]):
        problems.append("the engine's path, refine and lean sets must be disjoint lenses the skills own (refine ground = every ground lens)")
    return problems


def validate_lens_names(root: Path) -> None:
    """bin/protocol ALL_LENSES, skills/step-back and skills/ground (the owners) and the console's words.ts list the same lenses."""
    loader = importlib.machinery.SourceFileLoader("protocol_lenses", str(root / "bin" / "protocol"))
    engine = importlib.util.module_from_spec(importlib.util.spec_from_loader("protocol_lenses", loader))
    loader.exec_module(engine)
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
    engine = (root / "bin" / "protocol").read_text(encoding="utf-8")
    criteria = re.findall(r"^    '(\w+)': '", engine.split("STRONG_CRITERIA = {", 1)[1].split("}", 1)[0], re.M)
    causes = re.findall(r"'(\w+)'", engine.split("LEAN_CAUSES = (", 1)[1].split(")", 1)[0])
    named = re.findall(r"`(\w+)`", section)
    if not criteria or [name for name in named if name in criteria] != criteria or not all(cause in named for cause in causes):
        raise ValueError(f"decision-protocol Recommendation strength names {named}; the engine enforces {criteria} and causes {causes}")
    flat = " ".join(section.split())
    if "listed or not" not in flat or "strongest unlisted" not in flat or "listed or not" not in engine or "strongest unlisted" not in engine:
        raise ValueError("alternativesFail covers every realistic option, listed or not, and names the strongest unlisted one (engine and decision-protocol.md)")


def validate_console_programs(root: Path) -> None:
    """The console runs ~/.agents/bin programs either directly (their bin/ file must be executable) or through bash;
    its test kit has no processes, so only this check sees a missing execute bit. Reads the agents tree alone: the
    build checks a store copy without agents.nix beside it, so a name maps to the bin/ file it is linked from by stem."""
    calls = []
    for source in (root / "claude" / "mods" / "console" / "hooks").glob("*.ts*"):
        text = source.read_text(encoding="utf-8")
        calls += [(source.name, "direct", name) for name in re.findall(r"process\.run\(\[binary\([^,]+, '([\w-]+)'\)", text)]
        calls += [(source.name, "bash", name) for name in re.findall(r"process\.run\(\['bash', binary\([^,]+, '([\w-]+)'\)", text)]
    if not calls:
        raise ValueError("console: found no ~/.agents/bin calls; the pattern for validate_console_programs no longer matches")
    for file, how, name in calls:
        targets = [path for path in (root / "bin").iterdir() if path.name == name or path.name.split(".")[0] == name]
        if len(targets) != 1:
            raise ValueError(f"console {file} runs ~/.agents/bin/{name}, which matches {len(targets)} files in bin/")
        if how == "direct" and not os.access(targets[0], os.X_OK):
            raise ValueError(f"console {file} runs {name} directly, but bin/{targets[0].name} is not executable: run it through bash")


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


def validate_protocol(root: Path) -> None:
    """bin/protocol, the round engine, against a fake board CLI (PROTOCOL_BOARD) and once through the real board.py
    with a fake bd; every origin rule of the contract rulings."""
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
        registry = root / "bin" / "session-lead-mode.sh"
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

        loader = importlib.machinery.SourceFileLoader("protocol_engine", str(engine))
        engine_module = importlib.util.module_from_spec(importlib.util.spec_from_loader("protocol_engine", loader))
        loader.exec_module(engine_module)

        def proto(*args, stdin=None, cwd=plain, session="0000-lead0001", ok=True, env=None, process=False, observe=True):
            """The engine's `run_cli` in this process; `process=True` runs the real executable (the end-to-end path).
            A Claude session's pass report needs an observed run of its pass (the model's Skill call, which the console
            records as `pass --origin model`): unless `observe=False`, a report without one is preceded by it."""
            if observe and args[:1] == ("step",) and isinstance(stdin, dict) and stdin.get("pass") and session != "0000-cdx00001":
                saved = state / f"{session}.protocol" / "state.json"
                current = (json.loads(saved.read_text(encoding="utf-8")).get("round") or {}) if saved.is_file() else {}
                seen = current.get("observed") or {}
                waiting = current.get("pending") or {}
                if stdin["pass"] not in seen:  # the run is the pending pass with its arguments, like the console's
                    args_run = waiting.get("args", "") if waiting.get("command") == stdin["pass"] else ""
                    proto("pass", "--origin", "model", stdin={"command": stdin["pass"], "args": args_run, "pending": None}, cwd=cwd,
                          session=session, ok=None, env=env, process=process, observe=False)
            argv = [*(["--session", session] if session else []), *args]
            text = json.dumps(stdin) if isinstance(stdin, dict) else (stdin or "")
            if process:
                result = subprocess.run([sys.executable, "-B", str(engine), *argv], input=text, text=True,
                                        capture_output=True, cwd=cwd, env={**base, **(env or {})})
            else:
                code, out, err = engine_module.run_cli(argv, {**base, **(env or {})}, Path(cwd), text)
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
            return {"text": text, "title": text.rstrip("?"), "header": "Q", "options": [
                {"label": "Keep", "description": "keep it"}, {"label": "Drop", "description": "drop it"}],
                "recommendation": "Keep", "strength": "lean", "leanBecause": {"cause": "preference", "detail": "taste"}, **extra}

        def converge(**kwargs):
            """Every pending pass without changes (the path pass, a Base cycle, the refine pair, the lean pass, challenge-rulings) before the batch."""
            out = ""
            for _ in range(12):
                view = json.loads(proto("show", "--json", **kwargs).stdout)
                if view["step"] != "check" or not view["pending"] or view["batch"]:
                    break
                out = proto("step", stdin={"pass": view["pending"]["command"], "updates": [], "checked": ["every question"]}, **kwargs).stdout
            return out

        configure()
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
        notes = state / "notes"
        out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Which cache?"]}).stdout
        if "Round r1 · Collect" not in out or "pt1 [pasted]: Which cache?" not in out:
            raise ValueError(f"protocol start: {out}")
        refused("start", "round", needle="round r1 is open")
        if "Unclassified pasted points: pt1." not in proto("show").stdout:
            raise ValueError("protocol show at Collect must list the unclassified points")
        refused("step", stdin={"classes": {}}, needle="unclassified: pt1")
        refused("step", stdin={"classes": {"pt1": "ruled"}}, needle="cites its owner")
        proto("step", stdin={"classes": {"pt1": "user"}})
        proto("step", stdin={"select": ["pt1"]})
        refused("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", header="Much too long")]}, needle="longer than 12")
        refused("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", options=[{"label": "Only", "description": ""}])]},
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
        refused("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", strength="strong", **{"for": "pt1"})]},
                needle="strong is a claim: `strongBecause.noAssumptions`")
        refused("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", strength="strong", strongBecause={
            **STRONG_CLAIMS, "notPreference": "does-not-apply: x"}, **{"for": "pt1"})]}, needle="`strongBecause.notPreference` is \"true: …\"")
        refused("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", title="x" * 61, **{"for": "pt1"})]},
                needle="longer than 60")
        out = proto("step", stdin={**ROUND_INFO, "questions": [question("Which cache?", **{"for": "pt1"})]}).stdout
        if (shown()["title"], shown()["summary"]) != ("Cache policy", "Which cache the service keeps, and why now."):
            raise ValueError(f"protocol show --json must carry the round title and summary: {shown()}")
        first = shown()
        if first["step"] != "check" or (first["pending"]["command"], first["pending"]["args"]) != ("step-back", "goal foundations") \
                or first["check"]["cycle"] != 1 \
                or first["questions"][0]["status"] != "draft" or first["questions"][0]["overlaps"] != []:
            raise ValueError(f"protocol stage → check: {first}")
        body = out.split("\n", 1)[1]
        if "Don't run or report the next pass in this turn: the console starts it as its own turn. Finish any other work for the user, then end the turn without a closing status line." not in out or "model-reported" in out \
                or "step-back" in body.replace("report_hint", "").split("After the pass")[0] \
                or "Check cycle 1/5 (the round's path pass: goal and foundations, before the drafts settle" not in out \
                or "path pass, cycle 1/5" not in out.splitlines()[0]:
            raise ValueError(f"protocol Claude check output (hand-off names no pass, cycle cap 5): {out}")
        if "After the pass, report each change" not in out or '"pass": "step-back"' not in out:
            raise ValueError(f"protocol: the first pass of a round carries the report format: {out}")
        # pass: origins enforced; the pending pass stays until its report, which then counts the observed origin.
        refused("pass", "--origin", "dialog", stdin={"command": "step-back"}, needle="origin 'dialog' is not accepted")
        pending = first["pending"]["id"]
        after = json.loads(proto("pass", "--origin", "plugin", stdin={"command": "step-back", "args": "goal foundations", "pending": pending}).stdout)
        if after["pending"] != first["pending"] or after["note"] is not None:
            raise ValueError(f"protocol pass must keep the pending pass until its report: {after}")
        # A pass that changes nothing names what it checked; the refusal lands in the history and the pane's log.
        refused("step", stdin={"pass": "step-back", "updates": []}, needle="names what it checked")
        if not any(line["text"].startswith("refused step: a step-back pass that changes nothing") for line in shown()["log"]):
            raise ValueError(f"protocol log must show the refused call: {shown()['log']}")
        # An extra pass (asked for in chat) without changes leaves the sequence alone.
        proto("step", stdin={"pass": "ground", "updates": [], "checked": ["every question"]})
        if shown()["pending"]["command"] != "step-back":
            raise ValueError(f"protocol: an extra pass without changes must keep the expected pass: {shown()['pending']}")
        # The path pass first (once per round), then the Base loop.
        proto("step", stdin={"pass": "step-back", "updates": [], "checked": ["every question"]})
        if (shown()["pending"]["command"], shown()["pending"]["args"], shown()["check"]["cycle"]) != ("step-back", "", 1):
            raise ValueError(f"protocol: the path pass is followed by the Base loop in cycle 1: {shown()['pending']}")
        proto("step", stdin={"pass": "step-back", "updates": [], "checked": ["every question"]})
        ground_pending = shown()["pending"]["id"]
        proto("step", stdin={"pass": "ground", "updates": [], "checked": ["every question"]})
        # The Base loop converged: the refine pair (round-wide), then the lean pass (a preference lean counts), once each.
        for command, args in (("step-back", "decisions clean overfit mechanics"),
                              ("ground", "assumptions board sources probe"), ("ground", "assumptions sources probe q1")):
            if (shown()["pending"]["command"], shown()["pending"]["args"]) != (command, args):
                raise ValueError(f"protocol must run {command} {args} before challenge-rulings: {shown()['pending']}")
            out = proto("step", stdin={"pass": command, "updates": [], "checked": ["every question"]}).stdout
        # Every round runs challenge-rulings last before its first batch (user, 2026-10-31).
        if shown()["pending"]["command"] != "challenge-rulings" or "next: challenge-rulings, last before asking" not in out \
                or "After the pass" in out or "Report with `protocol step`" in out:
            raise ValueError(f"protocol must run challenge-rulings before the first batch:\n{out}")
        out = proto("step", stdin={"pass": "challenge-rulings", "updates": [], "checked": ["every question"]}).stdout
        asked = shown()
        if asked["check"]["last"] != {"step-back": {"changes": 0, "origin": "model"}, "ground": {"changes": 0, "origin": "model"},
                                      "challenge-rulings": {"changes": 0, "origin": "model"}} \
                or asked["step"] != "ask" or asked["batch"]["marker"] != "round:r1:1" or asked["pending"] is not None \
                or asked["batch"]["questions"] != [{"question": "Which cache?", "header": "Q", "options": [
                    {"label": "Keep (recommended, lean)", "description": "Your call: taste — keep it"}, {"label": "Drop", "description": "drop it"}],
                    "multiSelect": False}]:
            raise ValueError(f"protocol ask: {asked}")
        if '"metadata": {"source": "round:r1:1"}' not in out or "Never pass a person origin" not in out or "model-reported" in out:
            raise ValueError(f"protocol Claude ask output: {out}")
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
        if result["step"] != "record" or result["questions"][0]["answer"] != "Keep" or "Record" not in result["note"] \
                or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", result["questions"][0]["answeredAt"] or ""):
            raise ValueError(f"protocol answer: {result}")
        refused("answer", "--origin", "dialog", stdin=answers, needle="no batch is out")
        refused("step", stdin={"records": {}}, needle="records missing for q1")
        out = proto("step", stdin={"records": {"q1": {"rationale": "Simpler.", "ruleOwner": "docs/cache.md#cache"}}}).stdout
        record = (notes / "r1-q1.md").read_text(encoding="utf-8")
        if "Round r1 closed." not in out or "No board here" not in out or calls() \
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
        changing_cycles(range(1, 6))
        capped = shown()
        if capped["check"]["cycle"] != 5 or capped["pending"] is not None or capped["batch"]["marker"] != "round:r2:1" \
                or [o["label"] for o in capped["batch"]["questions"][0]["options"]] != ["Continue", "Ask now", "Pause"]:
            raise ValueError(f"protocol cap batch: {capped}")
        # The cap decision comes from the dialog only; a chat answer goes to a question that is out or ready.
        refused("answer", "--origin", "chat", stdin={"question": "q2", "answer": "Ask now", "quote": "ask now"},
                needle="q2 is draft, not ready or asked")
        cap_text = capped["batch"]["questions"][0]["question"]
        proto("answer", "--origin", "dialog", stdin={"marker": "round:r2:1", "answers": {cap_text: "Continue"}})
        resumed = shown()
        if resumed["check"]["cap"] != 10 or resumed["check"]["cycle"] != 6 or resumed["pending"]["command"] != "step-back":
            raise ValueError(f"protocol cap Continue: {resumed}")
        changing_cycles(range(6, 11))
        proto("decline", "--origin", "dialog", stdin={"marker": "round:r2:2", "partial": None})
        refused("step", stdin={"pass": "step-back", "updates": [], "checked": ["every question"]}, needle="paused")
        proto("resume")
        changing_cycles(range(11, 16))
        third = shown()
        if third["batch"]["marker"] != "round:r2:3" or third["check"]["cap"] != 15:
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
        out = proto("restart", "q2", "--reason", "criterion: only reversible caches").stdout
        restarted = shown()
        if restarted["step"] != "check" or restarted["questions"][0]["status"] != "draft" or restarted["questions"][0]["answer"] \
                or restarted["check"]["cycle"] != 1 or restarted["pending"]["command"] != "step-back" or "Check cycle 1/5" not in out:
            raise ValueError(f"protocol restart: {restarted}")
        history = proto("history").stdout
        if "0000-lead0001 r2:" not in history or "restarts q2 (criterion: only reversible caches)" not in history \
                or "cap Continue, Ask now" not in history or "declines 2" not in history \
                or "0000-lead0001 r1: passes model 7, plugin 1" not in history:
            raise ValueError(f"protocol history:\n{history}")
        line = proto("status", "--line").stdout.strip()
        if not line.startswith("protocol: round r2 · check 1/5 · pending /step-back (p") or "1 draft" not in line:
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
                or out.index("fx-d [decided]") > out.index("fx-a [questions]") or "fx-m [readyMilestone]" not in out:
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
        configure(related={"Pasted": ["fx-old", "fx-rel"]})
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
                or [c["args"][:4] for c in calls()] != [["related", "--like", "-", "--json"]]:
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
        proto("step", cwd=repo, stdin={"pass": "step-back", "updates": [{"id": "q3", "premises": "grounded in docs/a.md"}]})
        proto("step", cwd=repo, stdin={"pass": "ground", "updates": [], "checked": ["every question"]})
        # A draft a pass adds is searched before asking, and its hits need outcomes.
        proto("step", cwd=repo, stdin={"pass": "step-back", "updates": [question("Pasted extra?", **{"for": "pt3"})]})
        proto("step", cwd=repo, stdin={"pass": "ground", "updates": [], "checked": ["every question"]})
        for cycle in (4, 5):  # the cap is 5 cycles
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
        # A change by challenge-rulings loops again; at cycle 5 that is the cap; "Ask now" then asks (it ran already).
        proto("step", cwd=repo, stdin={"pass": "challenge-rulings", "updates": [{"id": added["id"], "remove": True,
                                                                                "reason": "merged into the point"}]})
        cap = shown(cwd=repo)["batch"]
        if cap["marker"] != "round:r3:1" or cap["questions"][0]["header"] != "Check cap":
            raise ValueError(f"a challenge change at the last cycle must reach the cap: {cap}")
        proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": "round:r3:1", "answers": {cap["questions"][0]["question"]: "Ask now"}})
        batch = shown(cwd=repo)["batch"]
        if batch["marker"] != "round:r3:2" or [q["question"] for q in batch["questions"]] != ["1. A?", "2. Pasted point?"]:
            raise ValueError(f"protocol batch must leave held questions out: {batch}")
        result = json.loads(proto("answer", "--origin", "dialog", cwd=repo, stdin={
            "marker": "round:r3:2", "answers": {"1. A?": "Keep"}, "annotations": {}, "response": "And mind the tenancy."}).stdout)
        if "And mind the tenancy." not in result["note"] or "not assigned" not in result["note"] \
                or result["batch"]["marker"] != "round:r3:3" or [q["question"] for q in result["batch"]["questions"]] != ["Pasted point?"]:
            raise ValueError(f"protocol answer with a response: {result}")
        declined = json.loads(proto("decline", "--origin", "dialog", cwd=repo,
                                    stdin={"marker": "round:r3:3", "partial": {"Pasted point?": "Keep"}}).stdout)
        if declined["batch"] is not None or draft_q["id"] not in [q["id"] for q in declined["questions"] if q["status"] == "ready"] \
                or "'Pasted point?': 'Keep'" not in declined["note"]:
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
        recording = json.loads(proto("answer", "--origin", "chat", stdin=chat, cwd=repo).stdout)
        if recording["step"] != "record" or next(q for q in recording["questions"] if q["id"] == draft_q["id"])["answer"] != "Keep":
            raise ValueError(f"protocol chat answer: {recording}")
        calls()
        out = proto("step", cwd=repo, stdin={"records": {
            "q3": {"rationale": "A rationale.", "ruleOwner": "docs/a.md#a"},
            draft_q["id"]: {"rationale": "P rationale.", "ruleOwner": "docs/p.md#p", "decision": "Keep the point."}}}).stdout
        board_calls = calls()
        records = Path(str(log) + ".records").read_text(encoding="utf-8")
        expected = [["claim", "fx-a"], ["record", "fx-a"], ["revise", "fx-old", "--title", "Pasted point", "--body-file"],
                    ["bd", "batch", "-m", "protocol: relate fx-rev1", "--json"], ["claim", "fx-rev1"], ["record", "fx-rev1"],
                    ["unclaim", "fx-b"], ["health", "--json"]]  # the held q4's item is released; the next round claims it
        if [c["args"][:len(want)] for c, want in zip(board_calls, expected)] != expected or len(board_calls) != len(expected) \
                or board_calls[3]["stdin"] != "dep add fx-rev1 fx-rel relates-to\n" \
                or 'User (chat), ' not in records or '"keep   it,\nfinal"' not in records or "## Decision\nKeep the point." not in records \
                or "Board: 3 open questions, 1 decided awaiting release, 2 released to plan, 0 in review, 1 waiting on the user." not in out \
                or "Held for a later round: q4." not in out:
            raise ValueError(f"protocol board Record: {board_calls}\n{out}\n{records}")
        # A held question whose item another session closed is dropped at the next start (the board owns it).
        session_dir = state / "0000-lead0001.protocol"
        saved = {name: (session_dir / name).read_text() for name in ("state.json", "history.jsonl")}
        configure(statuses={"fx-b": "closed"})
        out = proto("start", "round", cwd=repo).stdout
        if "Dropped held questions no longer open on the board: q4 fx-b (closed)." not in out \
                or not re.match(r"r\d+ · round started · dropped q4 \(no longer open on the board\)", out) \
                or json.loads((session_dir / "state.json").read_text())["carried"]:
            raise ValueError(f"protocol must drop a carried question the board closed:\n{out}")
        for name, text in saved.items():
            (session_dir / name).write_text(text)
        # The held decision is offered once its premise is answered; selecting it claims its item.
        configure()
        proto("start", "round", cwd=repo)
        out = proto("step", stdin={"classes": {}}, cwd=repo).stdout
        if "- q4 p9 (held): B" not in out:
            raise ValueError(f"protocol must offer the held decision:\n{out}")
        calls()
        proto("step", stdin={"select": ["q4"]}, cwd=repo)
        proto("step", stdin={**ROUND_INFO, "questions": []}, cwd=repo)
        held_round = shown(cwd=repo)
        if [c["args"] for c in calls()] != [["claim", "fx-b"]] or held_round["step"] != "check" \
                or [(q["id"], q["status"]) for q in held_round["questions"]] != [("q4", "draft")]:
            raise ValueError(f"protocol held decision in the next round: {held_round}")
        proto("abandon", cwd=repo)

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
        proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": "round:r5:1", "answers": {"Retry point?": "Keep"}})
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
                or "Round r5 closed." not in out or shown(cwd=repo)["round"] is not None:
            raise ValueError(f"protocol Record rerun: {made}\n{out}")
        configure()

        # F: evidence leans get one focused ground pass before challenge-rulings; a lean left unverified is flagged.
        out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Order?", "Batch?"]}, cwd=repo).stdout
        points = re.findall(r"(pt\d+) \[pasted\]", out)
        proto("step", stdin={"classes": {point: "user" for point in points}}, cwd=repo)
        proto("step", stdin={"select": points}, cwd=repo)
        evidence = {"cause": "evidence", "detail": "bd batch order"}
        proto("step", cwd=repo, stdin={**ROUND_INFO, "questions": [
            question("Order?", leanBecause=evidence, **{"for": points[0]}), question("Batch?", leanBecause=evidence, **{"for": points[1]})]})
        for command in ("step-back", "step-back", "ground"):  # the path pass, then one Base cycle
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
        if focused["pending"]["command"] != "ground" or focused["pending"]["args"] != f"assumptions sources probe {ids[0]} {ids[1]}":
            raise ValueError(f"protocol must run one focused ground pass on evidence leans: {focused['pending']}")
        proto("step", stdin={"pass": "ground", "updates": [{"id": ids[0], "strength": "strong", "leanBecause": None, "strongBecause": STRONG_CLAIMS}],
                             "checked": ["bd batch order (probe)"]}, cwd=repo)
        if shown(cwd=repo)["pending"]["command"] != "challenge-rulings":
            raise ValueError("protocol: the focused pass runs once, then challenge-rulings")
        proto("step", stdin={"pass": "challenge-rulings", "updates": [], "checked": ["every question"]}, cwd=repo)
        descriptions = [q["options"][0]["description"] for q in shown(cwd=repo)["batch"]["questions"]]
        if descriptions != ["keep it", "Unverified: bd batch order — keep it"]:
            raise ValueError(f"protocol dialog marks after the focused pass: {descriptions}")
        # An extra pass while the batch is out (before answers) withdraws it. Strength is presentation: the batch goes
        # out again at once; a substantive change (premises) reruns the loop first.
        out_marker = shown(cwd=repo)["batch"]["marker"]
        proto("step", stdin={"pass": "ground", "updates": [{"id": ids[1], "strength": "strong", "leanBecause": None,
                                                              "strongBecause": STRONG_CLAIMS}], "checked": ["bd batch order"]}, cwd=repo)
        reissued = shown(cwd=repo)["batch"]
        if reissued is None or reissued["marker"] == out_marker or shown(cwd=repo)["step"] != "ask":
            raise ValueError(f"protocol: a presentation-only pass must re-issue the batch without a loop: {shown(cwd=repo)}")
        proto("step", stdin={"pass": "ground", "updates": [{"id": ids[1], "premises": "bd batch keeps order (probe)"}]}, cwd=repo)
        if shown(cwd=repo)["pending"]["command"] != "step-back":
            raise ValueError("protocol: a substantive change with a batch out must rerun the loop")
        issued = converge(cwd=repo).splitlines()[0]
        if not re.fullmatch(r"r\d+ · .*asked q\d+, q\d+ · next: your answers \(batch \d+\)", issued):
            raise ValueError(f"protocol output must open with the call's events and the next step: {issued!r}")
        reissued = shown(cwd=repo)["batch"]
        if reissued["marker"] == out_marker or [q["options"][0]["description"] for q in reissued["questions"]] != ["keep it"] * 2:
            raise ValueError(f"protocol must issue the updated batch anew: {reissued}")
        # Updates apply one by one: a valid title edit applies while an invalid strong claim is set aside with its reason.
        headline = proto("step", stdin={"pass": "ground", "checked": ["titles"], "updates": [
            {"id": ids[0], "title": "Does bd batch keep order"}, {"id": ids[1], "strength": "strong", "strongBecause": {}}]},
            cwd=repo).stdout.splitlines()[0]
        if not re.fullmatch(rf"r\d+ · (.* · )?ground: {ids[0]} changed, 1 not applied · .*next: .+", headline):
            raise ValueError(f"protocol headline must name the changed and the not applied updates: {headline!r}")
        partial = shown(cwd=repo)
        titles = {q["id"]: q["title"] for q in partial["questions"]}
        if titles[ids[0]] != "Does bd batch keep order" or not any(line["text"].startswith("ground") for line in partial["log"]):
            raise ValueError(f"protocol must apply the valid update of a partly invalid report: {partial}")
        refused("step", stdin={"pass": "ground", "checked": ["x"], "updates": [{"id": ids[1], "strength": "strong", "strongBecause": {}}]},
                needle="no update applied", cwd=repo)
        # A refused call leaves only its refusal in the history: no event of the work it did not save.
        tail = [json.loads(line)["event"] for line in (state / "0000-lead0001.protocol" / "history.jsonl").read_text().splitlines()][-2:]
        if tail[-1] != "refused" or "batch-withdrawn" in tail:
            raise ValueError(f"protocol history must not keep events of a failed call: {tail}")
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

        # R: a release run (r3-q7, r4-q12..q19): the default set from the last closed round, refusals, a contained
        # drop that lapses the typed approval into a dialog, owner checks, a resumable release, spreads, Codex.
        def patch_config(**changes):
            config.write_text(json.dumps({**json.loads(config.read_text(encoding="utf-8")), **changes}), encoding="utf-8")

        docs = repo / "docs"
        docs.mkdir(exist_ok=True)
        (docs / "x.md").write_text("# X\n\n## Approved dependencies, settlement and retry — implementation pending\n\n"
                                   "```\n## Not a heading\n```\n<a id=\"explicit-one\"></a>\n", encoding="utf-8")
        (docs / "y.md").write_text("# Y\n", encoding="utf-8")
        anchor = "approved-dependencies-settlement-and-retry--implementation-pending"
        # A no-board last round gives no default set; a cwd without a board refuses a release outright.
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
        refused("start", "release", needle="recorded no board records; name the ids", cwd=repo)
        # A board round recording two records closes naming the release (r4-q15); nothing starts by itself.
        configure(health={"counts": counts, "items": {"questions": [
            {"id": "fx-r1", "status": "open", "type": "decision", "title": "R1?", "priority": 1, "blockedBy": []},
            {"id": "fx-r2", "status": "open", "type": "decision", "title": "R2?", "priority": 1, "blockedBy": []}]}})
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
                or shown(cwd=repo)["round"] is not None or shown(cwd=repo)["next"] != {"release": {"round": round_id, "count": 2}}:
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
        if started["protocol"] != "release" or started["step"] != "recheck" or started["title"] != f"{round_id}'s records" \
                or [r["id"] for r in started["records"]] != ["fx-r1", "fx-r2"] \
                or not started["note"].startswith(f"r{int(round_id[1:]) + 2} release · {round_id}'s records · release started") \
                or ["claim", "fx-r1", "fx-r2"] in [c["args"] for c in calls()]:
            raise ValueError(f"a typed /release-round must start the default release and stamp it: {started}")
        refused("step", stdin={"records": {"fx-r1": "unchanged"}}, needle="no line for fx-r2", cwd=repo)
        refused("step", stdin={"records": {"fx-r1": "unchanged", "fx-r2": {"change": "c", "reach": "unsure"}}},
                needle="unsure is spreads", cwd=repo)
        refused("step", stdin={"records": {"fx-r1": "unchanged", "fx-r2": {"change": "c", "reach": "contained"}}},
                needle="names `why`", cwd=repo)
        # Contained: fx-r2 leaves the set, the rest continue; the stamp lapses with the changed set.
        proto("step", stdin={"records": {"fx-r1": "unchanged", "fx-r2": {"change": "the store moved", "reach": "contained",
                                                                       "why": "no other record reads the store"}}}, cwd=repo)
        nones = {name: "none" for name in ("revises", "answers", "premise", "assumes", "deferred", "held", "doc")}
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
        refused("step", stdin={"rulings": [{"record": "fx-r1", "ruling": "x", "sure": True}]}, needle="needs alternative", cwd=repo)
        proto("step", stdin={"rulings": [{"record": "fx-r1", "ruling": "bundled", "alternative": "split", "fails": "nothing",
                                          "evidence": "decide.md", "sure": True}]}, cwd=repo)
        dialog = shown(cwd=repo)
        records = {r["id"]: r["state"] for r in dialog["records"]}
        if dialog["step"] != "ask" or dialog["batch"] is None or dialog["batch"]["questions"][0]["header"] != "Release" \
                or dialog["batch"]["questions"][0]["question"] != "Release r10's 1 record?" \
                or "left the set: fx-r2" in json.dumps(dialog["batch"]) or records != {"fx-r1": "set", "fx-r2": "dropped"} \
                or "left the set: fx-r2" not in proto("show", cwd=repo).stdout \
                or not any("approval asked: left the set: fx-r2" in line["text"] for line in dialog["log"]):
            raise ValueError(f"a dropped record must lapse the typed approval into the dialog: {dialog}")
        result = json.loads(proto("answer", "--origin", "dialog", cwd=repo, stdin={
            "marker": dialog["batch"]["marker"], "answers": {dialog["batch"]["questions"][0]["question"]: "Release (recommended, lean)"}}).stdout)
        if result["step"] != "owners":
            raise ValueError(f"the dialog approval must lead to Owner writes: {result}")
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
                or not re.match(r"r\d+ release · r\d+'s records · .*superseded fx-old by fx-r1 · released fx-r1", out) \
                or "- released fx-r1: R1" not in out or "- closed fx-q1: answered by released fx-r1" not in out \
                or "- superseded fx-old by fx-r1 (rule: Rule 2)" not in out or "- dropped fx-r2" not in out \
                or "decide.md Release 7" not in out or shown(cwd=repo)["round"] is not None \
                or "board release" in out.splitlines()[0]:
            raise ValueError(f"protocol release rerun: {made}\n{out}")
        # The default set is used up: a bare /release-round must not offer the dropped fx-r2 again (it goes to a round).
        refused("pass", "--origin", "composer", stdin={"command": "release-round", "args": "", "pending": None},
                needle="went through release", cwd=repo)
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
                            "fx-s2": {"status": "decided", "issue_type": "decision", "title": "S2", "assignee": "lead0001"}},
                     health={"counts": counts, "items": {"decided": [{"id": "fx-s2", "blockedBy": ["fx-open"]}]}})
        proto("start", "release", "fx-s1", "fx-s2", cwd=repo)
        proto("step", stdin={"records": {"fx-s1": "unchanged", "fx-s2": "unchanged"}}, cwd=repo)
        proto("step", stdin={"checks": {"fx-s1": nones, "fx-s2": nones}}, cwd=repo)
        if {r["id"]: (r["state"], r["reason"]) for r in shown(cwd=repo)["records"]}["fx-s2"] != ("dropped", "waits on open fx-open"):
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
        # Leading ids after the command name the set; the rest stays the skill's focus.
        named = json.loads(proto("pass", "--origin", "bridge", stdin={"command": "release-round", "args": "fx-s1 check the docs", "pending": None},
                                 cwd=repo).stdout)
        if [r["id"] for r in named["records"]] != ["fx-s1"] or named["title"] != "fx-s1":
            raise ValueError(f"/release-round <ids> must release those ids: {named}")
        proto("abandon", cwd=repo)
        proto("start", "round", "--no-board", str(notes), stdin={"points": ["Busy?"]}, cwd=repo)
        refused("pass", "--origin", "composer", stdin={"command": "release-round"}, needle="the release starts once it closes", cwd=repo)
        proto("abandon", cwd=repo)
        configure()

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
            "annotations": {"2. Picked?": {"notes": "but log it"}}}).stdout)
        typed = next(q for q in result["questions"] if q["text"] == "Typed?")
        if typed["status"] != "ready" or typed["answer"] is not None or result["batch"] is not None \
                or '"explain this" instead of picking' not in result["note"] or 'with the note "but log it"' not in result["note"] \
                or not result["note"].startswith(f"{result['round']} · answered q") or "; typed " + typed["id"] not in result["note"]:
            raise ValueError(f"protocol must hold a typed dialog answer for the model and pass on a pick's note: {result}")
        proto("step", stdin={}, cwd=repo)
        again = shown(cwd=repo)["batch"]
        if again is None or [q["question"] for q in again["questions"]] != ["Typed?"]:
            raise ValueError(f"protocol step must send a read typed question out again: {again}")
        proto("answer", "--origin", "dialog", cwd=repo, stdin={"marker": again["marker"], "answers": {"Typed?": "Drop, but keep the log"}})
        mapped = json.loads(proto("answer", "--origin", "chat", cwd=repo, stdin={
            "question": typed["id"], "answer": "Drop", "quote": "Drop, but keep the log"}).stdout)
        if mapped["step"] != "record" or "note: but log it" not in mapped["note"]:
            raise ValueError(f"protocol must accept the model's reading of typed text and show notes at Record: {mapped}")
        closed = proto("step", stdin={"records": {q["id"]: {"rationale": "r", "ruleOwner": "o"} for q in mapped["questions"]}},
                       cwd=repo).stdout.splitlines()[0]
        if not re.fullmatch(r"r\d+ · recorded q\d+, q\d+ · round closed", closed):
            raise ValueError(f"protocol's closing headline must name the file records: {closed!r}")

        # J: a pass that adds a question says so ("added", not "changed").
        out = proto("start", "round", "--no-board", str(notes), stdin={"points": ["Base?"]}, cwd=repo).stdout
        point = re.search(r"(pt\d+) \[pasted\]", out).group(1)
        proto("step", stdin={"classes": {point: "user"}}, cwd=repo)
        proto("step", stdin={"select": [point]}, cwd=repo)
        proto("step", stdin={**ROUND_INFO, "questions": [question("Base?", **{"for": point})]}, cwd=repo)
        added = proto("step", stdin={"pass": "step-back", "updates": [question("Extra?", **{"for": point})]}, cwd=repo)
        if not re.match(r"r\d+ · step-back: q\d+ added · next: ", added.stdout):
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
        result = json.loads(proto("answer", "--origin", "model-reported", session=None, env=codex,
                                  stdin={"marker": "round:r1:1", "answers": {"Codex?": "keep it, as I said"}}).stdout)
        if result["session"] != "0000-cdx00001" or result["step"] != "record":
            raise ValueError(f"protocol Codex answer: {result}")
        proto("step", session=None, env=codex, stdin={"records": {"q1": {"rationale": "R.", "ruleOwner": "o"}}})
        if 'User (model-reported), ' not in (notes / "r1-q1.md").read_text(encoding="utf-8"):
            raise ValueError("a Codex record must flag the answer model-reported")
        # Codex: the approval question is asked and recorded model-reported; the user's own words pick no option.
        codex_repo = {"session": None, "env": {"CODEX_THREAD_ID": "0000-cdx00001", "CODEX_SESSION_ID": "0000-cdx00001"}, "cwd": repo}
        nones = {name: "none" for name in ("revises", "answers", "premise", "assumes", "deferred", "held", "doc")}
        configure(items={"fx-s1": {"status": "decided", "issue_type": "decision", "title": "S1", "assignee": "lead0001"},
                            "fx-c1": {"status": "decided", "issue_type": "decision", "title": "C1"}})
        refused("start", "release", "fx-s1", needle="held by another live session: fx-s1 (lead0001)", **codex_repo)
        calls()
        proto("start", "release", "fx-c1", **codex_repo)
        if ["claim", "fx-c1"] not in [c["args"] for c in calls()]:
            raise ValueError("start release must claim an unheld record")
        proto("step", stdin={"records": {"fx-c1": "unchanged"}}, **codex_repo)
        proto("step", stdin={"checks": {"fx-c1": nones}}, **codex_repo)
        out = proto("step", stdin={"rulings": [{"record": "fx-c1", "ruling": "r", "alternative": "a", "fails": "f",
                                                "evidence": "e", "sure": False}]}, **codex_repo).stdout
        batch = json.loads(proto("show", "--json", **codex_repo).stdout)["batch"]
        if "protocol answer --origin model-reported" not in out or "unsure: fx-c1 r" not in out \
                or batch["questions"][0]["question"] != "Release 1 record?":
            raise ValueError(f"protocol Codex approval: {out}")
        text = batch["questions"][0]["question"]
        result = json.loads(proto("answer", "--origin", "model-reported", stdin={"marker": batch["marker"], "answers": {text: "sounds fine"}},
                                  **codex_repo).stdout)
        if result["step"] != "ask" or "needs the user's pick" not in result["note"]:
            raise ValueError(f"protocol: free words must not approve a release: {result}")
        proto("step", stdin={}, **codex_repo)
        batch = json.loads(proto("show", "--json", **codex_repo).stdout)["batch"]
        result = json.loads(proto("answer", "--origin", "model-reported", stdin={"marker": batch["marker"], "answers": {text: "Release"}},
                                  **codex_repo).stdout)
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

        # E: the real board path: board.py with a fake bd (the board fixture) gives Collect its items and Related its hits.
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
        if "fx-ovo.3 [questions] open decision: Open cache question" not in out or "fx-ovo.1 [decided]" not in out:
            raise ValueError(f"protocol Collect through board.py:\n{out}")
        proto("step", stdin={"classes": {"fx-ovo.3": "planning", "fx-ovo.1": "user", "fx-ovo.9": "planning"}}, **real_session)
        proto("step", stdin={"select": ["fx-ovo.1"]}, **real_session)
        proto("step", stdin={**ROUND_INFO, "questions": [question("Store choice?", board="fx-ovo.1"),
                                           question("Which store backs the cache?")]}, **real_session)
        overlaps = next(q for q in shown(**real_session)["questions"] if q["board"] is None)["overlaps"]
        if overlaps != [{"id": "fx-ovo.6", "title": "Design cache", "outcome": None},
                        {"id": "fx-ovo.3", "title": "Open cache question", "outcome": None}]:
            raise ValueError(f"protocol Related through board related --json: {overlaps}")

        # F: round texts: every error at once, the limits, previews, the report format once, hand-offs, the release dialog.
        texts = {"session": "0000-texts001"}
        proto("start", "round", "--no-board", str(notes), stdin={"points": ["Limits?"]}, **texts)
        proto("step", stdin={"classes": {"pt1": "user"}}, **texts)
        proto("step", stdin={"select": ["pt1"]}, **texts)
        long_round = {"round": {"title": "t" * 61, "summary": "s" * 241}}
        result = proto("step", ok=False, **texts, stdin={**long_round, "questions": [
            question("Limits?", title="x" * 61, header="Much too long", **{"for": "pt1"}),
            question("y" * 161, options=[{"label": "A", "description": "d" * 151}, {"label": "B", "description": ""}])]})
        for needle in ("round title at most 60", "round summary at most 240", "questions[0]: title", "questions[0]: header",
                       "questions[1]: text", "questions[1]: the description of option 'A' is longer than 150"):
            if needle not in result.stderr:
                raise ValueError(f"a staging refusal lists every error at once ({needle!r} missing): {result.stderr}")
        refused("step", **texts, stdin={**ROUND_INFO, "questions": [question("2. Numbered?", **{"for": "pt1"})]}, needle="carries no number")
        proto("step", **texts, stdin={**ROUND_INFO, "questions": [question("y" * 160, title="Long", options=[
            {"label": "Keep", "description": "d" * 150, "preview": "x = 1"}, {"label": "B", "description": ""}], **{"for": "pt1"})]})
        refused("step", **texts, stdin={"pass": "step-back", "updates": [question("Multi?", multiSelect=True, options=[
            {"label": "Keep", "description": "", "preview": "x"}, {"label": "B", "description": ""}])]}, needle="`preview` is for single-select")
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
        # Codex keeps its run line and gets the format with the round's first pass, as Claude does.
        codex = {"session": "0000-cdx00001"}
        point = re.search(r"(pt\d+) \[pasted\]", proto("start", "round", "--no-board", str(notes), stdin={"points": ["Codex?"]}, **codex).stdout)[1]
        proto("step", stdin={"classes": {point: "user"}}, **codex)
        proto("step", stdin={"select": [point]}, **codex)
        out = proto("step", **codex, stdin={**ROUND_INFO, "questions": [question("Codex?", **{"for": point})]}).stdout
        if "Run the step-back skill now with the argument `goal foundations` (lenses, then the questions to strengthen) (read its SKILL.md), then report the pass." not in out \
                or "After the pass, report each change" not in out or "Check cycle 1/5 (the round's path pass" not in out:
            raise ValueError(f"protocol Codex check output: {out}")
        out = proto("step", **codex, stdin={"pass": "step-back", "updates": [], "checked": ["q"]}).stdout  # the path pass
        out = proto("step", **codex, stdin={"pass": "step-back", "updates": [], "checked": ["q"]}).stdout
        if "Run the ground skill now" not in out or "After the pass" in out:
            raise ValueError(f"protocol Codex later passes carry no format: {out}")
        # Codex has no observation: it reports the scoped path pass it was told to run, with the ids in the run line.
        out = proto("step", **codex, stdin={"pass": "step-back", "updates": [], "checked": ["q"]}).stdout
        while json.loads(proto("show", "--json", **codex).stdout)["step"] == "check":
            out = proto("step", **codex, stdin={"pass": json.loads(proto("show", "--json", **codex).stdout)["pending"]["command"], "updates": [], "checked": ["q"]}).stdout
        scoped_id = json.loads(proto("show", "--json", **codex).stdout)["questions"][0]["id"]
        out = proto("restart", scoped_id, "--reason", "criterion", **codex).stdout
        if f"with the argument `goal foundations {scoped_id}`" not in out or f"the path pass on the restarted questions {scoped_id}" not in out:
            raise ValueError(f"Codex scoped path pass:\n{out}")
        out = proto("step", **codex, stdin={"pass": "step-back", "updates": [], "checked": ["q"]}).stdout
        if "path pass" in out.splitlines()[0] or "Check cycle 1/5." not in out:
            raise ValueError(f"Codex: the scoped path pass leads into the Base loop:\n{out}")
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
        refused("step", **texts, observe=False, stdin=unobserved, needle="Report with `protocol step`")
        proto("pass", "--origin", "plugin", stdin={"command": "step-back", "args": "", "pending": None}, **texts)
        partial = {"pass": "step-back", "updates": [{"id": qid, "premises": "moved"}, {"id": "q99", "premises": "x"}]}
        out = proto("step", **texts, observe=False, stdin=partial).stdout
        if "Not applied" not in out:
            raise ValueError(f"a partly applied report says what was not applied: {out}")
        proto("step", **texts, observe=False, stdin={"pass": "step-back", "updates": [{"id": qid, "premises": "moved again"}]})  # the run stayed open
        refused("step", **texts, observe=False, stdin=unobserved, needle="no /step-back ran")
        proto("abandon", **texts)
        # A question too long to ask (only a pre-limit one can be): a plain message naming the error, no automatic pass; the
        # model shortens it in a pass of its own, whose Skill call counts as the observed run.
        def long_at_ask(qid_, session_state):
            path = state / f"{texts['session']}.protocol" / "state.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["round"]["questions"][0]["text"] = "z" * 170
            path.write_text(json.dumps(data), encoding="utf-8")

        qid = texts_round("Fix?")
        long_at_ask(qid, None)
        out = converge(**texts)
        if "Not asked yet" not in out or "longer than 160" not in out or "in a pass of its own" not in out \
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
        # The check sequence per round: path pass, Base loop, refine pair, lean pass, challenge-rulings; the path pass and
        # the refine pair run once (a rebuilt check does not repeat them); a pressed pass naming their lenses counts.
        def pending_now():
            return (lambda p: (p["command"], p["args"]) if p else None)(shown(**texts)["pending"])

        def report(command="", updates=None):
            command = command or shown(**texts)["pending"]["command"]
            return proto("step", **texts, stdin={"pass": command, "updates": updates or [], "checked": ["q"]})

        qid = texts_round("Seq?")
        order = []
        while shown(**texts)["step"] == "check":
            order.append(pending_now())
            report()
        expected = [("step-back", "goal foundations"), ("step-back", ""), ("ground", ""),
                    ("step-back", "decisions clean overfit mechanics"), ("ground", "assumptions board sources probe"),
                    ("ground", f"assumptions sources probe {qid}"), ("challenge-rulings", "")]
        if order != expected:
            raise ValueError(f"the check sequence: {order}")
        # A check rebuilt while asking (a pass with changes) repeats neither the path pass nor the refine pair.
        proto("pass", "--origin", "press", stdin={"command": "ground", "args": "", "pending": None}, **texts)
        report("ground", [{"id": qid, "premises": "moved while asking"}])
        again = []
        while shown(**texts)["step"] == "check":
            again.append(pending_now())
            report()
        if again != [("step-back", ""), ("ground", ""), ("ground", f"assumptions sources probe {qid}"), ("challenge-rulings", "")]:
            raise ValueError(f"a rebuilt check repeats neither path nor refine: {again}")
        proto("abandon", **texts)
        # A pressed pass counts: All (every lens) as the path pass and the refine step-back; Refine as the refine step-back.
        qid = texts_round("Pressed?")
        proto("pass", "--origin", "press", stdin={"command": "step-back", "args": "goal decisions foundations consumer root-fix bloat gaps clean overfit mechanics the gate", "pending": None}, **texts)
        report("step-back")
        if pending_now() != ("step-back", ""):
            raise ValueError(f"a pressed All pass counts as the path pass: {pending_now()}")
        report()
        report()
        if pending_now() != ("ground", "assumptions board sources probe"):
            raise ValueError(f"a pressed All pass counts as the refine step-back pass: {pending_now()}")
        proto("abandon", **texts)
        qid = texts_round("Refined?")
        report()  # the path pass
        report()
        report()
        proto("pass", "--origin", "press", stdin={"command": "ground", "args": "assumptions board sources probe", "pending": None}, **texts)
        report("ground")  # a pressed ground All, with the refine step-back still pending
        if pending_now() != ("step-back", "decisions clean overfit mechanics"):
            raise ValueError(f"an extra pass leaves the pending refine pass: {pending_now()}")
        proto("pass", "--origin", "press", stdin={"command": "step-back", "args": "clean decisions mechanics overfit", "pending": None}, **texts)
        report("step-back", [{"id": qid, "premises": "moved by Refine"}])
        if pending_now() != ("step-back", "") or shown(**texts)["check"]["cycle"] != 2:
            raise ValueError(f"a pressed Refine counts as the refine step-back pass, and its change reruns Base: {pending_now()}")
        report()
        report()
        if pending_now() != ("ground", f"assumptions sources probe {qid}"):
            raise ValueError(f"the refine pair ran once; the lean pass follows with the fixed trio: {pending_now()}")
        proto("abandon", **texts)
        # A Base-only run reported while the path pass is pending does not count as it.
        qid = texts_round("Base only?")
        proto("pass", "--origin", "press", stdin={"command": "step-back", "args": "", "pending": None}, **texts)
        report("step-back")
        if pending_now() != ("step-back", "goal foundations"):
            raise ValueError(f"a Base run does not count as the path pass: {pending_now()}")
        proto("abandon", **texts)
        # A path pass that adds a draft goes through Related before the Base loop.
        qid = texts_round("Path adds?")
        report("step-back", [question("Added by path?", **{"for": shown(**texts)["questions"][0].get("for") or "pt1"})])
        view = shown(**texts)
        if view["step"] != "check" or pending_now() != ("step-back", "") or view["check"]["cycle"] != 1:
            raise ValueError(f"after the path pass the Base loop runs (nothing to search without a board): {view['step']} {pending_now()}")
        proto("abandon", **texts)
        # The refine pair's change reruns Base once; nothing repeats the pair.
        qid = texts_round("Pair?")
        for _ in range(3):
            report()
        report("step-back", [{"id": qid, "premises": "moved by the pair"}])
        report("ground")
        if pending_now() != ("step-back", "") or shown(**texts)["check"]["cycle"] != 2:
            raise ValueError(f"a change in the refine pair reruns the Base loop: {pending_now()}")
        report()
        report()
        if pending_now() != ("ground", f"assumptions sources probe {qid}"):
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
        if pending_now() != ("step-back", f"goal foundations {one}") or f"the path pass on the restarted questions {one}" not in out \
                or "path pass " + one not in out.splitlines()[0]:
            raise ValueError(f"a restart runs a scoped path pass first:\n{out}\n{pending_now()}")
        proto("restart", two, "--reason", "same criterion", **texts)  # a second restart before the loop settles adds its ids
        if pending_now() != ("step-back", f"goal foundations {one} {two}"):
            raise ValueError(f"a second restart adds its ids: {pending_now()}")
        report()  # the scoped path pass
        if pending_now() != ("step-back", "") or shown(**texts)["check"]["cycle"] != 1:
            raise ValueError(f"the Base loop runs round-wide after the scoped path pass: {pending_now()}")
        report()
        out = report().stdout
        if pending_now() != ("step-back", f"decisions clean overfit mechanics {one} {two}") \
                or f"the refine pass on the restarted questions {one} {two}" not in out or f"refine pass {one} {two}" not in out.splitlines()[0]:
            raise ValueError(f"the scoped refine step-back follows the Base loop:\n{out}")
        report()
        if pending_now() != ("ground", f"assumptions board sources probe {one} {two}"):
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
        # A scoped pass counts only when its argument names the full set plus the ids (a pressed Path on one id is not enough).
        proto("restart", three, "--reason", "again", **texts)
        proto("pass", "--origin", "press", stdin={"command": "step-back", "args": "goal foundations", "pending": None}, **texts)
        report("step-back")
        if pending_now() != ("step-back", f"goal foundations {three}"):
            raise ValueError(f"the round-wide path set without the ids does not count as the scoped pass: {pending_now()}")
        proto("pass", "--origin", "press", stdin={"command": "step-back", "args": f"goal foundations {three}", "pending": None}, **texts)
        report("step-back")
        if pending_now() != ("step-back", ""):
            raise ValueError(f"a pass naming the set and the ids counts as the scoped path pass: {pending_now()}")
        proto("abandon", **texts)
        def lens_round(word):
            """A round whose path pass and Base loop ran: the refine pair is pending."""
            found = texts_round(word)
            for _ in range(3):
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
        # With a batch out, edit withdraws and re-issues it; a previews-only change is presentation (no loop rerun).
        while shown(**texts)["step"] == "check":
            proto("step", **texts, stdin={"pass": shown(**texts)["pending"]["command"], "updates": [], "checked": ["q"]})
        first = shown(**texts)["batch"]["marker"]
        proto("say", "--origin", "composer", stdin={"text": "add a preview to Keep"}, **texts)
        proto("edit", **texts, stdin={"updates": [{"id": qid, "options": [{"label": "Keep", "description": "keep it", "preview": "x = 1"},
                                                                          {"label": "Drop", "description": "drop it"}]}], "quote": "add a preview to Keep"})
        again = shown(**texts)
        if again["batch"]["marker"] == first or again["batch"]["questions"][0]["options"][0].get("preview") != "x = 1" or again["step"] != "ask":
            raise ValueError(f"edit re-issues a batch that is out: {again}")
        proto("step", **texts, stdin={"pass": "ground", "updates": [{"id": qid, "options": [{"label": "Keep", "description": "keep it", "preview": "x = 2"},
                                                                                              {"label": "Drop", "description": "drop it"}]}], "checked": ["q"]})
        presented = shown(**texts)
        if presented["step"] != "ask" or presented["batch"]["questions"][0]["options"][0].get("preview") != "x = 2":
            raise ValueError(f"a previews-only pass update re-issues the batch without rerunning the loop: {presented}")
        proto("step", **texts, stdin={"pass": "ground", "updates": [{"id": qid, "options": [{"label": "Keep", "description": "keep it, changed"},
                                                                                              {"label": "Drop", "description": "drop it"}]}]})
        if shown(**texts)["step"] != "check":
            raise ValueError("an option description change is content: it reruns the check loop")
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
            {"record": rid, "ruling": "a fairly long ruling text " * 6, "alternative": "a", "fails": "f", "evidence": "e", "sure": n >= 3}
            for n, rid in enumerate(ids[:6])]})
        dialog = shown(cwd=repo, **texts)["batch"]["questions"][0]
        if len(dialog["question"]) > 160 or len(dialog["header"]) > 12 or any(len(o["description"]) > 150 for o in dialog["options"]) \
                or "unsure:" not in proto("show", cwd=repo, **texts).stdout or any(rid in dialog["question"] for rid in ids):
            raise ValueError(f"a release approval dialog stays within the limits by construction: {dialog}")
        title = next(q for q in shown(cwd=repo, **texts)["questions"])["title"]
        if len(title) > 60:
            raise ValueError(f"a release approval question title stays within 60 characters: {title}")
        proto("abandon", cwd=repo, **texts)


def validate_worker_last_use(root: Path) -> None:
    """Exercise only synthetic transcripts, never the invoking session's workers."""
    from datetime import datetime, timedelta, timezone

    helper = root / "bin" / "worker-last-use.py"
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
        validate_console_lenses(root)
        validate_console_programs(root)
        validate_strength_rules(root)
        validate_lens_names(root)
    elif name == "hooks":
        validate_hooks(root)
    elif name == "board":
        validate_board(root)  # patches os.environ and stdout in-process: nothing else shares this process
    elif name == "engine":
        validate_protocol(root)
        validate_console_contract(root)
    else:
        raise SystemExit(f"unknown group {name}")


GROUPS = ("core", "hooks", "board", "engine")


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
