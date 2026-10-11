"""Kubernetes: kubectl, the current context and its cluster, helm, a local cluster and the pod hello world."""

import unittest
from unittest import mock

from devenv_check import checks, install_hints, smoke
from devenv_check.checks import Status
from tests.helpers import LINUX, MACOS, WINDOWS, WSL, fail, fake_system, ok, platform_for, run_smoke, tool

FEDORA = platform_for("fedora")

KUBECTL = "Client Version: v1.32.0\nKustomize Version: v5.5.0"


class KubeContextTest(unittest.TestCase):
    def test_current_context(self):
        with mock.patch.object(checks, "run", return_value=ok("kind-dev")):
            context = checks.check_kube_context("/usr/bin/kubectl")
        self.assertEqual((context.status, context.detail, context.required), (Status.OK, "kind-dev", False))

    def test_no_context(self):
        with mock.patch.object(checks, "run", return_value=fail("error: current-context is not set")):
            context = checks.check_kube_context("/usr/bin/kubectl")
        self.assertEqual((context.status, context.hint), (Status.WARN, "kube_context"))


def kubectl(context="kind-dev", nodes="kind-dev-control-plane"):
    """A fake kubectl: `context` is current, and the cluster answers with `nodes` (a CommandResult fails)."""
    def output(args):
        if "current-context" in args:
            return context
        if "nodes" in args:
            return nodes
        return KUBECTL
    return output


class KubeClusterTest(unittest.TestCase):
    def test_reachable(self):
        with mock.patch.object(checks, "run", return_value=ok("desktop-control-plane desktop-worker")) as run:
            cluster, nodes = checks.check_kube_cluster("/usr/bin/kubectl", "docker-desktop")
        self.assertEqual((cluster.status, cluster.required), (Status.OK, False))
        self.assertEqual(nodes, ["desktop-control-plane", "desktop-worker"])
        self.assertEqual(run.call_args.args[0][1:3], ["--context", "docker-desktop"])

    def test_unreachable(self):
        refused = fail("The connection to the server 127.0.0.1:6443 was refused - did you specify the right host or port?")
        with mock.patch.object(checks, "run", return_value=refused):
            cluster, nodes = checks.check_kube_cluster("/usr/bin/kubectl", "docker-desktop")
        self.assertEqual((cluster.status, cluster.hint, nodes), (Status.WARN, "kube_cluster", []))
        self.assertIn("connection to the server", cluster.detail)


class CheckKubernetesTest(unittest.TestCase):
    def test_full_setup(self):
        with fake_system({"kubectl": kubectl("k3d-dev", "k3d-dev-server-0"), "helm": "v3.16.3+gcfd0749", "k3d": "k3d version v5.8.3"}):
            kubectl_tool, context, cluster, helm, local = checks.check_kubernetes(LINUX)
        self.assertEqual((kubectl_tool.version, context.detail, helm.version), ("1.32.0", "k3d-dev", "3.16.3"))
        self.assertIs(cluster.status, Status.OK)
        self.assertEqual((local.name, local.provider, local.version), ("local cluster", "k3d", "5.8.3"))

    def test_other_linux_accepts_any_cluster_tool(self):
        with fake_system({"kubectl": kubectl("minikube", "minikube"), "minikube": "v1.34.0"}):
            *_, local = checks.check_kubernetes(FEDORA)
        self.assertEqual(local.provider, "minikube")

    def test_docker_desktop_needs_no_cluster_cli(self):
        # Docker Desktop's Kubernetes with the kind provisioner, as on Windows and in WSL: no kind/k3d binary installed.
        for platform in (WINDOWS, WSL, MACOS):
            with self.subTest(platform=platform.name),                     fake_system({"kubectl": kubectl("docker-desktop", "desktop-control-plane")}):
                *_, cluster, helm, local = checks.check_kubernetes(platform)
                self.assertIs(cluster.status, Status.OK)
                self.assertEqual((local.status, local.provider), (Status.OK, "docker-desktop"))
                self.assertEqual(local.detail, "Docker Desktop Kubernetes (kind)")

    def test_docker_desktop_kubeadm(self):
        with fake_system({"kubectl": kubectl("docker-desktop", "docker-desktop")}):
            *_, local = checks.check_kubernetes(WINDOWS)
        self.assertEqual(local.detail, "Docker Desktop Kubernetes (kubeadm)")

    def test_docker_desktop_not_running(self):
        with fake_system({"kubectl": kubectl("docker-desktop", fail("Unable to connect to the server: EOF"))}):
            *_, cluster, helm, local = checks.check_kubernetes(WINDOWS)
        self.assertEqual((cluster.status, cluster.hint), (Status.WARN, "kube_cluster"))
        self.assertEqual((local.status, local.hint), (Status.MISSING, "local_cluster"))
        self.assertIn("Docker Desktop", local.detail)
        self.assertNotIn("k3d", local.detail)

    def test_ubuntu_requires_k3d(self):
        # kind, minikube or Docker Desktop do not count on an Ubuntu server: the local cluster is k3d.
        with fake_system({"kubectl": kubectl("docker-desktop", "desktop-control-plane"), "kind": "kind v0.27.0",
                          "minikube": "v1.34.0"}):
            *_, local = checks.check_kubernetes(LINUX)
        self.assertEqual((local.status, local.hint), (Status.MISSING, "local_cluster"))
        self.assertEqual(local.detail, "k3d not found (on Ubuntu the local cluster is k3d)")

    def test_without_kubectl(self):
        with fake_system({}):
            kubectl_tool, helm, cluster = checks.check_kubernetes(FEDORA)
        self.assertEqual((kubectl_tool.status, kubectl_tool.hint), (Status.MISSING, "kubectl"))
        self.assertFalse(helm.required or cluster.required)
        self.assertIn("Docker Desktop's Kubernetes also works", cluster.detail)


class DockerDesktopHintsTest(unittest.TestCase):
    """On Windows and WSL the only local cluster suggested is Docker Desktop's Kubernetes (kind)."""

    def test_only_docker_desktop_is_suggested(self):
        for platform in (WINDOWS, WSL):
            for key in ("kube_context", "kube_cluster", "local_cluster"):
                with self.subTest(platform=platform.name, key=key):
                    lines = install_hints.hint_for(key, platform)
                    self.assertTrue(any("Docker Desktop" in line for line in lines))
                    self.assertFalse(any(word in line for line in lines for word in ("k3d", "minikube")))
                    self.assertIn("docs.docker.com", install_hints.docs_for(key, platform))

    def test_other_platforms_keep_their_hints(self):
        self.assertTrue(any("k3d" in line for line in install_hints.hint_for("local_cluster", MACOS)))
        self.assertIn("k3d.io", install_hints.docs_for("local_cluster", MACOS))


class UbuntuHintsTest(unittest.TestCase):
    """On Ubuntu outside WSL the only setup suggested is the docker.io apt package plus k3d."""

    def test_only_k3d_is_suggested(self):
        for key in ("kube_context", "kube_cluster", "local_cluster"):
            with self.subTest(key=key):
                lines = install_hints.hint_for(key, LINUX)
                self.assertTrue(any("k3d" in line for line in lines))
                for word in ("kind", "minikube", "Docker Desktop"):
                    self.assertFalse(any(word in line for line in lines), word)
                self.assertIn("k3d.io", install_hints.docs_for(key, LINUX))

    def test_docker_comes_from_docker_io(self):
        lines = install_hints.hint_for("docker", LINUX)
        self.assertIn("sudo apt update && sudo apt install -y docker.io", lines)
        self.assertFalse(any("get.docker.com" in line or "Docker Desktop" in line for line in lines))
        self.assertTrue(any("docker.io" in line for line in install_hints.hint_for("local_cluster", LINUX)))
        self.assertIn("packages.ubuntu.com/docker.io", install_hints.docs_for("docker", LINUX))
        self.assertEqual(install_hints.docs_for("docker", WSL), install_hints.DOCS["docker"])  # WSL: Docker Desktop


class LocalContextTest(unittest.TestCase):
    def test_disposable_local_clusters(self):
        for context in ("docker-desktop", "kind-dev", "minikube", "k3d-test", "rancher-desktop", "orbstack", "colima"):
            self.assertTrue(smoke.LOCAL_KUBE_CONTEXT.match(context), context)
        for context in ("arn:aws:eks:us-east-1:1:cluster/prod", "gke_project_zone_prod", "kind", "my-minikube"):
            self.assertFalse(smoke.LOCAL_KUBE_CONTEXT.match(context), context)


class KubernetesSmokeTest(unittest.TestCase):
    def tools(self, context="kind-dev", context_status=Status.OK):
        return [tool("kubectl"), tool("kube context", status=context_status, detail=context, required=False)]

    def test_local_cluster_runs_a_pod_and_deletes_it(self):
        smoke_run = run_smoke("kubernetes", self.tools(), "hello from Kubernetes")
        self.assertIs(smoke_run.result.status, Status.OK)
        run, delete = smoke_run.commands
        self.assertEqual(run[:3], ["/usr/bin/kubectl", "--context", "kind-dev"])
        self.assertIn("--rm", run)
        pod = run[run.index("run") + 1]
        self.assertTrue(pod.startswith("devenv-check-hello-"))
        self.assertEqual(delete[3:6], ["delete", "pod", pod])

    def test_pod_is_deleted_even_when_it_fails(self):
        smoke_run = run_smoke("kubernetes", self.tools(), lambda args: fail("ImagePullBackOff") if "run" in args else "")
        self.assertIs(smoke_run.result.status, Status.MISSING)
        self.assertIn("delete", smoke_run.commands[-1])

    def test_remote_context_is_only_dry_run(self):
        def output(args):
            return f"pod/{args[args.index('run') + 1]}"

        smoke_run = run_smoke("kubernetes", self.tools("prod-eu-1"), output)
        self.assertIs(smoke_run.result.status, Status.OK)
        (command,) = smoke_run.commands  # nothing to clean up: nothing was created
        self.assertIn("--dry-run=server", command)
        self.assertIn("nothing was created", smoke_run.result.detail)

    def test_skips(self):
        self.assertEqual(run_smoke("kubernetes", [tool("kubectl", status=Status.MISSING)]).result.detail,
                         "skipped: kubectl not available")
        self.assertEqual(run_smoke("kubernetes", self.tools("", Status.WARN)).result.detail, "skipped: no current kube context")
        self.assertEqual(run_smoke("kubernetes", [tool("kubectl")]).result.status, Status.SKIPPED)
        unreachable = self.tools() + [tool("kube cluster", status=Status.WARN, required=False)]
        self.assertEqual(run_smoke("kubernetes", unreachable).result.detail, "skipped: cluster not reachable")


if __name__ == "__main__":
    unittest.main()
