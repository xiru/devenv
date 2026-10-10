"""Flutter: the SDK version, every `flutter doctor` validator and the template widget-test hello world."""

import json
import unittest
from unittest import mock

from devenv_check import checks, install_hints
from devenv_check.checks import Status
from tests.helpers import LINUX, WSL, ok, run_smoke, tool

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
[?] Something new
"""

FLUTTER_MACHINE = {"frameworkVersion": "3.27.1", "channel": "stable", "dartSdkVersion": "3.6.0"}


class VersionParsingTest(unittest.TestCase):
    def test_machine_version_after_a_banner(self):
        output = "  Welcome to Flutter! ...\n" + json.dumps(FLUTTER_MACHINE, indent=2)
        self.assertEqual(checks.flutter_version(output)["frameworkVersion"], "3.27.1")

    def test_garbage(self):
        self.assertEqual(checks.flutter_version("no json here"), {})
        self.assertEqual(checks.flutter_version("{not json}"), {})
        self.assertEqual(checks.flutter_version("} {"), {})


class DoctorParsingTest(unittest.TestCase):
    def test_unicode_marks(self):
        rows = {t.name: t for t in checks.parse_flutter_doctor(DOCTOR_UNICODE)}
        self.assertNotIn("doctor: Flutter", rows)  # the SDK itself is the main row
        self.assertIs(rows["doctor: Android toolchain"].status, Status.WARN)
        self.assertIs(rows["doctor: Chrome"].status, Status.MISSING)
        self.assertIn("Cannot find Chrome", rows["doctor: Chrome"].detail)
        self.assertIs(rows["doctor: Linux toolchain"].status, Status.OK)
        self.assertIs(rows["doctor: Connected device"].status, Status.OK)
        self.assertTrue(all(not t.required for t in rows.values()))
        self.assertEqual(rows["doctor: Chrome"].hint, "flutter_doctor")
        self.assertIsNone(rows["doctor: Network resources"].hint)

    def test_windows_legacy_marks(self):
        rows = {t.name: t for t in checks.parse_flutter_doctor(DOCTOR_WINDOWS_LEGACY)}
        self.assertIs(rows["doctor: Visual Studio"].status, Status.MISSING)
        self.assertIs(rows["doctor: Chrome"].status, Status.OK)
        self.assertIs(rows["doctor: Something new"].status, Status.WARN)  # unknown marks are not "ok"


class CheckFlutterTest(unittest.TestCase):
    def check(self, version_output, doctor_output=DOCTOR_UNICODE):
        def fake_run(args, **kwargs):
            return ok(version_output) if "--version" in args else ok(doctor_output)

        with mock.patch.object(checks, "which", return_value="/home/u/flutter/bin/flutter"), \
             mock.patch.object(checks, "run", side_effect=fake_run):
            return checks.check_flutter(LINUX)

    def test_installed(self):
        flutter, *doctor = self.check(json.dumps(FLUTTER_MACHINE))
        self.assertEqual((flutter.status, flutter.version), (Status.OK, "3.27.1"))
        self.assertEqual(flutter.detail, "channel stable, Dart 3.6.0")
        self.assertEqual(len(doctor), 5)
        env = checks.EnvResult("flutter", "Flutter", [flutter, *doctor])
        self.assertIs(env.status, Status.WARN)  # doctor issues never make Flutter "missing"

    def test_old_flutter_warns(self):
        flutter, *_ = self.check(json.dumps({"frameworkVersion": "3.19.6"}))
        self.assertIs(flutter.status, Status.WARN)
        self.assertIn("channel ?, Dart ?; older than recommended 3.22", flutter.detail)

    def test_unreadable_doctor_output(self):
        _, doctor = self.check(json.dumps(FLUTTER_MACHINE), "Waiting for another flutter command to release the startup lock...")
        self.assertEqual((doctor.name, doctor.status, doctor.hint), ("doctor", Status.WARN, "flutter_doctor"))
        self.assertIn("startup lock", doctor.detail)

    def test_broken_install(self):
        (flutter,) = self.check("Error: Unable to find git in your PATH.")
        self.assertIs(flutter.status, Status.MISSING)
        self.assertIn("git", flutter.detail)

    def test_no_output(self):
        (flutter,) = self.check("")
        self.assertIn("no output", flutter.detail)

    def test_not_installed(self):
        with mock.patch.object(checks, "which", return_value=None):
            (flutter,) = checks.check_flutter(LINUX)
        self.assertEqual((flutter.status, flutter.hint), (Status.MISSING, "flutter"))


class FlutterSmokeTest(unittest.TestCase):
    def test_creates_the_template_app_and_runs_its_widget_test(self):
        smoke_run = run_smoke("flutter", [tool("flutter")], "00:02 +1: All tests passed!")
        self.assertIs(smoke_run.result.status, Status.OK)
        create, test = smoke_run.commands
        self.assertEqual((create[1], create[-1]), ("create", "."))
        self.assertIn("--no-pub", create)
        self.assertEqual(test[1], "test")

    def test_skipped_without_flutter(self):
        self.assertIs(run_smoke("flutter", [tool("flutter", status=Status.MISSING)]).result.status, Status.SKIPPED)


class FlutterHintsTest(unittest.TestCase):
    def test_wsl_explains_which_targets_work(self):
        self.assertTrue(any("Windows" in line for line in install_hints.hint_for("flutter", WSL)))


if __name__ == "__main__":
    unittest.main()
