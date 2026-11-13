#!/usr/bin/env python3
"""Installs the Claude Code + Codex agent setup into $HOME. Idempotent. A rerun from a newer bundle removes what the last
install shipped and this one no longer does, recorded in ~/.agents/setup-state.json. It also grants the agents their write
roots: Edit rules in Claude's permissions.allow, tracked in the state file, and a marked
writable_roots block in ~/.codex/config.toml, found again by its marker.

Usage: ./install.py [--no-mod] [--dry-run]
       ./install.py --uninstall [--dry-run]

Everything is planned before the first change; a plan that fails stops with nothing changed.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

REEXEC = "CLAUDE_CODEX_SETUP_REEXEC"


def newest_python3() -> str | None:
    """The newest python3.N (N >= 11) on PATH that starts and reports 3.11 or newer; a shim of an unselected version is skipped."""
    for minor in range(30, 10, -1):
        found = shutil.which("python3.%d" % minor)
        if found and subprocess.run([found, "-c", "import sys; sys.exit(sys.version_info < (3, 11))"], capture_output=True).returncode == 0:
            return found
    return None


# macOS ships python3 3.9: this part must parse there, so the install either moves to a newer python3 or says why not.
if sys.version_info < (3, 11):
    current = "%d.%d.%d" % tuple(sys.version_info[:3])
    newer = None if os.environ.get(REEXEC) else newest_python3()
    if newer is None:
        sys.exit("python3 is %s; 3.11 or newer is needed (nothing changed)" % current)
    print("python3 is %s; continuing with %s" % (current, newer), file=sys.stderr)
    os.environ[REEXEC] = "1"
    os.execv(newer, [newer] + sys.argv)

import json
import re
import stat
import tempfile
import time
import tomllib
from pathlib import Path

BD_TESTED = "1.3.1"
MOD_VALUE = "~/.claude/mods/console"
# The agents' write folders outside repositories, as (XDG variable, its default under HOME, subpath): bin/scratch and
# bin/protocol_engine/cli.py own the subpaths and the suite checks them against these.
GRANT_ROOTS = (
    ("XDG_STATE_HOME", ".local/state", "agents/scratch"),
    ("XDG_DATA_HOME", ".local/share", "agents/decisions"),
)
CODEX_MARK = "# claude-codex-setup: agent scratch and records (./install.py --uninstall removes this block)"
CODEX_BLOCK = re.compile(r"^# claude-codex-setup: [^\r\n]*\r?\n\[sandbox_workspace_write\]\r?\nwritable_roots = (\[[^\r\n]*\])(?:\r?\n|\Z)", re.M)


class Fail(Exception):
    pass


def note(text: str) -> None:
    print("NOTE: " + text, file=sys.stderr)


def load_object(path: Path, rel: str) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise Fail("%s is not a JSON object; fix it first" % rel)
    return data


def grant_roots(home: str, env: dict) -> list:
    """Each root as ~/... when it lies under HOME, else absolute."""
    roots = []
    for variable, default, sub in GRANT_ROOTS:
        base = env.get(variable) or ""
        path = (base if base.startswith("/") else home + "/" + default).rstrip("/") + "/" + sub
        roots.append("~" + path[len(home):] if path.startswith(home + "/") else path)
    return roots


def edit_rule(root: str) -> str:
    """Claude reads a leading / as project-relative; // is the filesystem root."""
    return "Edit(%s/**)" % ("/" + root if root.startswith("/") else root)


def hook_commands(hooks: dict) -> list:
    return [h["command"] for groups in hooks.values() for g in groups for h in g.get("hooks", []) if "command" in h]


def merge_hooks(settings: dict, template: dict, earlier: list) -> None:
    """Drops this setup's registrations, last install's and this one's, keeps the rest, then adds the template's."""
    drop = set(earlier) | set(hook_commands(template))
    old = settings.get("hooks", {})
    if not isinstance(old, dict):
        raise ValueError("hooks is not an object")
    merged = {}
    for event in sorted(set(old) | set(template)):
        groups = old.get(event, [])
        if not isinstance(groups, list) or not all(isinstance(g, dict) and isinstance(g.get("hooks", []), list) for g in groups):
            raise ValueError("hooks.%s is not a list of hook groups" % event)
        kept = []
        for group in groups:
            entries = [h for h in group.get("hooks", []) if not (isinstance(h, dict) and h.get("command", "") in drop)]
            if entries:
                kept.append({**group, "hooks": entries})
        if kept + template.get(event, []):
            merged[event] = kept + template.get(event, [])
    if merged or "hooks" in settings:
        settings["hooks"] = merged


def merge_mod(settings: dict, shipped_mod: bool) -> None:
    env = settings.get("env", {})
    if not isinstance(env, dict):
        raise ValueError("env is not an object")
    current = env.get("CLAUDE_CODE_PLUGIN_DIRS", "") or ""
    if shipped_mod:
        if current == "":
            settings["env"] = {**env, "CLAUDE_CODE_PLUGIN_DIRS": MOD_VALUE}
        elif "mods/console" not in current:
            note("env.CLAUDE_CODE_PLUGIN_DIRS is already '%s'; add %s to it by hand." % (current, MOD_VALUE))
    elif current == MOD_VALUE:
        del env["CLAUDE_CODE_PLUGIN_DIRS"]
        if env:
            settings["env"] = env
        else:
            del settings["env"]
    elif "mods/console" in current:
        note("env.CLAUDE_CODE_PLUGIN_DIRS is '%s'; remove %s from it by hand." % (current, MOD_VALUE))


def merge_grants(settings: dict, rules: list, earlier: list) -> list:
    """Adds the Edit rules that are missing, drops the earlier install's that are no longer shipped. Returns the rules this
    install answers for: one the user already held before the first install is theirs and stays on upgrade and uninstall."""
    perms = settings.get("permissions", {})
    allow = perms.get("allow", []) if isinstance(perms, dict) else None
    if not isinstance(allow, list):
        raise ValueError("permissions.allow is not a list")
    kept = [a for a in allow if a not in [e for e in earlier if e not in rules]]
    result = kept + [r for r in rules if r not in kept]
    if result:
        settings["permissions"] = {**perms, "allow": result}
    elif allow:  # we emptied the user's list: drop what is left empty, but never an empty object they had
        perms.pop("allow")
        if not perms:
            settings.pop("permissions")
    return [r for r in rules if r in earlier or r not in allow]


def plan_settings(path: Path, rel: str, template: dict, earlier: list, tweak=None):
    """The new settings text, or None when the file stays as it is."""
    settings = load_object(path, rel)
    before = json.loads(json.dumps(settings))
    try:
        merge_hooks(settings, template, earlier)
        if tweak:
            tweak(settings)
    except ValueError as problem:
        raise Fail("%s has hooks or permissions the installer cannot merge: %s; fix them first" % (rel, problem))
    if path.exists() and settings == before:
        return None
    return json_text(settings)


def json_text(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def toml_parse(text: str) -> dict:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        raise Fail("~/.codex/config.toml is not valid TOML; fix it first")


def plan_codex_config(path: Path, roots: list, home: str):
    """The new config.toml text, or None. Only our marked block is ever written or removed; a table of the user's own gets
    a NOTE. The result is parsed back before it is accepted."""
    def expand(entry: str) -> str:
        return home + entry[1:] if entry.startswith("~/") else entry

    writable = not path.is_symlink()
    try:
        text = path.read_bytes().decode("utf-8") if path.exists() else ""
    except UnicodeDecodeError:
        raise Fail("~/.codex/config.toml is not valid TOML; fix it first")
    eol = "\r\n" if "\r\n" in text else "\n"
    data = toml_parse(text)
    table = data.get("sandbox_workspace_write")
    present = table.get("writable_roots", []) if isinstance(table, dict) else []
    missing = [r for r in roots if expand(r) not in [expand(e) for e in present if isinstance(e, str)]]
    found = list(CODEX_BLOCK.finditer(text))
    ours = listed = None
    if len(found) == 1:
        listed = toml_parse("r = " + found[0].group(1))["r"]
        if table == {"writable_roots": listed}:
            ours = found[0]

    def add_by_hand(reason: str) -> None:
        note("add %s to sandbox_workspace_write.writable_roots in ~/.codex/config.toml by hand (%s)." % (", ".join(missing), reason))

    block = eol.join([CODEX_MARK, "[sandbox_workspace_write]", "writable_roots = " + json.dumps(roots)]) + eol
    if not roots:
        if ours is None:
            if "claude-codex-setup:" in text:
                note("remove the claude-codex-setup block from ~/.codex/config.toml by hand; it was edited.")
            return None
        if not writable:
            note("remove the claude-codex-setup block from ~/.codex/config.toml by hand; it is a symlink.")
            return None
        head = text[:ours.start()]
        new = (head[:-len(eol)] if head.endswith(eol + eol) else head) + text[ours.end():]
    elif ours is not None:
        if listed == roots:
            return None
        if not writable:
            note("set writable_roots in the claude-codex-setup block of ~/.codex/config.toml to %s by hand; it is a symlink." % json.dumps(roots))
            return None
        new = text[:ours.start()] + block + text[ours.end():]
    elif not missing:
        return None
    elif table is not None or not writable:
        add_by_hand("it is a symlink" if not writable else "it has that table already")
        return None
    else:
        new = text + ("" if not text else eol if text.endswith("\n") else eol + eol) + block
    after = toml_parse(new)
    outside = lambda d: {k: v for k, v in d.items() if k != "sandbox_workspace_write"}
    held = [expand(e) for e in after.get("sandbox_workspace_write", {}).get("writable_roots", [])]
    if outside(after) != outside(data) or (roots and any(expand(r) not in held for r in roots)) or (not roots and "sandbox_workspace_write" in after):
        raise Fail("~/.codex/config.toml cannot be merged; fix it first")
    return new


def pinnable(rel: str, data: bytes) -> bool:
    return re.fullmatch(r"\.agents/bin/[^/]+", rel) is not None and data.split(b"\n", 1)[0] == b"#!/usr/bin/env python3"


def pinned_interpreter() -> tuple:
    """The PATH entry this python was started through, not its realpath: store and version-named paths go away on
    upgrades. A python3 on PATH is preferred to a python3.N. Returns (path, "" | "versioned" | "none")."""
    me = os.path.realpath(sys.executable)
    for name in ("python3", "python3.%d" % sys.version_info[1]):
        for folder in os.environ.get("PATH", "").split(os.pathsep):
            candidate = os.path.join(folder, name)
            if folder and os.path.isfile(candidate) and os.access(candidate, os.X_OK) and os.path.realpath(candidate) == me:
                return os.path.abspath(candidate), ("" if name == "python3" else "versioned")
    return sys.executable, "none"


def replace_file(path: Path, data: bytes, mode: int = -1) -> None:
    """Writes through a new file of the installer's own beside the target: a leftover or planted name there is never
    followed, and a crash leaves the old content. The mode is the given one, else the target's, else the new file's 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, pending = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.name + ".")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        if mode < 0 and path.exists():
            mode = stat.S_IMODE(path.stat().st_mode)
        if mode >= 0:
            os.chmod(pending, mode)
        os.replace(pending, str(path))
    finally:
        if os.path.lexists(pending):
            os.unlink(pending)


def refuse_symlinks(home: Path, rels) -> None:
    """A symlinked file or folder (for example into a read-only store or a dotfiles repo) cannot be replaced safely."""
    for rel in rels:
        parts = Path(rel).parts
        for i in range(len(parts), 0, -1):
            p = "/".join(parts[:i])
            if (home / p).is_symlink():
                raise Fail("~/%s is a symlink; resolve it first" % p)


def check_home() -> Path:
    value = os.environ.get("HOME", "")
    if not value.startswith("/"):
        raise Fail("HOME is not an absolute path: '%s'" % value)
    if not os.path.isdir(value):
        raise Fail("HOME is not a folder: %s" % value)
    if os.path.samefile(value, "/"):
        raise Fail("HOME is the root folder")
    return Path(value)


def list_shipped(files: Path, no_mod: bool) -> list:
    found = sorted(p.relative_to(files).as_posix() for p in files.rglob("*") if p.is_file())
    return [r for r in found if not (no_mod and r.startswith(".claude/mods/"))]


def read_state(path: Path, rel: str) -> dict:
    state = load_object(path, rel)
    files, hooks, grants = state.get("files", []), state.get("hooks", {}), state.get("grants", [])
    ok = (isinstance(files, list) and all(isinstance(f, str) for f in files) and isinstance(hooks, dict)
          and all(isinstance(v, list) for v in hooks.values()) and isinstance(grants, list))
    if not ok:
        raise Fail("%s is damaged; fix or delete it first" % rel)
    # The state decides what gets removed, so a damaged entry must not reach outside the install's own folders.
    if any(not re.match(r"\.(claude|codex|agents)/", f) or re.search(r"(^|/)\.\.(/|$)", f) for f in files):
        raise Fail("%s lists a path outside ~/.claude, ~/.codex and ~/.agents; fix or delete it first" % rel)
    return state


def person_prompt() -> None:
    if not shutil.which("git"):
        return
    probe = subprocess.run(["git", "config", "--global", "--get", "agents.person"], capture_output=True, text=True)
    if probe.stdout.strip():
        return
    if sys.stdin.isatty():
        try:
            who = input("Your name for shared boards (git config --global agents.person; blank skips): ")
        except EOFError:
            who = ""
        if who:
            subprocess.run(["git", "config", "--global", "agents.person", who])
    else:
        note("for shared boards, set your name: git config --global agents.person <name>.")


def main(argv: list) -> int:
    flags = set(argv)
    for flag in argv:
        if flag not in ("--uninstall", "--no-mod", "--dry-run"):
            print("unknown option: " + flag, file=sys.stderr)
            return 2
    uninstall, no_mod, dry = "--uninstall" in flags, "--no-mod" in flags, "--dry-run" in flags
    try:
        return run(uninstall, no_mod, dry)
    except Fail as problem:
        print("%s (nothing changed)" % problem, file=sys.stderr)
        return 1


def run(uninstall: bool, no_mod: bool, dry: bool) -> int:
    home = check_home()
    here = Path(__file__).resolve().parent
    state_path, state_rel = home / ".agents" / "setup-state.json", ".agents/setup-state.json"
    version = (here / "VERSION").read_text(encoding="utf-8").strip()

    # ---- 1. plan: everything here stops before the first change ----
    roots = []
    if not uninstall:
        if not shutil.which("bd"):
            raise Fail("missing required tool: bd")
        probe = subprocess.run(["bd", "--version"], capture_output=True, text=True)
        found = re.search(r"\d+\.\d+\.\d+", probe.stdout)
        if not found or found.group(0) != BD_TESTED:
            note("board is tested with bd %s; found %s." % (BD_TESTED, found.group(0) if found else "an unknown version"))
        roots = grant_roots(str(home), os.environ)

    settings_path, hooks_path, config_path = home / ".claude" / "settings.json", home / ".codex" / "hooks.json", home / ".codex" / "config.toml"
    state = read_state(state_path, state_rel)
    shipped = [] if uninstall else list_shipped(here / "files", no_mod)
    old = sorted(state.get("files", []))
    refuse_symlinks(home, [".claude/settings.json", ".codex/hooks.json", state_rel] + shipped + old)
    for rel in shipped + old:
        if (home / rel).exists() and not (home / rel).is_file():
            raise Fail("~/%s is not a regular file; move it away first" % rel)

    templates = {"claude": {}, "codex": {}}
    if not uninstall:
        for tool in templates:
            templates[tool] = json.loads((here / "settings" / (tool + "-hooks.json")).read_text(encoding="utf-8"))["hooks"]
    rules = [edit_rule(r) for r in roots]
    earlier_rules = state.get("grants", [])
    owned = []

    def claude_tweaks(settings: dict) -> None:
        merge_mod(settings, any(r.startswith(".claude/mods/") for r in shipped))
        owned.extend(merge_grants(settings, rules, earlier_rules))

    planned = []  # (target, text)
    for path, rel, tool, tweak in ((settings_path, ".claude/settings.json", "claude", claude_tweaks), (hooks_path, ".codex/hooks.json", "codex", None)):
        text = None if uninstall and not path.exists() else plan_settings(path, rel, templates[tool], state.get("hooks", {}).get(tool, []), tweak)
        if text is not None:
            planned.append((path, text))
    config = plan_codex_config(config_path, roots, str(home))
    created = state.get("config_created") is True or (config is not None and not config_path.exists())
    if config is not None:
        # A config.toml the installer created and the uninstall leaves blank goes with it.
        planned.append((config_path, config if config.strip() or not created else None))

    # Tools started from a launchd PATH would pick macOS's python3 3.9: the installed ones name the interpreter running this.
    pin = ""
    if not uninstall and any(pinnable(r, (here / "files" / r).read_bytes()) for r in shipped):
        pin, why = pinned_interpreter()
        if re.search(r"\s", pin):
            raise Fail("the python3 path '%s' holds a space, which a shebang cannot" % pin)
        if why == "versioned":
            note("the installed tools are pinned to the versioned %s; rerun the installer after removing or upgrading it." % pin)
        elif why == "none":
            note("no python3 on PATH is this interpreter; the installed tools are pinned to %s." % pin)

    new_state = {"version": version, "files": shipped, "hooks": {tool: hook_commands(t) for tool, t in templates.items()}, "grants": owned, "config_created": created}

    def content(rel: str) -> bytes:
        data = (here / "files" / rel).read_bytes()
        return b"#!" + pin.encode() + b"\n" + data.split(b"\n", 1)[1] if pin and pinnable(rel, data) else data

    # ---- 2. files: each replaced or removed one goes to the backup first ----
    backup = home / ".agent-config-backup" / ("%s-%d" % (time.strftime("%Y%m%d-%H%M%S"), os.getpid()))
    backed = changed = False

    def backup_path(rel: str) -> None:
        nonlocal backed
        if not (home / rel).exists():
            return
        backed = True
        if not dry:
            (backup / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(home / rel), str(backup / rel))

    for rel in shipped:
        target, data = home / rel, content(rel)
        if target.exists() and target.read_bytes() == data:
            continue
        changed = True
        backup_path(rel)
        print("install " + rel)
        if not dry:
            replace_file(target, data, stat.S_IMODE((here / "files" / rel).stat().st_mode))

    if any(r.startswith(".claude/mods/") for r in old) and not any(r.startswith(".claude/mods/") for r in shipped) and not dry:
        # Claude Code lays these into the mod's folder; they are no file of ours.
        shutil.rmtree(str(home / ".claude" / "mods" / "console" / ".claude-plugin" / "types"), ignore_errors=True)
    for rel in sorted(set(old) - set(shipped)):
        if not (home / rel).exists():
            continue
        changed = True
        backup_path(rel)
        print("remove  " + rel)
        if dry:
            continue
        (home / rel).unlink()
        folder = Path(rel).parent
        while str(folder) != ".":
            try:
                (home / folder).rmdir()
            except OSError:
                break
            folder = folder.parent

    # ---- 3. settings: the merges planned above ----
    for path, text in planned:
        rel = path.relative_to(home).as_posix()
        changed = True
        print(("merge   " if text is not None else "remove  ") + rel)
        if not dry:
            backup_path(rel)
            if text is None:
                path.unlink()
            else:
                replace_file(path, text.encode("utf-8"))

    # ---- 4. state: what the next run removes ----
    if not dry:
        if uninstall:
            if state_path.exists():
                state_path.unlink()
        else:
            replace_file(state_path, json_text(new_state).encode("utf-8"))

    # ---- 5. the person shared boards route to ----
    if not uninstall and not dry:
        person_prompt()

    if pin:
        print("python  " + pin)
    if backed and not dry:
        print("backup  %s" % backup)
    if uninstall:
        print("done. Your earlier instructions, if any, are in ~/.agent-config-backup/. Restart Claude Code and Codex.")
    elif not changed:
        print("already up to date (%s)." % version)
    else:
        print("done (%s). Restart Claude Code and Codex; Codex asks you to trust the changed hooks." % version)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
