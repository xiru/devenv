"""Visual Studio Code: locating the editor, its updates and the recommended extension per language."""

import io
import json
import os
import unittest
from pathlib import Path
from unittest import mock

from devenv_check import checks, vscode
from devenv_check.checks import Status
from tests.helpers import LINUX, MACOS, WINDOWS, WSL, TempDirMixin, fail, ok

PRERELEASE = [{"key": "Microsoft.VisualStudio.Code.PreRelease", "value": "true"}]


def manifest_entry(ext_id, version, prerelease=False):
    return {"identifier": {"id": ext_id}, "version": version, "metadata": {"isPreReleaseVersion": prerelease}}


class FindCodeTest(TempDirMixin, unittest.TestCase):
    def test_on_path(self):
        with mock.patch.object(vscode, "which", return_value="/usr/bin/code"):
            self.assertEqual(vscode.find_code(LINUX), ("/usr/bin/code", True))

    def test_known_location_off_path(self):
        code = self.tmp / "code"
        code.touch()
        with mock.patch.object(vscode, "which", return_value=None), \
             mock.patch.object(vscode, "_known_locations", return_value=[self.tmp / "missing", code]):
            self.assertEqual(vscode.find_code(LINUX), (str(code), False))

    def test_not_installed(self):
        with mock.patch.object(vscode, "which", return_value=None), mock.patch.object(vscode, "_known_locations", return_value=[]):
            self.assertEqual(vscode.find_code(LINUX), (None, False))

    def test_known_locations_per_platform(self):
        with mock.patch.dict(os.environ, {"LOCALAPPDATA": str(self.tmp), "ProgramFiles": str(self.tmp / "PF")}):
            windows = vscode._known_locations(WINDOWS)
        self.assertEqual(windows[0].parts[-3:], ("Microsoft VS Code", "bin", "code.cmd"))
        self.assertIn(str(self.tmp / "PF"), str(windows[1]))
        self.assertTrue(all("Visual Studio Code.app" in str(p) for p in vscode._known_locations(MACOS)))
        self.assertIn(Path("/snap/bin/code"), vscode._known_locations(LINUX))


class ExtensionsDirTest(unittest.TestCase):
    def test_locations(self):
        with mock.patch.dict(os.environ, {}, clear=False) as environ:
            environ.pop("VSCODE_EXTENSIONS", None)
            self.assertEqual(vscode.extensions_dir(LINUX).parts[-2:], (".vscode", "extensions"))
            self.assertEqual(vscode.extensions_dir(WSL).parts[-2:], (".vscode-server", "extensions"))
        with mock.patch.dict(os.environ, {"VSCODE_EXTENSIONS": "/custom/ext"}):
            self.assertEqual(vscode.extensions_dir(WSL), Path("/custom/ext"))


class InstalledExtensionsTest(TempDirMixin, unittest.TestCase):
    def test_reads_the_manifest(self):
        (self.tmp / "extensions.json").write_text(json.dumps([
            manifest_entry("golang.Go", "0.55.0"),
            manifest_entry("golang.go", "0.56.1"),
            manifest_entry("ms-dotnettools.csharp", "2.161.1", prerelease=True),
            {"identifier": {}},  # broken entries are ignored
            "junk",
        ]))
        found = vscode.installed_extensions(self.tmp)
        self.assertEqual(found["golang.go"].version, "0.56.1")  # newest wins, ids are case-insensitive
        self.assertTrue(found["ms-dotnettools.csharp"].prerelease)
        self.assertEqual(len(found), 2)

    def test_falls_back_to_folder_names(self):
        for name in ("ms-vscode.cpptools-1.34.4-win32-x64", "ms-dotnettools.csharp-2.160.4-win32-x64",
                     "golang.go-0.56.1", "golang.go-0.55.0", ".obsolete"):
            (self.tmp / name).mkdir()
        (self.tmp / "ms-python.python-2025.1.0").touch()  # files are not extensions
        found = vscode.installed_extensions(self.tmp)
        self.assertEqual(found["ms-vscode.cpptools"].version, "1.34.4")
        self.assertEqual(found["ms-dotnettools.csharp"].version, "2.160.4")
        self.assertEqual(found["golang.go"].version, "0.56.1")
        self.assertNotIn("ms-python.python", found)

    def test_unreadable_manifest_and_missing_folder(self):
        (self.tmp / "extensions.json").write_text("{broken")
        self.assertEqual(vscode.installed_extensions(self.tmp), {})
        self.assertEqual(vscode.installed_extensions(self.tmp / "nowhere"), {})


class MarketplaceTest(unittest.TestCase):
    def test_separates_stable_and_prerelease(self):
        payload = {"versions": [{"version": "0.57.2", "properties": PRERELEASE}, {"version": "0.56.1", "properties": []},
                                {"version": "0.7.1"}, {"version": "garbage"}]}
        with mock.patch.object(vscode, "_get_json", return_value=payload) as get_json:
            self.assertEqual(vscode.latest_versions("golang.go"), ("0.56.1", "0.57.2"))
        self.assertIn("/golang/go/latest", get_json.call_args.args[0])

    def test_no_versions(self):
        with mock.patch.object(vscode, "_get_json", return_value={}):
            self.assertEqual(vscode.latest_versions("a.b"), (None, None))

    def test_get_json_sends_a_user_agent(self):
        with mock.patch.object(vscode.urllib.request, "urlopen", return_value=io.BytesIO(b'["1.141.0"]')) as urlopen:
            self.assertEqual(vscode._get_json(vscode.VSCODE_RELEASES), ["1.141.0"])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("User-agent"), "devenv-check")
        self.assertEqual(urlopen.call_args.kwargs["timeout"], vscode.HTTP_TIMEOUT)

    def test_fetch_latest_keeps_errors_per_extension(self):
        def latest(ext_id):
            if ext_id == "bad.ext":
                raise OSError("no network")
            return ("1.0.0", None)

        with mock.patch.object(vscode, "latest_versions", side_effect=latest):
            result = vscode.fetch_latest(["good.ext", "bad.ext"])
        self.assertEqual(result["good.ext"], ("1.0.0", None))
        self.assertIsInstance(result["bad.ext"], OSError)
        self.assertEqual(vscode.fetch_latest([]), {})


class VscodeAppTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(vscode.SETTINGS, "offline", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def app(self, version_output=ok("1.141.0\nabc\nx64"), latest=("1.141.0",), found=("/usr/bin/code", True), platform=LINUX):
        get_json = mock.patch.object(vscode, "_get_json", side_effect=latest) if isinstance(latest, Exception) else \
            mock.patch.object(vscode, "_get_json", return_value=list(latest))
        with mock.patch.object(vscode, "find_code", return_value=found), \
             mock.patch.object(vscode, "run", return_value=version_output) as run, get_json:
            return vscode.check_vscode_app(platform), run

    def test_up_to_date(self):
        app, _ = self.app()
        self.assertEqual((app.status, app.version, app.detail), (Status.OK, "1.141.0", "up to date"))

    def test_outdated(self):
        app, _ = self.app(ok("1.139.0\nabc"), latest=("1.141.0", "1.140.0"))
        self.assertEqual((app.status, app.hint, app.detail), (Status.WARN, "vscode_update", "update available: 1.141.0"))

    def test_update_check_failure_never_fails(self):
        app, _ = self.app(latest=OSError("no network"))
        self.assertIs(app.status, Status.OK)
        self.assertIn("could not check for updates", app.detail)

    def test_offline(self):
        with mock.patch.object(vscode.SETTINGS, "offline", True):
            app, _ = self.app(latest=AssertionError("must not be called"))
        self.assertEqual(app.detail, "update check skipped (--offline)")

    def test_not_on_path_warns(self):
        app, _ = self.app(found=("/usr/share/code/bin/code", False))
        self.assertEqual((app.status, app.hint), (Status.WARN, "vscode_path"))

    def test_broken(self):
        app, _ = self.app(fail("cannot open display"))
        self.assertEqual((app.status, app.hint), (Status.MISSING, "vscode"))
        self.assertIn("cannot open display", app.detail)

    def test_not_installed(self):
        app, _ = self.app(found=(None, False))
        self.assertEqual((app.status, app.hint), (Status.MISSING, "vscode"))

    def test_wsl_never_launches_the_windows_editor(self):
        app, run = self.app(found=("/mnt/c/VS Code/bin/code", True), platform=WSL)
        run.assert_not_called()
        self.assertIs(app.status, Status.OK)
        self.assertIn("via WSL", app.detail)


class ExtensionCheckTest(unittest.TestCase):
    def check(self, installed, latest, offline=False, platform=LINUX, wsl_command=None):
        with mock.patch.object(vscode, "installed_extensions", return_value={e.id: e for e in installed}), \
             mock.patch.object(vscode, "fetch_latest", return_value=latest), \
             mock.patch.object(vscode, "which", return_value=wsl_command), \
             mock.patch.object(vscode.SETTINGS, "offline", offline):
            return {t.name: t for t in vscode.check_extensions(platform, "/usr/bin/code")}

    def test_missing_outdated_and_current(self):
        results = self.check(
            [vscode.InstalledExtension("golang.go", "0.55.0"), vscode.InstalledExtension("ms-dotnettools.csharp", "2.160.4")],
            {"golang.go": ("0.56.1", "0.57.2"), "ms-dotnettools.csharp": ("2.160.4", "11.2.14")},
        )
        self.assertIs(results["ext: Go"].status, Status.WARN)
        self.assertEqual(results["ext: Go"].fix, ["code --install-extension golang.go --force"])
        self.assertIs(results["ext: C#"].status, Status.OK)  # a stable install isn't compared with pre-releases
        self.assertEqual(results["ext: C#"].provider, "ms-dotnettools.csharp")  # the alternative id is accepted
        self.assertIs(results["ext: Python"].status, Status.MISSING)
        self.assertEqual(results["ext: Python"].fix, ["code --install-extension ms-python.python"])
        self.assertFalse({"ext: Java", "ext: Gradle", "ext: Kotlin"} & results.keys())  # JVM work uses IntelliJ IDEA
        self.assertFalse(results["ext: ESLint (JS/TS)"].required)
        self.assertIn("built into VS Code", results["ext: ESLint (JS/TS)"].detail)
        self.assertNotIn("ext: WSL", results)  # only offered on Windows

    def test_prerelease_installs_follow_prereleases(self):
        results = self.check([vscode.InstalledExtension("golang.go", "0.57.0", prerelease=True)], {"golang.go": ("0.56.1", "0.57.2")})
        self.assertEqual(results["ext: Go"].fix, ["code --install-extension golang.go --pre-release --force"])
        current = self.check([vscode.InstalledExtension("golang.go", "0.57.2", prerelease=True)], {"golang.go": ("0.56.1", "0.57.2")})
        self.assertEqual(current["ext: Go"].detail, "golang.go; up to date (pre-release)")

    def test_offline_and_network_errors_never_fail(self):
        installed = [vscode.InstalledExtension("golang.go", "0.55.0")]
        offline = self.check(installed, {}, offline=True)
        self.assertIs(offline["ext: Go"].status, Status.OK)
        self.assertIn("--offline", offline["ext: Go"].detail)
        broken = self.check(installed, {"golang.go": OSError("no network")})
        self.assertIs(broken["ext: Go"].status, Status.OK)
        self.assertIn("could not check for updates (no network)", broken["ext: Go"].detail)
        self.assertEqual(self.check(installed, {})["ext: Go"].detail, "golang.go")

    def test_wsl_extension_only_on_windows_with_wsl(self):
        self.assertIn("ext: WSL", self.check([], {}, platform=WINDOWS, wsl_command=r"C:\Windows\System32\wsl.exe"))
        self.assertNotIn("ext: WSL", self.check([], {}, platform=WINDOWS))

    def test_wsl_fix_explains_where_to_run_it(self):
        results = self.check([], {}, platform=WSL)
        self.assertIn("WSL side", results["ext: Go"].fix[1])


class CheckVscodeTest(unittest.TestCase):
    def test_missing_editor_skips_extensions(self):
        with mock.patch.object(vscode, "find_code", return_value=(None, False)):
            app, extensions = vscode.check_vscode(LINUX)
        self.assertIs(app.status, Status.MISSING)
        self.assertIs(extensions.status, Status.SKIPPED)

    def test_editor_and_extensions(self):
        app = vscode.ToolResult("VS Code", Status.OK, path="/usr/bin/code")
        ext = vscode.ToolResult("ext: Go", Status.OK)
        with mock.patch.object(vscode, "check_vscode_app", return_value=app), \
             mock.patch.object(vscode, "check_extensions", return_value=[ext]) as check_extensions:
            self.assertEqual(vscode.check_vscode(LINUX), [app, ext])
        check_extensions.assert_called_once_with(LINUX, "/usr/bin/code")

    def test_registered_as_an_environment(self):
        with mock.patch.object(vscode, "check_vscode", return_value=["rows"]):
            self.assertEqual(checks.ENVIRONMENTS["vscode"][1](LINUX), ["rows"])


if __name__ == "__main__":
    unittest.main()
