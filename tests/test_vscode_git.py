import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from devenv_check import checks, smoke, vscode
from devenv_check.checks import Status, ToolResult
from devenv_check.platform_info import PlatformInfo
from devenv_check.runner import CommandResult

LINUX = PlatformInfo("linux", "debian", "Ubuntu", "amd64")
WSL = PlatformInfo("linux", "debian", "Ubuntu (WSL)", "amd64", wsl=True)


def manifest_entry(ext_id, version, prerelease=False):
    return {"identifier": {"id": ext_id}, "version": version,
            "metadata": {"isPreReleaseVersion": prerelease}}


class InstalledExtensionsTest(unittest.TestCase):
    def test_reads_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "extensions.json").write_text(json.dumps([
                manifest_entry("golang.Go", "0.56.1"),
                manifest_entry("rust-lang.rust-analyzer", "0.4.3078", prerelease=True),
            ]))
            found = vscode.installed_extensions(Path(tmp))
        self.assertEqual(found["golang.go"].version, "0.56.1")
        self.assertTrue(found["rust-lang.rust-analyzer"].prerelease)

    def test_falls_back_to_folder_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("ms-vscode.cpptools-1.34.4-win32-x64", "rust-lang.rust-analyzer-0.3.3073-win32-x64",
                         "golang.go-0.55.0", "golang.go-0.56.1"):
                Path(tmp, name).mkdir()
            found = vscode.installed_extensions(Path(tmp))
        self.assertEqual(found["ms-vscode.cpptools"].version, "1.34.4")
        self.assertEqual(found["rust-lang.rust-analyzer"].version, "0.3.3073")
        self.assertEqual(found["golang.go"].version, "0.56.1")

    def test_wsl_uses_server_extensions(self):
        self.assertEqual(vscode.extensions_dir(WSL).parts[-2:], (".vscode-server", "extensions"))


class LatestVersionsTest(unittest.TestCase):
    def test_separates_stable_and_prerelease(self):
        pre = [{"key": "Microsoft.VisualStudio.Code.PreRelease", "value": "true"}]
        payload = {"versions": [
            {"version": "0.57.2", "properties": pre},
            {"version": "0.56.1", "properties": []},
            {"version": "0.7.1", "properties": []},
        ]}
        with mock.patch.object(vscode, "_get_json", return_value=payload):
            self.assertEqual(vscode.latest_versions("golang.go"), ("0.56.1", "0.57.2"))


class ExtensionCheckTest(unittest.TestCase):
    def run_check(self, installed, latest, offline=False):
        installed = {e.id: e for e in installed}
        with mock.patch.object(vscode, "installed_extensions", return_value=installed), \
             mock.patch.object(vscode, "fetch_latest", return_value=latest), \
             mock.patch.object(vscode.SETTINGS, "offline", offline):
            return {t.name: t for t in vscode.check_extensions(LINUX, "/usr/bin/code")}

    def test_missing_outdated_and_current(self):
        results = self.run_check(
            [vscode.InstalledExtension("golang.go", "0.55.0"),
             vscode.InstalledExtension("ms-dotnettools.csharp", "2.160.4")],
            {"golang.go": ("0.56.1", "0.57.2"), "ms-dotnettools.csharp": ("2.160.4", "11.2.14")},
        )
        self.assertIs(results["ext: Go"].status, Status.WARN)
        self.assertIn("--force", results["ext: Go"].fix[0])
        self.assertIs(results["ext: C#"].status, Status.OK)  # stable install isn't compared to pre-release
        self.assertIs(results["ext: Rust"].status, Status.MISSING)
        self.assertEqual(results["ext: Rust"].fix, ["code --install-extension rust-lang.rust-analyzer"])
        # JVM development is pointed at IntelliJ IDEA, never at VS Code extensions
        self.assertFalse({"ext: Java", "ext: Gradle", "ext: Kotlin"} & results.keys())
        self.assertFalse(results["ext: ESLint (JS/TS)"].required)
        self.assertNotIn("ext: WSL", results)  # only offered on Windows

    def test_offline_and_network_errors_never_fail(self):
        installed = [vscode.InstalledExtension("golang.go", "0.55.0")]
        offline = self.run_check(installed, {}, offline=True)
        self.assertIs(offline["ext: Go"].status, Status.OK)
        broken = self.run_check(installed, {"golang.go": OSError("no network")})
        self.assertIs(broken["ext: Go"].status, Status.OK)
        self.assertIn("could not check", broken["ext: Go"].detail)

    def test_vscode_missing_skips_extensions(self):
        with mock.patch.object(vscode, "find_code", return_value=(None, False)):
            app, extensions = vscode.check_vscode(LINUX)
        self.assertIs(app.status, Status.MISSING)
        self.assertIs(extensions.status, Status.SKIPPED)

    def test_vscode_not_on_path_warns(self):
        with mock.patch.object(vscode, "find_code", return_value=("/usr/share/code/bin/code", False)), \
             mock.patch.object(vscode, "run", return_value=CommandResult(True, "1.141.0\nabc\nx64", "", 0)):
            app = vscode.check_vscode_app(LINUX)
        self.assertIs(app.status, Status.WARN)
        self.assertEqual(app.hint, "vscode_path")

    def test_vscode_outdated(self):
        with mock.patch.object(vscode, "find_code", return_value=("/usr/bin/code", True)), \
             mock.patch.object(vscode, "run", return_value=CommandResult(True, "1.139.0\nabc", "", 0)), \
             mock.patch.object(vscode, "_get_json", return_value=["1.141.0", "1.140.0"]):
            app = vscode.check_vscode_app(LINUX)
        self.assertIs(app.status, Status.WARN)
        self.assertIn("1.141.0", app.detail)

    def test_wsl_does_not_launch_windows_editor(self):
        with mock.patch.object(vscode, "find_code", return_value=("/mnt/c/VS Code/bin/code", True)), \
             mock.patch.object(vscode, "run") as run:
            app = vscode.check_vscode_app(WSL)
        run.assert_not_called()
        self.assertIs(app.status, Status.OK)


class GitTest(unittest.TestCase):
    def test_identity(self):
        responses = {"user.name": CommandResult(True, "Ada", "", 0), "user.email": CommandResult(False, "", "", 1)}
        with mock.patch.object(checks, "run", side_effect=lambda args, **_: responses[args[-1]]):
            tool = checks.check_git_identity("/usr/bin/git")
        self.assertIs(tool.status, Status.WARN)
        self.assertIn("user.email", tool.detail)

    def test_smoke_isolates_user_config(self):
        calls = []

        def fake_run(args, timeout=30, **kwargs):
            calls.append(args)
            return CommandResult(True, "hello from git", "", 0)

        with mock.patch.object(smoke, "run", side_effect=fake_run):
            (result,) = smoke.run_smoke("git", LINUX, [ToolResult("git", Status.OK, path="/usr/bin/git")])
        self.assertIs(result.status, Status.OK)
        self.assertTrue(all("commit.gpgsign=false" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
