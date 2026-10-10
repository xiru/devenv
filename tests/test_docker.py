"""Docker: the CLI, the engine, compose and the image build / run hello world."""

import unittest
from unittest import mock

from devenv_check import checks
from devenv_check.checks import Status
from tests.helpers import LINUX, WSL, fail, fake_system, ok, run_smoke, tool

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
    def test_cli_engine_and_compose_plugin(self):
        with fake_system({"docker": lambda args: "Docker Compose version v2.31.0" if "compose" in args else
                          ok("27.4.0") if "info" in args else DOCKER_CLI}):
            cli, daemon, compose = checks.check_docker(LINUX)
        self.assertEqual((cli.version, daemon.status), ("27.4.0", Status.OK))
        self.assertEqual((compose.provider, compose.version), ("compose plugin", "2.31.0"))

    def test_standalone_compose(self):
        def docker(args):
            return fail("docker: 'compose' is not a docker command.") if "compose" in args else DOCKER_CLI

        with fake_system({"docker": docker, "docker-compose": "docker-compose version 1.29.2"}):
            _, _, compose = checks.check_docker(LINUX)
        self.assertEqual(compose.provider, "docker-compose (standalone)")

    def test_no_compose_is_optional(self):
        with fake_system({"docker": lambda args: fail("unknown command") if "compose" in args else DOCKER_CLI}):
            _, _, compose = checks.check_docker(LINUX)
        self.assertEqual((compose.status, compose.required), (Status.MISSING, False))

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
