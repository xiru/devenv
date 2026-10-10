"""Bash scripting: bash (Git Bash on Windows), shellcheck, shfmt and the script hello world."""

import os
import unittest
from pathlib import Path
from unittest import mock

from devenv_check import checks, smoke
from devenv_check.checks import Status
from devenv_check.runner import parse_version
from tests.helpers import LINUX, MACOS, WINDOWS, TempDirMixin, fake_system, ok, run_smoke, tool

BASH_5 = "GNU bash, version 5.2.37(1)-release (x86_64-pc-linux-gnu)"


class VersionTest(unittest.TestCase):
    def test_bash_version_format(self):
        self.assertEqual(parse_version("GNU bash, version 5.2.21(1)-release (x86_64-pc-linux-gnu)", checks.BASH_VERSION), (5, 2, 21))


class CheckBashTest(unittest.TestCase):
    def test_linux_with_linters(self):
        with fake_system({"bash": BASH_5, "shellcheck": "ShellCheck - version: 0.10.0", "shfmt": "v3.10.0"}):
            bash, shellcheck, shfmt = checks.check_bash(LINUX)
        self.assertEqual((bash.status, bash.version), (Status.OK, "5.2.37"))
        self.assertEqual((shellcheck.version, shfmt.version), ("0.10.0", "3.10.0"))
        self.assertFalse(shellcheck.required or shfmt.required)

    def test_missing_linters_are_optional(self):
        with fake_system({"bash": BASH_5}):
            tools = checks.check_bash(LINUX)
        self.assertIs(checks.EnvResult("bash", "Bash", tools).status, Status.WARN)

    def test_macos_system_bash_is_too_old(self):
        with fake_system({"bash": "GNU bash, version 3.2.57(1)-release"}):
            bash = checks.check_bash(MACOS)[0]
        self.assertEqual((bash.status, bash.hint), (Status.WARN, "bash"))
        self.assertIn("3.2", bash.detail)

    def test_windows_prefers_git_bash_over_wsl_launcher(self):
        def fake_which(name):
            return {"bash": r"C:\Windows\System32\bash.exe"}.get(name, name if name.endswith("bash.exe") else None)

        with mock.patch.object(checks, "find_git_bash", return_value=r"C:\Program Files\Git\bin\bash.exe"), \
             mock.patch.object(checks, "which", side_effect=fake_which), \
             mock.patch.object(checks, "run", return_value=ok(BASH_5)):
            bash = checks.check_bash(WINDOWS)[0]
        self.assertEqual((bash.status, bash.provider), (Status.OK, "Git Bash"))

    def test_windows_falls_back_to_wsl_bash(self):
        with mock.patch.object(checks, "find_git_bash", return_value=None), \
             mock.patch.object(checks, "which", side_effect=lambda n: r"C:\Windows\System32\bash.exe" if "bash" in n else None), \
             mock.patch.object(checks, "run", return_value=ok(BASH_5)):
            bash = checks.check_bash(WINDOWS)[0]
        self.assertEqual(bash.provider, "WSL bash")

    def test_windows_old_bash_warns(self):
        with mock.patch.object(checks, "find_git_bash", return_value=None), \
             mock.patch.object(checks, "which", side_effect=lambda n: r"C:\msys64\usr\bin\bash.exe" if "bash" in n else None), \
             mock.patch.object(checks, "run", return_value=ok("GNU bash, version 3.2.57(1)-release")):
            bash = checks.check_bash(WINDOWS)[0]
        self.assertEqual((bash.status, bash.provider), (Status.WARN, "bash"))
        self.assertIn("older than recommended 4.0", bash.detail)

    def test_windows_without_any_bash(self):
        with mock.patch.object(checks, "find_git_bash", return_value=None), mock.patch.object(checks, "which", return_value=None):
            bash = checks.check_bash(WINDOWS)[0]
        self.assertEqual((bash.status, bash.detail), (Status.MISSING, "neither Git Bash nor WSL bash found"))


class FindGitBashTest(TempDirMixin, unittest.TestCase):
    def test_bash_next_to_git(self):
        git = self.tmp / "Git" / "cmd" / "git.exe"
        bash = self.tmp / "Git" / "bin" / "bash.exe"
        for path in (git, bash):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        with mock.patch.object(checks, "which", return_value=str(git)):
            self.assertEqual(Path(checks.find_git_bash()).resolve(), bash.resolve())

    def test_default_install_folder(self):
        bash = self.tmp / "Git" / "bin" / "bash.exe"
        bash.parent.mkdir(parents=True)
        bash.touch()
        with mock.patch.object(checks, "which", return_value=None), mock.patch.dict(os.environ, {"ProgramFiles": str(self.tmp)}):
            self.assertEqual(checks.find_git_bash(), str(bash))

    def test_not_installed(self):
        with mock.patch.object(checks, "which", return_value=None), mock.patch.dict(os.environ, {"ProgramFiles": str(self.tmp)}):
            self.assertIsNone(checks.find_git_bash())


class BashSmokeTest(unittest.TestCase):
    def test_script_is_linted_then_run_with_lf_endings(self):
        smoke_run = run_smoke("bash", [tool("bash"), tool("shellcheck (linter)", required=False)], "hello from bash")
        self.assertIs(smoke_run.result.status, Status.OK)
        self.assertEqual(smoke_run.commands, [["/usr/bin/shellcheck", "hello.sh"], ["/usr/bin/bash", "hello.sh"]])
        self.assertEqual(smoke_run.result.detail, "passed shellcheck, ran with bash")
        self.assertNotIn("\r", smoke_run.written["hello.sh"])
        self.assertEqual(smoke_run.written["hello.sh"], smoke.BASH_SCRIPT)

    def test_without_shellcheck_and_with_a_provider(self):
        smoke_run = run_smoke("bash", [tool("bash", provider="Git Bash")], "hello from bash")
        self.assertEqual(smoke_run.commands, [["/usr/bin/bash", "hello.sh"]])
        self.assertEqual(smoke_run.result.detail, "ran with Git Bash")

    def test_skipped_without_bash(self):
        self.assertIs(run_smoke("bash", [tool("bash", status=Status.MISSING)]).result.status, Status.SKIPPED)


if __name__ == "__main__":
    unittest.main()
