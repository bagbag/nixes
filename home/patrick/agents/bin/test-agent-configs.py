#!/usr/bin/env python3
"""Validate shared skills and both generated custom-agent formats."""

from __future__ import annotations

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
            if command[1] == "history":
                return subprocess.CompletedProcess(command, 0, json.dumps(self.history.get(command[2], [])), "")
            if command[1] == "lint":
                return subprocess.CompletedProcess(command, 0, json.dumps(self.lint), "")
            if command[1] == "update" and command[2] in self.refuse:
                return subprocess.CompletedProcess(command, 13, "", f"assignee mismatch: {command[2]}")
            return subprocess.CompletedProcess(command, 0, "[]", "")

        def writes(self):
            return [args for args, _ in self.calls if args[0] not in ("export", "lint", "history")]

    def invoke(argv, fake, actor="", now="2026-10-22T15:30:00+00:00"):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(board.subprocess, "run", fake), \
                patch.object(board, "utcnow", lambda: datetime.fromisoformat(now)), \
                patch.dict(os.environ, {"BEADS_ACTOR": actor, "CODEX_SESSION_ID": "", "CLAUDE_CODE_SESSION_ID": ""}), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = board.main(argv)
        if sum(1 for args, _ in fake.calls if args[0] == "export") != 1:
            raise ValueError(f"board {argv[0]} must read exactly one bd export: {fake.calls}")
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
            for blocker, claimable in (("fx-missing", False), ("external:up:cap", True)):
                _, gated, _ = invoke(["queue"], Fake(variant(**{"Ready task": {"dependencies": [
                    *ready_task["dependencies"], {"issue_id": ready_task["id"], "depends_on_id": blocker, "type": "blocks"}]}})))
                if ("Ready task" in gated) != claimable:
                    raise ValueError(f"board queue misjudged a blocker outside the snapshot: {blocker}")
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

            store = ids["Store choice"]
            fake = Fake(fixture, lint={"results": [{"id": store, "missing": ["## Rule owner"]}]})
            code, _, errors = invoke(["release", store], fake, "lead0001")
            if code == 0 or "## Rule owner" not in errors or fake.writes():
                raise ValueError("board release accepted a record failing bd lint")
            for refused in (ids["Ready task"], ids["Released ruling"]):
                fake = Fake(fixture)
                if invoke(["release", refused], fake, "lead0001")[0] == 0 or fake.writes():
                    raise ValueError(f"board release accepted {refused}")
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


def main() -> int:
    root = (
        Path(sys.argv[1]).resolve()
        if len(sys.argv) > 1
        else Path(__file__).resolve().parents[1]
    )
    generator = load_generator(root)
    expander = load_skill_expander(root)
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
    validate_hooks(root)
    validate_board(root)
    print("shared agent and skill validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
