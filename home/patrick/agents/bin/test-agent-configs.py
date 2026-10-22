#!/usr/bin/env python3
"""Validate shared skills and both generated custom-agent formats."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import yaml


# User-only: Claude `disable-model-invocation: true` plus Codex's implicit-invocation policy.
USER_ONLY_SKILLS = {"board-migrate", "question-me", "recheck-rulings", "release-round", "retro", "role", "step-back"}
EXPLICIT_ONLY_SKILLS = USER_ONLY_SKILLS
ROLE_PROTOCOLS = ("decide", "plan", "work", "review", "unattended")
RETIRED_SKILL_PATHS = (
    "goal-lead", "goal-agent", "supervisor", "autopilot", "beads-migrate",
    "shared/goal-relay.md", "shared/worker-arcs.md",
)
RETIRED_REFERENCES = re.compile(
    r"skills/(goal-lead|goal-agent|supervisor|autopilot|beads-migrate)/|worker-arcs\.md|goal-relay\.md|board-health"
)
IMPLICIT_SKILLS = {"architect", "define-goal", "explore-options", "second-opinion", "staged-review"}
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
            "/nix/store/x/bin/bd list", "BEADS_ACTOR=a bd close x", 'bash -c "cd x && bd ready"']
    passing = ["board bd show x", "$HOME/.agents/bin/board bd close x", "cd x && board bd ready",
               "xargs -I{} board bd show {} < ids", 'echo "bd close x"', 'git commit -m "bd close"', "rg pattern skills",
               'board handover x "tests pass; bd lint clean"', 'git commit -m "x (bd 1.3.1)"', 'echo "x && bd ready"',
               "rg 'a|bd ' skills", "sh -c 'board bd show x'",
               'codex exec "line one\nslug \'demo\'. Run it." | grep -E "^(x|bd )"']
    for command in bare:
        for payload in ({}, {"session_id": SESSION}, {"session_id": SESSION, "turn_id": "t"}):
            result = guard(command, **payload)
            if not denied(result) or "board bd" not in result["hookSpecificOutput"]["permissionDecisionReason"]:
                raise ValueError(f"bd-guard let bare bd through: {command!r} with {payload}")
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
                'board bd comments add x "drop the --actor goal-agent habit and BEADS_ACTOR=goal-lead"']
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


def validate_hooks(root: Path) -> None:
    hooks = root / "hooks"
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
            self.history = history or {}

        def __call__(self, command, **kwargs):
            if command[0] != "bd":
                return real_run(command, **kwargs)
            self.calls.append((command[1:], kwargs.get("input")))
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

            # board check: one line per deviation with its class and work-tracking anchor.
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
                (cid["Old milestone"], "retired-type", "kinds"),
                (cid["[Design] Prefixed title"], "title-prefix", "kinds"),
                (cid["[Gate] Release: round 3"], "title-prefix", "kinds"),
                (cid["[Gate] Release: round 3"], "release-gate", "kinds"),
                (gate, "release-gate", "kinds"),
                (cid["Labelled status"], "label-status", "statuses-and-labels"),
                (cid["Released ruling"], "released-blocks", "questions-and-rulings"),
                (cid["Unformatted ruling"], "record-format", "questions-and-rulings"),
                (cid["Unnamed wait"], "unnamed-blocker", "dependencies"),
            ]
            for item_id, name, anchor in expected_lines:
                if f"  {item_id}  {name}  work-tracking.md#{anchor}" not in report:
                    raise ValueError(f"board check missed {name} on {item_id}:\n{report}")
            deviation_lines = [row for row in report.splitlines() if "  work-tracking.md#" in row]
            if code != 1 or len(deviation_lines) != len(expected_lines) or "convention deviations: 10\n" not in report:
                raise ValueError(f"board check reported extra deviations or the wrong exit code {code}:\n{report}")
            # Gate blockers carry their own reason; closed dependents of a released ruling block nothing.
            for clean in ("Clean task", "User action", "Waits on ruling", "Gated question", "Closed waiter"):
                if any(f"  {cid[clean]}  " in row for row in deviation_lines):
                    raise ValueError(f"board check flagged conforming {clean}")
            flag = report.split("flag, not a deviation")[1]
            if f"  {cid['Squashed text']}  squashed" not in flag or f"  {cid['Clean task']}  " in flag:
                raise ValueError(f"board check missed or misplaced the squashed-text flag:\n{report}")
            if "convention deviations: 10 — run /board-migrate" not in health_check:
                raise ValueError("board health lacks the deviation hint")
            _, scoped_check, _ = invoke(["check", "--root", cid["Goal"]], Fake(checked))
            if f"  {gate}  release-gate" in scoped_check or f"  {cid['Legacy holder']}  holder" not in scoped_check:
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

            closed_dependent = [{**issue, "status": "closed"} if issue["title"] == "Waits on ruling" else issue
                                for issue in checked]
            # Closed items are immutable history: no class or flag looks at them.
            closed_all = [{**issue, "status": "closed"} if issue["title"] != "Goal" else issue for issue in checked]
            code, report, _ = invoke(["check"], Fake(closed_all))
            if code != 0 or "convention deviations: 0\n" not in report or "squashed text on open items: 0" not in report:
                raise ValueError(f"board check looked at closed items:\n{report}")
            if "  released-blocks  " in invoke(["check"], Fake(closed_dependent))[1]:
                raise ValueError("board check counted a closed dependent of a released ruling")

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
            expected_ops = [f'update {store} status=released assignee=""',
                            f"dep remove {ids['Implement store A']} {store}",
                            f"dep add {ids['Implement store A']} {store} relates-to",
                            f'update {question} status=released assignee=""']
            if code or len(batch) != 1 or len(fake.writes()) != 1 \
                    or not all(op in batch[0][1].splitlines() for op in expected_ops) \
                    or f"dep add {ids['Closed waiter']} {question} relates-to" not in batch[0][1]:
                raise ValueError(f"board release must write one batch: {fake.calls}")

            # A full supersede relates the old record's open items to the new one, skipping closed and
            # already linked items; --partial only adds the edge. Both drop the pair's existing link first.
            old, new = ids["Old store ruling"], ids["Store choice"]
            old_issue = next(i for i in fixture if i["id"] == old)
            linked = variant(**{"Old store ruling": {"dependencies": [*(old_issue.get("dependencies") or []), *(
                {"issue_id": old, "depends_on_id": ids[title], "type": "relates-to"}
                for title in ("Ready task", "Closed waiter", "Implement store A"))]}})
            fake = Fake(linked)
            code, output, _ = invoke(["supersede", old, "--with", new], fake, "lead0001")
            if code or fake.writes() != [["batch", "-m", f"board supersede {old} --with {new}", "--json"],
                                         ["supersede", old, "--with", new]] \
                    or next(stdin for args, stdin in fake.calls if args[0] == "batch") \
                    != f"dep remove {new} {old}\ndep add {ids['Ready task']} {new} relates-to\n":
                raise ValueError(f"board supersede: {fake.calls}\n{output}")
            fake = Fake(fixture)
            code, _, _ = invoke(["supersede", old, "--with", new, "--partial"], fake, "lead0001")
            if code or fake.writes() != [["batch", "-m", f"board supersede {old} --with {new}", "--json"]] \
                    or fake.calls[-1][1] != f"dep remove {new} {old}\ndep add {old} {new} supersedes\n":
                raise ValueError(f"board supersede --partial: {fake.writes()}")

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

        result, seen = run_board("bd", "show", "x", "--json")
        if result.returncode != 7 or seen != "9999aaaa show x --json\n":
            raise ValueError(f"board bd passthrough: {result.returncode} {seen!r}")
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
    validate_generated_agents(root, generator)
    validate_multiline_and_optional_names(generator)
    validate_effort_overrides(generator)
    validate_hooks(root)
    validate_board(root)
    print("shared agent and skill validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
