"""Ruby + Bundler: ruby, gem, bundler, RubyInstaller's ridk and the bundle exec hello world."""

import unittest

from devenv_check import checks, install_hints
from devenv_check.checks import Status
from devenv_check.runner import parse_version
from tests.helpers import LINUX, MACOS, WINDOWS, fake_system, run_smoke, tool

RIDK_VERSION = "---\nruby:\n  path: C:/Ruby40-x64\n  version: 4.0.7\n  platform: x64-mingw-ucrt\nmsys2:\n  path: C:\\Ruby40-x64\\msys64\n"


class CheckRubyTest(unittest.TestCase):
    def test_version_formats(self):
        self.assertEqual(parse_version("ruby 3.4.1 (2024-12-25 revision 48d4efcb85) +PRISM [x86_64-linux]", r"ruby (\d+)\.(\d+)\.(\d+)"), (3, 4, 1))
        self.assertEqual(parse_version("Bundler version 2.6.2", r"Bundler version (\d+)\.(\d+)\.(\d+)"), (2, 6, 2))
        self.assertEqual(parse_version(RIDK_VERSION, r"version: (\d+)\.(\d+)\.(\d+)"), (4, 0, 7))

    def test_ruby_gem_bundler(self):
        with fake_system({"ruby": "ruby 3.4.1 (2024-12-25)", "gem": "3.6.2", "bundle": "Bundler version 2.6.2"}):
            tools = {t.name: t for t in checks.check_ruby(LINUX)}
        self.assertEqual(list(tools), ["ruby", "gem (RubyGems)", "bundler"])  # ridk is Windows only
        self.assertEqual((tools["ruby"].version, tools["gem (RubyGems)"].version, tools["bundler"].version),
                         ("3.4.1", "3.6.2", "2.6.2"))

    def test_macos_system_ruby(self):
        with fake_system({"ruby": "ruby 2.6.10p210 (2022-04-12 revision 67958)", "gem": "3.0.3.1", "bundle": "Bundler version 1.17.2"}):
            ruby = checks.check_ruby(MACOS)[0]
        self.assertIs(ruby.status, Status.WARN)
        self.assertIn("Homebrew", ruby.detail)

    def test_old_ruby_elsewhere_keeps_the_generic_warning(self):
        with fake_system({"ruby": "ruby 3.0.2"}, where="/opt/homebrew/bin"):
            ruby = checks.check_ruby(MACOS)[0]
        self.assertIn("older than recommended", ruby.detail)

    def test_windows_offers_ridk(self):
        with fake_system({"ruby": "ruby 4.0.7", "gem": "4.0.1", "bundle": "Bundler version 4.0.1", "ridk": RIDK_VERSION}):
            tools = {t.name: t for t in checks.check_ruby(WINDOWS)}
        ridk = tools["ridk (MSYS2 devkit)"]
        self.assertEqual((ridk.version, ridk.required, ridk.hint), ("4.0.7", False, "ridk"))


class RubySmokeTest(unittest.TestCase):
    def test_bundle_install_is_local_and_isolated(self):
        smoke_run = run_smoke("ruby", [tool("ruby"), tool("bundler", "/usr/bin/bundle")], "hello from Ruby")
        self.assertIs(smoke_run.result.status, Status.OK)
        install, exec_ = smoke_run.calls
        self.assertEqual(install.args[1:], ["install", "--local", "--quiet"])  # no network
        self.assertEqual(exec_.args[1:], ["exec", "ruby", "hello.rb"])
        self.assertTrue(install.env["BUNDLE_GEMFILE"].endswith("Gemfile"))  # never the user's project Gemfile
        self.assertTrue(install.env["BUNDLE_APP_CONFIG"].endswith(".bundle"))

    def test_without_bundler_ruby_still_runs(self):
        smoke_run = run_smoke("ruby", [tool("ruby"), tool("bundler", status=Status.MISSING)], "hello from Ruby")
        self.assertEqual((smoke_run.result.name, smoke_run.result.status), ("hello: Ruby", Status.OK))
        self.assertEqual(smoke_run.commands, [["/usr/bin/ruby", "hello.rb"]])

    def test_skipped_without_ruby(self):
        self.assertIs(run_smoke("ruby", [tool("ruby", status=Status.MISSING)]).result.status, Status.SKIPPED)


class RubyHintsTest(unittest.TestCase):
    def test_windows_installs_ruby_with_the_devkit(self):
        self.assertIn("RubyInstallerTeam.RubyWithDevKit.4.0", " ".join(install_hints.hint_for("ruby", WINDOWS)))


if __name__ == "__main__":
    unittest.main()
