#!/usr/bin/env python3
"""Check fingerprint behavior with real files and controlled Git metadata."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "fingerprint", Path(__file__).with_name("worktree-fingerprint.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FingerprintTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.head = b"a" * 40
        self.branch = b"main"
        self.index = b"100644 " + b"b" * 40 + b" 0\ttracked\0"
        self.paths = b"tracked\0new file\nwith newline\0"
        self.flags = b"H tracked\0"
        self.status = b"? new file\nwith newline\0"
        (self.root / "tracked").write_bytes(b"tracked content")
        (self.root / "new file\nwith newline").write_bytes(b"untracked content")
        self.mock = patch.object(module, "git", side_effect=self.git)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def git(self, repo, *args, optional=False):
        if args == ("rev-parse", "--show-toplevel"):
            return str(self.root).encode() + b"\n"
        if args == ("rev-parse", "--verify", "--quiet", "HEAD"):
            return self.head
        if args == ("symbolic-ref", "--quiet", "--short", "HEAD"):
            return self.branch
        if args == ("ls-files", "--stage", "-z"):
            return self.index
        if args == ("ls-files", "-v", "-z"):
            return self.flags
        if args == ("status", "--porcelain=v2", "-z", "--untracked-files=all", "--ignore-submodules=none"):
            return self.status
        if args == ("ls-files", "--cached", "--others", "--exclude-standard", "-z"):
            return self.paths
        raise AssertionError(args)

    def digest(self):
        return module.fingerprint(self.root)["sha256"]

    def test_stable_across_mtime_only_and_ignored_changes(self):
        before = self.digest()
        (self.root / "tracked").touch()
        (self.root / "ignored").write_bytes(b"outside Git-visible scope")
        self.assertEqual(before, self.digest())

    def test_tracked_and_untracked_content_changes(self):
        for name in ("tracked", "new file\nwith newline"):
            before = self.digest()
            (self.root / name).write_bytes(b"changed\x00binary content")
            self.assertNotEqual(before, self.digest())

    def test_index_changes_with_identical_working_files(self):
        before = self.digest()
        self.index = self.index.replace(b"b" * 40, b"c" * 40)
        self.assertNotEqual(before, self.digest())

    def test_head_and_branch_changes(self):
        before = self.digest()
        self.head = b"d" * 40
        self.assertNotEqual(before, self.digest())
        before = self.digest()
        self.branch = b"topic"
        self.assertNotEqual(before, self.digest())

    def test_index_flags_and_intent_to_add_status(self):
        for flags in (b"h tracked\0", b"S tracked\0", b"s tracked\0"):
            before = self.digest()
            self.flags = flags
            self.assertNotEqual(before, self.digest())
        before = self.digest()
        self.status = b"1 .A N... 000000 000000 100644 " + b"0" * 40 + b" " + b"0" * 40 + b" tracked\0"
        self.assertNotEqual(before, self.digest())

    def test_deletion_and_executable_bit(self):
        before = self.digest()
        (self.root / "tracked").chmod(0o755)
        self.assertNotEqual(before, self.digest())
        before = self.digest()
        (self.root / "tracked").unlink()
        self.assertNotEqual(before, self.digest())

    def test_symlink_target_is_hashed_without_following_it(self):
        path = self.root / "tracked"
        path.unlink()
        path.symlink_to("missing-a")
        before = self.digest()
        path.unlink()
        path.symlink_to("missing-b")
        self.assertNotEqual(before, self.digest())

    def test_detached_and_unborn_head(self):
        self.branch = b""
        self.assertIsNone(module.fingerprint(self.root)["branch"])
        self.head = b""
        self.assertIsNone(module.fingerprint(self.root)["head"])

    def test_metadata_change_during_capture_fails(self):
        original = module.metadata
        count = 0

        def changing(repo):
            nonlocal count
            count += 1
            if count == 2:
                self.index = b""
            return original(repo)

        with patch.object(module, "metadata", side_effect=changing):
            with self.assertRaisesRegex(RuntimeError, "Git state changed"):
                self.digest()

    def test_initialized_submodule_working_content(self):
        submodule = self.root / "sub"
        (submodule / ".git").mkdir(parents=True)
        (submodule / "file").write_bytes(b"before")
        self.index += b"160000 " + b"c" * 40 + b" 0\tsub\0"
        self.paths += b"sub\0"

        def nested_git(repo, *args, optional=False):
            if Path(repo) == submodule:
                return {
                    ("rev-parse", "--show-toplevel"): str(submodule).encode(),
                    ("rev-parse", "--verify", "--quiet", "HEAD"): b"c" * 40,
                    ("symbolic-ref", "--quiet", "--short", "HEAD"): b"",
                    ("ls-files", "--stage", "-z"): b"100644 " + b"d" * 40 + b" 0\tfile\0",
                    ("ls-files", "-v", "-z"): b"H file\0",
                    ("status", "--porcelain=v2", "-z", "--untracked-files=all", "--ignore-submodules=none"): b"",
                    ("ls-files", "--cached", "--others", "--exclude-standard", "-z"): b"file\0",
                }[args]
            return self.git(repo, *args, optional=optional)

        with patch.object(module, "git", side_effect=nested_git):
            before = self.digest()
            (submodule / "file").write_bytes(b"after")
            self.assertNotEqual(before, self.digest())

    def test_uninitialized_submodule(self):
        submodule = self.root / "sub"
        submodule.mkdir()
        self.index += b"160000 " + b"c" * 40 + b" 0\tsub\0"
        self.paths += b"sub\0"
        self.digest()
        (submodule / "unowned").write_bytes(b"content")
        with self.assertRaisesRegex(RuntimeError, "populated uninitialized submodule"):
            self.digest()


if __name__ == "__main__":
    unittest.main()
