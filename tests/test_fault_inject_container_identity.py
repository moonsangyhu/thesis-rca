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
        "scripts.fault_inject.injector.get_primary_container",
        return_value=("server", "example/shippingservice:stable"),
    )
    def test_f8_t4_patches_primary_container_not_a_sidecar(self, primary, patcher):
        result = self.injector._inject_f8_service_endpoint("shippingservice", 4, {})

        patch = patcher.call_args.args[2]
        self.assertEqual(patch["spec"]["template"]["spec"]["containers"][0]["name"], "server")
        self.assertEqual(result["container_name"], "server")

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
