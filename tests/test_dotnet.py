"""C# (.NET): the .NET SDK and the dotnet build / run hello world."""

import unittest

from devenv_check import checks
from devenv_check.checks import Status
from tests.helpers import LINUX, fake_system, run_smoke, tool

SDKS = "8.0.404 [/usr/lib/dotnet/sdk]\n10.0.100 [/usr/lib/dotnet/sdk]\n"


class CheckDotnetTest(unittest.TestCase):
    def check(self, list_sdks):
        with fake_system({"dotnet": list_sdks}) as calls:
            (dotnet,) = checks.check_dotnet(LINUX)
        return dotnet, calls

    def test_newest_sdk_wins(self):
        dotnet, calls = self.check(SDKS)
        self.assertEqual((dotnet.status, dotnet.version, dotnet.detail), (Status.OK, "10.0.100", "2 SDK(s) installed"))
        self.assertEqual(calls, [["/usr/bin/dotnet", "--list-sdks"]])

    def test_single_sdk(self):
        self.assertEqual(self.check("9.0.101 [C:\\Program Files\\dotnet\\sdk]")[0].detail, "")

    def test_old_sdk_warns(self):
        dotnet, _ = self.check("6.0.428 [/usr/share/dotnet/sdk]")
        self.assertEqual((dotnet.status, dotnet.detail), (Status.WARN, "older than recommended 8"))

    def test_runtime_without_sdk(self):
        dotnet, _ = self.check("")
        self.assertEqual((dotnet.status, dotnet.hint), (Status.MISSING, "dotnet"))
        self.assertIn("no SDK installed", dotnet.detail)

    def test_not_installed(self):
        with fake_system({}):
            (dotnet,) = checks.check_dotnet(LINUX)
        self.assertIn("not found in PATH", dotnet.detail)


class DotnetSmokeTest(unittest.TestCase):
    def test_build_and_run_target_the_installed_sdk(self):
        smoke_run = run_smoke("dotnet", [tool(".NET SDK (dotnet)", "/usr/bin/dotnet", version="10.0.100")], "hello from C#")
        self.assertIs(smoke_run.result.status, Status.OK)
        build, run = smoke_run.calls
        self.assertEqual(build.args[1], "build")
        self.assertEqual(run.args[1:], ["run", "--no-build"])
        self.assertEqual(build.env["DOTNET_CLI_TELEMETRY_OPTOUT"], "1")
        self.assertIn("<TargetFramework>net10.0</TargetFramework>", smoke_run.written["hello.csproj"])
        self.assertEqual(smoke_run.result.detail, "dotnet build + run (net10.0)")

    def test_unknown_version_targets_net8(self):
        smoke_run = run_smoke("dotnet", [tool(".NET SDK (dotnet)", "/usr/bin/dotnet")], "hello from C#")
        self.assertIn("net8.0", smoke_run.written["hello.csproj"])

    def test_skipped_without_the_sdk(self):
        self.assertIs(run_smoke("dotnet", [tool(".NET SDK (dotnet)", status=Status.MISSING)]).result.status, Status.SKIPPED)


if __name__ == "__main__":
    unittest.main()
