import json
import unittest
from pathlib import Path
from unittest import mock

from devenv_check import checks, install_hints, smoke
from devenv_check.checks import Status, ToolResult
from devenv_check.platform_info import PlatformInfo
from devenv_check.runner import CommandResult

LINUX = PlatformInfo("linux", "debian", "Ubuntu", "amd64")

DOCTOR_UNICODE = """Doctor summary (to see all details, run flutter doctor -v):
[✓] Flutter (Channel stable, 3.27.1, on Ubuntu 24.04.1 LTS 6.8.0-49-generic, locale en_US.UTF-8)
[!] Android toolchain - develop for Android devices (Android SDK version 35.0.0)
    ✗ Android license status unknown.
[✗] Chrome - develop for the web (Cannot find Chrome executable at google-chrome)
[✓] Linux toolchain - develop for Linux desktop
[✓] Connected device (1 available)
[✓] Network resources

! Doctor found issues in 2 categories.
"""

DOCTOR_WINDOWS_LEGACY = """[√] Flutter (Channel stable, 3.27.1, on Microsoft Windows [Version 10.0.26300], locale pt-BR)
[X] Visual Studio - develop Windows apps
[√] Chrome - develop for the web
"""

FLUTTER_MACHINE = {"frameworkVersion": "3.27.1", "channel": "stable", "dartSdkVersion": "3.6.0"}


def ok(stdout="", stderr=""):
    return CommandResult(True, stdout, stderr, 0)


class DartCheckTest(unittest.TestCase):
    def test_dart_version_and_flutter_bundle(self):
        with mock.patch.object(checks, "which", return_value="/home/u/flutter/bin/dart"), \
             mock.patch.object(checks, "run", return_value=ok("Dart SDK version: 3.6.0 (stable) on \"linux_x64\"")):
            (dart,) = checks.check_dart(LINUX)
        self.assertEqual((dart.status, dart.version), (Status.OK, "3.6.0"))
        self.assertEqual(dart.detail, "bundled with Flutter")

    def test_old_dart_warns(self):
        with mock.patch.object(checks, "which", return_value="/usr/bin/dart"), \
             mock.patch.object(checks, "run", return_value=ok("", "Dart SDK version: 2.19.6 (stable)")):
            (dart,) = checks.check_dart(LINUX)
        self.assertIs(dart.status, Status.WARN)


class FlutterParsingTest(unittest.TestCase):
    def test_machine_version_after_banner(self):
        output = "  Welcome to Flutter! ...\n" + json.dumps(FLUTTER_MACHINE, indent=2)
        self.assertEqual(checks.flutter_version(output)["frameworkVersion"], "3.27.1")
        self.assertEqual(checks.flutter_version("no json here"), {})

    def test_doctor_unicode(self):
        rows = {t.name: t for t in checks.parse_flutter_doctor(DOCTOR_UNICODE)}
        self.assertNotIn("doctor: Flutter", rows)
        self.assertIs(rows["doctor: Android toolchain"].status, Status.WARN)
        self.assertIs(rows["doctor: Chrome"].status, Status.MISSING)
        self.assertIn("Cannot find Chrome", rows["doctor: Chrome"].detail)
        self.assertIs(rows["doctor: Linux toolchain"].status, Status.OK)
        self.assertIs(rows["doctor: Connected device"].status, Status.OK)
        self.assertTrue(all(not t.required for t in rows.values()))
        self.assertEqual(rows["doctor: Chrome"].hint, "flutter_doctor")

    def test_doctor_windows_legacy_marks(self):
        rows = {t.name: t for t in checks.parse_flutter_doctor(DOCTOR_WINDOWS_LEGACY)}
        self.assertIs(rows["doctor: Visual Studio"].status, Status.MISSING)
        self.assertIs(rows["doctor: Chrome"].status, Status.OK)


class FlutterCheckTest(unittest.TestCase):
    def run_check(self, version_output, doctor_output=DOCTOR_UNICODE):
        def fake_run(args, **kwargs):
            return ok(version_output) if "--version" in args else ok(doctor_output)

        with mock.patch.object(checks, "which", return_value="/home/u/flutter/bin/flutter"), \
             mock.patch.object(checks, "run", side_effect=fake_run):
            return checks.check_flutter(LINUX)

    def test_installed(self):
        flutter, *doctor = self.run_check(json.dumps(FLUTTER_MACHINE))
        self.assertEqual((flutter.status, flutter.version), (Status.OK, "3.27.1"))
        self.assertIn("Dart 3.6.0", flutter.detail)
        self.assertEqual(len(doctor), 5)
        env = checks.EnvResult("flutter", "Flutter", [flutter, *doctor])
        self.assertIs(env.status, Status.WARN)  # doctor issues never make Flutter "missing"

    def test_broken_install(self):
        (flutter,) = self.run_check("Error: Unable to find git in your PATH.")
        self.assertIs(flutter.status, Status.MISSING)
        self.assertIn("git", flutter.detail)

    def test_not_installed(self):
        with mock.patch.object(checks, "which", return_value=None):
            (flutter,) = checks.check_flutter(LINUX)
        self.assertIs(flutter.status, Status.MISSING)
        self.assertEqual(flutter.hint, "flutter")


class SmokeTest(unittest.TestCase):
    def capture(self, key, tools, stdout):
        calls = []

        def fake_run(args, timeout=30, cwd=None, **kwargs):
            calls.append(args)
            return ok(stdout)

        with mock.patch.object(smoke, "run", side_effect=fake_run):
            (result,) = smoke.run_smoke(key, LINUX, tools)
        return result, calls

    def test_dart_compiles_native_executable(self):
        result, calls = self.capture("dart", [ToolResult("dart", Status.OK, path="/usr/bin/dart")], "hello from Dart")
        self.assertIs(result.status, Status.OK)
        self.assertEqual(calls[0][1:3], ["compile", "exe"])
        self.assertTrue(calls[1][0].endswith("hello" + smoke.EXE))

    def test_flutter_creates_and_tests_in_one_folder(self):
        result, calls = self.capture("flutter", [ToolResult("flutter", Status.OK, path="/opt/flutter/bin/flutter")],
                                     "00:02 +1: All tests passed!")
        self.assertIs(result.status, Status.OK)
        self.assertEqual(calls[0][1], "create")
        self.assertEqual(calls[0][-1], ".")
        self.assertEqual(calls[1][1], "test")

    def test_flutter_skipped_when_missing(self):
        result, _ = self.capture("flutter", [ToolResult("flutter", Status.MISSING)], "")
        self.assertIs(result.status, Status.SKIPPED)


class HintsTest(unittest.TestCase):
    def test_debian_dart_repo_uses_arch(self):
        lines = install_hints.hint_for("dart", PlatformInfo("linux", "debian", "Ubuntu", "arm64"))
        self.assertTrue(any("arch=arm64" in line for line in lines))

    def test_wsl_flutter_explains_targets(self):
        lines = install_hints.hint_for("flutter", PlatformInfo("linux", "debian", "Ubuntu (WSL)", "amd64", wsl=True))
        self.assertTrue(any("Windows" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
