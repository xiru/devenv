"""PHP + Composer: php, composer and the PSR-4 autoload hello world."""

import json
import unittest

from devenv_check import checks, install_hints
from devenv_check.checks import Status
from devenv_check.runner import parse_version
from tests.helpers import LINUX, WINDOWS, fake_system, run_smoke, tool

COMPOSER_VERSION = r"Composer (?:version )?(\d+)\.(\d+)\.(\d+)"


class CheckPhpTest(unittest.TestCase):
    def test_version_formats(self):
        self.assertEqual(parse_version("PHP 8.3.6 (cli) (built: Apr 15 2024 19:21:47) (NTS)", r"PHP (\d+)\.(\d+)\.(\d+)"), (8, 3, 6))
        self.assertEqual(parse_version("Composer version 2.8.4 2024-12-11 11:57:47", COMPOSER_VERSION), (2, 8, 4))
        self.assertEqual(parse_version("Composer 2.9.1 2026-01-02", COMPOSER_VERSION), (2, 9, 1))

    def test_php_and_composer(self):
        with fake_system({"php": "PHP 8.4.2 (cli)", "composer": "Composer version 2.8.4 2024-12-11"}) as calls:
            php, composer = checks.check_php(LINUX)
        self.assertEqual((php.status, php.version), (Status.OK, "8.4.2"))
        self.assertEqual((composer.status, composer.version), (Status.OK, "2.8.4"))
        self.assertIn("--no-ansi", calls[1])  # keeps the output parseable

    def test_old_php_warns_and_missing_composer_fails(self):
        with fake_system({"php": "PHP 7.4.33 (cli)"}):
            php, composer = checks.check_php(LINUX)
        self.assertIs(php.status, Status.WARN)
        self.assertEqual((composer.status, composer.hint), (Status.MISSING, "composer"))


class PhpSmokeTest(unittest.TestCase):
    def test_composer_autoloader(self):
        smoke_run = run_smoke("php", [tool("php"), tool("composer")], "hello from PHP")
        self.assertEqual((smoke_run.result.name, smoke_run.result.status), ("hello: PHP + Composer autoload", Status.OK))
        dump, run = smoke_run.calls
        self.assertEqual(dump.args[1], "dump-autoload")
        self.assertEqual(dump.env, {"COMPOSER_NO_INTERACTION": "1"})
        self.assertEqual(run.args, ["/usr/bin/php", "hello.php"])
        self.assertEqual(json.loads(smoke_run.written["composer.json"])["autoload"]["psr-4"], {"Hello\\": "src/"})
        self.assertIn("vendor/autoload.php", smoke_run.written["hello.php"])
        self.assertIn("namespace Hello;", smoke_run.written["Greeter.php"])

    def test_without_composer_php_still_runs(self):
        smoke_run = run_smoke("php", [tool("php"), tool("composer", status=Status.MISSING)], "hello from PHP")
        self.assertEqual((smoke_run.result.name, smoke_run.result.status), ("hello: PHP", Status.OK))
        self.assertEqual(smoke_run.commands, [["/usr/bin/php", "hello.php"]])
        self.assertIn("src/Greeter.php", smoke_run.written["hello.php"])

    def test_skipped_without_php(self):
        self.assertIs(run_smoke("php", [tool("php", status=Status.MISSING)]).result.status, Status.SKIPPED)


class PhpHintsTest(unittest.TestCase):
    def test_windows(self):
        self.assertIn("PHP.PHP.8.5", " ".join(install_hints.hint_for("php", WINDOWS)))
        self.assertIn("Composer-Setup.exe", " ".join(install_hints.hint_for("composer", WINDOWS)))


if __name__ == "__main__":
    unittest.main()
