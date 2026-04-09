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
from .config import NAMESPACE, INJECTION_WAIT

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

    def inject(self, fault_id: str, trial: int) -> dict:
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

        result = injector(target, trial, gt)
        result["fault_id"] = fault_id
        result["trial"] = trial
        result["target_service"] = target
        result["wait_seconds"] = INJECTION_WAIT.get(fault_id, 120)
        return result

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

    def _inject_f4_node_notready(self, target: str, trial: int, gt: dict) -> dict:
        """Make a worker node NotReady via SSH."""
        node_actions = {
            1: ("worker01", "sudo systemctl stop kubelet"),
            2: ("worker02", "sudo iptables -A OUTPUT -p tcp --dport 6443 -j DROP"),
            3: ("worker03", "sudo stress-ng --vm 2 --vm-bytes 90% --timeout 300s &"),
            4: ("worker01", "sudo fallocate -l $(($(df --output=avail / | tail -1) * 95 / 100))k /tmp/diskfill"),
            5: ("worker02", "sudo systemctl stop containerd"),
        }
        node_name, command = node_actions.get(trial, ("worker01", "sudo systemctl stop kubelet"))

        # Cordon node first for trial 1
        if trial == 1:
            kubectl("cordon", node_name, namespace="")

        output = ssh_node(node_name, command)
        logger.info("F4 injected: %s on %s", command, node_name)

        return {
            "action": "node_disruption",
            "node": node_name,
            "command": command,
            "ssh_output": output,
        }

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
                    "storageClassName": "local-path",
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
            return {"action": "scale_provisioner_to_zero", "kubectl_output": result}

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
            return {"action": "pv_bad_node_affinity", "kubectl_output": r1 + r2}

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

    def _inject_f7_cpu_throttle(self, target: str, trial: int, gt: dict) -> dict:
        """Set very low CPU limit."""
        cpu_limits = {
            1: "10m",   # frontend
            2: "5m",    # checkoutservice
            3: "5m",    # productcatalogservice
            4: "5m",    # adservice (Java)
            5: "5m",    # currencyservice
        }
        limit = cpu_limits.get(trial, "10m")

        result = kubectl(
            "set", "resources", "deployment", target,
            f"--limits=cpu={limit}", f"--requests=cpu={limit}",
        )
        logger.info("F7 injected: %s CPU limit → %s", target, limit)

        return {"action": "patch_cpu_limit", "cpu_limit": limit, "kubectl_output": result}

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
            return {
                "action": "apply_quota",
                "resource": manifest["kind"],
                "kubectl_output": result,
            }
        return {"action": "unknown_trial"}

    # ── F11: Network Delay ─────────────────────────────────────────

    NETEM_IFACE = "ens18"

    def _inject_f11_network_delay(self, target: str, trial: int, gt: dict) -> dict:
        """Inject network delay via tc netem on worker node."""
        delay_configs = {
            1: ("worker01", "delay 500ms"),
            2: ("worker02", "delay 1000ms 200ms"),
            3: ("worker01", "delay 2000ms"),
            4: ("worker03", "delay 300ms 100ms distribution normal"),
            5: ("worker02", "delay 5000ms"),
        }
        node_name, netem_params = delay_configs.get(trial, ("worker01", "delay 500ms"))
        iface = self.NETEM_IFACE

        # Apply netem with safety timeout (auto-remove after 5 minutes)
        command = (
            f"sudo tc qdisc add dev {iface} root netem {netem_params} 2>/dev/null || "
            f"sudo tc qdisc change dev {iface} root netem {netem_params}; "
            f"(sleep 300 && sudo tc qdisc del dev {iface} root 2>/dev/null) &"
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
            1: ("worker01", "loss 10%"),
            2: ("worker02", "loss 30%"),
            3: ("worker03", "loss 50%"),
            4: ("worker01", "loss 5% 25%"),
            5: ("worker02", "loss 80%"),
        }
        node_name, netem_params = loss_configs.get(trial, ("worker01", "loss 10%"))
        iface = self.NETEM_IFACE

        command = (
            f"sudo tc qdisc add dev {iface} root netem {netem_params} 2>/dev/null || "
            f"sudo tc qdisc change dev {iface} root netem {netem_params}; "
            f"(sleep 300 && sudo tc qdisc del dev {iface} root 2>/dev/null) &"
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
