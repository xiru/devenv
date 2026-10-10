"""Perl: perl, the CPAN module installer, cpanminus and the strict/warnings hello world."""

import os
import unittest
from unittest import mock

from devenv_check import checks, smoke
from devenv_check.checks import Status
from devenv_check.runner import parse_version
from tests.helpers import LINUX, WINDOWS, TempDirMixin, fail, fake_system, ok, run_smoke, tool

PERL_V = "\nThis is perl 5, version 38, subversion 2 (v5.38.2) built for x86_64-linux-gnu-thread-multi\n"


class CheckPerlTest(unittest.TestCase):
    def check(self, cpan=ok("2.36"), cpanm=True, perl=PERL_V):
        outputs = {"perl": lambda args: cpan if "-MCPAN" in args else ok(perl)}
        if cpanm:
            outputs["cpanm"] = "cpanm (App::cpanminus) version 1.7047 (/usr/bin/cpanm)"
        with fake_system(outputs) as calls:
            tools = {t.name: t for t in checks.check_perl(LINUX)}
        return tools, calls

    def test_version_format(self):
        self.assertEqual(parse_version(PERL_V, r"\(v(\d+)\.(\d+)\.(\d+)\)"), (5, 38, 2))

    def test_perl_with_cpan_and_cpanm(self):
        tools, _ = self.check()
        self.assertEqual(tools["perl"].version, "5.38.2")
        self.assertEqual((tools["CPAN (module installer)"].status, tools["CPAN (module installer)"].version), (Status.OK, "2.36"))
        self.assertEqual(tools["cpanm (cpanminus)"].version, "1.7047")

    def test_cpan_is_probed_without_running_the_interactive_cpan_shell(self):
        _, commands = self.check()
        self.assertIn(["/usr/bin/perl", "-MCPAN", "-e", "print $CPAN::VERSION"], commands)
        self.assertFalse(any(command[0].endswith("/cpan") for command in commands))

    def test_missing_cpan_module_and_optional_cpanm(self):
        tools, _ = self.check(cpan=fail("Can't locate CPAN.pm in @INC"), cpanm=False)
        cpan = tools["CPAN (module installer)"]
        self.assertEqual((cpan.status, cpan.hint), (Status.MISSING, "cpan"))
        self.assertFalse(tools["cpanm (cpanminus)"].required)

    def test_old_perl_warns(self):
        tools, _ = self.check(perl="This is perl 5, version 30, subversion 0 (v5.30.0)")
        self.assertIs(tools["perl"].status, Status.WARN)

    def test_missing_perl(self):
        with fake_system({}):
            (perl,) = checks.check_perl(LINUX)
        self.assertEqual((perl.status, perl.hint), (Status.MISSING, "perl"))


class WindowsGitPerlTest(TempDirMixin, unittest.TestCase):
    def check(self):
        with mock.patch.object(checks, "which", return_value=None), \
             mock.patch.dict(os.environ, {"ProgramFiles": str(self.tmp)}):
            (perl,) = checks.check_perl(WINDOWS)
        return perl

    def test_points_past_git_for_windows_internal_perl(self):
        git_perl = self.tmp / "Git" / "usr" / "bin" / "perl.exe"
        git_perl.parent.mkdir(parents=True)
        git_perl.touch()
        perl = self.check()
        self.assertIs(perl.status, Status.MISSING)
        self.assertIn("Strawberry Perl", perl.detail)

    def test_no_perl_at_all(self):
        self.assertNotIn("Strawberry Perl", self.check().detail)


class PerlSmokeTest(unittest.TestCase):
    def test_syntax_check_then_run(self):
        smoke_run = run_smoke("perl", [tool("perl")], lambda args: "hello.pl syntax OK" if "-c" in args else "hello from Perl")
        self.assertIs(smoke_run.result.status, Status.OK)
        self.assertEqual(smoke_run.commands, [["/usr/bin/perl", "-c", "hello.pl"], ["/usr/bin/perl", "hello.pl"]])
        self.assertEqual(smoke_run.written["hello.pl"], smoke.PERL_SCRIPT)
        self.assertIn("use strict;", smoke.PERL_SCRIPT)

    def test_skipped_without_perl(self):
        self.assertIs(run_smoke("perl", [tool("perl", status=Status.MISSING)]).result.status, Status.SKIPPED)


if __name__ == "__main__":
    unittest.main()
