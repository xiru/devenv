import unittest
from pathlib import Path
from unittest import mock

from devenv_check import checks, cli, smoke
from devenv_check.checks import ENVIRONMENTS, Status, ToolResult
from devenv_check.platform_info import PlatformInfo
from devenv_check.runner import CommandResult, parse_version

LINUX = PlatformInfo("linux", "debian", "Ubuntu", "amd64")
WINDOWS = PlatformInfo("windows", "windows", "Windows 11", "amd64")
PERL_V = "\nThis is perl 5, version 38, subversion 2 (v5.38.2) built for x86_64-linux-gnu-thread-multi\n"


def ok(stdout="", stderr=""):
    return CommandResult(True, stdout, stderr, 0)


class PerlCheckTest(unittest.TestCase):
    def test_version_format(self):
        self.assertEqual(parse_version(PERL_V, r"\(v(\d+)\.(\d+)\.(\d+)\)"), (5, 38, 2))

    def run_check(self, cpan_result, cpanm=True):
        def which(name):
            if Path(name).name == "cpanm" and not cpanm:
                return None
            return f"/usr/bin/{Path(name).name}"

        def run(args, **kwargs):
            if "-MCPAN" in args:
                return cpan_result
            if Path(args[0]).name == "cpanm":
                return ok("cpanm (App::cpanminus) version 1.7047 (/usr/bin/cpanm)")
            return ok(PERL_V)

        with mock.patch.object(checks, "which", side_effect=which), mock.patch.object(checks, "run", side_effect=run):
            return {t.name: t for t in checks.check_perl(LINUX)}

    def test_perl_with_cpan_and_cpanm(self):
        tools = self.run_check(ok("2.36"))
        self.assertEqual(tools["perl"].version, "5.38.2")
        self.assertIs(tools["CPAN (module installer)"].status, Status.OK)
        self.assertEqual(tools["cpanm (cpanminus)"].version, "1.7047")

    def test_cpan_is_probed_without_running_the_cpan_shell(self):
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            return ok(PERL_V if "-v" in args else "2.36")

        with mock.patch.object(checks, "which", side_effect=lambda n: f"/usr/bin/{Path(n).name}"), \
             mock.patch.object(checks, "run", side_effect=run):
            checks.check_perl(LINUX)
        self.assertFalse(any(Path(call[0]).name == "cpan" for call in calls))

    def test_missing_cpan_module(self):
        tools = self.run_check(CommandResult(False, "", "Can't locate CPAN.pm in @INC", 2), cpanm=False)
        self.assertIs(tools["CPAN (module installer)"].status, Status.MISSING)
        self.assertEqual(tools["CPAN (module installer)"].hint, "cpan")
        self.assertFalse(tools["cpanm (cpanminus)"].required)

    def test_windows_points_past_git_internal_perl(self):
        with mock.patch.object(checks, "which", return_value=None), \
             mock.patch.object(checks.Path, "is_file", return_value=True):
            (perl,) = checks.check_perl(WINDOWS)
        self.assertIs(perl.status, Status.MISSING)
        self.assertIn("Strawberry Perl", perl.detail)

    def test_smoke_syntax_checks_then_runs(self):
        calls = []

        def run(args, timeout=30, **kwargs):
            calls.append(args)
            return ok("hello.pl syntax OK" if "-c" in args else "hello from Perl")

        with mock.patch.object(smoke, "run", side_effect=run):
            (result,) = smoke.run_smoke("perl", LINUX, [ToolResult("perl", Status.OK, path="/usr/bin/perl")])
        self.assertIs(result.status, Status.OK)
        self.assertEqual(calls, [["/usr/bin/perl", "-c", "hello.pl"], ["/usr/bin/perl", "hello.pl"]])
        self.assertIn("use strict;", smoke.PERL_SCRIPT)


class FavoritesTest(unittest.TestCase):
    def test_default_favorites(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            args = cli.parse_args(["--favorites"])
        self.assertEqual(args.only, ["python", "go", "java"])
        self.assertTrue(set(cli.DEFAULT_FAVORITES) <= set(ENVIRONMENTS))

    def test_environment_variable_overrides(self):
        with mock.patch.dict("os.environ", {"DEVENV_CHECK_FAVORITES": "Rust, perl"}):
            self.assertEqual(cli.parse_args(["--favorites"]).only, ["rust", "perl"])

    def test_bad_environment_variable_is_reported(self):
        with mock.patch.dict("os.environ", {"DEVENV_CHECK_FAVORITES": "python,cobol"}), \
             mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            cli.parse_args(["--favorites"])

    def test_cannot_combine_with_only(self):
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            cli.parse_args(["--favorites", "--only", "go"])

    def test_main_runs_only_favorites(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
             mock.patch.object(cli, "run_checks", return_value=[]) as run_checks, \
             mock.patch("builtins.print"):
            cli.main(["--favorites", "--no-color"])
        self.assertEqual(run_checks.call_args.args[1], ["python", "go", "java"])


if __name__ == "__main__":
    unittest.main()
