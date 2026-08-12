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
from scripts.fault_inject.config import NAMESPACE, WORKER_NODES

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
            "F11": self._recover_f11_network_delay,
            "F12": self._recover_f12_network_loss,
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
        # Clean up failed/evicted pods before waiting
        self._cleanup_failed_pods()
        # Only node-level network faults need a namespace-wide restart to flush
        # stale netem state. Restarting every deployment after resource faults
        # creates unrelated rollout state and can hide an incomplete restore.
        if fault_id in {"F11", "F12"}:
            self._restart_all_deployments()
        # Wait for pods to stabilize
        self._wait_for_healthy()
        # Verify all service endpoints have at least one ready address
        ep_ok, ep_issues = self._verify_endpoints()
        if not ep_ok:
            logger.warning("Endpoint verification issues: %s — retrying after 30s", ep_issues)
            time.sleep(30)
            ep_ok, ep_issues = self._verify_endpoints()
            if not ep_ok:
                logger.error("Endpoint verification still failing: %s", ep_issues)

        # Comprehensive verification (100% restoration guarantee)
        from scripts.stabilize.health_verify import comprehensive_health_check
        ok, issues = comprehensive_health_check(max_retries=3, retry_delay=30)
        if not ok:
            logger.error("Comprehensive health check FAILED: %s — attempting full reset", issues)
            self._full_reset()
            self._wait_for_healthy(timeout=300)
            ok2, issues2 = comprehensive_health_check(max_retries=2, retry_delay=20)
            if not ok2:
                logger.error("CRITICAL: Cluster not fully restored after full reset: %s", issues2)
                result["health_check_passed"] = False
                result["remaining_issues"] = issues2
                return result
        result["health_check_passed"] = True
        return result

    def _full_reset(self) -> dict:
        """Nuclear option: re-apply original manifests."""
        logger.info("Full reset: re-applying original manifests")
        result = kubectl("apply", "-f", ORIGINAL_MANIFEST, namespace=NAMESPACE)
        return {"action": "full_reset", "output": result}

    def _wait_for_healthy(self, timeout: int = 300, min_pods: int = 12):
        """Wait until all deployments available AND running pod count >= min_pods."""
        logger.info("Waiting for boutique pods to stabilize...")
        start = time.time()
        while time.time() - start < timeout:
            # Check deployments
            output = kubectl(
                "get", "deployments", "-o",
                "jsonpath={.items[*].status.conditions[?(@.type=='Available')].status}",
            )
            deploys_ok = output and all(s == "True" for s in output.split())

            # Check running pod count
            pod_output = kubectl(
                "get", "pods", "--field-selector=status.phase=Running",
                "--no-headers",
            )
            running_count = len([l for l in pod_output.strip().split("\n") if l.strip()]) if pod_output else 0

            if deploys_ok and running_count >= min_pods:
                logger.info(
                    "All deployments healthy, %d pods running (%.0fs)",
                    running_count, time.time() - start,
                )
                return True
            logger.info(
                "Stabilizing... deploys_ok=%s, running_pods=%d/%d (%.0fs)",
                deploys_ok, running_count, min_pods, time.time() - start,
            )
            time.sleep(10)
        logger.warning("Timeout waiting for healthy state after %ds", timeout)
        return False

    def _cleanup_failed_pods(self):
        """Delete Failed/Evicted pods to prevent accumulation."""
        for phase in ["Failed", "Succeeded"]:
            try:
                output = kubectl("delete", "pods", f"--field-selector=status.phase={phase}")
                if output and "deleted" in output:
                    logger.info("Cleaned up %s pods: %s", phase, output.strip())
            except Exception as e:
                logger.warning("Failed to cleanup %s pods: %s", phase, e)

    def _restart_all_deployments(self):
        """Rollout restart all deployments to flush stale network state (e.g., tc netem residuals)."""
        try:
            deployments = kubectl("get", "deployments", "-o", "name", namespace=NAMESPACE)
            for deployment in deployments.splitlines():
                if deployment.strip():
                    output = kubectl(
                        "rollout", "restart", deployment.strip(), namespace=NAMESPACE
                    )
                    logger.info(
                        "Rollout restart %s: %s",
                        deployment.strip(), (output or "").strip(),
                    )
        except Exception as e:
            logger.warning("Failed to rollout restart deployments: %s", e)

    def _verify_endpoints(self) -> tuple[bool, list[str]]:
        """Verify all services in NAMESPACE have at least one ready endpoint address."""
        issues = []
        try:
            ep_json = kubectl_get_json("endpoints", namespace=NAMESPACE)
            items = ep_json.get("items", []) if ep_json else []
            for ep in items:
                name = ep.get("metadata", {}).get("name", "")
                subsets = ep.get("subsets", [])
                ready_count = sum(
                    len(s.get("addresses", [])) for s in (subsets or [])
                )
                if ready_count == 0:
                    issues.append(f"endpoint/{name}: 0 ready addresses")
            if issues:
                logger.warning("Endpoint issues: %s", issues)
                return False, issues
        except Exception as e:
            logger.warning("Endpoint verification error: %s", e)
            return False, [str(e)]
        return True, []

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
        node = ctx.get("node", next(iter(WORKER_NODES)))
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
            kubectl_delete("pv", "prometheus-capacity-probe-pv", namespace="")
        elif trial == 3:
            kubectl_delete("pvc", "storage-probe-pvc")
            kubectl(
                "scale", "deployment", "local-path-provisioner",
                "--replicas=1", namespace="local-path-storage",
            )
        elif trial == 4:
            kubectl_delete("pvc", "redis-cart-rwx")
        elif trial == 5:
            kubectl_delete("pod", "grafana-storage-probe", namespace="monitoring")
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
        """Restore the exact pre-injection CPU resources and verify desired state."""
        target = ctx.get("target_service", "")
        container = ctx.get("container_name", "")
        original_limit = ctx.get("original_cpu_limit", "")
        original_request = ctx.get("original_cpu_request", "")
        if not all((target, container, original_limit, original_request)):
            raise RuntimeError("F7 recovery receipt is incomplete")
        kubectl(
            "set", "resources", "deployment", target,
            f"--containers={container}",
            f"--limits=cpu={original_limit}",
            f"--requests=cpu={original_request}",
        )
        kubectl("rollout", "status", f"deployment/{target}", "--timeout=120s", timeout=150)
        deployment = kubectl_get_json("deployment", target)
        metadata = deployment.get("metadata", {})
        spec = deployment.get("spec", {})
        status = deployment.get("status", {})
        current = next(
            (
                item for item in spec.get("template", {}).get("spec", {}).get("containers", [])
                if item.get("name") == container
            ),
            None,
        )
        resources = (current or {}).get("resources", {})
        replicas = spec.get("replicas", 0)
        restored = all((
            current is not None,
            resources.get("limits", {}).get("cpu") == original_limit,
            resources.get("requests", {}).get("cpu") == original_request,
            status.get("observedGeneration") == metadata.get("generation"),
            status.get("updatedReplicas", 0) == replicas,
            status.get("readyReplicas", 0) == replicas,
            status.get("availableReplicas", 0) == replicas,
        ))
        if not restored:
            raise RuntimeError("F7 desired CPU state was not fully restored")
        return {
            "action": "restore_cpu_resources",
            "target": target,
            "container_name": container,
            "cpu_limit": original_limit,
            "cpu_request": original_request,
            "desired_state_verified": True,
        }

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

        return {"action": "delete_quota", "trial": trial}

    # ── F11: Network Delay ──────────────────────────────────────

    def _recover_f11_network_delay(self, trial: int, ctx: dict) -> dict:
        """Remove tc netem delay rules."""
        node_name = ctx.get("node", next(iter(WORKER_NODES)))
        iface = ctx.get("interface", "vmbr0")  # 재구축 랩 노드망 인터페이스(옛 ens18 → vmbr0)
        output = ssh_node(node_name, f"sudo tc qdisc del dev {iface} root 2>/dev/null; echo ok", timeout=15)
        logger.info("F11 recovered: removed netem delay on %s", node_name)
        return {"action": "remove_netem_delay", "node": node_name, "output": output}

    # ── F12: Network Loss ───────────────────────────────────────

    def _recover_f12_network_loss(self, trial: int, ctx: dict) -> dict:
        """Remove tc netem loss rules."""
        node_name = ctx.get("node", next(iter(WORKER_NODES)))
        iface = ctx.get("interface", "vmbr0")  # 재구축 랩 노드망 인터페이스(옛 ens18 → vmbr0)
        output = ssh_node(node_name, f"sudo tc qdisc del dev {iface} root 2>/dev/null; echo ok", timeout=15)
        logger.info("F12 recovered: removed netem loss on %s", node_name)
        return {"action": "remove_netem_loss", "node": node_name, "output": output}
