"""Python 3: finding a real interpreter, pip, venv and the virtual-environment hello world."""

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from devenv_check import checks
from devenv_check.checks import Status
from devenv_check.runner import CommandResult
from tests.helpers import LINUX, WINDOWS, fail, ok, run_smoke, tool

STORE_STUB = fail("Python was not found; run without arguments to install from the Microsoft Store", returncode=9009)
UBUNTU_VENV_ERROR = fail(stdout="The virtual environment was not created successfully because ensurepip is not\n"
                                "available.  On Debian/Ubuntu systems, you need to install the python3-venv\n"
                                "package using the following command.\n\n    apt install python3.12-venv\n")


def info(version="3.14.0", exe="/usr/bin/python3", managed=False) -> CommandResult:
    return ok(json.dumps({"version": version, "executable": exe, "externally_managed": managed}))


class FindPythonTest(unittest.TestCase):
    def test_windows_skips_the_store_stub_and_asks_the_launcher_for_python_3(self):
        paths = {"python": r"C:\Users\u\AppData\Local\Microsoft\WindowsApps\python.exe", "py": r"C:\Windows\py.exe"}
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return STORE_STUB if "WindowsApps" in args[0] else info(exe=r"C:\Python314\python.exe")

        with mock.patch.object(checks, "which", side_effect=paths.get), mock.patch.object(checks, "run", side_effect=fake_run):
            found_info, launcher = checks.find_python(WINDOWS)
        self.assertEqual(launcher, "py")
        self.assertEqual(calls[1][1], "-3")
        self.assertEqual(found_info["executable"], r"C:\Python314\python.exe")

    def test_linux_prefers_python3(self):
        names = []
        with mock.patch.object(checks, "which", side_effect=lambda n: names.append(n) or f"/usr/bin/{n}"), \
             mock.patch.object(checks, "run", return_value=info()):
            _, launcher = checks.find_python(LINUX)
        self.assertEqual((launcher, names), ("python3", ["python3"]))

    def test_python2_only_is_missing(self):
        with mock.patch.object(checks, "which", return_value="/usr/bin/python"), \
             mock.patch.object(checks, "run", return_value=info(version="2.7.18")):
            self.assertIsNone(checks.find_python(LINUX))

    def test_banners_before_the_json_and_garbage(self):
        banner = ok("sitecustomize says hi\n" + info().stdout)
        with mock.patch.object(checks, "which", return_value="/usr/bin/python3"), mock.patch.object(checks, "run", return_value=banner):
            self.assertIsNotNone(checks.find_python(LINUX))
        with mock.patch.object(checks, "which", return_value="/usr/bin/python3"), mock.patch.object(checks, "run", return_value=ok("{oops")):
            self.assertIsNone(checks.find_python(LINUX))

    def test_probe_script_runs_in_a_real_interpreter(self):
        with mock.patch.object(checks, "which", side_effect=lambda n: sys.executable if n == "python3" else None):
            found_info, _ = checks.find_python(LINUX)
        self.assertEqual(found_info["version"], "%d.%d.%d" % sys.version_info[:3])
        self.assertIsInstance(found_info["externally_managed"], bool)


class PythonErrorTest(unittest.TestCase):
    def test_install_command_beats_the_explanation(self):
        self.assertEqual(checks._python_error(UBUNTU_VENV_ERROR), "apt install python3.12-venv")
        self.assertEqual(checks._python_error(fail("x\nensurepip is missing\ny")), "ensurepip is missing")
        self.assertEqual(checks._python_error(fail("first\nlast")), "last")
        self.assertEqual(checks._python_error(fail(returncode=4)), "exit code 4")


class VenvTest(unittest.TestCase):
    def test_creates_a_throwaway_environment(self):
        with mock.patch.object(checks, "run", return_value=ok()) as run:
            venv = checks.check_venv("/usr/bin/python3")
        self.assertIs(venv.status, Status.OK)
        args = run.call_args.args[0]
        self.assertEqual(args[:3], ["/usr/bin/python3", "-m", "venv"])
        self.assertIn("devenv-check-venv-", args[3])
        self.assertFalse(Path(args[3]).parent.exists())  # cleaned up

    def test_failure(self):
        with mock.patch.object(checks, "run", return_value=UBUNTU_VENV_ERROR):
            venv = checks.check_venv("/usr/bin/python3")
        self.assertEqual((venv.status, venv.hint), (Status.MISSING, "venv"))
        self.assertIn("apt install python3.12-venv", venv.detail)


class CheckPythonTest(unittest.TestCase):
    def check(self, responses, managed=False, version="3.12.3"):
        """responses: substring of the command line -> CommandResult."""
        def fake_run(args, **kwargs):
            line = " ".join(map(str, args))
            return next((result for key, result in responses.items() if key in line), fail("unexpected command"))

        responses.setdefault("-c import json", info(version=version, managed=managed))
        with mock.patch.object(checks, "which", side_effect=lambda n: "/usr/bin/python3" if n == "python3" else None), \
             mock.patch.object(checks, "run", side_effect=fake_run):
            return {t.name: t for t in checks.check_python(LINUX)}

    def test_all_good(self):
        tools = self.check({"-m pip": ok("pip 25.2 from x (python 3.14)"), "-m venv": ok()}, version="3.14.0")
        self.assertTrue(all(t.status is Status.OK for t in tools.values()))
        self.assertEqual((tools["python"].provider, tools["pip"].version), ("python3", "25.2"))
        self.assertEqual(list(tools), ["python", "pip", "venv (virtual environments)"])

    def test_ubuntu_without_the_venv_package(self):
        tools = self.check({"-m pip": ok("pip 24.0 from /usr/lib/python3/dist-packages/pip (python 3.12)"),
                            "-m venv": UBUNTU_VENV_ERROR}, managed=True)
        self.assertIs(tools["python"].status, Status.OK)
        self.assertIn("PEP 668", tools["pip"].detail)
        venv = tools["venv (virtual environments)"]
        self.assertEqual((venv.status, venv.hint), (Status.MISSING, "venv"))
        self.assertIs(checks.EnvResult("python", "Python 3", list(tools.values())).status, Status.MISSING)

    def test_missing_pip(self):
        tools = self.check({"-m pip": fail("/usr/bin/python3: No module named pip"), "-m venv": ok()})
        self.assertEqual((tools["pip"].status, tools["pip"].hint), (Status.MISSING, "pip"))
        self.assertIn("No module named pip", tools["pip"].detail)

    def test_old_python_warns(self):
        tools = self.check({"-m pip": ok("pip 21.0"), "-m venv": ok()}, version="3.9.18")
        self.assertIs(tools["python"].status, Status.WARN)
        self.assertIn("older than recommended 3.11", tools["python"].detail)

    def test_no_python(self):
        with mock.patch.object(checks, "which", return_value=None):
            (python,) = checks.check_python(LINUX)
        self.assertEqual((python.status, python.hint), (Status.MISSING, "python"))


class PythonSmokeTest(unittest.TestCase):
    def test_runs_pip_and_the_script_inside_a_venv(self):
        smoke_run = run_smoke("python", [tool("python"), tool("venv (virtual environments)")], "hello from Python 3")
        self.assertIs(smoke_run.result.status, Status.OK)
        create, pip, script = smoke_run.commands
        self.assertEqual(create[1:], ["-m", "venv", ".venv"])
        self.assertIn(".venv", Path(pip[0]).parts)
        self.assertEqual(pip[1:], ["-m", "pip", "--version"])  # no network needed
        self.assertEqual((Path(script[0]), script[1]), (Path(pip[0]), "hello.py"))

    def test_skipped_without_a_working_venv(self):
        smoke_run = run_smoke("python", [tool("python"), tool("venv (virtual environments)", status=Status.MISSING)])
        self.assertIs(smoke_run.result.status, Status.SKIPPED)
        self.assertIs(run_smoke("python", [tool("python")]).result.status, Status.SKIPPED)


if __name__ == "__main__":
    unittest.main()
