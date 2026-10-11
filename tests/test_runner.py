"""runner: running commands, PATH lookup and version parsing."""

import os
import sys
import unittest

from devenv_check.runner import GENERIC_VERSION, CommandResult, first_line, format_version, parse_version, run, which
from tests.helpers import TempDirMixin


def python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


class CommandResultTest(unittest.TestCase):
    def test_output_joins_stdout_and_stderr(self):
        self.assertEqual(CommandResult(True, "out", "err", 0).output, "out\nerr")
        self.assertEqual(CommandResult(True, "", "err", 0).output, "err")
        self.assertEqual(CommandResult(True, "out", "", 0).output, "out")
        self.assertEqual(CommandResult(False, "", "", 1).output, "")


class RunTest(TempDirMixin, unittest.TestCase):
    def test_success_captures_stdout_and_stderr(self):
        result = run(python("import sys; print('hello'); print('warning', file=sys.stderr)"))
        self.assertTrue(result.ok)
        self.assertEqual((result.stdout, result.stderr, result.returncode), ("hello", "warning", 0))

    def test_non_zero_exit_is_not_ok(self):
        result = run(python("import sys; sys.exit(3)"))
        self.assertFalse(result.ok)
        self.assertEqual(result.returncode, 3)

    def test_missing_executable_never_raises(self):
        result = run([os.path.join(str(self.tmp), "no-such-tool")])
        self.assertFalse(result.ok)
        self.assertIsNone(result.returncode)
        self.assertTrue(result.stderr)

    def test_timeout_never_raises(self):
        result = run(python("import time; time.sleep(10)"), timeout=0.5)
        self.assertFalse(result.ok)
        self.assertIsNone(result.returncode)
        self.assertEqual(result.stderr, "timed out after 0.5s")

    def test_keeps_leading_blank_lines(self):
        # `go env GOBIN GOPATH` prints an empty first line when GOBIN is unset.
        result = run(python("print(); print('/home/u/go')"))
        self.assertEqual(result.stdout.splitlines(), ["", "/home/u/go"])

    def test_cwd(self):
        result = run(python("import os; print(os.getcwd())"), cwd=self.tmp)
        self.assertEqual(os.path.realpath(result.stdout), os.path.realpath(self.tmp))

    def test_env_is_layered_on_the_current_environment(self):
        code = "import os; print(os.environ['DEVENV_TEST_VAR'], 'PATH' in os.environ)"
        result = run(python(code), env={"DEVENV_TEST_VAR": "layered"})
        self.assertEqual(result.stdout, "layered True")

    def test_stdin_is_closed(self):
        # A tool waiting for input must not hang the check.
        result = run(python("import sys; print(repr(sys.stdin.read()))"), timeout=10)
        self.assertEqual(result.stdout, "''")

    def test_undecodable_output_is_replaced(self):
        result = run(python("import sys; sys.stdout.buffer.write(b'caf\\xe9')"))
        self.assertTrue(result.ok)
        self.assertTrue(result.stdout.startswith("caf"))


class WhichTest(unittest.TestCase):
    def test_finds_the_running_python_and_misses_unknown_tools(self):
        self.assertIsNotNone(which(sys.executable))
        self.assertIsNone(which("devenv-check-no-such-tool"))


class ParseVersionTest(unittest.TestCase):
    def test_generic_pattern(self):
        self.assertEqual(parse_version("GNU Make 4.4.1"), (4, 4, 1))
        self.assertEqual(parse_version("v22.3.0"), (22, 3, 0))
        self.assertEqual(parse_version("helm v3.16"), (3, 16))
        self.assertIsNone(parse_version("no digits here"))
        self.assertIsNone(parse_version(""))
        self.assertIsNone(parse_version(None))

    def test_first_match_wins(self):
        self.assertEqual(parse_version("tool 1.2.3 (built with lib 9.9.9)", GENERIC_VERSION), (1, 2, 3))

    def test_optional_groups_are_dropped(self):
        self.assertEqual(parse_version("go version go1.22 linux/amd64", r"go(\d+)\.(\d+)(?:\.(\d+))?"), (1, 22))

    def test_custom_pattern(self):
        self.assertEqual(parse_version("go version go1.22.4 linux/amd64", r"go(\d+)\.(\d+)(?:\.(\d+))?"), (1, 22, 4))


class FormattingTest(unittest.TestCase):
    def test_format_version(self):
        self.assertEqual(format_version((1, 22, 4)), "1.22.4")
        self.assertEqual(format_version((27,)), "27")
        self.assertIsNone(format_version(None))
        self.assertIsNone(format_version(()))

    def test_first_line_skips_blank_lines(self):
        self.assertEqual(first_line("\n\n  error: boom  \nmore"), "error: boom")
        self.assertEqual(first_line(""), "")
        self.assertEqual(first_line(None), "")


if __name__ == "__main__":
    unittest.main()
