"""Tool probing: probe(), first_available() and path_contains(), the building blocks of every check."""

import os
import unittest
from unittest import mock

from devenv_check import checks
from devenv_check.checks import Status, ToolResult
from tests.helpers import fail, fake_system, ok


class ProbeTest(unittest.TestCase):
    def test_missing_tool(self):
        with fake_system({}):
            tool = checks.probe("go", ["go", "version"], hint="go", required=False)
        self.assertEqual((tool.status, tool.hint, tool.required), (Status.MISSING, "go", False))
        self.assertIn("'go' not found in PATH", tool.detail)

    def test_found_but_broken(self):
        with fake_system({"java": fail("Unable to locate a Java Runtime")}):
            tool = checks.probe("java", ["java", "-version"])
        self.assertIs(tool.status, Status.MISSING)
        self.assertEqual(tool.path, "/usr/bin/java")
        self.assertIn("found but not working: Unable to locate", tool.detail)

    def test_broken_without_output_reports_exit_code(self):
        with fake_system({"tool": fail(returncode=127)}):
            self.assertIn("exit code 127", checks.probe("tool", ["tool"]).detail)

    def test_a_version_counts_even_with_a_non_zero_exit(self):
        with fake_system({"cl": fail("Microsoft (R) C/C++ Optimizing Compiler Version 19.44.35211 for x64")}):
            tool = checks.probe("cl", ["cl"], pattern=r"Version (\d+)\.(\d+)\.(\d+)")
        self.assertEqual((tool.status, tool.version), (Status.OK, "19.44.35211"))

    def test_runs_the_resolved_path(self):
        with fake_system({"npm": "10.9.2"}) as calls:
            checks.probe("npm", ["npm", "--version"])
        self.assertEqual(calls, [["/usr/bin/npm", "--version"]])

    def test_ok_and_old_versions(self):
        with fake_system({"node": "v24.4.0"}):
            current = checks.probe("node", ["node", "--version"], min_version=(22,))
        with fake_system({"node": "v18.19.0"}):
            old = checks.probe("node", ["node", "--version"], min_version=(22,))
        self.assertEqual((current.status, current.version, current.detail), (Status.OK, "24.4.0", ""))
        self.assertEqual((old.status, old.version), (Status.WARN, "18.19.0"))
        self.assertIn("older than recommended 22", old.detail)

    def test_fix_rewrites_the_version(self):
        with fake_system({"java": 'java version "1.8.0_381"'}):
            tool = checks.probe("java", ["java", "-version"], pattern=r'version "(\d+)(?:\.(\d+))?(?:\.(\d+))?',
                                fix=checks._java_legacy, min_version=(17,))
        self.assertEqual((tool.status, tool.version), (Status.WARN, "8.0"))

    def test_windows_tool_leaking_into_wsl_warns(self):
        with fake_system({"npm": "10.9.2"}, where="/mnt/c/Program Files/nodejs"), \
             mock.patch.object(checks, "is_wsl", return_value=True):
            tool = checks.probe("npm", ["npm", "--version"])
        self.assertIs(tool.status, Status.WARN)
        self.assertIn("WSL interop", tool.detail)

    def test_mnt_paths_are_fine_outside_wsl(self):
        with fake_system({"npm": "10.9.2"}, where="/mnt/c/tools"), mock.patch.object(checks, "is_wsl", return_value=False):
            self.assertIs(checks.probe("npm", ["npm", "--version"]).status, Status.OK)


class FirstAvailableTest(unittest.TestCase):
    def test_picks_the_first_installed_candidate(self):
        calls = []

        def candidate(name, status):
            def probe():
                calls.append(name)
                return ToolResult(name, status, version="17.0.6", detail="extra" if name == "ninja" else "")
            return probe

        tool = checks.first_available("C compiler", [candidate("gcc", Status.MISSING), candidate("clang", Status.OK),
                                                     candidate("never", Status.OK)], hint="cpp", required=False)
        self.assertEqual((tool.name, tool.provider, tool.detail, tool.hint, tool.required),
                         ("C compiler", "clang", "clang", "cpp", False))
        self.assertEqual(calls, ["gcc", "clang"])  # stops at the first hit

    def test_keeps_the_candidate_detail(self):
        tool = checks.first_available("make", [lambda: ToolResult("ninja", Status.WARN, detail="old")])
        self.assertEqual((tool.status, tool.detail), (Status.WARN, "ninja; old"))

    def test_nothing_installed(self):
        tool = checks.first_available("make / ninja", [lambda: ToolResult("make", Status.MISSING)],
                                      required=False, hint="build_tools", missing_detail="neither found")
        self.assertEqual((tool.name, tool.status, tool.detail, tool.required), ("make / ninja", Status.MISSING, "neither found", False))

    def test_candidate_helper_probes_with_a_label(self):
        with fake_system({"clang": "clang version 18.1.3"}):
            tool = checks._candidate("clang", ["clang", "--version"])()
        self.assertEqual((tool.name, tool.version), ("clang", "18.1.3"))


class PathContainsTest(unittest.TestCase):
    def test_matches_normalised_entries(self):
        bin_dir = os.path.join(os.sep, "home", "u", "go", "bin")
        path = os.pathsep.join(["", os.path.join(os.sep, "usr", "bin"), bin_dir + os.sep])
        with mock.patch.dict("os.environ", {"PATH": path}):
            self.assertTrue(checks.path_contains(bin_dir))
            self.assertFalse(checks.path_contains(os.path.join(os.sep, "opt", "bin")))

    def test_empty_path(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(checks.path_contains("/usr/bin"))


if __name__ == "__main__":
    unittest.main()
