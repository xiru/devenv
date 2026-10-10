"""Git: the git command, the global commit identity and the repository hello world."""

import unittest
from unittest import mock

from devenv_check import checks
from devenv_check.checks import Status
from tests.helpers import LINUX, MACOS, fail, fake_system, ok, run_smoke, tool


class GitIdentityTest(unittest.TestCase):
    def identity(self, name, email):
        responses = {"user.name": name, "user.email": email}
        with mock.patch.object(checks, "run", side_effect=lambda args, **_: responses[args[-1]]):
            return checks.check_git_identity("/usr/bin/git")

    def test_complete(self):
        tool_ = self.identity(ok("Ada"), ok("ada@example.com"))
        self.assertEqual((tool_.status, tool_.detail, tool_.required), (Status.OK, "Ada <ada@example.com>", False))

    def test_missing_email(self):
        tool_ = self.identity(ok("Ada"), fail())
        self.assertEqual((tool_.status, tool_.hint), (Status.WARN, "git_identity"))
        self.assertIn("user.email not set", tool_.detail)

    def test_nothing_set(self):
        self.assertIn("user.name and user.email", self.identity(ok("  "), fail()).detail)


class CheckGitTest(unittest.TestCase):
    def test_installed(self):
        with fake_system({"git": "git version 2.47.1"}) as calls:
            git, identity = checks.check_git(LINUX)
        self.assertEqual((git.status, git.version), (Status.OK, "2.47.1"))
        self.assertEqual(identity.name, "commit identity")
        self.assertIn(["/usr/bin/git", "config", "--global", "--get", "user.name"], calls)

    def test_old_git_warns(self):
        with fake_system({"git": "git version 2.25.1"}):
            git, _ = checks.check_git(LINUX)
        self.assertIs(git.status, Status.WARN)

    def test_windows_version_suffix(self):
        with fake_system({"git": "git version 2.47.1.windows.2"}):
            git, _ = checks.check_git(LINUX)
        self.assertEqual(git.version, "2.47.1")

    def test_missing(self):
        with fake_system({}):
            (git,) = checks.check_git(LINUX)
        self.assertEqual((git.status, git.hint), (Status.MISSING, "git"))

    def test_macos_stub_without_command_line_tools_is_never_run(self):
        with fake_system({"git": "git version 2.39.5", "xcode-select": fail("unable to get active developer directory")},
                         ) as calls:
            (git,) = checks.check_git(MACOS)
        self.assertIs(git.status, Status.MISSING)
        self.assertIn("Command Line Tools", git.detail)
        self.assertFalse(any(call[0].endswith("git") for call in calls))

    def test_macos_with_command_line_tools(self):
        with fake_system({"git": "git version 2.39.5", "xcode-select": "/Library/Developer/CommandLineTools"}):
            git, _ = checks.check_git(MACOS)
        self.assertEqual(git.version, "2.39.5")


class GitSmokeTest(unittest.TestCase):
    def test_commit_in_an_isolated_repository(self):
        smoke_run = run_smoke("git", [tool("git")], "hello from git")
        self.assertIs(smoke_run.result.status, Status.OK)
        self.assertEqual([c[c.index("user.email=devenv-check@example.invalid") + 1] for c in smoke_run.commands],
                         ["init", "add", "commit", "log"])
        for command in smoke_run.commands:
            self.assertIn("commit.gpgsign=false", command)  # no signing prompts
            self.assertIn("core.hooksPath=.no-hooks", command)  # the user's global hooks never run
        self.assertEqual(smoke_run.written["hello.txt"], "hello from git\n")

    def test_skipped_without_git(self):
        self.assertIs(run_smoke("git", [tool("git", status=Status.MISSING)]).result.status, Status.SKIPPED)


if __name__ == "__main__":
    unittest.main()
