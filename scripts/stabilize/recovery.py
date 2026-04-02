"""
Recovery/stabilization scripts for each fault type.

Reverts fault injection and restores cluster to healthy state.
"""
import logging
import time

from scripts.fault_inject.base import (
    kubectl, kubectl_apply, kubectl_delete, kubectl_patch,
    kubectl_get_json, ssh_node,
)
from scripts.fault_inject.config import NAMESPACE

logger = logging.getLogger(__name__)

# Original Online Boutique manifest path (for full reset)
ORIGINAL_MANIFEST = "/tmp/thesis-rca-work/k8s/app/online-boutique.yaml"


class Recovery:
    """Recover from injected faults."""

    def __init__(self):
        self._recoverers = {
            "F1": self._recover_f1,
            "F2": self._recover_f2,
            "F3": self._recover_f3,
            "F4": self._recover_f4,
            "F5": self._recover_f5,
            "F6": self._recover_f6,
            "F7": self._recover_f7,
            "F8": self._recover_f8,
            "F9": self._recover_f9,
            "F10": self._recover_f10,
        }

    def recover(self, fault_id: str, trial: int, injection_result: dict) -> dict:
        """
        Recover from a fault injection.

        Args:
            fault_id: e.g. "F1"
            trial: trial number
            injection_result: dict returned by FaultInjector.inject()
        """
        logger.info("Recovering from %s trial %d...", fault_id, trial)
        recoverer = self._recoverers.get(fault_id)
        if not recoverer:
            return self._full_reset()

        result = recoverer(trial, injection_result)
        # Wait for pods to stabilize
        self._wait_for_healthy()
        return result

    def _full_reset(self) -> dict:
        """Nuclear option: re-apply original manifests."""
        logger.info("Full reset: re-applying original manifests")
        result = kubectl("apply", "-f", ORIGINAL_MANIFEST, namespace=NAMESPACE)
        return {"action": "full_reset", "output": result}

    def _wait_for_healthy(self, timeout: int = 300):
        """Wait until all deployments in boutique are available."""
        logger.info("Waiting for boutique pods to stabilize...")
        start = time.time()
        while time.time() - start < timeout:
            output = kubectl(
                "get", "deployments", "-o",
                "jsonpath={.items[*].status.conditions[?(@.type=='Available')].status}",
            )
            if output and all(s == "True" for s in output.split()):
                logger.info("All deployments healthy (%.0fs)", time.time() - start)
                return
            time.sleep(10)
        logger.warning("Timeout waiting for healthy state after %ds", timeout)

    # ── Per-fault recovery ─────────────────────────────────────────

    def _recover_f1(self, trial: int, ctx: dict) -> dict:
        """Remove memory limit patch → rollout restart."""
        target = ctx.get("target_service", "")
        # Remove resource limits by patching with empty/null
        # Simplest: rollout undo or re-apply original
        kubectl("rollout", "undo", f"deployment/{target}")
        kubectl("rollout", "status", f"deployment/{target}", "--timeout=120s", timeout=150)
        return {"action": "rollout_undo", "target": target}

    def _recover_f2(self, trial: int, ctx: dict) -> dict:
        """Remove command override → rollout undo."""
        target = ctx.get("target_service", "")
        kubectl("rollout", "undo", f"deployment/{target}")
        kubectl("rollout", "status", f"deployment/{target}", "--timeout=120s", timeout=150)
        return {"action": "rollout_undo", "target": target}

    def _recover_f3(self, trial: int, ctx: dict) -> dict:
        """Restore correct image → rollout undo."""
        target = ctx.get("target_service", "")
        kubectl("rollout", "undo", f"deployment/{target}")
        kubectl("rollout", "status", f"deployment/{target}", "--timeout=120s", timeout=150)
        return {"action": "rollout_undo", "target": target}

    def _recover_f4(self, trial: int, ctx: dict) -> dict:
        """Restore node health."""
        node = ctx.get("node", "worker01")
        recovery_commands = {
            1: [
                "sudo systemctl start kubelet",
            ],
            2: [
                "sudo iptables -D OUTPUT -p tcp --dport 6443 -j DROP",
            ],
            3: [
                "sudo pkill -9 stress-ng",
            ],
            4: [
                "sudo rm -f /tmp/diskfill",
            ],
            5: [
                "sudo systemctl start containerd",
                "sudo systemctl restart kubelet",
            ],
        }

        commands = recovery_commands.get(trial, ["sudo systemctl start kubelet"])
        outputs = []
        for cmd in commands:
            outputs.append(ssh_node(node, cmd))

        # Uncordon node
        kubectl("uncordon", node, namespace="")
        time.sleep(30)  # Wait for node to rejoin

        return {"action": "restore_node", "node": node, "outputs": outputs}

    def _recover_f5(self, trial: int, ctx: dict) -> dict:
        """Delete faulty PVC/PV resources."""
        if trial == 1:
            kubectl_delete("pvc", "redis-cart-fault")
        elif trial == 2:
            kubectl_delete("pvc", "prometheus-fault", namespace="monitoring")
        elif trial == 3:
            kubectl(
                "scale", "deployment", "local-path-provisioner",
                "--replicas=1", namespace="local-path-storage",
            )
        elif trial == 4:
            kubectl_delete("pvc", "redis-cart-rwx")
        elif trial == 5:
            kubectl_delete("pvc", "grafana-fault-pvc", namespace="monitoring")
            kubectl_delete("pv", "grafana-fault-pv", namespace="")
        return {"action": "cleanup_pvc", "trial": trial}

    def _recover_f6(self, trial: int, ctx: dict) -> dict:
        """Delete injected NetworkPolicies."""
        policy_names = {
            1: "fault-deny-all",
            2: "fault-block-cart",
            3: "fault-block-payment",
            4: "fault-block-dns",
            5: "fault-block-redis",
        }
        name = policy_names.get(trial, "")
        if name:
            kubectl_delete("networkpolicy", name)
        return {"action": "delete_network_policy", "name": name}

    def _recover_f7(self, trial: int, ctx: dict) -> dict:
        """Remove CPU limit patch."""
        target = ctx.get("target_service", "")
        kubectl("rollout", "undo", f"deployment/{target}")
        kubectl("rollout", "status", f"deployment/{target}", "--timeout=120s", timeout=150)
        return {"action": "rollout_undo", "target": target}

    def _recover_f8(self, trial: int, ctx: dict) -> dict:
        """Fix service configuration."""
        if trial in (1, 2, 5):
            # Re-apply original manifests to fix service
            kubectl("apply", "-f", ORIGINAL_MANIFEST, namespace=NAMESPACE)
        elif trial == 3:
            # Rollout undo to restore labels
            kubectl("rollout", "undo", "deployment/paymentservice")
            kubectl("rollout", "status", "deployment/paymentservice", "--timeout=120s", timeout=150)
        elif trial == 4:
            target = ctx.get("target_service", "shippingservice")
            kubectl("rollout", "undo", f"deployment/{target}")
            kubectl("rollout", "status", f"deployment/{target}", "--timeout=120s", timeout=150)
        return {"action": "restore_service", "trial": trial}

    def _recover_f9(self, trial: int, ctx: dict) -> dict:
        """Fix secrets/configmaps."""
        target = ctx.get("target_service", "")
        kubectl("rollout", "undo", f"deployment/{target}")
        # Clean up any dummy secrets
        kubectl_delete("secret", "checkout-secret-bad")
        kubectl("rollout", "status", f"deployment/{target}", "--timeout=120s", timeout=150)
        return {"action": "rollout_undo_and_cleanup", "target": target}

    def _recover_f10(self, trial: int, ctx: dict) -> dict:
        """Remove ResourceQuota/LimitRange."""
        if trial <= 4:
            names = {
                1: "fault-quota",
                2: "fault-quota-cpu",
                3: "fault-quota-mem",
                4: "fault-quota-svc",
            }
            kubectl_delete("resourcequota", names.get(trial, "fault-quota"))
        elif trial == 5:
            kubectl_delete("limitrange", "fault-limitrange")

        # Restart any stuck deployments
        time.sleep(5)
        kubectl("rollout", "restart", "deployment", "--all", namespace=NAMESPACE)
        return {"action": "delete_quota", "trial": trial}
