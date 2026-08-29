"""Fail-closed live-state validation for every V2.3 injected fault."""

from __future__ import annotations

from collections.abc import Callable
import shlex
import subprocess

from .live_runner import (
    F4DisruptionNotObserved,
    F4ObservationTimeout,
    F7InjectionValidator,
    PilotError,
)
from scripts.fault_inject.config import (
    F4_T3_MEM_AVAILABLE_MAX_BYTES,
    F4_T3_STRESS_BYTES,
    F4_T3_OBSERVATION_WAIT_SECONDS,
    F4_T3_NODE_NAME,
    F4_T3_STRESS_TIMEOUT_SECONDS,
    F4_T3_STRESS_VM_WORKERS,
    F4_T4_ACCOUNTING_TOLERANCE_BYTES,
    F4_T4_NODEFS_PATH,
    F4_T4_NODE_NAME,
    F4_T4_SAFETY_FLOOR_PERCENT,
    F4_T4_TARGET_AVAILABLE_PERCENT,
    F4_T4_WORK_PREFIX,
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

    @staticmethod
    def _receipt_container(result: dict, target: str) -> str:
        """Bind validation to the exact container mutated by the injector."""
        name = result.get("container_name")
        if isinstance(name, str) and name:
            return name
        # Legacy unit fixtures predate durable container identity receipts.
        return target

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
            self.load("deployment", target, "boutique"),
            self._receipt_container(result, target),
        )
        if container.get("command") != result.get("command"):
            raise PilotError("F2 crash command treatment is absent")
        return {"command_bound": True}

    def _validate_f3(self, trial: int, target: str, result: dict) -> dict:
        container = self._find_container(
            self.load("deployment", target, "boutique"),
            self._receipt_container(result, target),
        )
        if not result.get("image") or container.get("image") != result["image"]:
            raise PilotError("F3 image treatment is absent")
        return {"image_bound": True}

    def _validate_f4(self, trial: int, target: str, result: dict) -> dict:
        node = result.get("node")
        if trial == 3:
            if node != F4_T3_NODE_NAME:
                raise PilotError("F4 memory stress node identity is invalid")
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
                or isinstance(result.get("stress_vm_workers"), bool)
                or not isinstance(result.get("stress_vm_workers"), int)
                or result.get("stress_vm_workers") != F4_T3_STRESS_VM_WORKERS
                or isinstance(result.get("stress_timeout_seconds"), bool)
                or not isinstance(result.get("stress_timeout_seconds"), int)
                or result.get("stress_timeout_seconds") != F4_T3_STRESS_TIMEOUT_SECONDS
                or isinstance(result.get("wait_seconds"), bool)
                or not isinstance(result.get("wait_seconds"), int)
                or result.get("wait_seconds") != F4_T3_OBSERVATION_WAIT_SECONDS
                or F4_T3_STRESS_TIMEOUT_SECONDS
                <= F4_T3_OBSERVATION_WAIT_SECONDS
            ):
                raise PilotError("F4 memory stress amount is invalid")
        if trial == 4:
            if node != F4_T4_NODE_NAME:
                raise PilotError("F4 diskfill node identity is invalid")
            nonce = result.get("diskfill_nonce")
            if (
                not isinstance(nonce, str) or len(nonce) != 32
                or any(c not in "0123456789abcdef" for c in nonce)
            ):
                raise PilotError("F4 diskfill nonce is invalid")
            work_dir = f"{F4_T4_WORK_PREFIX}{nonce}"
            exact_strings = {
                "diskfill_file": f"{work_dir}/diskfill",
                "diskfill_receipt_file": f"{work_dir}/receipt",
                "diskfill_work_dir": work_dir,
                "nodefs_path": F4_T4_NODEFS_PATH,
            }
            if any(result.get(name) != value for name, value in exact_strings.items()):
                raise PilotError("F4 diskfill path receipt is invalid")
            if (
                not isinstance(result.get("node_uid_before"), str)
                or not result["node_uid_before"]
                or result.get("node_ready_before") != "True"
                or result.get("node_disk_pressure_before") != "False"
            ):
                raise PilotError("F4 diskfill node baseline receipt is invalid")
            numeric_names = (
                "nodefs_device", "diskfill_work_inode",
                "nodefs_capacity_bytes", "nodefs_pre_available_bytes",
                "nodefs_injection_available_bytes",
                "diskfill_allocated_bytes", "diskfill_inode",
                "diskfill_size_bytes", "diskfill_allocated_blocks",
                "nodefs_post_available_bytes",
            )
            if any(
                isinstance(result.get(name), bool)
                or not isinstance(result.get(name), int)
                or result[name] <= 0
                for name in numeric_names
            ) or (
                result.get("nodefs_target_available_percent")
                != F4_T4_TARGET_AVAILABLE_PERCENT
                or result.get("diskfill_preexisting") is not False
                or isinstance(result.get("wait_seconds"), bool)
                or not isinstance(result.get("wait_seconds"), int)
                or result["wait_seconds"] != INJECTION_WAIT["F4"]
                or result["nodefs_pre_available_bytes"]
                >= result["nodefs_capacity_bytes"]
                or result["nodefs_pre_available_bytes"] * 100
                < result["nodefs_capacity_bytes"] * 10
                or result["diskfill_size_bytes"]
                != result["diskfill_allocated_bytes"]
                or result["diskfill_allocated_bytes"]
                != result["nodefs_injection_available_bytes"]
                - (
                    result["nodefs_capacity_bytes"]
                    * F4_T4_TARGET_AVAILABLE_PERCENT // 100
                )
                or result["diskfill_allocated_blocks"] * 512
                < result["diskfill_size_bytes"]
                or (
                    result["nodefs_injection_available_bytes"]
                    - result["nodefs_post_available_bytes"]
                    < result["diskfill_allocated_bytes"]
                )
                or (
                    result["nodefs_injection_available_bytes"]
                    - result["nodefs_post_available_bytes"]
                    > result["diskfill_allocated_bytes"]
                    + F4_T4_ACCOUNTING_TOLERANCE_BYTES
                )
                or result["nodefs_post_available_bytes"] * 100
                >= result["nodefs_capacity_bytes"] * 10
                or result["nodefs_post_available_bytes"] * 100
                < result["nodefs_capacity_bytes"]
                * F4_T4_SAFETY_FLOOR_PERCENT
            ):
                raise PilotError("F4 diskfill numeric receipt is invalid")
        try:
            observed = self.load("node", str(node), "")
        except (TimeoutError, subprocess.TimeoutExpired) as exc:
            if trial == 3:
                raise F4ObservationTimeout(
                    "F4 node observation timed out"
                ) from exc
            raise PilotError("F4 node observation timed out") from exc
        metadata = observed.get("metadata", {}) if isinstance(observed, dict) else {}
        raw_conditions = (
            observed.get("status", {}).get("conditions")
            if isinstance(observed, dict) else None
        )
        ready_items = (
            [item for item in raw_conditions
             if isinstance(item, dict) and item.get("type") == "Ready"]
            if isinstance(raw_conditions, list) else []
        )
        disk_items = (
            [item for item in raw_conditions
             if isinstance(item, dict) and item.get("type") == "DiskPressure"]
            if isinstance(raw_conditions, list) else []
        )
        if (
            not isinstance(observed, dict)
            or observed.get("kind") != "Node"
            or metadata.get("name") != node
            or not isinstance(metadata.get("uid"), str)
            or not metadata.get("uid")
            or (
                trial == 4
                and metadata.get("uid") != result.get("node_uid_before")
            )
            or not isinstance(raw_conditions, list)
            or len(ready_items) != 1
            or ready_items[0].get("status") not in {"True", "False", "Unknown"}
            or (
                trial == 4 and (
                    len(disk_items) != 1
                    or disk_items[0].get("status")
                    not in {"True", "False"}
                )
            )
        ):
            raise PilotError("F4 node observation schema is invalid")
        conditions = {
            item.get("type"): item.get("status")
            for item in raw_conditions if isinstance(item, dict)
        }
        disrupted = conditions.get("Ready") != "True"
        if trial == 4:
            disrupted = disrupted or conditions.get("DiskPressure") == "True"
        if trial == 1:
            disrupted = disrupted or observed.get("spec", {}).get("unschedulable") is True
        if not node:
            raise PilotError("F4 node disruption was not observed")
        details = {"node": node, "node_disrupted": disrupted}
        if trial == 3:
            command = (
                f"set -eu; pid={pid}; test -r /proc/$pid/stat; "
                f"test \"$(awk '{{print $22}}' /proc/$pid/stat)\" = \"{start_ticks}\"; "
                f"test \"$(sha256sum /proc/$pid/cmdline | awk '{{print $1}}')\" "
                f"= \"{cmdline_hash}\"; echo __V23_STRESS_NG_IDENTITY__=live; "
                "awk '/^MemAvailable:/{printf \"__V23_MEM_AVAILABLE_BYTES__=%.0f\\n\", "
                "$2 * 1024}' /proc/meminfo"
            )
            try:
                probe = self.ssh_probe(str(node), command)
            except (TimeoutError, subprocess.TimeoutExpired):
                probe = "connection timed out"
            if probe.splitlines().count("__V23_STRESS_NG_IDENTITY__=live") == 1:
                details["stress_process_probe"] = "live"
                details["stress_identity_verified"] = True
                values = [
                    line.removeprefix("__V23_MEM_AVAILABLE_BYTES__=")
                    for line in probe.splitlines()
                    if line.startswith("__V23_MEM_AVAILABLE_BYTES__=")
                ]
                if len(values) != 1 or not values[0].isdigit():
                    raise PilotError("F4 memory availability probe is malformed")
                mem_available = int(values[0])
                if mem_available < 0:
                    raise PilotError("F4 memory availability probe is malformed")
                details["mem_available_bytes"] = mem_available
                details["memory_pressure_verified"] = (
                    mem_available <= F4_T3_MEM_AVAILABLE_MAX_BYTES
                )
            elif conditions.get("Ready") != "True" and any(
                marker in probe.lower() for marker in (
                    "timed out", "timeout", "no route to host", "connection refused"
                )
            ):
                details["stress_process_probe"] = "node_unreachable"
                details["stress_identity_verified"] = False
                details["stress_identity_basis"] = (
                    "sealed-launch-plus-node-notready"
                )
                details["memory_pressure_verified"] = False
            else:
                if conditions.get("Ready") == "True" and any(
                    marker in probe.lower() for marker in (
                        "timed out", "timeout", "no route to host", "connection refused"
                    )
                ):
                    raise F4ObservationTimeout(
                        "F4 memory availability observation timed out"
                    )
                raise PilotError("F4 memory stress process identity was not observed")
            if not disrupted and not details.get("memory_pressure_verified"):
                raise F4DisruptionNotObserved(
                    "F4 memory pressure treatment was not observed"
                )
            details["treatment_verified"] = True
            details["treatment_basis"] = (
                "node-notready" if disrupted else "memavailable-threshold"
            )
        elif trial == 4:
            command = (
                "set -eu; "
                f"nonce={nonce}; nodefs={F4_T4_NODEFS_PATH}; work={work_dir}; "
                f"file={work_dir}/diskfill; receipt={work_dir}/receipt; "
                "read schema sealed_nonce device work_inode capacity pre_available target "
                "allocation file_inode file_size file_blocks post_available "
                "<\"$receipt\"; "
                "test \"$schema\" = post; "
                "test \"$sealed_nonce\" = \"$nonce\"; "
                f"test \"$device\" = {result['nodefs_device']}; "
                f"test \"$work_inode\" = {result['diskfill_work_inode']}; "
                f"test \"$capacity\" = {result['nodefs_capacity_bytes']}; "
                f"test \"$target\" = {F4_T4_TARGET_AVAILABLE_PERCENT}; "
                f"test \"$allocation\" = {result['diskfill_allocated_bytes']}; "
                f"test \"$file_inode\" = {result['diskfill_inode']}; "
                f"test \"$file_size\" = {result['diskfill_size_bytes']}; "
                f"test \"$file_blocks\" = {result['diskfill_allocated_blocks']}; "
                "test \"$(stat -c %d \"$nodefs\")\" = \"$device\"; "
                "test \"$(stat -c %d \"$work\")\" = \"$device\"; "
                "test \"$(stat -c %i \"$work\")\" = \"$work_inode\"; "
                "test \"$(stat -c %d \"$file\")\" = \"$device\"; "
                "test \"$(stat -c %i \"$file\")\" = \"$file_inode\"; "
                "test \"$(stat -c %s \"$file\")\" = \"$file_size\"; "
                "test \"$(stat -c %b \"$file\")\" = \"$file_blocks\"; "
                "set -- $(stat -f -c \"%S %b %a\" \"$nodefs\"); "
                "live_capacity=$(( $1 * $2 )); live_available=$(( $1 * $3 )); "
                "test \"$live_capacity\" = \"$capacity\"; "
                "printf \"__V23_DISK_LIVE_DEVICE__=%s\\n"
                "__V23_DISK_LIVE_WORK_INODE__=%s\\n"
                "__V23_DISK_LIVE_FILE_INODE__=%s\\n"
                "__V23_DISK_LIVE_FILE_SIZE__=%s\\n"
                "__V23_DISK_LIVE_FILE_BLOCKS__=%s\\n"
                "__V23_NODEFS_LIVE_CAPACITY__=%s\\n"
                "__V23_NODEFS_INJECTION_AVAILABLE__=%s\\n"
                "__V23_DISK_LIVE_ALLOCATION__=%s\\n"
                "__V23_NODEFS_POST_AVAILABLE__=%s\\n"
                "__V23_NODEFS_LIVE_AVAILABLE__=%s\\n\" "
                "\"$device\" \"$work_inode\" \"$file_inode\" "
                "\"$file_size\" \"$file_blocks\" \"$live_capacity\" "
                "\"$pre_available\" \"$allocation\" \"$post_available\" "
                "\"$live_available\""
            )
            # The nonce directory is deliberately root-owned mode 0700.  The
            # validator must cross that boundary without weakening the file
            # permissions that protect the crash-recovery receipt.
            command = "sudo sh -c " + shlex.quote(command)
            probe = self.ssh_probe(str(node), command)
            markers = {
                "nodefs_device": "__V23_DISK_LIVE_DEVICE__=",
                "diskfill_work_inode": "__V23_DISK_LIVE_WORK_INODE__=",
                "diskfill_inode": "__V23_DISK_LIVE_FILE_INODE__=",
                "diskfill_size_bytes": "__V23_DISK_LIVE_FILE_SIZE__=",
                "diskfill_allocated_blocks": "__V23_DISK_LIVE_FILE_BLOCKS__=",
                "nodefs_capacity_bytes": "__V23_NODEFS_LIVE_CAPACITY__=",
                "nodefs_injection_available_bytes": (
                    "__V23_NODEFS_INJECTION_AVAILABLE__="
                ),
                "diskfill_allocated_bytes": "__V23_DISK_LIVE_ALLOCATION__=",
                "nodefs_post_available_bytes": "__V23_NODEFS_POST_AVAILABLE__=",
                "nodefs_live_available_bytes": "__V23_NODEFS_LIVE_AVAILABLE__=",
            }
            live = {}
            for name, marker in markers.items():
                values = [
                    line.removeprefix(marker) for line in probe.splitlines()
                    if line.startswith(marker)
                ]
                if len(values) != 1 or not values[0].isdigit():
                    raise PilotError("F4 diskfill live probe is malformed")
                live[name] = int(values[0])
            if any(
                live[name] != result[name]
                for name in (
                    "nodefs_device", "diskfill_work_inode", "diskfill_inode",
                    "diskfill_size_bytes", "diskfill_allocated_blocks",
                    "nodefs_capacity_bytes", "nodefs_injection_available_bytes",
                    "diskfill_allocated_bytes", "nodefs_post_available_bytes",
                )
            ):
                raise PilotError("F4 diskfill live identity mismatch")
            low_disk = (
                live["nodefs_live_available_bytes"] * 100
                < live["nodefs_capacity_bytes"] * 10
            )
            safe_floor = (
                live["nodefs_live_available_bytes"] * 100
                >= live["nodefs_capacity_bytes"]
                * F4_T4_SAFETY_FLOOR_PERCENT
            )
            ready_status = conditions.get("Ready")
            disk_status = conditions.get("DiskPressure")
            condition_observed = (
                ready_status != "True" or disk_status == "True"
            )
            if not safe_floor or (not condition_observed and not low_disk):
                raise PilotError("F4 nodefs available threshold was not crossed")
            details.update({
                "disk_pressure_observed": disk_status == "True",
                "ready_status": ready_status,
                "disk_pressure_status": disk_status,
                "nodefs_injection_threshold_verified": True,
                "nodefs_injection_post_available_bytes": (
                    result["nodefs_post_available_bytes"]
                ),
                "nodefs_injection_allocation_bytes": (
                    result["diskfill_allocated_bytes"]
                ),
                "diskfill_nonce": result["diskfill_nonce"],
                "diskfill_work_inode": result["diskfill_work_inode"],
                "diskfill_inode": result["diskfill_inode"],
                "diskfill_allocated_blocks": result["diskfill_allocated_blocks"],
                "nodefs_live_threshold_verified": low_disk,
                "nodefs_available_bytes": live["nodefs_live_available_bytes"],
                "nodefs_capacity_bytes": live["nodefs_capacity_bytes"],
                "treatment_verified": True,
                "treatment_basis": (
                    "node-notready"
                    if ready_status != "True"
                    else (
                        "diskpressure-condition"
                        if disk_status == "True"
                        else "nodefs-available-threshold"
                    )
                ),
            })
        elif not disrupted:
            raise PilotError("F4 node disruption was not observed")
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
                probe = self._find_container(
                    deployment, self._receipt_container(result, target)
                ).get("readinessProbe", {})
                valid = probe.get("httpGet", {}).get("path") == "/nonexistent"
        if not valid:
            raise PilotError("F8 endpoint treatment is absent")
        return {"endpoint_treatment": True}

    def _validate_f9(self, trial: int, target: str, result: dict) -> dict:
        deployment = self.load("deployment", target, "boutique")
        container = self._find_container(
            deployment, self._receipt_container(result, target)
        )
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
