"""
Fault injector implementations for F1~F12.

Each fault is injected via kubectl patch/apply/delete.
Node-level faults (F4) use SSH.
"""
import csv
import logging
import time
from pathlib import Path
from typing import Optional

from .base import (
    kubectl, kubectl_apply, kubectl_delete, kubectl_patch,
    kubectl_get_json, get_container_image, ssh_node, git_commit_and_push,
)
from .config import (
    F4_T3_STRESS_BYTES,
    F4_T3_STRESS_LOG_FILE,
    F4_T3_NODE_NAME,
    F4_T3_OBSERVATION_WAIT_SECONDS,
    F4_T3_STRESS_RECEIPT_FILE,
    F4_T3_STRESS_TIMEOUT_SECONDS,
    F4_T3_STRESS_VM_WORKERS,
    F4_T3_STRESS_VERSION,
    INJECTION_WAIT,
    NAMESPACE,
)

logger = logging.getLogger(__name__)

# Ground truth CSV path
GT_CSV = Path(__file__).parent.parent.parent / "results" / "ground_truth.csv"


def load_trial(fault_id: str, trial: int) -> dict:
    """Load a specific trial from ground_truth.csv."""
    with open(GT_CSV) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["fault_id"] == fault_id and int(row["trial"]) == trial:
                return row
    raise ValueError(f"Trial not found: {fault_id} trial {trial}")


class FaultInjector:
    """Inject faults F1~F10 into the boutique namespace."""

    def __init__(self):
        self._injectors = {
            "F1": self._inject_f1_oomkilled,
            "F2": self._inject_f2_crashloop,
            "F3": self._inject_f3_imagepull,
            "F4": self._inject_f4_node_notready,
            "F5": self._inject_f5_pvc_pending,
            "F6": self._inject_f6_network_policy,
            "F7": self._inject_f7_cpu_throttle,
            "F8": self._inject_f8_service_endpoint,
            "F9": self._inject_f9_secret_configmap,
            "F10": self._inject_f10_resource_quota,
            "F11": self._inject_f11_network_delay,
            "F12": self._inject_f12_network_loss,
        }

    def inject(
        self, fault_id: str, trial: int, recovery_context: Optional[dict] = None
    ) -> dict:
        """
        Inject a fault based on ground truth definition.

        Returns:
            dict with injection details and wait_seconds
        """
        gt = load_trial(fault_id, trial)
        target = gt["target_service"]
        method = gt["injection_method"]

        logger.info(
            "Injecting %s trial %d: %s on %s",
            fault_id, trial, gt["fault_name"], target,
        )

        injector = self._injectors.get(fault_id)
        if not injector:
            raise ValueError(f"No injector for {fault_id}")

        if fault_id in {"F4", "F7"}:
            result = injector(target, trial, gt, recovery_context)
        else:
            result = injector(target, trial, gt)
        if fault_id == "F4" and isinstance(recovery_context, dict):
            # Preserve the durably sealed pre-mutation identity alongside the
            # post-launch process receipt.  Runner recovery must receive both.
            result = {**recovery_context, **result}
        result["fault_id"] = fault_id
        result["trial"] = trial
        result["target_service"] = target
        result["wait_seconds"] = (
            F4_T3_OBSERVATION_WAIT_SECONDS
            if (fault_id, trial) == ("F4", 3)
            else INJECTION_WAIT.get(fault_id, 120)
        )
        return result

    def prepare_recovery_context(self, fault_id: str, trial: int) -> dict:
        """Capture reversible pre-state before a V2.3 mutation is attempted."""
        gt = load_trial(fault_id, trial)
        target = gt["target_service"]
        if fault_id in {"F11", "F12"}:
            node_maps = {
                "F11": {1: "yms-proxmox-02", 2: "yms-proxmox-03", 3: "yms-proxmox-02", 4: "yms-proxmox-04", 5: "yms-proxmox-03"},
                "F12": {1: "yms-proxmox-02", 2: "yms-proxmox-03", 3: "yms-proxmox-04", 4: "yms-proxmox-02", 5: "yms-proxmox-03"},
            }
            return {
                "fault_id": fault_id, "trial": trial,
                "target_service": target, "node": node_maps[fault_id][trial],
                "interface": self.NETEM_IFACE,
            }
        if fault_id == "F4":
            nodes = {1: "yms-proxmox-02", 2: "yms-proxmox-03", 3: F4_T3_NODE_NAME, 4: "yms-proxmox-02", 5: "yms-proxmox-03"}
            context = {
                "fault_id": fault_id, "trial": trial,
                "target_service": target, "node": nodes[trial],
            }
            if trial == 3:
                preflight = ssh_node(
                    nodes[trial],
                    "set -eu; command -v stress-ng >/dev/null 2>&1; "
                    "version=$(stress-ng --version 2>/dev/null | "
                    "sed -n 's/^stress-ng, version \\([^ ]*\\).*/\\1/p'); "
                    f"test \"$version\" = \"{F4_T3_STRESS_VERSION}\"; "
                    "if pgrep '^stress-ng' >/dev/null; then exit 126; fi; "
                    f"sudo rm -f {F4_T3_STRESS_RECEIPT_FILE} "
                    f"{F4_T3_STRESS_RECEIPT_FILE}.tmp.* {F4_T3_STRESS_LOG_FILE}; "
                    "sudo sync -f /tmp; "
                    f"sudo test ! -e {F4_T3_STRESS_RECEIPT_FILE}; "
                    "printf '__V23_STRESS_NG_PREFLIGHT__=%s\\n' \"$version\"",
                )
                expected = f"__V23_STRESS_NG_PREFLIGHT__={F4_T3_STRESS_VERSION}"
                if preflight.splitlines().count(expected) != 1:
                    raise RuntimeError("F4 trial 3 stress-ng preflight failed")
                context.update({
                    "stress_ng_version": F4_T3_STRESS_VERSION,
                    "stress_ng_preexisting": False,
                    "stress_receipt_file": F4_T3_STRESS_RECEIPT_FILE,
                    "stress_vm_workers": F4_T3_STRESS_VM_WORKERS,
                })
            return context
        if fault_id != "F7":
            return {
                "fault_id": fault_id, "trial": trial,
                "target_service": target,
            }
        original = kubectl_get_json("deployment", target)
        containers = (
            original.get("spec", {}).get("template", {}).get("spec", {})
            .get("containers", [])
        )
        matched = next(
            (container for container in containers if container.get("name") == target),
            containers[0] if len(containers) == 1 else None,
        )
        if not matched:
            raise RuntimeError(f"F7 target container not found: {target}")
        resources = matched.get("resources", {})
        original_limit = resources.get("limits", {}).get("cpu")
        original_request = resources.get("requests", {}).get("cpu")
        if not original_limit or not original_request:
            raise RuntimeError(f"F7 original CPU resources are incomplete: {target}")
        return {
            "fault_id": fault_id,
            "trial": trial,
            "target_service": target,
            "container_name": matched["name"],
            "original_cpu_limit": original_limit,
            "original_cpu_request": original_request,
        }

    # ── F1: OOMKilled ──────────────────────────────────────────────

    def _inject_f1_oomkilled(self, target: str, trial: int, gt: dict) -> dict:
        """Set very low memory limit to trigger OOMKilled."""
        memory_limits = {
            1: "32Mi",    # cartservice
            2: "24Mi",    # recommendationservice
            3: "16Mi",    # checkoutservice
            4: "16Mi",    # productcatalogservice
            5: "32Mi",    # frontend
        }
        limit = memory_limits.get(trial, "32Mi")

        # Save original for rollback
        original = kubectl_get_json("deployment", target)
        original_limit = None
        if original:
            containers = original.get("spec", {}).get("template", {}).get(
                "spec", {}
            ).get("containers", [])
            for c in containers:
                if c.get("name") == target or len(containers) == 1:
                    original_limit = (
                        c.get("resources", {}).get("limits", {}).get("memory")
                    )

        # Use kubectl set resources (avoids strategic merge patch validation issues)
        result = kubectl(
            "set", "resources", "deployment", target,
            f"--limits=memory={limit}", f"--requests=memory={limit}",
        )
        logger.info("F1 injected: %s memory limit → %s", target, limit)

        return {
            "action": "patch_memory_limit",
            "memory_limit": limit,
            "original_limit": original_limit,
            "kubectl_output": result,
        }

    # ── F2: CrashLoopBackOff ───────────────────────────────────────

    def _inject_f2_crashloop(self, target: str, trial: int, gt: dict) -> dict:
        """Override container command to crash immediately."""
        # Use command override to make container exit immediately
        crash_commands = {
            1: ["/bin/sh", "-c", "exit 1"],                # paymentservice
            2: ["/bin/sh", "-c", "exit 1"],                # emailservice
            3: ["/bin/sh", "-c", "exit 1"],                # currencyservice
            4: ["/bin/sh", "-c", "exit 1"],                # shippingservice
            5: ["/bin/sh", "-c", "exit 2"],                # adservice (exit 2 = usage error)
        }
        cmd = crash_commands.get(trial, ["/bin/sh", "-c", "exit 1"])

        image = get_container_image(target)
        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{
                            "name": target,
                            "image": image,
                            "command": cmd,
                        }],
                    },
                },
            },
        }
        result = kubectl_patch("deployment", target, patch)
        logger.info("F2 injected: %s command → crash", target)

        return {"action": "override_command", "command": cmd, "kubectl_output": result}

    # ── F3: ImagePullBackOff ───────────────────────────────────────

    def _inject_f3_imagepull(self, target: str, trial: int, gt: dict) -> dict:
        """Change container image to non-existent version."""
        bad_images = {
            1: f"{target}:v99.99.99",                          # nonexistent tag
            2: f"private.registry.io/boutique/{target}:latest", # private registry
            3: f"gcr.typo.io/google-samples/{target}:latest",   # typo in registry
            4: f"{target}@sha256:000000000000000000000000000000", # bad digest
            5: f"docker.io/ratelimited/{target}:latest",        # rate-limited
        }
        image = bad_images.get(trial, f"{target}:nonexistent")

        patch = {
            "spec": {
                "template": {
                    "spec": {
                        "containers": [{
                            "name": target,
                            "image": image,
                        }],
                    },
                },
            },
        }
        result = kubectl_patch("deployment", target, patch)
        logger.info("F3 injected: %s image → %s", target, image)

        return {"action": "change_image", "image": image, "kubectl_output": result}

    # ── F4: NodeNotReady ───────────────────────────────────────────

    def _inject_f4_node_notready(
        self, target: str, trial: int, gt: dict,
        recovery_context: Optional[dict] = None,
    ) -> dict:
        """Make a worker node NotReady via SSH."""
        stress_launch_marker = "__V23_STRESS_NG_PID__="
        stress_start_marker = "__V23_STRESS_NG_START_TICKS__="
        stress_hash_marker = "__V23_STRESS_NG_CMDLINE_SHA256__="
        if trial == 3 and (
            not isinstance(recovery_context, dict)
            or recovery_context.get("stress_ng_version") != F4_T3_STRESS_VERSION
            or recovery_context.get("stress_ng_preexisting") is not False
            or recovery_context.get("stress_receipt_file") != F4_T3_STRESS_RECEIPT_FILE
            or isinstance(recovery_context.get("stress_vm_workers"), bool)
            or not isinstance(recovery_context.get("stress_vm_workers"), int)
            or recovery_context.get("stress_vm_workers") != F4_T3_STRESS_VM_WORKERS
        ):
            raise RuntimeError("F4 trial 3 sealed recovery preflight is invalid")
        node_actions = {
            1: ("yms-proxmox-02", "sudo systemctl stop kubelet"),
            2: ("yms-proxmox-03", "sudo iptables -A OUTPUT -p tcp --dport 6443 -j DROP"),
            3: (
                F4_T3_NODE_NAME,
                "sudo sh -c 'set -eu; umask 077; "
                "command -v stress-ng >/dev/null 2>&1 || exit 127; "
                "if pgrep '^stress-ng' >/dev/null; then exit 126; fi; "
                f"nohup stress-ng --vm {F4_T3_STRESS_VM_WORKERS} "
                f"--vm-bytes {F4_T3_STRESS_BYTES} "
                f"--vm-keep --timeout {F4_T3_STRESS_TIMEOUT_SECONDS}s "
                f">{F4_T3_STRESS_LOG_FILE} 2>&1 </dev/null & pid=$!; "
                "sleep 1; kill -0 \"$pid\" || exit 1; "
                "start=$(awk \"{print \\$22}\" /proc/$pid/stat); "
                "cmdhash=$(sha256sum /proc/$pid/cmdline | awk \"{print \\$1}\"); "
                f"receipt={F4_T3_STRESS_RECEIPT_FILE}; tmp=${{receipt}}.tmp.$$; "
                "printf \"%s %s %s\\n\" \"$pid\" \"$start\" \"$cmdhash\" >\"$tmp\"; "
                "sync -f \"$tmp\"; mv \"$tmp\" \"$receipt\"; sync -f /tmp; "
                "read rpid rstart rhash <\"$receipt\"; "
                "test \"$rpid\" = \"$pid\"; test \"$rstart\" = \"$start\"; "
                "test \"$rhash\" = \"$cmdhash\"; "
                f"printf \"{stress_launch_marker}%s\\n{stress_start_marker}%s\\n"
                f"{stress_hash_marker}%s\\n\" \"$pid\" \"$start\" \"$cmdhash\"'",
            ),
            4: ("yms-proxmox-02", "sudo fallocate -l $(($(df --output=avail / | tail -1) * 95 / 100))k /tmp/diskfill"),
            5: ("yms-proxmox-03", "sudo systemctl stop containerd"),
        }
        node_name, command = node_actions.get(trial, ("yms-proxmox-02", "sudo systemctl stop kubelet"))

        # Cordon node first for trial 1
        if trial == 1:
            kubectl("cordon", node_name, namespace="")

        output = ssh_node(node_name, command)
        stress_ng_pid = None
        stress_ng_start_ticks = None
        stress_ng_cmdline_sha256 = None
        if trial == 3:
            def marker_value(marker: str) -> str:
                values = [
                    line.removeprefix(marker) for line in output.splitlines()
                    if line.startswith(marker)
                ]
                return values[0] if len(values) == 1 else ""

            pid_value = marker_value(stress_launch_marker)
            start_value = marker_value(stress_start_marker)
            hash_value = marker_value(stress_hash_marker)
            if not pid_value.isdigit() or int(pid_value) <= 1:
                raise RuntimeError("F4 trial 3 stress-ng launch receipt is missing")
            if not start_value.isdigit() or int(start_value) <= 0:
                raise RuntimeError("F4 trial 3 stress-ng start receipt is missing")
            if len(hash_value) != 64 or any(c not in "0123456789abcdef" for c in hash_value):
                raise RuntimeError("F4 trial 3 stress-ng command receipt is missing")
            stress_ng_pid = int(pid_value)
            stress_ng_start_ticks = int(start_value)
            stress_ng_cmdline_sha256 = hash_value
        logger.info("F4 injected: %s on %s", command, node_name)

        result = {
            "action": "node_disruption",
            "node": node_name,
            "command": command,
            "ssh_output": output,
        }
        if stress_ng_pid is not None:
            result["stress_ng_pid"] = stress_ng_pid
            result["stress_ng_start_ticks"] = stress_ng_start_ticks
            result["stress_ng_cmdline_sha256"] = stress_ng_cmdline_sha256
            result["stress_memory_bytes"] = F4_T3_STRESS_BYTES
            result["stress_vm_workers"] = F4_T3_STRESS_VM_WORKERS
            result["stress_timeout_seconds"] = F4_T3_STRESS_TIMEOUT_SECONDS
            result["stress_receipt_file"] = F4_T3_STRESS_RECEIPT_FILE
        return result

    # ── F5: PVCPending ─────────────────────────────────────────────

    def _inject_f5_pvc_pending(self, target: str, trial: int, gt: dict) -> dict:
        """Create PVC that cannot be satisfied."""
        pvc_manifests = {
            1: {
                "apiVersion": "v1",
                "kind": "PersistentVolumeClaim",
                "metadata": {"name": "redis-cart-fault", "namespace": NAMESPACE},
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "storageClassName": "premium-ssd",  # doesn't exist
                    "resources": {"requests": {"storage": "1Gi"}},
                },
            },
            2: {
                "apiVersion": "v1",
                "kind": "PersistentVolumeClaim",
                "metadata": {"name": "prometheus-fault", "namespace": "monitoring"},
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "storageClassName": "capacity-probe",
                    "selector": {"matchLabels": {"capacity-probe": "small"}},
                    "resources": {"requests": {"storage": "500Gi"}},  # too large
                },
            },
            3: None,  # Delete local-path-provisioner
            4: {
                "apiVersion": "v1",
                "kind": "PersistentVolumeClaim",
                "metadata": {"name": "redis-cart-rwx", "namespace": NAMESPACE},
                "spec": {
                    "accessModes": ["ReadWriteMany"],  # not supported
                    "storageClassName": "local-path",
                    "resources": {"requests": {"storage": "1Gi"}},
                },
            },
            5: None,  # Handled specially: PV with bad node affinity
        }

        if trial == 3:
            # Delete local-path-provisioner
            result = kubectl(
                "scale", "deployment", "local-path-provisioner",
                "--replicas=0", namespace="local-path-storage",
            )
            probe = {
                "apiVersion": "v1", "kind": "PersistentVolumeClaim",
                "metadata": {"name": "storage-probe-pvc", "namespace": NAMESPACE},
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "storageClassName": "local-path",
                    "resources": {"requests": {"storage": "1Gi"}},
                },
            }
            result += kubectl_apply(probe)
            return {
                "action": "scale_provisioner_to_zero",
                "pvc": "storage-probe-pvc", "kubectl_output": result,
            }

        if trial == 2:
            # local-path does not reserve requested bytes, so a bare 500Gi PVC
            # can bind despite insufficient disk.  A sealed 1Gi available PV
            # makes the intended capacity mismatch deterministic and observable.
            pv = {
                "apiVersion": "v1", "kind": "PersistentVolume",
                "metadata": {
                    "name": "prometheus-capacity-probe-pv",
                    "labels": {"capacity-probe": "small"},
                },
                "spec": {
                    "capacity": {"storage": "1Gi"},
                    "accessModes": ["ReadWriteOnce"],
                    "storageClassName": "capacity-probe",
                    "hostPath": {"path": "/tmp/prometheus-capacity-probe"},
                },
            }
            r1 = kubectl_apply(pv, namespace="")
            manifest = pvc_manifests[2]
            r2 = kubectl_apply(manifest, namespace="monitoring")
            return {
                "action": "create_pvc", "pvc": "prometheus-fault",
                "capacity_probe_pv": "prometheus-capacity-probe-pv",
                "kubectl_output": r1 + r2,
            }

        if trial == 5:
            # Create PV with impossible node affinity, then PVC
            pv = {
                "apiVersion": "v1",
                "kind": "PersistentVolume",
                "metadata": {"name": "grafana-fault-pv"},
                "spec": {
                    "capacity": {"storage": "1Gi"},
                    "accessModes": ["ReadWriteOnce"],
                    "storageClassName": "manual",
                    "hostPath": {"path": "/tmp/grafana-data"},
                    "nodeAffinity": {
                        "required": {
                            "nodeSelectorTerms": [{
                                "matchExpressions": [{
                                    "key": "kubernetes.io/hostname",
                                    "operator": "In",
                                    "values": ["nonexistent-node"],
                                }],
                            }],
                        },
                    },
                },
            }
            pvc = {
                "apiVersion": "v1",
                "kind": "PersistentVolumeClaim",
                "metadata": {"name": "grafana-fault-pvc", "namespace": "monitoring"},
                "spec": {
                    "accessModes": ["ReadWriteOnce"],
                    "storageClassName": "manual",
                    "resources": {"requests": {"storage": "1Gi"}},
                },
            }
            r1 = kubectl_apply(pv, namespace="")
            r2 = kubectl_apply(pvc, namespace="monitoring")
            pod = {
                "apiVersion": "v1", "kind": "Pod",
                "metadata": {"name": "grafana-storage-probe", "namespace": "monitoring"},
                "spec": {
                    "containers": [{
                        "name": "probe", "image": "busybox:1.36",
                        "command": ["sh", "-c", "sleep 600"],
                        "volumeMounts": [{"name": "data", "mountPath": "/data"}],
                    }],
                    "volumes": [{
                        "name": "data",
                        "persistentVolumeClaim": {"claimName": "grafana-fault-pvc"},
                    }],
                },
            }
            r3 = kubectl_apply(pod, namespace="monitoring")
            return {
                "action": "pv_bad_node_affinity", "pod": "grafana-storage-probe",
                "kubectl_output": r1 + r2 + r3,
            }

        manifest = pvc_manifests.get(trial)
        if manifest:
            ns = manifest["metadata"].get("namespace", NAMESPACE)
            result = kubectl_apply(manifest, namespace=ns)
            return {"action": "create_pvc", "pvc": manifest["metadata"]["name"], "kubectl_output": result}

        return {"action": "unknown_trial", "error": f"No F5 implementation for trial {trial}"}

    # ── F6: NetworkPolicy ──────────────────────────────────────────

    def _inject_f6_network_policy(self, target: str, trial: int, gt: dict) -> dict:
        """Apply NetworkPolicy to block traffic."""
        policies = {
            1: {  # deny-all ingress
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {"name": "fault-deny-all", "namespace": NAMESPACE},
                "spec": {
                    "podSelector": {},
                    "policyTypes": ["Ingress"],
                },
            },
            2: {  # block frontend→cartservice:7070
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {"name": "fault-block-cart", "namespace": NAMESPACE},
                "spec": {
                    "podSelector": {"matchLabels": {"app": "cartservice"}},
                    "policyTypes": ["Ingress"],
                    "ingress": [{
                        "from": [{"podSelector": {"matchLabels": {"app": "NOT-frontend"}}}],
                        "ports": [{"port": 7070, "protocol": "TCP"}],
                    }],
                },
            },
            3: {  # block checkoutservice egress to paymentservice
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {"name": "fault-block-payment", "namespace": NAMESPACE},
                "spec": {
                    "podSelector": {"matchLabels": {"app": "checkoutservice"}},
                    "policyTypes": ["Egress"],
                    "egress": [{
                        "to": [{"podSelector": {"matchLabels": {"app": "NOT-paymentservice"}}}],
                    }],
                },
            },
            4: {  # block DNS egress from productcatalogservice
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {"name": "fault-block-dns", "namespace": NAMESPACE},
                "spec": {
                    "podSelector": {"matchLabels": {"app": "productcatalogservice"}},
                    "policyTypes": ["Egress"],
                    "egress": [{
                        "ports": [{"port": 443, "protocol": "TCP"}],
                    }],
                    # Only allow 443, blocking DNS (53)
                },
            },
            5: {  # block cartservice→redis:6379
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {"name": "fault-block-redis", "namespace": NAMESPACE},
                "spec": {
                    "podSelector": {"matchLabels": {"app": "redis-cart"}},
                    "policyTypes": ["Ingress"],
                    "ingress": [{
                        "from": [{"podSelector": {"matchLabels": {"app": "NOT-cartservice"}}}],
                        "ports": [{"port": 6379, "protocol": "TCP"}],
                    }],
                },
            },
        }

        policy = policies.get(trial)
        if policy:
            result = kubectl_apply(policy)
            return {
                "action": "apply_network_policy",
                "policy_name": policy["metadata"]["name"],
                "kubectl_output": result,
            }
        return {"action": "unknown_trial"}

    # ── F7: CPUThrottle ────────────────────────────────────────────

    def _inject_f7_cpu_throttle(
        self,
        target: str,
        trial: int,
        gt: dict,
        recovery_context: Optional[dict] = None,
    ) -> dict:
        """Set very low CPU limit."""
        cpu_limits = {
            1: "10m",   # frontend
            2: "5m",    # checkoutservice
            3: "5m",    # productcatalogservice
            4: "5m",    # adservice (Java)
            5: "5m",    # currencyservice
        }
        limit = cpu_limits.get(trial, "10m")

        recovery_context = recovery_context or self.prepare_recovery_context("F7", trial)
        if (
            recovery_context.get("fault_id") != "F7"
            or recovery_context.get("trial") != trial
            or recovery_context.get("target_service") != target
            or not recovery_context.get("container_name")
            or not recovery_context.get("original_cpu_limit")
            or not recovery_context.get("original_cpu_request")
        ):
            raise RuntimeError("F7 recovery context identity is invalid")

        result = kubectl(
            "set", "resources", "deployment", target,
            f"--containers={recovery_context['container_name']}",
            f"--limits=cpu={limit}", f"--requests=cpu={limit}",
        )
        logger.info("F7 injected: %s CPU limit → %s", target, limit)

        return {
            **recovery_context,
            "action": "patch_cpu_limit",
            "cpu_limit": limit,
            "kubectl_output": result,
        }

    # ── F8: ServiceEndpoint ────────────────────────────────────────

    def _inject_f8_service_endpoint(self, target: str, trial: int, gt: dict) -> dict:
        """Misconfigure service selector/port."""
        if trial == 1:
            # Change selector to non-matching label
            patch = {"spec": {"selector": {"app": "frontend-v2"}}}
            result = kubectl_patch("service", "frontend", patch, patch_type="merge")
            return {"action": "change_selector", "new_selector": "frontend-v2", "kubectl_output": result}

        elif trial == 2:
            # Change targetPort to wrong port
            patch = {"spec": {"ports": [{"port": 7070, "targetPort": 9999, "protocol": "TCP", "name": "grpc"}]}}
            result = kubectl_patch("service", "cartservice", patch, patch_type="merge")
            return {"action": "change_target_port", "new_port": 9999, "kubectl_output": result}

        elif trial == 3:
            # Remove app label from pods
            patch = {"spec": {"template": {"metadata": {"labels": {"app": None}}}}}
            # Use JSON merge patch to remove label
            result = kubectl_patch(
                "deployment", "paymentservice",
                {"spec": {"template": {"metadata": {"labels": {"app-disabled": "paymentservice"}}}}},
            )
            # Also directly relabel to break selector
            kubectl(
                "label", "pods", "-l", "app=paymentservice",
                "app-", namespace=NAMESPACE,
            )
            return {"action": "remove_pod_label", "kubectl_output": result}

        elif trial == 4:
            # Add always-failing readiness probe
            image = get_container_image(target, "server")
            patch = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [{
                                "name": "server",
                                "image": image,
                                "readinessProbe": {
                                    "httpGet": {"path": "/nonexistent", "port": 9999},
                                    "initialDelaySeconds": 1,
                                    "periodSeconds": 5,
                                    "failureThreshold": 1,
                                },
                            }],
                        },
                    },
                },
            }
            result = kubectl_patch("deployment", target, patch)
            return {"action": "add_failing_readiness", "kubectl_output": result}

        elif trial == 5:
            # Change service port
            patch = {"spec": {"ports": [{"port": 9999, "targetPort": 8080, "protocol": "TCP", "name": "grpc"}]}}
            result = kubectl_patch("service", "emailservice", patch, patch_type="merge")
            return {"action": "change_service_port", "kubectl_output": result}

        return {"action": "unknown_trial"}

    # ── F9: SecretConfigMap ────────────────────────────────────────

    def _inject_f9_secret_configmap(self, target: str, trial: int, gt: dict) -> dict:
        """Mess with Secrets/ConfigMaps."""
        image = get_container_image(target)

        if trial == 1:
            # Set env var pointing to non-existent secret
            patch = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [{
                                "name": target,
                                "image": image,
                                "env": [{
                                    "name": "REDIS_ADDR",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "redis-cart-secret-nonexistent",
                                            "key": "addr",
                                        },
                                    },
                                }],
                            }],
                        },
                    },
                },
            }
            result = kubectl_patch("deployment", target, patch)
            return {"action": "ref_nonexistent_secret", "kubectl_output": result}

        elif trial == 2:
            # Set wrong port via env var
            patch = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [{
                                "name": target,
                                "image": image,
                                "env": [{
                                    "name": "PRODUCT_CATALOG_SERVICE_ADDR",
                                    "value": "productcatalogservice:9999",
                                }, {
                                    "name": "CURRENCY_SERVICE_ADDR",
                                    "value": "currencyservice:9999",
                                }],
                            }],
                        },
                    },
                },
            }
            result = kubectl_patch("deployment", target, patch)
            return {"action": "wrong_env_port", "kubectl_output": result}

        elif trial == 3:
            # Mount non-existent ConfigMap as volume
            patch = {
                "spec": {
                    "template": {
                        "spec": {
                            "volumes": [{
                                "name": "config-vol",
                                "configMap": {"name": "paymentservice-config-nonexistent"},
                            }],
                            "containers": [{
                                "name": target,
                                "image": image,
                                "volumeMounts": [{
                                    "name": "config-vol",
                                    "mountPath": "/etc/payment-config",
                                }],
                            }],
                        },
                    },
                },
            }
            result = kubectl_patch("deployment", target, patch)
            return {"action": "mount_nonexistent_configmap", "kubectl_output": result}

        elif trial == 4:
            # Wrong secret key name
            patch = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [{
                                "name": target,
                                "image": image,
                                "env": [{
                                    "name": "CHECKOUT_WRONG_KEY",
                                    "valueFrom": {
                                        "secretKeyRef": {
                                            "name": "checkout-secret-bad",
                                            "key": "API_KEY",
                                        },
                                    },
                                }],
                            }],
                        },
                    },
                },
            }
            # Create a dummy secret first
            secret = {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": "checkout-secret-bad", "namespace": NAMESPACE},
                "type": "Opaque",
                "stringData": {"WRONG_KEY": "dummy"},
            }
            kubectl_apply(secret)
            result = kubectl_patch("deployment", target, patch)
            return {"action": "wrong_secret_key", "kubectl_output": result}

        elif trial == 5:
            # Env var with bad value
            patch = {
                "spec": {
                    "template": {
                        "spec": {
                            "containers": [{
                                "name": target,
                                "image": image,
                                "env": [{
                                    "name": "DISABLE_TRACING",
                                    "value": "corrupt_value_\x00\x01",
                                }],
                            }],
                        },
                    },
                },
            }
            result = kubectl_patch("deployment", target, patch)
            return {"action": "corrupted_env", "kubectl_output": result}

        return {"action": "unknown_trial"}

    # ── F10: ResourceQuota ─────────────────────────────────────────

    def _inject_f10_resource_quota(self, target: str, trial: int, gt: dict) -> dict:
        """Apply restrictive ResourceQuota/LimitRange."""
        quotas = {
            1: {
                "apiVersion": "v1",
                "kind": "ResourceQuota",
                "metadata": {"name": "fault-quota", "namespace": NAMESPACE},
                "spec": {"hard": {"pods": "5"}},
            },
            2: {
                "apiVersion": "v1",
                "kind": "ResourceQuota",
                "metadata": {"name": "fault-quota-cpu", "namespace": NAMESPACE},
                "spec": {"hard": {"requests.cpu": "100m"}},
            },
            3: {
                "apiVersion": "v1",
                "kind": "ResourceQuota",
                "metadata": {"name": "fault-quota-mem", "namespace": NAMESPACE},
                "spec": {"hard": {"requests.memory": "128Mi"}},
            },
            4: {
                "apiVersion": "v1",
                "kind": "ResourceQuota",
                "metadata": {"name": "fault-quota-svc", "namespace": NAMESPACE},
                "spec": {"hard": {"services": "3"}},
            },
            5: {
                "apiVersion": "v1",
                "kind": "LimitRange",
                "metadata": {"name": "fault-limitrange", "namespace": NAMESPACE},
                "spec": {
                    "limits": [{
                        "type": "Container",
                        "max": {"memory": "32Mi"},
                        "default": {"memory": "32Mi"},
                        "defaultRequest": {"memory": "32Mi"},
                    }],
                },
            },
        }

        manifest = quotas.get(trial)
        if manifest:
            result = kubectl_apply(manifest)
            # For quota to take effect on existing pods, we need to trigger a rollout
            if trial in (1, 2, 3):
                # Delete a few pods to trigger quota enforcement
                time.sleep(5)
                kubectl("delete", "pod", "-l", "app=frontend", "--grace-period=0", namespace=NAMESPACE)
            elif trial == 4:
                probe_service = {
                    "apiVersion": "v1", "kind": "Service",
                    "metadata": {"name": "quota-probe-service", "namespace": NAMESPACE},
                    "spec": {"selector": {"app": "frontend"}, "ports": [{"port": 80, "targetPort": 8080}]},
                }
                try:
                    kubectl_apply(probe_service)
                except RuntimeError:
                    # Admission rejection is the intended treatment signal.
                    pass
            elif trial == 5:
                kubectl("delete", "pod", "-l", "app=frontend", "--grace-period=0", namespace=NAMESPACE)
            return {
                "action": "apply_quota",
                "resource": manifest["kind"],
                "kubectl_output": result,
            }
        return {"action": "unknown_trial"}

    # ── F11: Network Delay ─────────────────────────────────────────

    # 재구축 직접 K8s 랩의 노드망 인터페이스. 옛 nested 환경의 ens18은 존재하지 않으며,
    # 새 호스트에서 K8s 노드망(172.25.100.0/24)은 vmbr0에 바인딩된다(docs/lab-environment.md).
    # 관리 SSH는 ens7(172.25.20.x)로 들어오므로 vmbr0 netem이 주입용 SSH 세션을 끊지 않는다.
    NETEM_IFACE = "vmbr0"

    def _inject_f11_network_delay(self, target: str, trial: int, gt: dict) -> dict:
        """Inject network delay via tc netem on worker node."""
        delay_configs = {
            1: ("yms-proxmox-02", "delay 500ms"),
            2: ("yms-proxmox-03", "delay 1000ms 200ms"),
            3: ("yms-proxmox-02", "delay 2000ms"),
            4: ("yms-proxmox-04", "delay 300ms 100ms distribution normal"),
            5: ("yms-proxmox-03", "delay 5000ms"),
        }
        node_name, netem_params = delay_configs.get(trial, ("yms-proxmox-02", "delay 500ms"))
        iface = self.NETEM_IFACE

        # Apply netem with safety timeout (auto-remove after 5 minutes).
        # 백그라운드 서브셸의 stdin/stdout/stderr를 /dev/null로 끊어야 SSH가 즉시 반환된다
        # (안 끊으면 ssh가 채널 EOF를 기다리며 hang → 과거 F11/F12 전량 15초 타임아웃의 원인).
        command = (
            f"sudo tc qdisc replace dev {iface} root netem {netem_params}; "
            f"(sleep 300 && sudo tc qdisc del dev {iface} root) >/dev/null 2>&1 </dev/null &"
        )
        output = ssh_node(node_name, command, timeout=15)
        logger.info("F11 injected: netem %s on %s (%s)", netem_params, node_name, iface)

        return {
            "action": "netem_delay",
            "node": node_name,
            "netem_params": netem_params,
            "interface": iface,
            "ssh_output": output,
        }

    # ── F12: Network Loss ──────────────────────────────────────────

    def _inject_f12_network_loss(self, target: str, trial: int, gt: dict) -> dict:
        """Inject packet loss via tc netem on worker node."""
        loss_configs = {
            1: ("yms-proxmox-02", "loss 10%"),
            2: ("yms-proxmox-03", "loss 30%"),
            3: ("yms-proxmox-04", "loss 50%"),
            4: ("yms-proxmox-02", "loss 5% 25%"),
            5: ("yms-proxmox-03", "loss 80%"),
        }
        node_name, netem_params = loss_configs.get(trial, ("yms-proxmox-02", "loss 10%"))
        iface = self.NETEM_IFACE

        # F11과 동일: vmbr0 대상 + 백그라운드 fd 차단으로 SSH 즉시 반환.
        command = (
            f"sudo tc qdisc replace dev {iface} root netem {netem_params}; "
            f"(sleep 300 && sudo tc qdisc del dev {iface} root) >/dev/null 2>&1 </dev/null &"
        )
        output = ssh_node(node_name, command, timeout=15)
        logger.info("F12 injected: netem %s on %s (%s)", netem_params, node_name, iface)

        return {
            "action": "netem_loss",
            "node": node_name,
            "netem_params": netem_params,
            "interface": iface,
            "ssh_output": output,
        }
