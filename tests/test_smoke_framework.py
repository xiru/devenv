"""smoke: the machinery shared by every --deep hello world test (each test itself lives with its language)."""

import unittest
from unittest import mock

from devenv_check import smoke
from devenv_check.checks import Status, ToolResult
from tests.helpers import LINUX, TempDirMixin, fail, ok


class BuildAndRunTest(TempDirMixin, unittest.TestCase):
    def build(self, *results, steps=2, expected="hello from Go", **kwargs):
        commands = [([f"step{i}"], 7) for i in range(steps)]
        with mock.patch.object(smoke, "run", side_effect=list(results)) as run:
            result = smoke.build_and_run("hello: Go", commands, expected, self.tmp, **kwargs)
        return result, run

    def test_success_requires_expected_output(self):
        result, run = self.build(ok(), ok("hello from Go"), env={"GOTOOLCHAIN": "local"}, detail="custom")
        self.assertEqual((result.status, result.kind, result.detail), (Status.OK, "hello", "custom"))
        self.assertEqual(result.output, "$ step0\n$ step1\nhello from Go")
        self.assertEqual(run.call_args.kwargs, {"timeout": 7, "cwd": self.tmp, "env": {"GOTOOLCHAIN": "local"}})

    def test_build_failure_stops_and_reports_the_error_line(self):
        result, run = self.build(fail("hello.c:1: warning: x\nhello.c:2: error: expected ';'"))
        self.assertIs(result.status, Status.MISSING)
        self.assertEqual(result.detail, "build failed: hello.c:2: error: expected ';'")
        self.assertEqual(run.call_count, 1)
        self.assertIn("error: expected", result.output)

    def test_failure_of_the_last_step_is_a_run_failure(self):
        result, _ = self.build(ok(), fail("segfault"))
        self.assertEqual(result.detail, "run failed: segfault")

    def test_unexpected_output(self):
        result, _ = self.build(ok("bonjour"), steps=1)
        self.assertIs(result.status, Status.MISSING)
        self.assertEqual(result.detail, "unexpected output: 'bonjour'")

    def test_expected_text_must_be_on_stdout(self):
        result, _ = self.build(ok("", "hello from Go"), steps=1)
        self.assertIs(result.status, Status.MISSING)

    def test_no_steps(self):
        result = smoke.build_and_run("hello", [], "x", self.tmp)
        self.assertIs(result.status, Status.MISSING)

    def test_log_keeps_only_the_tail(self):
        noisy = ok("\n".join(f"line {i}" for i in range(100)))
        result, _ = self.build(noisy, steps=1, expected="line 99")
        self.assertEqual(len(result.output.splitlines()), 20)
        self.assertTrue(result.output.endswith("line 99"))


class ErrorLineTest(unittest.TestCase):
    def test_prefers_a_line_mentioning_error(self):
        self.assertEqual(smoke._error_line(fail("note: x\nfatal ERROR: y")), "fatal ERROR: y")
        self.assertEqual(smoke._error_line(fail("note: x\nterror: no")), "note: x")  # whole words only

    def test_falls_back_to_the_exit_code(self):
        self.assertEqual(smoke._error_line(fail(returncode=2)), "exit code 2")

    def test_long_lines_are_shortened(self):
        line = smoke._error_line(fail("error: " + "x" * 300))
        self.assertEqual(len(line), 160)
        self.assertTrue(line.endswith("..."))


class WriteTest(TempDirMixin, unittest.TestCase):
    def test_creates_folders_and_keeps_lf_endings(self):
        path = smoke._write(self.tmp / "a" / "b" / "x.sh", "a\nb\n")
        self.assertEqual(path.read_bytes(), b"a\nb\n")  # bash rejects CRLF, also on Windows

    def test_crlf_content_is_written_as_given(self):
        path = smoke._write(self.tmp / "build.bat", "@echo off\r\nexit\r\n")
        self.assertEqual(path.read_bytes(), b"@echo off\r\nexit\r\n")


class HelpersTest(unittest.TestCase):
    def test_usable_needs_a_path_and_a_working_status(self):
        self.assertTrue(smoke._usable(ToolResult("go", Status.OK, path="/usr/bin/go")))
        self.assertTrue(smoke._usable(ToolResult("go", Status.WARN, path="/usr/bin/go")))
        self.assertFalse(smoke._usable(ToolResult("go", Status.OK)))
        self.assertFalse(smoke._usable(ToolResult("go", Status.MISSING, path="/usr/bin/go")))
        self.assertFalse(smoke._usable(None))

    def test_find(self):
        tools = [ToolResult("go", Status.OK), ToolResult("gofmt", Status.OK)]
        self.assertIs(smoke._find(tools, "gofmt"), tools[1])
        self.assertIsNone(smoke._find(tools, "rust"))

    def test_skipped(self):
        result = smoke._skipped("hello: Go", "go not available")
        self.assertEqual((result.status, result.kind, result.detail), (Status.SKIPPED, "hello", "skipped: go not available"))


class RunSmokeTest(unittest.TestCase):
    def test_unknown_environment_has_no_test(self):
        self.assertEqual(smoke.run_smoke("vscode", LINUX, []), [])

    def test_runs_in_a_temporary_folder_that_is_removed(self):
        seen = []

        def fake_test(p, tools, work):
            seen.append(work)
            self.assertTrue(work.is_dir())
            (work / "file.txt").write_text("x")
            return [ToolResult("hello: x", Status.OK, kind="hello")]

        with mock.patch.dict(smoke.SMOKE_TESTS, {"x": fake_test}):
            (result,) = smoke.run_smoke("x", LINUX, [])
        self.assertIs(result.status, Status.OK)
        self.assertTrue(seen[0].name.startswith("devenv-check-x-"))
        self.assertFalse(seen[0].exists())

    def test_a_crashing_test_is_reported(self):
        def boom(p, tools, work):
            raise ValueError("bad")

        with mock.patch.dict(smoke.SMOKE_TESTS, {"x": boom}):
            (result,) = smoke.run_smoke("x", LINUX, [])
        self.assertEqual((result.name, result.status, result.kind), ("hello: x", Status.MISSING, "hello"))
        self.assertIn("ValueError('bad')", result.detail)


if __name__ == "__main__":
    unittest.main()
