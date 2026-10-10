import json
import unittest
from pathlib import Path
from unittest import mock

from devenv_check import checks, install_hints, smoke
from devenv_check.checks import Status, ToolResult
from devenv_check.platform_info import PlatformInfo
from devenv_check.runner import CommandResult, parse_version

LINUX = PlatformInfo("linux", "debian", "Ubuntu", "amd64")
MACOS = PlatformInfo("macos", "macos", "macOS 15", "arm64")
WINDOWS = PlatformInfo("windows", "windows", "Windows 11", "amd64")


def ok(stdout="", stderr=""):
    return CommandResult(True, stdout, stderr, 0)


def fake_tools(outputs: dict[str, str]):
    """Patch which/run so each tool name prints the given output."""
    def which(name):
        return f"/usr/bin/{Path(name).name}" if Path(name).name in outputs else None

    def run(args, **kwargs):
        return ok(outputs[Path(args[0]).name])

    return mock.patch.object(checks, "which", side_effect=which), mock.patch.object(checks, "run", side_effect=run)


class VersionFormatsTest(unittest.TestCase):
    def test_outputs(self):
        self.assertEqual(parse_version("PHP 8.3.6 (cli) (built: Apr 15 2024 19:21:47) (NTS)", r"PHP (\d+)\.(\d+)\.(\d+)"), (8, 3, 6))
        composer = r"Composer (?:version )?(\d+)\.(\d+)\.(\d+)"
        self.assertEqual(parse_version("Composer version 2.8.4 2024-12-11 11:57:47", composer), (2, 8, 4))
        self.assertEqual(parse_version("Composer 2.9.1 2026-01-02", composer), (2, 9, 1))
        self.assertEqual(parse_version("ruby 3.4.1 (2024-12-25 revision 48d4efcb85) +PRISM [x86_64-linux]", r"ruby (\d+)\.(\d+)\.(\d+)"), (3, 4, 1))
        self.assertEqual(parse_version("Bundler version 2.6.2", r"Bundler version (\d+)\.(\d+)\.(\d+)"), (2, 6, 2))
        ridk = "---\nruby:\n  path: C:/Ruby40-x64\n  version: 4.0.7\n  platform: x64-mingw-ucrt\nmsys2:\n  path: C:\\Ruby40-x64\\msys64\n"
        self.assertEqual(parse_version(ridk, r"version: (\d+)\.(\d+)\.(\d+)"), (4, 0, 7))


class CheckPhpTest(unittest.TestCase):
    def test_php_and_composer(self):
        which, run = fake_tools({"php": "PHP 8.4.2 (cli)", "composer": "Composer version 2.8.4 2024-12-11"})
        with which, run:
            php, composer = checks.check_php(LINUX)
        self.assertEqual((php.status, php.version), (Status.OK, "8.4.2"))
        self.assertEqual((composer.status, composer.version), (Status.OK, "2.8.4"))

    def test_old_php_warns_and_missing_composer_fails(self):
        which, run = fake_tools({"php": "PHP 7.4.33 (cli)"})
        with which, run:
            php, composer = checks.check_php(LINUX)
        self.assertIs(php.status, Status.WARN)
        self.assertIs(composer.status, Status.MISSING)
        self.assertEqual(composer.hint, "composer")


class CheckRubyTest(unittest.TestCase):
    def test_ruby_gem_bundler(self):
        which, run = fake_tools({"ruby": "ruby 3.4.1 (2024-12-25)", "gem": "3.6.2", "bundle": "Bundler version 2.6.2"})
        with which, run:
            tools = {t.name: t for t in checks.check_ruby(LINUX)}
        self.assertEqual(tools["ruby"].version, "3.4.1")
        self.assertEqual(tools["gem (RubyGems)"].version, "3.6.2")
        self.assertEqual(tools["bundler"].version, "2.6.2")
        self.assertNotIn("ridk (MSYS2 devkit)", tools)  # Windows only

    def test_macos_system_ruby(self):
        which, run = fake_tools({"ruby": "ruby 2.6.10p210 (2022-04-12 revision 67958)", "gem": "3.0.3.1", "bundle": "Bundler version 1.17.2"})
        with which, run:
            ruby = checks.check_ruby(MACOS)[0]
        self.assertIs(ruby.status, Status.WARN)
        self.assertIn("Homebrew", ruby.detail)

    def test_windows_offers_ridk(self):
        which, run = fake_tools({"ruby": "ruby 4.0.7", "gem": "4.0.1", "bundle": "Bundler version 4.0.1"})
        with which, run:
            tools = {t.name: t for t in checks.check_ruby(WINDOWS)}
        self.assertFalse(tools["ridk (MSYS2 devkit)"].required)
        self.assertEqual(tools["ridk (MSYS2 devkit)"].hint, "ridk")


class SmokeTest(unittest.TestCase):
    def capture(self, key, tools, stdout):
        calls, envs = [], []

        def fake_run(args, timeout=30, cwd=None, env=None, **kwargs):
            calls.append(args)
            envs.append(env or {})
            return ok(stdout)

        with mock.patch.object(smoke, "run", side_effect=fake_run):
            (result,) = smoke.run_smoke(key, LINUX, tools)
        return result, calls, envs

    def test_php_uses_composer_autoloader(self):
        tools = [ToolResult("php", Status.OK, path="/usr/bin/php"), ToolResult("composer", Status.OK, path="/usr/bin/composer")]
        written = {}
        real_write = smoke._write

        def spy(path, text):
            written[path.name] = text
            return real_write(path, text)

        with mock.patch.object(smoke, "_write", side_effect=spy):
            result, calls, _ = self.capture("php", tools, "hello from PHP")
        self.assertIs(result.status, Status.OK)
        self.assertEqual(calls[0][1], "dump-autoload")
        self.assertEqual(calls[1], ["/usr/bin/php", "hello.php"])
        self.assertEqual(json.loads(written["composer.json"])["autoload"]["psr-4"], {"Hello\\": "src/"})
        self.assertIn("vendor/autoload.php", written["hello.php"])

    def test_php_without_composer_still_runs_php(self):
        result, calls, _ = self.capture("php", [ToolResult("php", Status.OK, path="/usr/bin/php"),
                                                ToolResult("composer", Status.MISSING)], "hello from PHP")
        self.assertIs(result.status, Status.OK)
        self.assertEqual(result.name, "hello: PHP")

    def test_ruby_bundle_install_is_local_and_isolated(self):
        tools = [ToolResult("ruby", Status.OK, path="/usr/bin/ruby"), ToolResult("bundler", Status.OK, path="/usr/bin/bundle")]
        result, calls, envs = self.capture("ruby", tools, "hello from Ruby")
        self.assertIs(result.status, Status.OK)
        self.assertEqual(calls[0][1:], ["install", "--local", "--quiet"])
        self.assertEqual(calls[1][1:], ["exec", "ruby", "hello.rb"])
        self.assertTrue(envs[0]["BUNDLE_GEMFILE"].endswith("Gemfile"))

    def test_ruby_skipped_when_missing(self):
        result, _, _ = self.capture("ruby", [ToolResult("ruby", Status.MISSING)], "")
        self.assertIs(result.status, Status.SKIPPED)


class HintsTest(unittest.TestCase):
    def test_windows_ids(self):
        self.assertIn("PHP.PHP.8.5", " ".join(install_hints.hint_for("php", WINDOWS)))
        self.assertIn("RubyInstallerTeam.RubyWithDevKit.4.0", " ".join(install_hints.hint_for("ruby", WINDOWS)))
        self.assertIn("Composer-Setup.exe", " ".join(install_hints.hint_for("composer", WINDOWS)))


if __name__ == "__main__":
    unittest.main()
