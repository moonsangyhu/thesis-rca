"""Regression tests for F1 sealed-memory recovery.

F1 must restore the exact request and limit captured before the OOM injection;
Kubernetes rollout history is not a source of truth for that state.
"""
import unittest
from unittest.mock import patch

from scripts.fault_inject.injector import FaultInjector
from scripts.stabilize.recovery import Recovery


def _cartservice_deployment(request="64Mi", limit="128Mi"):
    return {
        "spec": {
            "template": {
                "spec": {
                    "containers": [{
                        "name": "server",
                        "resources": {
                            "requests": {"memory": request},
                            "limits": {"memory": limit},
                        },
                    }]
                }
            }
        }
    }


class F1MemoryRecoveryTests(unittest.TestCase):
    @patch("scripts.fault_inject.injector.kubectl")
    @patch("scripts.fault_inject.injector.kubectl_get_json")
    def test_injector_seals_target_container_and_both_memory_values(self, get_json, kubectl):
        get_json.return_value = _cartservice_deployment()
        kubectl.return_value = "patched"

        result = FaultInjector()._inject_f1_oomkilled("cartservice", 1, {})

        self.assertEqual(result["container_name"], "server")
        self.assertEqual(result["original_request"], "64Mi")
        self.assertEqual(result["original_limit"], "128Mi")
        kubectl.assert_called_once_with(
            "set", "resources", "deployment", "cartservice",
            "--containers=server", "--limits=memory=32Mi", "--requests=memory=32Mi",
        )

    @patch("scripts.stabilize.recovery.kubectl")
    @patch("scripts.stabilize.recovery.kubectl_get_json")
    def test_recovery_restores_exact_sealed_request_and_limit(self, get_json, kubectl):
        get_json.return_value = _cartservice_deployment()
        result = Recovery()._recover_f1(1, {
            "target_service": "cartservice",
            "container_name": "server",
            "original_request": "64Mi",
            "original_limit": "128Mi",
        })

        self.assertEqual(result, {
            "action": "restore_memory_resources", "target": "cartservice",
        })
        self.assertEqual(kubectl.call_args_list[0].args, (
            "set", "resources", "deployment/cartservice",
            "--containers=server", "--limits=memory=128Mi",
            "--requests=memory=64Mi",
        ))
        self.assertEqual(kubectl.call_args_list[1].args, (
            "rollout", "status", "deployment/cartservice", "--timeout=120s",
        ))
        self.assertEqual(kubectl.call_args_list[1].kwargs, {"timeout": 150})

    def test_recovery_rejects_incomplete_sealed_receipt(self):
        with self.assertRaisesRegex(RuntimeError, "F1 recovery receipt is incomplete"):
            Recovery()._recover_f1(1, {
                "target_service": "cartservice",
                "container_name": "server",
                "original_limit": "128Mi",
            })

    @patch("scripts.stabilize.recovery.kubectl")
    @patch("scripts.stabilize.recovery.kubectl_get_json")
    def test_recovery_rejects_non_exact_poststate(self, get_json, _kubectl):
        get_json.return_value = _cartservice_deployment(request="32Mi", limit="128Mi")
        with self.assertRaisesRegex(RuntimeError, "F1 desired memory state was not exactly restored"):
            Recovery()._recover_f1(1, {
                "target_service": "cartservice",
                "container_name": "server",
                "original_request": "64Mi",
                "original_limit": "128Mi",
            })
