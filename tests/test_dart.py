"""Dart: the dart SDK (standalone or bundled with Flutter) and the native-executable hello world."""

import os
import unittest

from devenv_check import checks, install_hints
from devenv_check.checks import Status
from tests.helpers import LINUX, fake_system, ok, platform_for, run_smoke, tool


class CheckDartTest(unittest.TestCase):
    def test_bundled_with_flutter(self):
        with fake_system({"dart": 'Dart SDK version: 3.6.0 (stable) on "linux_x64"'}, where="/home/u/flutter/bin"):
            (dart,) = checks.check_dart(LINUX)
        self.assertEqual((dart.status, dart.version, dart.detail), (Status.OK, "3.6.0", "bundled with Flutter"))

    def test_standalone(self):
        with fake_system({"dart": 'Dart SDK version: 3.6.0 (stable)'}):
            (dart,) = checks.check_dart(LINUX)
        self.assertEqual(dart.detail, "")

    def test_old_dart_warns_even_on_stderr(self):
        with fake_system({"dart": ok("", "Dart SDK version: 2.19.6 (stable)")}):
            (dart,) = checks.check_dart(LINUX)
        self.assertIs(dart.status, Status.WARN)


class DartSmokeTest(unittest.TestCase):
    def test_compiles_a_native_executable(self):
        smoke_run = run_smoke("dart", [tool("dart")], "hello from Dart")
        self.assertIs(smoke_run.result.status, Status.OK)
        self.assertEqual(smoke_run.commands[0][1:4], ["compile", "exe", "hello.dart"])
        self.assertTrue(smoke_run.commands[1][0].endswith("hello" + (".exe" if os.name == "nt" else "")))

    def test_skipped_without_dart(self):
        self.assertIs(run_smoke("dart", [tool("dart", status=Status.MISSING)]).result.status, Status.SKIPPED)


class DartHintsTest(unittest.TestCase):
    def test_debian_repository_uses_the_architecture(self):
        lines = install_hints.hint_for("dart", platform_for("debian", arch="arm64"))
        self.assertTrue(any("arch=arm64" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
