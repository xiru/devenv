"""Docker: the CLI, the engine and the image build / run hello world."""

import unittest
from unittest import mock

from devenv_check import checks
from devenv_check.checks import Status
from tests.helpers import LINUX, WSL, fail, fake_system, ok, platform_for, run_smoke, tool

DOCKER_CLI = "Docker version 27.4.0, build bde2b89"


class DaemonTest(unittest.TestCase):
    def daemon(self, result):
        with mock.patch.object(checks, "run", return_value=result):
            return checks.check_docker_daemon("/usr/bin/docker")

    def test_running(self):
        self.assertEqual((self.daemon(ok("27.4.0")).status, self.daemon(ok("27.4.0")).version), (Status.OK, "27.4.0"))

    def test_not_reachable(self):
        daemon = self.daemon(fail("Cannot connect to the Docker daemon at unix:///var/run/docker.sock."))
        self.assertEqual((daemon.status, daemon.hint), (Status.MISSING, "docker_daemon"))
        self.assertIn("Cannot connect", daemon.detail)

    def test_error_printed_on_stdout(self):
        self.assertIs(self.daemon(ok("error during connect")).status, Status.MISSING)
        self.assertIn("daemon not reachable", self.daemon(fail()).detail)


class CheckDockerTest(unittest.TestCase):
    def test_cli_and_engine(self):
        with fake_system({"docker": lambda args: ok("27.4.0") if "info" in args else DOCKER_CLI}):
            cli, daemon = checks.check_docker(LINUX)
        self.assertEqual((cli.version, daemon.status), ("27.4.0", Status.OK))

    def docker_io(self, status, platform=LINUX):
        """check_docker with dpkg-query reporting the docker.io package `status`."""
        with fake_system({"docker": lambda args: ok("27.4.0") if "info" in args else DOCKER_CLI,
                          "dpkg-query": status}) as calls:
            cli, _ = checks.check_docker(platform)
        return cli, calls

    def test_ubuntu_docker_io_package(self):
        cli, calls = self.docker_io("install ok installed")
        self.assertEqual((cli.status, cli.detail), (Status.OK, ""))
        self.assertIn(["/usr/bin/dpkg-query", "-W", "-f=${Status}", "docker.io"], calls)

    def test_ubuntu_docker_from_another_source(self):
        cli, _ = self.docker_io(fail("dpkg-query: no packages found matching docker.io"))
        self.assertEqual((cli.status, cli.hint), (Status.WARN, "docker"))
        self.assertIn("docker.io", cli.detail)

    def test_package_is_only_checked_on_ubuntu_outside_wsl(self):
        for platform in (WSL, platform_for("fedora")):
            with self.subTest(platform=platform.name):
                cli, calls = self.docker_io(fail("not installed"), platform)
                self.assertIs(cli.status, Status.OK)
                self.assertFalse(any("dpkg-query" in call[0] for call in calls))

    def test_not_installed(self):
        with fake_system({}):
            (cli,) = checks.check_docker(LINUX)
        self.assertEqual((cli.status, cli.hint), (Status.MISSING, "docker"))

    def test_docker_desktop_stub_in_wsl(self):
        stub = fail("The command 'docker' could not be found in this WSL 2 distro.\n"
                    "We recommend to activate the WSL integration in Docker Desktop settings.")
        with fake_system({"docker": stub}):
            (cli,) = checks.check_docker(WSL)
        self.assertEqual(cli.detail, "Docker Desktop is installed on Windows, but WSL integration is off for this distro")


class DockerSmokeTest(unittest.TestCase):
    def tools(self, daemon=Status.OK):
        return [tool("docker CLI", "/usr/bin/docker"), tool("docker engine (daemon)", status=daemon)]

    def test_builds_runs_and_removes_the_image(self):
        smoke_run = run_smoke("docker", self.tools(), "Hello from Docker!")
        self.assertIs(smoke_run.result.status, Status.OK)
        build, run, rmi = smoke_run.commands
        tag = build[build.index("-t") + 1]
        self.assertTrue(tag.startswith("devenv-check-hello:"))
        self.assertEqual(run, ["/usr/bin/docker", "run", "--rm", tag])
        self.assertEqual(rmi, ["/usr/bin/docker", "rmi", "-f", tag])
        self.assertEqual(smoke_run.written["Dockerfile"], "FROM hello-world\n")

    def test_image_is_removed_even_when_the_build_fails(self):
        smoke_run = run_smoke("docker", self.tools(), lambda args: fail("pull access denied") if "build" in args else "")
        self.assertIs(smoke_run.result.status, Status.MISSING)
        self.assertEqual(smoke_run.commands[-1][1:3], ["rmi", "-f"])

    def test_skipped_without_a_running_engine(self):
        self.assertIs(run_smoke("docker", self.tools(daemon=Status.MISSING)).result.status, Status.SKIPPED)
        self.assertIs(run_smoke("docker", [tool("docker CLI", status=Status.MISSING)]).result.status, Status.SKIPPED)


if __name__ == "__main__":
    unittest.main()
