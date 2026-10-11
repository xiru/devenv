"""cli: argument parsing, environment selection (--only / --favorites), output modes and exit codes."""

import json
import runpy
import unittest
from unittest import mock

from devenv_check import __version__, checks, cli
from devenv_check.checks import ENVIRONMENTS, EnvResult, Status, ToolResult
from tests.helpers import LINUX


def parse(*argv, environ=None):
    with mock.patch.dict("os.environ", environ or {}, clear=True):
        return cli.parse_args(list(argv))


class SelectionTest(unittest.TestCase):
    def test_everything_by_default(self):
        self.assertIsNone(parse().only)

    def test_only(self):
        self.assertEqual(parse("--only", " Go,java ,,").only, ["go", "java"])

    def test_unknown_or_empty_only_is_rejected(self):
        for value in ("cobol", "go,cobol", ","):
            with self.subTest(value=value), mock.patch("sys.stderr"), self.assertRaises(SystemExit):
                parse("--only", value)

    def test_default_favorites(self):
        self.assertEqual(parse("--favorites").only, ["python", "go", "java", "node"])
        self.assertLessEqual(set(cli.DEFAULT_FAVORITES), set(ENVIRONMENTS))

    def test_favorites_from_the_environment(self):
        self.assertEqual(parse("--favorites", environ={"DEVENV_CHECK_FAVORITES": "Docker, kotlin"}).only, ["docker", "kotlin"])

    def test_bad_favorites_are_reported(self):
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            parse("--favorites", environ={"DEVENV_CHECK_FAVORITES": "python,cobol"})

    def test_favorites_and_only_are_exclusive(self):
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            parse("--favorites", "--only", "go")

    def test_version(self):
        with mock.patch("sys.stdout") as stdout, self.assertRaises(SystemExit) as exit_:
            parse("--version")
        self.assertEqual(exit_.exception.code, 0)
        self.assertIn(__version__, "".join(call.args[0] for call in stdout.write.call_args_list))


class MainTest(unittest.TestCase):
    def setUp(self):
        offline = checks.SETTINGS.offline
        self.addCleanup(setattr, checks.SETTINGS, "offline", offline)

    def run_main(self, *argv, status=Status.OK, environ=None):
        results = [EnvResult(key, title, [ToolResult("t", status, hint="go")]) for key, (title, _) in ENVIRONMENTS.items()]
        with mock.patch.dict("os.environ", environ or {}, clear=True), \
             mock.patch.object(cli, "detect", return_value=LINUX), \
             mock.patch.object(cli, "run_checks", return_value=results) as run_checks, \
             mock.patch("builtins.print") as printed:
            code = cli.main(list(argv))
        return code, printed, run_checks

    def test_exit_codes(self):
        self.assertEqual(self.run_main("--no-color", status=Status.OK)[0], 0)
        self.assertEqual(self.run_main("--no-color", status=Status.WARN)[0], 0)
        self.assertEqual(self.run_main("--no-color", "--strict", status=Status.WARN)[0], 1)
        self.assertEqual(self.run_main("--no-color", status=Status.MISSING)[0], 1)

    def test_text_output(self):
        _, printed, run_checks = self.run_main("--no-color", "--only", "go")
        self.assertIn("Development environment check", printed.call_args.args[0])
        self.assertEqual(run_checks.call_args.args, (LINUX, ["go"]))
        self.assertEqual(run_checks.call_args.kwargs, {"deep": False})

    def test_no_hints(self):
        _, printed, _ = self.run_main("--no-color", "--no-hints", status=Status.MISSING)
        self.assertNotIn("How to fix", printed.call_args.args[0])

    def test_json_output(self):
        _, printed, _ = self.run_main("--json", status=Status.MISSING)
        data = json.loads(printed.call_args.args[0])
        self.assertEqual(len(data["environments"]), len(ENVIRONMENTS))
        self.assertEqual(data["environments"][0]["status"], "missing")
        self.assertEqual(data["environments"][0]["fix"][0]["hint"], "go")

    def test_deep_announces_the_slow_run_except_in_json_mode(self):
        _, printed, run_checks = self.run_main("--deep", "--no-color")
        self.assertIn("this can take a few minutes", printed.call_args_list[0].args[0])
        self.assertEqual(run_checks.call_args.kwargs, {"deep": True})
        _, printed, _ = self.run_main("--deep", "--json")
        self.assertEqual(len(printed.call_args_list), 1)

    def test_offline_setting(self):
        self.run_main("--offline", "--no-color")
        self.assertTrue(checks.SETTINGS.offline)
        self.run_main("--no-color")
        self.assertFalse(checks.SETTINGS.offline)

    def test_favorites(self):
        _, _, run_checks = self.run_main("--favorites", "--no-color")
        self.assertEqual(run_checks.call_args.args[1], ["python", "go", "java", "node"])


class ModuleEntryPointTest(unittest.TestCase):
    def test_python_dash_m_exits_with_mains_code(self):
        with mock.patch.object(cli, "main", return_value=1), self.assertRaises(SystemExit) as exit_:
            runpy.run_module("devenv_check", run_name="__main__")
        self.assertEqual(exit_.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
