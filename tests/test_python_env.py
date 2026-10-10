import json
import unittest
from pathlib import Path
from unittest import mock

from devenv_check import checks, smoke
from devenv_check.checks import Status, ToolResult
from devenv_check.platform_info import PlatformInfo
from devenv_check.runner import CommandResult

LINUX = PlatformInfo("linux", "debian", "Ubuntu", "amd64")
WINDOWS = PlatformInfo("windows", "windows", "Windows 11", "amd64")

STORE_STUB = CommandResult(False, "", "Python was not found; run without arguments to install from the Microsoft Store", 9009)
UBUNTU_VENV_ERROR = CommandResult(False, "The virtual environment was not created successfully because ensurepip is not\n"
                                         "available.  On Debian/Ubuntu systems, you need to install the python3-venv\n"
                                         "package using the following command.\n\n    apt install python3.12-venv\n", "", 1)


def info(version="3.14.0", exe="/usr/bin/python3", managed=False):
    return CommandResult(True, json.dumps({"version": version, "executable": exe, "externally_managed": managed}), "", 0)


class FindPythonTest(unittest.TestCase):
    def test_windows_skips_store_stub(self):
        paths = {"python": r"C:\Users\u\AppData\Local\Microsoft\WindowsApps\python.exe",
                 "py": r"C:\Windows\py.exe"}
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return STORE_STUB if "WindowsApps" in args[0] else info(exe=r"C:\Python314\python.exe")

        with mock.patch.object(checks, "which", side_effect=paths.get), \
             mock.patch.object(checks, "run", side_effect=fake_run):
            found_info, launcher = checks.find_python(WINDOWS)
        self.assertEqual(launcher, "py")
        self.assertEqual(calls[1][1], "-3")  # the launcher is asked for Python 3 explicitly
        self.assertEqual(found_info["executable"], r"C:\Python314\python.exe")

    def test_python2_only_is_missing(self):
        with mock.patch.object(checks, "which", return_value="/usr/bin/python"), \
             mock.patch.object(checks, "run", return_value=info(version="2.7.18")):
            self.assertIsNone(checks.find_python(LINUX))


class CheckPythonTest(unittest.TestCase):
    def run_check(self, responses, managed=False, version="3.12.3"):
        """responses: substring of the command line -> CommandResult."""
        def fake_run(args, **kwargs):
            line = " ".join(map(str, args))
            for key, result in responses.items():
                if key in line:
                    return result
            return CommandResult(False, "", "No module named virtualenv", 1)

        def fake_which(name):  # like shutil.which: absolute paths resolve to themselves
            return "/usr/bin/python3" if name in ("python3", "/usr/bin/python3") else None

        with mock.patch.object(checks, "which", side_effect=fake_which), \
             mock.patch.object(checks, "run", side_effect=fake_run):
            responses.setdefault("-c import json", info(version=version, managed=managed))
            return {t.name: t for t in checks.check_python(LINUX)}

    def test_ubuntu_without_venv_package(self):
        tools = self.run_check({"-m pip": CommandResult(True, "pip 24.0 from /usr/lib/python3/dist-packages/pip (python 3.12)", "", 0),
                                "-m venv": UBUNTU_VENV_ERROR}, managed=True)
        self.assertIs(tools["python"].status, Status.OK)
        self.assertIn("PEP 668", tools["pip"].detail)
        venv = tools["venv (virtual environments)"]
        self.assertIs(venv.status, Status.MISSING)
        self.assertIn("apt install python3.12-venv", venv.detail)
        self.assertEqual(venv.hint, "venv")
        self.assertFalse(tools["virtualenv"].required)
        self.assertIs(checks.EnvResult("python", "Python 3", list(tools.values())).status, Status.MISSING)

    def test_missing_pip(self):
        tools = self.run_check({"-m pip": CommandResult(False, "", "/usr/bin/python3: No module named pip", 1),
                                "-m venv": CommandResult(True, "", "", 0)})
        self.assertIs(tools["pip"].status, Status.MISSING)
        self.assertEqual(tools["pip"].hint, "pip")

    def test_all_good_with_virtualenv(self):
        tools = self.run_check({"-m pip": CommandResult(True, "pip 25.2 from x (python 3.14)", "", 0),
                                "-m venv": CommandResult(True, "", "", 0),
                                "-m virtualenv": CommandResult(True, "virtualenv 20.29.1 from /x/virtualenv/__init__.py", "", 0)},
                               version="3.14.0")
        self.assertTrue(all(t.status is Status.OK for t in tools.values()))
        self.assertEqual(tools["virtualenv"].version, "20.29.1")

    def test_old_python_warns(self):
        tools = self.run_check({"-m pip": CommandResult(True, "pip 21.0", "", 0), "-m venv": CommandResult(True, "", "", 0)},
                               version="3.9.18")
        self.assertIs(tools["python"].status, Status.WARN)


class SmokeTest(unittest.TestCase):
    def test_runs_pip_and_script_inside_venv(self):
        calls = []

        def fake_run(args, timeout=30, **kwargs):
            calls.append(args)
            return CommandResult(True, "hello from Python 3", "", 0)

        tools = [ToolResult("python", Status.OK, path="/usr/bin/python3"),
                 ToolResult("venv (virtual environments)", Status.OK)]
        with mock.patch.object(smoke, "run", side_effect=fake_run):
            (result,) = smoke.run_smoke("python", LINUX, tools)
        self.assertIs(result.status, Status.OK)
        self.assertEqual(calls[0][1:], ["-m", "venv", ".venv"])
        venv_python = Path(calls[1][0])
        self.assertIn(".venv", venv_python.parts)
        self.assertEqual(calls[1][1:], ["-m", "pip", "--version"])
        self.assertEqual(Path(calls[2][0]), venv_python)

    def test_skipped_without_venv(self):
        tools = [ToolResult("python", Status.OK, path="/usr/bin/python3"),
                 ToolResult("venv (virtual environments)", Status.MISSING)]
        (result,) = smoke.run_smoke("python", LINUX, tools)
        self.assertIs(result.status, Status.SKIPPED)


if __name__ == "__main__":
    unittest.main()
