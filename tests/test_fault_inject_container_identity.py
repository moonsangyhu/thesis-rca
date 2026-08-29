"""Regression coverage for deployment-name/container-name divergence."""

import unittest
from unittest.mock import patch

from scripts.fault_inject.injector import FaultInjector
from experiments.v2_3.injection_validator import LiveInjectionValidator


class WorkloadContainerIdentityTests(unittest.TestCase):
    def setUp(self):
        self.injector = FaultInjector()

    @patch("scripts.fault_inject.injector.kubectl_patch", return_value="patched")
    @patch(
        "scripts.fault_inject.injector.get_primary_container",
        return_value=("server", "example/shippingservice:stable"),
    )
    def test_f2_patches_primary_container_not_deployment_name(self, primary, patcher):
        result = self.injector._inject_f2_crashloop("shippingservice", 4, {})

        patcher.assert_called_once()
        patch = patcher.call_args.args[2]
        self.assertEqual(patch["spec"]["template"]["spec"]["containers"][0]["name"], "server")
        self.assertEqual(result["container_name"], "server")

    @patch("scripts.fault_inject.injector.kubectl_patch", return_value="patched")
    @patch(
        "scripts.fault_inject.injector.get_primary_container",
        return_value=("server", "example/shippingservice:stable"),
    )
    def test_f3_patches_primary_container_not_deployment_name(self, primary, patcher):
        result = self.injector._inject_f3_imagepull("shippingservice", 3, {})

        patch = patcher.call_args.args[2]
        self.assertEqual(patch["spec"]["template"]["spec"]["containers"][0]["name"], "server")
        self.assertEqual(result["container_name"], "server")

    @patch("scripts.fault_inject.injector.kubectl_patch", return_value="patched")
    @patch(
        "scripts.fault_inject.injector.kubectl_get_json",
        return_value={"spec": {"template": {"spec": {"containers": [
            {"name": "server", "readinessProbe": {"grpc": {"port": 50051}}},
        ]}}}},
    )
    @patch(
        "scripts.fault_inject.injector.get_primary_container",
        return_value=("server", "example/shippingservice:stable"),
    )
    def test_f8_t4_replaces_probe_on_primary_container(self, primary, deployment, patcher):
        result = self.injector._inject_f8_service_endpoint("shippingservice", 4, {})

        patch = patcher.call_args.args[2]
        self.assertEqual(patcher.call_args.kwargs["patch_type"], "json")
        self.assertEqual(patch[0]["op"], "replace")
        self.assertEqual(patch[0]["path"], "/spec/template/spec/containers/0/readinessProbe")
        self.assertEqual(patch[0]["value"]["httpGet"]["path"], "/nonexistent")
        self.assertEqual(result["container_name"], "server")

    @patch("scripts.fault_inject.injector.load_trial", return_value={
        "target_service": "shippingservice",
    })
    @patch(
        "scripts.fault_inject.injector.kubectl_get_json",
        return_value={"spec": {"template": {"spec": {"containers": [
            {"name": "server", "readinessProbe": {"grpc": {"port": 50051}}},
        ]}}}},
    )
    @patch(
        "scripts.fault_inject.injector.get_primary_container",
        return_value=("server", "example/shippingservice:stable"),
    )
    def test_f8_t4_seals_original_probe_before_mutation(self, primary, deployment, trial):
        context = self.injector.prepare_recovery_context("F8", 4)
        self.assertEqual(context["container_name"], "server")
        self.assertEqual(context["original_readiness_probe"], {"grpc": {"port": 50051}})

    @patch("scripts.fault_inject.injector.kubectl_patch", return_value="patched")
    @patch(
        "scripts.fault_inject.injector.get_primary_container",
        return_value=("server", "example/cartservice:stable"),
    )
    def test_f9_patches_primary_container_not_deployment_name(self, primary, patcher):
        self.injector._inject_f9_secret_configmap("cartservice", 1, {})

        patch = patcher.call_args.args[2]
        self.assertEqual(patch["spec"]["template"]["spec"]["containers"][0]["name"], "server")

    def test_validator_binds_f2_to_receipted_primary_container(self):
        deployment = {
            "spec": {"template": {"spec": {"containers": [
                {"name": "server", "command": ["/bin/sh", "-c", "exit 1"]},
            ]}}}
        }
        validator = LiveInjectionValidator(
            lambda resource, name, namespace: deployment,
            lambda node, command: "",
        )
        result = validator.validate("F2", 4, {"target_service": "shippingservice"}, {
            "fault_id": "F2", "trial": 4, "target_service": "shippingservice",
            "action": "override_command", "container_name": "server",
            "command": ["/bin/sh", "-c", "exit 1"],
        })
        self.assertTrue(result["command_bound"])


if __name__ == "__main__":
    unittest.main()
