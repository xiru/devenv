"""Go: the go toolchain, its bin folder on PATH and the build hello world."""

import os
import unittest
from unittest import mock

from devenv_check import checks
from devenv_check.checks import Status
from tests.helpers import LINUX, fail, fake_system, ok, run_smoke, tool

GOPATH = os.path.join(os.sep, "home", "u", "go")
GOPATH_BIN = os.path.join(GOPATH, "bin")


class CheckGoTest(unittest.TestCase):
    def test_installed(self):
        with fake_system({"go": "go version go1.23.4 linux/amd64"}), \
             mock.patch.object(checks, "check_go_bin", return_value=checks.ToolResult("Go bin dir in PATH", Status.OK)) as go_bin:
            go, bin_dir = checks.check_go(LINUX)
        self.assertEqual((go.status, go.version), (Status.OK, "1.23.4"))
        go_bin.assert_called_once_with("/usr/bin/go")

    def test_old_go_warns(self):
        with fake_system({"go": "go version go1.21.13 linux/amd64"}):
            go, _ = checks.check_go(LINUX)
        self.assertIs(go.status, Status.WARN)

    def test_missing(self):
        with fake_system({}):
            (go,) = checks.check_go(LINUX)
        self.assertEqual((go.status, go.hint), (Status.MISSING, "go"))


class GoBinTest(unittest.TestCase):
    def check(self, result, path=""):
        with mock.patch.object(checks, "run", return_value=result), mock.patch.dict("os.environ", {"PATH": path}):
            return checks.check_go_bin("/usr/bin/go")

    def test_gopath_bin_on_path(self):
        tool_ = self.check(ok("\n" + GOPATH), path=GOPATH_BIN)  # empty GOBIN line first
        self.assertEqual((tool_.status, tool_.path, tool_.required), (Status.OK, GOPATH_BIN, False))

    def test_gobin_wins(self):
        gobin = os.path.join(os.sep, "opt", "gobin")
        self.assertEqual(self.check(ok(f"{gobin}\n{GOPATH}"), path=gobin).path, gobin)

    def test_first_gopath_entry_is_used(self):
        self.assertEqual(self.check(ok(f"\n{GOPATH}{os.pathsep}/other"), path=GOPATH_BIN).status, Status.OK)

    def test_not_on_path(self):
        tool_ = self.check(ok("\n" + GOPATH), path="")
        self.assertEqual((tool_.status, tool_.hint), (Status.WARN, "go_path"))
        self.assertIn("is not in PATH", tool_.detail)

    def test_unknown_gopath(self):
        tool_ = self.check(fail("go: command broken"))
        self.assertEqual((tool_.status, tool_.detail), (Status.WARN, "could not determine GOPATH"))


class GoSmokeTest(unittest.TestCase):
    def test_build_and_run_with_the_local_toolchain(self):
        smoke_run = run_smoke("go", [tool("go")], "hello from Go")
        self.assertIs(smoke_run.result.status, Status.OK)
        build, binary = smoke_run.calls
        self.assertEqual(build.args[1:3], ["build", "-o"])
        self.assertEqual(build.env, {"GOTOOLCHAIN": "local"})  # never downloads another toolchain
        self.assertTrue(binary.args[0].endswith("hello" + (".exe" if os.name == "nt" else "")))
        self.assertIn("module example.com/hello", smoke_run.written["go.mod"])

    def test_skipped_without_go(self):
        self.assertIs(run_smoke("go", [tool("go", status=Status.MISSING)]).result.status, Status.SKIPPED)


if __name__ == "__main__":
    unittest.main()
