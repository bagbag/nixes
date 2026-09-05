#!/usr/bin/env python3
"""Fingerprint Git-visible state without changing the index or working tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path


def git(repo: Path, *args: str, optional: bool = False) -> bytes:
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        capture_output=True,
    )
    if result.returncode:
        if optional and result.returncode == 1:
            return b""
        raise RuntimeError(result.stderr.decode(errors="replace").strip())
    return result.stdout


def metadata(repo: Path) -> tuple[bytes, ...]:
    return (
        git(repo, "rev-parse", "--verify", "--quiet", "HEAD", optional=True).strip(),
        git(repo, "symbolic-ref", "--quiet", "--short", "HEAD", optional=True).strip(),
        git(repo, "ls-files", "--stage", "-z"),
        git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z"),
        git(repo, "ls-files", "-v", "-z"),
        git(repo, "status", "--porcelain=v2", "-z", "--untracked-files=all", "--ignore-submodules=none"),
    )


def add_field(digest, value: bytes) -> None:
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def file_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def fingerprint(repo: Path) -> dict[str, object]:
    repo = Path(os.fsdecode(git(repo, "rev-parse", "--show-toplevel").strip())).resolve()
    before = metadata(repo)
    digest = hashlib.sha256(b"agent-worktree-v1\0")
    for value in before[:3] + before[4:]:
        add_field(digest, value)

    submodules = set()
    for entry in before[2].split(b"\0"):
        if entry.startswith(b"160000 "):
            submodules.add(entry.split(b"\t", 1)[1])

    paths = sorted(set(before[3].split(b"\0")) - {b""})
    for raw_path in paths:
        add_field(digest, raw_path)
        path = repo / os.fsdecode(raw_path)
        try:
            info = path.lstat()
        except FileNotFoundError:
            add_field(digest, b"missing")
            continue

        if stat.S_ISLNK(info.st_mode):
            add_field(digest, b"symlink")
            add_field(digest, os.fsencode(os.readlink(path)))
        elif stat.S_ISREG(info.st_mode):
            add_field(digest, b"executable" if info.st_mode & 0o111 else b"file")
            content = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    content.update(chunk)
            add_field(digest, content.digest())
        elif stat.S_ISDIR(info.st_mode) and raw_path in submodules:
            add_field(digest, b"submodule")
            if (path / ".git").exists():
                nested_root = Path(os.fsdecode(git(path, "rev-parse", "--show-toplevel").strip()))
                if nested_root.resolve() != path.resolve():
                    raise RuntimeError(f"Submodule points at a different worktree: {path}")
                nested = fingerprint(path)
                add_field(digest, str(nested["sha256"]).encode())
            elif not any(path.iterdir()):
                add_field(digest, b"uninitialized")
            else:
                raise RuntimeError(f"Cannot fingerprint populated uninitialized submodule: {path}")
        else:
            raise RuntimeError(f"Unsupported Git-visible file type: {path}")

        if file_identity(info) != file_identity(path.lstat()):
            raise RuntimeError(f"File changed during fingerprinting; retry when work is idle: {path}")

    if before != metadata(repo):
        raise RuntimeError("Git state changed during fingerprinting; retry when work is idle")
    return {
        "version": 1,
        "branch": os.fsdecode(before[1]) or None,
        "head": before[0].decode() or None,
        "sha256": digest.hexdigest(),
        "files": len(paths),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        result = fingerprint(args.repo)
    except (OSError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
