#!/usr/bin/env python3
"""Backfill kind metadata on legacy landed-change and design ratifications."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


KINDS = {"Ratify: ": "landing", "Ratify design: ": "design"}
WORK_TYPES = {"task", "bug", "spike"}


def kind_and_title(title: str) -> tuple[str, str] | None:
    for prefix, kind in sorted(KINDS.items(), key=lambda entry: len(entry[0]), reverse=True):
        if title.startswith(prefix):
            return kind, title[len(prefix):]
    return None


def parents(issue: dict) -> list[str]:
    return [edge["depends_on_id"] for edge in issue.get("dependencies") or []
            if edge.get("type") == "parent-child"]


def board_call(board: str, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([board, *args], cwd=cwd, capture_output=True, text=True)


def migration_plan(board: str, cwd: Path) -> tuple[list[tuple[str, str, str, str]], list[str]]:
    result = board_call(board, cwd, "bd", "list", "--status", "needs_ratification", "--limit", "0", "--json")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "board list failed")
    try:
        rows = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"board list returned invalid JSON: {error}") from error
    if not isinstance(rows, list):
        raise RuntimeError("board list did not return a JSON array")

    plan: list[tuple[str, str, str, str]] = []
    identities: Counter[tuple[str, str]] = Counter()
    problems: list[str] = []
    for issue in rows:
        if issue.get("issue_type") not in WORK_TYPES:
            continue
        title = str(issue.get("title") or "")
        metadata = issue.get("metadata") if isinstance(issue.get("metadata"), dict) else {}
        stored = str(metadata.get("ratification") or "")
        inferred = kind_and_title(title)
        if stored in ("landing", "design"):
            identities.update((parent, stored) for parent in parents(issue))
            if inferred is None:
                continue
            if inferred[0] != stored:
                problems.append(f"{issue.get('id')}: title prefix implies {inferred[0]}, metadata says {stored}")
                continue
            plan.append((issue["id"], title, inferred[1], stored))
            continue
        if stored not in ("", "1"):
            problems.append(f"{issue.get('id')}: unsupported ratification metadata {stored!r}")
            continue
        if inferred is None:
            if stored == "1":
                problems.append(f"{issue.get('id')}: legacy ratification marker has no recognized title prefix")
            continue
        parent_ids = parents(issue)
        if len(parent_ids) != 1:
            problems.append(f"{issue.get('id')}: expected one parent change request, found {len(parent_ids)}")
            continue
        identities[(parent_ids[0], inferred[0])] += 1
        plan.append((issue["id"], title, inferred[1], inferred[0]))

    for (parent, kind), count in identities.items():
        if count > 1:
            problems.append(f"{parent}: {count} {kind} ratifications would share the same parent and kind")
    return plan, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", default=str(Path.home() / ".agents" / "bin" / "board"),
                        help="board executable (default: ~/.agents/bin/board)")
    parser.add_argument("--apply", action="store_true", help="write the listed title and metadata changes")
    args = parser.parse_args()
    cwd = Path.cwd()
    try:
        plan, problems = migration_plan(args.board, cwd)
    except (OSError, RuntimeError) as error:
        print(f"ratification migration failed: {error}", file=sys.stderr)
        return 1
    if problems:
        print("ratification migration stopped without changes:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    if not plan:
        print("No legacy ratification items to migrate.")
        return 0

    verb = "migrating" if args.apply else "would migrate"
    for item_id, old_title, new_title, kind in plan:
        print(f"{verb} {item_id}: {kind}, {old_title!r} -> {new_title!r}")
    if not args.apply:
        print("No changes made. Rerun with --apply to update these board items.")
        return 0

    completed = 0
    for item_id, _, new_title, kind in plan:
        result = board_call(args.board, cwd, "bd", "--raw", "--yes", "update", item_id,
                            "--title", new_title, "--set-metadata", f"ratification={kind}", "--json")
        if result.returncode:
            print(f"migration stopped after {completed} item(s): {item_id}: "
                  f"{result.stderr.strip() or result.stdout.strip()}", file=sys.stderr)
            return 1
        completed += 1
    print(f"Migrated {completed} ratification item(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
