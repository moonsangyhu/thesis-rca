"""Fail-closed live-state validation for every V2.3 injected fault."""

from __future__ import annotations

from collections.abc import Callable
import subprocess

from .live_runner import F7InjectionValidator, PilotError
from scripts.fault_inject.config import (
    F4_T3_STRESS_BYTES,
    F4_T3_STRESS_TIMEOUT_SECONDS,
    INJECTION_WAIT,
)


EXPECTED_ACTIONS = {
    "F1": "patch_memory_limit",
    "F2": "override_command",
    "F3": "change_image",
    "F4": "node_disruption",
    "F5": {1: "create_pvc", 2: "create_pvc", 3: "scale_provisioner_to_zero",
           4: "create_pvc", 5: "pv_bad_node_affinity"},
    "F6": "apply_network_policy",
    "F7": "patch_cpu_limit",
    "F8": {1: "change_selector", 2: "change_target_port", 3: "remove_pod_label",
           4: "add_failing_readiness", 5: "change_service_port"},
    "F9": {1: "ref_nonexistent_secret", 2: "wrong_env_port",
           3: "mount_nonexistent_configmap", 4: "wrong_secret_key",
           5: "corrupted_env"},
    "F10": "apply_quota",
    "F11": "netem_delay",
    "F12": "netem_loss",
}


class LiveInjectionValidator:
    """Bind an injector receipt to an independently observed cluster state."""

    def __init__(
        self,
        kubectl_loader: Callable[[str, str, str], dict],
        ssh_probe: Callable[[str, str], str],
    ) -> None:
        self.load = kubectl_loader
        self.ssh_probe = ssh_probe
        self.f7 = F7InjectionValidator(
            lambda target: self.load("deployment", target, "boutique"),
            lambda: self.load("pods", "", "boutique"),
        )

    @staticmethod
    def _containers(deployment: dict) -> list[dict]:
        return (
            deployment.get("spec", {}).get("template", {}).get("spec", {})
            .get("containers", [])
        )

    @staticmethod
    def _find_container(deployment: dict, target: str) -> dict:
        containers = LiveInjectionValidator._containers(deployment)
        matched = next((item for item in containers if item.get("name") == target), None)
        if matched is None and len(containers) == 1:
            matched = containers[0]
        if not isinstance(matched, dict):
            raise PilotError("post-injection target container is missing")
        return matched

    def _identity(self, fault_id: str, trial: int, ground_truth: dict, result: dict) -> str:
        target = str(ground_truth.get("target_service") or "")
        try:
            result_trial = int(result.get("trial"))
        except (TypeError, ValueError) as exc:
            raise PilotError("post-injection trial identity mismatch") from exc
        expected = EXPECTED_ACTIONS[fault_id]
        if isinstance(expected, dict):
            expected = expected[trial]
        if (
            result.get("fault_id") != fault_id
            or result_trial != trial
            or result.get("target_service") != target
            or result.get("action") != expected
        ):
            raise PilotError("post-injection receipt identity mismatch")
        return target

    def validate(
        self, fault_id: str, trial: int, ground_truth: dict, result: dict
    ) -> dict:
        if fault_id not in EXPECTED_ACTIONS or trial not in range(1, 6):
            raise PilotError("post-injection identity is outside V2.3 scope")
        target = self._identity(fault_id, trial, ground_truth, result)
        method = getattr(self, f"_validate_{fault_id.lower()}")
        details = method(trial, target, result)
        return {"status": "verified", "target_service": target, **details}

    def _validate_f1(self, trial: int, target: str, result: dict) -> dict:
        requested = result.get("memory_limit")
        container = self._find_container(
            self.load("deployment", target, "boutique"), target
        )
        resources = container.get("resources", {})
        if not requested or resources.get("limits", {}).get("memory") != requested \
                or resources.get("requests", {}).get("memory") != requested:
            raise PilotError("F1 memory treatment is absent")
        return {"memory_limit": requested}

    def _validate_f2(self, trial: int, target: str, result: dict) -> dict:
        container = self._find_container(
            self.load("deployment", target, "boutique"), target
        )
        if container.get("command") != result.get("command"):
            raise PilotError("F2 crash command treatment is absent")
        return {"command_bound": True}

    def _validate_f3(self, trial: int, target: str, result: dict) -> dict:
        container = self._find_container(
            self.load("deployment", target, "boutique"), target
        )
        if not result.get("image") or container.get("image") != result["image"]:
            raise PilotError("F3 image treatment is absent")
        return {"image_bound": True}

    def _validate_f4(self, trial: int, target: str, result: dict) -> dict:
        node = result.get("node")
        if trial == 3:
            pid = result.get("stress_ng_pid")
            start_ticks = result.get("stress_ng_start_ticks")
            cmdline_hash = result.get("stress_ng_cmdline_sha256")
            if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
                raise PilotError("F4 memory stress launch receipt is invalid")
            if (
                not isinstance(start_ticks, int) or isinstance(start_ticks, bool)
                or start_ticks <= 0
                or not isinstance(cmdline_hash, str) or len(cmdline_hash) != 64
                or any(c not in "0123456789abcdef" for c in cmdline_hash)
            ):
                raise PilotError("F4 memory stress process receipt is invalid")
            if (
                result.get("stress_memory_bytes") != F4_T3_STRESS_BYTES
                or result.get("stress_timeout_seconds") != F4_T3_STRESS_TIMEOUT_SECONDS
                or F4_T3_STRESS_TIMEOUT_SECONDS <= INJECTION_WAIT["F4"]
            ):
                raise PilotError("F4 memory stress amount is invalid")
        observed = self.load("node", str(node), "")
        conditions = {
            item.get("type"): item.get("status")
            for item in observed.get("status", {}).get("conditions", [])
        }
        disrupted = conditions.get("Ready") != "True"
        if trial == 3:
            disrupted = disrupted or conditions.get("MemoryPressure") == "True"
        if trial == 4:
            disrupted = disrupted or conditions.get("DiskPressure") == "True"
        if trial == 1:
            disrupted = disrupted or observed.get("spec", {}).get("unschedulable") is True
        if not node or not disrupted:
            raise PilotError("F4 node disruption was not observed")
        details = {"node": node, "node_disrupted": True}
        if trial == 3:
            command = (
                f"pid={pid}; test -r /proc/$pid/stat; "
                f"test \"$(awk '{{print $22}}' /proc/$pid/stat)\" = \"{start_ticks}\"; "
                f"test \"$(sha256sum /proc/$pid/cmdline | awk '{{print $1}}')\" "
                f"= \"{cmdline_hash}\"; echo __V23_STRESS_NG_IDENTITY__=live"
            )
            try:
                probe = self.ssh_probe(str(node), command)
            except (TimeoutError, subprocess.TimeoutExpired):
                probe = "connection timed out"
            if "__V23_STRESS_NG_IDENTITY__=live" in probe:
                details["stress_process_probe"] = "live"
            elif conditions.get("Ready") != "True" and any(
                marker in probe.lower() for marker in (
                    "timed out", "timeout", "no route to host", "connection refused"
                )
            ):
                details["stress_process_probe"] = "node_unreachable"
            else:
                raise PilotError("F4 memory stress process identity was not observed")
        return details

    def _validate_f5(self, trial: int, target: str, result: dict) -> dict:
        if trial == 3:
            deployment = self.load("deployment", "local-path-provisioner", "local-path-storage")
            if deployment.get("spec", {}).get("replicas") != 0:
                raise PilotError("F5 provisioner treatment is absent")
            pvc = self.load("pvc", "storage-probe-pvc", "boutique")
            if pvc.get("status", {}).get("phase") == "Bound":
                raise PilotError("F5 provisioner probe PVC unexpectedly bound")
            return {
                "provisioner_replicas": 0,
                "pvc": "storage-probe-pvc",
                "pvc_phase": pvc.get("status", {}).get("phase", ""),
            }
        if trial == 5:
            pv = self.load("pv", "grafana-fault-pv", "")
            values = (
                pv.get("spec", {}).get("nodeAffinity", {}).get("required", {})
                .get("nodeSelectorTerms", [{}])[0].get("matchExpressions", [{}])[0]
                .get("values", [])
            )
            if "nonexistent-node" not in values:
                raise PilotError("F5 bad-affinity PV treatment is absent")
            self.load("pvc", "grafana-fault-pvc", "monitoring")
            pod = self.load("pod", "grafana-storage-probe", "monitoring")
            if pod.get("status", {}).get("phase") != "Pending":
                raise PilotError("F5 bad-affinity probe pod is not Pending")
            return {"bad_node_affinity": True, "probe_pod_phase": "Pending"}
        name, namespace = {
            1: ("redis-cart-fault", "boutique"),
            2: ("prometheus-fault", "monitoring"),
            4: ("redis-cart-rwx", "boutique"),
        }[trial]
        pvc = self.load("pvc", name, namespace)
        if pvc.get("status", {}).get("phase") == "Bound":
            raise PilotError("F5 PVC unexpectedly bound")
        return {"pvc": name, "pvc_phase": pvc.get("status", {}).get("phase", "")}

    def _validate_f6(self, trial: int, target: str, result: dict) -> dict:
        name = result.get("policy_name")
        policy = self.load("networkpolicy", str(name), "boutique")
        if policy.get("metadata", {}).get("name") != name:
            raise PilotError("F6 NetworkPolicy treatment is absent")
        return {"network_policy": name}

    def _validate_f7(self, trial: int, target: str, result: dict) -> dict:
        details = self.f7.validate("F7", trial, {
            "target_service": target
        }, result)
        return {key: value for key, value in details.items() if key != "status"}

    def _validate_f8(self, trial: int, target: str, result: dict) -> dict:
        if trial in {1, 2, 5}:
            service = self.load("service", target, "boutique")
            spec = service.get("spec", {})
            valid = (
                trial == 1 and spec.get("selector", {}).get("app") == "frontend-v2"
            ) or (
                trial == 2 and any(str(p.get("targetPort")) == "9999" for p in spec.get("ports", []))
            ) or (
                trial == 5 and any(str(p.get("port")) == "9999" for p in spec.get("ports", []))
            )
        else:
            deployment = self.load("deployment", target, "boutique")
            if trial == 3:
                valid = (
                    deployment.get("spec", {}).get("template", {}).get("metadata", {})
                    .get("labels", {}).get("app-disabled") == "paymentservice"
                )
            else:
                probe = self._find_container(deployment, target).get("readinessProbe", {})
                valid = probe.get("httpGet", {}).get("path") == "/nonexistent"
        if not valid:
            raise PilotError("F8 endpoint treatment is absent")
        return {"endpoint_treatment": True}

    def _validate_f9(self, trial: int, target: str, result: dict) -> dict:
        deployment = self.load("deployment", target, "boutique")
        container = self._find_container(deployment, target)
        serialized = str(container)
        markers = {
            1: "redis-cart-secret-nonexistent", 2: ":9999",
            3: "paymentservice-config-nonexistent", 4: "checkout-secret-bad",
            5: "corrupt_value_",
        }
        if markers[trial] not in serialized:
            raise PilotError("F9 secret/config treatment is absent")
        return {"configuration_treatment": True}

    def _validate_f10(self, trial: int, target: str, result: dict) -> dict:
        kind = "limitrange" if trial == 5 else "resourcequota"
        name = "fault-limitrange" if trial == 5 else {
            1: "fault-quota", 2: "fault-quota-cpu", 3: "fault-quota-mem", 4: "fault-quota-svc"
        }[trial]
        resource = self.load(kind, name, "boutique")
        if resource.get("metadata", {}).get("name") != name:
            raise PilotError("F10 quota treatment is absent")
        return {"resource_kind": kind, "resource_name": name}

    def _validate_netem(self, expected: str, result: dict) -> dict:
        node = str(result.get("node") or "")
        interface = str(result.get("interface") or "")
        output = self.ssh_probe(node, f"sudo tc qdisc show dev {interface}")
        if "netem" not in output or expected not in output:
            raise PilotError(f"network {expected} treatment is absent")
        return {"node": node, "interface": interface, "netem": expected}

    def _validate_f11(self, trial: int, target: str, result: dict) -> dict:
        return self._validate_netem("delay", result)

    def _validate_f12(self, trial: int, target: str, result: dict) -> dict:
        return self._validate_netem("loss", result)
