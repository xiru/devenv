"""Kubernetes: kubectl, the current context, helm, a local cluster tool and the pod hello world."""

import unittest
from unittest import mock

from devenv_check import checks, smoke
from devenv_check.checks import Status
from tests.helpers import LINUX, fail, fake_system, ok, run_smoke, tool

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


class CheckKubernetesTest(unittest.TestCase):
    def test_full_setup(self):
        with fake_system({"kubectl": lambda args: "docker-desktop" if "current-context" in args else KUBECTL,
                          "helm": "v3.16.3+gcfd0749", "minikube": "v1.34.0"}):
            kubectl, context, helm, cluster = checks.check_kubernetes(LINUX)
        self.assertEqual((kubectl.version, context.detail, helm.version), ("1.32.0", "docker-desktop", "3.16.3"))
        self.assertEqual((cluster.name, cluster.provider), ("local cluster tool", "minikube"))

    def test_without_kubectl(self):
        with fake_system({}):
            kubectl, helm, cluster = checks.check_kubernetes(LINUX)
        self.assertEqual((kubectl.status, kubectl.hint), (Status.MISSING, "kubectl"))
        self.assertFalse(helm.required or cluster.required)
        self.assertIn("Docker Desktop's Kubernetes also works", cluster.detail)


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


if __name__ == "__main__":
    unittest.main()
